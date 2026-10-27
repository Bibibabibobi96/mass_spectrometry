"""Hand-calculated cohort arithmetic and lifetime facts; no solver evidence."""
from __future__ import annotations

import copy
import math
import unittest

from common.analysis.particle_census import (
    CENSUS_SCHEMA_VERSION, lifetime_position, partition_cohort, subset_efficiency,
)


class LifetimeTests(unittest.TestCase):
    def at(self, time, start=1., end=3., **tolerances):
        return lifetime_position(time, start, end, start_tolerance_us=tolerances.get("start", 0.),
                                 terminal_tolerance_us=tolerances.get("end", 0.))

    def test_half_open_boundaries_do_not_infer_observation(self):
        self.assertEqual(self.at(0.), dict(before_start=True, terminal_reached=False))
        self.assertEqual(self.at(1.), dict(before_start=False, terminal_reached=False))
        self.assertEqual(self.at(2.), dict(before_start=False, terminal_reached=False))
        self.assertEqual(self.at(3.), dict(before_start=False, terminal_reached=True))
        self.assertEqual(self.at(4.), dict(before_start=False, terminal_reached=True))
        self.assertEqual(self.at(1., end=1.), dict(before_start=False, terminal_reached=True))

    def test_missing_terminal_is_not_survival_or_observation(self):
        result = self.at(100., end=None)
        self.assertEqual(result, dict(before_start=False, terminal_reached=False))
        self.assertNotIn("alive", result)
        self.assertNotIn("observed", result)

    def test_explicit_32_ulp_matches_native_comparison_boundaries(self):
        end = 3.
        tolerance = 32*math.ulp(end)
        self.assertTrue(lifetime_position(end-tolerance, 1., end, start_tolerance_us=0., terminal_tolerance_us=tolerance)["terminal_reached"])
        self.assertFalse(lifetime_position(end-33*math.ulp(end), 1., end, start_tolerance_us=0., terminal_tolerance_us=tolerance)["terminal_reached"])

    def test_independent_start_tolerance_and_before_start_precedence(self):
        self.assertFalse(lifetime_position(.99, 1., 3., start_tolerance_us=.02, terminal_tolerance_us=0.)["before_start"])
        result = lifetime_position(.9, 1., 1., start_tolerance_us=0., terminal_tolerance_us=.2)
        self.assertEqual(result, dict(before_start=True, terminal_reached=False))

    def test_invalid_clock_and_tolerance_rejected(self):
        invalid = [
            (math.nan, 1., 3., 0., 0.), (2., math.inf, 3., 0., 0.),
            (2., 1., math.inf, 0., 0.), (2., 3., 1., 0., 0.),
            (True, 1., 3., 0., 0.), (2., 1., 3., -1., 0.),
            (2., 1., 3., 0., math.nan), (2., 1., 3., False, 0.),
        ]
        for query, start, end, start_tol, end_tol in invalid:
            with self.subTest(values=(query, start, end, start_tol, end_tol)), self.assertRaises(ValueError):
                lifetime_position(query, start, end, start_tolerance_us=start_tol, terminal_tolerance_us=end_tol)


