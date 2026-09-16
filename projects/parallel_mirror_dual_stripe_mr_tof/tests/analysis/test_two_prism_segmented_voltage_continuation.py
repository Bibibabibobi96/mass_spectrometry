from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_voltage_continuation import (
    ContinuationControls,
    continue_angle_zero_branch,
    continue_y_zero_branch,
    solve_adaptive_position_domain_slice,
    solve_position_slice_from_legal_anchor,
    solve_position_domain_slice,
    tangent_ratio_tolerance_from_angle_degrees,
)


SIGNATURE = "branch-a"


def _controls(**changes) -> ContinuationControls:
    values = dict(
        p1_bounds_v=(-3.0, 3.0), p2_bounds_v=(-6.0, 6.0),
        angle_ratio_tolerance=1e-8, positive_turn_y_tolerance_mm=1e-6,
        p2_root_tolerance_v=1e-9,
        initial_p1_step_v=0.5, minimum_p1_step_v=0.125, maximum_p1_step_v=0.5,
        p1_step_growth_factor=1.0, p2_initial_half_width_v=1.0,
        p2_bracket_expansion_factor=2.0, p2_bracket_maximum_expansions=3,
        maximum_inner_iterations=80, maximum_outer_iterations=40,
        maximum_transport_evaluations=400, maximum_nodes_per_direction=12,
    )
    values.update(changes)
    return ContinuationControls(**values)


def _record(p1: float, p2: float, *, signature: str = SIGNATURE) -> dict:
    return {
        "status": "legal_topology", "topology_signature_sha256": signature,
        "residual_vector": [p1 - 1.0, p2 - 2.0 * p1],
    }


