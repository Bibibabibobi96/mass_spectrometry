"""Regression tests for the solver-free three-zone ideal-theory oracle."""

from __future__ import annotations

import math
import unittest

import numpy as np

from common.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_root_solver import (
    JacobianLimits,
    JacobianSettings,
    RootBounds,
    RootSearchSettings,
    RootSeed,
    collect_three_zone_roots,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    AffineSource,
    InnerSolution,
    OuterGeometry,
    PhysicsGateLimits,
    ReflectronGeometry,
    build_exact_cohort,
    compute_time_derivatives,
    derive_three_zone_state,
    evaluate_three_zone_design,
    exact_accelerator_normalized_time,
    exact_accelerator_normalized_time_from_state,
    exact_total_normalized_time,
    exact_total_normalized_time_from_state,
    source_energy_per_charge,
)


class ThreeZoneIdealTheoryTests(unittest.TestCase):
    """Freeze the independently recomputed C3 pilot and identity oracles."""

    @staticmethod
    def source() -> AffineSource:
        return AffineSource.from_velocity(
            mass_to_charge_th=100.0,
            center_x_mm=1.498375640839315,
            center_velocity_m_per_s=-2.9323518410018137,
            velocity_slope_m_per_s_per_mm=228.80604377795845,
        )

    @staticmethod
    def outer(*, split_fraction: float = 0.55) -> OuterGeometry:
        return OuterGeometry(
            zone1_length_mm=4.5,
            downstream_length_mm=17.0,
            split_fraction=split_fraction,
            zone1_voltage_drop_v=250.0,
            nominal_energy_per_charge_v=2000.0,
        )

    @staticmethod
    def reflectron(*, upstream_drift_mm: float = 600.0) -> ReflectronGeometry:
        return ReflectronGeometry(
            stage1_length_mm=120.0,
            stage2_length_mm=96.1563,
            upstream_drift_mm=upstream_drift_mm,
            downstream_drift_mm=600.0,
        )

    @staticmethod
    def candidate() -> InnerSolution:
        return InnerSolution(
            stage1_voltage_drop_v=1762.5730126973656,
            stage2_field_v_per_mm=10.383472997268399,
            eta=-2.2157577786035914,
        )

    @staticmethod
    def permissive_ideal_limits() -> PhysicsGateLimits:
        # The current approved engineering voltage envelope is intentionally not
        # an ideal-theory physics gate; the static repository safety envelope is.
        return PhysicsGateLimits(
            minimum_zone_length_mm=0.84,
            minimum_electrode_clearance_mm=0.1,
            minimum_energy_margin_v=1.0,
            minimum_abs_energy_slope_v_per_mm=1.0,
            minimum_focus_drift_mm=1.0,
            maximum_accelerator_focus_envelope_mm=67.3503680966,
            minimum_stage1_voltage_v=0.0,
            maximum_stage1_voltage_v=10000.0,
            maximum_accelerator_field_v_per_mm=1000.0,
            maximum_accelerator_field_contrast=20.0,
            minimum_stage2_depth_margin_mm=1.0,
        )

    def test_affine_source_preserves_signed_chi_and_mm_to_seconds_scale(self) -> None:
        source = self.source()
        root_factor = math.sqrt(
            100.0 * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C / 2.0
        )
        self.assertAlmostEqual(
            source.time_scale_s_per_mm_sqrt_v,
            1.0e-3 * root_factor,
            delta=1e-18,
        )
        self.assertAlmostEqual(
            source.chi_center_sqrt_v,
            -2.9323518410018137 * root_factor,
            delta=1e-15,
        )
        self.assertLess(source.chi_center_sqrt_v, 0.0)

    def test_independent_state_oracle_matches_affine_manifold(self) -> None:
        source = self.source()
        outer = self.outer()
        inner = self.candidate()
        state = derive_three_zone_state(source, outer, inner.eta)
        derivatives = compute_time_derivatives(source, state, self.reflectron(), inner)
        positions = np.linspace(source.center_x_mm - 0.2, source.center_x_mm + 0.2, 7)
        chi = source.chi(positions)
        self.assertTrue(np.allclose(
            exact_accelerator_normalized_time(
                source, state, positions, derivatives.focus_drift_after_exit_mm
            ),
            exact_accelerator_normalized_time_from_state(
                state, positions, chi, derivatives.focus_drift_after_exit_mm
            ),
            rtol=0.0, atol=1e-14,
        ))
        self.assertTrue(np.allclose(
            exact_total_normalized_time(
                source, state, self.reflectron(), inner, positions,
                derivatives.focus_drift_after_exit_mm,
            ),
            exact_total_normalized_time_from_state(
                state, self.reflectron(), inner, positions, chi,
                derivatives.focus_drift_after_exit_mm,
            ),
            rtol=0.0, atol=1e-14,
        ))

        state = derive_three_zone_state(source, self.outer(), self.candidate().eta)
        drift = compute_time_derivatives(
            source, state, self.reflectron(), self.candidate()
        ).focus_drift_after_exit_mm
        actual = exact_accelerator_normalized_time(
            source, state, source.center_x_mm, drift
        )
        energy = source_energy_per_charge(source, state, source.center_x_mm)
        chi = source.chi_center_sqrt_v
        signed_formula = (
            2.0 / state.field1_v_per_mm * (math.sqrt(energy - state.grid1_v) - chi)
            + 2.0
            / state.field2_v_per_mm
            * (
                math.sqrt(energy - state.grid2_v)
                - math.sqrt(energy - state.grid1_v)
            )
            + 2.0
            / state.field3_v_per_mm
            * (math.sqrt(energy) - math.sqrt(energy - state.grid2_v))
            + drift / math.sqrt(energy)
        )
        self.assertAlmostEqual(actual, signed_formula, delta=1e-13)
        unsigned_formula = signed_formula + 2.0 / state.field1_v_per_mm * (
            chi - abs(chi)
        )
        self.assertGreater(abs(actual - unsigned_formula), 1e-5)

        cohort = build_exact_cohort(
            source,
            state,
            self.reflectron(),
            self.candidate(),
            width_mm=0.5,
            sample_count=11,
        )
        np.testing.assert_allclose(
            cohort.tof_us,
            cohort.normalized_time_mm_sqrt_v
            * source.time_scale_s_per_mm_sqrt_v
            * 1.0e6,
            rtol=0.0,
            atol=1e-14,
        )

    def test_eta_zero_is_exact_two_zone_degeneration(self) -> None:
        source = self.source()
        inner = InnerSolution(
            stage1_voltage_drop_v=1455.143905794,
            stage2_field_v_per_mm=8.495082391735,
            eta=0.0,
        )
        low_split = derive_three_zone_state(source, self.outer(split_fraction=0.25), 0.0)
        high_split = derive_three_zone_state(source, self.outer(split_fraction=0.75), 0.0)
        self.assertEqual(low_split.field2_v_per_mm, low_split.field3_v_per_mm)
        self.assertEqual(high_split.field2_v_per_mm, high_split.field3_v_per_mm)
        self.assertEqual(low_split.affine_g, 0.0)
        self.assertEqual(high_split.affine_g, 0.0)

        xs = np.linspace(source.center_x_mm - 1.1, source.center_x_mm + 1.1, 1001)
        low_drift = compute_time_derivatives(
            source, low_split, self.reflectron(), inner
        ).focus_drift_after_exit_mm
        high_drift = compute_time_derivatives(
            source, high_split, self.reflectron(), inner
        ).focus_drift_after_exit_mm
        self.assertAlmostEqual(low_drift, high_drift, delta=1e-11)
        low_times = exact_total_normalized_time(
            source, low_split, self.reflectron(), inner, xs, low_drift
        )
        high_times = exact_total_normalized_time(
            source, high_split, self.reflectron(), inner, xs, high_drift
        )
        np.testing.assert_allclose(low_times, high_times, rtol=0.0, atol=2e-13)

        energy = np.asarray(source_energy_per_charge(source, low_split, xs))
        chi = np.asarray(source.chi(xs))
        two_zone_accelerator = (
            2.0
            / low_split.field1_v_per_mm
            * (np.sqrt(energy - low_split.grid1_v) - chi)
            + 2.0
            / low_split.field2_v_per_mm
            * (np.sqrt(energy) - np.sqrt(energy - low_split.grid1_v))
            + low_drift / np.sqrt(energy)
        )
        np.testing.assert_allclose(
            exact_accelerator_normalized_time(
                source, low_split, xs, low_drift
            ),
            two_zone_accelerator,
            rtol=0.0,
            atol=2e-13,
        )

    def test_high_contrast_pilot_fields_derivatives_and_exact_peak_metrics(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), self.candidate().eta)
        derivatives = compute_time_derivatives(
            source, state, self.reflectron(), self.candidate()
        )
        self.assertAlmostEqual(state.zone2_length_mm, 9.35, delta=1e-13)
        self.assertAlmostEqual(state.zone3_length_mm, 7.65, delta=1e-13)
        self.assertAlmostEqual(state.field2_v_per_mm, 23.06316927894989, delta=2e-9)
        self.assertAlmostEqual(state.field3_v_per_mm, 211.45130175157627, delta=2e-9)
        self.assertAlmostEqual(state.grid2_v, 1617.6024583995584, delta=2e-8)
        self.assertAlmostEqual(
            derivatives.focus_drift_after_exit_mm, 40.09732696997708, delta=2e-8
        )
        self.assertLess(abs(derivatives.d1), 1e-12)
        self.assertLess(abs(derivatives.d2), 1e-13)
        self.assertLess(abs(derivatives.d3), 1e-15)
        self.assertAlmostEqual(derivatives.d4, 2.2521535254576206e-10, delta=2e-18)
        self.assertGreater(abs(derivatives.d4), 1e-11)

        cohort = build_exact_cohort(
            source,
            state,
            self.reflectron(),
            self.candidate(),
            width_mm=2.2,
            sample_count=1001,
        )
        self.assertAlmostEqual(cohort.population_sigma_ns, 0.0326914522181, delta=2e-10)
        self.assertAlmostEqual(cohort.sample_sigma_ns, 0.0327077938598, delta=2e-10)
        metrics, _ = compute_peak_metrics(cohort.tof_us, 100.0)
        self.assertEqual(metrics["particles"], 1001)
        self.assertAlmostEqual(metrics["mean_tof_us"], 30.9018297555965, delta=2e-10)
        self.assertAlmostEqual(metrics["std_tof_ns"], cohort.sample_sigma_ns, delta=1e-12)
        self.assertAlmostEqual(
            metrics["direct_fwhm_tof_ns"], 0.0252838915671, delta=2e-7
        )
        self.assertEqual(metrics["significant_kde_modes"], 1)

    def test_low_contrast_c3_anchor_peak_metrics(self) -> None:
        source = self.source()
        outer = OuterGeometry(
            zone1_length_mm=3.25,
            downstream_length_mm=17.0,
            split_fraction=0.30,
            zone1_voltage_drop_v=250.0,
            nominal_energy_per_charge_v=2000.0,
        )
        inner = InnerSolution(
            stage1_voltage_drop_v=1701.7426470171715,
            stage2_field_v_per_mm=9.880402594968652,
            eta=-1.0391326394747527,
        )
        state = derive_three_zone_state(source, outer, inner.eta)
        derivatives = compute_time_derivatives(source, state, self.reflectron(), inner)
        self.assertLessEqual(
            max(
                state.field1_v_per_mm,
                state.field2_v_per_mm,
                state.field3_v_per_mm,
            )
            / min(
                state.field1_v_per_mm,
                state.field2_v_per_mm,
                state.field3_v_per_mm,
            ),
            3.0,
        )
        self.assertAlmostEqual(
            derivatives.focus_drift_after_exit_mm, 42.7426154615485, delta=2e-10
        )
        self.assertLess(max(abs(derivatives.d1), abs(derivatives.d2), abs(derivatives.d3)), 1e-15)
        self.assertAlmostEqual(derivatives.d4, 2.4892814297124147e-10, delta=2e-18)

        cohort = build_exact_cohort(
            source,
            state,
            self.reflectron(),
            inner,
            width_mm=2.2,
            sample_count=1001,
        )
        self.assertAlmostEqual(cohort.population_sigma_ns, 0.1824010908675, delta=2e-10)
        metrics, _ = compute_peak_metrics(cohort.tof_us, 100.0)
        self.assertAlmostEqual(metrics["mean_tof_us"], 31.3314271787927, delta=2e-10)
        self.assertAlmostEqual(metrics["std_tof_ns"], 0.1824922686242, delta=2e-10)
        self.assertAlmostEqual(
            metrics["direct_fwhm_tof_ns"], 0.1411351744558, delta=2e-7
        )
        self.assertEqual(metrics["significant_kde_modes"], 1)

    def test_upstream_drift_is_focus_based_not_frozen_exit_distance(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), self.candidate().eta)
        correct = compute_time_derivatives(
            source, state, self.reflectron(upstream_drift_mm=600.0), self.candidate()
        )
        mechanical_exit_to_reflectron_mm = (
            600.0 + correct.focus_drift_after_exit_mm
        )
        self.assertAlmostEqual(mechanical_exit_to_reflectron_mm, 640.0973269699771, delta=2e-8)
        self.assertLess(max(abs(correct.d1), abs(correct.d2), abs(correct.d3)), 1e-12)

        wrong = compute_time_derivatives(
            source,
            state,
            self.reflectron(
                upstream_drift_mm=600.0 - correct.focus_drift_after_exit_mm
            ),
            self.candidate(),
        )
        self.assertGreater(abs(wrong.d1), 1e-4)

    def test_physics_gates_include_backward_turn_but_not_current_u_envelope(self) -> None:
        evaluation = evaluate_three_zone_design(
            self.source(),
            self.outer(),
            self.reflectron(),
            self.candidate(),
            width_mm=2.2,
            sample_count=1001,
            physics_limits=self.permissive_ideal_limits(),
        )
        self.assertGreater(self.candidate().stage1_voltage_drop_v, 1650.0)
        self.assertTrue(evaluation.gates.passed, evaluation.gates.failed_names)
        self.assertNotIn(
            "current_approved_voltage_envelope",
            {check.name for check in evaluation.gates.checks},
        )

        backward_source = AffineSource.from_velocity(
            mass_to_charge_th=100.0,
            center_x_mm=1.498375640839315,
            center_velocity_m_per_s=-12000.0,
            velocity_slope_m_per_s_per_mm=228.80604377795845,
        )
        backward = evaluate_three_zone_design(
            backward_source,
            self.outer(),
            self.reflectron(),
            self.candidate(),
            width_mm=0.5,
            sample_count=101,
            physics_limits=self.permissive_ideal_limits(),
        )
        self.assertFalse(backward.gates.passed)
        self.assertIn("backward_turn_clearance_mm", backward.gates.failed_names)

    def test_root_collection_does_not_stop_at_first_failed_seed(self) -> None:
        source = self.source()
        outer = self.outer()
        reflectron = self.reflectron()
        inner = self.candidate()
        center_energy = (
            outer.nominal_energy_per_charge_v + source.chi_center_sqrt_v**2
        )
        exact_seed = RootSeed(
            inner.stage1_voltage_drop_v / center_energy,
            inner.stage2_field_v_per_mm
            * reflectron.stage2_length_mm
            / center_energy,
            inner.eta / math.log(10.0),
        )
        settings = RootSearchSettings(
            seeds=(RootSeed(2.0, 2.0, 2.0), exact_seed),
            bounds=RootBounds(0.5, 0.99, 0.1, 1.0, -1.5, 1.5),
            convergence_tolerance=1e-10,
            maximum_iterations=2,
            maximum_backtracks=4,
            cluster_distance=1e-8,
            jacobian=JacobianSettings(
                eta_scale=math.log(10.0),
                step_u=1e-5,
                step_f=1e-5,
                step_eta_hat=1e-5,
                stability_step_multiplier=0.5,
                rank_relative_tolerance=1e-10,
            ),
            limits=JacobianLimits(
                root_residual_absolute_max=1e-10,
                minimum_reciprocal_condition=0.0,
                maximum_condition_number=1e12,
                maximum_jacobian_stability_relative_error=1.0,
                minimum_gamma3_uncertainty_multiple=0.0,
            ),
        )
        collection = collect_three_zone_roots(
            source,
            outer,
            reflectron,
            width_mm=2.2,
            cohort_sample_count=101,
            physics_limits=self.permissive_ideal_limits(),
            settings=settings,
        )
        self.assertEqual(len(collection.attempts), 2)
        self.assertEqual(collection.attempts[0].reason, "seed_out_of_bounds")
        self.assertTrue(collection.attempts[1].converged)
        self.assertEqual(len(collection.candidates), 1)
        self.assertEqual(collection.candidates[0].source_seed_indices, (1,))
        self.assertEqual(collection.accepted_candidates, collection.candidates)


if __name__ == "__main__":
    unittest.main()
