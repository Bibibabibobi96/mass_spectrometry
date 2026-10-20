"""Lifecycle coverage and interpolation support; no solver or GUI."""
from __future__ import annotations

import copy
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_transport_snapshots as d
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as local


def state(t: float, pid: int = 1) -> dict:
    return dict(particle_id=pid, t_us=t, x_mm=t, y_mm=2*t, z_mm=-10*t,
                vx_mm_us=1., vy_mm_us=2., vz_mm_us=-10., potential_v=0.)


def fixture() -> dict:
    births = {1: state(0.), 2: state(1., 2), 3: state(3., 3)}
    ends = {1: dict(state(2.), reason="solver_stop"),
            2: dict(state(4., 2), reason="reached_exit"),
            3: dict(state(6., 3), reason="reached_exit")}
    tracks = {pid: [state(t/2, pid) for t in range(int(b["t_us"]*2), int(ends[pid]["t_us"]*2)+1)]
              for pid, b in births.items()}
    return dict(case=dict(case_id="C", sample_interval_us=.4, maximum_step_us=.1),
                census={pid: dict(particle_id=pid) for pid in (1, 2, 3, 99)}, births=births,
                terminals=ends, tracks=tracks, planes={"p1_exit": {pid: e for pid, e in ends.items() if e["reason"] == "reached_exit"}})


