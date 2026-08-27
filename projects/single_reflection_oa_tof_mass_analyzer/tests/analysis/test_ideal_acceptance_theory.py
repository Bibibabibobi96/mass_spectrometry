"""Independent low-cost checks of ideal acceptance theory and population logic."""

from dataclasses import replace
import unittest

import numpy as np
from scipy.special import ndtri

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_design import prepare_source_quadrature
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_experiment import (
    accepted, exact_population_moments, midpoint_population,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_theory import (
    axial_time_coefficients, residual_time_sensitivity, uniform_polynomial_variance,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint, NumericalSourceSpec,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution, OuterGeometry, ReflectronGeometry, derive_three_zone_state,
    exact_total_normalized_time_from_state,
)


class IdealAcceptanceTheoryTests(unittest.TestCase):
    def setUp(self):
        self.spec = NumericalSourceSpec(100., 1.498375640839315,
                                       -2.9323518410018137, 228.80604377795845)
        source = self.spec.affine()
        outer = OuterGeometry(3.25, 17., .3, 250., 2000.)
        mirror = ReflectronGeometry(120., 96.1563, 600., 600.)
        inner = InnerSolution(1701.7426470174573, 9.880402594970798, -1.0391326394747527)
        self.point = IdealWorkingPoint(source, derive_three_zone_state(source, outer, inner.eta),
                                       mirror, inner, 42.742615461548496, None)

    def exact(self, offsets, residual=0., point=None):
        point = self.point if point is None else point
        velocity = (self.spec.center_velocity_m_per_s
                    + self.spec.velocity_slope_m_per_s_per_mm*np.asarray(offsets)+residual)
        factor = point.design_source.time_scale_s_per_mm_sqrt_v
        return np.asarray(exact_total_normalized_time_from_state(
            point.state, point.reflectron, point.inner, self.spec.center_x_mm+offsets,
            velocity*factor*1e3, point.focus_drift_mm))*factor*1e9

    def test_coefficients_close_first_three_orders_not_fourth(self):
        coefficients = axial_time_coefficients(self.point, order=6)
        np.testing.assert_allclose(coefficients[1:4], 0., atol=2e-10)
        self.assertAlmostEqual(coefficients[4], .261432398030247, places=11)
        self.assertAlmostEqual(coefficients[5], .16420282702811112, places=11)
        self.assertAlmostEqual(coefficients[6], .08216715832552902, places=11)

    def test_high_order_series_converges_to_independent_exact_time(self):
        offsets = np.linspace(-.4, .4, 17)
        exact = self.exact(offsets)
        errors = []
        for order in (4, 6, 12):
            polynomial = np.polynomial.polynomial.polyval(offsets,
                axial_time_coefficients(self.point, order=order))
            errors.append(float(np.max(abs(polynomial-exact))))
        self.assertGreater(errors[0], errors[1]*5)
        self.assertGreater(errors[1], errors[2]*10)
        self.assertLess(errors[2], 1e-8)

    def test_frozen_drift_is_not_implicitly_refocused(self):
        moved = replace(self.point, focus_drift_mm=self.point.focus_drift_mm+100.)
        offsets = np.array([-.1, 0., .1])
        coefficients = axial_time_coefficients(moved, order=8)
        self.assertGreater(abs(coefficients[1]), 1.)
        np.testing.assert_allclose(np.polynomial.polynomial.polyval(offsets, coefficients),
                                   self.exact(offsets, point=moved), rtol=0, atol=1e-9)

    def test_residual_sensitivity_matches_independent_velocity_perturbation(self):
        offsets = np.array([-1.2, -.5, 0., .5, 1.2])
        step = .1
        numerical = (self.exact(offsets, step)-self.exact(offsets, -step))/(2*step)
        analytic = residual_time_sensitivity(self.point, offsets)
        np.testing.assert_allclose(analytic, numerical, rtol=2e-7, atol=1e-9)
        self.assertAlmostEqual(analytic[2], -.013473428768299262, places=12)

    def test_quartic_uniform_variance_is_sixteen_over_225(self):
        half, coefficient = 1.4, 2.3
        expected = coefficient**2*half**8*16/225
        for constant in (0., 31331.3235, 1e12):
            actual = uniform_polynomial_variance(np.array([constant, 0., 0., 0., coefficient]), 2*half)
            self.assertAlmostEqual(actual, expected, places=12)

    def test_exact_population_variance_decomposes_without_gaussian_fwhm(self):
        q = prepare_source_quadrature(self.spec, full_width_mm=2.2,
            residual_sigma_m_per_s=10., position_order=24, residual_order=12)
        result = exact_population_moments(self.spec, self.point, q, envelope_sigma=6.)
        exact = self.exact(q.position_offset_mm, q.residual_m_per_s)
        mean = float(q.weights @ exact)
        variance = float(q.weights @ (exact-mean)**2)
        self.assertAlmostEqual(result["variance_ns2"], variance, places=12)
        self.assertAlmostEqual(result["conditional_mean_variance_ns2"]
                               + result["conditional_thickness_variance_ns2"], variance, places=10)
        self.assertLess(abs(result["variance_decomposition_residual_ns2"]), 1e-10)
        self.assertGreater(result["conditional_mean_variance_ns2"], 0.)
        self.assertGreater(result["conditional_thickness_variance_ns2"], 0.)
        self.assertFalse(result["fwhm_claim"])

    def test_zero_residual_has_zero_conditional_thickness_and_invalid_mirror_fails(self):
        q = prepare_source_quadrature(self.spec, full_width_mm=1.,
            residual_sigma_m_per_s=0., position_order=8, residual_order=4)
        result = exact_population_moments(self.spec, self.point, q, envelope_sigma=6.)
        self.assertLess(result["conditional_thickness_variance_ns2"], 1e-20)
        invalid = replace(self.point, inner=replace(self.point.inner, stage1_voltage_drop_v=1999.))
        with self.assertRaisesRegex(ValueError, "field regions"):
            exact_population_moments(self.spec, invalid, q, envelope_sigma=6.)

    def test_midpoint_population_is_equal_probability_complete_tensor(self):
        population = midpoint_population(self.spec, full_width_mm=2.,
            residual_sigma_m_per_s=10., position_order=4, residual_order=6)
        np.testing.assert_array_equal(population.particle_id, np.arange(1, 25))
        expected_x = np.repeat(np.array([-.75, -.25, .25, .75]), 6)
        expected_residual = np.tile(ndtri((np.arange(6)+.5)/6)*10., 4)
        np.testing.assert_allclose(population.source_x_mm-self.spec.center_x_mm, expected_x)
        np.testing.assert_allclose(population.residual_m_per_s, expected_residual)
        np.testing.assert_allclose(population.velocity_z_m_per_s,
            self.spec.center_velocity_m_per_s+self.spec.velocity_slope_m_per_s_per_mm*expected_x+expected_residual)
        self.assertFalse(hasattr(population, "weights"))

    def test_midpoint_population_rejects_fractional_counts(self):
        with self.assertRaises(ValueError):
            midpoint_population(self.spec, full_width_mm=1., residual_sigma_m_per_s=10.,
                                position_order=2.5, residual_order=4)

    def test_acceptance_requires_full_cohort_and_defined_finite_resolution(self):
        good = {"full_cohort_reachable": True, "peak_metrics": {"mass_resolution": 25000.}}
        self.assertTrue(accepted(good, 25000.))
        self.assertFalse(accepted({**good, "full_cohort_reachable": False}, 25000.))
        for resolution in (None, float("nan"), float("inf"), 24999.):
            self.assertFalse(accepted({**good, "peak_metrics": {"mass_resolution": resolution}}, 25000.))
        self.assertFalse(accepted({"full_cohort_reachable": True}, 25000.))


if __name__ == "__main__":
    unittest.main()
