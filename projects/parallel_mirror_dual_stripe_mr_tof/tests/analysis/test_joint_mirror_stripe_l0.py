from __future__ import annotations

import math
import unittest
from pathlib import Path
import json

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    JointL0Trial,
    StripeHardBoundary,
    classify_constraint_system,
    coupled_reduced_period_mm_per_sqrt_v,
    derive_coupled_drift_state,
    evaluate_joint_l0_trial,
    finite_difference_joint_jacobian,
    require_exactly_determined,
    reduced_action_delta_mm_sqrt_v,
    solve_exactly_determined_joint_l0,
    stripes_from_contract,
    time_platform_derivative_residuals,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    TwoPrismTransportObservation,
)


class JointMirrorStripeL0Test(unittest.TestCase):
    @staticmethod
    def _trial(mirror_voltage_b: float) -> JointL0Trial:
        return JointL0Trial(
            mirror_design=MirrorL0Design(
                transverse_half_gap_mm=15.0,
                transition_z_mm=(0.0, 167.0, 229.0, 261.0, 291.0),
                electrode_voltages_v=(0.0, mirror_voltage_b, 3500.0, 5500.0, 8000.0),
                terminal_electrode_plane_z_mm=320.0,
                terminal_electrode_voltage_v=8000.0,
            ),
            energy_points_v=(3900.0, 4000.0, 4100.0),
            stripes=(
                StripeHardBoundary(-40.0, lambda y: 40.0 - 0.03 * y),
                StripeHardBoundary(60.0, lambda y: 20.0 + 0.05 * y),
            ),
            stripe_entry_y_mm=0.0,
            nominal_turning_y_mm=100.0,
            target_oscillation_count=25,
            time_platform_eta_nodes=(0.9, 0.95, 1.05, 1.1),
            eta_derivative_step=1e-3,
        )

    def test_joint_trial_keeps_all_nine_declared_residuals_together(self) -> None:
        report = evaluate_joint_l0_trial(self._trial(-2000.0))
        self.assertEqual(len(report.residuals), 9)
        self.assertTrue(all(math.isfinite(value) for _name, value in report.residuals))

    def test_joint_trial_appends_all_five_three_dimensional_prism_components(self) -> None:
        state = ProjectPhaseSpaceState((0.0, -40.0, -10.0), (0.0, -1.0, -2.0))
        trial = self._trial(-2000.0)
        trial = JointL0Trial(
            **{**trial.__dict__,
               "stripe_target_position_mm": state.position_mm,
               "stripe_target_unit_direction_project": state.unit_direction_project,
               "two_prism_transport_observation": TwoPrismTransportObservation(state, state, state, state, True)}
        )
        report = evaluate_joint_l0_trial(trial)
        self.assertEqual(len(report.residuals), 14)
        self.assertEqual(dict(report.residuals)["P1_P2_to_Stripe_position_x_mm"], 0.0)

    def test_partial_prism_transport_input_fails_closed(self) -> None:
        trial = JointL0Trial(**{**self._trial(-2000.0).__dict__, "stripe_target_position_mm": (0.0, 0.0, 0.0)})
        with self.assertRaises(CandidateContractError):
            evaluate_joint_l0_trial(trial)

    def test_joint_jacobian_requires_feasible_actual_residuals(self) -> None:
        report, classification = finite_difference_joint_jacobian(
            ("mirror_voltage_b",), (-2000.0,), (1.0,), lambda values: self._trial(values[0]),
        )
        self.assertEqual(len(report.residuals), 9)
        self.assertEqual(classification.status, "overdetermined_incompatible")

    def test_solver_refuses_missing_user_scales_and_tolerances(self) -> None:
        with self.assertRaises(CandidateContractError):
            solve_exactly_determined_joint_l0(
                ("mirror_voltage_b",), (-2000.0,), (-3000.0,), (-1000.0,), (1.0,), {}, {}, 1,
                lambda values: self._trial(values[0]),
            )

    def test_solver_refuses_a_rank_deficient_parameterization(self) -> None:
        """An optimizer iterate is not publishable when two knobs coincide."""
        report = evaluate_joint_l0_trial(self._trial(-2000.0))
        scales = {name: 1.0 for name in report.residual_names()}
        tolerances = {name: 1.0e99 for name in report.residual_names()}
        builder = lambda values: self._trial(values[0] + values[1])
        _report, classification = finite_difference_joint_jacobian(
            ("mirror_voltage_b_component_1", "mirror_voltage_b_component_2"),
            (-1000.0, -1000.0),
            (1.0, 1.0),
            builder,
        )
        self.assertEqual(classification.independent_constraint_rank, 1)
        self.assertEqual(classification.status, "overdetermined_incompatible")
        with self.assertRaisesRegex(CandidateContractError, "overdetermined_incompatible"):
            solve_exactly_determined_joint_l0(
                ("mirror_voltage_b_component_1", "mirror_voltage_b_component_2"),
                (-1000.0, -1000.0),
                (-1500.0, -1500.0),
                (-500.0, -500.0),
                (1.0, 1.0),
                scales,
                tolerances,
                1,
                builder,
            )

    def test_contract_adapter_evaluates_the_frozen_bspline_not_a_resampled_shape(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = json.loads((root / "config" / "simion_candidate_two_zone.json").read_text(encoding="utf-8"))
        first, second = stripes_from_contract(contract)
        y0, y1 = contract["dual_stripe"]["theory_profile"]["active_y_span_mm"]
        self.assertGreater(first.width_mm(y0), 0.0)
        self.assertGreater(second.width_mm(y1), 0.0)
        with self.assertRaises(CandidateContractError):
            first.width_mm(y1 + 1.0)

    def test_current_hardware_problem_declares_derived_quantities_separately(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = json.loads((root / "config" / "simion_candidate_two_zone.json").read_text(encoding="utf-8"))
        problem = contract["dual_stripe_l0"]["current_fixed_hardware_l0_l1_problem"]
        self.assertEqual(len(problem["independent_unknowns"]), 8)
        self.assertEqual(len(problem["named_residual_blocks"]), 11)
        self.assertIn("coupled_axial_width_W_mm", problem["derived_not_independent_unknowns"])
        self.assertNotIn("coupled_axial_width_W_mm", problem["independent_unknowns"])
        self.assertIn("prism_1_voltage_v", problem["independent_unknowns"])
        self.assertIn("stripe_entrance_project_position_mm", problem["derived_not_independent_unknowns"])
        entrance = contract["dual_stripe_l0"]["theory_stripe_entrance"]
        self.assertEqual(entrance["project_y_mm"], 0.0)
        self.assertEqual(entrance["excluded_mechanical_extension_y_mm"], [0.0, 2.0])

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

    def test_time_platform_nodes_use_the_same_trial_action_response(self) -> None:
        stripes = (
            StripeHardBoundary(-40.0, lambda y: 30.0 - 0.02 * y),
            StripeHardBoundary(60.0, lambda y: 20.0 + 0.04 * y),
        )
        residuals = time_platform_derivative_residuals(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            stripes=stripes,
            entry_y_mm=0.0,
            nominal_turning_y_mm=100.0,
            eta_turn_nodes=(0.9, 0.95, 1.05, 1.1),
            derivative_step=1e-3,
        )
        self.assertEqual(len(residuals), 4)
        self.assertTrue(all(math.isfinite(value) for value in residuals))


if __name__ == "__main__":
    unittest.main()
