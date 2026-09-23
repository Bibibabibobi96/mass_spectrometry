from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from projects.orthogonal_accelerator.analysis.component_focus_pa_cache import identity
from projects.orthogonal_accelerator.analysis.component_focus_mr_runtime_receipt import (
    MrRuntimeReceiptError, project, write_receipt,
)
from projects.orthogonal_accelerator.analysis.component_focus_workflow import (
    ComponentFocusWorkflowError,
    compile_workflow,
)


class ComponentFocusWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[2]
        self.campaign = json.loads((self.project / "config" / "two_zone_component_focus_campaign.json").read_text(encoding="utf-8"))

    def _request(self) -> dict:
        return {
            "schema_version": 1,
            "role": "orthogonal_accelerator_component_focus_request",
            "consumer_project_id": "parallel_mirror_dual_stripe_mr_tof",
            "geometry_profile_id": self.campaign["geometry_profile_id"],
            "time_focus": {
                "final_energy_per_charge_v": 4371.2351565,
                "focus_plane_offset_from_exit_mm": 0.0,
                "gap1_voltage_drop_bounds_v": [100.0, 1500.0],
            },
            "numerics": self.campaign["numerics"],
            "acceptance": self.campaign["acceptance"],
            "simion_projection": self.campaign["simion_projection"],
        }

    def test_compiles_one_frozen_campaign_and_pa_plan_from_caller_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, release = root / "request.json", root / "release.json"
            request.write_text(json.dumps(self._request()), encoding="utf-8")
            release.write_text(json.dumps(self.campaign["release_spec"]), encoding="utf-8")
            result = compile_workflow(request, release)
        self.assertEqual(result["consumer_project_id"], "parallel_mirror_dual_stripe_mr_tof")
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
        builder = self.project / "simion" / "build_component_focus_pa.lua"
        self.assertEqual(identity(first["pa_plan"], builder, Path(__file__)),
                         identity(second["pa_plan"], builder, Path(__file__)))
        self.assertNotEqual(first["release_spec_sha256"], second["release_spec_sha256"])
        self.assertGreater(second["campaign"]["operating_point"]["instance_center_y_mm"], 0.9)

    def test_mr_release_is_frozen_unchanged_while_provider_derives_its_voltage_pair(self) -> None:
        release = (self.project.parents[1] / "projects" / "parallel_mirror_dual_stripe_mr_tof" /
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
        runner = (self.project / "simion" / "run_component_focus_workflow.ps1").read_text(encoding="utf-8")
        self.assertEqual(runner.count("&$paRunner -RunId"), 1)
        self.assertEqual(runner.count("&$flightRunner -RunId"), 1)
        self.assertIn("--request $request --release-spec $release --output $workflowPlan", runner)
        self.assertIn("-CampaignPath $resolvedCampaign", runner)
        self.assertIn("-ReleaseSpecPath $release", runner)
        self.assertIn("component_focus_workflow_receipt.json", runner)
        self.assertIn("one_provider_cache_probe__at_most_one_native_build", runner)
        self.assertNotIn("build_component_focus_pa.lua", runner)

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
        manifest.write_text(json.dumps({"role": "simulation_run_manifest", "status": "success",
                                        "project": "orthogonal_accelerator", "mode": "component_focus_pa_build",
                                        "run_config": self._record(config), "outputs": [self._record(result)]}), encoding="utf-8")
        return manifest

    def test_mr_runtime_receipt_projects_only_small_provider_identity_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generation = root / "generation"
            generation.mkdir()
            names = ["orthogonal_accelerator_focus.pa#"] + [f"orthogonal_accelerator_focus.pa{i}" for i in range(10)]
            for name in names:
                (generation / name).write_bytes(name.encode())
            cache = {"files": [{"name": name, "bytes": len(name), "sha256": "0" * 64} for name in names]}
            (generation / "cache_manifest.json").write_text(json.dumps(cache), encoding="utf-8")
            workflow = root / "workflow.json"
            workflow.write_text(json.dumps({"role": "orthogonal_accelerator_component_focus_workflow_receipt", "status": "candidate_complete"}), encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps({"disposition": "hit", "cache_key": "key", "generation_sha256": "generation", "generation_directory": str(generation)}), encoding="utf-8")
            manifest = self._write_pa_child_manifest(root, result)
            campaign = root / "campaign.json"
            campaign.write_text(json.dumps({"operating_point": {"final_energy_per_charge_v": 4372.0, "electrode_voltages_v": [0, 5000, 3800, 0, 3000, 2400, 1800, 1200, 600]}}), encoding="utf-8")
            plan = root / "plan.json"
            plan.write_text(json.dumps({"geometry_profile_id": "profile", "layout": {"gap_1_mm": 6, "gap_2_mm": 30, "aperture_height_y_mm": 16}, "theory_seed": {"release_position_from_repeller_mm": 2.4}}), encoding="utf-8")
            original_read_bytes = Path.read_bytes

            def forbid_pa_payload_read(path: Path) -> bytes:
                if path.resolve() == (generation / "orthogonal_accelerator_focus.pa0").resolve():
                    raise AssertionError("runtime receipt must not hash or read controller PA payload")
                return original_read_bytes(path)

            with patch("projects.orthogonal_accelerator.analysis.component_focus_mr_runtime_receipt.validate_pa_family_cache_generation", return_value=cache), patch.object(Path, "read_bytes", forbid_pa_payload_read):
                receipt = project(workflow_receipt_path=workflow, pa_result_path=result, pa_manifest_path=manifest, campaign_path=campaign, plan_path=plan)
        self.assertEqual(receipt["status"], "published_read_only")
        self.assertEqual(receipt["mrtof_projection"]["endpoint_voltages_v"], [5000.0, 3800.0, 0.0])
        self.assertEqual(receipt["mrtof_projection"]["geometry"]["repeller_to_exit_mm"], 36.0)
        self.assertEqual(receipt["read_only_controller_pa0"]["path"], str((generation / "orthogonal_accelerator_focus.pa0").resolve()))
        self.assertEqual(receipt["read_only_controller_pa0"]["sha256"], "0" * 64)

    def test_mr_runtime_receipt_rejects_workflow_without_complete_focus_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / "workflow.json"
            workflow.write_text(json.dumps({"role": "orthogonal_accelerator_component_focus_workflow_receipt", "status": "candidate_incomplete"}), encoding="utf-8")
            with patch("projects.orthogonal_accelerator.analysis.component_focus_mr_runtime_receipt._verify_pa_child_source"):
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
        manifest.write_text(json.dumps({"role": "simulation_run_manifest", "status": "checkpoint",
                                        "project": value["project"], "mode": value["mode"],
                                        "run_config": self._record(config)}), encoding="utf-8")
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
