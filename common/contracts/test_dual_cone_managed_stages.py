"""Actual managed independent stages with explicitly inert observed native outputs."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.io.manifest_records import file_record
from common.contracts.test_dual_cone_transport_execution import request, ROOT
from common.contracts.test_dual_cone_stages import CLOCK


class ManagedIndependentStagesTests(unittest.TestCase):
    def test_geometry_model_and_fields_are_actual_sourcefree_managed_publications(self):
        from common.contracts.test_execution_runtime import NormalOwnerTests
        from msplatform.workflows.dual_cone_stages import build_geometry, prepare_model, solve_fields, track_fields
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger
        from msplatform.execution.capacity_protection import load_capacity_protection_leases

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = NormalOwnerTests()
            context = helper._context(root)
            capacity = root / "capacity.json"
            capacity.write_text(json.dumps(helper._policy()))
            simion = root / "simion.exe"
            simion.write_bytes(b"INERT_NOT_EXECUTABLE")
            stages = root / "stages.json"
            stage = dict(
                limits=dict(
                    wall_clock_seconds=120,
                    transient_run_directory_bytes=128 * 1024**2,
                    process_tree_working_set_bytes=1024**3,
                    minimum_system_available_memory_bytes=1,
                    compact_final_retained_bytes=128 * 1024**2,
                    automatic_retry_count=0,
                ),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="inert stage closure"),
            )
            stages.write_text(
                json.dumps(
                    dict(
                        schema_version=1,
                        role="execution_stage_policy",
                        stages={
                            "dual_cone_geometry": stage,
                            "dual_cone_model": stage,
                            "dual_cone_fields": stage,
                            "dual_cone_saved_fly": stage,
                        },
                    )
                )
            )
            context = replace(
                context, capacity_policy_path=capacity, stage_policy_path=stages, tools={"simion": simion}
            )
            artifacts = context.workspace / "artifacts"
            artifacts.mkdir(parents=True)
            initialize_capacity_ledger(artifacts, objects=[])
            calls = []

            def observed(_context, **kwargs):
                args = kwargs["arguments"]
                run = kwargs["working_directory"]
                solver = run / "simion"
                solver.mkdir(exist_ok=True)
                stdout = "INERT_SOFTWARE_NOT_SIMION\n"
                if "-RequestPath" in args:
                    selected = json.loads(Path(args[args.index("-RequestPath") + 1]).read_text(encoding="utf-8-sig"))
                    outputs = []
                    releases = {}
                    for row in selected["copies"]:
                        original = row["source_record"]
                        target = Path(row["destination"])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(Path(original["path"]).read_bytes())
                        actual = file_record(target, original["retention_role"])
                        outputs.append(actual)
                        for record in (original, actual):
                            releases[record["path"]] = dict(record, write_delete_guarded=False)
                    Path(selected["receipt_path"]).write_text(
                        json.dumps(
                            dict(
                                schema_version=1,
                                role="payload_materialization",
                                status="success",
                                primary=None,
                                secondary_errors=[],
                                outputs=outputs,
                                source_and_destination_releases=list(releases.values()),
                            )
                        )
                    )
                elif "build_frontend_geometry.lua" in " ".join(args):
                    (solver / "dual_cone_tandem.pa#").write_bytes(b"INERT_RAW_NOT_PA")
                    (solver / "dual_cone_tandem.pa-surf").write_bytes(b"INERT_SURFACE")
                    (solver / "dual_cone_surface.csv").write_text("0,0,0,0.25,nil,nil\n")
                    stdout += "BUILD_GEOMETRY=PASS\n"
                elif "refine_rf_field_family.lua" in " ".join(args):
                    for eid in (0, 1, 2, 3, 11, 12, 21, 22):
                        (solver / ("dual_cone_tandem.pa" + str(eid))).write_bytes(b"INERT_RESPONSE")
                    stdout += "INDEPENDENT_RF_REFINE=PASS\n"
                elif "audit_rf_field_family.lua" in " ".join(args):
                    (run / "results/field_audit.json").write_text(
                        '{"status":"success","checked_domains":["dual_cone"]}'
                    )
                    stdout += "INDEPENDENT_RF_FIELDS_READBACK=PASS\n"
                elif "build_tracking_iob.lua" in " ".join(args):
                    tracking = run / "transport/solver/simion"
                    if "verify" not in args:
                        (tracking / "transport.iob").write_bytes(b"INERT_SAVED_FIELD_IOB")
                    stdout += "DUAL_CONE_TRACKING_IOB=PASS\nDUAL_CONE_TRACKING_IOB_REOPEN=PASS\n"
                elif "fly" in args:
                    from common.simion.test_analyze_terminal_plane import HEADER

                    result = run / "transport/results"
                    (result / "particle_final_state.csv").write_text(
                        HEADER + "".join(f"{i},10,25.5,25.5,121.75,0,0,1,0\n" for i in range(1, 101))
                    )
                    (result / "trajectory_samples.csv").write_text("INERT_TRAJECTORY_NOT_NATIVE")
                    stdout += "status,Fly completed. 100 splats, 0.1 seconds\n"
                    actual = {Path(row["path"]) for row in kwargs["immutable_input_records"]}
                    self.assertTrue(original_family_paths.issubset(actual))
                    self.assertFalse(any(path.is_relative_to(run) for path in original_family_paths))
                else:
                    build = "verify_geometry" not in args and "verify_model" not in args
                    model = "build_model_iob.lua" in " ".join(args)
                    if build:
                        (solver / "model.iob").write_bytes(b"INERT_ZERO_SOURCE_IOB")
                        (solver / "model.fly2").write_text("particles{coordinates=0,}\n")
                    if model:
                        if not build:
                            (run / "results/model_readback.txt").write_text("INERT_SEVEN_GROUP_READBACK_NOT_NATIVE")
                        stdout += "DUAL_CONE_MODEL_BUILD=PASS\nDUAL_CONE_MODEL_READBACK=PASS\n"
                    else:
                        stdout += "DUAL_CONE_GEOMETRY_IOB=PASS\nDUAL_CONE_GEOMETRY_IOB_REOPEN=PASS\n"
                calls.append(list(args))
                for key in ("stdout_path", "stderr_path", "usage_path"):
                    kwargs[key].write_text(stdout if key == "stdout_path" else "{}")
                return dict(
                    observation=dict(exit_code=0, root_process_id=os.getpid(), root_process_started_at_utc_ticks=12345),
                    host_release=dict(
                        inherited=False, token="inert", error=None, result=dict(status="released", token="inert")
                    ),
                )

            values = request()
            numerics = {key: value for key, value in values["numerics"].items() if key != "trajectory"}
            clockroot = root / "clock"
            clockroot.mkdir()
            clockrows = {}
            for key, name in [
                ("contract", "instrument_clock_authority_v1.json"),
                ("authority", "instrument_epoch_v1.json"),
            ]:
                path = clockroot / name
                path.write_bytes((ROOT / "src/msplatform/examples" / name).read_bytes())
                clockrows[key] = file_record(path, "required_evidence")
            clockrows["data_root"] = str(clockroot)
            with patch("msplatform.execution.run_session.run_observed_process", side_effect=observed):
                geometry = build_geometry(resolved=values["resolved"], numerics=numerics, context=context)
                self.assertEqual(geometry.metadata["sampled_particles"], 0)
                self.assertEqual(
                    geometry.data_path("zero_particle_format_control").read_text(), "particles{coordinates=0,}\n"
                )
                model = prepare_model(
                    geometry,
                    electric_field=values["science"]["electric_field"],
                    clock=CLOCK,
                    physics=RF_PHYSICS,
                    clock_authority_reference=clockrows,
                    context=context,
                )
                self.assertEqual(model.metadata["field_status"], "not_solved")
                import copy
                inconsistent=copy.deepcopy(numerics)
                inconsistent['pa']['cell_mm_xyz']['x']*=2
                with patch('msplatform.workflows.dual_cone_stages.run_managed_stage',
                           side_effect=RuntimeError('INERT_OWNER_WOULD_HAVE_LAUNCHED')) as invalid_owner:
                    with self.assertRaisesRegex(ValueError,'field numerics cannot redefine'):
                        solve_fields(model,numerics=inconsistent,context=context)
                    invalid_owner.assert_not_called()
                fields = solve_fields(model, numerics=numerics, context=context)
            self.assertEqual(len(calls), 9)
            self.assertFalse(any("fly" in args for args in calls))
            self.assertEqual(sum("refine_rf_field_family.lua" in " ".join(args) for args in calls), 1)
            self.assertEqual(fields.metadata["field_status"], "available")
            self.assertEqual(fields.metadata["source_status"], "not_requested")
            self.assertEqual(load_capacity_protection_leases(artifacts)["audit"], [])
            import copy

            changed_drive = copy.deepcopy(values["science"]["electric_field"])
            changed_drive["stage_1"]["rf_amplitude_v_zero_to_peak_per_group"] = 123
            with patch("msplatform.execution.run_session.run_observed_process", side_effect=observed):
                changed_model = prepare_model(
                    geometry,
                    electric_field=changed_drive,
                    clock=CLOCK,
                    physics=RF_PHYSICS,
                    clock_authority_reference=clockrows,
                    context=context,
                )
                reused = solve_fields(changed_model, numerics=numerics, context=context, reuse_fields_reference=fields)
            self.assertEqual(len(calls), 13)
            self.assertEqual(reused.metadata["refine_calls"], 0)
            self.assertIs(reused.metadata["fields_reused"], True)
            self.assertEqual(reused.metadata["family_producer_reference"], fields.reference)
            selected = json.loads(reused.data_path("compiled_model").read_text())
            self.assertEqual(selected["electric_field"]["stage_1"]["rf_amplitude_v_zero_to_peak_per_group"], 123)
            gas_reference = self._gas_source(context)
            sds = root / "sds"
            sds.mkdir()
            for name in ("collision_sds.lua", "mbmr.dat", "textfilelib.lua", "arraylib.lua", "m_defs.dat"):
                (sds / name).write_text("INERT_SDS_NOT_VENDOR")
            original_family_paths = {
                fields.data_path(name)
                for name in [
                    "family_raw",
                    "family_surface",
                    "family_carrier",
                    "surface_witnesses",
                    *["response_" + str(eid) for eid in (1, 2, 3, 11, 12, 21, 22)],
                ]
            }
            original_records = {path: file_record(path, "required_evidence") for path in original_family_paths}
            with patch("msplatform.execution.run_session.run_observed_process", side_effect=observed):
                trajectory = track_fields(
                    reused,
                    gas_field_reference=gas_reference,
                    source_spec_path=ROOT
                    / "projects/dual_cone_tandem_quadrupole_ion_interface/config/cylindrical_ion_source.json",
                    numerics_path=ROOT
                    / "projects/dual_cone_tandem_quadrupole_ion_interface/config/simion_solver_numerics.json",
                    interface_path=ROOT
                    / "projects/dual_cone_tandem_quadrupole_ion_interface/config/gas_field_interface.json",
                    collision_science=values["science"]["gas"],
                    collision_sds_dir=sds,
                    context=context,
                )
            self.assertEqual(len(calls), 16)
            self.assertEqual(sum("refine_rf_field_family.lua" in " ".join(args) for args in calls), 1)
            self.assertEqual(trajectory.metadata["refine_calls"], 0)
            self.assertEqual(trajectory.metadata["execution_count"], 100)
            for name in (
                "family_raw",
                "family_surface",
                "family_carrier",
                "surface_witnesses",
                *["response_" + str(eid) for eid in (1, 2, 3, 11, 12, 21, 22)],
            ):
                self.assertEqual(reused.data_path(name), fields.data_path(name))
            self.assertIs(trajectory.metadata["saved_field_reuse"], True)
            self.assertEqual(load_capacity_protection_leases(artifacts)["audit"], [])
            for path, original in original_records.items():
                self.assertEqual(file_record(path, "required_evidence"), original)
            changed_source = copy.deepcopy(values["source_spec"])
            changed_source["sampling"]["seed"] += 1
            changed_numerics = copy.deepcopy(values["numerics"])
            changed_numerics["trajectory"]["sample_interval_us"] = 2
            source_path = root / "changed_source.json"
            source_path.write_text(json.dumps(changed_source))
            numerics_path = root / "changed_numerics.json"
            numerics_path.write_text(json.dumps(changed_numerics))
            with patch("msplatform.execution.run_session.run_observed_process", side_effect=observed):
                changed_trajectory = track_fields(
                    reused,
                    gas_field_reference=gas_reference,
                    source_spec_path=source_path,
                    numerics_path=numerics_path,
                    interface_path=ROOT
                    / "projects/dual_cone_tandem_quadrupole_ion_interface/config/gas_field_interface.json",
                    collision_science=values["science"]["gas"],
                    collision_sds_dir=sds,
                    context=context,
                )
            self.assertEqual(len(calls), 19)
            self.assertEqual(sum("refine_rf_field_family.lua" in " ".join(args) for args in calls), 1)
            self.assertEqual(changed_trajectory.metadata["execution_count"], 100)
            self.assertEqual(changed_trajectory.metadata["mother_count"], 100)
            self.assertNotEqual(
                trajectory.data_path("source_csv").read_bytes(), changed_trajectory.data_path("source_csv").read_bytes()
            )
            configuration = changed_trajectory.manifest_location.parent / "transport/solver/simion/run_config.lua"
            self.assertIn("trajectory_sample_interval_us=2", configuration.read_text())
            self.assertEqual(load_capacity_protection_leases(artifacts)["audit"], [])
            for path, original in original_records.items():
                self.assertEqual(file_record(path, "required_evidence"), original)

    def _gas_source(self, context):
        import csv, hashlib
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import _write_fixture
        from msplatform.execution.capacity_ledger import record_capacity_object

        config = ROOT / "projects/dual_cone_tandem_quadrupole_ion_interface/config"
        source = context.workspace / "artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/runs/inert-gas"
        source.mkdir(parents=True)
        csv_path, metadata = _write_fixture(source)
        with csv_path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            names = reader.fieldnames
            rows = list(reader)
        domain = json.loads((config / "gas_field_interface.json").read_text())["runtime_artifact_contract"]["domain"]
        radii = [
            domain["minimum_radius_mm"] + (domain["maximum_radius_mm"] - domain["minimum_radius_mm"]) * i / 9
            for i in range(10)
        ]
        axial = [domain["minimum_z_mm"] + (domain["maximum_z_mm"] - domain["minimum_z_mm"]) * i / 9 for i in range(10)]
        for row in rows:
            row.update(r_mm=radii[int(row["r_index"])], z_mm=axial[int(row["z_index"])])
        with csv_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=names)
            writer.writeheader()
            writer.writerows(rows)
        meta = json.loads(metadata.read_text())
        meta["grid"] = {"r_values_mm": radii, "z_values_mm": axial}
        meta["field_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        metadata.write_text(json.dumps(meta))
        identity = dict(
            project="dual_cone_tandem_quadrupole_ion_interface",
            run_id=source.name,
            mode="axisymmetric_gas_flow_screening",
        )
        runtime = source / "run_config.json"
        runtime.write_text(json.dumps(identity))
        inputs = {}
        for key, name in [
            ("gas_flow_science", "gas_flow_science.json"),
            ("comsol_solver_numerics", "comsol_solver_numerics.json"),
            ("resolved_geometry", "resolved_geometry.json"),
        ]:
            path = source / name
            path.write_bytes((config / name).read_bytes())
            inputs[key] = file_record(path, "required_evidence")
        manifest = source / "run_manifest.json"
        manifest.write_text(
            json.dumps(
                dict(
                    schema_version=2,
                    role="simulation_run_manifest",
                    status="success",
                    **identity,
                    run_config=file_record(runtime, "required_evidence"),
                    inputs=inputs,
                    outputs=[file_record(path, "required_evidence") for path in (csv_path, metadata)],
                )
            )
        )
        record_capacity_object(
            context.workspace / "artifacts",
            path=source,
            object_class="light_evidence",
            bytes_count=sum(p.stat().st_size for p in source.iterdir()),
            status="ready",
            owner="inert-gas",
        )
        return dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")

    def test_public_saved_fly_rejects_missing_unknown_and_tampered_sources_before_owner(self):
        from msplatform.workflows.dual_cone_stages import track_fields
        from common.contracts.test_dual_cone_stages import fields_fixture

        for scenario in ("missing", "unknown_writer", "tampered"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                reference, _ = fields_fixture(
                    root, unknown=scenario == "unknown_writer", missing="response_22" if scenario == "missing" else None
                )
                if scenario == "tampered":
                    (root / "dual_cone.pa22").write_text("CHANGED_ORIGINAL_PUBLISHED_FIELD")
                with patch("msplatform.workflows.dual_cone_stages.run_managed_stage") as owner:
                    expected_error = AssertionError if scenario == "tampered" else ValueError
                    with self.assertRaises(expected_error):
                        track_fields(
                            reference,
                            gas_field_reference=None,
                            source_spec_path=root / "absent-source.json",
                            numerics_path=root / "absent-numerics.json",
                            collision_science={},
                            interface_path=root / "absent-interface.json",
                            collision_sds_dir=root / "absent-sds",
                            context=None,
                        )
                    owner.assert_not_called()

    def test_saved_model_program_consumes_selected_seven_group_drive(self):
        import math, subprocess
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.dual_cone_transport import _render_run_config
        from msplatform.backends.simion.dual_cone_stages import render_model_stage_configuration
        from common.contracts.test_dual_cone_stages import model
        from common.contracts.test_dual_cone_transport_execution import LUA

        if not LUA.is_file():
            self.skipTest("plain Lua unavailable; no native fallback")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = request()
            selected = model(amplitude=123)
            (root / "model_drive_configuration.lua").write_text(render_model_stage_configuration(selected))
            for name in ("model_drive.lua", "rf_drive.lua", "single_flight_pulse_hook.lua", "voltage_waveforms.lua"):
                (root / name).write_bytes(native_resource_path(name).read_bytes())
            (root / "simion_rf_drive.lua").write_bytes(native_resource_path("rf_drive.lua").read_bytes())
            config = root / "run_config.lua"
            config.write_text(
                _render_run_config(
                    mode="c0_gem_smoke",
                    science=values["science"],
                    numerics=values["numerics"],
                    resolved=values["resolved"],
                    solver=root,
                    model_projection=selected,
                )
            )
            time = 3.125
            expected = {}
            for row in selected["native_drive_rows"]:
                if row["kind"] == "static":
                    voltage = row["voltage_v"]
                else:
                    phase = 2 * math.pi * row["frequency_hz"] * time / 1e6 + row["phase_rad"]
                    wave = math.sin(phase) if row["waveform"] == "sine" else math.cos(phase)
                    voltage = row["common_mode_v"] + row["dc_v"] + row["polarity"] * row["rf_amplitude_v"] * wave
                expected[row["native_targets"][0]["electrode_id"]] = voltage
            checks = "\n".join(
                f"assert(math.abs(adj_elect[{eid}]-({value:.17g}))<1e-10,'selectedmodelgroup{eid} differs')"
                for eid, value in expected.items()
            )
            script = root / "wire.lua"
            script.write_text(
                "simion={workbench_program=function()segment={}end}\n"
                + "os.getenv=function()return "
                + json.dumps(str(config))
                + " end\n"
                + "local stream=assert(io.open("
                + json.dumps(str(native_resource_path("dual_cone_gas_assisted_transport.lua")))
                + ",'rb'));local code=stream:read('*a');stream:close()\n"
                + "assert(loadstring(code:gsub('adjustable%s+','')))()\nadj_elect={};ion_time_of_flight="
                + str(time)
                + "\nsegment.fast_adjust()\n"
                + checks
                + "\nprint('SELECTED_SEVEN_GROUP_MODEL=PASS')\n"
            )
            result = subprocess.run([str(LUA), str(script)], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SELECTED_SEVEN_GROUP_MODEL=PASS", result.stdout)
