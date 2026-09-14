"""Analytic residual vectors and report-schema parity for both consumers."""

import unittest

import numpy as np

from common.analysis.longitudinal_fit import fit_longitudinal_polynomial
from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_ideal_acceptance_aperture_campaign import (
    _polynomial_metrics as campaign_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_ideal_acceptance_aperture_full_flight import (
    _polynomial_metrics as full_flight_metrics,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_apertures import (
    _polynomial_fit_diagnostics as integration_metrics,
)


class LongitudinalFitTests(unittest.TestCase):
    def test_polynomial_and_orthogonal_residual_have_known_coefficients_and_sigma(self):
        z = np.arange(-2.0, 3.0)
        # Fourth finite-difference weights are orthogonal to powers 0..3.
        residual = np.array([1., -4., 6., -4., 1.]) / 8
        for degree in (1, 2, 3):
            coefficients = [2., -3., 4., 5.][-degree-1:]
            velocity = sum(c * z**p for p, c in enumerate(reversed(coefficients))) + residual
            fit = fit_longitudinal_polynomial(z, velocity, degree)
            np.testing.assert_allclose(fit.metrics['coefficients_descending_power'], coefficients, atol=1e-12)
            np.testing.assert_allclose(fit.residual_mm_per_us, residual, atol=1e-12)
            self.assertAlmostEqual(fit.metrics['residual_sample_sigma_mm_per_us'], np.sqrt(70/4)/8)
            self.assertAlmostEqual(fit.metrics['residual_rms_mm_per_us'], np.sqrt(70/5)/8)
            self.assertAlmostEqual(fit.metrics['residual_max_abs_mm_per_us'], 6/8)

    def test_consumers_keep_units_named_terms_and_integration_only_percentile(self):
        z = np.arange(-2.0, 3.0)
        velocity = 2*z**3 - 3*z**2 + 4*z + 5 + np.array([1., -4., 6., -4., 1.])/8
        for consumer in (campaign_metrics, full_flight_metrics, integration_metrics):
            metrics = consumer(z, velocity, degree=3)
            self.assertEqual(metrics['coefficient_units_descending_power'],
                             ['mm_per_us_per_mm3', 'mm_per_us_per_mm2', 'mm_per_us_per_mm', 'mm_per_us'])
            for name, expected in [('intercept_mm_per_us', 5), ('k_per_us', 4),
                                   ('quadratic_coefficient_per_mm_us', -3),
                                   ('cubic_coefficient_per_mm2_us', 2)]:
                self.assertAlmostEqual(metrics[name], expected)
            if consumer is integration_metrics:
                self.assertAlmostEqual(metrics['residual_abs_p95_mm_per_us'], .7)
            else:
                self.assertNotIn('residual_abs_p95_mm_per_us', metrics)

    def test_input_samples_are_not_mutated(self):
        z, velocity = np.arange(5.), np.array([1., 3., 6., 7., 10.])
        before = (z.copy(), velocity.copy())
        fit_longitudinal_polynomial(z, velocity, 2)
        np.testing.assert_array_equal(z, before[0])
        np.testing.assert_array_equal(velocity, before[1])


if __name__ == '__main__':
    unittest.main()
