from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import analyze
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel import marker_area


class SingleFlightAnalysisTests(unittest.TestCase):
    def test_n1000_marker_does_not_obscure_geometry(self) -> None:
        self.assertLess(marker_area(1000), marker_area(100))
        self.assertLessEqual(marker_area(1000), 2.0)

    def test_preserves_original_ion_identity_at_all_checkpoints(self) -> None:
        text = "\n".join([
            "TRACE: source_release ion=2 instrument_time_us=0 x_mm=-68.8 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: single_flight_handoff ion=2 instrument_time_us=10 x_mm=-67.8 y_mm=0 z_mm=-18.4 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: pre_pulse_state ion=2 instrument_time_us=20 x_mm=-48.8 y_mm=0 z_mm=1.5 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: local_accelerator_exit ion=2 instrument_time_us=41 x_mm=-67 y_mm=0 z_mm=20 vx_mm_per_us=2 vy_mm_per_us=0 vz_mm_per_us=20",
            "TRACE: detector_crossing ion=2 t=70 x=49 y=0 z=19.83 r=0 zmax=19.83",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            path.write_text(text, encoding="utf-8")
            rows, summary = analyze(path, 3, 100.0)
        self.assertEqual({row["particle_id"] for row in rows}, {2})
        self.assertEqual(summary["census"], {"launched": 3, "source_release": 1, "multipole_handoff": 1, "pre_pulse_state": 1, "local_accelerator_exit": 1, "detector_crossing": 1})
        self.assertIsNone(summary["instrument_clock_peak"])
        self.assertFalse(summary["instrument_clock_peak_is_resolution_claim"])
        pre_pulse = next(row for row in rows if row["event"] == "pre_pulse_state")
        self.assertGreater(pre_pulse["kinetic_energy_eV"], 0.0)

    def test_target_energy_uses_pre_pulse_state_inside_accelerator(self) -> None:
        text = "\n".join([
            "TRACE: single_flight_handoff ion=1 instrument_time_us=9 x_mm=-88 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4.392 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: handoff_pulse_on ion=1 instrument_time_us=10",
        ])
        geometry = {
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
            "single_flight_layout_derivation": {"target_injection_energy_eV": 10.0},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text(text, encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            rows, summary = analyze(log, 1, 100.0, model, 10.0)
        validation = summary["injection_energy_validation"]
        self.assertEqual(validation["sampling_event"], "pre_pulse_state")
        self.assertEqual(validation["sample_count"], 1)
        self.assertFalse(validation["terminal_or_handoff_energy_is_target_validation"])
        handoff = next(row for row in rows if row["event"] == "multipole_handoff")
        sample = next(row for row in rows if row["event"] == "pre_pulse_state")
        self.assertNotEqual(handoff["kinetic_energy_eV"], sample["kinetic_energy_eV"])
        self.assertEqual(sample["pulse_eligibility"], "eligible")
        self.assertEqual(summary["pulse_capture"]["counts"]["eligible"], 1)
        self.assertFalse(summary["pulse_capture"]["selection_uses_detector_outcome"])

    def test_absolute_clock_adds_birth_time_to_native_detector_time(self) -> None:
        text = "\n".join([
            "TRACE: source_release ion=1 instrument_time_us=0.25 x_mm=-70 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: source_release ion=2 instrument_time_us=0.75 x_mm=-70 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: detector_crossing ion=1 t=70.5 x=69 y=0 z=0",
            "TRACE: detector_crossing ion=2 t=70.0 x=69 y=0 z=0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            rows, summary = analyze(
                log, 2, 100.0, clock_basis="absolute_birth_time"
            )
        detector_times = [
            row["instrument_time_us"]
            for row in rows
            if row["event"] == "detector_crossing"
        ]
        self.assertEqual(detector_times, [70.75, 70.75])
        self.assertTrue(summary["detector_native_time_offset_applied"])
        self.assertEqual(summary["detector_time_basis"], "instrument_time_us")

    def test_absolute_clock_rejects_detector_without_birth_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(
                "TRACE: detector_crossing ion=1 t=70 x=69 y=0 z=0",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "lacks source-release times"):
                analyze(log, 1, 100.0, clock_basis="absolute_birth_time")

    def test_classifies_physical_pulse_capture_without_rejecting_losses(self) -> None:
        text = "\n".join([
            "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=2 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-20.0 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=3 instrument_time_us=10 x_mm=-60 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: detector_crossing ion=1 t=70 x=49 y=0 z=19.83",
        ])
        geometry = {
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text(text, encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            rows, summary = analyze(log, 4, 100.0, model, 10.0)
        capture = summary["pulse_capture"]
        self.assertEqual(capture["counts"], {
            "eligible": 1,
            "upstream_of_repeller": 1,
            "downstream_of_grid1": 0,
            "outside_transverse_bore": 1,
            "missing_before_pulse": 1,
        })
        self.assertEqual(capture["capture_fraction_of_launched"], 0.25)
        self.assertEqual(capture["conditional_detector_efficiency"], 1.0)
        classified = {
            row["particle_id"]: row["pulse_eligibility"]
            for row in rows if row["event"] == "pre_pulse_state"
        }
        self.assertEqual(classified[2], "upstream_of_repeller")
        self.assertEqual(classified[3], "outside_transverse_bore")


if __name__ == "__main__":
    unittest.main()
