"""Installed batch transport with controlled PS telemetry and real inert Python children."""
import json
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
    def _unmodified_simion_role(self,root,*,failure):
        """Actual heavy admission; Python payloads are not native solver evidence."""
        self.assertTrue(os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'shared public GATE required')
        context=ExecutionContext(workspace=root,python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')),tools={},
            host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
            policy_path=resource_path('host_resource_policy.json'))
        names=('batch_process_owner.ps1','simion_dispatch_support.ps1','resource_process_support.ps1',
               'host_execution_lease.ps1','payload_file_support.ps1','host_resource_policy.json')
        before={name:resource_path(name).read_bytes() for name in names}
        data=root/'immutable.bin';data.write_bytes(b'INERT_NOT_PA_REAL_ROLE')
        code=(
            'import sys,time,json,os;from pathlib import Path;data=Path(sys.argv[1]);blocked=False\n'
            'try:data.write_bytes(b"UNSAFE")\n'
            'except PermissionError:blocked=True\n'
            'facts=dict(actual_python_pid=os.getpid(),executable=sys.executable,locked=blocked,started_ns=time.time_ns());'
            'target=Path(sys.argv[2]);target.write_text(json.dumps(facts));'
            'print("INERT_PYTHON_STARTED",flush=True);time.sleep(float(sys.argv[3]));'
            'facts["ended_ns"]=time.time_ns();target.write_text(json.dumps(facts));'
            'print("INERT_PYTHON_FINISHED",flush=True);sys.exit(int(sys.argv[4]))'
        )
        compile(code,'inert-real-role-payload','exec')
        specifications=[]
        for index,name in enumerate(('healthy','failure','pending'),1):
            # Keep the real first observation alive through its normal window
            # and two unchanged staggers so the failure can precede healthy exit.
            delay=FORMAL_OBSERVATION_SECONDS+2*LAUNCH_STAGGER_SECONDS+2 if failure and index==1 else (LAUNCH_STAGGER_SECONDS if index==1 else .2)
            specifications.append(dict(operation_id=name,executable=Path(sys.executable),
                arguments=['-I','-B','-c',code,str(data),str(root/(name+'.json')),str(delay),
                           '7' if failure and name=='failure' else '0'],working_directory=root,
                stdout_path=root/(name+'.out'),stderr_path=root/(name+'.err'),receipt_path=root/(name+'.receipt.json'),
                environment={},scheduler_batch=dict(index=index,count=1,particle_id_min=index,
                    particle_id_max=index,simion_particle_id_offset=index-1)))
        original=plan_simion_dispatch(dict(solver='SIMION',field_kind='electrostatic',particle_count=3,
            independent_particles=True),[])
        fixed=dict(role='simion_single_wave_particle_batch_plan',coverage='complete_population',particle_count=3,
            batches=[row['scheduler_batch'] for row in specifications])
        plan=prepare_fixed_partition_dispatch(original,fixed,[1,2,3])
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
        with patch.dict(os.environ,clear):
            kwargs=dict(specifications=specifications,dispatch_plan=plan,run_directory=root,usage_path=root/'actual.json',
                role='SIMION',stage='flight',run_id='inert-real-role-failure' if failure else 'inert-real-role-success',
                formal_operation_id='healthy',immutable_input_records=[file_record(data,'solver_native_binary')])
            if failure:
                with self.assertRaisesRegex(ProcessExecutionError,'batch wave failed') as caught:
                    run_observed_process_group(context,**kwargs)
                receipt=caught.exception.receipt
            else:receipt=run_observed_process_group(context,**kwargs)
        self.assertEqual(receipt['host_release'],dict(inherited=False,token=receipt['host_release']['token'],
            error=None,result=dict(status='released',token=receipt['host_release']['token'])))
        self.assertTrue(receipt['host_release']['token'])
        children={}
        for name,observation in receipt['observations'].items():
            child=json.loads((root/(name+'.json')).read_text(encoding='utf-8'))
            self.assertTrue(child['locked']);self.assertGreater(child['actual_python_pid'],0)
            self.assertEqual(Path(child['executable']).resolve(),Path(sys.executable).resolve())
            self.assertGreater(child['ended_ns'],child['started_ns'])
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
            self.assertGreater(children['healthy']['ended_ns'],children['failure']['ended_ns'])
        else:
            self.assertEqual(set(receipt['observations']),{'healthy','failure','pending'})
            self.assertTrue(all(row['exit_code']==0 for row in receipt['observations'].values()))
            self.assertEqual(receipt['not_started'],[])
        print('UNMODIFIED_SIMION_ROLE_INERT_PROOF='+json.dumps(dict(native_qualification=False,
            role='SIMION',stage='flight',failure_case=failure,observations=receipt['observations'],
            attempts=receipt['attempts'],host_release=receipt['host_release'],children=children,
            not_started=receipt['not_started'],actual_estimation=actual['estimation'],
            launch_stagger_seconds=LAUNCH_STAGGER_SECONDS,guard_write_after_exit=True,
            unmodified_resources=True),sort_keys=True))

    def test_unmodified_simion_role_inert_success_real_admission_and_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            self._unmodified_simion_role(Path(directory),failure=False)

    def test_unmodified_simion_role_failure_drains_live_sibling_and_stops_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            self._unmodified_simion_role(Path(directory),failure=True)

    def fixture(self,root,*,fault=None):
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
            code='import sys,time,json;from pathlib import Path;p=Path(sys.argv[1]);blocked=False\ntry:p.write_bytes(b"BAD")\nexcept PermissionError:blocked=True\nPath(sys.argv[2]).write_text(json.dumps(dict(pid=__import__("os").getpid(),locked=blocked)));time.sleep(float(sys.argv[3]));sys.exit(int(sys.argv[4]))'
            delay=3 if name=='healthy' else .2
            exit_code=7 if fault=='exit7' and name=='failure' else 0
            specs.append(dict(operation_id=name,executable=Path(sys.executable),arguments=['-I','-c',code,str(data),str(root/(name+'.json')),str(delay),str(exit_code)],
                working_directory=root,stdout_path=root/(name+'.out'),stderr_path=root/(name+'.err'),receipt_path=root/(name+'.receipt.json'),
                environment={},scheduler_batch=dict(index=index,count=1,particle_id_min=index,particle_id_max=index)))
        return context,data,owner,before,plan,specs

    def run_fixture(self,root,*,fault=None):
        context,data,folder,before,plan,specs=self.fixture(root,fault=fault)
        real_resource=resource_path
        with patch('msplatform.execution.processes.resource_path',side_effect=lambda name:folder/name if name=='batch_process_owner.ps1' else real_resource(name)):
            if fault=='exit7':
                with self.assertRaisesRegex(ProcessExecutionError,'batch wave failed') as caught:
                    run_observed_process_group(context,specifications=specs,dispatch_plan=plan,run_directory=root,usage_path=root/'wave.json',
                        role='GATE',stage='unclassified',run_id='inert-batch',immutable_input_records=[file_record(data,'solver_native_binary')])
                receipt=caught.exception.receipt
            else:
                receipt=run_observed_process_group(context,specifications=specs,dispatch_plan=plan,run_directory=root,usage_path=root/'wave.json',
                    role='GATE',stage='unclassified',run_id='inert-batch',immutable_input_records=[file_record(data,'solver_native_binary')])
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
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);receipt=self.run_fixture(root,fault='exit7')
            self.assertEqual(receipt['observations']['healthy']['exit_code'],0)
            self.assertEqual(receipt['observations']['failure']['exit_code'],7)
            self.assertEqual(receipt['not_started'],['pending'])
            self.assertFalse((root/'pending.json').exists())
            self.assertEqual(len(receipt['attempts']),2)

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
