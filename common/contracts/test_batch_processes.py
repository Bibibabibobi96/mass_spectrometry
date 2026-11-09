"""Installed batch transport with controlled PS telemetry and real inert Python children."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.manifest_records import file_record
from msplatform.execution.processes import ProcessExecutionError,run_observed_process_group
from msplatform.execution.resources import resource_path
from msplatform.execution.simion_dispatch import plan_simion_dispatch,prepare_fixed_partition_dispatch
from msplatform.execution.simion_dispatch import FORMAL_OBSERVATION_SECONDS,LAUNCH_STAGGER_SECONDS


@unittest.skipUnless(os.name=='nt' and shutil.which('pwsh'),'Windows PowerShell required')
class BatchProcessTests(unittest.TestCase):
    def _inert_payload_code(self):
        # Test-only publication rendezvous;600s expiry is failure, never readiness.
        return r'''import sys,time,json,os,hashlib
from pathlib import Path
def _wait_publication(protocol,facts,*,deadline,monotonic=time.monotonic,poll=lambda:time.sleep(.1),clock=time.time_ns):
    mode=protocol["mode"];publication=Path(protocol["path"])
    while True:
        if monotonic()>=deadline:
            raise TimeoutError("INERT_"+mode.upper()+"_PUBLICATION_NOT_OBSERVED_WITHIN_600S")
        if publication.is_file():
            raw=publication.read_bytes()
            record=json.loads(raw.decode("utf-8-sig"))
            if mode=="replan":
                assert record["particle_count"]==3
                assert record["waves"][0]["batches"]==protocol["fixed_batches"]
                kind=record["estimation"]["kind"]
                if kind=="formal_first_batch_observation":
                    poll()
                    continue
                assert kind=="observed_formal_batch"
                assert record["estimation"]["recovered_missing_observation_completed"] is True
                assert record["estimation"]["observed_missing_batch_index"]==1
                capacity=record["limits"]["maximum_concurrency"]
                assert type(capacity) is int and capacity>=1
                assert record["limits"]["formal_observation_seconds"]==protocol["formal_observation_seconds"]
                assert record["limits"]["launch_stagger_seconds"]==protocol["launch_stagger_seconds"]
                facts["replan"]=record
                facts["replan_sha256"]=hashlib.sha256(raw).hexdigest()
                facts["replan_observed_ns"]=clock()
                facts["causal_events"].append("completed_replan_validated")
            else:
                observation=record["observation"]
                assert record["operation_id"]=="failure" and record["host_release"] is None
                assert type(observation["exit_code"]) is int and observation["exit_code"]==7
                for key in ("root_process_id","root_process_started_at_utc_ticks"):
                    assert type(observation[key]) is int and observation[key]>0
                facts["failure_receipt"]=record
                facts["failure_receipt_observed_ns"]=clock()
                facts["failure_receipt_sha256"]=hashlib.sha256(raw).hexdigest()
                facts["causal_events"].append("peer_exit_receipt_validated")
            return record
        poll()

def _main():
    started_monotonic=time.monotonic()
    data=Path(sys.argv[1]);target=Path(sys.argv[2])
    protocol=json.loads(sys.argv[5]);mode=protocol["mode"]
    clock_mode=protocol.get("diagnostic_clock_mode","actual")
    clock_values=iter(protocol.get("diagnostic_clock_values",[]))
    clock=time.time_ns if clock_mode=="actual" else lambda:next(clock_values)
    facts=dict(pid=os.getpid(),actual_python_pid=os.getpid(),executable=sys.executable,
               diagnostic_clock_mode=clock_mode,started_ns=clock(),causal_events=[])
    try:
        blocked=False
        try:data.write_bytes(b"UNSAFE")
        except PermissionError:blocked=True
        facts["locked"]=blocked
        target.write_text(json.dumps(facts),encoding="utf-8")
        print("INERT_PYTHON_STARTED",flush=True)
        if mode=="sleep":
            time.sleep(float(sys.argv[3]))
            facts["causal_events"].append("sleep_completed")
        elif mode in ("replan","peer_receipt"):
            _wait_publication(protocol,facts,deadline=started_monotonic+600,clock=clock)
            still_blocked=False
            try:data.write_bytes(b"UNSAFE_AFTER_PUBLICATION")
            except PermissionError:still_blocked=True
            facts["locked_after_publication"]=still_blocked
            assert still_blocked,"Immutable input guard ended before live payload"
            facts["causal_events"].append("immutable_write_denied_after_"+("peer_receipt" if mode=="peer_receipt" else "replan"))
        else:
            raise ValueError("Unknown inert fixture protocol")
    except BaseException as error:
        facts["protocol_error"]=type(error).__name__+": "+str(error)
        raise
    finally:
        facts["causal_events"].append("finally_entered")
        facts["ended_ns"]=clock()
        target.write_text(json.dumps(facts),encoding="utf-8")
    print("INERT_PYTHON_FINISHED",flush=True)
    sys.exit(int(sys.argv[4]))
if __name__=="__main__":_main()
'''

    def _publish_batch_fixture_facts(self,root,receipt,dispatch_name,prefix):
        # Preserve small actual facts before assertions and TemporaryDirectory cleanup.
        evidence=dict(receipt=receipt,files={},diagnostic_errors=[])
        names=[name+suffix for name in ('healthy','failure','pending')
               for suffix in ('.json','.receipt.json')]
        for name in names+[dispatch_name]:
            path=root/name
            try:
                if not path.is_file():
                    evidence['files'][name]=dict(exists=False)
                    continue
                raw=path.read_bytes()
                evidence['files'][name]=dict(exists=True,bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    text=raw[:65536].decode('utf-8',errors='backslashreplace'),
                    truncated=len(raw)>65536)
            except OSError as error:
                evidence['diagnostic_errors'].append(name+': '+str(error))
        print(prefix+json.dumps(evidence,sort_keys=True),flush=True)

    def _real_simion_role(self,root,*,failure):
        """Actual heavy admission; Python payloads are not native solver evidence."""
        observation_seconds = FORMAL_OBSERVATION_SECONDS
        self.assertTrue(os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'shared public GATE required')
        context=ExecutionContext(workspace=root,python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')),tools={},
            host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
            policy_path=resource_path('host_resource_policy.json'))
        names=('batch_process_owner.ps1','simion_dispatch_support.ps1','resource_process_support.ps1',
               'host_execution_lease.ps1','payload_file_support.ps1','host_resource_policy.json')
        before={name:resource_path(name).read_bytes() for name in names}
        data=root/'immutable.bin';data.write_bytes(b'INERT_NOT_PA_REAL_ROLE')
        code=self._inert_payload_code()
        compile(code,'inert-real-role-payload','exec')
        specifications=[]
        batches=[dict(index=index,count=1,particle_id_min=index,particle_id_max=index,
                      simion_particle_id_offset=index-1) for index in range(1,4)]
        for index,name in enumerate(('healthy','failure','pending'),1):
            # Real policy may serialize; completed replan does not need a second lane.
            delay=LAUNCH_STAGGER_SECONDS if index==1 else .2
            protocol=(dict(mode='replan',path=str(root/'actual.dispatch.json'),fixed_batches=batches,
                           formal_observation_seconds=FORMAL_OBSERVATION_SECONDS,
                           launch_stagger_seconds=LAUNCH_STAGGER_SECONDS)
                      if failure and name=='healthy' else dict(mode='sleep'))
            specifications.append(dict(operation_id=name,executable=Path(sys.executable),
                arguments=['-I','-B','-c',code,str(data),str(root/(name+'.json')),str(delay),
                           '7' if failure and name=='failure' else '0',json.dumps(protocol)],working_directory=root,
                stdout_path=root/(name+'.out'),stderr_path=root/(name+'.err'),receipt_path=root/(name+'.receipt.json'),
                environment={},scheduler_batch=batches[index-1]))
        original=plan_simion_dispatch(dict(solver='SIMION',field_kind='electrostatic',particle_count=3,
            independent_particles=True),[])
        fixed=dict(role='simion_single_wave_particle_batch_plan',coverage='complete_population',particle_count=3,
            batches=[row['scheduler_batch'] for row in specifications])
        plan=prepare_fixed_partition_dispatch(original,fixed,[1,2,3])
        self.assertEqual(plan['limits']['formal_observation_seconds'],FORMAL_OBSERVATION_SECONDS)
        self.assertEqual(plan['limits']['launch_stagger_seconds'],LAUNCH_STAGGER_SECONDS)
        self.assertTrue(plan['estimation']['recovered_missing_observation'])
        self.assertEqual(plan['estimation']['kind'],'formal_first_batch_observation')
        # Contract rejection is checked before any actual bridge/native role.
        with patch('msplatform.execution.processes.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                run_observed_process_group(context,specifications=[specifications[0],specifications[0]],dispatch_plan=plan,
                    run_directory=root,usage_path=root/'invalid.json',role='SIMION',stage='flight',run_id='inert-role-preflight')
            launch.assert_not_called()
        # The outer software GATE is not a vendor grant. Request an independent
        # real SIMION flight lease on the SAME shared ledger, without inheritance.
        clear={name:'' for name in ('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN',
            'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE')}
        receipt=None
        try:
            with patch.dict(os.environ,clear):
                kwargs=dict(specifications=specifications,dispatch_plan=plan,run_directory=root,usage_path=root/'actual.json',
                    role='SIMION',stage='flight',run_id='inert-real-role-failure' if failure else 'inert-real-role-success',
                    formal_operation_id='healthy',immutable_input_records=[file_record(data,'solver_native_binary')])
                if failure:
                    with self.assertRaisesRegex(ProcessExecutionError,'batch wave failed') as caught:
                        try:
                            run_observed_process_group(context,**kwargs)
                        except ProcessExecutionError as error:
                            receipt=error.receipt
                            raise
                    receipt=caught.exception.receipt
                else:receipt=run_observed_process_group(context,**kwargs)
        except ProcessExecutionError as error:
            receipt=error.receipt
            raise
        finally:
            self._publish_batch_fixture_facts(root,receipt,'actual.dispatch.json','UNMODIFIED_SIMION_ROLE_RAW_FACTS=')
        self.assertEqual(receipt['host_release'],dict(inherited=False,token=receipt['host_release']['token'],
            error=None,result=dict(status='released',token=receipt['host_release']['token'])))
        self.assertTrue(receipt['host_release']['token'])
        children={}
        for name,observation in receipt['observations'].items():
            child=json.loads((root/(name+'.json')).read_text(encoding='utf-8'))
            self.assertTrue(child['locked']);self.assertGreater(child['actual_python_pid'],0)
            self.assertEqual(Path(child['executable']).resolve(),Path(sys.executable).resolve())
            self.assertNotIn('protocol_error',child)
            self.assertEqual(child['causal_events'][-1],'finally_entered')
            self.assertGreater(observation['root_process_id'],0)
            self.assertGreater(observation['root_process_started_at_utc_ticks'],0)
            children[name]=child
        self.assertEqual(data.read_bytes(),b'INERT_NOT_PA_REAL_ROLE')
        data.write_bytes(b'RELEASED_AFTER_ACTUAL_EXIT')
        actual=json.loads((root/'actual.dispatch.json').read_text(encoding='utf-8'))
        self.assertEqual(actual['estimation']['kind'],'observed_formal_batch')
        self.assertEqual(actual['waves'][0]['batches'],fixed['batches'])
        self.assertEqual(actual['limits']['launch_stagger_seconds'],LAUNCH_STAGGER_SECONDS)
        for name,raw in before.items():self.assertEqual(resource_path(name).read_bytes(),raw)
        if failure:
            self.assertEqual(receipt['observations']['failure']['exit_code'],7)
            self.assertEqual(receipt['observations']['healthy']['exit_code'],0)
            self.assertEqual(receipt['not_started'],['pending'])
            self.assertFalse((root/'pending.json').exists())
            self.assertEqual(children['healthy']['replan'],actual)
            self.assertEqual(children['healthy']['replan_sha256'],hashlib.sha256((root/'actual.dispatch.json').read_bytes()).hexdigest())
            self.assertTrue(children['healthy']['locked_after_publication'])
            self.assertEqual(children['healthy']['causal_events'],[
                'completed_replan_validated','immutable_write_denied_after_replan','finally_entered'])
        else:
            self.assertEqual(set(receipt['observations']),{'healthy','failure','pending'})
            self.assertTrue(all(row['exit_code']==0 for row in receipt['observations'].values()))
            self.assertEqual(receipt['not_started'],[])
        print('REAL_SIMION_ROLE_INERT_PROOF='+json.dumps(dict(native_qualification=False,
            role='SIMION',stage='flight',failure_case=failure,observations=receipt['observations'],
            attempts=receipt['attempts'],host_release=receipt['host_release'],children=children,
            not_started=receipt['not_started'],actual_estimation=actual['estimation'],
            launch_stagger_seconds=LAUNCH_STAGGER_SECONDS,guard_write_after_exit=True,
            unmodified_resources=True,observation_seconds=observation_seconds,
            scope='real_admission_replan_failure_pending_guard_release',
            live_overlap_claimed=False),sort_keys=True))

    def test_real_simion_role_inert_success_real_admission_and_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            self._real_simion_role(Path(directory),failure=False)

    def test_unmodified_simion_role_failure_replans_stops_pending_and_releases_guards(self):
        """Real admission/failure with the unmodified formal observation window."""
        with tempfile.TemporaryDirectory() as directory:
            self._real_simion_role(Path(directory),failure=True)

    def fixture(self,root,*,fault=None,clock_mode="actual"):
        self.assertTrue(os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'normal shared GATE required')
        context=ExecutionContext(workspace=root,python_executable=Path(sys.executable),powershell_executable=Path(shutil.which('pwsh')),
            tools={},host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),policy_path=resource_path('host_resource_policy.json'))
        data=root/'immutable.bin';data.write_bytes(b'INERT_NOT_PA')
        owner=root/'owner';owner.mkdir()
        names=('batch_process_owner.ps1','simion_dispatch_support.ps1','resource_process_support.ps1','host_execution_lease.ps1','payload_file_support.ps1')
        before={name:resource_path(name).read_bytes() for name in names}
        for name,body in before.items():
            text=body.decode('utf-8')
            if name=='batch_process_owner.ps1':
                marker=". (Join-Path $PSScriptRoot 'simion_dispatch_support.ps1')"
                # Explicit test-only role/CPU seams. Installed heavy policy is NOT changed.
                text=text.replace(marker,marker+"\nfunction Assert-HostResourceHeavyStage {}\nfunction Get-SystemCpuPercent {return 0}\n")
            (owner/name).write_text(text,encoding='utf-8',newline='\n')
        plan=plan_simion_dispatch(dict(solver='SIMION',field_kind='electrostatic',particle_count=3,independent_particles=True),[],
            available_memory_bytes=16*1024**3,total_physical_memory_bytes=32*1024**3,logical_processors=4)
        plan['estimation']=dict(kind='exact_resource_profile',per_process_memory_budget_bytes=1024**2,per_process_cpu_percent=1.)
        plan['limits']['maximum_concurrency']=2
        plan['limits']['launch_stagger_seconds']=1  # bounded declared fixture cadence
        specs=[]
        for index,name in enumerate(('healthy','failure','pending'),1):
            code=self._inert_payload_code()
            delay=3 if name=='healthy' else .2
            exit_code=7 if fault=='exit7' and name=='failure' else 0
            protocol=(dict(mode='peer_receipt',path=str(root/'failure.receipt.json'))
                      if fault=='exit7' and name=='healthy' else dict(mode='sleep'))
            if fault=='exit7' and name=='healthy':
                protocol['diagnostic_clock_mode']=clock_mode
                if clock_mode!='actual':
                    protocol['diagnostic_clock_values']=([100,100,100] if clock_mode=='equal' else [300,200,100])
            specs.append(dict(operation_id=name,executable=Path(sys.executable),arguments=['-I','-c',code,str(data),str(root/(name+'.json')),str(delay),str(exit_code),json.dumps(protocol)],
                working_directory=root,stdout_path=root/(name+'.out'),stderr_path=root/(name+'.err'),receipt_path=root/(name+'.receipt.json'),
                environment={},scheduler_batch=dict(index=index,count=1,particle_id_min=index,particle_id_max=index)))
        return context,data,owner,before,plan,specs

    def run_fixture(self,root,*,fault=None,clock_mode="actual"):
        context,data,folder,before,plan,specs=self.fixture(root,fault=fault,clock_mode=clock_mode)
        real_resource=resource_path
        receipt=None
        try:
            with patch('msplatform.execution.processes.resource_path',side_effect=lambda name:folder/name if name=='batch_process_owner.ps1' else real_resource(name)):
                if fault=='exit7':
                    with self.assertRaisesRegex(ProcessExecutionError,'batch wave failed') as caught:
                        try:
                            run_observed_process_group(context,specifications=specs,dispatch_plan=plan,run_directory=root,usage_path=root/'wave.json',
                                role='GATE',stage='unclassified',run_id='inert-batch',immutable_input_records=[file_record(data,'solver_native_binary')])
                        except ProcessExecutionError as error:
                            receipt=error.receipt
                            raise
                    receipt=caught.exception.receipt
                else:
                    receipt=run_observed_process_group(context,specifications=specs,dispatch_plan=plan,run_directory=root,usage_path=root/'wave.json',
                        role='GATE',stage='unclassified',run_id='inert-batch',immutable_input_records=[file_record(data,'solver_native_binary')])
        except ProcessExecutionError as error:
            receipt=error.receipt
            raise
        finally:
            self._publish_batch_fixture_facts(root,receipt,'wave.dispatch.json','CONTROLLED_BATCH_RAW_FACTS=')
        for name,body in before.items():self.assertEqual(resource_path(name).read_bytes(),body)
        self.assertEqual(data.read_bytes(),b'INERT_NOT_PA')
        data.write_bytes(b'RELEASED')  # real final guard release
        for name,observation in receipt['observations'].items():
            child=json.loads((root/(name+'.json')).read_text())
            self.assertTrue(child['locked'])
            self.assertGreater(observation['root_process_id'],0)
            self.assertGreater(observation['root_process_started_at_utc_ticks'],0)
            self.assertTrue((root/(name+'.receipt.json')).is_file())
        return receipt

    def test_actual_inert_group_preserves_real_identities_guards_and_zero_native_policy_change(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt=self.run_fixture(Path(directory))
            self.assertEqual(set(receipt['observations']),{'healthy','failure','pending'})
            self.assertEqual(receipt['not_started'],[])
            self.assertEqual([row['exit_code'] for row in receipt['observations'].values()],[0,0,0])
            self.assertEqual(len(receipt['attempts']),3)

    def test_failed_child_stops_pending_and_healthy_sibling_naturally_drains(self):
        # Wall timestamps are diagnostic only; receipt/guard/finally establish order.
        for clock_mode in ('actual','equal','backward'):
            with self.subTest(diagnostic_clock_mode=clock_mode):
                with tempfile.TemporaryDirectory() as directory:
                    root=Path(directory);receipt=self.run_fixture(root,fault='exit7',clock_mode=clock_mode)
                    self.assertEqual(receipt['observations']['healthy']['exit_code'],0)
                    self.assertEqual(receipt['observations']['failure']['exit_code'],7)
                    self.assertEqual(receipt['not_started'],['pending'])
                    self.assertFalse((root/'pending.json').exists())
                    self.assertEqual(len(receipt['attempts']),2)
                    children={name:json.loads((root/(name+'.json')).read_text(encoding='utf-8'))
                              for name in ('healthy','failure')}
                    observed=json.loads((root/'failure.receipt.json').read_text(encoding='utf-8'))
                    self.assertEqual(children['healthy']['failure_receipt'],observed)
                    self.assertEqual(observed['observation'],receipt['observations']['failure'])
                    self.assertTrue(children['healthy']['locked_after_publication'])
                    self.assertEqual(children['healthy']['failure_receipt_sha256'],
                        hashlib.sha256((root/'failure.receipt.json').read_bytes()).hexdigest())
                    self.assertNotIn('protocol_error',children['healthy'])
                    self.assertEqual(children['healthy']['diagnostic_clock_mode'],clock_mode)
                    self.assertEqual(children['healthy']['causal_events'],[
                        'peer_exit_receipt_validated','immutable_write_denied_after_peer_receipt','finally_entered'])
                    if clock_mode!='actual':
                        self.assertEqual([children['healthy'][key] for key in
                            ('started_ns','failure_receipt_observed_ns','ended_ns')],
                            [100,100,100] if clock_mode=='equal' else [300,200,100])

    def test_shared_payload_publication_protocol_rejects_missing_and_malformed_receipts(self):
        # Parser-only synthetic NON_NATIVE inputs; real process provenance is tested above.
        from msplatform.execution.recorded_file_removal import write_json_atomic
        namespace={'__name__':'inert_protocol_definitions'}
        exec(compile(self._inert_payload_code(),'shared-inert-protocol','exec'),namespace)
        wait=namespace['_wait_publication']
        valid=dict(operation_id='failure',host_release=None,observation=dict(
            exit_code=7,root_process_id=123,root_process_started_at_utc_ticks=456),
            test_scope='SYNTHETIC_NON_NATIVE')
        for case in ('missing','delayed','malformed','wrong_operation','bool_exit','zero_pid','missing_birth'):
            with self.subTest(protocol_case=case),tempfile.TemporaryDirectory() as directory:
                publication=Path(directory)/'synthetic.receipt.json'
                record=json.loads(json.dumps(valid));facts={'causal_events':[]};ticks=[0];polls=[]
                if case=='wrong_operation':record['operation_id']='other'
                if case=='bool_exit':record['observation']['exit_code']=True
                if case=='zero_pid':record['observation']['root_process_id']=0
                if case=='missing_birth':del record['observation']['root_process_started_at_utc_ticks']
                if case=='malformed':publication.write_text('{',encoding='utf-8')
                elif case not in ('missing','delayed'):write_json_atomic(publication,record)
                def poll():
                    polls.append('publication_absent_observed')
                    self.assertFalse(publication.exists())
                    ticks[0]+=1
                    if case=='delayed':write_json_atomic(publication,record)
                kwargs=dict(deadline=2,monotonic=lambda:ticks[0],poll=poll,clock=lambda:0)
                if case=='delayed':
                    self.assertEqual(wait(dict(mode='peer_receipt',path=str(publication)),facts,**kwargs),record)
                    self.assertEqual(polls,['publication_absent_observed'])
                    self.assertEqual(facts['causal_events'],['peer_exit_receipt_validated'])
                else:
                    error=TimeoutError if case=='missing' else (json.JSONDecodeError if case=='malformed' else (KeyError if case=='missing_birth' else AssertionError))
                    with self.assertRaises(error):
                        wait(dict(mode='peer_receipt',path=str(publication)),facts,**kwargs)
                    self.assertEqual(facts['causal_events'],[])
                    if case=='missing':self.assertEqual(ticks[0],2)

    def test_invalid_metadata_and_wrong_hash_do_not_launch_inert_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);context,data,folder,before,plan,specs=self.fixture(root)
            with patch('msplatform.execution.processes.subprocess.Popen') as launch:
                for changed in ([specs[0],specs[0]],[dict(specs[0],arguments='not argv')],
                                [dict(specs[0],stdout_path=Path('relative.out'))]):
                    with self.assertRaises(ValueError):
                        run_observed_process_group(context,specifications=changed,dispatch_plan=plan,run_directory=root,usage_path=root/'bad.json',
                            role='GATE',stage='unclassified',run_id='inert-batch')
                launch.assert_not_called()
            real_resource=resource_path
            with patch('msplatform.execution.processes.resource_path',side_effect=lambda name:folder/name if name=='batch_process_owner.ps1' else real_resource(name)):
                with self.assertRaisesRegex(ProcessExecutionError,'SHA256 differs') as caught:
                    run_observed_process_group(context,specifications=specs,dispatch_plan=plan,run_directory=root,usage_path=root/'wrong.json',
                        role='GATE',stage='unclassified',run_id='inert-batch',immutable_input_records=[dict(file_record(data,'solver_native_binary'),sha256='F'*64)])
            self.assertEqual(caught.exception.receipt['observations'],{})
            self.assertFalse(any((root/(name+'.json')).exists() for name in ('healthy','failure','pending')))

    def test_fixed_first_formal_observation_is_real_retained_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);context,data,folder,before,_,specs=self.fixture(root)
            original=plan_simion_dispatch(dict(solver='SIMION',field_kind='electrostatic',particle_count=3,independent_particles=True),[],
                available_memory_bytes=16*1024**3,total_physical_memory_bytes=32*1024**3,logical_processors=4)
            fixed=dict(role='simion_single_wave_particle_batch_plan',particle_count=3,coverage='complete_population',batches=[dict(row['scheduler_batch'],simion_particle_id_offset=index) for index,row in enumerate(specs)])
            plan=prepare_fixed_partition_dispatch(original,fixed,[1,2,3])
            plan['limits']['launch_stagger_seconds']=1
            real_resource=resource_path
            with patch('msplatform.execution.processes.resource_path',side_effect=lambda name:folder/name if name=='batch_process_owner.ps1' else real_resource(name)):
                receipt=run_observed_process_group(context,specifications=specs,dispatch_plan=plan,run_directory=root,usage_path=root/'formal.json',
                    role='GATE',stage='unclassified',run_id='inert-formal',formal_operation_id='healthy',immutable_input_records=[file_record(data,'solver_native_binary')])
            self.assertEqual(len(receipt['attempts']),3)
            actual=json.loads((root/'formal.dispatch.json').read_text())
            self.assertEqual(actual['estimation']['kind'],'observed_formal_batch')
            self.assertEqual(actual['particle_count'],3)
            self.assertEqual(actual['waves'][0]['batches'],fixed['batches'])

    def test_runsession_records_actual_subset_common_release_and_preserves_primary(self):
        from msplatform.execution.run_session import RunSession
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);context,data,folder,before,plan,specs=self.fixture(root)
            (root/'run_config.json').write_text('{"inputs":{}}',encoding='utf-8')
            (root/'logs').mkdir()
            def make(name):
                return RunSession(context=context,artifact_root=root,run_id=name,project='instrument_assembly',mode='sim',
                    package={'run_dir':str(root),'artifact_run_dir':str(root)},capacity_session={},execution_request=root/'request.json',
                    result_path=root/'result.json',expected_operation_ids=('healthy','failure','pending'),operation_dependencies={})
            group=[{key:row[key] for key in ('operation_id','executable','arguments','scheduler_batch')} for row in specs]
            release=dict(inherited=True,token='fixture-shared-release',result=None,error=None)
            receipt=dict(observations={name:dict(exit_code=code,root_process_id=1000+i,root_process_started_at_utc_ticks=2000+i)
                for i,(name,code) in enumerate((('healthy',0),('failure',7)))},attempts=[],not_started=['pending'],
                error={'message':'ORIGINAL_GROUP_FAILURE'},host_release=release)
            session=make('failure')
            with patch.object(RunSession,'renew_capacity'),patch('msplatform.execution.run_session.run_observed_process_group',
                    side_effect=ProcessExecutionError('ORIGINAL_GROUP_FAILURE',receipt)):
                with self.assertRaisesRegex(ProcessExecutionError,'ORIGINAL_GROUP_FAILURE'):
                    session.run_process_group(group,dispatch_plan=plan,group_id='failure',role='GATE',stage='unclassified')
            self.assertTrue(session.writers_stopped)
            self.assertEqual(session._completed,{'healthy':0,'failure':7})
            self.assertNotIn('pending',session._completed)
            self.assertEqual(len(session.operations),2)
            self.assertEqual(len(session.resource_releases),1)
            self.assertEqual({row['resource_release_id'] for row in session.operations},{'host-resource-1'})
            self.assertEqual(json.loads((root/'logs/group_failure.process.json').read_text()),receipt)
            failed=make('secondary')
            with patch.object(RunSession,'renew_capacity'),patch('msplatform.execution.run_session.run_observed_process_group',
                    side_effect=ProcessExecutionError('ORIGINAL_GROUP_FAILURE',receipt)),patch.object(
                    RunSession,'_record_process',side_effect=OSError('SECONDARY_RECORD_FAILURE')):
                with self.assertRaisesRegex(ProcessExecutionError,'ORIGINAL_GROUP_FAILURE') as caught:
                    failed.run_process_group(group,dispatch_plan=plan,group_id='secondary',role='GATE',stage='unclassified')
            self.assertIn('SECONDARY_RECORD_FAILURE',' '.join(caught.exception.__notes__))
            self.assertTrue((root/'logs/group_secondary.process.json').exists())
            no_launch=make('no_launch')
            with patch.object(RunSession,'renew_capacity'),patch('msplatform.execution.run_session.run_observed_process_group',
                    side_effect=ValueError('PREFLIGHT_BAD_SPEC')):
                with self.assertRaisesRegex(ValueError,'PREFLIGHT_BAD_SPEC'):
                    no_launch.run_process_group(group,dispatch_plan=plan,group_id='no_launch',role='GATE',stage='unclassified')
            self.assertTrue(no_launch.writers_stopped)
            self.assertEqual(no_launch.operations,[])


if __name__=='__main__':unittest.main()