class SegmentedVoltageContinuationTests(unittest.TestCase):
    def test_position_domain_slice_scans_and_refines_same_signature_root(self) -> None:
        def evaluate(pair):
            p1, p2 = pair
            return {
                "status": "legal_topology",
                "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p2 + 2.25, p1 - 0.5],
            }

        result = solve_position_domain_slice(
            evaluate,
            p1_v=0.5,
            allowed_signature_sha256=[SIGNATURE],
            p2_scan_count=5,
            controls=_controls(p2_bounds_v=(-4.0, 0.0)),
        )
        self.assertEqual(result["status"], "position_root_found")
        self.assertAlmostEqual(result["best_root"]["p2_voltage_v"], -2.25, places=6)
        self.assertTrue(result["joint_tolerance_reached"])

    def test_position_domain_slice_does_not_bridge_an_illegal_scan_gap(self) -> None:
        def evaluate(pair):
            _p1, p2 = pair
            if -3.0 < p2 < -1.0:
                return {"status": "invalid_topology"}
            return {
                "status": "legal_topology",
                "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p2 + 2.0, 0.0],
            }

        result = solve_position_domain_slice(
            evaluate,
            p1_v=0.0,
            allowed_signature_sha256=[SIGNATURE],
            p2_scan_count=5,
            controls=_controls(p2_bounds_v=(-4.0, 0.0)),
        )
        self.assertEqual(result["status"], "no_position_root_bracketed")

    def test_position_domain_does_not_bridge_turn_identities_under_one_legacy_signature(self) -> None:
        def evaluate(pair):
            _p1, p2 = pair
            return {
                "status": "legal_topology",
                "topology_signature_sha256": "turn-left" if p2 < -2.0 else "turn-right",
                "legacy_topology_signature_sha256": "legacy-branch",
                "residual_vector": [p2 + 2.0, 0.0],
            }

        result = solve_position_domain_slice(
            evaluate,
            p1_v=0.0,
            allowed_signature_sha256=["legacy-branch"],
            p2_scan_count=4,
            controls=_controls(p2_bounds_v=(-4.0, 0.0)),
        )
        self.assertEqual(result["status"], "no_position_root_bracketed")

    def test_adaptive_position_slice_finds_narrow_same_signature_root(self) -> None:
        def evaluate(pair):
            _p1, p2 = pair
            return {
                "status": "legal_topology",
                "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p2 + 2.125, 0.0],
            }

        result = solve_adaptive_position_domain_slice(
            evaluate,
            p1_v=0.0,
            allowed_signature_sha256=[SIGNATURE],
            p2_scan_count=5,
            refinement_levels=4,
            refinement_candidate_count=2,
            controls=_controls(p2_bounds_v=(-4.0, 0.0)),
        )
        self.assertEqual(result["status"], "position_root_found")
        self.assertAlmostEqual(result["best_root"]["p2_voltage_v"], -2.125, places=6)
        self.assertTrue(result["joint_tolerance_reached"])

    def test_adaptive_position_slice_classifies_but_never_bridges_topology_boundary(self) -> None:
        def evaluate(pair):
            _p1, p2 = pair
            if -2.2 < p2 < -1.8:
                return {"status": "invalid_topology"}
            return {
                "status": "legal_topology",
                "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p2 + 2.0, 0.0],
            }

        result = solve_adaptive_position_domain_slice(
            evaluate,
            p1_v=0.0,
            allowed_signature_sha256=[SIGNATURE],
            p2_scan_count=5,
            refinement_levels=5,
            refinement_candidate_count=2,
            controls=_controls(p2_bounds_v=(-4.0, 0.0)),
        )
        self.assertEqual(result["status"], "no_position_root_bracketed")
        self.assertTrue(result["topology_boundary_brackets"])
        self.assertTrue(all(
            root["p2_voltage_v"] <= -2.2 or root["p2_voltage_v"] >= -1.8
            for root in result["roots"]
        ))

    def test_independent_position_slice_keeps_p1_fixed_and_reports_angle(self) -> None:
        def evaluate(pair):
            p1, p2 = pair
            return {
                "status": "legal_topology",
                "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p2 - 2.0, p1 - 0.25],
            }

        result = solve_position_slice_from_legal_anchor(
            evaluate,
            legal_anchor_pair_v=(0.25, 1.0),
            expected_signature_sha256=SIGNATURE,
            controls=_controls(),
        )
        self.assertEqual(result["status"], "position_root_found")
        self.assertAlmostEqual(result["node"]["p1_voltage_v"], 0.25)
        self.assertAlmostEqual(result["node"]["p2_voltage_v"], 2.0)
        self.assertTrue(result["position_tolerance_reached"])
        self.assertTrue(result["angle_tolerance_reached"])

    def test_y_priority_mode_traces_y_zero_and_only_reports_best_angle(self) -> None:
        def evaluate(pair):
            p1, p2 = pair
            return {
                "status": "legal_topology",
                "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p2 - (p1 + 1.0), p1 - 2.0],
            }

        result = continue_y_zero_branch(
            evaluate,
            expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0,
            initial_p2_bracket_v=(0.0, 2.0),
            controls=_controls(),
        )
        self.assertEqual(result["solve_mode"], "y_then_angle_diagnostic")
        self.assertEqual(result["angle_ratio_acceptance_tolerance"], 1e-8)
        self.assertTrue(all(
            abs(node["positive_mirror_turn_y_residual_mm"]) <= 1e-6
            for node in result["nodes"]
        ))
        best = result["minimum_abs_angle_residual_node"]
        self.assertAlmostEqual(best["p1_voltage_v"], 2.0)
        self.assertAlmostEqual(best["p2_voltage_v"], 3.0)
        self.assertAlmostEqual(best["p2_reference_signed_tangent_ratio_residual"], 0.0)
        self.assertTrue(result["joint_search_tolerance_reached"])

    def test_degree_tolerance_is_converted_at_the_target_angle(self) -> None:
        target = 0.03382208991096363
        ratio_tolerance = tangent_ratio_tolerance_from_angle_degrees(target, 0.01)
        self.assertAlmostEqual(ratio_tolerance, 0.000174733613, places=12)

    def test_affine_branch_reaches_joint_root_without_mixing_signatures(self) -> None:
        result = continue_angle_zero_branch(
            lambda pair: _record(*pair), expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0), controls=_controls(),
        )
        self.assertTrue(result["joint_root_tolerance_reached"])
        candidate = result["joint_root_candidates"][0]
        self.assertAlmostEqual(candidate["p1_voltage_v"], 1.0)
        self.assertAlmostEqual(candidate["p2_voltage_v"], 2.0)

    def test_nonlinear_angle_corrector_uses_a_true_bracket(self) -> None:
        def evaluate(pair):
            p1, p2 = pair
            return {
                "status": "legal_topology", "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p1 + 1.0, p2**3 - (p1 + 2.0)],
            }
        result = continue_angle_zero_branch(
            evaluate, expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(1.0, 2.0),
            controls=_controls(maximum_nodes_per_direction=2),
        )
        self.assertLess(
            abs(result["seed"]["p2_reference_signed_tangent_ratio_residual"]), 1e-7,
        )

    def test_outer_bisection_refines_y_root_between_continuation_nodes(self) -> None:
        def evaluate(pair):
            p1, p2 = pair
            return {
                "status": "legal_topology", "topology_signature_sha256": SIGNATURE,
                "residual_vector": [p1 - 0.7, p2 - 2.0 * p1],
            }
        result = continue_angle_zero_branch(
            evaluate, expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0), controls=_controls(),
        )
        self.assertTrue(result["joint_root_tolerance_reached"])
        candidate = result["joint_root_candidates"][0]
        self.assertLess(abs(candidate["positive_mirror_turn_y_residual_mm"]), 1e-6)
        self.assertLess(
            abs(candidate["p2_reference_signed_tangent_ratio_residual"]), 1e-8,
        )
        self.assertAlmostEqual(candidate["p1_voltage_v"], 0.7, places=5)

    def test_signature_change_is_a_boundary_not_a_penalty(self) -> None:
        def evaluate(pair):
            record = _record(*pair)
            if pair[0] > 0.25:
                record["topology_signature_sha256"] = "branch-b"
            return record
        result = continue_angle_zero_branch(
            evaluate, expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0), controls=_controls(),
        )
        self.assertEqual(
            result["positive_direction"]["terminal_status"],
            "topology_boundary_or_unbracketed_angle_root",
        )
        self.assertTrue(all(node["p1_voltage_v"] <= 0.25 for node in result["nodes"]))

    def test_corrector_accepts_predicted_root_when_remote_bracket_side_changes_signature(self) -> None:
        def evaluate(pair):
            record = _record(*pair)
            if pair[0] > 0.0 and pair[1] > 2.0 * pair[0] + 0.25:
                record["topology_signature_sha256"] = "remote-branch"
            return record
        result = continue_angle_zero_branch(
            evaluate, expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0),
            controls=_controls(maximum_nodes_per_direction=2),
        )
        self.assertTrue(any(node["p1_voltage_v"] > 0.0 for node in result["nodes"]))

    def test_illegal_trial_is_a_boundary_and_step_is_reduced(self) -> None:
        def evaluate(pair):
            if 0.3 < pair[0] < 0.7:
                return {"status": "invalid_topology", "failure": "gap"}
            return _record(*pair)
        result = continue_angle_zero_branch(
            evaluate, expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0), controls=_controls(),
        )
        self.assertEqual(
            result["positive_direction"]["terminal_status"],
            "topology_boundary_or_unbracketed_angle_root",
        )

    def test_initial_bracket_requires_the_frozen_signature(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "changed topology signature"):
            continue_angle_zero_branch(
                lambda pair: _record(*pair, signature="wrong"),
                expected_signature_sha256=SIGNATURE,
                initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0), controls=_controls(),
            )

    def test_budget_is_exactly_enforced(self) -> None:
        result = continue_angle_zero_branch(
            lambda pair: _record(*pair), expected_signature_sha256=SIGNATURE,
            initial_p1_v=0.0, initial_p2_bracket_v=(-1.0, 1.0),
            controls=_controls(maximum_transport_evaluations=3),
        )
        self.assertEqual(result["transport_evaluation_count"], 3)
        self.assertIn(
            "transport_budget_exhausted",
            {
                result["negative_direction"]["terminal_status"],
                result["positive_direction"]["terminal_status"],
            },
        )


if __name__ == "__main__":
    unittest.main()
