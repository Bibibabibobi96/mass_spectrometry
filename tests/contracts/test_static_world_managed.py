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

from tests.contracts import test_static_world_model as static_fixture
from tests.contracts.test_simion_rf_tracking import rf_tracking_case
from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
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
        self._exercise_public_chain(False)

    def test_public_empty_surface_chain_and_failed_refine(self):
        self._exercise_public_chain(True)

    def _exercise_public_chain(self, empty_surface):
        case=static_fixture.StaticWorldModelTests();case.setUp()
        compiled=operations.compile_geometry(case.assembly,numerics=case.numerics)
        _,_,packet,_,propagation,numerics=rf_tracking_case()
        numerics.pop('rf_steps_per_period')
        for row in packet['rows']:row['frame_id']='toy_local'
        for row in packet['mother']['records'].values():row['frame_id']='toy_local'
        prior_process=RunSession.run_process
        fail_refine=[False]; calls=[]; tracking_guards={}; export_requests=[]
        def inert_process(session,operation_id,*,immutable_input_records=(),**kwargs):
            if kwargs['role'] != 'SIMION':
                return prior_process(session,operation_id,immutable_input_records=immutable_input_records,**kwargs)
            calls.append(operation_id);run=session.run_dir
            guards=[str(record['path']) for record in immutable_input_records]
            if operation_id.startswith(('build_tracking_iob','verify_tracking_iob','track_fly')):
                tracking_guards[operation_id]=set(guards)
            code='from pathlib import Path\nimport json\n'
            if guards:
                code+='for p in '+repr(guards)+':\n try:\n  f=open(p,"ab");f.close()\n except PermissionError: pass\n else: raise AssertionError("immutable input was writable")\n'
            if operation_id.startswith('geometry_'):
                seed=file_record(structural_seed_path(1),'required_evidence')
                plan=plan_geometry_build(compiled,run_directory=run,seed_record=seed,native_path_resource=session.input_dir/'native_sources/native_run_path.lua')
                op=next(row for row in plan.operations if row['operation_id']==operation_id)
                for path in op['outputs']:
                    if path.endswith('_surface_state.json'):
                        dims=compiled.frontend_geometry['dimensions'];pitch=compiled.frontend_geometry['pitch_mm']
                        state=dict(schema_version=1,mode='empty' if empty_surface else 'present',grid=dims,pitch=[pitch]*3,
                                   scanned_nodes=dims[0]*dims[1]*dims[2] if empty_surface else None,offset_nodes=0 if empty_surface else None)
                        code+='p=Path('+repr(path)+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('+repr(json.dumps(state,separators=(',',':')))+'+"\\n",encoding="utf8")\n'
                    else:
                        value=b'1,1,1,nil,nil,nil\n' if path.endswith('_surface.csv') and empty_surface else b'INERT_ONLY'
                        code+='p=Path('+repr(path)+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes('+repr(value)+')\n'
                if not empty_surface:
                    code+='p=Path('+repr(op['optional_surface'])+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_SURFACE")\n'
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
            elif operation_id=='audit_family':
                output=run/'results/static_family_audit.json'
                code+='p=Path('+repr(str(output))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"role":"simion_rf_fractional_field_audit","status":"success","checked_domains":["world"],"fixture":"INERT_ONLY"}),encoding="utf-8")\nprint("INDEPENDENT_RF_FIELDS_READBACK=PASS")\n'
            elif operation_id=='export_operating':
                source,output,workpoint=map(Path,kwargs['arguments'][-3:])
                self.assertEqual(source.name,'world.pa0');self.assertEqual(output.name,'world_operating.pa')
                self.assertEqual(output.parent,source.parent)
                self.assertEqual(output.parent,run/'simion/fields/world')
                self.assertEqual(workpoint.name,'static_workpoint.lua');self.assertTrue(workpoint.is_file())
                self.assertNotIn(str(session.canonical_path(source)),guards)
                exporter=session.input_dir/'native_sources/export_detached_standalone_pa.lua'
                from msplatform.backends.simion import native_surface_state
                validator=Path(native_surface_state.__file__).resolve()
                frozen_validator=session.input_dir/'native_sources/native_surface_state.py'
                self.assertEqual(set(guards),{str(session.canonical_path(workpoint)),str(session.canonical_path(exporter)),
                                              str(validator),str(session.canonical_path(frozen_validator))})
                export_requests.append((str(source),str(output),workpoint.read_text(encoding='utf-8')))
                for path in ((output,) if empty_surface else (output,output.with_suffix('.pa-surf'))):
                    code+='p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_STANDALONE_NOT_NATIVE")\n'
                code+='print("DETACHED_STANDALONE_PA_EXPORT=PASS")\n'
            elif operation_id=='audit_fields':
                output=run/'results/static_operating_audit.json'
                code+='p=Path('+repr(str(output))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"role":"simion_static_operating_field_audit","status":"success","checked_domains":["world"],"fixture":"INERT_ONLY"}),encoding="utf-8")\nprint("STATIC_OPERATING_FIELDS_READBACK=PASS")\n'
            elif operation_id.startswith(('build_tracking_iob','verify_tracking_iob')):
                building=operation_id.startswith('build_tracking_iob')
                if building:
                    for path in (run/'simion/tracking/instrument.iob',run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0'):
                        code+='p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
                code+='print('+repr('STATIC_WORLD_TRACKING_IOB=PASS' if building else 'STATIC_WORLD_TRACKING_IOB_REOPEN=PASS')+')\n'
            elif operation_id=='track_fly':
                code+='rows=json.loads(Path('+repr(str(session.input_dir/'canonical_source_states.json'))+').read_text(encoding="utf-8"));print(\'RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}\')\n'
                from tests.contracts.test_support.terminal_evidence_fixture import native_run_from_program, inert_wire_source
                code += inert_wire_source()+"native_run="+repr(native_run_from_program(run/"simion/tracking/instrument.lua"))+"\n"
                code+='for ion,row in enumerate(rows,1):\n state=dict(event="source_release",reason="none",particle_id=row["particle_id"],ion=ion,instrument_time_us=row["instrument_time_us"],mass_amu=row["mass_amu"],charge_state=row["charge_state"],instance=1);state.update({a+"_mm":row["position_"+a+"_mm"] for a in "xyz"});state.update({"v"+a+"_mm_per_us":row["velocity_"+a+"_m_s"]/1000 for a in "xyz"});print("RF_NATIVE_STATE_V1: "+json.dumps(state));state.update(event="terminal",reason="unknown",instrument_time_us=2.);print("RF_NATIVE_STATE_V1: "+json.dumps(state));print("\\n".join(terminal_wire_lines(row,ion,native_run,2.,1)))\nprint("status,Fly completed. 2 splats")\n'
            else:raise AssertionError('unexpected SIMION operation '+operation_id)
            return prior_process(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_static_world',limits=kwargs['limits'],immutable_input_records=immutable_input_records)
        private={'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
        with retained_on_failure() as directory, patch.dict(os.environ,private):
            os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']=str(Path(directory)/'private-host.sqlite3')
            context,_,_=make_context(Path(directory));policy=json.loads(context.stage_policy_path.read_text(encoding='utf-8'))
            from msplatform.execution.owner import standalone_native_store
            from msplatform.storage import ArtifactStore
            store = ArtifactStore(Path(directory)/'store')
            for name in ('build_geometry','prepare_model','solve_fields'):
                policy['stages'][name]=copy.deepcopy(policy['stages']['track'])
            policy['stages']['solve_fields']['limits']['reserved_run_payload_bytes']=1048576
            context.stage_policy_path.write_text(json.dumps(policy),encoding='utf-8')
            with standalone_native_store(store,task_key='static-world-public-chain',budget=1024**3), patch.object(RunSession,'run_process',new=inert_process):
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
                self.assertEqual(field.metadata['field_representation'],'producer_owned_static_world_standalone_operating_pa')
                expected_binding=dict(operating='world_operating',surface_witnesses='world_surface_witnesses',surface_state='world_surface_state')
                if not empty_surface:expected_binding['surface']='world_surface'
                self.assertEqual(field.metadata['native_assets'],{'world':expected_binding})
                native_names=('world_operating','world_surface_witnesses','world_surface_state') + (() if empty_surface else ('world_surface',))
                if empty_surface:self.assertFalse((field.manifest_location.parent/'simion/fields/world/world_operating.pa-surf').exists())
                native_paths={str(field.data_path(name)) for name in native_names}
                original={name:field.data_path(name).read_bytes() for name in native_names}
                self.assertEqual(field.metadata['spatial_identity']['voltages'],sorted((dict(electrode_id=row['native_targets'][0]['electrode_id'],voltage_v=row['voltage_v']) for row in document['native_drive_rows']),key=lambda row:row['electrode_id']))
                self.assertEqual(len(export_requests),1)
                self.assertIn('[1]=1.25',export_requests[0][2]);self.assertIn('[2]=0',export_requests[0][2])
                native_receipts=json.loads(field.data_path('field_native_receipts').read_text(encoding='utf-8'))
                self.assertEqual({row['operation_id'] for row in native_receipts},{'refine_world','audit_family','export_operating','audit_fields'})
                self.assertTrue(all(row['observation']['exit_confirmed'] and row['observation']['returncode']==0 for row in native_receipts))
                operating_audit=json.loads(field.data_path('field_audit').read_text(encoding='utf-8'))
                self.assertEqual((operating_audit['role'],operating_audit['status'],operating_audit['checked_domains']),('simion_static_operating_field_audit','success',['world']))
                self.assertEqual(calls.count('refine_world'),1)
                reused=operations.solve_fields(model,numerics=dict(refine_policy='vendor_default'),context=context,reuse_fields=field)
                self.assertTrue(reused.metadata['fields_reused'])
                self.assertEqual(reused.metadata['operating_producer_reference'],field.reference)
                self.assertEqual({name:reused.data_records[name] for name in native_names},{name:field.data_records[name] for name in native_names})
                self.assertEqual(calls.count('refine_world'),1);self.assertEqual(calls.count('export_operating'),1)
                protected={str(artifact.data_path(name)):artifact.data_path(name).read_bytes() for artifact in (geometry,model) for name in artifact.data_records if ('raw_geometry' in name or name.startswith('geometry_'))}
                packet['clock']={key:document['drive']['clock'][key] for key in ('clock_epoch_id','authority_sha256')}
                for row in packet['rows']:row['clock_epoch_id']=packet['clock']['clock_epoch_id']
                for row in packet['mother']['records'].values():row['clock_epoch_id']=packet['clock']['clock_epoch_id']
                trajectory=operations.track(reused,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context)
                reopened=open_artifact(trajectory.reference,expected_kind='trajectory_result')
                collection=json.loads(reopened.data_path('collection').read_text(encoding='utf-8'))
                self.assertEqual([row['particle_id'] for row in collection['native_terminals']],[7,91])
                self.assertEqual(collection['original_mother']['mother_records'],list(packet['mother']['records'].values()))
                program=(trajectory.manifest_location.parent/'simion/tracking/instrument.lua').read_text(encoding='utf-8')
                self.assertIn('local rf_static_operating=true',program)
                self.assertIn('if not rf_static_operating then\nfunction segment.fast_adjust()',program)
                self.assertEqual(original,{name:field.data_path(name).read_bytes() for name in native_names})
                tracking_names=[name for name in tracking_guards if name.startswith(('build_tracking_iob','verify_tracking_iob','track_fly'))]
                self.assertEqual(len(tracking_names),3)
                for name in tracking_names:self.assertTrue(native_paths <= tracking_guards[name],name)
                family_paths={str(path) for path in (field.manifest_location.parent/'simion/fields/world').glob('world.pa[0-9]')}
                for name in tracking_names:self.assertTrue(tracking_guards[name].isdisjoint(family_paths),name)

                fail_refine[0]=True
                with self.assertRaisesRegex(ProcessExecutionError, '7'):operations.solve_fields(model,numerics=dict(refine_policy='vendor_default'),context=context)
            self.assertEqual(calls.count('refine_world'),2)
            paths=list(store.root.glob('assets/native_stage/*/*/runs/*/run_manifest.json'))
            manifests=[json.loads(path.read_text(encoding='utf-8')) for path in paths]
            failed=[row for row in manifests if row.get('status')=='failed']
            self.assertEqual(len(failed),1);self.assertFalse(failed[0].get('products'))
            failed_dir=paths[manifests.index(failed[0])].parent;completion=json.loads((failed_dir/'results/execution_completion.json').read_text(encoding='utf-8'))
            self.assertEqual(completion['status'],'failed')
            ops=completion['writer_completion']['operations']
            self.assertEqual([row['operation_id'] for row in ops],['materialize_geometry','refine_world'])
            self.assertTrue(ops[-1]['observation']['exit_confirmed']);self.assertEqual(ops[-1]['observation']['returncode'],7)
            self.assertIn('INERT_REFINE_FAILURE',(failed_dir/'logs/operation_0002.stdout.log').read_text(encoding='utf-8'))
            self.assertTrue((failed_dir/'simion/fields/world/world.pa#').is_file())
            failed_request=json.loads((failed_dir/'inputs/execution_request.json').read_text(encoding='utf-8'))
            self.assertIn(model.reference['manifest'],[row['manifest_record'] for row in failed_request['capacity']['source_references']])
            self.assertEqual(protected,{path:Path(path).read_bytes() for path in protected})
            with store._db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM claims').fetchone()[0],0)
            for artifact,source in ((geometry,None),(model,geometry),(field,model),(reused,field),(trajectory,reused)):
                request=json.loads((artifact.manifest_location.parent/'inputs/execution_request.json').read_text(encoding='utf-8'))
                if source is not None:
                    self.assertIn(source.reference['manifest'],[row['manifest_record'] for row in request['capacity']['source_references']])
