"""Small deterministic regressions for the ideal numerical-source comparison."""

from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np

from common.analysis.peak_metrics import AnalysisSettings
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    AxialParticleSource,
    NumericalSourceSpec,
    build_numerical_source,
    build_working_point,
    propagate_ideal_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    exact_total_normalized_time,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison import slope_scan


class IdealSourceComparisonTests(unittest.TestCase):
    """Cover pairing, fixed geometry, exact time parity, and complete loss accounting."""

    def setUp(self) -> None:
        self.spec = NumericalSourceSpec(100.0, 1.498375640839315, -2.9323518410018137, 228.80604377795845)
        self.outer = OuterGeometry(3.25, 17.0, 0.3, 250.0, 2000.0)
        self.reflectron = ReflectronGeometry(120.0, 96.1563, 600.0, 600.0)
        self.settings = AnalysisSettings(grid_points=201, standardized_grid_points=101)

    def point(self, slope: float | None = None, eta: float = -1.0391326394747527):
        return build_working_point(
            self.spec, self.outer, self.reflectron,
            design_velocity_slope_m_per_s_per_mm=self.spec.velocity_slope_m_per_s_per_mm if slope is None else slope,
            eta=eta, focus_drift_mm=42.742615461548496,
        )

    def sample(self, count: int = 31, width: float = 1.0, sigma: float = 3.0):
        return build_numerical_source(self.spec, particle_count=count, seed=73, full_width_mm=width, residual_sigma_m_per_s=sigma)

    def test_random_pairs_preserve_prefix_and_residual_scaling(self) -> None:
        small, large = self.sample(17), self.sample(31)
        np.testing.assert_array_equal(small.source_x_mm, large.source_x_mm[:17])
        np.testing.assert_array_equal(small.residual_m_per_s, large.residual_m_per_s[:17])
        wide = self.sample(width=2.0, sigma=6.0)
        np.testing.assert_allclose(wide.source_x_mm-self.spec.center_x_mm, 2*(large.source_x_mm-self.spec.center_x_mm), atol=1e-15)
        np.testing.assert_array_equal(wide.residual_m_per_s, 2*large.residual_m_per_s)

    def test_quadratic_mean_and_no_detector_fit(self) -> None:
        spec = replace(self.spec, velocity_quadratic_m_per_s_per_mm2=17.0)
        source = build_numerical_source(spec, particle_count=17, seed=73, full_width_mm=1.0, residual_sigma_m_per_s=0.0)
        offset = source.source_x_mm-spec.center_x_mm
        np.testing.assert_allclose(source.velocity_z_m_per_s, spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*offset+17*offset**2)
        np.testing.assert_array_equal(source.residual_m_per_s, np.zeros(17))

    def test_reflectron_retuning_does_not_move_any_geometry_or_accelerator_voltage(self) -> None:
        before, after = self.point(0.0), self.point()
        self.assertEqual(before.reflectron, after.reflectron)
        self.assertEqual(before.focus_drift_mm, after.focus_drift_mm)
        for name in ("repeller_v", "grid1_v", "grid2_v", "field1_v_per_mm", "field2_v_per_mm", "field3_v_per_mm"):
            self.assertEqual(getattr(before.state, name), getattr(after.state, name))
        self.assertNotEqual(before.inner.stage1_voltage_drop_v, after.inner.stage1_voltage_drop_v)
        self.assertLess(abs(after.reflectron_solution.total_first_derivative_residual), 1e-12)
        self.assertLess(abs(after.reflectron_solution.total_second_derivative_residual), 1e-12)

    def test_zero_residual_matches_existing_affine_exact_total_time(self) -> None:
        source, point = self.sample(sigma=0.0), self.point()
        result = propagate_ideal_source(source, point, settings=self.settings)
        expected = exact_total_normalized_time(point.design_source, point.state, point.reflectron, point.inner, source.source_x_mm, point.focus_drift_mm)*point.design_source.time_scale_s_per_mm_sqrt_v*1e6
        np.testing.assert_allclose(result.tof_us, expected, atol=2e-14, rtol=1e-14)
        self.assertEqual(result.summary["detector_arrival_count"], 31)
        self.assertEqual(result.summary["status"], "SUCCESS")

    def test_fixed_reference_plane_closure_in_full_particle_times(self) -> None:
        point = self.point()
        offsets = np.linspace(-0.003, 0.003, 7)
        times = np.asarray(exact_total_normalized_time(
            point.design_source, point.state, point.reflectron, point.inner,
            self.spec.center_x_mm + offsets, point.focus_drift_mm,
        ))
        coefficients = np.polynomial.polynomial.polyfit(offsets, times-times[3], 4)
        # Finite-time differencing amplifies float64 roundoff by h^-order;
        # these bounds are tied to the evaluated time magnitude and stencil.
        roundoff = 64.0*np.spacing(float(np.max(times)))
        self.assertLess(abs(coefficients[1]), roundoff/0.001)
        self.assertLess(abs(coefficients[2]), roundoff/0.001**2)

    def test_two_zone_degeneration_independent_of_arbitrary_split(self) -> None:
        first = self.point(eta=0.0)
        second = build_working_point(self.spec, replace(self.outer, split_fraction=.7), self.reflectron, design_velocity_slope_m_per_s_per_mm=self.spec.velocity_slope_m_per_s_per_mm, eta=0.0, focus_drift_mm=first.focus_drift_mm)
        left = propagate_ideal_source(self.sample(), first, settings=self.settings)
        right = propagate_ideal_source(self.sample(), second, settings=self.settings)
        np.testing.assert_allclose(left.tof_us, right.tof_us, rtol=1e-14, atol=2e-14)

    def test_loss_labels_keep_full_mother_and_no_common_hit_filter(self) -> None:
        point = self.point()
        source = AxialParticleSource(np.arange(1, 5), np.array([-1., .01, 1.5, 1.5]), np.array([0., -2000., 0., 50000.]), np.zeros(4), 100.)
        result = propagate_ideal_source(source, point, settings=self.settings)
        self.assertEqual(result.classification.tolist(), ["source_outside_first_acceleration_zone", "repeller_collision", "detector_arrival", "reflectron_backplate_collision"])
        self.assertEqual(sum(result.summary["classification_counts"].values()), 4)
        self.assertFalse(result.summary["full_cohort_reachable"])
        self.assertTrue(np.isnan(result.tof_us[[0, 1, 3]]).all())

    def test_first_stage_mirror_turn_is_unsupported_not_fabricated_arrival(self) -> None:
        point = self.point()
        point = replace(point, inner=InnerSolution(2100.0, 10.0, point.inner.eta))
        result = propagate_ideal_source(self.sample(sigma=0.0), point, settings=self.settings)
        self.assertEqual(result.summary["classification_counts"], {"reflectron_stage1_turn_model_unsupported": 31})
        self.assertEqual(result.summary["status"], "NO_ARRIVALS")

    def test_identical_arrivals_have_no_infinite_or_fabricated_resolution(self) -> None:
        result = propagate_ideal_source(self.sample(width=0.0, sigma=0.0), self.point(), settings=self.settings)
        self.assertEqual(result.summary["status"], "SINGULAR_OR_NUMERICALLY_UNRESOLVED_PEAK")
        self.assertIsNone(result.summary["peak_metrics"])

    def test_invalid_source_and_mismatched_mass_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.sample(sigma=-1.0)
        with self.assertRaises(ValueError):
            AxialParticleSource(np.array([1, 1]), np.zeros(2), np.zeros(2), np.zeros(2), 100.)
        with self.assertRaises(ValueError):
            propagate_ideal_source(replace(self.sample(), mass_to_charge_th=300.), self.point(), settings=self.settings)

    def test_slope_scan_uses_theory_derived_matching_and_zero_slope_arms(self) -> None:
        config = slope_scan.load_json(Path(__file__).parents[2] / "config" / "experiments" / "ideal_source_affine_slope_scan.json")
        slope_scan.validate_slope_scan_config(config)
        zero = slope_scan._arms(config, 0.0)
        self.assertEqual(zero["zero_slope_design"], zero["matching_slope_design"])
        historical = slope_scan._arms(config, 37.79182865654923)
        self.assertNotEqual(historical["matching_slope_design"].design_source.chi_slope_sqrt_v_per_mm, 0.0)
        self.assertEqual(historical["zero_slope_design"].design_source.chi_slope_sqrt_v_per_mm, 0.0)
        self.assertNotEqual(historical["matching_slope_design"].inner, historical["zero_slope_design"].inner)
        self.assertNotEqual(
            historical["matching_slope_design"].state.field3_v_per_mm,
            historical["zero_slope_design"].state.field3_v_per_mm,
        )


if __name__ == "__main__":
    unittest.main()
