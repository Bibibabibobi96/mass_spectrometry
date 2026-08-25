from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c3_j3_real_field_analysis import (
    EVENTS,
    analyze_c3_real_field_platform,
)


class Paper1C3J3RealFieldAnalysisTest(unittest.TestCase):
    def _run(self, root: Path, scale: float, detector_ns: dict[int, float]) -> Path:
        run = root / str(scale).replace("-", "m").replace(".", "p")
        (run / "inputs").mkdir(parents=True)
        (run / "results").mkdir()
        (run / "summary.json").write_text(json.dumps({
            "status": "success", "pulse_effective_time_us": 10.0,
            "census": {event: len(detector_ns) for event in EVENTS},
        }), encoding="utf-8")
        (run / "run_manifest.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
        (run / "inputs" / "three_zone_t5_candidate_resolved.json").write_text(json.dumps({
            "c3_j3_evidence": {"scale_h": scale},
        }), encoding="utf-8")
        with (run / "results" / "single_flight_particle_checkpoints.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("particle_id", "event", "instrument_time_us"))
            writer.writeheader()
            for event in EVENTS:
                for particle_id, detector_time in detector_ns.items():
                    writer.writerow({
                        "particle_id": particle_id, "event": event,
                        "instrument_time_us": 10.0 + detector_time / 1000.0,
                    })
        return run

    def test_reports_incomplete_without_independent_axis_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = {
                scale: self._run(root, scale, {1: 100.0 - 2.0 * scale, 2: 120.0 - 4.0 * scale})
                for scale in (-2.0, -1.0, 0.0, 1.0, 2.0)
            }
            result = analyze_c3_real_field_platform(runs=runs, bootstrap_replicates=20)
        self.assertEqual(result["conclusion"], "INCONCLUSIVE_REVISE")
        self.assertTrue(result["metrics"]["gates"]["paired_step_platform_le_5_percent"])
        self.assertIn("independent_axis_reference_supplied", result["failures"])

    def test_passes_when_axis_reference_agrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = {
                scale: self._run(root, scale, {1: 100.0 - 2.0 * scale, 2: 120.0 - 4.0 * scale})
                for scale in (-2.0, -1.0, 0.0, 1.0, 2.0)
            }
            result = analyze_c3_real_field_platform(
                runs=runs, axis_reference_derivative_ns_per_h=-3.0, bootstrap_replicates=20,
            )
        self.assertEqual(result["conclusion"], "PASS_CONTINUE")

    def test_rejects_event_topology_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = {
                scale: self._run(root, scale, {1: 100.0 - 2.0 * scale, 2: 120.0 - 4.0 * scale})
                for scale in (-2.0, -1.0, 0.0, 1.0, 2.0)
            }
            checkpoints = runs[1.0] / "results" / "single_flight_particle_checkpoints.csv"
            with checkpoints.open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            with checkpoints.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(row for row in rows if not (row["event"] == "reflectron_midgrid_forward" and row["particle_id"] == "2"))
            result = analyze_c3_real_field_platform(
                runs=runs, axis_reference_derivative_ns_per_h=-3.0, bootstrap_replicates=20,
            )
        self.assertEqual(result["conclusion"], "INCONCLUSIVE_REVISE")
        self.assertIn("event_topology_stable", result["failures"])


if __name__ == "__main__":
    unittest.main()
