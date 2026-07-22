import unittest
from pathlib import Path

import pandas as pd


from projects.oa_tof.analysis.analyze_accelerator_transverse_field_uniformity import analyze


class TransverseFieldUniformityTests(unittest.TestCase):
    def test_signed_envelope_and_all_metric_intersection(self):
        rows = []
        for y_mm in (-1.0, -0.5, 0.0, 0.5, 1.0):
            for z_mm, ez_axis, potential_axis in ((0.0, 10.0, 0.0), (1.0, 20.0, 10.0)):
                scale = abs(y_mm)
                rows.append({
                    "x_mm": 0.0,
                    "y_mm": y_mm,
                    "z_mm": z_mm,
                    "Ex_V_per_m": scale,
                    "Ey_V_per_m": 0.0,
                    "Ez_V_per_m": ez_axis + scale,
                    "potential_V": potential_axis + scale,
                })
        envelope, report = analyze(pd.DataFrame(rows), formal_half_width_mm=0.5)
        self.assertEqual(report["closed_shield_contiguous_full_width_mm"], 1.0)
        by_offset = envelope.set_index("abs_y_mm")
        self.assertTrue(bool(by_offset.loc[0.5, "all_metrics_pass"]))
        self.assertFalse(bool(by_offset.loc[1.0, "all_metrics_pass"]))

    def test_missing_axis_is_rejected(self):
        samples = pd.DataFrame({
            "x_mm": [0.0], "y_mm": [0.5], "z_mm": [0.0],
            "Ex_V_per_m": [0.0], "Ey_V_per_m": [0.0],
            "Ez_V_per_m": [1.0], "potential_V": [1.0],
        })
        with self.assertRaisesRegex(ValueError, "no y=0"):
            analyze(samples, formal_half_width_mm=0.5)


if __name__ == "__main__":
    unittest.main()
