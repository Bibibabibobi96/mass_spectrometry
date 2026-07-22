from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import analyze_s1_end_to_end as module  # noqa: E402


def write(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


class S1EndToEndTests(unittest.TestCase):
    def test_builds_sparse_census_and_maps_solver_rows(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            entry, local, downstream, mapping, events = (root / name for name in
                ("entry.csv", "local.csv", "down.csv", "map.csv", "events.csv"))
            write(entry, ["particle_id", "instrument_time_us", "position_x_mm", "position_y_mm", "position_z_mm"],
                  [{"particle_id": i, "instrument_time_us": 1, "position_x_mm": 0,
                    "position_y_mm": 0, "position_z_mm": 0} for i in range(1, 101)])
            write(local, ["particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm", "status"],
                  [{"particle_id": i, "event": "local_joint_exit" if i <= 5 else "terminal",
                    "instrument_time_us": 2, "x_mm": 0, "y_mm": 0, "z_mm": 1,
                    "status": "transmitted" if i <= 5 else "lost"} for i in range(1, 101)])
            write(mapping, ["solver_row_index", "particle_id", "solver_birth_time_us"],
                  [{"solver_row_index": i, "particle_id": i, "solver_birth_time_us": 2}
                   for i in range(1, 6)])
            write(downstream, ["Ion", "Hit", "InstrumentTimeUs", "XMm", "YMm"],
                  [{"Ion": i, "Hit": i == 1, "InstrumentTimeUs": 10, "XMm": 0, "YMm": 0}
                   for i in range(1, 6)])
            result = module.analyze(entry, local, downstream, mapping, events)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["detector_hits"], 1)
            self.assertTrue(result["checks"]["original_particle_id_set_preserved"])
            self.assertTrue(result["checks"]["absolute_clock_monotonic"])
            self.assertEqual(result["sparse_event_rows"], 205)
            figure = root / "funnel.png"
            module.plot_funnel(result, figure)
            self.assertGreater(figure.stat().st_size, 0)

    def test_resolution_uses_shared_pulse_as_time_origin(self) -> None:
        downstream = [
            {"InstrumentTimeUs": str(50.0 + delta), "Hit": "true",
             "XMm": str(48.8 + delta), "YMm": str(-delta)}
            for delta in (0.10, 0.11, 0.12, 0.14, 0.17)
        ]
        with tempfile.TemporaryDirectory() as root:
            figure = Path(root) / "resolution.png"
            result = module.resolution_diagnostic(
                downstream, 100.0, 40.0, module.AnalysisSettings(), "ABC",
                48.8, 0.0, 40.0, "DEF", figure)
            metrics = result["canonical_peak_metrics"]
            self.assertEqual(result["status"], "AVAILABLE")
            self.assertAlmostEqual(metrics["mean_tof_us"], 10.128)
            self.assertGreater(metrics["direct_fwhm_tof_ns"], 0.0)
            self.assertAlmostEqual(
                result["detector_metrics"]["impact_centroid_x_mm"], 0.128)
            self.assertFalse(result["formal_resolution_claim_allowed"])
            self.assertGreater(figure.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
