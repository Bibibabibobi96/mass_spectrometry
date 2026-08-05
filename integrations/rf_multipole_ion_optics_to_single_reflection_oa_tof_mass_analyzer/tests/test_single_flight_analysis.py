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


if __name__ == "__main__":
    unittest.main()
