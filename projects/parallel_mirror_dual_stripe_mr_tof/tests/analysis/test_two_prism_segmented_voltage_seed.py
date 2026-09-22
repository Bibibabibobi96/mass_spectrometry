from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    TransportNumerics,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_voltage_seed import (
    selected_positive_mirror_turn_identity,
    solve_two_prism_segmented_voltage_seed,
    two_prism_legacy_topology_signature,
    two_prism_topology_signature,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


def diagnostic(first: float, second: float, *, turn_boundary: str = "stripe_11_set_1.lower"):
    event = SimpleNamespace(
        kind="interface",
        name="fixed",
        region_name="prism_16",
        entering=True,
        transmitted=True,
    )
    stage = SimpleNamespace(events=(event,))
    stripe_entry = SimpleNamespace(
        kind="interface",
        name=turn_boundary,
        region_name=turn_boundary.rsplit(".", 1)[0],
        entering=True,
        transmitted=True,
    )
    stripe_exit = SimpleNamespace(
        kind="interface",
        name=turn_boundary.rsplit(".", 1)[0] + ".upper",
        region_name=turn_boundary.rsplit(".", 1)[0],
        entering=False,
        transmitted=True,
    )
    turn_event = SimpleNamespace(
        kind="stop",
        name="first_post_P2_positive_mirror_turn",
        region_name=None,
        entering=None,
        transmitted=None,
    )
    stage_c = SimpleNamespace(
        status="stopped_at_positive_mirror_turn",
        events=(turn_event,),
    )
    stage_d = SimpleNamespace(
        status="stopped_after_first_positive_stripe_pass",
        events=(stripe_entry, stripe_exit, SimpleNamespace(
            kind="stop",
            name="first_post_turn_positive_stripe_pass_complete",
            region_name=None,
            entering=None,
            transmitted=None,
        )),
    )
    return SimpleNamespace(
        qualification="projected_yz_seed_only",
        inferred_negative_mirror_pre_reflection=True,
        stripe_entrance_region_name="stripe_11_set_1",
        stage_a_p1_to_interface=stage,
        stage_b_p1_exit_to_p2_low_field_reference=stage,
        stage_c_low_field_reference_to_positive_mirror_turn=stage_c,
        stage_d_positive_mirror_turn_to_first_stripe_pass=stage_d,
        voltage_residuals=(
            ("P1_P2_positive_mirror_turn_y_mm", first),
            ("P1_P2_P2_shield_low_field_signed_vy_over_vz", second),
        ),
    )


class TwoPrismSegmentedVoltageSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(CONTRACT)
        self.source = ProjectPhaseSpaceState((0.0, -55.0, 0.0), (0.0, 1.0, -20.0))
        self.mirror = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 100.0, 130.0, 160.0, 190.0),
            electrode_voltages_v=(0.0, 1000.0, 2000.0, 3000.0, 5000.0),
            terminal_electrode_plane_z_mm=230.0,
            terminal_electrode_voltage_v=5000.0,
        )
        self.numerics = TransportNumerics(
            relative_tolerance=1e-8,
            absolute_tolerance=1e-10,
            max_step_mm_per_sqrt_v=0.1,
            event_samples_per_step=4,
            root_time_tolerance_mm_per_sqrt_v=1e-10,
            boundary_root_tolerance_mm=1e-8,
            momentum_tolerance_sqrt_v=1e-8,
            normal_energy_tolerance_v=1e-10,
            maximum_steps=1000,
        )

    def test_turn_identity_separates_paths_with_same_legacy_topology(self) -> None:
        left = diagnostic(1.0, 2.0, turn_boundary="stripe_11_set_1.lower")
        right = diagnostic(1.0, 2.0, turn_boundary="stripe_13_set_2.lower")
        self.assertEqual(
            two_prism_legacy_topology_signature(left),
            two_prism_legacy_topology_signature(right),
        )
        self.assertNotEqual(
            selected_positive_mirror_turn_identity(left),
            selected_positive_mirror_turn_identity(right),
        )
        self.assertNotEqual(
            two_prism_topology_signature(left),
            two_prism_topology_signature(right),
        )
    def solve(
        self,
        evaluator,
        *,
        maximum_evaluations=40,
        initial=((0.0, 0.0),),
        maximum_backtracking_reductions=4,
    ):
        with (
            patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
                "two_prism_segmented_voltage_seed.evaluate_two_prism_segmented_voltage_pair",
                side_effect=evaluator,
            ),
            patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
                "two_prism_segmented_voltage_seed.natural_two_prism_scales",
                return_value=([100.0, 100.0], [340.0, 0.05]),
            ) as scales,
        ):
            result = solve_two_prism_segmented_voltage_seed(
                self.contract,
                source=self.source,
                particle_mass_th=524.0,
                charge_state=1,
                mirror_design=self.mirror,
                selected_axial_energy_per_charge_v=4000.0,
                target_slow_kinetic_energy_per_charge_v=5.0,
                target_p2_reference_tangent_ratio=0.05,
                stripe_bias_v_by_set_name={"set_1": -25.0, "set_2": 50.0},
                numerics=self.numerics,
                stage_a_maximum_reduced_time_mm_per_sqrt_v=20.0,
                stage_b_maximum_reduced_time_mm_per_sqrt_v=200.0,
                prism_voltage_bounds_v_by_electrode_id={16: (-20.0, 20.0), 17: (-20.0, 20.0)},
                initial_prism_voltage_pairs_v=initial,
                central_difference_step_v_by_electrode_id={16: 0.1, 17: 0.1},
                maximum_iterations=10,
                maximum_transport_evaluations=maximum_evaluations,
                trust_step_v_by_electrode_id={16: 5.0, 17: 5.0},
                maximum_backtracking_reductions=maximum_backtracking_reductions,
                backtracking_factor=0.5,
                minimum_scaled_residual_norm_decrease=1e-12,
                physical_residual_tolerance_by_name={
                    "P1_P2_positive_mirror_turn_y_mm": 1e-9,
                    "P1_P2_P2_shield_low_field_signed_vy_over_vz": 1e-9,
                },
                relative_singular_value_rank_tolerance=1e-10,
                scaled_compatibility_tolerance=1e-10,
            )
        scales.assert_called_once_with(self.contract)
        return result

    def test_full_rank_system_converges_and_retains_transport_diagnostics(self) -> None:
        def evaluator(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            return diagnostic(p1 + 2.0 * p2 - 3.0, 3.0 * p1 - p2 - 7.0)

        result = self.solve(evaluator)
        self.assertEqual(result.status, "converged")
        self.assertAlmostEqual(result.selected_prism_voltages_v[0], 17.0 / 7.0)
        self.assertAlmostEqual(result.selected_prism_voltages_v[1], 2.0 / 7.0)
        self.assertEqual(result.final_classification.status, "square_exact")
        self.assertEqual(result.final_classification.independent_constraint_rank, 2)
        self.assertTrue(all(item.transport_diagnostic is not None for item in result.evaluations))
        self.assertEqual(result.iterations[0].central_difference_evaluation_indices, (1, 2, 3, 4))

    def test_equivalent_initial_feasible_pairs_choose_lower_absolute_voltage(self) -> None:
        def evaluator(_contract, **_kwargs):
            return diagnostic(0.0, 0.0)

        result = self.solve(evaluator, initial=((8.0, -8.0), (1.0, -1.0)))
        self.assertEqual(result.status, "underdetermined")
        center = result.evaluations[result.iterations[0].center_evaluation_index]
        self.assertEqual(center.prism_voltages_v, (1.0, -1.0))

    def test_rank_deficient_system_reports_underdetermined(self) -> None:
        def evaluator(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            return diagnostic(p1 + p2 - 1.0, 2.0 * (p1 + p2 - 1.0))

        result = self.solve(evaluator)
        self.assertEqual(result.status, "underdetermined")
        self.assertEqual(result.final_classification.independent_constraint_rank, 1)
        self.assertEqual(result.final_classification.nullity, 1)
        self.assertIsNone(result.iterations[0].proposed_voltages_v)

    def test_invalid_central_topology_is_not_replaced_by_a_penalty(self) -> None:
        def evaluator(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            if p1 < 0.0:
                raise CandidateContractError("P1 reflected")
            return diagnostic(p1 - 1.0, p2 - 2.0)

        result = self.solve(evaluator)
        self.assertEqual(result.status, "all_initial_neighborhoods_invalid")
        failed = [item for item in result.evaluations if item.failure]
        self.assertEqual(len(failed), 1)
        self.assertIn("P1 reflected", failed[0].failure)
        self.assertIsNone(failed[0].residuals)

    def test_next_best_initial_point_is_used_when_best_neighborhood_is_invalid(self) -> None:
        def evaluator(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            if abs(p1) < 0.05 and p2 < -0.05:
                raise CandidateContractError("best point lies on a topology boundary")
            return diagnostic(p1 - 1.0, p2 - 2.0)

        result = self.solve(evaluator, initial=((0.0, 0.0), (5.0, 5.0)))
        self.assertEqual(result.status, "converged")
        self.assertEqual(result.iterations[0].outcome, "initial_neighborhood_rejected")
        self.assertEqual(result.iterations[0].center_evaluation_index, 0)
        self.assertEqual(result.iterations[1].center_evaluation_index, 1)
        self.assertEqual(result.final_classification.status, "square_exact")

    def test_transport_evaluation_budget_terminates_during_jacobian(self) -> None:
        def evaluator(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            return diagnostic(p1 - 1.0, p2 - 2.0)

        result = self.solve(evaluator, maximum_evaluations=3)
        self.assertEqual(result.status, "evaluation_budget_exhausted")
        self.assertEqual(len(result.evaluations), 3)
        self.assertIn("central differences", result.reason)

    def test_worsening_full_step_is_rejected_before_smaller_step_improves(self) -> None:
        def evaluator(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            return diagnostic(p1 * p1 - 1.0, p2)

        result = self.solve(evaluator, initial=((0.1, 0.0),))
        self.assertEqual(result.status, "converged")
        first = result.iterations[0]
        self.assertEqual(first.accepted_step_scale, 0.25)
        self.assertEqual(len(first.backtracking_evaluation_indices), 3)
        trial_norms = [
            result.evaluations[index].scaled_residual_norm_2
            for index in first.backtracking_evaluation_indices
        ]
        center_norm = result.evaluations[first.center_evaluation_index].scaled_residual_norm_2
        self.assertGreater(trial_norms[0], center_norm)
        self.assertGreater(trial_norms[1], center_norm)
        self.assertLess(trial_norms[2], center_norm)

    def test_backtracking_distinguishes_all_invalid_from_no_decrease(self) -> None:
        def invalid_after_local_neighborhood(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            if p1 > 0.2:
                raise CandidateContractError("lost topology")
            return diagnostic(p1 - 1.0, p2 - 2.0)

        invalid = self.solve(
            invalid_after_local_neighborhood, maximum_backtracking_reductions=2,
        )
        self.assertEqual(invalid.status, "backtracking_exhausted_all_invalid_topology")
        self.assertEqual(len(invalid.iterations[0].backtracking_evaluation_indices), 3)
        self.assertTrue(all(
            invalid.evaluations[index].failure == "lost topology"
            for index in invalid.iterations[0].backtracking_evaluation_indices
        ))

        def legal_without_descent(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            if abs(p1) <= 0.11 and abs(p2) <= 0.11:
                return diagnostic(p1 - 1.0, p2 - 2.0)
            return diagnostic(2.0 + abs(p1), 2.0 + abs(p2))

        no_descent = self.solve(legal_without_descent, maximum_backtracking_reductions=2)
        self.assertEqual(
            no_descent.status, "backtracking_exhausted_no_sufficient_decrease",
        )
        self.assertTrue(all(
            no_descent.evaluations[index].failure is None
            for index in no_descent.iterations[0].backtracking_evaluation_indices
        ))


if __name__ == "__main__":
    unittest.main()
