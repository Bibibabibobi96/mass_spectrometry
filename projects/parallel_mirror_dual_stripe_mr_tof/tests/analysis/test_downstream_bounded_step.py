from __future__ import annotations

import copy
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_bounded_step import (
    assess_bounded_step,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_voltage_definition import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class DownstreamBoundedStepTest(unittest.TestCase):
    def definition(self):
        frozen = {"identity": "one-problem"}
        return {
            "role": "mrtof_finite_3d_downstream_voltage_definition_audit",
            "status": "success",
            "unknown_names": list(UNKNOWN_NAMES),
            "residual_names": list(RESIDUAL_NAMES),
            "classification": {"status": "square_exact"},
            "baseline": {
                "run_id": "baseline",
                "parameters": [10.0, 20.0, 30.0, 40.0],
                "residuals": [1.0, -2.0, 3.0, -4.0],
                "frozen_problem": frozen,
            },
            "physical_jacobian_rows": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "undamped_linear_correction_v": [-1.0, 2.0, -3.0, 4.0],
            "residual_scales": [1.0, 2.0, 3.0, 4.0],
        }

    def candidate(self):
        return {
            "run_id": "candidate",
            "parameters": [9.9, 20.2, 29.7, 40.4],
            "residuals": [0.89, -1.78, 2.67, -3.56],
            "frozen_problem": {"identity": "one-problem"},
        }

    def test_reports_actual_and_predicted_descent_without_publishing(self):
        result = assess_bounded_step(self.definition(), self.candidate())
        self.assertEqual(result["qualification"], "descent_observed__new_jacobian_required")
        self.assertAlmostEqual(result["maximum_absolute_coordinate_step_v"], 0.4)
        self.assertAlmostEqual(result["newton_direction_fraction"], 0.1)
        self.assertGreater(result["actual_to_predicted_reduction_ratio"], 1.0)
        self.assertIn("does_not_choose", result["iteration_authority"])

    def test_rejects_an_off_direction_or_changed_problem(self):
        candidate = self.candidate()
        candidate["parameters"][0] += 0.01
        with self.assertRaises(CandidateContractError):
            assess_bounded_step(self.definition(), candidate)
        candidate = self.candidate()
        candidate["frozen_problem"] = {"identity": "different"}
        with self.assertRaises(CandidateContractError):
            assess_bounded_step(self.definition(), candidate)

    def test_retains_a_real_increase_as_rejected_evidence(self):
        candidate = copy.deepcopy(self.candidate())
        candidate["residuals"] = [2.0, -4.0, 6.0, -8.0]
        result = assess_bounded_step(self.definition(), candidate)
        self.assertEqual(result["qualification"], "actual_objective_increased__step_rejected")
        self.assertLess(result["actual_objective_reduction"], 0.0)

    def test_accepts_central_difference_definition_without_changing_policy(self):
        definition = self.definition()
        definition["role"] = "mrtof_finite_3d_downstream_central_difference_audit"
        definition["classifications"] = {"central": definition.pop("classification")}
        definition["physical_jacobians"] = {
            "central": definition.pop("physical_jacobian_rows")
        }
        definition["central_undamped_linear_correction_v"] = definition.pop(
            "undamped_linear_correction_v"
        )
        result = assess_bounded_step(definition, self.candidate())
        self.assertEqual(result["definition_derivative_kind"], "central")
        self.assertEqual(result["qualification"], "descent_observed__new_jacobian_required")

    def test_runner_uses_managed_inputs_and_never_launches_simion(self):
        project = Path(__file__).resolve().parents[2]
        source = (project / "analysis" / "run_downstream_bounded_step.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("New-RunPackage", source)
        self.assertIn("Copy-VerifiedRunInput", source)
        self.assertIn("Apply-RunArtifactRetention", source)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertIn("physical_acceptance='not_defined'", source)
        self.assertNotIn("SIMION-2020", source)


if __name__ == "__main__":
    unittest.main()