class CohortTests(unittest.TestCase):
    def test_full_partition_retains_original_order_unknown_and_weight_mass(self):
        mother = [20, 2, 9]
        assignments = [(9, "unknown"), (2, "exit"), (20, "exit")]
        weights = {2: .125, 9: 3.5, 20: 8.}
        before = copy.deepcopy((mother, assignments, weights))
        result = partition_cohort(iter(mother), iter(assignments), categories=("exit", "unknown", "terminal"),
                                  relative_weights=weights)
        self.assertEqual(result["schema_version"], CENSUS_SCHEMA_VERSION)
        self.assertEqual(result["particle_ids_by_category"], dict(exit=[20, 2], unknown=[9], terminal=[]))
        self.assertEqual(result["counts"], dict(exit=2, unknown=1, terminal=0))
        self.assertEqual(result["weight_sums"], dict(exit=8.125, unknown=3.5, terminal=0.))
        self.assertEqual(result["mother_weight_sum"], 11.625)
        self.assertEqual((mother, assignments, weights), before)

    def test_hand_calculated_count_and_weight_efficiency(self):
        result = subset_efficiency([2, 9, 20], [20, 2], [2, 9, 20],
                                   relative_weights={2: .125, 9: 3.5, 20: 8.})
        self.assertEqual(result["numerator_particle_ids"], [2, 20])
        self.assertEqual(result["count_fraction"], 2/3)
        self.assertEqual(result["relative_weight_fraction"], 65/93)
        conditional = subset_efficiency([2, 9, 20], [2], [2, 20],
                                        relative_weights={2: .125, 9: 3.5, 20: 8.})
        self.assertEqual(conditional["count_fraction"], .5)
        self.assertEqual(conditional["relative_weight_fraction"], 1/65)

    def test_explicit_unit_weights_and_empty_denominator(self):
        unit = subset_efficiency([2, 9, 20], [2, 20], [2, 9, 20], relative_weights=None)
        self.assertEqual(unit["weighting"], "unit")
        self.assertEqual(unit["count_fraction"], unit["relative_weight_fraction"])
        empty = subset_efficiency([2], [], [], relative_weights={2: 7.})
        self.assertIsNone(empty["count_fraction"])
        self.assertIsNone(empty["relative_weight_fraction"])
        self.assertEqual(empty["undefined_reason"], "empty_denominator")
        partition = partition_cohort([], [], categories=("unknown",), relative_weights={})
        self.assertEqual(partition["mother_count"], 0)
        self.assertEqual(partition["mother_weight_sum"], 0.)
        zero = subset_efficiency([2], [], [2], relative_weights=None)
        self.assertEqual(zero["count_fraction"], 0.)
        self.assertEqual(zero["relative_weight_fraction"], 0.)

    def test_duplicate_unknown_missing_ids_and_category_fail(self):
        cases = [
            ([2, 2], [(2, "a")], ("a",)),
            ([True], [(True, "a")], ("a",)),
            ([0], [(0, "a")], ("a",)),
            ([2], [(3, "a")], ("a",)),
            ([2], [(True, "a")], ("a",)),
            ([2], [], ("a",)),
            ([2], [(2, "a"), (2, "a")], ("a",)),
            ([2], [(2, "other")], ("a",)),
            ([2], [(2, "a")], ("a", "a")),
            ([2], [(2, "a")], "a"),
        ]
        for mother, rows, categories in cases:
            with self.subTest(case=(mother, rows, categories)), self.assertRaises(ValueError):
                partition_cohort(mother, rows, categories=categories, relative_weights=None)

    def test_missing_extra_nonpositive_nonfinite_weights_fail(self):
        for weights in ({}, {2: 1., 9: 2.}, {2: 0.}, {2: -1.}, {2: math.nan},
                        {2: math.inf}, {2: True}, {2: "1"}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                partition_cohort([2], [(2, "a")], categories=("a",), relative_weights=weights)
            with self.subTest(efficiency_weights=weights), self.assertRaises(ValueError):
                subset_efficiency([2], [2], [2], relative_weights=weights)

    def test_invalid_subset_identity_and_duplicate_denominator_fail(self):
        for numerator, denominator in (([2, 2], [2]), ([2], [2, 2]), ([9], [2]),
                                       ([2], [2, 99]), ([True], [2])):
            with self.subTest(values=(numerator, denominator)), self.assertRaises(ValueError):
                subset_efficiency([2, 9], numerator, denominator, relative_weights=None)

    def test_weight_scale_preserves_fractions_without_normalizing_sums(self):
        a = subset_efficiency([2, 9], [2], [2, 9], relative_weights={2: .125, 9: 8.})
        b = subset_efficiency([2, 9], [2], [2, 9], relative_weights={2: 1., 9: 64.})
        self.assertEqual(a["relative_weight_fraction"], b["relative_weight_fraction"])
        self.assertEqual(b["denominator_weight_sum"], 65.)
        with self.assertRaises(ValueError):
            subset_efficiency([2, 9], [2], [2], relative_weights={2: 1e308, 9: 1e308})


if __name__ == "__main__":
    unittest.main()
