"""Managed model-to-sample witness; inert leaves only, no native qualification."""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts import test_generic_scalar_binding as fixture
from common.contracts.test_support.sfi_scalar_owner_fixture import make_context
from msplatform.backends.simion import operations
from msplatform.backends.simion.generic_scalar_binding import admit_linear_samples
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(os.name == "nt", "Windows process guard required")
class GenericScalarTrackingManagedTests(unittest.TestCase):
    def test_public_sampled_tracking(self):
        self._exercise(False)

    def _exercise(self, derived):
        case = fixture.GenericScalarTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        from msplatform.backends.simion.model import model_geometry

        compiled = model_geometry(case.model)
        original = RunSession.run_process
        calls = []
        field_guards = []
        tracking_guards = []
        fail_verify = [False]
        live_refs = []
        live_checks = []

        def inert(session, operation_id, *, immutable_input_records=(), **kwargs):
            if kwargs["role"] != "SIMION":
                return original(
                    session,
                    operation_id,
                    immutable_input_records=immutable_input_records,
                    **kwargs,
                )
            calls.append(operation_id)
            if operation_id in ('build_tracking_iob', 'verify_tracking_iob', 'track_fly'):
                tracking_guards.append({str(Path(row['path']).resolve()) for row in immutable_input_records})
            run = session.run_dir
            if operation_id in ('collision_build_01','collision_verify_01','background_build','background_verify','collision_iob_build','collision_iob_verify'):
                field_guards.append({str(Path(row['path']).resolve()) for row in immutable_input_records})
            code = "from pathlib import Path\nimport json\n"
            if operation_id == 'collision_verify_01' and fail_verify[0]:
                code += 'raise SystemExit(7)\n'
                return original(session, operation_id, executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_model',limits=kwargs['limits'],immutable_input_records=immutable_input_records)
            if operation_id == "geometry_world":
                seed = file_record(structural_seed_path(1), "required_evidence")
                plan = plan_geometry_build(
                    compiled,
                    run_directory=run,
                    seed_record=seed,
                    native_path_resource=session.input_dir
                    / "native_sources/native_run_path.lua",
                )
                op = next(
                    row
                    for row in plan.operations
                    if row["operation_id"] == operation_id
                )
                for path in op["outputs"]:
                    if path.endswith("_surface_state.json"):
                        dims = compiled.frontend_geometry["dimensions"]
                        pitch = compiled.frontend_geometry["pitch_mm"]
                        state = dict(
                            schema_version=1,
                            mode="present",
                            grid=dims,
                            pitch=[pitch] * 3,
                            scanned_nodes=None,
                            offset_nodes=None,
                        )
                        code += f'p=Path({path!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_text({json.dumps(state)!r},encoding="utf8")\n'
                    else:
                        code += f'p=Path({path!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                code += f'Path({op["optional_surface"]!r}).write_bytes(b"INERT")\nprint({op["success_marker"]!r})\n'
            elif operation_id in (
                "build_geometry",
                "verify_geometry",
                "build_model",
                "verify_model",
            ):
                if operation_id.startswith("build_"):
                    for path in (
                        run / "simion/geometry/geometry.iob",
                        run / "simion/geometry/geometry.fly2",
                    ):
                        code += f'p=Path({str(path)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                if operation_id == "verify_model":
                    code += f'm=json.loads(Path({str(session.input_dir / "compiled_model.json")!r}).read_text(encoding="utf8"));p=Path({str(run / "results/model_drive_readback.txt")!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(dict(fixture="INERT_ONLY",model_identity_sha256=m["model_identity_sha256"],groups=m["native_drive_rows"],clock=m["drive"]["clock"])),encoding="utf8")\n'
                markers = {
                    "build_geometry": "NEUTRAL_WORLD_GEOMETRY_IOB=PASS",
                    "verify_geometry": "NEUTRAL_WORLD_GEOMETRY_IOB_REOPEN=PASS",
                    "build_model": "NEUTRAL_WORLD_MODEL_BUILD=PASS",
                    "verify_model": "NEUTRAL_WORLD_MODEL_READBACK=PASS",
                }
                code += f"print({markers[operation_id]!r})\n"
            elif operation_id in ("collision_build_01", "collision_verify_01"):
                target=run/'simion/collision/collision_01.pa'
                if operation_id=='collision_build_01':
                    code+=f'p=Path({str(target)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT");p.with_suffix(".pa-surf").write_bytes(b"INERT")\n'
                mode='BUILD' if operation_id=='collision_build_01' else 'VERIFY'
                code+=f'print("RAW_COLLISION_{mode}=PASS nodes=1 metal_nodes=1 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False")\n'
            elif operation_id in ("background_build", "background_verify"):
                target=run/'simion/collision/background.pa'
                if operation_id=='background_build':code+=f'p=Path({str(target)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                marker='NUMERICAL_CARRIER_REOPEN=PASS' if operation_id=='background_build' else 'NUMERICAL_CARRIER_COLD_REOPEN=PASS'
                code+=f'print({marker!r})\n'
            elif operation_id in ("collision_iob_build", "collision_iob_verify"):
                if operation_id=='collision_iob_build':
                    for target in (run/'simion/collision/collision.iob',run/'simion/collision/collision.fly2'):
                        code+=f'p=Path({str(target)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                marker='NEUTRAL_SAMPLED_COLLISION_IOB=PASS' if operation_id=='collision_iob_build' else 'NEUTRAL_SAMPLED_COLLISION_IOB_REOPEN=PASS'
                code+=f'print({marker!r})\n'
            elif operation_id in ('build_tracking_iob', 'verify_tracking_iob'):
                if operation_id == 'build_tracking_iob':
                    for path in (run/'simion/tracking/instrument.iob', run/'inputs/structural_seed/iob_seed_placeholder_01.pa0', run/'inputs/structural_seed/iob_seed_placeholder_02.pa0'):
                        code += f'p=Path({str(path)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                marker = 'NEUTRAL_SAMPLED_TRACKING_IOB=PASS' if operation_id == 'build_tracking_iob' else 'NEUTRAL_SAMPLED_TRACKING_IOB_REOPEN=PASS'
                code += f'print({marker!r})\n'
            elif operation_id == 'track_fly':
                code += 'rows=json.loads(Path('+repr(str(session.input_dir/'canonical_source_states.json'))+').read_text(encoding="utf8"));print(\'RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}\')\n'
                code += 'for ion,row in enumerate(rows,1):\n state=dict(event="source_release",reason="none",particle_id=row["particle_id"],ion=ion,instrument_time_us=row["instrument_time_us"],mass_amu=row["mass_amu"],charge_state=row["charge_state"],instance=1);state.update({a+"_mm":row["position_"+a+"_mm"] for a in "xyz"});state.update({"v"+a+"_mm_per_us":row["velocity_"+a+"_m_s"]/1000 for a in "xyz"});print("RF_NATIVE_STATE_V1: "+json.dumps(state));state.update(event="terminal",reason="unknown",instrument_time_us=2.);print("RF_NATIVE_STATE_V1: "+json.dumps(state))\nprint("status,Fly completed. 2 splats")\n'
            else:
                raise AssertionError("unexpected operation " + operation_id)
            if operation_id == 'collision_build_01' and live_refs:
                import threading,time
                from msplatform.execution.capacity_protection import load_capacity_protection_leases,path_is_protected
                ready=Path(directory)/'fixture_child_ready';release=Path(directory)/'fixture_child_release'
                code = 'import time\nfrom pathlib import Path\n' + f'Path({str(ready)!r}).write_text("ready")\n' + f'while not Path({str(release)!r}).exists(): time.sleep(.05)\n' + code
                result=[];errors=[]
                def child():
                    try: result.append(original(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_model',limits=kwargs['limits'],immutable_input_records=immutable_input_records))
                    except BaseException as exc: errors.append(exc)
                worker=threading.Thread(target=child);worker.start()
                try:
                    deadline=time.monotonic()+30
                    while not ready.exists() and worker.is_alive() and time.monotonic()<deadline:time.sleep(.05)
                    self.assertTrue(ready.exists(),'inert child did not reach pause')
                    view=load_capacity_protection_leases(context.workspace/'artifacts')
                    for ref in live_refs:self.assertTrue(path_is_protected(Path(ref['manifest']['path']),view['protected_paths']))
                    live_checks.append(len(live_refs))
                finally:
                    release.parent.mkdir(parents=True,exist_ok=True);release.write_text('release',encoding='utf8');worker.join(30)
                if worker.is_alive():raise RuntimeError('inert child did not exit')
                if errors:raise errors[0]
                return result[0]
            return original(
                session,
                operation_id,
                executable=Path(sys.executable),
                arguments=["-I", "-B", "-c", code],
                role="GATE",
                stage="inert_model",
                limits=kwargs["limits"],
                immutable_input_records=immutable_input_records,
            )

        private = {
            "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "",
            "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "",
            "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE": "",
        }
        with (
            tempfile.TemporaryDirectory(prefix="generic-dynamic-owner-") as directory,
            patch.dict(os.environ, private),
        ):
            context, _, _ = make_context(Path(directory))
            policy = json.loads(context.stage_policy_path.read_text(encoding="utf8"))
            for name in ("build_geometry", "prepare_model", "solve_fields", "export_assembly_world_scalar"):
                policy["stages"][name] = copy.deepcopy(policy["stages"]["track"])
            policy["stages"]["solve_fields"]["limits"]["reserved_run_payload_bytes"] = 1048576
            context.stage_policy_path.write_text(json.dumps(policy), encoding="utf8")
            from common.contracts import test_execution_runtime as owner_fixture
            from msplatform.execution.owner import run_managed_stage
            from msplatform.execution.completion import no_particle_batch_completion_api
            from msplatform.results.artifacts import open_artifact
            helper=owner_fixture.NormalOwnerTests()
            counter=[0]
            def publish(kind, data, metadata, *, payload, linked=None, sources=()):
                counter[0]+=1
                def action(session):
                    records={};outputs=[]
                    for name,value in data.items():
                        target=session.declare_file(session.result_dir/(name+('.pa' if name in ('field_v','field_valid') else '.bin' if isinstance(value,bytes) else '.json')),'required_evidence')
                        target.write_bytes(value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode())
                        records[name]=file_record(session.canonical_path(target),'required_evidence');outputs.append(str(target))
                    for name,record in (linked or {}).items():
                        session.add_input(name,record)
                        if name=='field_solution_manifest':records[name]=record
                    product_id='solution' if kind=='field_solution' else 'product'
                    return dict(status='success',summary={'fixture':'INERT_ONLY'},output_paths=outputs,required_output_paths=outputs,retention_preserve_paths=[],manifest_extra_fields={'products':{product_id:dict(schema_version=1,kind=kind,status='complete',metadata=metadata,data=records)}})
                args=helper._arguments(Path(directory),action)
                args.update(run_id=f'20261115_1300{counter[0]:02d}__analysis__python__fixture',payload=payload,action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api,source_references=[{'manifest_record':ref['manifest']} for ref in sources])
                result=run_managed_stage(context,**args)
                product_id='solution' if kind=='field_solution' else 'product'
                return open_artifact({'manifest':result['manifest'],'product_id':product_id},expected_kind=kind)
            geometry_sample=publish('geometry_artifact',{'projection':case.projection},dict(backend='comsol',scope='geometry_only',native_reopen_verified=True),payload={'action':'build_comsol_geometry','assembly':case.snapshot,'projection':case.projection})
            owned_samples={}
            for name,row in case.samples.items():
                selected=open_artifact(row['reference'],expected_kind='scalar_field_samples')
                old_source=open_artifact({'manifest':selected.data_records['field_solution_manifest'],'product_id':'solution'},expected_kind='field_solution')
                source_data={key:(old_source.data_path(key).read_bytes() if key=='model' else json.loads(old_source.data_path(key).read_text(encoding='utf8'))) for key in old_source.data_records}
                solution=publish('field_solution',source_data,dict(old_source.metadata),payload={'action':'fixture_stationary'})
                sample_data={}
                for key in selected.data_records:
                    if key=='field_solution_manifest':continue
                    path=selected.data_path(key);sample_data[key]=path.read_bytes() if key in ('field_v','field_valid') else json.loads(path.read_text(encoding='utf8'))
                sample_data['report']['model_path']=str(solution.data_path('model'))
                if derived:
                    import struct
                    from msplatform.backends.simion.standalone_pa_composition import PaHeader
                    grid=sample_data['grid'];grid['dimensions']=[5,5,5];grid['maximum_mm']=[4.,4.,4.];grid['point_count']=125
                    header=PaHeader(-2,1,10000.,5,5,5,1<<28,1.,1.,1.).pack()
                    sample_data['field_v']=header+struct.pack('<125d',*([0.]*125))
                    sample_data['field_valid']=header+struct.pack('<125d',0.,*([1.]*124))
                    sample_data['report'].update(grid,invalid_count=1,fem_valid=124)
                sample=publish('scalar_field_samples',sample_data,dict(selected.metadata),payload={'action':'fixture_scalar'},linked={'field_solution_manifest':solution.reference['manifest'],'field_solution_model':solution.data_records['model']},sources=(solution.reference,))
                owned_samples[name]=dict(reference=sample.reference,request=row['request'],weights=row['weights'])
            case.geometry=geometry_sample.reference
            case.samples=owned_samples
            selected_refs=[]
            original_refs=[]
            windows=None
            if derived:
                from msplatform.backends.comsol.assembly_field_export import derive_world_scalar_support
                base_samples={};window_samples={}
                for name,row in owned_samples.items():
                    base=derive_world_scalar_support(row['reference'],context=context)
                    window=derive_world_scalar_support(row['reference'],context=context)
                    self.assertEqual(base.metadata['original_samples_reference'],row['reference'])
                    self.assertEqual(window.metadata['original_samples_reference'],row['reference'])
                    selected_refs.extend([base.reference,window.reference]);original_refs.append(row['reference'])
                    base_samples[name]=dict(reference=base.reference,request=row['request'],weights=row['weights'])
                    window_samples[name]=window.reference
                case.samples=base_samples
                windows=[dict(name='window',active_box_mm=[[1.,2.],[1.,2.],[1.,2.]],samples=window_samples)]
            drive = copy.deepcopy(case.drive)
            drive["clock"] = {"phase_reference_instrument_time_us": 0.0}
            drive["clock_authority"] = {
                "example_resource": "instrument_clock_authority_v1.json"
            }
            with patch.object(RunSession, "run_process", new=inert):
                geometry = operations.build_geometry(compiled, context=context)
                model = operations.prepare_model(
                    geometry, drive=drive, physics=RF_PHYSICS, context=context
                )
                admitted = admit_linear_samples(
                    model_reference=model.reference,
                    assembly=case.assembly,
                    geometry_artifact=case.geometry,
                    operator=case.operator,
                    samples=case.samples,
                )
                # Evaluate the same owner-published model through the real Lua consumer and adapter.
                from msplatform.backends.simion.field_closure import load_field_model

                case.model = load_field_model(model.reference).model
                case.model_reference = model.reference
                if not derived:case.test_actual_lua_model_and_scalar_adapter()
                selection=dict(geometry_artifact=case.geometry,operator=case.operator,samples=case.samples)
                if derived:live_refs.extend([*selected_refs,*original_refs])
                if windows is not None:selection['refinement_windows']=windows
                field=operations.solve_fields(model,numerics={},context=context,scalar_field_basis=selection)
                self.assertEqual(field.metadata['field_representation'],'neutral_sampled_basis_with_collision_geometry')
                self.assertEqual((field.metadata['refine_calls'],field.metadata['compute_calls'],field.metadata['fly_calls']),(0,0,0))
                from common.contracts.test_simion_rf_tracking import rf_tracking_case
                _, _, packet, _, propagation, numerics = rf_tracking_case()
                packet['clock'] = {key: case.model.document['drive']['clock'][key] for key in ('clock_epoch_id', 'authority_sha256')}
                source_names = [next(name for name, groups in case.drive['groups'].items()
                                     if any(value['kind'] == kind for value in groups.values()))
                                for kind in ('rf', 'pulse')]
                for row, name in zip(packet['rows'], source_names, strict=True):
                    row['clock_epoch_id'] = case.model.document['drive']['clock']['clock_epoch_id']
                    row['source_component_id'] = name
                    row['target_component_id'] = name
                    row['frame_id'] = 'toy_local'
                    mother = packet['mother']['records'][row['particle_id']]
                    mother['clock_epoch_id'] = case.model.document['drive']['clock']['clock_epoch_id']
                    mother['source_component_id'] = name
                    mother['target_component_id'] = name
                    mother['frame_id'] = 'toy_local'
                trajectory = operations.track(field, packet, propagation=propagation,
                    observations=dict(plane_observations=[]), numerics=numerics, context=context)
                self.assertEqual(trajectory.metadata['mother_count'], 2)
                self.assertEqual(trajectory.metadata['execution_count'], 2)
                collection = json.loads(trajectory.data_path('collection').read_text(encoding='utf8'))
                self.assertEqual([row['particle_id'] for row in collection['native_terminals']], [7, 91])
                self.assertEqual(collection['original_mother']['mother_records'], list(packet['mother']['records'].values()))
                self.assertEqual(collection['clock_epoch_id'], packet['clock']['clock_epoch_id'])
                program = (trajectory.manifest_location.parent/'simion/tracking/instrument.lua').read_text(encoding='utf8')
                self.assertIn('local rf_static_operating=true', program)
                self.assertIn('function segment.efield_adjust()', program)
                self.assertEqual(len(tracking_guards), 3)
                tracked_paths = {str(open_artifact(row['reference'], expected_kind='scalar_field_samples').data_path(key).resolve())
                                 for row in case.samples.values() for key in ('field_v', 'field_valid', 'grid')}
                for guards in tracking_guards:
                    self.assertTrue(tracked_paths <= guards)
                # Execute the actual generated Program using only portable Lua API doubles.
                import subprocess
                from msplatform.backends.simion.source import lua_value
                one = admitted['bases']['one']['records']['field_v']['path']
                prefix = r'''segment={};simion={pas={},experimental={},wb={instances={}}}
function simion.workbench_program() end
function simion.early_access() end
local count=0;local invalid=false
function simion.pas:open(path)
 local mask=path:find('field_valid',1,true)~=nil
 return {path=path,symmetry='3dplanar',nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,
 potential=function() if mask and invalid then return 0 end return 1 end}
end
simion.experimental.field_array=function(t) return {efield=function() count=count+1;local n=t.V.path==ONE and 1 or 2;return n,0,0 end} end
ion_number=1;ion_time_of_flight=0;ion_instance=1;ion_px_mm=1;ion_py_mm=1;ion_pz_mm=1
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0;ion_mass=100;ion_charge=1;ion_splat=0;ion_time_step=.001
local inst={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1},wb_to_pa_orient=function(self,x,y,z)return x,y,z end}
simion.wb.instances[1]=inst;simion.wb.instances[2]=inst
'''.replace('ONE', lua_value(one))
                suffix = r'''
assert(segment.fast_adjust==nil,'sampled collision PA must not be fast-adjusted')
segment.efield_adjust();assert(count==2);assert(math.abs(ion_dvoltsx_gu+1)<1e-9)
ion_instance=2;count=0;segment.efield_adjust();assert(count==2);assert(math.abs(ion_dvoltsx_gu+1)<1e-9)
invalid=true;local ok,err=pcall(segment.efield_adjust);assert(not ok and err:find('V_SUPPORT_UNKNOWN',1,true))
print('NEUTRAL_SAMPLED_GENERATED_PROGRAM=PASS')
'''
                script = Path(directory)/'actual_program_test.lua'
                script.write_text(prefix+program+suffix, encoding='utf8')
                checked = subprocess.run([os.environ['SIMION_LUA_EXE'], str(script)], cwd=Path(directory),
                    capture_output=True, text=True, encoding='utf8', timeout=30, check=False)
                self.assertEqual(checked.returncode, 0, checked.stdout+checked.stderr)
                self.assertIn('NEUTRAL_SAMPLED_GENERATED_PROGRAM=PASS', checked.stdout)
                # The FieldBundle basis is the sole authority and its bytes must remain valid.
                basis_path = field.data_path('sampled_basis')
                original_basis = basis_path.read_bytes()
                try:
                    basis_path.write_bytes(original_basis + b' ')
                    with patch('msplatform.execution.owner.run_managed_stage') as blocked:
                        with self.assertRaisesRegex(AssertionError, "manifest sampled_basis byte count changed"):
                            operations.track(field, packet, propagation=propagation,
                                observations=dict(plane_observations=[]), numerics=numerics, context=context)
                        blocked.assert_not_called()
                finally:
                    basis_path.write_bytes(original_basis)
                sample_paths={str(open_artifact(row['reference'],expected_kind='scalar_field_samples').data_path(key).resolve()) for row in case.samples.values() for key in ('field_v','field_valid','grid')}
                if derived:self.assertEqual(live_checks,[6]);live_refs.clear()
                self.assertEqual(len(field_guards),6)
                for guarded in field_guards:self.assertTrue(sample_paths <= guarded)
                missing=dict(case.samples);missing.pop('one')
                with patch('msplatform.execution.owner.run_managed_stage') as blocked:
                    with self.assertRaisesRegex(ValueError,'span'):
                        operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=case.geometry,operator=case.operator,samples=missing))
                    blocked.assert_not_called()
                from msplatform.execution.processes import ProcessExecutionError
                fail_verify[0]=True
                with self.assertRaises(ProcessExecutionError):
                    operations.solve_fields(model,numerics={},context=context,scalar_field_basis=selection)
                from msplatform.execution.capacity_protection import load_capacity_protection_leases
                self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
            self.assertEqual(
                admitted["model_identity_sha256"],
                model.metadata["model_identity_sha256"],
            )
            self.assertEqual(
                calls[:11],
                [
                    "geometry_world",
                    "build_geometry",
                    "verify_geometry",
                    "build_model",
                    "verify_model",
                    "collision_build_01", "collision_verify_01", "background_build",
                    "background_verify", "collision_iob_build", "collision_iob_verify",
                ],
            )
