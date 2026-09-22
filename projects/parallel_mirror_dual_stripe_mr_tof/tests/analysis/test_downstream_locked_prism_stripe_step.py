from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_locked_prism_stripe_step import (
    solve_locked_prism_stripe_step,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class LockedPrismStripeStepTests(unittest.TestCase):
    def fixtures(self):
        prior = {
            "role": "mrtof_downstream_fixed_grid_workpoint_audit",
            "status": "linearized_candidate_step",
            "target_drift_period_ratio": 25.5,
            "unknown_names": ["stripe_1_voltage_v", "stripe_2_voltage_v", "prism_1_voltage_v", "prism_2_voltage_v"],
            "residual_names": [
                "P1_P2_positive_mirror_turn_y_mm",
                "P1_P2_P2_shield_low_field_signed_vy_over_vz",
                "Stripe_slow_turn_y_minus_L_mm",
                "Stripe_target_phase_y_minus_origin_mm",
            ],
            "proposed_voltages_v": [-25.35, 51.85, 190.6, -191.94],
            "physical_jacobian_rows": [
                [-0.0015, 0.00018, 0.19, 0.068],
                [1.4e-7, 1.8e-7, 2.2e-4, 2.3e-4],
                [1.245, -2.092, 0.85, 0.92],
                [5.646, -0.715, -1.40, -1.39],
            ],
            "resolved_numerics": {
                "maximum_abs_step_v": [2, 2, 2, 2],
                "lower_bounds_v": [-4000, 1, 100, -300],
                "upper_bounds_v": [-1, 3900, 300, -100],
            },
        }
        observation = {
            "status": "full_drift_observed",
            "return_topology": "exact_target_k_phase_return",
            "residuals": {
                "P1_P2_positive_mirror_turn_y_mm": 0.0013,
                "P1_P2_P2_shield_low_field_signed_vy_over_vz": 4.9e-6,
                "Stripe_slow_turn_y_minus_L_mm": -1.965,
                "Stripe_target_phase_y_minus_origin_mm": 6.603,
            },
        }
        materialization = {
            "target_drift_period_ratio": 25.5,
            "target_low_field_tangent_ratio_vy_over_vz": 0.033686,
            "stripe_biases_v": [-25.35, 51.85],
            "prism_voltages_v": [190.6, -191.94],
        }
        contract = {"downstream_fixed_grid_workpoint_profile": {
            "schema_version": 1,
            "position_residual_scale_mm": 0.01,
            "angle_residual_scale_degrees": 0.01,
        }}
        return prior, observation, materialization, contract

    def test_solves_only_stripes_and_preserves_accepted_prisms(self):
        result = solve_locked_prism_stripe_step(*self.fixtures())
        self.assertEqual(result["locked_coordinates"], ["prism_1_voltage_v", "prism_2_voltage_v"])
        self.assertEqual(result["proposed_voltages_v"][2:], [190.6, -191.94])
        self.assertLess(abs(result["predicted_residuals"]["Stripe_slow_turn_y_minus_L_mm"]), 1e-10)
        self.assertLess(abs(result["predicted_residuals"]["Stripe_target_phase_y_minus_origin_mm"]), 1e-10)

    def test_rejects_unaccepted_prism_handoff(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 0.02
        with self.assertRaisesRegex(CandidateContractError, "P1/P2 handoff"):
            solve_locked_prism_stripe_step(prior, observation, materialization, contract)

    def test_rejects_coordinate_return_before_target_phase(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["return_topology"] = "coordinate_return_before_target_phase"
        del observation["residuals"]["Stripe_target_phase_y_minus_origin_mm"]
        with self.assertRaisesRegex(CandidateContractError, "restore the valid topology"):
            solve_locked_prism_stripe_step(prior, observation, materialization, contract)

    def test_uses_real_target_phase_sample_after_early_coordinate_return(self):
        prior, observation, materialization, contract = self.fixtures()
        prior["status"] = "transported_linearized_candidate_step"
        observation["return_topology"] = "coordinate_return_before_target_phase"
        result = solve_locked_prism_stripe_step(prior, observation, materialization, contract)
        self.assertEqual(result["proposed_voltages_v"][2:], [190.6, -191.94])
        self.assertEqual(result["locked_coordinates"], ["prism_1_voltage_v", "prism_2_voltage_v"])

    def test_iterates_from_previously_confirmed_locked_prism_step(self):
        prior, observation, materialization, contract = self.fixtures()
        first = solve_locked_prism_stripe_step(prior, observation, materialization, contract)
        materialization["stripe_biases_v"] = first["proposed_voltages_v"][:2]
        observation["residuals"]["Stripe_slow_turn_y_minus_L_mm"] = -0.8
        observation["residuals"]["Stripe_target_phase_y_minus_origin_mm"] = -0.175
        second = solve_locked_prism_stripe_step(first, observation, materialization, contract)
        self.assertEqual(second["baseline_voltages_v"], first["proposed_voltages_v"])
        self.assertEqual(second["proposed_voltages_v"][2:], [190.6, -191.94])
        self.assertIn("physical_jacobian_rows", second)
        self.assertIn("resolved_numerics", second)


if __name__ == "__main__":
    unittest.main()
