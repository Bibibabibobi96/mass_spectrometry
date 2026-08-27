from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_gap_working_point import (
    RESOLUTION_TIME_BASIS,
    _arm_metrics,
    _comparison,
    _hits,
)


class GapWorkingPointReportTests(unittest.TestCase):
    def _write_run(self, run_root: Path, *, pulse: float = 45.0, width: float = 1.0) -> Path:
        results = run_root / "results"
        results.mkdir(parents=True)
        with (results / "single_flight_particle_checkpoints.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=(
                "particle_id", "event", "instrument_time_us", "pulse_effective_elapsed_us",
            ))
            writer.writeheader()
            for particle_id, time_us in reversed(list(enumerate(
                10.0 + width * np.linspace(-0.003, 0.003, 64), start=1,
            ))):
                writer.writerow({
                    "particle_id": particle_id,
                    "event": "detector_crossing",
                    "instrument_time_us": pulse + time_us,
                    "pulse_effective_elapsed_us": time_us,
                })
        (run_root / "summary.json").write_text(json.dumps({
            "clock_basis": "canonical_instrument_time_us",
            "resolution_time_basis": RESOLUTION_TIME_BASIS,
            "pulse_effective_time_us": pulse,
            "census": {
                "launched": 80,
                "accelerator_grid1_forward": 76,
                "local_accelerator_exit": 70,
                "detector_crossing": 64,
            },
        }), encoding="utf-8")
        return run_root

    def test_reports_every_loss_against_the_full_mother_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_root = self._write_run(Path(directory) / "run")
            report = _arm_metrics(run_root, mother_count=100)

            self.assertEqual(report["detector_hit_count"], 64)
            self.assertEqual(report["loss_counts_from_mother"], {
                "before_pre_pulse_release": 20,
                "accelerator_grid1_or_before": 4,
                "accelerator_interior": 6,
                "after_accelerator_before_detector": 6,
            })
            self.assertAlmostEqual(report["detector_fraction_of_mother"], 0.64)
            self.assertAlmostEqual(report["peak"]["mean_tof_us"], 10.0)
            self.assertFalse(report["instrument_clock_peak_is_resolution_claim"])

    def test_epoch_translation_changes_neither_resolution_nor_paired_gain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self._write_run(root / "before", pulse=45.0)
            after = self._write_run(root / "after", pulse=45.0, width=0.5)
            shifted_before = self._write_run(root / "shifted_before", pulse=1045.0)
            shifted_after = self._write_run(root / "shifted_after", pulse=1045.0, width=0.5)
            comparison = _comparison(before, after, 100, 42, resamples=16)
            shifted = _comparison(shifted_before, shifted_after, 100, 42, resamples=16)
            self.assertEqual(comparison["inherited"]["peak"], shifted["inherited"]["peak"])
            self.assertEqual(comparison["source_z_vz_adjusted"]["peak"], shifted["source_z_vz_adjusted"]["peak"])
            self.assertEqual(comparison["paired_bootstrap"], shifted["paired_bootstrap"])
            self.assertAlmostEqual(comparison["resolution_change_pct"], 100.0, delta=0.1)

    def test_paired_interval_preserves_gain_loss_and_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wide = self._write_run(root / "wide")
            narrow = self._write_run(root / "narrow", width=0.5)
            improved = _comparison(wide, narrow, 100, 42, resamples=16)
            worsened = _comparison(narrow, wide, 100, 42, resamples=16)
            equal = _comparison(wide, wide, 100, 42, resamples=16)
            self.assertGreater(improved["paired_bootstrap"]["resolution_change_pct"]["lower_95"], 0)
            self.assertLess(worsened["paired_bootstrap"]["resolution_change_pct"]["upper_95"], 0)
            self.assertEqual(equal["paired_bootstrap"]["resolution_change_pct"], {
                "lower_95": 0.0, "median": 0.0, "upper_95": 0.0,
            })
            self.assertEqual(_hits(wide)["particle_id"].tolist(), list(range(1, 65)))

    def test_missing_nonfinite_or_contradictory_clock_is_rejected(self) -> None:
        for field, value in (
            ("pulse_effective_time_us", None),
            ("pulse_effective_time_us", float("nan")),
            ("pulse_effective_time_us", 46.0),
            ("resolution_time_basis", None),
            ("resolution_time_basis", "canonical_instrument_time_us"),
            ("clock_basis", "solver_local_time_us"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                root = self._write_run(Path(directory) / "run")
                path = root / "summary.json"
                summary = json.loads(path.read_text(encoding="utf-8"))
                if value is None:
                    summary.pop(field)
                else:
                    summary[field] = value
                path.write_text(json.dumps(summary), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _arm_metrics(root, 100)

    def test_missing_elapsed_column_does_not_fall_back_to_instrument_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._write_run(Path(directory) / "run")
            path = root / "results" / "single_flight_particle_checkpoints.csv"
            path.write_text("particle_id,event,instrument_time_us\n1,detector_crossing,55\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing detector clock"):
                _arm_metrics(root, 100)


if __name__ == "__main__":
    unittest.main()
