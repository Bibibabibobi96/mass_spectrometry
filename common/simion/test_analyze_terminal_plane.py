from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.simion.analyze_terminal_plane import analyze_terminal_plane


HEADER = "ion_number,time_us,x_mm,y_mm,z_mm,vx_mm_per_us,vy_mm_per_us,vz_mm_per_us,splat\n"


class TerminalPlaneAnalysisTests(unittest.TestCase):
    def test_transmission_and_spatial_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.csv"
            path.write_text(
                HEADER
                + "1,10,1,0,5,0,0,1,1\n"
                + "2,11,-1,0,5,0,0,1,1\n"
                + "3,12,0,0,2,0,0,0,2\n",
                encoding="utf-8",
            )
            metrics, transmitted = analyze_terminal_plane(
                path, source_count=3, pass_code=1,
                axis_center_x_mm=0.0, axis_center_y_mm=0.0,
            )
        self.assertEqual(metrics["transmitted_count"], 2)
        self.assertAlmostEqual(metrics["transmission_fraction"], 2 / 3)
        self.assertEqual(metrics["terminal_code_counts"], {"1": 2, "2": 1})
        self.assertEqual(metrics["transmitted_spatial_distribution"]["rms_radius_mm"], 1.0)
        self.assertEqual(len(transmitted), 2)

    def test_zero_transmission_is_a_valid_measured_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.csv"
            path.write_text(HEADER + "1,10,0,0,2,0,0,0,0\n", encoding="utf-8")
            metrics, _ = analyze_terminal_plane(
                path, source_count=1, pass_code=1,
                axis_center_x_mm=0.0, axis_center_y_mm=0.0,
            )
        self.assertEqual(metrics["transmission_fraction"], 0.0)
        self.assertIsNone(metrics["transmitted_spatial_distribution"])

    def test_incomplete_census_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.csv"
            path.write_text(HEADER + "1,10,0,0,2,0,0,0,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "census"):
                analyze_terminal_plane(
                    path, source_count=2, pass_code=1,
                    axis_center_x_mm=0.0, axis_center_y_mm=0.0,
                )


if __name__ == "__main__":
    unittest.main()
