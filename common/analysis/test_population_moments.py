"""Known population pairs and degenerate/invalid input contracts."""
import unittest

import numpy as np

from common.analysis.population_moments import population_pair_moments


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
