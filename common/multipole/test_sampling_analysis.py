from __future__ import annotations

import unittest

from common.multipole.sampling_analysis import (
    _metric,
    _percentile,
    _relative_change,
    wilson_interval,
)


class SamplingAnalysisTests(unittest.TestCase):
    def test_percentile_interpolates_endpoints_and_midpoint(self) -> None:
        values = [1.0, 2.0, 3.0]
        self.assertEqual(_percentile(values, 0.0), 1.0)
        self.assertEqual(_percentile(values, 0.5), 2.0)
        self.assertEqual(_percentile(values, 1.0), 3.0)

    def test_mean_and_rms_are_distinct(self) -> None:
        self.assertEqual(_metric([3.0, 4.0], "mean"), 3.5)
        self.assertAlmostEqual(_metric([3.0, 4.0], "rms"), (12.5) ** 0.5)

    def test_relative_change_preserves_direction(self) -> None:
        self.assertAlmostEqual(_relative_change(10.0, 8.0), -0.2)

    def test_wilson_interval_contains_observed_fraction(self) -> None:
        interval = wilson_interval(21, 100)
        self.assertLess(interval["lower"], 0.21)
        self.assertGreater(interval["upper"], 0.21)
        self.assertEqual(interval["estimate"], 0.21)

    def test_wilson_interval_rejects_invalid_counts(self) -> None:
        with self.assertRaises(ValueError):
            wilson_interval(2, 1)


if __name__ == "__main__":
    unittest.main()