class TransportSnapshotsTests(unittest.TestCase):
    def test_full_lifetime_automatic_exit_anchors_and_every_mother(self):
        case = fixture()
        original = copy.deepcopy(case)
        old = local.prepare_common_time_snapshots([case])
        result = d.prepare_transport_snapshots([case])
        self.assertEqual(result["times_us"], [0., 1.5, 3., 4., 4.5, 5., 6.])
        self.assertEqual(result["exit_anchor_times_us"], [4., 5.])
        self.assertEqual(len(result["rows"]), 7*4)
        self.assertEqual(old, local.prepare_common_time_snapshots([case]))
        self.assertEqual(case, original)
        for count in result["counts"]:
            self.assertEqual(sum(count[s] for s in d.STATUSES), 4)
            self.assertEqual(count["upstream_not_transferred"], 1)
        first, last = result["counts"][0], result["counts"][-1]
        self.assertEqual((first["active"], first["not_born"]), (1, 2))
        self.assertEqual((last["active"], last["lost"], last["reached_exit"]), (0, 1, 2))
        self.assertFalse(old)  # Later birth occurs after the first loss.
        self.assertGreater(result["times_us"][-1], 2.)

    def test_boundary_statuses_and_no_post_terminal_positions(self):
        case = fixture()
        rows = d.prepare_transport_snapshots([case])["rows"]
        at_birth = next(r for r in rows if r["particle_id"] == 3 and r["t_us"] == 3.)
        at_exit = next(r for r in rows if r["particle_id"] == 2 and r["t_us"] == 4.)
        lost = next(r for r in rows if r["particle_id"] == 1 and r["t_us"] == 3.)
        self.assertEqual(at_birth["status"], "active")
        self.assertEqual(at_birth["z_mm"], -30.)
        self.assertEqual(at_exit["status"], "reached_exit")
        self.assertEqual(lost["status"], "lost")
        for row in rows:
            if row["status"] != "active":
                self.assertTrue(all(row[k] is None for k in local.STATE_FIELDS[1:]))

    def test_long_gap_is_unsupported_but_exact_saved_state_is_known(self):
        case = fixture()
        case["tracks"][3] = [state(3., 3), state(6., 3)]
        result = d.prepare_transport_snapshots([case])
        middle = next(r for r in result["rows"] if r["particle_id"] == 3 and r["t_us"] == 4.5)
        self.assertEqual(middle["status"], "numerical_unsupported")
        self.assertEqual(middle["support_reason"], "canonical_bracket_gap_exceeds_bound")
        self.assertIsNone(middle["z_mm"])
        exact = next(r for r in result["rows"] if r["particle_id"] == 3 and r["t_us"] == 3.)
        self.assertEqual(exact["status"], "active")
        count = next(r for r in result["counts"] if r["t_us"] == 4.5)
        self.assertEqual(count["numerical_unsupported"], 1)

    def test_halo_cannot_fill_missing_canonical_support(self):
        case = fixture()
        case["tracks"][3] = [state(3., 3), state(4., 3), state(7., 3)]
        row = next(r for r in d.prepare_transport_snapshots([case])["rows"]
                   if r["particle_id"] == 3 and r["t_us"] == 5.)
        self.assertEqual(row["status"], "numerical_unsupported")
        self.assertEqual(row["support_reason"], "no_canonical_bracket")

    def test_no_exit_and_shared_clock_across_cases(self):
        first, second = fixture(), fixture()
        second["case"]["case_id"] = "D"
        for case in (first, second):
            case["planes"]["p1_exit"] = {}
            for end in case["terminals"].values():
                end["reason"] = "solver_stop"
        result = d.prepare_transport_snapshots([first, second])
        self.assertEqual(result["times_us"], [0., 1.5, 3., 4.5, 6.])
        self.assertEqual(result["exit_anchor_times_us"], [])
        self.assertEqual({r["t_us"] for r in result["rows"] if r["case_id"] == "C"},
                         {r["t_us"] for r in result["rows"] if r["case_id"] == "D"})
        self.assertEqual(result["counts"][-1]["lost"], 3)

    def test_gap_serialization_and_missing_track_and_invalid_lifetime(self):
        case = fixture()
        case["tracks"].pop(3)
        unsupported = next(r for r in d.prepare_transport_snapshots([case])["rows"]
                           if r["particle_id"] == 3 and r["t_us"] == 3.)
        self.assertEqual(unsupported["status"], "numerical_unsupported")
        a, b = state(7500.), state(7500.500000000001)
        value, evidence = d._supported_state([a, b], 7500.25, .5)
        self.assertIsNotNone(value)
        self.assertGreater(evidence["serialization_bound_us"], 0)
        case["terminals"][3]["t_us"] = 2.
        with self.assertRaisesRegex(ValueError, "Terminal before birth"):
            d.prepare_transport_snapshots([case])

    def test_export_figures_empty_final_packet_and_csv_counts(self):
        case = fixture()
        paths = []
        def save(figure, path):
            figure.canvas.draw()
            paths.append(path.name)
            if "spatial" in path.name:
                self.assertEqual(len(figure.axes), 7)
                self.assertIn("No supported active ions", [t.get_text() for t in figure.axes[-1].texts])
            from matplotlib import pyplot as plt
            plt.close(figure)
        with tempfile.TemporaryDirectory() as folder, patch.object(d.local, "_save_figure", side_effect=save):
            result = d.export_transport_snapshots(Path(folder), [case], 0.)
            self.assertEqual(result["figure_names"], paths)
            self.assertEqual(paths[-2:], ["transport_packet_zoom_xz", "transport_packet_zoom_yz"])
            self.assertEqual(len(local._load_rows(Path(folder)/"transport_time_census.csv")), 28)
            with (Path(folder)/"transport_time_counts.csv").open(newline="", encoding="utf-8") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 7)
            with (Path(folder)/"display_zoom_centers.csv").open(newline="", encoding="utf-8") as stream:
                centers = list(csv.DictReader(stream))
            self.assertEqual(len(centers), 7)
            self.assertEqual(centers[-1]["active_count"], "0")
            self.assertEqual(centers[-1]["mean_z_mm"], "")
            self.assertIn("solely for display", result["display_zoom"])

    def test_zoom_uses_identical_active_ids_and_leaves_absolute_rows_unchanged(self):
        prepared = d.prepare_transport_snapshots([fixture()])
        original = copy.deepcopy(prepared)
        centers = d.prepare_display_zoom_centers(prepared)
        for center in centers:
            active = [r for r in prepared["rows"] if r["snapshot_index"] == center["snapshot_index"]
                      and r["status"] == "active"]
            self.assertEqual(center["active_ids"], [r["particle_id"] for r in active])
            self.assertEqual(center["active_count"], len(active))
            for axis in "xyz":
                if active:
                    self.assertAlmostEqual(center[f"mean_{axis}_mm"],
                                           sum(r[f"{axis}_mm"] for r in active)/len(active))
                else:
                    self.assertIsNone(center[f"mean_{axis}_mm"])
        self.assertEqual(prepared, original)

    def test_zoom_renderer_is_only_a_display_translation(self):
        case = fixture()
        prepared = d.prepare_transport_snapshots([case])
        centers = d.prepare_display_zoom_centers(prepared)
        from matplotlib import pyplot as plt
        for axis in ("x", "y"):
            absolute = d.build_transport_positions_figure(prepared, [case], 0., axis)
            zoom = d.build_transport_positions_figure(prepared, [case], 0., axis, centers)
            try:
                zoom.canvas.draw()
                for index, center in enumerate(centers):
                    before = np.asarray(absolute.axes[index].collections[0].get_offsets())
                    after = np.asarray(zoom.axes[index].collections[0].get_offsets())
                    self.assertEqual(before.shape, after.shape)
                    if len(before):
                        np.testing.assert_allclose(after, before-[center["mean_z_mm"], center[f"mean_{axis}_mm"]])
                        self.assertIn("mean z=", zoom.axes[index].get_title())
                        self.assertIn(f"active {len(before)}", zoom.axes[index].get_title())
                    else:
                        self.assertIn("No supported active ions", [t.get_text() for t in zoom.axes[index].texts])
                self.assertIn("display only", zoom._suptitle.get_text())
            finally:
                plt.close(absolute)
                plt.close(zoom)


if __name__ == "__main__":
    unittest.main()
