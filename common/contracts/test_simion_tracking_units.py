"""Ordinal/full-mother recovery and actual original-owner inert process tests.

Inert Python emits explicitly synthetic TRACE. No SIMION/PA/native qualification.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

from common.contracts import test_simion_tracking_execution as base_fixture
from msplatform.backends.simion.tracking_execution import plan_tracking_execution,execute_tracking
from msplatform.backends.simion.tracking_units import partition_tracking_units,slice_tracking_plan,inspect_tracking_recovery,require_tracking_executable_identity
from msplatform.execution import owner
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import file_record
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession


INERT = r'''
import json,sys,time
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
if p['kind']=='build':
    Path(p['iob']).write_bytes(b'INERT_NOT_IOB')
    print('SINGLE_REFLECTION_IOB=PASS',flush=True)
elif p['kind']=='verify':print('SINGLE_REFLECTION_IOB_REOPEN=PASS',flush=True)
else:
    time.sleep(p.get('delay',0))
    for ion,row in enumerate(p['rows'],1):
        pid,t=row['particle_id'],row['instrument_time_us']
        state=' '.join(f'{a}_mm={row["position_"+a+"_mm"]:.17g}' for a in 'xyz')+' '+' '.join(f'v{a}_mm_per_us={row["velocity_"+a+"_m_s"]/1000:.17g}' for a in 'xyz')
        xyz=' '.join(f'{a}={row["position_"+a+"_mm"]:.17g}' for a in 'xyz')
        print(f'TRACE: source_release ion={ion} particle_id={pid} instrument_time_us={t:.17g} {state}')
        print(f'TRACE: handoff_terminal_raw ion={ion} instance=3 instrument_time_us={t+1:.17g} {state}')
        print(f'TRACE: non_detector_splat ion={ion} instance=3 t={t+1:.17g} {xyz} zmax=0')
    if p.get('partial'):sys.exit(7)
    print(f'status,Fly completed. {len(p["rows"])} splats')
'''


class TrackingUnitPlanTests(unittest.TestCase):
    def test_recovery_rejects_same_directory_sidecar_before_reading_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar=Path(directory)/'result.json';sidecar.write_text('{}',encoding='utf-8')
            with patch('msplatform.backends.simion.tracking_units._whole_unit_artifact_hashes') as read:
                with self.assertRaisesRegex(ValueError,'canonical run_manifest.json'):
                    inspect_tracking_recovery({},file_record(sidecar,'required_evidence'))
                read.assert_not_called()

    def test_partial_replay_binds_binary_bytes_and_missing_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            tool=Path(directory)/'first.exe';tool.write_bytes(b'INERT_IDENTITY_A')
            relocated=Path(directory)/'elsewhere.exe';relocated.write_bytes(tool.read_bytes())
            changed=Path(directory)/'changed.exe';changed.write_bytes(b'INERT_IDENTITY_B')
            plan={'expected_operation_ids':['track_fly__unit_0002']}
            identity=require_tracking_executable_identity(plan,None,tool)
            recovery={'index':{'native_executable_identity':identity},'reused_unit_keys':['unit_0001']}
            self.assertEqual(require_tracking_executable_identity(plan,recovery,relocated),identity)
            with self.assertRaisesRegex(ValueError,'executable identity differs'):
                require_tracking_executable_identity(plan,recovery,changed)
            historical={'index':{},'reused_unit_keys':['unit_0001']}
            with self.assertRaisesRegex(ValueError,'executable identity is missing'):
                require_tracking_executable_identity(plan,historical,tool)
            historical['reused_unit_keys']=[]
            self.assertEqual(require_tracking_executable_identity(plan,historical,changed),
                             require_tracking_executable_identity(plan,None,changed))
            with self.assertRaisesRegex(ValueError,'selected native executable'):
                require_tracking_executable_identity(plan,recovery,None)

    def test_complete_reuse_preserves_recorded_or_unknown_identity_without_tools(self):
        prior={'bytes':17,'sha256':'A'*64}
        with patch('msplatform.backends.simion.tracking_units.file_record',side_effect=AssertionError('no tool read')):
            for identity in (prior,None):
                recovery={'index':{'native_executable_identity':identity},'reused_unit_keys':['unit_0001']}
                self.assertEqual(require_tracking_executable_identity({'expected_operation_ids':[]},recovery,None),identity)
            self.assertIsNone(require_tracking_executable_identity({'expected_operation_ids':[]},
                {'index':{},'reused_unit_keys':['unit_0001']},None))
            self.assertIsNone(require_tracking_executable_identity({'expected_operation_ids':[]},None,None))

    def test_ordinal_partition_not_ids_and_global_mother_immutable(self):
        case=base_fixture.TrackingExecutionPlanTests();case.setUp()
        plan=case.plan(unit_size=27)
        self.assertEqual([len(unit['expected_particle_ids']) for unit in plan['units']],[27,27,27,19])
        self.assertEqual(len(plan['expected_operation_ids']),12)
        before=copy.deepcopy(plan)
        for unit in plan['units']:
            sliced=slice_tracking_plan(plan,unit)
            self.assertEqual([row['particle_id'] for row in sliced['rows']],unit['expected_particle_ids'])
            self.assertEqual(sliced['source_provenance']['mother_records'],plan['source_provenance']['mother_records'])
            self.assertEqual(sliced['absolute_deadlines_us_by_particle_id'],plan['absolute_deadlines_us_by_particle_id'])
        self.assertEqual(plan,before)
        for invalid in (True,0,-1,2.5,'25'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):case.plan(unit_size=invalid)
        selected=partition_tracking_units(plan,unit_size=27,reused_unit_keys=['unit_0003','unit_0001'])
        self.assertEqual(len(selected['expected_operation_ids']),6)
        self.assertEqual([u['action'] for u in selected['units']],['reuse','replay','reuse','replay'])
        self.assertEqual(partition_tracking_units(plan,unit_size=27,reused_unit_keys=[u['key'] for u in plan['units']])['expected_operation_ids'],[])
        for bad in (['unit_0001','unit_0001'],['unknown']):
            with self.assertRaises(ValueError):partition_tracking_units(plan,unit_size=27,reused_unit_keys=bad)


@unittest.skipUnless(os.name=='nt' and shutil.which('pwsh'),'Windows PowerShell required')
class TrackingUnitOwnerTests(unittest.TestCase):
    def test_original_owner_four_units_out_of_order_partial_replay_then_zero_calls(self):
        """Real owner/dispatcher/guards/children, controlled test-only role/CPU seams."""
        case=base_fixture.TrackingExecutionPlanTests();case.setUp()
        case.packet=base_fixture.ion_release_api.sample_release(dict(case.case.release,relative_weights={pid:1.+i/100 for i,pid in enumerate(case.case.release['particle_ids'])})).to_dict()
        self.assertTrue(os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'shared GATE required')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,_session,producer=base_fixture.tracking_action_fixture(case,root)
            case.clocks={key:dict(artifact.data_records[key],path=str(artifact.data_path(key)))
                         for key in ('clock_authority','instrument_epoch')}
            script=root/'inert.py';script.write_text(INERT,encoding='utf-8',newline='\n')
            budget=root/'budget.json';budget.write_text('{"bytes":67108864}',encoding='utf-8')
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable)},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'))
            copied=root/'copied-ps';copied.mkdir()
            originals={}
            for name in ('batch_process_owner.ps1','simion_dispatch_support.ps1','resource_process_support.ps1','host_execution_lease.ps1','payload_file_support.ps1'):
                raw=resource_path(name).read_bytes();originals[name]=raw;text=raw.decode('utf-8')
                if name=='batch_process_owner.ps1':
                    marker=". (Join-Path $PSScriptRoot 'simion_dispatch_support.ps1')"
                    text=text.replace(marker,marker+"\nfunction Assert-HostResourceHeavyStage {}\nfunction Get-SystemCpuPercent {return 0}\n")
                (copied/name).write_text(text,encoding='utf-8',newline='\n')
            actual_single,actual_group=RunSession.run_process,RunSession.run_process_group
            from msplatform.execution.simion_dispatch import plan_simion_dispatch as actual_plan
            calls=[]
            def payload(session,name,argv,*,partial_log=False):
                key=name.split('__')[-1];index=int(key.split('_')[-1]);low=(index-1)*25;high=index*25
                value={'kind':'fly' if name.startswith('track_fly') else ('build' if name.startswith('build_') else 'verify')}
                if value['kind']=='fly':
                    value.update(rows=json.loads((session.input_dir/'canonical_source_states.json').read_text())[low:high],
                        partial=partial_log,delay=5 if index==1 and partial_log is False and 'failed' in session.run_id else .2)
                else:value['iob']=str(session.run_dir/'units'/key/'simion/tracking/instrument.iob')
                target=session.declare_file(session.input_dir/(name+'.inert.json'),'required_evidence')
                target.write_text(json.dumps(value),encoding='utf-8')
                session.add_input('inert_'+name,file_record(target,'required_evidence'))
                return ['-I','-B',str(script),str(target)]
            def single(session,name,*,immutable_input_records=(),**kwargs):
                kwargs['immutable_input_records']=immutable_input_records
                calls.append((session.run_id,name))
                kwargs.update(arguments=payload(session,name,kwargs['arguments']),executable=Path(sys.executable),role='GATE',stage='unclassified')
                return actual_single(session,name,**kwargs)
            def group(session,specs,**kwargs):
                failed='failed' in session.run_id
                prepared=[]
                for spec in specs:
                    item=dict(spec);name=item['operation_id']
                    item.update(executable=Path(sys.executable),arguments=payload(session,name,item['arguments'],partial_log=failed and name.endswith('0002')))
                    prepared.append(item)
                if failed:prepared.sort(key=lambda row:{3:0,1:1,2:2,4:3}[row['scheduler_batch']['index']])
                kwargs.update(role='GATE',stage='unclassified')
                try:return actual_group(session,prepared,**kwargs)
                finally:
                    # Hashtable observation keys are not a completion order.
                    # The original dispatcher keeps actual chronological attempts.
                    saved=session.log_dir/'group_tracking_fly.process.json'
                    if saved.exists():
                        for attempt in json.loads(saved.read_text())['attempts']:
                            calls.append((session.run_id,attempt['operation_id']))
            def dispatch(*args,**kwargs):
                value=actual_plan(*args,**kwargs)
                value['estimation']=dict(kind='exact_resource_profile',per_process_memory_budget_bytes=1024**2,
                    per_process_cpu_percent=1.,observed_batch_work_units=25)
                value['limits'].update(maximum_concurrency=2,launch_stagger_seconds=1)
                return value
            def fail_after_reuse(session,execute_action):
                execute_action(session)
                raise RuntimeError('INERT_FAIL_AFTER_REUSE')
            def run(label,recovery=None,after_error=False,selected_tool=None):
                graph=case.plan(unit_size=25,field_manifest_record=artifact.reference['manifest'])
                if recovery is not None:
                    inspected=inspect_tracking_recovery(graph,recovery)
                    graph=case.plan(unit_size=25,reused_unit_keys=inspected['reused_unit_keys'],field_manifest_record=artifact.reference['manifest'])
                run_id='20261104_120000__test__python__tracking-'+label
                action=partial(execute_tracking,fields_reference=artifact,particles=case.packet,propagation=case.policy,
                    observations={'plane_observations':[]},numerics=case.numerics,limits={},unit_size=25,recovery_reference=recovery)
                if after_error:action=partial(fail_after_reuse,execute_action=action)
                from dataclasses import replace
                active_context=replace(context,tools={}) if label=='all-reused' or after_error else context
                if selected_tool is not None:active_context=replace(active_context,tools={'simion':selected_tool})
                return owner.run_managed_stage(active_context,descriptor=dict(project='instrument_assembly',mode='inert_tracking',software=[]),
                    run_id=run_id,payload={},committed_new_bytes=67108864,commitment_inputs=[file_record(budget,'required_evidence')],
                    retention=dict(policy_version=1,**{'class':'solver_review'},reason='explicit inert Python not native'),
                    expected_operation_ids=graph['expected_operation_ids'],operation_dependencies=graph['operation_dependencies'],
                    action=action,action_record=file_record(Path(__file__) if after_error else Path(execute_tracking.__code__.co_filename),'required_evidence'),
                    completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            private=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            policy=dict(_capacity_policy(),target_gib=1,minimum_free_gib=0)
            real_resource=resource_path
            with patch.dict(os.environ,private),patch(
                    'msplatform.execution.capacity_admission._capacity_policy',return_value=policy),patch(
                    'msplatform.backends.simion.model_execution._protected_source'),patch.object(RunSession,'run_process',new=single),patch.object(
                    RunSession,'run_process_group',new=group),patch('msplatform.backends.simion.tracking_execution.plan_tracking_execution',wraps=plan_tracking_execution),patch(
                    'msplatform.execution.simion_dispatch.plan_simion_dispatch',side_effect=dispatch),patch(
                    'msplatform.execution.processes.resource_path',side_effect=lambda name:copied/name if name=='batch_process_owner.ps1' else real_resource(name)):
                with self.assertRaisesRegex(Exception,'batch wave failed'):run('failed')
                predecessor=context.workspace/'artifacts/projects/instrument_assembly/runs/20261104_120000__test__python__tracking-failed'
                reference=file_record(predecessor/'run_manifest.json','required_evidence')
                index=json.loads((predecessor/'logs/tracking_units.json').read_text())
                self.assertEqual([row['complete'] for row in index['units']],[True,False,True,False])
                selected_record=file_record(Path(sys.executable),'solver_native_binary')
                self.assertEqual(index['native_executable_identity'],{key:selected_record[key] for key in ('bytes','sha256')})
                self.assertEqual([name for rid,name in calls if rid.endswith('failed') and name.startswith('track_fly')],
                    ['track_fly__unit_0003','track_fly__unit_0002','track_fly__unit_0001'])
                graph=case.plan(unit_size=25,field_manifest_record=artifact.reference['manifest'])
                for key in ('numerics','source_realization','field_manifest_identity'):
                    changed=copy.deepcopy(graph)
                    if key=='numerics':changed[key]['maximum_step_us']*=2
                    elif key=='source_realization':changed[key]['realization']['spec']['sampling']['seed']+=1
                    else:changed[key]['sha256']='F'*64
                    with self.subTest(changed=key),self.assertRaisesRegex(ValueError,'applicability'):
                        inspect_tracking_recovery(changed,reference)
                intact=Path(index['units'][0]['stdout_record']['path'])
                original=intact.read_bytes();intact.write_bytes(original+b'TAMPER')
                try:
                    with self.assertRaises((ValueError,AssertionError)):inspect_tracking_recovery(graph,reference)
                finally:intact.write_bytes(original)
                frozen_path=Path(index['immutable_inputs'][0]['path'])
                original=frozen_path.read_bytes();frozen_path.write_bytes(original+b'TAMPER')
                try:
                    with self.assertRaises((ValueError,AssertionError)):inspect_tracking_recovery(graph,reference)
                finally:frozen_path.write_bytes(original)
                # A declared partial log is not inspected to guess completion.
                partial_path=Path(index['units'][1]['stdout_record']['path'])
                original_read=Path.read_bytes
                def no_partial(path):
                    if path==partial_path:raise AssertionError('partial output must not be hashed')
                    return original_read(path)
                with patch.object(Path,'read_bytes',new=no_partial):
                    self.assertEqual(inspect_tracking_recovery(graph,reference)['reused_unit_keys'],['unit_0001','unit_0003'])
                # Actual recovery consumer must not mix completed Fly units from
                # one binary with replay under a different selected executable.
                changed_tool=root/'different-selected-tool.exe'
                changed_tool.write_bytes(b'INERT_IDENTITY_FIXTURE_NEVER_EXECUTED')
                before_calls=len(calls)
                with self.assertRaisesRegex(ValueError,'executable identity'):
                    run('changed-tool',reference,selected_tool=changed_tool)
                self.assertEqual(calls[before_calls:],[])
                relocated_tool=root/'same-selected-tool.exe'
                shutil.copyfile(sys.executable,relocated_tool)
                resumed=run('resumed',reference,selected_tool=relocated_tool)
                child=Path(resumed['run_directory'])
                self.assertEqual(len([x for rid,x in calls if rid.endswith('resumed')]),6)
                collection=json.loads((child/'results/collection.json').read_text())
                self.assertEqual(collection['native_calls'],6)
                self.assertEqual(len(collection['native_terminals']),100)
                self.assertEqual(collection['original_mother']['mother_particle_ids'],case.case.release['particle_ids'])
                all_reused=run('all-reused',file_record(child/'run_manifest.json','required_evidence'))
                self.assertEqual(len([x for rid,x in calls if rid.endswith('all-reused')]),0)
                self.assertEqual(json.loads((Path(all_reused['run_directory'])/'results/collection.json').read_text())['native_calls'],0)
                self.assertEqual([row['particle_weight'] for row in collection['original_mother']['mother_records']],
                    [1.+i/100 for i in range(100)])
                self.assertEqual([row['particle_birth_time_us'] for row in collection['original_mother']['mother_records']],
                    [row['particle_birth_time_us'] for row in case.packet['rows']])
                # Fail after a zero-native reused calculation: its immutable
                # replay plan must remain bound by this FAILED direct parent.
                with self.assertRaisesRegex(RuntimeError,'INERT_FAIL_AFTER_REUSE'):
                    run('failed-after-reuse',file_record(child/'run_manifest.json','required_evidence'),after_error=True)
                failed_child=context.workspace/'artifacts/projects/instrument_assembly/runs/20261104_120000__test__python__tracking-failed-after-reuse'
                failed_manifest=file_record(failed_child/'run_manifest.json','required_evidence')
                self.assertEqual(inspect_tracking_recovery(graph,failed_manifest)['reused_unit_keys'],
                    ['unit_0001','unit_0002','unit_0003','unit_0004'])
                self.assertEqual([name for rid,name in calls if rid.endswith('failed-after-reuse')],[])
                fresh=run('fresh')
                self.assertEqual(len([x for rid,x in calls if rid.endswith('fresh')]),12)
                fresh_collection=json.loads((Path(fresh['run_directory'])/'results/collection.json').read_text())
                self.assertEqual(fresh_collection['native_calls'],12)
                completion=json.loads((child/'results/execution_completion.json').read_text())
                print('TRACKING_F1_INERT_PROOF='+json.dumps(dict(native_qualification=False,
                    mother_count=100,execution_ids=case.case.release['particle_ids'],
                    failed_parent_complete=[row['complete'] for row in index['units']],
                    failed_parent_attempt_order=[name for rid,name in calls if rid.endswith('failed') and name.startswith('track_fly')],
                    fresh_calls=12,resumed_calls=6,all_reuse_calls=0,refine_calls=0,
                    resumed_actual_operations=completion['writer_completion']['operations'],
                    resumed_release_count=len(completion['writer_completion']['resource_releases']),
                    clock=collection['original_mother']['clock_authority_sha256']),sort_keys=True))
            for name,raw in originals.items():self.assertEqual(resource_path(name).read_bytes(),raw)


if __name__=='__main__':unittest.main()
