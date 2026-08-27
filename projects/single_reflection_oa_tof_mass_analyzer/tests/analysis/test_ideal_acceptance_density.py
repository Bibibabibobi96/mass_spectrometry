"""Population-density correctness, explicit domain failures and convergence."""

from dataclasses import replace
import json
import unittest

import numpy as np
from scipy.integrate import cumulative_trapezoid

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_density import (
    compute_population_density, compute_residual_time_derivative,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_design import DesignDomainError
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint, NumericalSourceSpec, build_numerical_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution, OuterGeometry, ReflectronGeometry, derive_three_zone_state,
    exact_total_normalized_time_from_state,
)


class IdealAcceptanceDensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = NumericalSourceSpec(100., 1.498375640839315, -2.9323518410018137, 228.80604377795845)
        outer = OuterGeometry(3.25, 17., .3, 250., 2000.)
        mirror = ReflectronGeometry(120., 96.1563, 600., 600.)
        inner = InnerSolution(1701.7426470174573, 9.880402594970798, -1.0391326394747527)
        affine = cls.spec.affine()
        cls.point = IdealWorkingPoint(affine, derive_three_zone_state(affine, outer, inner.eta),
                                     mirror, inner, 42.742615461548496, None)
        cls.settings = dict(full_width_mm=2.8, residual_sigma_m_per_s=10.,
                            grid_points=2001, position_order=64, envelope_sigma=6.,
                            root_iterations=48, residual_tolerance_m_per_s=1e-7,
                            monotonicity_subdivisions=32)
        cls.result = compute_population_density(cls.spec, cls.point, **cls.settings)

    def _times(self, offset: np.ndarray, residual: np.ndarray) -> np.ndarray:
        scale = self.point.design_source.time_scale_s_per_mm_sqrt_v
        chi = (self.spec.center_velocity_m_per_s + self.spec.velocity_slope_m_per_s_per_mm * offset + residual) * scale * 1e3
        return np.asarray(exact_total_normalized_time_from_state(
            self.point.state, self.point.reflectron, self.point.inner,
            self.spec.center_x_mm + offset, chi, self.point.focus_drift_mm,
        )) * scale * 1e6

    def test_analytic_residual_derivative_matches_independent_finite_difference(self) -> None:
        offset = np.linspace(-1.4, 1.4, 17)
        residual = np.linspace(-50., 50., 17)
        step = .02
        exact = compute_residual_time_derivative(self.spec, self.point, offset, residual)
        difference = (self._times(offset, residual + step) - self._times(offset, residual - step)) / (2 * step)
        np.testing.assert_allclose(exact, difference, rtol=1e-6, atol=1e-11)

    def test_probability_mass_and_change_of_variable_are_normalized(self) -> None:
        r = self.result
        self.assertLess(abs(r.summary["probability_integration_error"]), 1e-7)
        self.assertAlmostEqual(float(np.trapezoid(r.mass_density_per_da, r.mass_grid_da)),
                               r.summary["integrated_probability"], places=7)
        self.assertGreater(r.summary["minimum_absolute_residual_derivative_bound_us_per_m_per_s"], 0.)
        self.assertEqual(r.summary["metric_kind"], "population_pushforward_density_not_finite_particle_kde")
        json.dumps(r.summary, allow_nan=False)

    def test_time_grid_and_position_integral_converge_without_kde_bandwidth(self) -> None:
        refined = compute_population_density(self.spec, self.point,
            **{**self.settings, "position_order": 128, "grid_points": 4001})
        self.assertLess(abs(refined.summary["resolution_mass"] / self.result.summary["resolution_mass"] - 1), 1e-4)
        # Regression for the old design: the population peak is not the low-N,
        # tail-broadened KDE peak. This interval is covered by grid convergence.
        self.assertGreater(refined.summary["resolution_mass"], 40190.)
        self.assertLess(refined.summary["resolution_mass"], 40200.)

    def test_narrow_source_matches_local_gaussian_width(self) -> None:
        narrow = compute_population_density(self.spec, self.point,
            **{**self.settings, "full_width_mm": .001, "position_order": 8})
        derivative = float(compute_residual_time_derivative(self.spec, self.point, np.array(0.), np.array(0.)))
        expected_ns = 2 * np.sqrt(2 * np.log(2)) * 10 * abs(derivative) * 1e3
        self.assertLess(abs(narrow.summary["fwhm_tof_ns"] / expected_ns - 1), 1e-4)

    def test_independent_monte_carlo_cdf_agrees_with_integrated_density(self) -> None:
        sample = build_numerical_source(self.spec, particle_count=5000, seed=19451,
                                       full_width_mm=2.8, residual_sigma_m_per_s=10.)
        times = self._times(sample.source_x_mm - self.spec.center_x_mm, sample.residual_m_per_s)
        r = self.result
        cdf = cumulative_trapezoid(r.time_density_per_us, r.time_grid_us, initial=0.)
        cdf /= cdf[-1]
        empirical = np.sort(times)
        probabilities = np.interp(empirical, r.time_grid_us, cdf)
        distance = max(np.max(np.arange(1, times.size + 1) / times.size - probabilities),
                       np.max(probabilities - np.arange(times.size) / times.size))
        # DKW 99% bound for N=5000 is 0.023; allow only that statistical budget.
        self.assertLess(float(distance), .0231)

    def test_invalid_numerics_and_zero_residual_fail_explicitly(self) -> None:
        for key, value in (("grid_points", True), ("position_order", 1),
                           ("residual_sigma_m_per_s", 0.), ("envelope_sigma", float("nan")),
                           ("residual_tolerance_m_per_s", -1.)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                compute_population_density(self.spec, self.point, **{**self.settings, key: value})

    def test_geometry_mirror_and_root_failures_are_not_physical_resolution_claims(self) -> None:
        with self.assertRaisesRegex(DesignDomainError, "first acceleration"):
            compute_population_density(self.spec, self.point, **{**self.settings, "full_width_mm": 3.})
        blocked = replace(self.point, inner=replace(self.point.inner, stage2_field_v_per_mm=.1))
        with self.assertRaisesRegex(DesignDomainError, "backplate"):
            compute_population_density(self.spec, blocked, **self.settings)
        with self.assertRaisesRegex(ArithmeticError, "root_iterations"):
            compute_population_density(self.spec, self.point, **{**self.settings, "root_iterations": 2})

    def test_nonmonotone_residual_map_is_rejected_even_with_all_events_reachable(self) -> None:
        folded = replace(self.point,
            inner=replace(self.point.inner, stage2_field_v_per_mm=.01),
            reflectron=replace(self.point.reflectron, stage2_length_mm=100000.))
        with self.assertRaisesRegex(DesignDomainError, "monotonicity"):
            compute_population_density(self.spec, folded, **self.settings)


if __name__ == "__main__":
    unittest.main()
