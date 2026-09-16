from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_projective_scan import (
    NativeStripeProjectiveScanNumerics,
    ProjectiveKappaNumerics,
    _evaluate_kappa_prime,
    scan_native_stripe_projective_candidates,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def controls(*, sample_budget: int, root_budget: int, near_zero: float) -> NativeStripeProjectiveScanNumerics:
    return NativeStripeProjectiveScanNumerics(
        theta_sample_count=32,
        admissibility_eta_sample_count=16,
        adaptive_refinement_levels=1,
        normalization_pole_absolute_tolerance=1e-10,
        root_absolute_tolerance=1e-10,
        root_relative_tolerance=1e-10,
        maximum_root_iterations=50,
        near_zero_candidate_threshold=near_zero,
        maximum_sample_kappa_prime_evaluations=sample_budget,
        maximum_root_refinement_kappa_prime_evaluations=root_budget,
        kappa=ProjectiveKappaNumerics(
            derivative_step=0.002,
            initial_panels=8,
            maximum_integral_refinements=5,
            integral_relative_tolerance=1e-8,
        ),
    )


class NativeStripeProjectiveScanTests(unittest.TestCase):
    paths = (lambda y: 10.0 + y, lambda y: 10.0 + y * y)

    def test_explicit_kappa_integral_matches_linear_profile(self) -> None:
        value = _evaluate_kappa_prime(
            lambda eta: eta,
            ProjectiveKappaNumerics(
                derivative_step=0.002,
                initial_panels=8,
                maximum_integral_refinements=5,
                integral_relative_tolerance=1e-9,
            ),
        )
        self.assertAlmostEqual(value, 1.0, places=5)

    def test_full_projective_chart_reports_pole_arcs_and_bracketed_root(self) -> None:
        def fake_kappa_prime(profile, _numerics):
            return profile(0.5) - 0.4

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            side_effect=fake_kappa_prime,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:quadratic-native-paths",
                numerics=controls(sample_budget=256, root_budget=64, near_zero=1e-5),
            )

        roots = [root for arc in result.admissible_arcs for root in arc.bracketed_roots]
        self.assertEqual(result.sample_budget_status, "completed_within_budget")
        self.assertEqual(result.root_refinement_budget_status, "completed_within_budget")
        self.assertEqual(result.completeness_status, "finite_candidate_scan_only__not_exhaustive_or_unique")
        self.assertAlmostEqual(result.normalization_pole_ratio, -1.0)
        self.assertGreaterEqual(len(result.invalid_boundaries), 2)
        self.assertTrue(any(item.boundary_kind == "normalization_pole" for item in result.invalid_boundaries))
        self.assertEqual(len(roots), 1)
        self.assertAlmostEqual(roots[0].relative_action_weight_ratio, 2.0 / 3.0, places=7)

    def test_sampling_can_fill_its_budget_while_reserved_refinement_finishes_root(self) -> None:
        def fake_kappa_prime(profile, _numerics):
            return profile(0.5) - 0.4

        patch_target = (
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime"
        )
        with patch(patch_target, side_effect=fake_kappa_prime):
            inventory = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:derive-admissible-sample-count",
                numerics=controls(sample_budget=256, root_budget=64, near_zero=1e-5),
            )
        exact_sample_budget = inventory.sample_kappa_prime_evaluations_used
        with patch(patch_target, side_effect=fake_kappa_prime):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:reserved-root-refinement",
                numerics=controls(
                    sample_budget=exact_sample_budget,
                    root_budget=64,
                    near_zero=1e-5,
                ),
            )
        roots = [root for arc in result.admissible_arcs for root in arc.bracketed_roots]
        self.assertEqual(result.sample_kappa_prime_evaluations_used, exact_sample_budget)
        self.assertEqual(result.sample_budget_status, "completed_within_budget")
        self.assertGreater(result.root_refinement_kappa_prime_evaluations_used, 0)
        self.assertEqual(result.root_refinement_budget_status, "completed_within_budget")
        self.assertEqual(len(roots), 1)

    def test_insufficient_root_reserve_preserves_unresolved_sign_change_bracket(self) -> None:
        def fake_kappa_prime(profile, _numerics):
            return profile(0.5) - 0.4

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            side_effect=fake_kappa_prime,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:insufficient-root-reserve",
                numerics=controls(sample_budget=256, root_budget=1, near_zero=1e-5),
            )
        roots = [root for arc in result.admissible_arcs for root in arc.bracketed_roots]
        unresolved = [item for arc in result.admissible_arcs for item in arc.unresolved_brackets]
        self.assertEqual(roots, [])
        self.assertEqual(result.root_refinement_budget_status, "exhausted")
        self.assertEqual(result.root_refinement_kappa_prime_evaluations_used, 1)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].reason, "root_refinement_evaluation_reserve_exhausted")
        self.assertLess(unresolved[0].bracket_kappa_prime[0] * unresolved[0].bracket_kappa_prime[1], 0.0)

    def test_integral_failure_is_not_reported_as_budget_exhaustion(self) -> None:
        calls = 0

        def intermittently_failing_kappa_prime(_profile, _numerics):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise CandidateContractError("synthetic endpoint integration failure")
            return 1.0

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            side_effect=intermittently_failing_kappa_prime,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:integral-failure",
                numerics=controls(sample_budget=256, root_budget=8, near_zero=1e-5),
            )
        self.assertEqual(result.sample_integral_failure_count, 1)
        self.assertEqual(result.sample_budget_status, "completed_within_budget")
        self.assertEqual(result.root_refinement_budget_status, "completed_within_budget")

    def test_same_sign_near_zero_is_unresolved_not_a_root(self) -> None:
        def fake_kappa_prime(profile, _numerics):
            return (profile(0.5) - 0.4) ** 2 + 1e-7

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            side_effect=fake_kappa_prime,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:near-zero",
                numerics=controls(sample_budget=256, root_budget=64, near_zero=1e-3),
            )
        roots = [root for arc in result.admissible_arcs for root in arc.bracketed_roots]
        candidates = [item for arc in result.admissible_arcs for item in arc.near_zero_unresolved_candidates]
        self.assertEqual(roots, [])
        self.assertTrue(candidates)
        self.assertIn("unresolved", candidates[0].reason)

    def test_root_across_zero_pi_chart_seam_is_not_lost(self) -> None:
        def fake_kappa_prime(profile, _numerics):
            return profile(0.5) - 0.5

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            side_effect=fake_kappa_prime,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:chart-seam",
                numerics=controls(sample_budget=256, root_budget=64, near_zero=1e-5),
            )
        roots = [root for arc in result.admissible_arcs for root in arc.bracketed_roots]
        self.assertEqual(len(roots), 1)
        self.assertAlmostEqual(roots[0].relative_action_weight_ratio, 0.0, places=8)

    def test_root_on_a_sample_is_reported_once(self) -> None:
        ratio = math.tan(math.pi / 128.0)
        target = (0.5 + 0.25 * ratio) / (1.0 + ratio)

        def fake_kappa_prime(profile, _numerics):
            return profile(0.5) - target

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            side_effect=fake_kappa_prime,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:sample-root",
                numerics=controls(sample_budget=256, root_budget=64, near_zero=1e-5),
            )
        roots = [root for arc in result.admissible_arcs for root in arc.bracketed_roots]
        self.assertEqual(len(roots), 1)

    def test_sample_budget_exhaustion_is_separate_from_root_reserve(self) -> None:
        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "native_stripe_projective_scan._evaluate_kappa_prime",
            return_value=1.0,
        ):
            result = scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:budget",
                numerics=controls(sample_budget=3, root_budget=5, near_zero=1e-5),
            )
        self.assertEqual(result.sample_budget_status, "exhausted")
        self.assertEqual(result.sample_kappa_prime_evaluations_used, 3)
        self.assertEqual(result.root_refinement_budget_status, "completed_within_budget")
        self.assertIn("not_exhaustive", result.completeness_status)

    def test_invalid_controls_fail_closed(self) -> None:
        bad = NativeStripeProjectiveScanNumerics(
            theta_sample_count=32,
            admissibility_eta_sample_count=16,
            adaptive_refinement_levels=True,
            normalization_pole_absolute_tolerance=1e-10,
            root_absolute_tolerance=1e-10,
            root_relative_tolerance=1e-10,
            maximum_root_iterations=50,
            near_zero_candidate_threshold=1e-5,
            maximum_sample_kappa_prime_evaluations=64,
            maximum_root_refinement_kappa_prime_evaluations=16,
            kappa=ProjectiveKappaNumerics(0.002, 8, 5, 1e-8),
        )
        with self.assertRaisesRegex(CandidateContractError, "refinement"):
            scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=1.0,
                geometry_input_identity_source="test:bad-controls",
                numerics=bad,
            )

        with self.assertRaisesRegex(CandidateContractError, "direction"):
            scan_native_stripe_projective_candidates(
                self.paths,
                entry_y_mm=0.0,
                drift_length_l_mm=1.0,
                drift_direction_sign=True,
                geometry_input_identity_source="test:bad-direction",
                numerics=controls(sample_budget=64, root_budget=16, near_zero=1e-5),
            )


if __name__ == "__main__":
    unittest.main()
