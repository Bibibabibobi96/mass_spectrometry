"""Public neutral-static owner chain with inert children; not native qualification."""
from contextlib import contextmanager
import copy
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import test_static_world_model as static_fixture
from common.contracts.test_simion_rf_tracking import rf_tracking_case
from common.contracts.test_support.sfi_scalar_owner_fixture import make_context
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.execution.capacity_protection import _lease_path
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact

@contextmanager
def retained_on_failure():
    root = Path(tempfile.mkdtemp(prefix='static-world-owner-')).resolve()
    print('STATIC_WORLD_OWNER', root, flush=True)
    try:
        yield root
    except BaseException:
        print('RETAINED_STATIC_WORLD_OWNER', root, flush=True)
        raise
    else:
        parent = Path(tempfile.gettempdir()).resolve()
        if root.parent != parent or not root.name.startswith('static-world-owner-'):
            raise ValueError('test-owned temporary directory escaped its expected parent')
        shutil.rmtree(root)
@unittest.skipUnless(os.name == 'nt', 'actual Windows process guard required')
class StaticWorldManagedTests(unittest.TestCase):
    def test_public_chain_and_failed_refine(self):
        case=static_fixture.StaticWorldModelTests();case.setUp()
        compiled=operations.compile_geometry(case.assembly,numerics=case.numerics)
        _,_,packet,_,propagation,numerics=rf_tracking_case()
        numerics.pop('rf_steps_per_period')
        for row in packet['rows']:row['frame_id']='toy_local'
        for row in packet['mother']['records'].values():row['frame_id']='toy_local'
        prior_process=RunSession.run_process
        fail_refine=[False]; calls=[]
        def inert_process(session,operation_id,*,immutable_input_records=(),**kwargs):
            if kwargs['role'] != 'SIMION':
                return prior_process(session,operation_id,immutable_input_records=immutable_input_records,**kwargs)
            calls.append(operation_id);run=session.run_dir
            guards=[str(record['path']) for record in immutable_input_records]
            code='from pathlib import Path\nimport json\n'
            if guards:
                code+='for p in '+repr(guards)+':\n try:\n  f=open(p,"ab");f.close()\n except PermissionError: pass\n else: raise AssertionError("immutable input was writable")\n'
            if operation_id.startswith('geometry_'):
                seed=file_record(structural_seed_path(1),'required_evidence')
                plan=plan_geometry_build(compiled,run_directory=run,seed_record=seed,native_path_resource=session.input_dir/'native_sources/native_run_path.lua')
                op=next(row for row in plan.operations if row['operation_id']==operation_id)
                for path in op['outputs']:code+='p=Path('+repr(path)+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
                code+='print('+repr(op['success_marker'])+')\n'
            elif operation_id in ('build_geometry','verify_geometry'):
                if operation_id=='build_geometry':
                    for path in (run/'simion/geometry/geometry.iob',run/'simion/geometry/geometry.fly2'):
                        code+='p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
                code+='print('+repr('NEUTRAL_WORLD_GEOMETRY_IOB=PASS' if operation_id=='build_geometry' else 'NEUTRAL_WORLD_GEOMETRY_IOB_REOPEN=PASS')+')\n'
            elif operation_id in ('build_model','verify_model'):
                if operation_id=='build_model':
                    for path in (run/'simion/geometry/geometry.iob',run/'simion/geometry/geometry.fly2'):
                        code+='p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
                else:
                    code+='m=json.loads(Path('+repr(str(session.input_dir/'compiled_model.json'))+').read_text(encoding="utf-8"));p=Path('+repr(str(run/'results/model_drive_readback.txt'))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"fixture":"INERT_ONLY","model_identity_sha256":m["model_identity_sha256"],"groups":m["native_drive_rows"],"clock":m["drive"]["clock"]}),encoding="utf-8")\n'
                code+='print('+repr('NEUTRAL_WORLD_MODEL_BUILD=PASS' if operation_id=='build_model' else 'NEUTRAL_WORLD_MODEL_READBACK=PASS')+')\n'
            elif operation_id=='refine_world':
                if fail_refine[0]:code+='print("INERT_REFINE_FAILURE",flush=True);raise SystemExit(7)\n'
                else:
                    raw=run/'simion/fields/world/world.pa#'
                    labels=[row['native_id'] for row in compiled.frontend_geometry['electrode_mapping']]
                    for suffix in ['.pa0',*('.pa'+str(n) for n in labels)]:
                        code+='Path('+repr(str(raw.with_suffix(suffix)))+').write_bytes(b"INERT_RESPONSE_NOT_NATIVE")\n'
                    code+='print("INDEPENDENT_RF_REFINE=PASS")\n'
            elif operation_id=='audit_fields':
                output=run/'results/rf_field_audit.json'
                code+='p=Path('+repr(str(output))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"role":"simion_rf_fractional_field_audit","status":"success","checked_domains":["world"],"fixture":"INERT_ONLY"}),encoding="utf-8")\nprint("INDEPENDENT_RF_FIELDS_READBACK=PASS")\n'
            elif operation_id.startswith(('build_tracking_iob','verify_tracking_iob')):
                building=operation_id.startswith('build_tracking_iob')
                if building:
                    for path in (run/'simion/tracking/instrument.iob',run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0'):
                        code+='p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
                code+='print('+repr('STATIC_WORLD_TRACKING_IOB=PASS' if building else 'STATIC_WORLD_TRACKING_IOB_REOPEN=PASS')+')\n'
            elif operation_id=='track_fly':
                code+='rows=json.loads(Path('+repr(str(session.input_dir/'canonical_source_states.json'))+').read_text(encoding="utf-8"));print(\'RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}\')\n'
                code+='for ion,row in enumerate(rows,1):\n state=dict(event="source_release",reason="none",particle_id=row["particle_id"],ion=ion,instrument_time_us=row["instrument_time_us"],mass_amu=row["mass_amu"],charge_state=row["charge_state"],instance=1);state.update({a+"_mm":row["position_"+a+"_mm"] for a in "xyz"});state.update({"v"+a+"_mm_per_us":row["velocity_"+a+"_m_s"]/1000 for a in "xyz"});print("RF_NATIVE_STATE_V1: "+json.dumps(state));state.update(event="terminal",reason="unknown",instrument_time_us=2.);print("RF_NATIVE_STATE_V1: "+json.dumps(state))\nprint("status,Fly completed. 2 splats")\n'
            else:raise AssertionError('unexpected SIMION operation '+operation_id)
            return prior_process(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_static_world',limits=kwargs['limits'],immutable_input_records=immutable_input_records)
        private={'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
        with retained_on_failure() as directory, patch.dict(os.environ,private):
            context,_,_=make_context(Path(directory));policy=json.loads(context.stage_policy_path.read_text(encoding='utf-8'))
            for name in ('build_geometry','prepare_model','solve_fields'):
                policy['stages'][name]=copy.deepcopy(policy['stages']['track'])
            policy['stages']['solve_fields']['limits']['reserved_run_payload_bytes']=1048576
            context.stage_policy_path.write_text(json.dumps(policy),encoding='utf-8')
            with patch.object(RunSession,'run_process',new=inert_process):
                bad=copy.deepcopy(compiled);bad.frontend_geometry['source_snapshot']['components_source']['first']['width_mm']=9
                with patch('msplatform.execution.owner.run_managed_stage') as blocked:
                    with self.assertRaises(ValueError):operations.build_geometry(bad,context=context)
                    blocked.assert_not_called()
                geometry=operations.build_geometry(compiled,context=context)
                authored_drive=dict(groups=case.drive['groups'],clock=dict(phase_reference_instrument_time_us=0),clock_authority=dict(example_resource='instrument_clock_authority_v1.json'))
                with patch('msplatform.execution.owner.run_managed_stage') as blocked:
                    with self.assertRaises(ValueError):operations.prepare_model(geometry,drive=authored_drive,physics=dict(RF_PHYSICS,boundary_policy='grounded_pa_faces'),context=context)
                    bad_drive=copy.deepcopy(authored_drive);bad_drive['groups']['first']['body']['voltage_v']=True
                    with self.assertRaises(ValueError):operations.prepare_model(geometry,drive=bad_drive,physics=RF_PHYSICS,context=context)
                    blocked.assert_not_called()
                model=operations.prepare_model(geometry,drive=authored_drive,physics=RF_PHYSICS,context=context)
                document=json.loads(model.data_path('compiled_model').read_text(encoding='utf-8'))
                readback=json.loads(model.data_path('drive_readback').read_text(encoding='utf-8'))
                self.assertEqual(readback['fixture'],'INERT_ONLY');self.assertEqual(readback['groups'],document['native_drive_rows']);self.assertEqual(readback['clock'],document['drive']['clock'])
                field=operations.solve_fields(model,numerics=dict(refine_policy='vendor_default'),context=context)
                self.assertEqual(field.metadata['field_representation'],'producer_owned_static_world_fractional_family')
                self.assertEqual(set(field.metadata['native_assets']),{'world'})
                original={name:Path(row['path']).read_bytes() for name,row in field.data_records.items() if '_family_' in name}
                protected={str(artifact.data_path(name)):artifact.data_path(name).read_bytes() for artifact in (geometry,model) for name in artifact.data_records if ('raw_geometry' in name or name.startswith('geometry_'))}
                packet['clock']={key:document['drive']['clock'][key] for key in ('clock_epoch_id','authority_sha256')}
                for row in packet['rows']:row['clock_epoch_id']=packet['clock']['clock_epoch_id']
                for row in packet['mother']['records'].values():row['clock_epoch_id']=packet['clock']['clock_epoch_id']
                trajectory=operations.track(field,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context)
                reopened=open_artifact(trajectory.reference,expected_kind='trajectory_result')
                collection=json.loads(reopened.data_path('collection').read_text(encoding='utf-8'))
                self.assertEqual([row['particle_id'] for row in collection['native_terminals']],[7,91])
                self.assertEqual(collection['original_mother']['mother_records'],list(packet['mother']['records'].values()))
                self.assertEqual(original,{name:Path(field.data_records[name]['path']).read_bytes() for name in original})
                fail_refine[0]=True
                with self.assertRaisesRegex(ProcessExecutionError, '7'):operations.solve_fields(model,numerics=dict(refine_policy='vendor_default'),context=context)
            self.assertEqual(calls.count('refine_world'),2)
            runs=context.workspace/'artifacts/projects/instrument_assembly/runs'
            manifests=[json.loads(path.read_text(encoding='utf-8')) for path in runs.glob('*/run_manifest.json')]
            failed=[row for row in manifests if row.get('status')=='failed']
            self.assertEqual(len(failed),1);self.assertFalse(failed[0].get('products'))
            failed_dir=runs/failed[0]['run_id'];completion=json.loads((failed_dir/'results/execution_completion.json').read_text(encoding='utf-8'))
            self.assertEqual(completion['status'],'failed')
            ops=completion['writer_completion']['operations']
            self.assertEqual([row['operation_id'] for row in ops],['materialize_geometry','refine_world'])
            self.assertTrue(ops[-1]['observation']['exit_confirmed']);self.assertEqual(ops[-1]['observation']['returncode'],7)
            self.assertIn('INERT_REFINE_FAILURE',(failed_dir/'logs/operation_0002.stdout.log').read_text(encoding='utf-8'))
            self.assertTrue((failed_dir/'simion/fields/world/world.pa#').is_file())
            failed_result_path=context.workspace/'artifacts/projects/instrument_assembly/scratch/workflow_results'/failed_dir.name/'result.json'
            failed_result=json.loads(failed_result_path.read_text(encoding='utf-8'));failed_capacity=failed_result['capacity_session']
            self.assertEqual(failed_result['status'],'failed');self.assertEqual(failed_capacity['status'],'released')
            self.assertIn(model.manifest_location.parent.resolve(),{Path(path).resolve() for path in failed_capacity['protected_paths']})
            self.assertEqual(protected,{path:Path(path).read_bytes() for path in protected})
            self.assertFalse(_lease_path(Path(failed_capacity['artifact_root']),failed_capacity['lease_id']).exists())
            for source_lease in failed_capacity.get('source_protection_leases',[]):
                self.assertFalse(_lease_path(Path(source_lease['artifact_root']),source_lease['lease_id']).exists())
            for artifact,source in ((geometry,None),(model,geometry),(field,model),(trajectory,field)):
                result_path=context.workspace/'artifacts/projects/instrument_assembly/scratch/workflow_results'/artifact.manifest_location.parent.name/'result.json'
                result=json.loads(result_path.read_text(encoding='utf-8'));capacity=result['capacity_session']
                self.assertEqual(capacity['status'],'released');self.assertFalse(_lease_path(Path(capacity['artifact_root']),capacity['lease_id']).exists())
                if source is not None:self.assertIn(source.manifest_location.parent.resolve(),{Path(path).resolve() for path in capacity['protected_paths']})
                for source_lease in capacity.get('source_protection_leases',[]):
                    self.assertFalse(_lease_path(Path(source_lease['artifact_root']),source_lease['lease_id']).exists())
