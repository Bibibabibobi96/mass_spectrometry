from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "analysis"


from common.analysis.peak_metrics import (
    AnalysisSettings,
    bootstrap_resolution_distribution,
    bootstrap_resolution_difference,
    compare_peak_shapes,
    compute_peak_metrics,
    compute_paired_tof_delta_source_metrics,
    compute_source_mapping_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis import (
    DEFAULT_DETECTOR_CENTER_X_MM,
    analyze_comparison,
    analyze_single,
    audit_simion_recording,
    read_particle_table,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum import (
    _normalized_simion_rows,
    analyze_mass_spectrum,
    fit_calibration,
    load_mode,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.truncation_diagnostics import _common_intersection_masks


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
        particle_ids = np.arange(1, tof_us.size + 1)
        comparison, _ = compare_peak_shapes(
            tof_us, tof_us, self.settings,
            left_particle_ids=particle_ids, right_particle_ids=particle_ids,
        )
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
    def test_large_integer_csv_ids_survive_alias_override_hit_and_event_columns(self) -> None:
        expected = [9007199254740993, 9223372036854775807, 9007199254740995]
        for column, overrides in (("Ion Number", None), ("program off", {"particle_id": "program off"})):
            with self.subTest(column=column), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "exact_ids.csv"
                path.write_text(
                    f"{column},TofUs,Hit,Event\n"
                    "9007199254740993.0,71.9,True,splat\n"
                    "19,,False,splat\n"
                    "9.223372036854775807e18,72.0,True,splat\n"
                    "9007199254740995e0,72.1,True,splat\n",
                    encoding="utf-8",
                )
                frame, metadata = read_particle_table(
                    path, column_overrides=overrides, declared_event="splat",
                )
                self.assertEqual(frame["particle_id"].tolist(), expected)
                self.assertEqual(str(frame["particle_id"].dtype), "int64")
                self.assertEqual(frame["event"].tolist(), ["splat"] * 3)
                np.testing.assert_array_equal(frame["tof_us"], [71.9, 72., 72.1])
                self.assertFalse(metadata["particle_id_generated"])
                self.assertEqual(metadata["missed_rows"], 1)
                output = Path(temporary) / "normalized.csv"
                frame.to_csv(output, index=False)
                self.assertEqual(pd.read_csv(output, dtype={"particle_id": str})["particle_id"].tolist(),
                                 [str(value) for value in expected])

    def test_excel_text_ids_keep_exact_integer_encodings(self) -> None:
        source = pd.DataFrame({
            "Ion": ["9007199254740993.0", "9223372036854775807", "9.223372036854775806e18"],
            "TofUs": [71.9, 72., 72.1],
        })
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "text_ids.xlsx"
            source.to_excel(path, index=False)
            frame, metadata = read_particle_table(path)
        self.assertEqual(frame["particle_id"].tolist(),
                         [9007199254740993, 9223372036854775807, 9223372036854775806])
        self.assertFalse(metadata["particle_id_generated"])

    def test_invalid_lexical_ids_are_rejected_even_on_missed_rows(self) -> None:
        for invalid in ("9007199254740993.1", "9223372036854775807.00000000001",
                        "1.00000000000000001", "9223372036854775808", "True", "nan", "inf", ""):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "invalid_id.csv"
                path.write_text("Ion,TofUs,Hit\n1,71.9,True\n2,72,True\n3,72.1,True\n"
                                f"{invalid},,False\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "particle IDs"):
                    read_particle_table(path)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate_id.csv"
            path.write_text("Ion,TofUs\n9007199254740993,71.9\n9007199254740993.0,72\n3,72.1\n",
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate particle_id"):
                read_particle_table(path)

    def test_csv_without_ids_keeps_generated_identity_flag_after_hit_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "without_ids.csv"
            path.write_text("TofUs,Hit\n71.9,True\n,False\n72,True\n72.1,True\n", encoding="utf-8")
            frame, metadata = read_particle_table(path)
        self.assertEqual(frame["particle_id"].tolist(), [1, 3, 4])
        self.assertTrue(metadata["particle_id_generated"])

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
    @staticmethod
    def _mass_spectrum_inputs(root: Path, particle_count: int = 100) -> tuple[Path, Path, Path]:
        mode = json.loads((ANALYSIS_DIR.parent / "config/modes/mass_spectrum.json").read_text(encoding="utf-8"))
        for item in mode["species"]:
            item["particle_count"] = particle_count
        mode_path = root / "mode.json"
        mode_path.write_text(json.dumps(mode), encoding="utf-8")
        comsol_dir = root / "comsol"
        comsol_dir.mkdir()
        simion_rows = []
        for item in mode["species"]:
            mean = 0.25 + 3.1 * np.sqrt(float(item["mz"]))
            tof = mean + np.array([-1.0, 0.0, 1.0]) * 1e-4
            frame = pd.DataFrame({
                "Ion": [1, 2, 3], "TofUs": tof,
                "XMm": DEFAULT_DETECTOR_CENTER_X_MM + np.array([0.0, 0.1, -0.1]),
                "YMm": [0.0] * 3, "Hit": [True] * 3, "X0Mm": [0.0] * 3,
                "Y0Mm": [0.0] * 3, "Z0Mm": [0.0] * 3, "EnergyEv": [5.0] * 3,
            })
            frame.to_csv(comsol_dir / f"{item['species_id']}.csv", index=False)
            for value in tof:
                simion_rows.append({
                    "Ion": len(simion_rows) + 1, "MassAmu": float(item["mass_amu"]),
                    "ChargeState": int(item["charge_state"]), "TofUs": value,
                    "XMm": DEFAULT_DETECTOR_CENTER_X_MM, "YMm": 0.0, "Hit": True,
                    "X0Mm": 0.0, "Y0Mm": 0.0, "Z0Mm": 0.0, "EnergyEv": 5.0,
                })
        simion_path = root / "simion.csv"
        pd.DataFrame(simion_rows).to_csv(simion_path, index=False)
        return mode_path, comsol_dir, simion_path

    def test_single_analysis_names_relative_mass_mapping_without_clock_qualification(self) -> None:
        tof = np.array([71.9, 72.0, 72.1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "particles.csv"
            pd.DataFrame({"Ion": [3, 7, 11], "TofUs": tof}).to_csv(source, index=False)
            result = analyze_single(source, root / "output", 524.0)
            spectrum_columns = pd.read_csv(root / "output" / "spectra.csv").columns.tolist()

        metadata = result["metrics"]["analysis_metadata"]
        self.assertEqual(metadata["method_id"], "common_gaussian_kde_nominal_mass_v1")
        self.assertEqual(metadata["time_reference"], {
            "kind": "caller_supplied_tof", "clock_qualification": "unspecified",
        })
        self.assertEqual(metadata["mass_axis"]["quantity"], "mass")
        self.assertEqual(metadata["mass_axis"]["unit"], "Da")
        self.assertEqual(metadata["mass_axis"]["mapping_method"], "nominal_mean_relative_square_v1")
        self.assertFalse(metadata["mass_axis"]["absolute_calibration"])
        self.assertEqual(metadata["mass_axis"]["nominal_mass_amu"], 524.0)
        self.assertEqual(metadata["mass_axis"]["reference_tof_us"], float(tof.mean()))
        legacy_metrics, _ = compute_peak_metrics(tof, 524.0)
        self.assertEqual(
            {key: value for key, value in result["metrics"].items() if key != "analysis_metadata"},
            legacy_metrics,
        )
        self.assertEqual(spectrum_columns, [
            "tof_grid_us", "tof_density", "tof_intensity_normalized",
            "mass_grid_Da", "mass_density", "mass_intensity_normalized",
        ])

    def test_wide_mass_calibration_recovers_time_offset(self) -> None:
        mz = np.array([10.0, 100.0, 524.0, 1000.0, 2000.0])
        tof = 0.25 + 3.1 * np.sqrt(mz)
        fit = fit_calibration(tof, mz)

        self.assertAlmostEqual(fit["time_offset_us"], 0.25, places=12)
        self.assertLess(fit["residual_max_abs_mz"], 1e-9)

    def test_wide_mass_calibration_fits_sqrt_mz_as_response(self) -> None:
        # The unequal residuals distinguish this regression from fitting time
        # against sqrt(m/z), which would produce different coefficients.
        fit = fit_calibration(np.array([1.0, 2.0, 3.0]), np.array([1.0, 4.0, 16.0]))
        self.assertAlmostEqual(fit["slope_sqrt_mz_per_us"], 1.5)
        self.assertAlmostEqual(fit["intercept_sqrt_mz"], -2.0 / 3.0)
        expected = np.array([5.0 / 6.0, 7.0 / 3.0, 23.0 / 6.0]) ** 2
        np.testing.assert_allclose(fit["fitted_mz"], expected, rtol=0, atol=1e-14)
        np.testing.assert_allclose(fit["residual_mz"], expected - [1.0, 4.0, 16.0], atol=1e-14)

    def test_mass_calibration_rejects_degenerate_design_and_invalid_numeric_inputs(self) -> None:
        for tof in ([10., 10., 10.], [1., 1., np.nextafter(1., 2.)]):
            with self.subTest(tof=tof), self.assertRaisesRegex(ValueError, "not identifiable"):
                fit_calibration(tof, [10., 100., 1000.])
        for tof, mz in (([[1., 2., 3.]], [1., 4., 9.]), ([1., 2.], [1., 4.]),
                        ([1., 2., 3.], [1., 4.]), ([0., 1., 2.], [1., 4., 9.]),
                        ([1., float("nan"), 3.], [1., 4., 9.]),
                        ([1., 2., 3.], [1., float("inf"), 9.]),
                        ([1., 2., 3.], [1., -4., 9.]),
                        ([1j, 2j, 3j], [1., 4., 9.]),
                        ([True, True, True], [1., 4., 9.])):
            with self.subTest(tof=tof, mz=mz), self.assertRaises(ValueError):
                fit_calibration(tof, mz)
        with self.assertRaisesRegex(ValueError, "finite numerical results"):
            fit_calibration([1e308, 1.1e308, 1.2e308], [1., 4., 9.])

    def test_mass_calibration_keeps_identifiable_polyfit_results_exact(self) -> None:
        # Two distinct times suffice for affine rank; repeated observations are valid.
        for tof, mz in (([1., 1., 2.], [1., 1., 4.]),
                        ([1., 2., 3.], [1., 4., 16.]),
                        ([10., 20., 30., 40.], [10., 100., 524., 2000.])):
            with self.subTest(tof=tof):
                tof, mz = np.asarray(tof), np.asarray(mz)
                slope, intercept = np.polyfit(tof, np.sqrt(mz), 1)
                expected = (slope * tof + intercept)**2
                fit = fit_calibration(tof, mz)
                self.assertEqual(fit["slope_sqrt_mz_per_us"], slope)
                self.assertEqual(fit["intercept_sqrt_mz"], intercept)
                self.assertEqual(fit["time_offset_us"], -intercept / slope)
                np.testing.assert_array_equal(fit["fitted_mz"], expected)
                np.testing.assert_array_equal(fit["residual_mz"], expected - mz)

    def test_mass_spectrum_rejects_unidentifiable_solver_calibration_before_output(self) -> None:
        for solver in ("COMSOL", "SIMION"):
            with self.subTest(solver=solver), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                mode, comsol, simion = self._mass_spectrum_inputs(root)
                for path in list(comsol.glob("*.csv")) if solver == "COMSOL" else [simion]:
                    frame = pd.read_csv(path)
                    frame["TofUs"] = [9.999, 10., 10.001] * (len(frame) // 3)
                    frame.to_csv(path, index=False)
                with self.assertRaisesRegex(ValueError, "not identifiable"):
                    analyze_mass_spectrum(mode, comsol, simion, root / "output")
                self.assertFalse((root / "output").exists())

    def test_mass_mode_rejects_fractional_charge_before_conversion(self) -> None:
        mode_path = ANALYSIS_DIR.parent / "config" / "modes" / "mass_spectrum.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mode.json"
            for charge in (1.5, -1.5, True, 0, float("nan"), float("inf")):
                with self.subTest(charge=charge):
                    mode["species"][0]["charge_state"] = charge
                    path.write_text(json.dumps(mode), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "charge_state.*integer"):
                        load_mode(path)
            mode["species"][0]["charge_state"] = -2
            mode["species"][0]["mz"] = mode["species"][0]["mass_amu"] / 2
            path.write_text(json.dumps(mode), encoding="utf-8")
            self.assertEqual(load_mode(path)["species"][0]["charge_state"], -2)
            mode["species"][0].update(mass_amu=float("inf"), mz=float("inf"))
            path.write_text(json.dumps(mode), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid species definition"):
                load_mode(path)

    def test_simion_mass_rows_reject_fractional_charge_before_conversion(self) -> None:
        frame = pd.DataFrame({
            "Ion": [1, 2, 3], "MassAmu": [10.0] * 3,
            "ChargeState": ["1.0", "1.0", "1.0"], "TofUs": [1.0, 2.0, 3.0],
            "XMm": [0.0] * 3, "YMm": [0.0] * 3, "Hit": [False, True, True],
        })
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mixed.csv"
            for charge in ("1.5", "-1.5", "0", "nan", "inf", "True", "1.00000000000000001"):
                with self.subTest(charge=charge):
                    frame.loc[0, "ChargeState"] = charge
                    frame.to_csv(path, index=False)
                    with self.assertRaisesRegex(ValueError, "charge_state.*integer"):
                        _normalized_simion_rows(path)
            frame["ChargeState"] = ["-2.0", "1e0", "+2"]
            frame.to_csv(path, index=False)
            np.testing.assert_array_equal(
                _normalized_simion_rows(path)["charge_state"], [-2, 1, 2]
            )

    def test_radius_intersection_uses_same_particles(self) -> None:
        left = [("r <= 5 mm", 5.0, np.array([True, True, False]))]
        right = [("r <= 5 mm", 5.0, np.array([True, False, True]))]
        result = _common_intersection_masks(left, right)

        np.testing.assert_array_equal(result[0][2], [True, False, False])

    def test_mass_spectrum_rejects_original_ids_before_conversion_or_output(self) -> None:
        for solver in ("COMSOL", "SIMION"):
            for invalid in ("1.9", "1.00000000000000001", "True", "nan", "inf", "0", "-1", "2", "999"):
                with self.subTest(solver=solver, invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    mode, comsol, simion = self._mass_spectrum_inputs(root, 4)
                    source = next(comsol.glob("*.csv")) if solver == "COMSOL" else simion
                    frame = pd.read_csv(source, dtype=str)
                    frame.loc[0, "Ion"] = invalid
                    frame.to_csv(source, index=False)
                    with self.assertRaisesRegex(ValueError, "particle ID|particle_id"):
                        analyze_mass_spectrum(mode, comsol, simion, root / "output")
                    self.assertFalse((root / "output").exists())

    def test_mass_spectrum_rejects_extra_rows_and_unknown_species_including_nonhits(self) -> None:
        for solver in ("COMSOL", "SIMION"):
            for hit in (True, False):
                with self.subTest(solver=solver, hit=hit), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    mode, comsol, simion = self._mass_spectrum_inputs(root, 4)
                    document = json.loads(mode.read_text(encoding="utf-8"))
                    document["species"][0]["particle_count"] = 3
                    mode.write_text(json.dumps(document), encoding="utf-8")
                    source = comsol / f"{document['species'][0]['species_id']}.csv" if solver == "COMSOL" else simion
                    frame = pd.read_csv(source)
                    extra = frame.iloc[0].to_dict()
                    extra.update(Ion=4 if solver == "COMSOL" else 16, Hit=hit)
                    pd.concat([frame, pd.DataFrame([extra])]).to_csv(source, index=False)
                    with self.assertRaisesRegex(ValueError, f"{solver}.*more particle rows than emitted"):
                        analyze_mass_spectrum(mode, comsol, simion, root / "output")
                    self.assertFalse((root / "output").exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mode, comsol, simion = self._mass_spectrum_inputs(root)
            frame = pd.read_csv(simion)
            frame.loc[0, ["MassAmu", "Hit"]] = [9999., False]
            frame.to_csv(simion, index=False)
            with self.assertRaisesRegex(ValueError, "exactly one declared"):
                analyze_mass_spectrum(mode, comsol, simion, root / "output")
            self.assertFalse((root / "output").exists())

    def test_mass_spectrum_preserves_noncontiguous_integer_encodings_and_real_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mode, comsol, simion = self._mass_spectrum_inputs(root, 4)
            for path in comsol.glob("*.csv"):
                frame = pd.read_csv(path)
                frame["Ion"] = ["4e0", "1.0", "3"]
                frame.to_csv(path, index=False)
            frame = pd.read_csv(simion)
            frame["Ion"] = [f"{value}.0" for value in frame["Ion"]]
            frame.to_csv(simion, index=False)
            analyze_mass_spectrum(mode, comsol, simion, root / "output")
            particles = pd.read_csv(root / "output/mass_spectrum_particles.csv")
            self.assertEqual(particles.loc[particles.solver == "COMSOL", "particle_id"].tolist(), [4, 1, 3] * 5)
            self.assertEqual(particles.loc[particles.solver == "SIMION", "particle_id"].tolist(), list(range(1, 16)))
            source = next(comsol.glob("*.csv"))
            pd.read_csv(source).drop(columns="Ion").to_csv(source, index=False)
            with self.assertRaisesRegex(ValueError, "Required column"):
                analyze_mass_spectrum(mode, comsol, simion, root / "missing_id_output")
            self.assertFalse((root / "missing_id_output").exists())

    def test_mass_spectrum_large_original_ids_survive_filtering_and_output(self) -> None:
        large, maximum = 9007199254740993, 9223372036854775807
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # A parser-boundary fixture; no particles are generated or simulated.
            mode, comsol, simion = self._mass_spectrum_inputs(root, maximum)
            for path in comsol.glob("*.csv"):
                frame = pd.read_csv(path)
                frame["Ion"] = ["9223372036854775807.0", "9007199254740993e0", "9007199254740995.0"]
                frame["Event"] = "detector_crossing"
                miss = frame.iloc[[0]].copy()
                miss["Ion"], miss["Hit"], miss["TofUs"] = "19", False, np.nan
                pd.concat([frame.iloc[:1], miss, frame.iloc[1:]]).to_csv(path, index=False)
            frame = pd.read_csv(simion)
            expected_simion = [maximum, *range(large + 3, large + 17)]
            frame["Ion"] = [f"{value}e0" for value in expected_simion]
            miss = frame.iloc[[0]].copy()
            miss["Ion"], miss["Hit"], miss["TofUs"] = str(large + 2), False, np.nan
            pd.concat([frame.iloc[:1], miss, frame.iloc[1:]]).to_csv(simion, index=False)
            analyze_mass_spectrum(mode, comsol, simion, root / "output")
            particles = pd.read_csv(root / "output/mass_spectrum_particles.csv", dtype={"particle_id": str})
            self.assertEqual(particles.loc[particles.solver == "COMSOL", "particle_id"].tolist(),
                             [str(value) for value in (maximum, large, large + 2)] * 5)
            self.assertEqual(particles.loc[particles.solver == "SIMION", "particle_id"].tolist(),
                             [str(value) for value in expected_simion])

    def test_mass_spectrum_cli_rejects_bad_ids_and_overfull_species_without_outputs(self) -> None:
        for invalid in ("fractional_id", "overfull_species", "unidentifiable_calibration"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                mode, comsol, simion = self._mass_spectrum_inputs(root, 4)
                frame = pd.read_csv(simion)
                if invalid == "fractional_id":
                    frame["Ion"] = frame["Ion"].astype(float) + .9
                elif invalid == "unidentifiable_calibration":
                    frame["TofUs"] = [9.999, 10., 10.001] * (len(frame) // 3)
                else:
                    document = json.loads(mode.read_text(encoding="utf-8"))
                    document["species"][0]["particle_count"] = 3
                    mode.write_text(json.dumps(document), encoding="utf-8")
                    extra = frame.iloc[0].to_dict()
                    extra["Ion"] = 16
                    frame = pd.concat([frame, pd.DataFrame([extra])])
                frame.to_csv(simion, index=False)
                result = subprocess.run([
                    sys.executable, "-B", "-m", "projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum",
                    "--mode-config", str(mode), "--comsol-dir", str(comsol),
                    "--simion-csv", str(simion), "--output", str(root / "output"),
                ], cwd=ANALYSIS_DIR.parents[2], capture_output=True, text=True, timeout=60)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("MASS_SPECTRUM_ANALYSIS=PASS", result.stdout)
                self.assertIn("ValueError", result.stderr)
                self.assertFalse((root / "output").exists())

    def test_wide_mass_spectrum_analysis_writes_candidate_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mode_path, comsol_dir, simion_path = self._mass_spectrum_inputs(root)
            species = json.loads(mode_path.read_text(encoding="utf-8"))["species"]
            output = root / "output"
            result = analyze_mass_spectrum(mode_path, comsol_dir, simion_path, output)

            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["resolution_claim_allowed"])
            metadata = result["analysis_metadata"]
            self.assertEqual(metadata["method_id"], "sqrt_mz_affine_centroid_fit_v1")
            self.assertEqual(metadata["fit_equation"], "sqrt(m/z)=a*tof_us+b")
            self.assertEqual(metadata["weight_policy"], "equal_species_centroid_weights")
            self.assertEqual(metadata["sample_unit"], "species_centroid")
            self.assertEqual(metadata["scientific_qualification"], "not_assessed")
            self.assertEqual(metadata["units"]["mass_to_charge"], "Th")
            for solver in ("COMSOL", "SIMION"):
                samples = metadata["fit_samples"][solver]
                self.assertEqual(samples["sample_count"], len(species))
                self.assertEqual(samples["effective_sample_count"], len(species))
                self.assertEqual(samples["weight_sum"], len(species))
                self.assertEqual(samples["particle_count_by_species"], {
                    str(item["species_id"]): 3 for item in species
                })
            self.assertEqual(metadata["residual_scope"], "same_sample_centroids")
            self.assertEqual(metadata["time_reference"]["clock_qualification"], "unspecified")
            self.assertEqual(metadata["time_offset_role"], "fitted_zero_intercept_not_pulse_epoch")
            self.assertEqual(metadata["mass_axis"]["quantity"], "mass_to_charge")
            self.assertEqual(metadata["mass_axis"]["unit"], "Th")
            self.assertEqual(metadata["mass_axis"]["calibration_scope"], "same_sample_centroids_per_solver")
            self.assertFalse(metadata["mass_axis"]["absolute_calibration"])
            self.assertTrue((output / "mass_spectrum_comparison.png").is_file())
            self.assertTrue(
                (output / "mass_detector_landing_comparison.png").is_file()
            )
            self.assertTrue((output / "mass_peak_shape_comparison.csv").is_file())
            self.assertFalse((output / "mass_peak_local_comparison.png").exists())
            self.assertEqual(len(pd.read_csv(output / "mass_spectrum_summary.csv")), 10)
            shapes = pd.read_csv(output / "mass_peak_shape_comparison.csv")
            self.assertEqual(len(shapes), len(species))
            np.testing.assert_allclose(shapes["standardized_kde_overlap"], 1.0)
            self.assertEqual(len(result["peak_shape_comparisons"]), len(species))
            summary = pd.read_csv(output / "mass_spectrum_summary.csv")
            self.assertTrue(
                {
                    "impact_centroid_x_mm", "impact_centroid_y_mm",
                    "impact_rms_radius_mm", "cross_solver_centroid_distance_mm",
                }.issubset(summary.columns)
            )
            np.testing.assert_allclose(
                summary["cross_solver_centroid_distance_mm"], 0.0, atol=1e-12
            )

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
        for side in ("left", "right"):
            metadata = result[side]["metrics"]["analysis_metadata"]
            self.assertEqual(metadata["mass_axis"]["mapping_method"], "nominal_mean_relative_square_v1")
            self.assertEqual(metadata["time_reference"]["clock_qualification"], "unspecified")
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

    def test_bootstrap_requires_explicit_pairing_even_with_matching_import_ids(self) -> None:
        for explicit_ids in (True, False):
            frame = pd.DataFrame({"TofUs": [71.9, 72.0, 72.1]})
            if explicit_ids:
                frame["Ion"] = [4, 10, 22]
            with self.subTest(explicit_ids=explicit_ids), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                frame.to_csv(root / "left.csv", index=False)
                right = frame.copy()
                right["TofUs"] = frame["TofUs"].to_numpy()[::-1]
                right.to_csv(root / "right.csv", index=False)
                # Independent runs may reuse real IDs or receive import-only IDs.
                # Neither is permission to resample paired particle indices.
                with self.assertRaisesRegex(ValueError, "requires explicit paired"):
                    analyze_comparison(root / "left.csv", root / "right.csv", root / "result",
                                       524.0, bootstrap_resamples=20)
                self.assertFalse((root / "result").exists())

    def test_paired_comparison_rejects_generated_or_reordered_ids(self) -> None:
        left = pd.DataFrame({"Ion": [4, 10, 22], "TofUs": [71.9, 72.0, 72.1]})
        cases = (
            (left.drop(columns="Ion"), left.drop(columns="Ion"), "generated"),
            (left, left.iloc[::-1], "identical ordered"),
        )
        for left_frame, right_frame, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                left_frame.to_csv(root / "left.csv", index=False)
                right_frame.to_csv(root / "right.csv", index=False)
                with self.assertRaisesRegex(ValueError, message):
                    analyze_comparison(root / "left.csv", root / "right.csv", root / "result",
                                       524.0, paired_particle_ids_required=True, bootstrap_resamples=20)
                self.assertFalse((root / "result").exists())

    def test_explicit_paired_comparison_publishes_bootstrap(self) -> None:
        particle_ids = 4 + 3 * np.arange(31)
        frame = pd.DataFrame({"Ion": particle_ids, "TofUs": np.linspace(71.9, 72.1, 31)})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame.to_csv(root / "left.csv", index=False)
            frame.to_csv(root / "right.csv", index=False)
            result = analyze_comparison(root / "left.csv", root / "right.csv", root / "result",
                                        524.0, paired_particle_ids_required=True,
                                        bootstrap_resamples=12, bootstrap_seed=7)
            self.assertTrue((root / "result" / "comparison_metrics.json").is_file())
        self.assertEqual(result["comparison"]["sample_relationship"], "paired_fixed_particles")
        self.assertAlmostEqual(result["comparison"]["paired_standardized_tof_correlation"], 1.0)
        bootstrap = result["comparison"]["paired_bootstrap"]
        self.assertEqual(bootstrap["resamples_valid"], 12)
        self.assertEqual(bootstrap["absolute_resolution_difference_pct_median"], 0.0)

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
        particle_ids = 4 + 3 * np.arange(left.size)
        first = bootstrap_resolution_difference(
            left, right, 524.0, resamples=20, seed=7, settings=settings, batch_size=4,
            left_particle_ids=particle_ids, right_particle_ids=particle_ids,
        )
        second = bootstrap_resolution_difference(
            left, right, 524.0, resamples=20, seed=7, settings=settings, batch_size=4,
            left_particle_ids=particle_ids, right_particle_ids=particle_ids,
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
