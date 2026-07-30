from __future__ import annotations

import unittest

from common.multipole.sampling_analysis import _percentile, _relative_change, _metric


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


if __name__ == "__main__":
    unittest.main()
