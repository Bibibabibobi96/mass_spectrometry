from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "analysis"
sys.path.insert(0, str(ANALYSIS_DIR))

from peak_metrics import (
    AnalysisSettings,
    bootstrap_resolution_difference,
    compare_peak_shapes,
    compute_peak_metrics,
    compute_source_mapping_metrics,
)
from reference_analysis import audit_simion_recording, read_particle_table


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
    def test_simion_trace_is_normalized_directly(self) -> None:
        trace = "\n".join(
            [
                "noise",
                "TRACE: detector_crossing ion=2 t=72.1 x=49.8 y=1 z=19.83 r=1.41421356237 zmax=19.83",
                "TRACE: detector_crossing ion=1 t=71.9 x=48.8 y=0 z=19.83 r=0 zmax=19.83",
                "TRACE: detector_crossing ion=3 t=72.0 x=47.8 y=-1 z=19.83 r=1.41421356237 zmax=19.83",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "flight.log"
            path.write_text(trace, encoding="utf-8")
            normalized, metadata = read_particle_table(path)

        self.assertEqual(metadata["source_format"], "SIMION detector_crossing TRACE")
        self.assertEqual(normalized["particle_id"].tolist(), [2, 1, 3])
        np.testing.assert_allclose(normalized["detector_z_mm"], 19.83)
        np.testing.assert_allclose(normalized["detector_x_mm"], [1.0, 0.0, -1.0])

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

    def test_strict_gui_recording_audit_requires_provenance_columns(self) -> None:
        source = pd.DataFrame(
            {
                "Ion Number": [1, 2, 3],
                "TOF": [71.9, 72.0, 72.1],
                "X": [48.8, 49.8, 47.8],
                "Y": [0.0, 1.0, -1.0],
                "Z": [19.83, 19.83, 19.83],
                "PA Instance": [4, 4, 4],
                "Event": ["splat", "splat", "splat"],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recording.csv"
            source.to_csv(path, index=False)
            normalized, metadata = read_particle_table(path)
            audit = audit_simion_recording(normalized, metadata, 3, 4, 19.83, 40.0)

        self.assertEqual(audit["status"], "PASS")
        self.assertTrue(all(audit["checks"].values()))

    def test_strict_gui_recording_audit_rejects_blank_event(self) -> None:
        source = pd.DataFrame(
            {
                "Ion": [1, 2, 3],
                "TofUs": [71.9, 72.0, 72.1],
                "X": [48.8, 48.8, 48.8],
                "Y": [0.0, 0.0, 0.0],
                "Z": [19.83, 19.83, 19.83],
                "PA Instance": [4, 4, 4],
                "Event": ["splat", None, "splat"],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recording.csv"
            source.to_csv(path, index=False)
            normalized, metadata = read_particle_table(path)
            audit = audit_simion_recording(normalized, metadata, 3, 4, 19.83, 40.0)

        self.assertEqual(audit["status"], "FAIL")
        self.assertFalse(audit["checks"]["event_column_present_and_nonempty"])


class SourceMappingAndBootstrapTest(unittest.TestCase):
    def test_quadratic_z_mapping_is_recovered(self) -> None:
        z = np.linspace(1.0, 2.0, 101)
        x = np.sin(z * 10.0) * 0.1
        y = np.cos(z * 9.0) * 0.1
        energy = 5.0 + 0.2 * np.sin(z * 7.0)
        tof = 72.0 + 0.004 * (z - 1.45) ** 2 + 0.0002 * energy
        metrics, arrays = compute_source_mapping_metrics(tof, x, y, z, energy)

        self.assertGreater(metrics["z_only_quadratic_r_squared"], 0.99)
        self.assertAlmostEqual(metrics["quadratic_vertex_z_mm"], 1.45, delta=0.01)
        self.assertEqual(int(np.sum(arrays["z_bin_particle_count"])), z.size)

    def test_paired_bootstrap_is_deterministic(self) -> None:
        left = 72.0 + np.linspace(-0.001, 0.001, 31) ** 3 * 1.0e5
        right = 72.0 + np.linspace(-0.0011, 0.0011, 31) ** 3 * 1.0e5
        settings = AnalysisSettings(grid_points=401)
        first = bootstrap_resolution_difference(
            left, right, 524.0, resamples=20, seed=7, settings=settings, batch_size=4
        )
        second = bootstrap_resolution_difference(
            left, right, 524.0, resamples=20, seed=7, settings=settings, batch_size=4
        )

        self.assertEqual(first, second)
        self.assertEqual(first["resamples_valid"], 20)


if __name__ == "__main__":
    unittest.main()
