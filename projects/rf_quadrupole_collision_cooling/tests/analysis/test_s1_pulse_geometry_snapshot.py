from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import plot_s1_pulse_geometry_snapshot as module  # noqa: E402


class S1PulseGeometrySnapshotTests(unittest.TestCase):
    def test_particle_markers_shrink_for_large_n(self) -> None:
        n100 = module.particle_marker_areas(100)
        n1000 = module.particle_marker_areas(1000)
        self.assertEqual(n100["active"], 16.0)
        self.assertLess(n1000["active"], n100["active"])
        self.assertGreater(n1000["active"], 0.0)

    def test_geometry_is_derived_from_contracts_and_plot_is_written(self) -> None:
        baseline_path = REPO_ROOT / "projects" / "oa_tof" / "config" / "baseline.json"
        joint_path = PROJECT_ROOT / "config" / "rf_to_oatof_s1_joint_field.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        joint = json.loads(joint_path.read_text(encoding="utf-8"))
        geometry = module.accelerator_geometry(baseline, joint)
        self.assertAlmostEqual(geometry["shield_outer_half"], 19.0)
        self.assertAlmostEqual(geometry["ring_outer_half"], 10.0)
        self.assertEqual(len(geometry["ring_centers_z"]), 5)
        self.assertAlmostEqual(geometry["port_width_y"], 1.0)
        self.assertAlmostEqual(geometry["port_height_z"], 0.9)
        self.assertAlmostEqual(geometry["grid1_half"], 10.0)
        self.assertAlmostEqual(geometry["grid2_half"], 15.0)

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            capture = temp_path / "capture.csv"
            events = temp_path / "events.csv"
            figure = temp_path / "snapshot.png"
            metadata = temp_path / "snapshot.json"
            pd.DataFrame([
                {"particle_id": 1, "instrument_time_us": 34.0,
                 "x_mm": -67.0, "y_mm": 0.5, "z_mm": -18.4},
                {"particle_id": 2, "instrument_time_us": 34.0,
                 "x_mm": -55.0, "y_mm": -0.2, "z_mm": -18.2},
                {"particle_id": 3, "instrument_time_us": 34.0,
                 "x_mm": -49.0, "y_mm": 0.1,
                 "z_mm": geometry["repeller_z"]},
            ]).to_csv(capture, index=False)
            pd.DataFrame([
                {"particle_id": 1, "event": "terminal", "status": "lost",
                 "terminal_reason": "electrode_or_boundary"},
                {"particle_id": 2, "event": "local_joint_exit", "status": "transmitted",
                 "terminal_reason": "none"},
                {"particle_id": 3, "event": "terminal", "status": "lost",
                 "terminal_reason": "electrode_or_boundary"},
            ]).to_csv(events, index=False)
            result = module.plot_snapshot(
                capture, events, baseline_path, joint_path, figure, metadata)
            self.assertEqual(result["particles_active_at_pulse"], 1)
            self.assertEqual(result["frozen_port_losses_before_pulse"], 1)
            self.assertEqual(result["frozen_accelerator_losses_before_pulse"], 1)
            self.assertGreater(figure.stat().st_size, 1000)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["status"], "PASS")

    def test_mixed_pulse_times_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            capture = Path(temp) / "capture.csv"
            events = Path(temp) / "events.csv"
            pd.DataFrame([
                {"particle_id": 1, "instrument_time_us": 1.0,
                 "x_mm": 0, "y_mm": 0, "z_mm": 0},
                {"particle_id": 2, "instrument_time_us": 2.0,
                 "x_mm": 0, "y_mm": 0, "z_mm": 0},
            ]).to_csv(capture, index=False)
            pd.DataFrame([
                {"particle_id": 1, "event": "terminal", "status": "lost",
                 "terminal_reason": "electrode_or_boundary"},
                {"particle_id": 2, "event": "terminal", "status": "lost",
                 "terminal_reason": "electrode_or_boundary"},
            ]).to_csv(events, index=False)
            with self.assertRaisesRegex(ValueError, "shared-time"):
                module.plot_snapshot(
                    capture, events,
                    REPO_ROOT / "projects" / "oa_tof" / "config" / "baseline.json",
                    PROJECT_ROOT / "config" / "rf_to_oatof_s1_joint_field.json",
                    Path(temp) / "out.png", Path(temp) / "out.json")


if __name__ == "__main__":
    unittest.main()
