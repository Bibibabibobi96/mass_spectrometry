from __future__ import annotations

import math
import unittest

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
    AxisFieldResponseBasis,
    AxisResponseBasis,
    normalized_slopes,
    reduced_period_from_basis,
)


class MirrorRealFieldVoltageFamilyTest(unittest.TestCase):

    def test_harmonic_response_has_energy_independent_period(self) -> None:
        z = np.linspace(-10.0, 10.0, 401)
        responses = np.zeros((len(z), 4))
        responses[:, 0] = 10000.0 * z * z
        basis = AxisResponseBasis(z, responses, 10000.0)

        period, turns = reduced_period_from_basis(basis, 25.0, (1.0, 0.0, 0.0, 0.0))

        self.assertAlmostEqual(period, math.pi, places=5)
        self.assertAlmostEqual(turns[0], -5.0, places=9)
        self.assertAlmostEqual(turns[1], 5.0, places=9)
        slopes = normalized_slopes(basis, (1.0, 0.0, 0.0, 0.0), (20.0, 25.0, 30.0), 0.1)
        self.assertLess(max(abs(value) for value in slopes), 1e-8)

    def test_linearly_interpolated_axis_field_integrates_to_piecewise_quadratic_potential(self) -> None:
        z = np.linspace(-10.0, 10.0, 41)
        ez_responses = np.zeros((len(z), 4))
        ez_responses[:, 0] = -20000.0 * z
        basis = AxisFieldResponseBasis(z, ez_responses, 10000.0)

        potential = basis.potential((1.0, 0.0, 0.0, 0.0))

        np.testing.assert_allclose(potential(z), z * z, rtol=0.0, atol=1.0e-12)
        np.testing.assert_allclose(potential.derivative()(z), 2.0 * z, rtol=0.0, atol=1.0e-12)
        period, turns = reduced_period_from_basis(
            basis, 25.0, (1.0, 0.0, 0.0, 0.0),
        )
        self.assertAlmostEqual(period, math.pi, places=5)
        self.assertEqual(turns, (-5.0, 5.0))

    def test_rejects_voltage_vector_with_wrong_dimension(self) -> None:
        z = np.linspace(-10.0, 10.0, 41)
        basis = AxisResponseBasis(z, np.zeros((len(z), 4)), 10000.0)
        with self.assertRaises(Exception):
            basis.potential((1.0, 2.0, 3.0))


if __name__ == "__main__":
    unittest.main()
