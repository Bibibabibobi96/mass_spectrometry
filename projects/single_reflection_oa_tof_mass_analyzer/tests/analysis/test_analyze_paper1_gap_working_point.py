from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_gap_working_point import (
    _arm_metrics,
)


class GapWorkingPointReportTests(unittest.TestCase):
    def test_reports_every_loss_against_the_full_mother_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory) / "run"
            results = run_root / "results"
            results.mkdir(parents=True)
            with (results / "single_flight_particle_checkpoints.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=("particle_id", "event", "instrument_time_us")
                )
                writer.writeheader()
                for particle_id, time_us in enumerate(
                    10.0 + np.linspace(-0.003, 0.003, 64), start=1
                ):
                    writer.writerow({
                        "particle_id": particle_id,
                        "event": "detector_crossing",
                        "instrument_time_us": time_us,
                    })
            (run_root / "summary.json").write_text(json.dumps({"census": {
                "launched": 80,
                "accelerator_grid1_forward": 76,
                "local_accelerator_exit": 70,
                "detector_crossing": 64,
            }}), encoding="utf-8")

            report = _arm_metrics(run_root, mother_count=100)

            self.assertEqual(report["detector_hit_count"], 64)
            self.assertEqual(report["loss_counts_from_mother"], {
                "before_pre_pulse_release": 20,
                "accelerator_grid1_or_before": 4,
                "accelerator_interior": 6,
                "after_accelerator_before_detector": 6,
            })
            self.assertAlmostEqual(report["detector_fraction_of_mother"], 0.64)


if __name__ == "__main__":
    unittest.main()
