from __future__ import annotations

import math
import unittest
from pathlib import Path
import json

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    JointL0Trial,
    StripeHardBoundary,
    adiabatic_fast_phase_oscillation_count,
    classify_constraint_system,
    coupled_normalized_period_slope_at_energy,
    coupled_reduced_period_mm_per_sqrt_v,
    derive_coupled_drift_state,
    derive_coupled_drift_state_from_entry_direction,
    derive_turning_y_from_entry_direction,
    evaluate_joint_l0_trial,
    finite_difference_joint_jacobian,
    fit_dimensionless_psi_g_profiles,
    require_exactly_determined,
    reduced_action_delta_mm_sqrt_v,
    solve_exactly_determined_joint_l0,
    spatial_return_kappa_derivative_residual,
    stripes_from_contract,
    time_platform_derivative_residuals,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design, reduced_period
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    TwoPrismTransportObservation,
)


class JointMirrorStripeL0Test(unittest.TestCase):
    def test_spatial_return_derivative_does_not_renormalize_each_perturbed_turn(self) -> None:
        residual = spatial_return_kappa_derivative_residual(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            stripes=(StripeHardBoundary(100.0, lambda y: 10.0 - 0.1 * y),),
            entry_y_mm=0.0,
            nominal_turning_y_mm=-100.0,
            derivative_step=1e-3,
        )
        self.assertAlmostEqual(residual, 1.0, places=5)

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
            kappa_derivative_step=2e-3,
            time_platform_derivative_step=1e-3,
            energy_derivative_step_v=1.0,
        )

    def test_joint_trial_keeps_all_nine_downstream_analytic_residuals_together(self) -> None:
        report = evaluate_joint_l0_trial(self._trial(-2000.0))
        self.assertEqual(len(report.residuals), 9)
        self.assertEqual(report.residual_names()[:3], (
            "full_analyser_period_slope_at_3900V",
            "full_analyser_period_slope_at_4000V",
            "full_analyser_period_slope_at_4100V",
        ))
        self.assertNotIn("mirror_gamma_90_m11", report.residual_names())
        self.assertTrue(all(math.isfinite(value) for _name, value in report.residuals))

    def test_dimensionless_profile_fit_derives_normalization_from_the_physical_turn(self) -> None:
        trial = self._trial(-2000.0)
        result = fit_dimensionless_psi_g_profiles(
            mirror_reduced_period_mm_per_sqrt_v=reduced_period(4000.0, trial.mirror_design),
            energy_per_charge_v=4000.0,
            stripes=trial.stripes,
            entry_y_mm=trial.stripe_entry_y_mm,
            nominal_turning_y_mm=trial.nominal_turning_y_mm,
            eta_max=max(trial.time_platform_eta_nodes),
            polynomial_degree=5,
            sample_count=32,
        )
        self.assertEqual(len(result.psi_coefficients_by_power), 5)
        self.assertAlmostEqual(result.psi_at_nominal_turn, 1.0)
        self.assertAlmostEqual(result.psi_fit_at_nominal_turn, 1.0, places=10)
        self.assertLess(result.psi_max_abs_fit_residual, 1e-10)
        self.assertLess(result.g_max_abs_fit_residual, 1e-10)
        self.assertTrue(all(abs(value) < 1e-10 for value in result.psi_coefficients_by_power[1:]))

    def test_joint_trial_appends_the_two_three_dimensional_prism_targets(self) -> None:
        state = ProjectPhaseSpaceState((0.0, 0.0, -10.0), (0.0, 1.0, 0.0))
        trial = self._trial(-2000.0)
        slow_energy = 0.5 * 524.0 * 1.66053906660e-27 * (1000.0 ** 2) / 1.602176634e-19
        trial = JointL0Trial(
            **{**trial.__dict__,
               "prism_target_turn_y_mm": 0.0,
               "prism_target_slow_kinetic_energy_per_charge_v": slow_energy,
               "particle_mass_th": 524.0,
               "charge_state": 1,
               "two_prism_transport_observation": TwoPrismTransportObservation(state, state, state, True)}
        )
        report = evaluate_joint_l0_trial(trial)
        self.assertEqual(len(report.residuals), 11)
        self.assertEqual(dict(report.residuals)["P1_P2_phase_origin_turn_y_mm"], 0.0)

    def test_partial_prism_transport_input_fails_closed(self) -> None:
        trial = JointL0Trial(**{**self._trial(-2000.0).__dict__, "prism_target_turn_y_mm": 0.0})
        with self.assertRaises(CandidateContractError):
            evaluate_joint_l0_trial(trial)

    def test_joint_jacobian_requires_feasible_actual_residuals(self) -> None:
        report, classification = finite_difference_joint_jacobian(
            ("mirror_voltage_b",), (-2000.0,), (1.0,), lambda values: self._trial(values[0]),
        )
        self.assertEqual(len(report.residuals), 9)
        self.assertEqual(classification.status, "locally_incompatible")

        selected_report, selected = finite_difference_joint_jacobian(
            ("mirror_voltage_b",),
            (-2000.0,),
            (1.0,),
            lambda values: self._trial(values[0]),
            selected_residual_names=("target_oscillation_count", "spatial_return_kappa_prime"),
        )
        self.assertEqual(len(selected_report.residuals), 9)
        self.assertEqual(selected.declared_constraint_count, 2)

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
        self.assertEqual(classification.status, "locally_incompatible")
        with self.assertRaisesRegex(CandidateContractError, "locally_incompatible"):
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
        first, second = stripes_from_contract(contract, (-40.0, 60.0))
        y0, y1 = contract["dual_stripe"]["theory_profile"]["active_y_span_mm"]
        self.assertGreater(first.width_mm(y0), 0.0)
        self.assertGreater(second.width_mm(y1), 0.0)
        with self.assertRaises(CandidateContractError):
            first.width_mm(y1 + 1.0)

    def test_contract_adapter_applies_the_explicit_geometry_to_path_length_mapping(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = json.loads((root / "config" / "simion_candidate_two_zone.json").read_text(encoding="utf-8"))
        nominal_first, _nominal_second = stripes_from_contract(contract, (-40.0, 60.0))
        doubled = json.loads(json.dumps(contract))
        doubled["dual_stripe"]["theory_profile"]["path_length_mapping"][
            "profile_width_to_total_S_multiplier"
        ] = 2.0
        doubled_first, _doubled_second = stripes_from_contract(doubled, (-40.0, 60.0))
        self.assertAlmostEqual(doubled_first.width_mm(0.0), 2.0 * nominal_first.width_mm(0.0))

    def test_current_hardware_problem_declares_derived_quantities_separately(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = json.loads((root / "config" / "simion_candidate_two_zone.json").read_text(encoding="utf-8"))
        problem = contract["dual_stripe_l0"]["current_fixed_hardware_l0_l1_problem"]
        self.assertEqual(problem["mirror_independent_unknowns"], [
            "mirror_voltage_B_v", "mirror_voltage_C_v", "mirror_voltage_D_v", "mirror_voltage_E_v",
        ])
        self.assertEqual(problem["mirror_named_residual_blocks"], [
            "mirror_period_slope_at_3900V", "mirror_period_slope_at_4000V",
            "mirror_period_slope_at_4100V",
        ])
        self.assertEqual(problem["stripe_fixed_hardware_independent_unknowns"], [
            "stripe_set_1_bias_v", "stripe_set_2_bias_v",
        ])
        self.assertEqual(problem["stripe_fixed_hardware_inputs"], [
            "manufactured_design_abs_drift_length_L_mm",
        ])
        self.assertEqual(problem["prism_transport_independent_unknowns"], [
            "prism_1_voltage_v", "prism_2_voltage_v",
        ])
        self.assertEqual(len(problem["downstream_independent_unknown_inventory"]), 4)
        self.assertEqual(problem["global_energy_calibration_diagnostic_residual_blocks"], [
            "full_analyser_period_slope_at_3900V",
            "full_analyser_period_slope_at_4000V",
            "full_analyser_period_slope_at_4100V",
        ])
        drift_residuals = problem["stripe_fixed_hardware_operating_residual_blocks"]
        self.assertNotIn("mirror_gamma_90_m11", drift_residuals)
        self.assertEqual(len(drift_residuals), 6)
        self.assertEqual(problem["prism_transport_named_residual_blocks"], [
            "P1_P2_phase_origin_turn_y_mm",
            "P1_P2_slow_kinetic_energy_per_charge_v",
        ])
        self.assertIn("stripe_entrance_project_position_mm", problem["derived_not_independent_unknowns"])
        self.assertNotIn("drift_length_L_mm", problem["derived_not_independent_unknowns"])
        self.assertNotIn(
            "nominal_drift_kinetic_energy_per_charge_v",
            problem["derived_not_independent_unknowns"],
        )
        partition = contract["prism_transport"]["energy_partition"]
        self.assertIn("initialization_only", partition["qualification"])
        self.assertIn("fixed nominal input", partition["candidate_operating_partition"])
        self.assertEqual(partition["total_kinetic_energy_ev"], 4005)
        self.assertEqual(partition["fast_reflection_kinetic_energy_ev"], 4000)
        initialization = problem["voltage_initialization"]
        self.assertEqual(
            initialization["authority"],
            "analytic_inverse_from_user_confirmed_manufactured_theory_basis",
        )
        envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
        self.assertEqual(envelope["B"]["minimum_inclusive_v"], -10000.0)
        self.assertEqual(
            envelope["D"]["maximum_inclusive_v"],
            "minimum_particle_net_acceleration_gain_per_charge_v",
        )
        self.assertEqual(envelope["E"]["maximum_inclusive_v"], 10000.0)
        self.assertIn("mirror.theory_requirements.voltage_envelope_v", initialization["semantics"])
        self.assertIn("historical_mirror_voltage_vector", initialization["forbidden_seed_sources"])
        self.assertIn("independently constructs and ranks", initialization["derivation_chain"][0])
        selection = problem["mirror_family_selection"]
        self.assertEqual(selection["selection_order"][0], "minimize_absolute_phase_averaged_transverse_time_aberration_Tbar_xx")
        self.assertIn("exactly three energy-local normalized period-slope equalities", selection["semantics"])
        review_point = contract["dual_stripe"]["geometry_review_visualization"]
        self.assertEqual(review_point["status"], "geometry_review_only__not_a_solver_seed")
        self.assertNotIn("set_1_bias_v", contract["dual_stripe"])
        self.assertNotIn("set_2_bias_v", contract["dual_stripe"])
        registration = contract["dual_stripe_l0"]["theory_function_coordinate_registration"]
        self.assertEqual(registration["function_y_zero_project_y_mm"], 0.0)
        self.assertEqual(registration["excluded_mechanical_extension_y_mm"], [-2.0, 0.0])
        shooting = contract["prism_transport"]["two_prism_injection_l0"]
        self.assertNotIn("prism_2_effective_plane_and_face_order_from_CAD", shooting["frozen_inputs_before_three_dimensional_shooting"])
        self.assertIn("prism_2_effective_plane_and_face_order_from_CAD", shooting["hard_boundary_seed_only_inputs"])

    def test_rank_gate_distinguishes_under_exact_and_incompatible_systems(self) -> None:
        under = classify_constraint_system(("mirror_voltage", "stripe_bias"), ("target_K",), jacobian_rows=((1.0, 0.0),))
        self.assertEqual(under.status, "underdetermined")
        with self.assertRaises(CandidateContractError):
            require_exactly_determined(under)
        exact = classify_constraint_system(("mirror_voltage", "stripe_bias"), ("target_K", "time_platform"), jacobian_rows=((1.0, 0.0), (0.0, 1.0)), residuals=(0.0, 0.0))
        self.assertEqual(exact.status, "square_exact")
        require_exactly_determined(exact)
        incompatible = classify_constraint_system(("mirror_voltage",), ("first", "second"), jacobian_rows=((1.0,), (1.0,)), residuals=(0.0, 1.0))
        self.assertEqual(incompatible.status, "locally_incompatible")

    def test_scaled_svd_distinguishes_consistent_redundancy_from_incompatibility(self) -> None:
        consistent = classify_constraint_system(
            ("stripe_bias_v",),
            ("condition_1", "condition_2"),
            jacobian_rows=((1.0e-3,), (2.0e-3,)),
            residuals=(2.0e-6, 4.0e-6),
            parameter_scales=(1000.0,),
            residual_scales=(1.0e-3, 2.0e-3),
        )
        self.assertEqual(consistent.status, "overdetermined_consistent")
        self.assertEqual(consistent.nullity, 0)
        self.assertEqual(consistent.redundant_constraint_count, 1)
        self.assertAlmostEqual(consistent.scaled_irreducible_residual_norm_2, 0.0, places=12)
        require_exactly_determined(consistent)
        incompatible = classify_constraint_system(
            ("stripe_bias_v",),
            ("condition_1", "condition_2"),
            jacobian_rows=((1.0e-3,), (2.0e-3,)),
            residuals=(2.0e-6, 5.0e-6),
            parameter_scales=(1000.0,),
            residual_scales=(1.0e-3, 2.0e-3),
            compatibility_tolerance=1.0e-6,
        )
        self.assertEqual(incompatible.status, "locally_incompatible")
        self.assertGreater(incompatible.scaled_irreducible_residual_norm_2, 1.0e-6)

    def test_count_without_jacobian_never_claims_exact_determination(self) -> None:
        result = classify_constraint_system(("mirror_voltage",), ("target_K",))
        self.assertEqual(result.status, "rank_unverified")

    def test_baseline_action_changes_the_same_trial_period(self) -> None:
        mirror_period = 10.0
        corrected = coupled_reduced_period_mm_per_sqrt_v(mirror_period, 4000.0, (20.0, 30.0), (-40.0, 60.0))
        self.assertNotEqual(corrected, mirror_period)
        self.assertGreater(corrected, 0.0)

    def test_full_analyser_uses_three_local_energy_slopes(self) -> None:
        trial = self._trial(-2000.0)
        widths = tuple(stripe.width_mm(trial.stripe_entry_y_mm) for stripe in trial.stripes)
        biases = tuple(stripe.bias_v for stripe in trial.stripes)
        slope = coupled_normalized_period_slope_at_energy(
            trial.mirror_design,
            4000.0,
            widths,
            biases,
            1.0,
        )
        report = dict(evaluate_joint_l0_trial(trial).residuals)
        self.assertAlmostEqual(report["full_analyser_period_slope_at_4000V"], slope, places=15)

    def test_nominal_state_derives_l_w_theta_and_k_without_external_w(self) -> None:
        stripes = (
            StripeHardBoundary(40.0, lambda y: 30.0 - 0.02 * y),
            StripeHardBoundary(-60.0, lambda y: 20.0 + 0.04 * y),
        )
        state = derive_coupled_drift_state(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            target_oscillation_count=25,
            stripes=stripes,
            entry_y_mm=0.0,
            turning_y_mm=-100.0,
        )
        self.assertAlmostEqual(state.drift_length_l_mm, 100.0)
        self.assertAlmostEqual(state.axial_width_w_mm, 10.0 * math.sqrt(4000.0))
        self.assertNotAlmostEqual(
            state.axial_width_w_mm,
            state.coupled_reduced_period_mm_per_sqrt_v * math.sqrt(4000.0),
        )
        self.assertGreater(state.nominal_kappa_1, 0.0)
        self.assertGreater(state.nominal_injection_angle_rad, 0.0)
        self.assertGreater(state.paper_normalized_oscillation_count, 0.0)
        self.assertGreater(state.predicted_oscillation_count, 0.0)

    def test_stripe_on_fast_phase_uses_local_period_inside_integral(self) -> None:
        stripes = (
            StripeHardBoundary(40.0, lambda y: 30.0 - 0.02 * y),
            StripeHardBoundary(-60.0, lambda y: 20.0 + 0.04 * y),
        )
        state = derive_coupled_drift_state(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            target_oscillation_count=25,
            stripes=stripes,
            entry_y_mm=0.0,
            turning_y_mm=-100.0,
        )
        direct = adiabatic_fast_phase_oscillation_count(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            stripes=stripes,
            entry_y_mm=0.0,
            turning_y_mm=-100.0,
        )
        self.assertAlmostEqual(state.predicted_oscillation_count, direct, places=12)
        self.assertNotAlmostEqual(
            state.predicted_oscillation_count,
            state.paper_normalized_oscillation_count,
            places=10,
        )

    def test_width_baselines_change_full_period_but_not_mirror_owned_drift_normalization(self) -> None:
        first = (
            StripeHardBoundary(40.0, lambda y: 30.0 - 0.02 * y),
            StripeHardBoundary(-60.0, lambda y: 20.0 + 0.04 * y),
        )
        shifted = (
            StripeHardBoundary(40.0, lambda y: 130.0 - 0.02 * y),
            StripeHardBoundary(-60.0, lambda y: 220.0 + 0.04 * y),
        )
        states = [
            derive_coupled_drift_state(
                mirror_reduced_period_mm_per_sqrt_v=10.0,
                energy_per_charge_v=4000.0,
                target_oscillation_count=25,
                stripes=stripes,
                entry_y_mm=0.0,
                turning_y_mm=-100.0,
            )
            for stripes in (first, shifted)
        ]
        self.assertNotEqual(
            states[0].coupled_reduced_period_mm_per_sqrt_v,
            states[1].coupled_reduced_period_mm_per_sqrt_v,
        )
        self.assertEqual(states[0].axial_width_w_mm, states[1].axial_width_w_mm)
        self.assertAlmostEqual(states[0].turning_pseudopotential_v, states[1].turning_pseudopotential_v)
        self.assertAlmostEqual(states[0].nominal_kappa_1, states[1].nominal_kappa_1)
        self.assertNotEqual(
            states[0].predicted_oscillation_count,
            states[1].predicted_oscillation_count,
        )

    def test_entry_direction_derives_first_physical_turn_without_free_l(self) -> None:
        stripes = (
            StripeHardBoundary(40.0, lambda y: 30.0 - 0.02 * y),
            StripeHardBoundary(-60.0, lambda y: 20.0 + 0.04 * y),
        )
        turning = derive_turning_y_from_entry_direction(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            stripes=stripes,
            entry_y_mm=0.0,
            entry_unit_direction_project=(0.0, -0.01, -1.0),
            search_end_y_mm=-300.0,
            sample_count=300,
        )
        self.assertLess(turning, 0.0)
        state = derive_coupled_drift_state_from_entry_direction(
            mirror_reduced_period_mm_per_sqrt_v=10.0,
            energy_per_charge_v=4000.0,
            target_oscillation_count=25,
            stripes=stripes,
            entry_y_mm=0.0,
            entry_unit_direction_project=(0.0, -0.01, -1.0),
            search_end_y_mm=-300.0,
            sample_count=300,
        )
        self.assertAlmostEqual(state.drift_length_l_mm, abs(turning))

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
