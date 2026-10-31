"""Authoritative OA clock and event-consistency regressions."""
import csv
import json
import unittest
from projects.orthogonal_accelerator.tests.analysis import test_component_focus_analysis as fixtures

from projects.orthogonal_accelerator.analysis import component_focus_analysis as draft

class FocusClockTests(unittest.TestCase):
    setUp = fixtures.ComponentFocusAnalysisTests.setUp
    tearDown = fixtures.ComponentFocusAnalysisTests.tearDown

    def events(self):
        path = fixtures.ComponentFocusAnalysisTests.write_events(self)
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if row["kind"] == "exit":
                row["t_us"] = "0.1"
        return path, rows

    def evaluate(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        return draft.analyze(path, self.receipt, self.campaign)

    def test_real_consumer_rejects_same_plane_and_each_present_event_order(self):
        for change in ("same_time", "same_state", "exit_before_source", "exit_after_focus", "terminal_before_focus", "lost_terminal_before_source"):
            with self.subTest(change=change):
                path, rows = self.events()
                if change == "lost_terminal_before_source":
                    rows = [r for r in rows if r["kind"] not in {"exit", "focus"}]
                for row in rows:
                    if change == "same_time" and row["kind"] == "exit": row["t_us"] = "0.09"
                    if change == "same_state" and row["kind"] == "exit": row["x_mm"] = "0.001"
                    if change == "exit_before_source" and row["kind"] == "exit": row["t_us"] = "-0.1"
                    if change == "exit_after_focus" and row["kind"] == "exit": row["t_us"] = "0.2"
                    if change == "terminal_before_focus" and row["kind"] == "terminal": row["t_us"] = "0.05"
                    if change == "lost_terminal_before_source" and row["kind"] == "terminal": row["t_us"] = "-0.01"
                with self.assertRaises(draft.ComponentFocusError): self.evaluate(path, rows)

    def test_valid_same_plane_accepts_interleaved_rows_and_terminal_later(self):
        path, rows = self.events()
        result = self.evaluate(path, list(reversed(rows)))
        self.assertEqual(result["status"], "candidate_complete")
        self.assertEqual(result["focus_metrics"]["clock_semantics"], "instrument_clock_arrival_times")
        self.assertEqual(result["focus_metrics"]["propagation_duration_peak_to_peak_ns"], 0.0)

    def test_distributed_segment_start_separates_arrival_and_duration_width(self):
        campaign = json.loads(self.campaign.read_text())
        states = {i: dict(z_mm=32.0, vz_m_s=0.0, t_us=start) for i, start in enumerate((1.0, 2.0, 4.0), 1)}
        voltages = campaign["operating_point"]["electrode_voltages_v"]
        duration = draft.time_to_fixed_plane_s(voltages[1], voltages[2], 4.0, 30.0, 2.0, 0.0, 0.0, 100.0, exit_v=voltages[3])*1e6
        hits = {i:(state, dict(t_us=state["t_us"]+duration)) for i,state in states.items()}
        result = draft._ideal_two_zone_contrast(hits, campaign)
        self.assertAlmostEqual(result["native_peak_to_peak_t_ns"], 3000.0)
        self.assertAlmostEqual(result["propagation_duration_width_ns"]["native"], 0.0)
        self.assertAlmostEqual(result["paired_time_difference_ns"]["rms"], 0.0)
        for state, focus in hits.values():
            state["t_us"] += 7.0; focus["t_us"] += 7.0
        shifted = draft._ideal_two_zone_contrast(hits, campaign)
        self.assertAlmostEqual(shifted["paired_time_difference_ns"]["rms"], 0.0)
        self.assertAlmostEqual(shifted["native_peak_to_peak_t_ns"], result["native_peak_to_peak_t_ns"])

    def test_recording_roundoff_only_and_downstream_distinct_crossing(self):
        path, rows = self.events()
        for row in rows:
            if row["kind"] == "exit": row["t_us"] = str(0.1-1e-13)
        self.assertEqual(self.evaluate(path, rows)["status"], "candidate_complete")
        campaign = json.loads(self.campaign.read_text())
        campaign["operating_point"]["focus_plane_offset_from_exit_mm"] = -10.0
        self.campaign.write_text(json.dumps(campaign))
        for row in rows:
            if row["kind"] == "focus": row.update(t_us="0.2", z_mm="-10")
        self.assertEqual(self.evaluate(path, rows)["status"], "candidate_complete")

if __name__ == "__main__": unittest.main()
