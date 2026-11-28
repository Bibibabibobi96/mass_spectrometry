from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.io.file_identity import file_sha256
from msplatform.backends.simion.standalone_pa_response_set import ResponseExport, write_standalone_pa_response_set
from msplatform.backends.simion.oa_focus_identity import identity
from msplatform.workflows.oa_focus_mr_runtime_receipt import (
    MrRuntimeReceiptError, project, write_receipt,
)
from msplatform.workflows.oa_focus_workflow import (
    ComponentFocusWorkflowError,
    compile_workflow,
)


class ComponentFocusWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = (Path(__file__).resolve().parents[4] / "src/msplatform/components/orthogonal_accelerator")
        self.campaign = json.loads((self.project / "config" / "two_zone_component_focus_campaign.json").read_text(encoding="utf-8"))

    def _request(self) -> dict:
        return {
            "schema_version": 1,
            "role": "orthogonal_accelerator_component_focus_request",
            "consumer_project_id": "multi_reflection_tof",
            "geometry_profile_id": self.campaign["geometry_profile_id"],
            "time_focus": {
                "final_energy_per_charge_v": 4371.2351565,
                "focus_plane_offset_from_exit_mm": 0.0,
                "gap1_voltage_drop_bounds_v": [100.0, 1500.0],
            },
            "numerics": {**self.campaign["numerics"], "mesh_mm_per_gu": [0.25, 0.25, 0.1]},
            "acceptance": self.campaign["acceptance"],
            "simion_projection": self.campaign["simion_projection"],
        }

    def test_explicit_request_mesh_roundtrip_and_missing_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, release = root / "request.json", root / "release.json"
            release.write_text(json.dumps(self.campaign["release_spec"]), encoding="utf-8")
            value = self._request()
            del value["numerics"]["mesh_mm_per_gu"]
            request.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit PA mesh"):
                compile_workflow(request, release)
            value["numerics"]["mesh_mm_per_gu"] = [.2, .5, .2]
            request.write_text(json.dumps(value), encoding="utf-8")
            result = compile_workflow(request, release)
            self.assertEqual(result["pa_plan"]["numerical_domain"]["mesh_mm_per_gu"], [.2, .5, .2])
            self.assertEqual(result["campaign"]["numerics"], self.campaign["numerics"])
            self.assertEqual(result["request_sha256"], file_sha256(request).lower())

    def test_compiles_one_frozen_campaign_and_pa_plan_from_caller_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, release = root / "request.json", root / "release.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            release.write_text(json.dumps(self.campaign["release_spec"]), encoding="utf-8")
            result = compile_workflow(request, release)
        self.assertEqual(result["consumer_project_id"], "multi_reflection_tof")
        self.assertEqual(result["campaign"]["release_spec"], self.campaign["release_spec"])
        self.assertEqual(result["pa_plan"]["geometry_profile_id"], self.campaign["geometry_profile_id"])
        self.assertEqual(result["pa_plan"]["layout"]["source_cylinder"], {"radius_mm": 1.0, "height_mm": 1.0})
        self.assertAlmostEqual(result["campaign"]["operating_point"]["electrode_voltages_v"][1],
                               self.campaign["operating_point"]["electrode_voltages_v"][1], places=5)
        self.assertEqual(result["campaign"]["operating_point"]["instance_center_y_mm"], 0.0)

    def test_velocity_only_release_change_does_not_change_pa_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, release = root / "request.json", root / "release.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            release.write_text(json.dumps(self.campaign["release_spec"]), encoding="utf-8")
            first = compile_workflow(request, release)
            changed = json.loads(release.read_text(encoding="utf-8"))
            changed["sampling"]["kinetic_energy"]["center_ev"] = 4.961131691875479
            changed["sampling"]["nominal_direction"] = [0.0, 1.0, 0.0]
            release.write_text(json.dumps(changed), encoding="utf-8")
            second = compile_workflow(request, release)
        builder = self.project.parents[1] / "backends/simion/resources" / "build_component_focus_pa.lua"
        self.assertEqual(identity(first["pa_plan"], builder, Path(__file__)),
                         identity(second["pa_plan"], builder, Path(__file__)))
        self.assertNotEqual(first["release_spec_sha256"], second["release_spec_sha256"])
        self.assertGreater(second["campaign"]["operating_point"]["instance_center_y_mm"], 0.9)

    def test_mr_release_is_frozen_unchanged_while_provider_derives_its_voltage_pair(self) -> None:
        release = (self.project.parents[3] / "src/msplatform/components/multi_reflection_tof" /
                   "config" / "accelerator_component_release_n100.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            result = compile_workflow(request, release)
        original = json.loads(release.read_text(encoding="utf-8"))
        self.assertEqual(result["campaign"]["release_spec"]["geometry"]["center_mm"][:2], original["geometry"]["center_mm"][:2])
        self.assertEqual(result["campaign"]["release_spec"]["geometry"]["center_mm"][2], 32.0)
        self.assertAlmostEqual(result["pa_plan"]["theory_seed"]["release_position_from_repeller_mm"], 2.0)
        self.assertEqual(result["campaign"]["operating_point"]["electrode_voltages_v"],
                         self.campaign["operating_point"]["electrode_voltages_v"])
        self.assertGreater(result["campaign"]["operating_point"]["instance_center_y_mm"], 0.9)
        self.assertEqual(
            result["pa_plan"]["layout"]["source_cylinder"],
            {"radius_mm": 1.0, "height_mm": 1.0},
        )

    def test_rejects_non_n100_or_wrong_frame_before_any_cache_or_solver_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, release = root / "request.json", root / "release.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            invalid = json.loads(json.dumps(self.campaign["release_spec"]))
            invalid["particle_count"] = 99
            release.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ComponentFocusWorkflowError, "N=100"):
                compile_workflow(request, release)

    def test_parent_runner_uses_existing_children_once_and_records_one_receipt(self) -> None:
        resources = self.project.parents[1] / "backends/simion/resources"
        profile = json.loads((self.project / "config/execution_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
        owner = (self.project.parents[1] / "workflows/oa_focus_component.py").read_text(encoding="utf-8")
        controller = (self.project.parents[1] / "workflows/oa_focus_controller.py").read_text(encoding="utf-8")
        self.assertEqual(profile["steps"][0]["shell"], "python")
        self.assertEqual(profile["steps"][0]["entrypoint"], "src/msplatform/workflows/oa_focus_component.py")
        self.assertIn("--powershell-exe", profile["steps"][0]["arguments"])
        self.assertNotIn("New-RunPackage", owner)
        self.assertEqual(owner.count("run_focus_controller_campaign("), 1)
        self.assertEqual(owner.count("action='flight'"), 1)
        self.assertIn("action='field-contrast'", owner)
        self.assertIn("action='fast-adjust'", owner)
        self.assertIn("component_focus_workflow_receipt.json", owner)
        self.assertIn("one_store_cache_claim__at_most_one_native_build", owner)
        self.assertIn("standalone_native_store", owner)
        self.assertIn("recover_managed_native_store_stage", owner)
        self.assertIn("materialize_focus_runtime", controller)
        for name in ("component_focus_flight_action.ps1", "component_focus_field_contrast_action.ps1",
                     "component_focus_fast_adjust_action.ps1"):
            action = (resources / name).read_text(encoding="utf-8")
            self.assertNotIn("New-RunPackage", action)
            self.assertNotIn("Complete-FailedRun", action)
            self.assertNotIn("Write-VerifiedRunManifest", action)
            self.assertIn("oa_focus_action_publication", action)

    def _store_focus_context(self, root: Path):
        from dataclasses import replace
        from tests.contracts.test_execution_runtime import NormalOwnerTests
        helper = NormalOwnerTests()
        context = helper._context(root)
        capacity = root / "capacity.json"
        capacity.write_text(json.dumps(helper._policy()), encoding="utf-8")
        stage = dict(limits=dict(wall_clock_seconds=120, transient_run_directory_bytes=16*1024**2,
            process_tree_working_set_bytes=1024**3, minimum_system_available_memory_bytes=1,
            compact_final_retained_bytes=16*1024**2, automatic_retry_count=0),
            artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="inert focus workflow"))
        policy = root / "stages.json"
        policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
            stages={"oa_focus_workflow": stage, "oa_focus_controller": stage})), encoding="utf-8")
        return replace(context, capacity_policy_path=capacity, stage_policy_path=policy)

    def _fake_focus_pa(self, root: Path) -> dict:
        (root / "results").mkdir(parents=True)
        controller = root / "runtime/orthogonal_accelerator_focus.pa0"
        controller.parent.mkdir()
        controller.write_bytes(b"INERT_NOT_PA")
        result = root / "results/component_focus_pa_result.json"
        result.write_text(json.dumps({"cache_key": "inert", "generation_sha256": "inert",
            "runtime_controller_path": str(controller)}), encoding="utf-8")
        (root / "results/component_focus_pa_plan.json").write_text("{}", encoding="utf-8")
        (root / "run_manifest.json").write_text("{}", encoding="utf-8")
        return {"run_directory": str(root)}

    @staticmethod
    def _analysis() -> dict:
        return {"status": "candidate_complete", "hard_gate": {
            "complete_transport_passed": True, "exit_slow_energy_passed": True,
            "exit_axial_energy_passed": True, "exit_transverse_energy_passed": True,
            "exit_transverse_velocity_bias_passed": True}, "exit_energy_assessment": {"passed": True}}

    def _fake_focus_flight(self, root: Path, *, complete: bool) -> dict:
        (root / "results").mkdir(parents=True)
        (root / "inputs").mkdir(parents=True)
        analysis = self._analysis()
        if not complete:
            analysis["status"] = "candidate_incomplete"
        (root / "results/focus_analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
        (root / "inputs/release_receipt.json").write_text("{}", encoding="utf-8")
        (root / "run_manifest.json").write_text("{}", encoding="utf-8")
        summary = dict(status="candidate_complete" if complete else "candidate_incomplete")
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return {"run_directory": str(root), "run_id": root.name}

    def test_python_cli_rejects_missing_request_before_store_registration(self) -> None:
        import shutil
        import subprocess
        import sys
        from msplatform.storage import ArtifactStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ArtifactStore(root / "store")
            result = subprocess.run([sys.executable, "-m", "msplatform.workflows.oa_focus_component",
                "--action", "workflow", "--run-id", "20261128_020002__test__python__focus-missing",
                "--workspace-root", str(root), "--store-root", str(store.root),
                "--powershell-exe", shutil.which("pwsh"), "--request-path", str(root / "missing-request.json"),
                "--release-spec-path", str(root / "missing-release.json")], cwd=root,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
            self.assertNotEqual(result.returncode, 0)
            with store._db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_store_parent_publishes_focus_and_mr_receipt(self) -> None:
        from msplatform.storage import ArtifactStore
        from msplatform.workflows.oa_focus_component import run_component_focus
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            release = root / "release.json"
            release.write_text(json.dumps(self.campaign["release_spec"]), encoding="utf-8")
            context = self._store_focus_context(root)
            store = ArtifactStore(root / "store")
            pa = self._fake_focus_pa(root / "pa")
            flight = self._fake_focus_flight(root / "flight", complete=True)
            with patch("msplatform.workflows.oa_focus_component.run_focus_controller_campaign", return_value=pa), \
                 patch("msplatform.workflows.oa_focus_component._run_action", return_value=flight), \
                 patch("msplatform.workflows.oa_focus_component.project", return_value={"role": "orthogonal_accelerator_mrtof_runtime_receipt"}):
                result = run_component_focus(context, artifact_store=store, request_path=request,
                    release_spec_path=release, run_id="20261128_020000__test__python__focus-store-parent")
            self.assertEqual(result["status"], "success")
            self.assertEqual(store.run_status(result["store_run_id"])["execution_status"], "succeeded")
            run = Path(result["run_directory"])
            self.assertTrue((run / "results/component_focus_workflow_receipt.json").is_file())
            self.assertTrue((run / "results/mrtof_runtime_receipt.json").is_file())
            self.assertEqual(request.read_bytes(), json.dumps(self._request()).encode())
            self.assertEqual(release.read_bytes(), json.dumps(self.campaign["release_spec"]).encode())

    def test_store_parent_withholds_receipt_when_fast_adjust_is_exhausted(self) -> None:
        from msplatform.storage import ArtifactStore
        from msplatform.workflows.oa_focus_component import run_component_focus
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            release = root / "release.json"
            release.write_text(json.dumps(self.campaign["release_spec"]), encoding="utf-8")
            store = ArtifactStore(root / "store")
            pa = self._fake_focus_pa(root / "pa")
            flight = self._fake_focus_flight(root / "flight", complete=False)
            contrast = self._fake_focus_flight(root / "contrast", complete=False)
            Path(contrast["run_directory"], "results/two_zone_ideal_field_contrast.json").write_text("{}", encoding="utf-8")
            adjust = self._fake_focus_flight(root / "adjust", complete=False)
            Path(adjust["run_directory"], "summary.json").write_text(json.dumps({"status": "exhausted"}), encoding="utf-8")

            def action(_context, *, action, run_id, **kwargs):
                return {"flight": flight, "field-contrast": contrast, "fast-adjust": adjust}[action]

            receipt = root / "focus-result.json"
            with patch("msplatform.workflows.oa_focus_component.run_focus_controller_campaign", return_value=pa), \
                 patch("msplatform.workflows.oa_focus_component._run_action", side_effect=action), \
                 self.assertRaisesRegex(ValueError, "Fast-Adjust exhausted") as raised:
                run_component_focus(self._store_focus_context(root), artifact_store=store, request_path=request,
                    release_spec_path=release, run_id="20261128_020001__test__python__focus-store-exhausted",
                    receipt_path=receipt)
            run_id = next(note.removeprefix("Store run_id: ") for note in raised.exception.__notes__
                          if note.startswith("Store run_id: "))
            self.assertEqual(store.run_status(run_id)["execution_status"], "failed")
            result = json.loads(receipt.read_text(encoding="utf-8-sig"))
            self.assertFalse(Path(result["run_directory"], "results/mrtof_runtime_receipt.json").exists())

    @staticmethod
    def _record(path: Path) -> dict:
        import hashlib
        return {"path": str(path.resolve()), "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def _write_pa_child_manifest(self, root: Path, result: Path) -> Path:
        config = root / "pa_run_config.json"
        config.write_text(json.dumps({"run_id": "20260923_120000__sim__simion__component-focus-pa",
                                      "project": "orthogonal_accelerator",
                                      "mode": "component_focus_pa_build"}), encoding="utf-8")
        manifest = root / "manifest.json"
        config_record = self._record(config)
        result_record = self._record(result)
        config_record["sha256"] = config_record["sha256"].upper()
        result_record["sha256"] = result_record["sha256"].upper()
        manifest.write_text(json.dumps({"role": "simulation_run_manifest", "status": "success",
                                        "project": "orthogonal_accelerator", "mode": "component_focus_pa_build",
                                        "run_config": config_record, "outputs": [result_record]}), encoding="utf-8")
        return manifest

    def test_mr_runtime_receipt_projects_only_small_provider_identity_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generation = root / "generation"
            generation.mkdir()
            voltages = self.campaign["operating_point"]["electrode_voltages_v"]
            native_names = [
                f"orthogonal_accelerator_focus.pa{i}" for i in range(len(voltages) + 1)
            ]
            standalone_names = [
                f"orthogonal_accelerator_focus.response{i}.pa" for i in range(1, len(voltages) + 1)
            ]
            names = ["orthogonal_accelerator_focus.pa#", *native_names, *standalone_names]
            for name in names:
                (generation / name).write_bytes(name.encode())
            exporter = generation / "export_standalone_pa.lua"
            exporter.write_bytes(b"exporter")
            receipt_name = "orthogonal_accelerator_focus.standalone_responses.json"
            write_standalone_pa_response_set(
                generation,
                exporter,
                tuple(ResponseExport(i, native_names[i], standalone_names[i - 1])
                      for i in range(1, len(voltages) + 1)),
                generation / receipt_name,
                source_directory=generation,
            )
            names.append(receipt_name)
            cache = {"schema_version": 3, "files": [
                {"name": name, "bytes": (generation / name).stat().st_size,
                 "sha256": file_sha256(generation / name)} for name in names
            ]}
            (generation / "cache_manifest.json").write_text(json.dumps(cache), encoding="utf-8")
            payloads = {name: (generation / name).read_bytes() for name in names}
            hard_gate = {"complete_transport_passed": True, "exit_slow_energy_passed": True, "exit_axial_energy_passed": True,
                         "exit_transverse_energy_passed": True,
                         "exit_transverse_velocity_bias_passed": True}
            assessment = {
                "passed": True, "target_axial_energy_per_charge_v": 4372.0,
                "tolerances": {"maximum_exit_slow_energy_error_per_charge_v": 0.05,
                               "maximum_exit_axial_energy_error_per_charge_v": 0.05,
                               "maximum_exit_transverse_energy_error_per_charge_v": 0.05,
                               "maximum_exit_transverse_velocity_bias_mm_per_us": 0.0001},
                "center_particle": {"measured_exit_slow_energy_per_charge_v": 5.0,
                                    "slow_energy_residual_per_charge_v": 0.01,
                                    "measured_exit_axial_energy_per_charge_v": 4372.01,
                                    "axial_energy_residual_per_charge_v": 0.01,
                                    "measured_exit_transverse_energy_per_charge_v": 0.0,
                                    "transverse_energy_residual_per_charge_v": 0.0,
                                    "delta_x_mm": 0.0,
                                    "delta_vx_mm_per_us": 0.0,
                                    "slow_energy_passed": True, "axial_energy_passed": True,
                                    "transverse_energy_passed": True,
                                    "transverse_velocity_bias_passed": True},
                "cohort": {"maximum_absolute_slow_energy_residual_per_charge_v": 0.02,
                           "maximum_absolute_axial_energy_residual_per_charge_v": 0.02,
                           "maximum_absolute_transverse_energy_residual_per_charge_v": 0.0,
                           "mean_delta_x_mm": 0.0,
                           "mean_delta_vx_mm_per_us": 0.0,
                           "slow_energy_passed": True, "axial_energy_passed": True,
                           "transverse_energy_passed": True,
                           "transverse_velocity_bias_passed": True},
            }
            flight = root / "flight"
            (flight / "results").mkdir(parents=True)
            analysis = flight / "results" / "focus_analysis.json"
            analysis.write_text(json.dumps({"status": "candidate_complete", "hard_gate": hard_gate,
                                            "exit_energy_assessment": assessment}), encoding="utf-8")
            flight_manifest = flight / "run_manifest.json"
            flight_manifest.write_text(json.dumps({"role": "simulation_run_manifest", "status": "success",
                                                   "project": "orthogonal_accelerator", "mode": "component_focus_flight",
                                                   "outputs": [self._record(analysis)]}), encoding="utf-8")
            workflow = root / "workflow.json"
            workflow.write_text(json.dumps({"role": "orthogonal_accelerator_component_focus_workflow_receipt",
                                            "status": "candidate_complete", "hard_gate": hard_gate,
                                            "exit_energy_assessment": assessment,
                                            "flight_child": {"manifest_sha256": self._record(flight_manifest)["sha256"],
                                                             "analysis": self._record(analysis)}}), encoding="utf-8")
            runtime = root / "runtime" / "accelerator_family"
            runtime.mkdir(parents=True)
            runtime_members = []
            for index in range(len(voltages) + 1):
                member = runtime / f"orthogonal_accelerator_focus.pa{index}"
                member.write_bytes(f"runtime-{index}".encode())
                runtime_members.append({"name": member.name, "bytes": member.stat().st_size})
            runtime_checkpoint = root / "accelerator_runtime_checkpoint.json"
            runtime_checkpoint.write_text(json.dumps({
                "schema_version": 1,
                "role": "orthogonal_accelerator_shared_runtime_checkpoint",
                "status": "prepared",
                "cache_key": "key",
                "generation_sha256": "generation",
                "directory": str(runtime),
                "members": runtime_members,
                "controller_refine": "solutions={0}",
                "response_refine_performed": False,
                "published_native_members_opened": False,
            }), encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps({"status": "published", "action_required": "complete",
                                          "cache_key": "key", "generation_sha256": "generation",
                                          "generation_directory": str(generation),
                                          "runtime_checkpoint_path": str(runtime_checkpoint),
                                          "runtime_controller_path": str(runtime / "orthogonal_accelerator_focus.pa0")}), encoding="utf-8")
            manifest = self._write_pa_child_manifest(root, result)
            campaign = root / "campaign.json"
            campaign.write_text(json.dumps({"operating_point": {"final_energy_per_charge_v": 4372.0,
                                             "electrode_voltages_v": voltages,
                                             "finite_3d_gain_correction_v": 0.0, "instance_center_y_mm": 0.0},
                                            "release_spec": {"geometry": {"shape": "cylinder", "center_mm": [0, 0, 32],
                                                                           "axis": "y", "radius_mm": 0.5, "height_mm": 1.0},
                                                             "species": {"mass_amu": 100, "charge_state": 1},
                                                             "sampling": {"kinetic_energy": {"center_ev": 5, "full_width_ev": 0},
                                                                          "nominal_direction": [0, 1, 0],
                                                                          "angular_full_width_deg": 0.0}}}), encoding="utf-8")
            plan = root / "plan.json"
            plan.write_text(json.dumps({"role": "orthogonal_accelerator_component_focus_pa_plan", "gem": "INERT",
                                        "geometry_profile_id": "profile", "electrode_count": len(voltages),
                                        "numerical_domain": {"mesh_mm_per_gu": [1, 1, 1],
                                            "span_mm": [2, 2, 2], "stored_span_mm": [1, 2, 2],
                                            "mirror_axes": ["x"], "iob_origin_mm": [0, -1, 0]},
                                        "layout": {"gap_1_mm": 6, "gap_2_mm": 30,
                                                   "ring_count": len(voltages) - 4,
                                                   "aperture_height_y_mm": 16},
                                        "theory_seed": {"release_position_from_repeller_mm": 2.4}}), encoding="utf-8")
            original_read_bytes = Path.read_bytes

            def forbid_pa_payload_read(path: Path) -> bytes:
                if path.resolve() == (generation / "orthogonal_accelerator_focus.pa0").resolve():
                    raise AssertionError("runtime receipt must not hash or read controller PA payload")
                return original_read_bytes(path)

            with patch("msplatform.workflows.oa_focus_mr_runtime_receipt.validate_pa_family_cache_generation", return_value=cache), patch.object(Path, "read_bytes", forbid_pa_payload_read):
                receipt = project(workflow_receipt_path=workflow, pa_result_path=result, pa_manifest_path=manifest, campaign_path=campaign, plan_path=plan)
                for target, message in ((result, "provider PA result is not the verified child-manifest output"),
                                        (flight_manifest, "selected provider flight manifest is invalid"),
                                        (analysis, "selected provider flight analysis differs")):
                    with self.subTest(tampered=target.name):
                        original = target.read_bytes()
                        target.write_bytes(original + b" ")
                        try:
                            with self.assertRaisesRegex(MrRuntimeReceiptError, message):
                                project(workflow_receipt_path=workflow, pa_result_path=result, pa_manifest_path=manifest,
                                        campaign_path=campaign, plan_path=plan)
                        finally:
                            target.write_bytes(original)
            from msplatform.backends.simion.oa_focus_controller_store import _write_focus_manifest
            from msplatform.storage import ArtifactStore
            builder = self.project.parents[1] / "backends/simion/resources/build_component_focus_pa.lua"
            store = ArtifactStore(root / "store")
            work = store.new_work()
            for name in names:
                (work / name).write_bytes(payloads[name])
            (work / "focus_identity.json").write_text(json.dumps({"identity": identity(json.loads(plan.read_text(encoding="utf-8")), builder, Path(__file__))}), encoding="utf-8")
            bank = _write_focus_manifest(work, "fixture", json.loads(plan.read_text(encoding="utf-8")))
            asset_id = store.put_asset("simion_focus_controller", "fixture", work)
            asset = store.asset_status(asset_id)["path"]
            stored_result = json.loads(result.read_text(encoding="utf-8"))
            stored_result.update(generation_directory=str(asset), generation_sha256=bank["generation_sha256"],
                                 cache_key=bank["cache_key"], store_asset_id=asset_id)
            result.write_text(json.dumps(stored_result), encoding="utf-8")
            runtime_checkpoint.write_text(json.dumps({**json.loads(runtime_checkpoint.read_text(encoding="utf-8")),
                "cache_key": bank["cache_key"], "generation_sha256": bank["generation_sha256"]}), encoding="utf-8")
            manifest = self._write_pa_child_manifest(root, result)
            stored = project(workflow_receipt_path=workflow, pa_result_path=result, pa_manifest_path=manifest,
                             campaign_path=campaign, plan_path=plan)
            self.assertEqual(stored["mrtof_projection"], receipt["mrtof_projection"])
            self.assertEqual(stored["standalone_response_bank"]["store_asset_id"], asset_id)
            original_manifest = (asset / "focus_manifest.json").read_bytes()
            try:
                (asset / "focus_manifest.json").write_bytes(original_manifest + b" ")
                with self.assertRaisesRegex(ValueError, "incomplete|modified"):
                    project(workflow_receipt_path=workflow, pa_result_path=result, pa_manifest_path=manifest,
                            campaign_path=campaign, plan_path=plan)
            finally:
                (asset / "focus_manifest.json").write_bytes(original_manifest)
        self.assertEqual(receipt["status"], "published_standalone_response_bank")
        self.assertEqual(receipt["mrtof_projection"]["endpoint_voltages_v"], [
            float(value) for value in self.campaign["operating_point"]["electrode_voltages_v"][1:4]
        ])
        self.assertEqual(receipt["mrtof_projection"]["geometry"]["repeller_to_exit_mm"], 36.0)
        self.assertEqual(receipt["mrtof_projection"]["geometry"]["ring_count"], 15)
        self.assertEqual(receipt["mrtof_projection"]["accepted_release"]["geometry"]["axis"], "y")
        self.assertEqual(receipt["mrtof_projection"]["required_source_y_offset_from_accelerator_axis_mm"], 0.0)
        self.assertEqual(receipt["standalone_response_bank"]["response_ids"], list(range(1, len(voltages) + 1)))
        self.assertFalse(receipt["standalone_response_bank"]["published_native_members_opened"])
        self.assertEqual(receipt["private_runtime_checkpoint"]["controller_path"],
                         str((runtime / "orthogonal_accelerator_focus.pa0").resolve()))

    def test_mr_runtime_receipt_rejects_workflow_without_complete_focus_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / "workflow.json"
            workflow.write_text(json.dumps({"role": "orthogonal_accelerator_component_focus_workflow_receipt", "status": "candidate_incomplete"}), encoding="utf-8")
            with patch("msplatform.workflows.oa_focus_mr_runtime_receipt._verify_pa_child_source"):
                with self.assertRaisesRegex(ValueError, "complete N=100 time focus"):
                    project(workflow_receipt_path=workflow, pa_result_path=workflow, pa_manifest_path=workflow,
                            campaign_path=workflow, plan_path=workflow)

    def _write_active_owner(self, root: Path) -> Path:
        results = root / "results"
        results.mkdir()
        config = root / "run_config.json"
        value = {"schema_version": 2, "run_id": "20260923_120000__sim__simion__component-focus-workflow",
                 "project": "orthogonal_accelerator", "mode": "component_focus_workflow",
                 "artifact_retention": {"policy_version": 1, "class": "solver_review", "reason": "test"},
                 "capacity_ledger_lifecycle": {"enabled": True}}
        config.write_text(json.dumps(value), encoding="utf-8")
        manifest = root / "run_manifest.json"
        config_record = self._record(config)
        config_record["sha256"] = config_record["sha256"].upper()
        manifest.write_text(json.dumps({"role": "simulation_run_manifest", "status": "checkpoint",
                                        "project": value["project"], "mode": value["mode"],
                                        "run_config": config_record}), encoding="utf-8")
        return results / "mrtof_runtime_receipt.json"

    def test_mr_runtime_receipt_output_requires_active_owner_lifecycle_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self._write_active_owner(root)
            write_receipt({"role": "test"}, output)
            self.assertTrue(output.is_file())
            with self.assertRaisesRegex(MrRuntimeReceiptError, "already exists"):
                write_receipt({"role": "test"}, output)
            with self.assertRaisesRegex(MrRuntimeReceiptError, "owner run results"):
                write_receipt({"role": "test"}, root / "unowned.json")

    def test_mr_runtime_receipt_output_rejects_owner_without_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self._write_active_owner(root)
            config = root / "run_config.json"
            value = json.loads(config.read_text(encoding="utf-8"))
            value.pop("capacity_ledger_lifecycle")
            config.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MrRuntimeReceiptError, "lifecycle envelope"):
                write_receipt({"role": "test"}, output)


if __name__ == "__main__":
    unittest.main()
