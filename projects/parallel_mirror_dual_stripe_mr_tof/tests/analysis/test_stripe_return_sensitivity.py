from __future__ import annotations

import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.stripe_return_sensitivity import (
    CORRECT_HANDOFF_RESIDUALS,
    _particle_metrics,
    _run,
    _shield_lip_coordinates,
    _source_receipt_from_manifest,
    build_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


class StripeReturnSensitivityTest(unittest.TestCase):
    @staticmethod
    def _record(path: Path) -> dict[str, object]:
        data = path.read_bytes()
        return {
            "path": str(path.resolve()),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
        }

    def _verified_run_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        root.mkdir()
        run_config = root / "run_config.json"
        summary = root / "summary.json"
        upstream = root / "upstream.json"
        evidence = root / "evidence.json"
        run_config.write_text(json.dumps({
            "schema_version": 1, "run_id": "verified", "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial",
        }), encoding="utf-8")
        summary.write_text(json.dumps({"status": "success"}), encoding="utf-8")
        upstream.write_text("upstream", encoding="utf-8")
        evidence.write_text("evidence", encoding="utf-8")
        manifest = root / "run_manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1, "run_id": "verified", "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial", "status": "success",
            "run_config": self._record(run_config),
            "inputs": {"upstream": self._record(upstream)},
            "outputs": [self._record(summary), self._record(evidence)],
        }), encoding="utf-8")
        return upstream, evidence, manifest

    def _verified_source_fixture(self, root: Path) -> tuple[Path, Path]:
        (root / "results").mkdir(parents=True)
        run_config = root / "run_config.json"
        summary = root / "summary.json"
        receipt = root / "results" / "bunch_source_receipt.json"
        run_config.write_text(json.dumps({
            "schema_version": 1,
            "run_id": "source",
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "frozen_bunch_source",
        }), encoding="utf-8")
        summary.write_text(json.dumps({"status": "success"}), encoding="utf-8")
        receipt.write_text("{}", encoding="utf-8")
        manifest = root / "run_manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "run_id": "source",
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "status": "success",
            "run_config": self._record(run_config),
            "inputs": {},
            "outputs": [self._record(summary), self._record(receipt)],
        }), encoding="utf-8")
        return receipt, manifest

    def _event(self, kind: str, t: float, **extra):
        return {"kind": kind, "ion": 1, "t_us": t, **extra}

    def test_particle_metrics_use_correct_handoff_and_lip_events(self) -> None:
        events = [
            self._event("p2_low_field_reference", 1, vy_mm_us=2.0, vz_mm_us=40.0),
            self._event("pre_origin_positive_mirror_turn", 2, y_mm=0.004),
            self._event("drift_phase_origin", 2.1),
            self._event("slow_turn", 4, y_mm=341.5),
            self._event("target_k_phase_sample", 8, k=25.5, y_mm=0.2),
            self._event(
                "patch_interface", 9, name="mirror_turn_negative__z_max",
                direction=1, y_mm=-6.4, z_mm=-97.0,
            ),
            self._event("terminal", 12, splat=1, y_mm=-48, z_mm=97),
        ]
        trial = {
            "target_positive_mirror_turn_y_mm": 0.0,
            "target_low_field_tangent_ratio_vy_over_vz": 0.04,
            "target_slow_turn_y_mm": 340.0,
        }
        metrics = _particle_metrics(events, trial, -6.0, -97.0)
        self.assertAlmostEqual(metrics["positive_mirror_turn_y_residual_mm"], 0.004)
        self.assertAlmostEqual(metrics["p2_low_field_tangent_ratio_residual"], 0.01)
        self.assertAlmostEqual(metrics["return_p2_lip_margin_mm"], 0.4)
        self.assertAlmostEqual(metrics["slow_turn_y_minus_L_mm"], 1.5)
        self.assertEqual(metrics["classification"], "detector")

    def test_lip_collision_is_retained_as_negative_margin(self) -> None:
        events = [
            self._event("p2_low_field_reference", 1, vy_mm_us=1.0, vz_mm_us=40.0),
            self._event("pre_origin_positive_mirror_turn", 2, y_mm=0.0),
            self._event("drift_phase_origin", 2.1),
            self._event("slow_turn", 4, y_mm=340.0),
            self._event("target_k_phase_sample", 8, k=25.5, y_mm=0.6),
            self._event("terminal", 9, splat=-1, y_mm=-5.95, z_mm=-97.0),
        ]
        trial = {
            "target_positive_mirror_turn_y_mm": 0.0,
            "target_low_field_tangent_ratio_vy_over_vz": 0.025,
            "target_slow_turn_y_mm": 340.0,
        }
        metrics = _particle_metrics(events, trial, -6.0, -97.0)
        self.assertAlmostEqual(metrics["return_p2_lip_margin_mm"], -0.05)
        self.assertEqual(metrics["classification"], "electrode_collision")

    def test_shield_lip_coordinates_read_yz_polygon_without_flattening(self) -> None:
        lip_y, lip_z = _shield_lip_coordinates({
            "cross_aperture": {"y_mm": [-6.0, 6.0]},
            "outer_polygon_yz_mm": [[-10.0, -97.0], [10.0, -97.0], [10.0, 97.0]],
        })
        self.assertEqual(lip_y, 6.0)
        self.assertEqual(lip_z, -97.0)

    def test_shield_lip_coordinates_reject_malformed_polygon(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "two-dimensional yz polygon"):
            _shield_lip_coordinates({
                "cross_aperture": {"y_mm": [-6.0, 6.0]},
                "outer_polygon_yz_mm": [-97.0, 97.0],
            })

    def test_analysis_source_never_labels_sampled_direction_as_candidate(self) -> None:
        source = Path(
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/stripe_return_sensitivity.py"
        ).read_text(encoding="utf-8")
        self.assertIn("sampled_boundary_unit_direction_dS1_dS2", source)
        self.assertIn("not_evaluated__extrapolation_prohibited", source)
        self.assertNotIn('"candidate_unit_direction_dS1_dS2"', source)

    def test_plan_is_five_states_two_cohorts_and_runner_only(self) -> None:
        with TemporaryDirectory() as temp_text:
            temp = Path(temp_text)
            runner = temp / "run_two_prism_trial.ps1"
            runner.write_text("# runner\n", encoding="utf-8")
            parents = {}
            for name in ("geometry", "mirror", "stripe", "accelerator", "workbench"):
                root = temp / name
                root.mkdir()
                manifest = root / "run_manifest.json"
                manifest.write_text("{}", encoding="utf-8")
                parents[name] = str(manifest.resolve())
            receipt, source_manifest = self._verified_source_fixture(temp / "source")
            inputs = {
                "geometry_run_manifest": parents["geometry"],
                "mirror_run_manifest": parents["mirror"],
                "stripe_run_manifest": parents["stripe"],
                "accelerator_run_manifest": parents["accelerator"],
                "local_workbench_run_manifest": parents["workbench"],
                "bunch_source_run_manifest": str(source_manifest.resolve()),
            }
            params = {
                "prism_1_voltage_v": 191.0, "prism_2_voltage_v": -192.0,
                "stripe_biases_v": [-25.0, 50.0],
                "flight_scope": "complete_three_dimensional_static_return",
                "accelerator_pulse": {"mode": "static"},
                "trajectory_profile": {"profile_id": "center_screening"},
            }
            fake_roots = {key: temp / key for key in ("r26", "r27", "r28", "r29")}
            for root in fake_roots.values():
                (root / "results").mkdir(parents=True)
            (fake_roots["r27"] / "results" / "two_prism_trial_materialization.json").write_text(
                json.dumps({"target_drift_period_ratio": 25.5}), encoding="utf-8"
            )
            common_config = {"project": "parallel_mirror_dual_stripe_mr_tof", "mode": "finite_3d_two_prism_voltage_trial", "inputs": inputs}
            returns = {
                "r26": (fake_roots["r26"], {"project": "parallel_mirror_dual_stripe_mr_tof", "status": "success", "run_id": "r26"}, {**common_config, "run_id": "r26", "parameters": params}, {"status": "success", "residuals": {name: 0 for name in CORRECT_HANDOFF_RESIDUALS}}),
                "r27": (fake_roots["r27"], {"project": "parallel_mirror_dual_stripe_mr_tof", "status": "success", "run_id": "r27"}, {**common_config, "run_id": "r27", "parameters": params}, {"status": "success"}),
            }
            boundary_params = {**params, "source_selection": {"particle_id_min": 97, "particle_id_max": 98}}
            for key in ("r28", "r29"):
                returns[key] = (fake_roots[key], {"project": "parallel_mirror_dual_stripe_mr_tof", "status": "success", "run_id": key}, {**common_config, "run_id": key, "parameters": boundary_params}, {"status": "success"})
            definition = temp / "definition.json"
            definition.write_text(json.dumps({
                "schema_version": 1, "role": "mrtof_stripe_return_sensitivity_definition",
                "delta_voltage_v": 0.25,
                "member_run_id_prefix": "20260916_030000__sim__simion__stripe-sensitivity",
                "baseline_runs": {key: str(root) for key, root in fake_roots.items()},
            }), encoding="utf-8")
            with patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.stripe_return_sensitivity._run",
                side_effect=lambda _path, label: returns[label],
            ):
                plan = build_plan(definition, runner)
            self.assertEqual(len(plan["states"]), 5)
            self.assertEqual(len(plan["tasks"]), 8)
            self.assertEqual(
                [(item["cohort"], item["particle_ids"], Path(item["source_run_path"]).name)
                 for item in plan["baseline_observations"]],
                [("center_ion1", [1], "r27"), ("boundary_ions97_98", [97, 98], "r27")],
            )
            center = [task for task in plan["tasks"] if task["cohort"] == "center_ion1"]
            self.assertTrue(all(task["particle_ids"] == [1] for task in center))
            self.assertNotIn("baseline", {task["state"] for task in plan["tasks"]})
            self.assertTrue(all(Path(task["argv"][3]).name == "run_two_prism_trial.ps1" for task in plan["tasks"]))
            self.assertEqual(plan["states"][1]["stripe_biases_v"], [-25.25, 50.0])
            self.assertEqual(plan["states"][4]["stripe_biases_v"], [-25.0, 50.25])
            self.assertTrue(all("_" not in task["run_id"].split("__")[-1] for task in plan["tasks"]))

    def test_delta_has_no_default_and_must_be_positive(self) -> None:
        with TemporaryDirectory() as temp_text:
            temp = Path(temp_text)
            runner = temp / "run_two_prism_trial.ps1"
            runner.write_text("", encoding="utf-8")
            definition = temp / "definition.json"
            definition.write_text(json.dumps({
                "schema_version": 1, "role": "mrtof_stripe_return_sensitivity_definition",
                "delta_voltage_v": 0, "member_run_id_prefix": "x", "baseline_runs": {},
            }), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "explicitly positive"):
                build_plan(definition, runner)

    def test_complete_manifest_rejects_tampered_input_hash(self) -> None:
        with TemporaryDirectory() as temp_text:
            root = Path(temp_text) / "run"
            upstream, _evidence, _manifest = self._verified_run_fixture(root)
            _run(root, "fixture")
            upstream.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "record verification failed"):
                _run(root, "fixture")

    def test_complete_manifest_rejects_tampered_output_bytes_record(self) -> None:
        with TemporaryDirectory() as temp_text:
            root = Path(temp_text) / "run"
            _upstream, _evidence, manifest_path = self._verified_run_fixture(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"][1]["bytes"] += 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "byte count changed"):
                _run(root, "fixture")

    def test_plan_rejects_tampered_source_receipt(self) -> None:
        with TemporaryDirectory() as temp_text:
            temp = Path(temp_text)
            _receipt, source_manifest = self._verified_source_fixture(temp / "source")
            manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
            manifest["outputs"][1]["bytes"] += 1
            source_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "record verification failed"):
                _source_receipt_from_manifest(source_manifest)


if __name__ == "__main__":
    unittest.main()
