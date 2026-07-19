from __future__ import annotations

import json
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
    bootstrap_resolution_distribution,
    bootstrap_resolution_difference,
    compare_peak_shapes,
    compute_peak_metrics,
    compute_paired_tof_delta_source_metrics,
    compute_source_mapping_metrics,
)
from reference_analysis import (
    analyze_comparison,
    audit_simion_recording,
    read_particle_table,
)
from mass_spectrum import analyze_mass_spectrum, fit_calibration
from truncation_diagnostics import _common_intersection_masks


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

    def test_paired_tof_delta_source_mapping_identifies_longitudinal_term(
        self,
    ) -> None:
        z = np.linspace(-0.5, 0.5, 101)
        x = np.sin(np.arange(z.size))
        y = np.cos(np.arange(z.size))
        energy = 5.0 + 0.1 * np.sin(2.0 * np.arange(z.size))
        delta_ns = 0.8 + 2.5 * z + 0.7 * z**2

        metrics = compute_paired_tof_delta_source_metrics(
            delta_ns, x, y, z, energy
        )

        self.assertGreater(metrics["corr_delta_tof_initial_z"], 0.99)
        self.assertGreater(metrics["z_linear_r_squared"], 0.98)
        self.assertAlmostEqual(metrics["z_quadratic_r_squared"], 1.0, places=12)
        self.assertAlmostEqual(metrics["z2_energy_xy_r_squared"], 1.0, places=12)
        self.assertAlmostEqual(metrics["z_linear_slope_ns_per_mm"], 2.5, places=12)
        self.assertAlmostEqual(
            metrics["z_quadratic_curvature_ns_per_mm2"], 0.7, places=12
        )

    def test_constant_paired_tof_delta_has_undefined_mapping_r_squared(self) -> None:
        z = np.linspace(-0.5, 0.5, 11)
        metrics = compute_paired_tof_delta_source_metrics(
            np.ones(z.size), z, z, z, 5.0 + z
        )

        self.assertIsNone(metrics["corr_delta_tof_initial_z"])
        self.assertIsNone(metrics["z_linear_r_squared"])
        self.assertIsNone(metrics["z_quadratic_r_squared"])
        self.assertIsNone(metrics["z2_energy_xy_r_squared"])


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

    def test_side_by_side_gui_export_uses_explicit_column_mapping(self) -> None:
        source = pd.DataFrame(
            {
                "program on": [1, 2, 3],
                "event": [4, 4, 4],
                "TOF": [71.9, 72.0, 72.1],
                "program off": [1, 2, 3],
                "event.1": [4, 4, 4],
                "TOF.1": [70.9, 71.0, 71.1],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "side_by_side.xlsx"
            source.to_excel(path, index=False)
            normalized, metadata = read_particle_table(
                path,
                column_overrides={
                    "particle_id": "program off",
                    "event": "event.1",
                    "tof_us": "TOF.1",
                },
            )

        self.assertEqual(normalized["particle_id"].tolist(), [1, 2, 3])
        self.assertEqual(normalized["event"].tolist(), ["4", "4", "4"])
        np.testing.assert_allclose(normalized["tof_us"], [70.9, 71.0, 71.1])
        self.assertEqual(metadata["column_overrides"]["tof_us"], "TOF.1")

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

    def test_strict_gui_recording_audit_rejects_program_off(self) -> None:
        source = pd.DataFrame(
            {
                "Ion": [1, 2, 3],
                "TofUs": [71.9, 72.0, 72.1],
                "X": [48.8, 48.8, 48.8],
                "Y": [0.0, 0.0, 0.0],
                "Z": [19.83, 19.83, 19.83],
                "PA Instance": [4, 4, 4],
                "Event": [4, 4, 4],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recording.csv"
            source.to_csv(path, index=False)
            normalized, metadata = read_particle_table(path)
            audit = audit_simion_recording(
                normalized, metadata, 3, 4, 19.83, 40.0, program_state="off"
            )

        self.assertEqual(audit["status"], "FAIL")
        self.assertFalse(audit["checks"]["program_was_enabled"])


class SourceMappingAndBootstrapTest(unittest.TestCase):
    def test_wide_mass_calibration_recovers_time_offset(self) -> None:
        mz = np.array([10.0, 100.0, 524.0, 1000.0, 2000.0])
        tof = 0.25 + 3.1 * np.sqrt(mz)
        fit = fit_calibration(tof, mz)

        self.assertAlmostEqual(fit["time_offset_us"], 0.25, places=12)
        self.assertLess(fit["residual_max_abs_mz"], 1e-9)

    def test_radius_intersection_uses_same_particles(self) -> None:
        left = [("r <= 5 mm", 5.0, np.array([True, True, False]))]
        right = [("r <= 5 mm", 5.0, np.array([True, False, True]))]
        result = _common_intersection_masks(left, right)

        np.testing.assert_array_equal(result[0][2], [True, False, False])

    def test_wide_mass_spectrum_analysis_writes_candidate_outputs(self) -> None:
        mode_path = ANALYSIS_DIR.parent / "config" / "modes" / "mass_spectrum.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        species = mode["species"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            comsol_dir = root / "comsol"
            comsol_dir.mkdir()
            simion_rows = []
            global_id = 0
            for item in species:
                mass = float(item["mass_amu"])
                mean = 0.25 + 3.1 * np.sqrt(float(item["mz"]))
                tof = mean + np.array([-1.0, 0.0, 1.0]) * 1e-4
                frame = pd.DataFrame(
                    {
                        "Ion": [1, 2, 3], "TofUs": tof,
                        "XMm": [0.0, 0.1, -0.1], "YMm": [0.0, 0.0, 0.0],
                        "Hit": [True, True, True], "X0Mm": [0.0] * 3,
                        "Y0Mm": [0.0] * 3, "Z0Mm": [0.0] * 3,
                        "EnergyEv": [5.0] * 3,
                    }
                )
                frame.to_csv(comsol_dir / f"{item['species_id']}.csv", index=False)
                for local_id, value in enumerate(tof, start=1):
                    global_id += 1
                    simion_rows.append(
                        {
                            "Ion": global_id, "MassAmu": mass,
                            "ChargeState": int(item["charge_state"]), "TofUs": value,
                            "XMm": 0.0, "YMm": 0.0, "Hit": True,
                            "X0Mm": 0.0, "Y0Mm": 0.0, "Z0Mm": 0.0,
                            "EnergyEv": 5.0,
                        }
                    )
            simion_path = root / "simion.csv"
            pd.DataFrame(simion_rows).to_csv(simion_path, index=False)
            output = root / "output"
            result = analyze_mass_spectrum(mode_path, comsol_dir, simion_path, output)

            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["resolution_claim_allowed"])
            self.assertTrue((output / "mass_spectrum_comparison.png").is_file())
            self.assertTrue((output / "mass_peak_shape_comparison.csv").is_file())
            self.assertFalse((output / "mass_peak_local_comparison.png").exists())
            self.assertEqual(len(pd.read_csv(output / "mass_spectrum_summary.csv")), 10)
            shapes = pd.read_csv(output / "mass_peak_shape_comparison.csv")
            self.assertEqual(len(shapes), len(species))
            np.testing.assert_allclose(shapes["standardized_kde_overlap"], 1.0)
            self.assertEqual(len(result["peak_shape_comparisons"]), len(species))

    def test_paired_comparison_writes_detector_landing_outputs(self) -> None:
        left = pd.DataFrame(
            {
                "Ion": [1, 2, 3, 4],
                "TofUs": [71.9, 72.0, 72.1, 72.2],
                "XMm": [48.8, 49.8, 47.8, 48.8],
                "YMm": [0.0, 0.0, 0.0, 1.0],
            }
        )
        right = left.copy()
        right["XMm"] += [0.1, 0.0, -0.1, 0.0]
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            left_path = temporary_path / "left.csv"
            right_path = temporary_path / "right.csv"
            output_path = temporary_path / "result"
            left.to_csv(left_path, index=False)
            right.to_csv(right_path, index=False)
            result = analyze_comparison(
                left_path,
                right_path,
                output_path,
                524.0,
                left_label="left",
                right_label="right",
                paired_particle_ids_required=True,
            )

            self.assertTrue((output_path / "detector_landing_comparison.png").is_file())
            self.assertTrue((output_path / "detector_landing_particles.csv").is_file())

        detector = result["comparison"]["detector_landing"]
        self.assertAlmostEqual(detector["centroid_distance_mm"], 0.0, places=12)
        self.assertAlmostEqual(
            detector["paired_mean_landing_distance_mm"], 0.05, places=12
        )

    def test_independent_comparison_does_not_report_paired_correlation(self) -> None:
        left = pd.DataFrame({"Ion": [1, 2, 3], "TofUs": [71.9, 72.0, 72.1]})
        right = pd.DataFrame({"Ion": [1, 2, 3], "TofUs": [72.1, 71.9, 72.0]})
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            left_path = temporary_path / "left.csv"
            right_path = temporary_path / "right.csv"
            left.to_csv(left_path, index=False)
            right.to_csv(right_path, index=False)
            result = analyze_comparison(
                left_path,
                right_path,
                temporary_path / "result",
                524.0,
            )

        self.assertEqual(
            result["comparison"]["sample_relationship"], "independent_runs"
        )
        self.assertIsNone(
            result["comparison"]["paired_standardized_tof_correlation"]
        )

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

    def test_matched_size_resolution_bootstrap_is_deterministic(self) -> None:
        tof = 72.0 + np.linspace(-0.001, 0.001, 41) ** 3 * 1.0e5
        settings = AnalysisSettings(grid_points=401)
        first = bootstrap_resolution_distribution(
            tof, 524.0, resamples=20, seed=11, sample_size=31,
            replace=False, settings=settings, batch_size=4
        )
        second = bootstrap_resolution_distribution(
            tof, 524.0, resamples=20, seed=11, sample_size=31,
            replace=False, settings=settings, batch_size=4
        )

        self.assertEqual(first, second)
        self.assertEqual(first["sample_size"], 31)
        self.assertFalse(first["replacement"])


if __name__ == "__main__":
    unittest.main()
