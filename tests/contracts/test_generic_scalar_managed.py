"""Managed model-to-sample witness; inert leaves only, no native qualification."""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.contracts import test_generic_scalar_binding as fixture
from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context
from msplatform.backends.simion import operations
from msplatform.backends.simion.generic_scalar_binding import admit_linear_samples
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(os.name == "nt", "Windows process guard required")
class GenericScalarManagedTests(unittest.TestCase):
    def test_public_model_then_public_scalar_admission(self):
        case = fixture.GenericScalarTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        from msplatform.backends.simion.model import model_geometry

        compiled = model_geometry(case.model)
        original = RunSession.run_process
        calls = []
        field_guards = []
        fail_verify = [False]

        def inert(session, operation_id, *, immutable_input_records=(), **kwargs):
            if kwargs["role"] != "SIMION":
                return original(
                    session,
                    operation_id,
                    immutable_input_records=immutable_input_records,
                    **kwargs,
                )
            calls.append(operation_id)
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
            else:
                raise AssertionError("unexpected operation " + operation_id)
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
            for name in ("build_geometry", "prepare_model", "solve_fields"):
                policy["stages"][name] = copy.deepcopy(policy["stages"]["track"])
            policy["stages"]["solve_fields"]["limits"]["reserved_run_payload_bytes"] = 1048576
            context.stage_policy_path.write_text(json.dumps(policy), encoding="utf8")
            from tests.contracts import test_execution_runtime as owner_fixture
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
                sample=publish('scalar_field_samples',sample_data,dict(selected.metadata),payload={'action':'fixture_scalar'},linked={'field_solution_manifest':solution.reference['manifest'],'field_solution_model':solution.data_records['model']},sources=(solution.reference,))
                owned_samples[name]=dict(reference=sample.reference,request=row['request'],weights=row['weights'])
            case.geometry=geometry_sample.reference
            case.samples=owned_samples
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
                case.test_actual_lua_model_and_scalar_adapter()
                field=operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=case.geometry,operator=case.operator,samples=case.samples))
                self.assertEqual(field.metadata['field_representation'],'neutral_sampled_basis_with_collision_geometry')
                self.assertEqual((field.metadata['refine_calls'],field.metadata['compute_calls'],field.metadata['fly_calls']),(0,0,0))
                with self.assertRaisesRegex(ValueError, 'static world tracking requires original births'):
                    operations.track(field,None,propagation={},observations={},numerics={},context=context)
                sample_paths={str(open_artifact(row['reference'],expected_kind='scalar_field_samples').data_path(key).resolve()) for row in case.samples.values() for key in ('field_v','field_valid','grid')}
                self.assertEqual(len(field_guards),6)
                for guarded in field_guards:self.assertTrue(sample_paths <= guarded)
                from msplatform.backends.simion import generic_geometry, mr_geometry
                from msplatform.components import cad_geometry
                for module in (generic_geometry, mr_geometry, cad_geometry):
                    source = str(Path(module.__file__).resolve())
                    copy_name = module.__name__.replace('.', '_') + '.py'
                    for guarded in field_guards:
                        self.assertIn(source, guarded)
                        self.assertTrue(any(Path(path).name == copy_name and 'native_sources' in Path(path).parts for path in guarded))

                missing=dict(case.samples);missing.pop('one')
                with patch('msplatform.execution.owner.run_managed_stage') as blocked:
                    with self.assertRaisesRegex(ValueError,'span'):
                        operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=case.geometry,operator=case.operator,samples=missing))
                    blocked.assert_not_called()
                from msplatform.execution.processes import ProcessExecutionError
                fail_verify[0]=True
                with self.assertRaises(ProcessExecutionError):
                    operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=case.geometry,operator=case.operator,samples=case.samples))
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
