"""Small headless tests for ideal-source figure data and export structure."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PIL import Image

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison_plot import (
    build_residual_gain_figure,
    export_comparison_figures,
    prepare_comparison_series,
)


class IdealSourceComparisonPlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {"sampling": {"particle_count": 1000, "replicate_count": 3},
                       "source": {"mass_to_charge_th": 100},
                       "residual_scan": {"residual_sigma_m_per_s": [0, 1, 10]},
                       "width_scan": {"residual_sigma_m_per_s": [0, 1, 10], "full_widths_mm": [.5, 1., 2.2], "minimum_resolution": 25000}}
        self.records = []
        for sigma in (0, 1, 10):
            for seed in range(3):
                self.records.append({"case": {"stage": "residual_scan", "seed": seed, "residual_sigma_m_per_s": sigma, "full_width_mm": 1.},
                                     "arms": {}, "resolution_gain_percent": 30-sigma+seed,
                                     "comparison_eligible": True})
                for width in (.5, 1., 2.2):
                    self.records.append({"case": {"stage": "width_scan", "seed": seed, "residual_sigma_m_per_s": sigma, "full_width_mm": width},
                                         "arms": {arm: {"resolution": value/(width+sigma+.1)+seed, "full_cohort_reachable": True}
                                                  for arm, value in (("two_zone_matched", 40000), ("three_zone_matched", 90000))}})

    def test_ranges_are_seed_minimum_median_maximum(self) -> None:
        series = prepare_comparison_series(self.records, self.config, stage="residual_scan")
        self.assertEqual([point["x"] for point in series], [0., 1., 10.])
        self.assertEqual((series[0]["minimum"], series[0]["median"], series[0]["maximum"]), (30., 31., 32.))

    def test_missing_seed_breaks_curve_without_hiding_remaining_seed_dots(self) -> None:
        missing = [record for record in self.records if not (record["case"]["stage"] == "residual_scan" and record["case"]["seed"] == 1 and record["case"]["residual_sigma_m_per_s"] == 1)]
        series = prepare_comparison_series(missing, self.config, stage="residual_scan")
        self.assertIsNone(series[1]["median"])
        self.assertEqual(len(series[1]["samples"]), 2)
        figure, axis = build_residual_gain_figure(series)
        self.assertTrue(np.isnan(axis.lines[0].get_ydata()[1]))
        self.assertIn("m/s", axis.get_xlabel())
        figure.clear()

    def test_nonfinite_and_duplicate_seed_fail_closed(self) -> None:
        self.records[0]["resolution_gain_percent"] = float("nan")
        with self.assertRaises(ValueError):
            prepare_comparison_series(self.records, self.config, stage="residual_scan")
        self.records[0]["resolution_gain_percent"] = 30.
        with self.assertRaises(ValueError):
            prepare_comparison_series(self.records + [self.records[0]], self.config, stage="residual_scan")

    def test_export_png_svg_and_traceable_caption_without_mutating_input(self) -> None:
        before = json.dumps(self.records, sort_keys=True)
        with TemporaryDirectory() as directory:
            paths = export_comparison_figures(self.records, self.config, Path(directory))
            self.assertEqual(len(paths), 5)
            self.assertEqual({path.suffix for path in paths}, {".png", ".svg", ".json"})
            for path in paths:
                self.assertGreater(path.stat().st_size, 100)
                if path.suffix == ".png":
                    with Image.open(path) as preview:
                        self.assertGreaterEqual(preview.width, 2100)
            metadata = json.loads(paths[-1].read_text())
            self.assertIn("not confidence intervals", metadata["caption"])
            self.assertEqual(metadata["resolution_threshold"], 25000)
            self.assertEqual(len(metadata["source_records"]), len(self.records))
            with self.assertRaises(FileExistsError):
                export_comparison_figures(self.records, self.config, Path(directory))
        self.assertEqual(json.dumps(self.records, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
