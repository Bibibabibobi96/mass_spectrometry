from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    _trial,
    assert_trial_matches_jacobian,
    audit,
    resolve_numerics,
    solve_linearized_step,
)
from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)

RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_downstream_fixed_grid_workpoint.ps1"


class DownstreamFixedGridWorkpointTests(unittest.TestCase):
    def test_runner_uses_ledger_lifecycle_and_one_capacity_session(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "-CapacityLedgerLifecycleEnabled", "Enter-ArtifactWorkflowCapacitySession",
            "Update-ArtifactWorkflowCapacitySession", "Exit-ArtifactWorkflowCapacitySession",
        ):
            self.assertIn(token, source)
        self.assertNotIn("Invoke-ArtifactCapacityGate", source)

    @staticmethod
    def _fixture():
        base_v = np.array([-25.0, 50.0, 190.0, -190.0])
        base_r = np.array([0.15, 2.0e-4, 4.4, 0.65])
        jacobian = np.array([
            [0.01, 0.00, 0.20, 0.03],
            [0.00, 1.0e-5, 2.0e-4, -3.0e-4],
            [0.40, -0.10, 0.02, 0.01],
            [0.05, 0.20, 0.01, -0.02],
        ])
        frozen = {"target_k": 25.5}
        baseline = {"voltages_v": base_v.tolist(), "residual_vector": base_r.tolist(), "frozen_problem": frozen}
        perturbations = []
        for index in range(4):
            voltage = base_v.copy()
            voltage[index] += 0.1
            perturbations.append({
                "voltages_v": voltage.tolist(),
                "residual_vector": (base_r + 0.1 * jacobian[:, index]).tolist(),
                "frozen_problem": frozen,
            })
        return baseline, perturbations, jacobian

    def test_recovers_full_rank_step_and_applies_trust_limit(self) -> None:
        baseline, perturbations, jacobian = self._fixture()
        result = solve_linearized_step(
            baseline,
            perturbations,
            lower_bounds_v=[-100, 1, 1, -400],
            upper_bounds_v=[-1, 100, 400, -1],
            parameter_scales_v=[25, 50, 190, 190],
            residual_scales=[0.01, np.tan(np.deg2rad(0.01)), 1.0, 1.0],
            maximum_abs_step_v=[2, 2, 2, 2],
            relative_rank_tolerance=1e-10,
            compatibility_tolerance=1e-8,
        )
        np.testing.assert_allclose(result["physical_jacobian_rows"], jacobian, atol=1e-12)
        np.testing.assert_allclose(result["stencil_steps_v"], [0.1] * 4)
        self.assertNotIn("forward_steps_v", result)
        self.assertEqual(result["classification"]["status"], "square_exact")
        self.assertGreater(result["trust_scale"], 0.0)
        self.assertLessEqual(max(abs(value) for value in result["applied_correction_v"]), 2.0 + 1e-12)
        self.assertEqual(set(result["predicted_residuals"]), set(RESIDUAL_NAMES))

    def test_rejects_non_single_axis_perturbation(self) -> None:
        baseline, perturbations, _jacobian = self._fixture()
        perturbations[0]["voltages_v"][1] += 0.1
        with self.assertRaisesRegex(CandidateContractError, "change only"):
            solve_linearized_step(
                baseline,
                perturbations,
                lower_bounds_v=[-100, 1, 1, -400],
                upper_bounds_v=[-1, 100, 400, -1],
                parameter_scales_v=[25, 50, 190, 190],
                residual_scales=[1, 1, 1, 1],
                maximum_abs_step_v=[2, 2, 2, 2],
                relative_rank_tolerance=1e-10,
                compatibility_tolerance=1e-8,
            )

    def test_signed_columns_preserve_jacobian_direction(self) -> None:
        baseline, perturbations, jacobian = self._fixture()
        steps = [-0.1, 0.2, -0.3, 0.4]
        for index, step in enumerate(steps):
            voltages = np.array(baseline["voltages_v"])
            voltages[index] += step
            perturbations[index]["voltages_v"] = voltages.tolist()
            perturbations[index]["residual_vector"] = (
                np.array(baseline["residual_vector"]) + step * jacobian[:, index]
            ).tolist()
        result = solve_linearized_step(
            baseline, perturbations,
            lower_bounds_v=[-100, 1, 1, -400], upper_bounds_v=[-1, 100, 400, -1],
            parameter_scales_v=[25, 50, 190, 190], residual_scales=[1, 1, 1, 1],
            maximum_abs_step_v=[2, 2, 2, 2], relative_rank_tolerance=1e-10,
            compatibility_tolerance=1e-8,
        )
        np.testing.assert_allclose(result["physical_jacobian_rows"], jacobian, atol=1e-12)
        np.testing.assert_allclose(result["stencil_steps_v"], steps)
        self.assertNotIn("forward_steps_v", result)

    def test_rejects_zero_step(self) -> None:
        baseline, perturbations, _ = self._fixture()
        perturbations[0]["voltages_v"] = list(baseline["voltages_v"])
        with self.assertRaisesRegex(CandidateContractError, "nonzero step"):
            solve_linearized_step(
                baseline, perturbations,
                lower_bounds_v=[-100, 1, 1, -400], upper_bounds_v=[-1, 100, 400, -1],
                parameter_scales_v=[25, 50, 190, 190], residual_scales=[1, 1, 1, 1],
                maximum_abs_step_v=[2, 2, 2, 2], relative_rank_tolerance=1e-10,
                compatibility_tolerance=1e-8,
            )

    def test_rejects_changed_frozen_problem(self) -> None:
        baseline, perturbations, _jacobian = self._fixture()
        perturbations[3]["frozen_problem"] = {"target_k": 24.5}
        with self.assertRaisesRegex(CandidateContractError, "frozen physical problem"):
            solve_linearized_step(
                baseline,
                perturbations,
                lower_bounds_v=[-100, 1, 1, -400],
                upper_bounds_v=[-1, 100, 400, -1],
                parameter_scales_v=[25, 50, 190, 190],
                residual_scales=[1, 1, 1, 1],
                maximum_abs_step_v=[2, 2, 2, 2],
                relative_rank_tolerance=1e-10,
                compatibility_tolerance=1e-8,
            )

    @staticmethod
    def _contract():
        path = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"
        return json.loads(path.read_text(encoding="utf-8-sig"))

    @staticmethod
    def _write_trial(folder, trial):
        folder.mkdir()
        voltages = trial["voltages_v"]
        observation = {
            "status": "detected", "prism_voltages_v": voltages[2:],
            "residuals": dict(zip(RESIDUAL_NAMES, trial["residual_vector"])),
        }
        materialization = {
            "stripe_biases_v": voltages[:2], "prism_voltages_v": voltages[2:],
            "inputs": {
                "geometry_sha256": "same-geometry",
                "fixed_mirror_stripe_authority_sha256": "same-authority",
                "mirror_summary_sha256": "same-mirror",
                "reviewed_contract_sha256": "same-reviewed-contract",
                "stripe_summary_sha256": "same-stripe",
            },
            "target_drift_period_ratio": 25.5, "target_positive_mirror_turn_y_mm": 0.0,
            "target_low_field_tangent_ratio_vy_over_vz": 0.033,
            "target_slow_turn_y_mm": 340.0,
            "mirror_voltages_v": [0, -5900, -2600, 4200, 6030],
            "selected_axial_energy_per_charge_v": 4372.0,
            "source_slow_kinetic_energy_per_charge_v": 4.96,
            "fly2_sha256": "same-source", "drift_phase_contract": {"half_oscillations": 51},
            "nonaccelerator_mesh_mm_per_gu": [1, 1, 1],
        }
        def record(name, content):
            path = folder / name
            path.write_text(json.dumps(content), encoding="utf-8")
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        manifest = {
            "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial",
            "run_config": record("run_config.json", {"parameters": {}}),
            "outputs": [record("two_prism_trial_observation.json", observation),
                        record("two_prism_trial_materialization.json", materialization),
                        {"path": str(folder / "unused_corrupt.pa"), "exists": True, "bytes": 100, "sha256": "bad"}],
        }
        path = folder / "run_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_contract_derives_energy_bounds_and_angle_scale(self):
        contract = self._contract()
        baseline, _, _ = self._fixture()
        baseline["frozen_problem"] = {
            "selected_axial_energy_per_charge_v": 4372.0,
            "targets": {"target_low_field_tangent_ratio_vy_over_vz": 0.033},
        }
        controls = resolve_numerics(contract, baseline)
        self.assertEqual(controls["lower_bounds_v"][0], -4372.0)
        self.assertLess(controls["upper_bounds_v"][1], 4272.0)
        self.assertEqual(controls["parameter_scales_v"], [25, 50, 190, 190])
        self.assertAlmostEqual(controls["residual_scales"][1], 0.000174722, places=8)
        missing = copy.deepcopy(contract)
        del missing["downstream_fixed_grid_workpoint_profile"]["maximum_abs_step_v"]
        with self.assertRaises(KeyError):
            resolve_numerics(missing, baseline)

    def test_audit_reads_materialized_stripes_freezes_projection_and_ignores_unused_pa(self):
        baseline, perturbations, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifests = [self._write_trial(root / str(index), value)
                         for index, value in enumerate((baseline, *perturbations))]
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(self._contract()), encoding="utf-8")
            definition = {"schema_version": 1, "role": "mrtof_downstream_fixed_grid_workpoint_definition",
                          "contract": str(contract_path), "baseline_manifest": str(manifests[0]),
                          "perturbation_manifests": dict(zip(UNKNOWN_NAMES, map(str, manifests[1:])))}
            definition_path = root / "definition.json"
            definition_path.write_text(json.dumps(definition), encoding="utf-8")
            result = audit(definition_path, root / "frozen")
            self.assertEqual(result["target_drift_period_ratio"], 25.5)
            self.assertEqual(result["classification"]["status"], "square_exact")
            self.assertEqual(len(result["consumed_trials"]), 5)
            self.assertEqual(len(list((root / "frozen").rglob("*.json"))), 20)
            changed_contract = self._contract()
            changed_contract["nominal"]["target_drift_period_ratio"] = 24.5
            contract_path.write_text(json.dumps(changed_contract), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "target K"):
                audit(definition_path)
            definition["maximum_abs_step_v"] = [99]*4
            definition_path.write_text(json.dumps(definition), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "overrides"):
                audit(definition_path)

    def test_iteration_rejects_changed_source_offset_and_profile(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = self._write_trial(root / "base", baseline)
            child = self._write_trial(root / "child", baseline)
            proposal = {"baseline_manifest": str(base), "consumed_trials": [
                {"manifest": str(base), "manifest_sha256": file_sha256(base)}]}
            assert_trial_matches_jacobian(proposal, child)
            original = json.loads(child.read_text())
            mat_path = child.parent / "two_prism_trial_materialization.json"
            original_mat = json.loads(mat_path.read_text())
            for key, value in (("source_position_project_mm", [0, -1.8, 0]),
                               ("trajectory_profile", {"maximum_step_us": 0.1})):
                mat_path.write_text(json.dumps({**original_mat, key: value}))
                doc = copy.deepcopy(original)
                doc["outputs"][1].update(bytes=mat_path.stat().st_size, sha256=file_sha256(mat_path))
                child.write_text(json.dumps(doc))
                with self.assertRaisesRegex(Exception, key):
                    assert_trial_matches_jacobian(proposal, child)

    def test_native_trial_requires_bound_receipt_and_freezes_bank_identity(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifest_path = self._write_trial(Path(temp) / "trial", baseline)
            manifest = json.loads(manifest_path.read_text())
            config_path = manifest_path.parent / "run_config.json"
            config = json.loads(config_path.read_text())
            config["parameters"]["pa_binding_mode"] = "native_corridor_private_fast_adjust_family__four_instances__n1"
            config_path.write_text(json.dumps(config))
            manifest["run_config"].update(bytes=config_path.stat().st_size, sha256=file_sha256(config_path))
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(Exception, "mode and receipt disagree"):
                _trial(manifest_path)
            receipt = manifest_path.parent / "native_corridor_runtime_family.json"
            receipt.write_text(json.dumps({
                "schema_version": 1, "role": "mrtof_private_native_corridor_family", "status": "prepared",
                "cache_key": "a" * 64, "generation_sha256": "b" * 64,
                "response_refine_performed": False, "published_native_members_opened": False,
                "controller_refine": "solutions={0}",
            }))
            manifest["outputs"].append({"path": str(receipt), "exists": True,
                                        "bytes": receipt.stat().st_size, "sha256": file_sha256(receipt)})
            manifest_path.write_text(json.dumps(manifest))
            trial = _trial(manifest_path, Path(temp) / "frozen")
            self.assertEqual(trial["frozen_problem"]["native_bank_identity"]["cache_key"], "A" * 64)
            self.assertTrue((Path(temp) / "frozen" / receipt.name).is_file())
            receipt.write_text("{}")
            with self.assertRaises(Exception):
                _trial(manifest_path)

    def test_trial_rejects_consumed_output_corruption(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifest = self._write_trial(Path(temp) / "trial", baseline)
            (manifest.parent / "two_prism_trial_observation.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "byte count"):
                _trial(manifest)

    def test_trial_rejects_inconsistent_observed_prism_voltage(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifest_path = self._write_trial(Path(temp) / "trial", baseline)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = manifest["outputs"][0]
            path = Path(record["path"])
            observation = json.loads(path.read_text(encoding="utf-8"))
            observation["prism_voltages_v"][0] += 1.0
            path.write_text(json.dumps(observation), encoding="utf-8")
            record.update(bytes=path.stat().st_size, sha256=file_sha256(path))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "observed prism"):
                _trial(manifest_path)

    def test_rank_deficiency_does_not_publish_proposal(self):
        baseline, perturbations, _ = self._fixture()
        perturbations[3]["residual_vector"] = baseline["residual_vector"]
        with self.assertRaisesRegex(CandidateContractError, "not square exact"):
            solve_linearized_step(
                baseline, perturbations, lower_bounds_v=[-100, 1, 100, -300],
                upper_bounds_v=[-1, 100, 300, -100], parameter_scales_v=[25, 50, 190, 190],
                residual_scales=[1, 1, 1, 1], maximum_abs_step_v=[2]*4,
                relative_rank_tolerance=1e-10, compatibility_tolerance=1e-8,
            )

    def test_transported_jacobian_rebases_current_real_baseline(self):
        baseline, perturbations, jacobian = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_manifests = [self._write_trial(root / f"old_{index}", value)
                             for index, value in enumerate((baseline, *perturbations))]
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(self._contract()), encoding="utf-8")
            original_definition = {
                "schema_version": 1,
                "role": "mrtof_downstream_fixed_grid_workpoint_definition",
                "contract": str(contract_path),
                "baseline_manifest": str(old_manifests[0]),
                "perturbation_manifests": dict(zip(UNKNOWN_NAMES, map(str, old_manifests[1:]))),
            }
            original_definition_path = root / "original_definition.json"
            original_definition_path.write_text(json.dumps(original_definition), encoding="utf-8")
            prior = audit(original_definition_path)
            prior_path = root / "downstream_fixed_grid_workpoint.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")
            prior_record = {
                "path": str(prior_path), "exists": True, "bytes": prior_path.stat().st_size,
                "sha256": file_sha256(prior_path),
            }
            prior_manifest_path = root / "prior_run_manifest.json"
            prior_manifest_path.write_text(json.dumps({
                "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "downstream_fixed_grid_workpoint", "outputs": [prior_record],
            }), encoding="utf-8")

            current_voltage = np.array([-25.2, 50.2, 196.0, -195.1])
            current_residual = np.array([-0.09, -6.0e-5, 1.5, 1.8])
            current_manifest = self._write_trial(root / "current", {
                "voltages_v": current_voltage.tolist(),
                "residual_vector": current_residual.tolist(),
            })
            transported_definition = {
                "schema_version": 1,
                "role": "mrtof_downstream_transported_jacobian_definition",
                "contract": str(contract_path),
                "baseline_manifest": str(current_manifest),
                "prior_workpoint_manifest": str(prior_manifest_path),
            }
            transported_path = root / "transported_definition.json"
            transported_path.write_text(json.dumps(transported_definition), encoding="utf-8")
            result = audit(transported_path, root / "frozen")
            expected_raw = np.linalg.solve(jacobian, -current_residual)
            np.testing.assert_allclose(result["unbounded_linear_correction_v"], expected_raw, atol=1e-12)
            np.testing.assert_allclose(
                result["proposed_voltages_v"],
                current_voltage + np.asarray(result["applied_correction_v"]),
                atol=1e-12,
            )
            self.assertLessEqual(max(map(abs, result["applied_correction_v"])), 2.0)
            self.assertEqual(result["status"], "transported_linearized_candidate_step")
            self.assertEqual(result["jacobian_use"], "transported_local_approximation")
            self.assertTrue(result["outside_source_trust_radius"])
            self.assertTrue(result["requires_real_center_flight_confirmation"])
            self.assertEqual(len(result["consumed_trials"]), 1)
            self.assertTrue((root / "frozen" / "prior_baseline" / "run_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
