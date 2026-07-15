from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "analysis"
sys.path.insert(0, str(ANALYSIS_DIR))

from peak_metrics import AnalysisSettings, compare_peak_shapes, compute_peak_metrics
from reference_analysis import read_particle_table


class PeakMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = AnalysisSettings(grid_points=2001)

    def test_narrow_gaussian_mass_and_time_definitions_are_equivalent(self) -> None:
        probabilities = (np.arange(1, 20001) - 0.5) / 20000
        from scipy.stats import norm

        tof_us = 72.0 + 0.0008 * norm.ppf(probabilities)
        metrics, _ = compute_peak_metrics(tof_us, 524.0, self.settings)

        self.assertLess(
            abs(metrics["direct_mass_vs_time_resolution_difference_pct"]), 0.01
        )
        self.assertLess(
            abs(metrics["direct_vs_gaussian_mass_fwhm_difference_pct"]), 1.2
        )
        self.assertAlmostEqual(metrics["tof_skewness"], 0.0, places=10)

    def test_right_shoulder_is_reported_as_non_gaussian(self) -> None:
        rng = np.random.default_rng(20260716)
        main = rng.normal(72.0, 0.00055, 4000)
        shoulder = rng.normal(72.0015, 0.00030, 1000)
        metrics, _ = compute_peak_metrics(
            np.concatenate([main, shoulder]), 524.0, self.settings
        )

        self.assertGreater(metrics["tof_skewness"], 0.3)
        self.assertGreater(metrics["significant_kde_modes"], 1)
        self.assertGreater(
            abs(metrics["direct_vs_gaussian_mass_fwhm_difference_pct"]), 5.0
        )

    def test_identical_samples_have_unit_overlap_and_zero_ks(self) -> None:
        tof_us = np.linspace(71.99, 72.01, 101) ** 1.00001
        comparison, _ = compare_peak_shapes(tof_us, tof_us, self.settings)
        self.assertAlmostEqual(comparison["standardized_kde_overlap"], 1.0, places=6)
        self.assertEqual(comparison["standardized_ks_distance"], 0.0)
        self.assertAlmostEqual(
            comparison["paired_standardized_tof_correlation"], 1.0, places=12
        )


class ParticleImportTest(unittest.TestCase):
    def test_csv_aliases_and_detector_local_coordinates(self) -> None:
        source = pd.DataFrame(
            {
                "Ion Number": [1, 2, 3],
                "TOF": [71.9, 72.0, 72.1],
                "X": [48.8, 49.8, 47.8],
                "Y": [0.0, 1.0, -1.0],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gui.csv"
            source.to_csv(path, index=False)
            normalized, metadata = read_particle_table(path)

        np.testing.assert_allclose(normalized["detector_x_mm"], [0.0, 1.0, -1.0])
        np.testing.assert_allclose(normalized["detector_y_mm"], [0.0, 1.0, -1.0])
        self.assertEqual(metadata["detected_rows"], 3)

    def test_duplicate_particle_id_is_rejected(self) -> None:
        source = pd.DataFrame({"Ion": [1, 1, 2], "TofUs": [1.0, 1.1, 1.2]})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.csv"
            source.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Duplicate particle_id"):
                read_particle_table(path)

    def test_tof_only_human_import_generates_unpaired_ids(self) -> None:
        source = pd.DataFrame({"TOF": [71.9, 72.0, 72.1], "mean": [72.0, None, None]})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tof_only.xlsx"
            source.to_excel(path, index=False)
            normalized, metadata = read_particle_table(path)

        self.assertEqual(normalized["particle_id"].tolist(), [1, 2, 3])
        self.assertTrue(metadata["particle_id_generated"])

    def test_missing_tof_is_allowed_only_for_missed_particle(self) -> None:
        source = pd.DataFrame(
            {
                "Ion": [1, 2, 3, 4],
                "TofUs": [71.9, 72.0, 72.1, None],
                "Hit": [True, True, True, False],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "with_miss.csv"
            source.to_csv(path, index=False)
            normalized, metadata = read_particle_table(path)

        self.assertEqual(len(normalized), 3)
        self.assertEqual(metadata["missed_rows"], 1)
        self.assertEqual(metadata["hit_fraction"], 0.75)


if __name__ == "__main__":
    unittest.main()
