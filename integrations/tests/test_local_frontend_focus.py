"""Behavioral regressions for the native-record local focus adapter."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from integrations.workflows.local_frontend.focus import (
    export_local_focus,
    prepare_local_focus,
)


class LocalFocusTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.source = {pid: {"mass_amu": 524} for pid in (1, 2, 3)}
        self.lives = {}
        self.frontend = dict(native_frame_id="mrtof_global_cartesian", slow_axis="y", acceleration_direction=-1,
                             cell_mm_xyz=dict(z=.25), instance_origin_mm=dict(z=-.25),
                             accelerator_local_region=dict(planes=dict(grid1=1., exit=0.)))
        self.numerics = dict(trajectory_sample_interval_us=.1, maximum_step_us=.01)
        for pid in self.source:
            birth = self.event(pid, "source_release", 0., 1.2)
            if pid != 2:
                self.event(pid, "local_trajectory", .1, 1.)
            if pid == 3:
                end = self.event(pid, "local_native_stop", .16, .7)
                exit_row = None
            else:
                row = self.event(pid, "local_trajectory", .2, .5)
                if pid == 1:
                    duplicate = {**row, "event": "local_shared_time", "raw_line_number": len(self.events)+10}
                    self.events.append(duplicate)
                exit_row = self.event(pid, "local_accelerator_exit", .3, 0.)
                end = self.event(pid, "accelerator_exit_stop", .31, -.05)
            self.lives[pid] = dict(birth=birth, terminal=end, exit=exit_row)

    def event(self, pid, name, time, z):
        row = dict(particle_id=pid, event=name, instrument_time_us=time,
                   x_mm=.1*pid+time, y_mm=-50.+pid*.2, z_mm=z,
                   vx_mm_per_us=1., vy_mm_per_us=pid*.1, vz_mm_per_us=-5.,
                   raw_log_path="native.stdout.log", raw_line_number=len(self.events)+10,
                   source_instance=1)
        self.events.append(row)
        return row

    def prepare(self):
        return prepare_local_focus(self.events, self.source, self.lives, self.frontend, self.numerics,
                                   pulse_time_us=.01, source_events_path=Path("all_native_events.csv"))

    def test_bounded_complete_census_and_fixed_ids(self):
        prepared = self.prepare()
        self.assertEqual(prepared["metadata"]["planes_mm"], [1., .75, .5, .25, 0.])
        self.assertEqual(len(prepared["crossings"]), 15)
        self.assertEqual(prepared["metadata"]["own_exit_ids"], [1, 2])
        self.assertEqual(prepared["metadata"]["fixed_all_plane_exit_ids"], [1])
        self.assertEqual(prepared["metadata"]["terminal_loss_ids"], [3])
        missing = next(r for r in prepared["crossings"] if r["particle_id"] == 2 and r["plane_z_mm"] == 1.)
        self.assertEqual(missing["status"], "unknown")
        self.assertEqual(missing["terminal_reason"], "accelerator_exit_stop")
        self.assertIsNone(missing["t_us"])
        crossing = next(r for r in prepared["crossings"] if r["particle_id"] == 1 and r["plane_z_mm"] == .75)
        self.assertAlmostEqual(crossing["t_us"], .15)
        self.assertAlmostEqual(crossing["x_mm"], .25)
        self.assertEqual(crossing["lower_raw_line_number"], self.events[crossing["lower_sample_line"]-2]["raw_line_number"])
        self.assertEqual(prepared["metadata"]["duplicate_count"], 1)
        lost = next(r for r in prepared["crossings"] if r["particle_id"] == 3 and r["plane_z_mm"] == .75)
        self.assertEqual(lost["status"], "unknown")
        self.assertIsNone(lost["upper_sample_line"])
        # Drift curves are only at z=0, while recorded moments cover every plane.
        self.assertEqual({r["plane_z_mm"] for r in prepared["exit_time"]["plane_drift_predictions"]}, {0.})

    def test_exit_energy_and_covariance_keep_both_exits_without_tail_selection(self):
        prepared = self.prepare()
        portrait = prepared["exit_portrait"]
        self.assertEqual([row["particle_id"] for row in portrait["states"]], [1, 2])
        self.assertEqual(portrait["count"], 2)
        first, second = portrait["states"]
        self.assertAlmostEqual(second["Ey_eV"] / first["Ey_eV"], 4.)
        for row in portrait["states"]:
            self.assertAlmostEqual(row["Ex_eV"]+row["Ey_eV"]+row["Ez_eV"], row["total_energy_eV"])
        self.assertEqual(len(portrait["covariance_matrix"]), len(portrait["fields"]))
        self.assertEqual(portrait["moments"]["arrival_minus_mean_ns"]["population_sd"], 0.)
        self.lives[1]["exit"] = self.lives[2]["exit"] = None
        empty = self.prepare()["exit_portrait"]
        self.assertEqual(empty["states"], [])
        self.assertIsNone(empty["covariance_matrix"])

    def test_duplicate_time_requires_identical_state_and_preserves_inputs(self):
        before = copy.deepcopy(self.events)
        self.prepare()
        self.assertEqual(self.events, before)
        duplicate = next(r for r in self.events if r["event"] == "local_shared_time")
        duplicate["vx_mm_per_us"] += .001
        with self.assertRaisesRegex(ValueError, "conflicting native states"):
            self.prepare()

    def test_large_gap_is_unknown_not_loss_and_no_extrapolation(self):
        self.numerics["trajectory_sample_interval_us"] = .02
        prepared = self.prepare()
        self.assertEqual(prepared["metadata"]["fixed_all_plane_exit_ids"], [])
        self.assertEqual(prepared["metadata"]["own_exit_ids"], [1, 2])
        self.assertTrue(all(r["status"] == "unknown" for r in prepared["crossings"] if r["plane_z_mm"] > 0))
        self.assertEqual(sum(r["status"] == "alive" for r in prepared["crossings"]), 2)

    def test_export_preserves_existing_phase_outputs_and_records_exit_provenance(self):
        prepared = self.prepare()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            original = output / "summary.json"
            original.write_text('{"phase":"extraction"}', encoding="utf-8")
            summary = export_local_focus(prepared, output)
            self.assertEqual(json.loads(original.read_text()), {"phase": "extraction"})
            self.assertEqual(summary["mother_count"], 3)
            self.assertEqual(summary["fixed_all_plane_exit_count"], 1)
            with (output / "focus_spatial_crossings.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            exit_row = next(r for r in rows if r["particle_id"] == "1" and float(r["plane_z_mm"]) == 0.)
            self.assertEqual(exit_row["lower_sample_line"], "")
            self.assertTrue(exit_row["exit_event_sample_line"])
            self.assertTrue((output / "focus_time_focus_fixed_ids.png").is_file())
            self.assertTrue((output / "focus_exit_phase_energy.png").is_file())
            self.assertTrue((output / "focus_exit_phase_energy.csv").is_file())
            self.assertNotIn("crossings", json.loads((output / "focus_summary.json").read_text()))
            with self.assertRaises(FileExistsError):
                export_local_focus(prepared, output)


if __name__ == "__main__":
    unittest.main()
