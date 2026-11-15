"""Existing managed scalar test inert native leaves, never native qualification."""
import json
import sys
from pathlib import Path
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.io.manifest_records import file_record


def inert_dynamics_code(numerics_path):
    """Emit fixture marker from frozen numerics; unspecified keeps existing stub default."""
    return ("numerics=json.loads(Path(" + repr(str(numerics_path)) + ").read_text(encoding='utf8'));"
            "grouped=numerics.get('grouped',1);"
            "assert type(grouped) is int and grouped in (0,1);"
            "print('RF_DYNAMICS_V1: '+json.dumps(dict(grouped=grouped,repulsion='none',relativity=0,segment_global=1)))\n")


def make_inert(self, compiled, original, calls, field_guards, tracking_guards, fail_verify, live_refs, live_checks, directory, context):
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
            code += 'rows=json.loads(Path('+repr(str(session.input_dir/'canonical_source_states.json'))+').read_text(encoding="utf8"))\n'
            code += inert_dynamics_code(session.input_dir/'tracking_numerics.json')
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

    return inert
