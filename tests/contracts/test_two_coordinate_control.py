"""Numerical trust-region contract; no particle source or solver is run."""
import unittest

import numpy as np

from msplatform.analysis.two_coordinate_control import accepted_secant_update, bounded_coordinate_step, scaled_two_coordinate_step


class TwoCoordinateControlTests(unittest.TestCase):
    def test_secant_preserves_anchor_and_matches_observed_change(self):
        matrix = np.eye(2); dv = np.array([1., 2.]); dr = np.array([3., 4.])
        updated = accepted_secant_update(matrix, dv, dr)
        np.testing.assert_allclose(updated @ dv, dr)
        np.testing.assert_array_equal(matrix, np.eye(2))
        self.assertIs(accepted_secant_update(matrix, np.zeros(2), dr), matrix)

    def test_direct_rectangular_regularized_and_bounded_directions(self):
        one = np.ones(2)
        direct, method, _ = scaled_two_coordinate_step(np.eye(2), np.array([2., -4.]), one, one)
        np.testing.assert_allclose(direct, [-2., 4.])
        self.assertEqual(method, 'scaled_direct_solve')
        rectangular, method, _ = scaled_two_coordinate_step(np.array([[1.], [2.]]),
            np.array([1., 2.]), np.ones(1), one)
        np.testing.assert_allclose(rectangular, [-1.])
        self.assertEqual(method, 'scaled_rectangular_least_squares')
        _, method, condition = scaled_two_coordinate_step(np.diag([1., .001]), one, one, one)
        self.assertGreater(condition, 100.)
        self.assertEqual(method, 'ridge_regularized_scaled_least_squares')
        delta, alpha = bounded_coordinate_step(np.array([0., 0.]), np.array([2., -4.]),
            np.array([1., 3.]), np.array([-10., -10.]), np.array([10., 10.]))
        self.assertEqual(alpha, .5)
        np.testing.assert_allclose(delta, [1., -2.])
        with self.assertRaises(np.linalg.LinAlgError):
            scaled_two_coordinate_step(np.zeros((2, 2)), one, one, one)


if __name__ == '__main__':
    unittest.main()
