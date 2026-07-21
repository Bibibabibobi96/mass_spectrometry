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

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            capture = temp_path / "capture.csv"
            figure = temp_path / "snapshot.png"
            metadata = temp_path / "snapshot.json"
            pd.DataFrame([
                {"particle_id": 1, "instrument_time_us": 34.0,
                 "x_mm": -60.0, "y_mm": 0.1, "z_mm": -18.4},
                {"particle_id": 2, "instrument_time_us": 34.0,
                 "x_mm": -55.0, "y_mm": -0.2, "z_mm": -18.2},
            ]).to_csv(capture, index=False)
            result = module.plot_snapshot(capture, baseline_path, joint_path, figure, metadata)
            self.assertEqual(result["particles_alive_at_pulse"], 2)
            self.assertGreater(figure.stat().st_size, 1000)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["status"], "PASS")

    def test_mixed_pulse_times_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            capture = Path(temp) / "capture.csv"
            pd.DataFrame([
                {"particle_id": 1, "instrument_time_us": 1.0,
                 "x_mm": 0, "y_mm": 0, "z_mm": 0},
                {"particle_id": 2, "instrument_time_us": 2.0,
                 "x_mm": 0, "y_mm": 0, "z_mm": 0},
            ]).to_csv(capture, index=False)
            with self.assertRaisesRegex(ValueError, "shared-time"):
                module.plot_snapshot(
                    capture,
                    REPO_ROOT / "projects" / "oa_tof" / "config" / "baseline.json",
                    PROJECT_ROOT / "config" / "rf_to_oatof_s1_joint_field.json",
                    Path(temp) / "out.png", Path(temp) / "out.json")


if __name__ == "__main__":
    unittest.main()
