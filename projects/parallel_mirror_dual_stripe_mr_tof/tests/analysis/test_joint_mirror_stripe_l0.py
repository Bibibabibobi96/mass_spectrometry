from __future__ import annotations

import math
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    StripeHardBoundary,
    classify_constraint_system,
    coupled_reduced_period_mm_per_sqrt_v,
    derive_coupled_drift_state,
    require_exactly_determined,
    reduced_action_delta_mm_sqrt_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


class JointMirrorStripeL0Test(unittest.TestCase):
    def test_rank_gate_distinguishes_under_exact_and_incompatible_systems(self) -> None:
        under = classify_constraint_system(("mirror_voltage", "stripe_bias"), ("target_K",), jacobian_rows=((1.0, 0.0),))
        self.assertEqual(under.status, "underdetermined")
        with self.assertRaises(CandidateContractError):
            require_exactly_determined(under)
        exact = classify_constraint_system(("mirror_voltage", "stripe_bias"), ("target_K", "time_platform"), jacobian_rows=((1.0, 0.0), (0.0, 1.0)), residuals=(0.0, 0.0))
        self.assertEqual(exact.status, "exactly_determined")
        require_exactly_determined(exact)
        incompatible = classify_constraint_system(("mirror_voltage",), ("first", "second"), jacobian_rows=((1.0,), (1.0,)), residuals=(0.0, 1.0))
        self.assertEqual(incompatible.status, "overdetermined_incompatible")

    def test_count_without_jacobian_never_claims_exact_determination(self) -> None:
        result = classify_constraint_system(("mirror_voltage",), ("target_K",))
        self.assertEqual(result.status, "rank_unverified")

    def test_baseline_action_changes_the_same_trial_period(self) -> None:
        mirror_period = 10.0
        corrected = coupled_reduced_period_mm_per_sqrt_v(mirror_period, 4000.0, (20.0, 30.0), (-40.0, 60.0))
        self.assertNotEqual(corrected, mirror_period)
        self.assertGreater(corrected, 0.0)

    def test_nominal_state_derives_l_w_theta_and_k_without_external_w(self) -> None:
        stripes = (
            StripeHardBoundary(-40.0, lambda y: 30.0 - 0.02 * y),
            StripeHardBoundary(60.0, lambda y: 20.0 + 0.04 * y),
        )
        state = derive_coupled_drift_state(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            target_oscillation_count=25,
            stripes=stripes,
            entry_y_mm=0.0,
            turning_y_mm=100.0,
        )
        self.assertAlmostEqual(state.drift_length_l_mm, 100.0)
        self.assertAlmostEqual(state.axial_width_w_mm, state.coupled_reduced_period_mm_per_sqrt_v * math.sqrt(4000.0))
        self.assertGreater(state.nominal_kappa_1, 0.0)
        self.assertGreater(state.nominal_injection_angle_rad, 0.0)

    def test_nontransmitting_or_nonturning_trials_fail_closed(self) -> None:
        with self.assertRaises(CandidateContractError):
            reduced_action_delta_mm_sqrt_v(4000.0, 4000.0, 10.0)
        with self.assertRaises(CandidateContractError):
            derive_coupled_drift_state(
                mirror_reduced_period_mm_per_sqrt_v=10.0,
                energy_per_charge_v=4000.0,
                target_oscillation_count=25,
                stripes=(StripeHardBoundary(-40.0, lambda _y: 20.0),),
                entry_y_mm=0.0,
                turning_y_mm=100.0,
            )


if __name__ == "__main__":
    unittest.main()
