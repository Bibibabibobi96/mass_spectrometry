"""Known population pairs and degenerate/invalid input contracts."""
import unittest

import numpy as np

from common.analysis.population_moments import population_moments, population_pair_moments


class PopulationMomentsTests(unittest.TestCase):
    def test_hand_calculated_relative_weighted_population(self):
        # Total weight 4, squared-weight sum 6, mean (2, 2, 3).
        values = np.array([[0., 1., 2.], [2., 3., 2.], [4., 1., 6.]])
        original = values.copy()
        weights = np.array([1., 2., 1.])
        result = population_moments(values, weights)
        self.assertEqual(result.sample_count, 3)
        self.assertEqual(result.weight_sum, 4.)
        self.assertAlmostEqual(result.effective_sample_count, 8./3.)
        np.testing.assert_array_equal(result.mean, [2., 2., 3.])
        np.testing.assert_array_equal(result.covariance, [[2., 0., 2.], [0., 1., -1.], [2., -1., 3.]])
        np.testing.assert_array_equal(values, original)
        np.testing.assert_array_equal(weights, [1., 2., 1.])

    def test_equal_weights_and_weight_scale_do_not_change_population_moments(self):
        values = np.array([[0., 2.], [1., 2.], [2., 0.], [9., -4.]])
        unit = population_moments(values)
        equal = population_moments(values, [7., 7., 7., 7.])
        np.testing.assert_array_equal(equal.mean, unit.mean)
        np.testing.assert_array_equal(equal.covariance, unit.covariance)
        self.assertEqual(equal.effective_sample_count, 4.)
        self.assertEqual(equal.weight_sum, 28.)
        weights = np.array([1., 2., 3., 4.])
        reference = population_moments(values, weights)
        for factor in (1e-120, 1e120):
            with self.subTest(factor=factor):
                scaled = population_moments(values, weights*factor)
                # Floating scaling introduces only binary64 rounding.
                np.testing.assert_allclose(scaled.mean, reference.mean, rtol=8*np.finfo(float).eps)
                np.testing.assert_allclose(scaled.covariance, reference.covariance, rtol=8*np.finfo(float).eps)
                self.assertAlmostEqual(scaled.effective_sample_count, reference.effective_sample_count)

    def test_translation_rotation_and_row_reordering_preserve_declared_moments(self):
        values = np.array([[0., 1., 2.], [2., 3., 2.], [4., 1., 6.]])
        weights = np.array([1., 2., 1.])
        rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        translation = np.array([100., -12., 3.])
        reference = population_moments(values, weights)
        transformed = population_moments(values @ rotation.T + translation, weights)
        np.testing.assert_array_equal(transformed.mean, rotation @ reference.mean + translation)
        np.testing.assert_array_equal(transformed.covariance, rotation @ reference.covariance @ rotation.T)
        permutation = [2, 0, 1]
        reordered = population_moments(values[permutation], weights[permutation])
        np.testing.assert_array_equal(reordered.mean, reference.mean)
        np.testing.assert_array_equal(reordered.covariance, reference.covariance)

    def test_empty_singleton_and_constant_dimensions(self):
        for weights in (None, []):
            empty = population_moments(np.empty((0, 3)), weights)
            self.assertEqual((empty.sample_count, empty.weight_sum, empty.effective_sample_count), (0, 0., 0.))
            self.assertIsNone(empty.mean)
            self.assertIsNone(empty.covariance)
        singleton = population_moments([[7., -2.]], [5.])
        self.assertEqual(singleton.effective_sample_count, 1.)
        np.testing.assert_array_equal(singleton.mean, [7., -2.])
        np.testing.assert_array_equal(singleton.covariance, np.zeros((2, 2)))
        constant = population_moments([[1., 1.], [1., 3.]])
        np.testing.assert_array_equal(constant.covariance, [[0., 0.], [0., 1.]])

    def test_invalid_weights_are_rejected_without_removing_observations(self):
        values = np.array([[1., 2.], [3., 4.]])
        for weights in ([], [1.], [[1., 2.]], [0., 1.], [-1., 1.], [True, 1.],
                        ["1", "2"], [float("nan"), 1.], [float("inf"), 1.], [1e308, 1e308]):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                population_moments(values, weights)

    def test_invalid_array_or_nonfinite_result_is_rejected(self):
        for values in ([], [1., 2.], np.empty((2, 0)), [[[1.]]],
                       [[float("nan")]], [[float("inf")]], [[-1e308], [1e308]]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                population_moments(values)

    def test_complex_values_are_rejected_without_discarding_imaginary_parts(self):
        with self.assertRaisesRegex(ValueError, "real values"):
            population_moments(np.array([[1.+2.j, 3.], [4., 5.]]))
        for first, second in ((np.array([1.+2.j]), np.array([3.])),
                              (np.array([1.]), np.array([3.+4.j]))):
            with self.subTest(first=first, second=second), self.assertRaisesRegex(ValueError, "real values"):
                population_pair_moments(first, second)


class PopulationPairMomentsTests(unittest.TestCase):
    def test_known_population_pair_retains_tail_and_signed_covariance(self):
        # Means 3 and 0; population variances 12.5 and 6; covariance -8.5.
        result = population_pair_moments(np.array([0., 1., 2., 9.]), np.array([2., 2., 0., -4.]))
        self.assertEqual(result["variance_first"], 12.5)
        self.assertEqual(result["variance_second"], 6.)
        self.assertEqual(result["covariance"], -8.5)
        self.assertAlmostEqual(result["correlation"], -8.5/np.sqrt(75.))
        shifted = population_pair_moments(np.array([100., 101., 102., 109.]), np.array([-3., -3., -5., -9.]))
        self.assertEqual(shifted, result)

    def test_empty_singleton_and_constant(self):
        self.assertTrue(all(value is None for value in population_pair_moments(np.array([]), np.array([])).values()))
        singleton = population_pair_moments(np.array([7.]), np.array([-2.]))
        self.assertEqual(singleton, dict(variance_first=0., variance_second=0., covariance=0., correlation=None))
        constant = population_pair_moments(np.array([1., 1.]), np.array([1., 3.]))
        self.assertEqual(constant["covariance"], 0.)
        self.assertIsNone(constant["correlation"])

    def test_invalid_pairs_are_not_silently_filtered(self):
        for first, second in (([1.], []), ([[1.]], [[2.]]), ([float("nan")], [0.]), ([0.], [float("inf")])):
            with self.subTest(first=first, second=second), self.assertRaises(ValueError):
                population_pair_moments(np.asarray(first), np.asarray(second))


if __name__ == "__main__":
    unittest.main()
