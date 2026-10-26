"""Saved-default parity fixtures; no SIMION process or real field is used."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from integrations.tests.test_local_frontend_analysis import (
    fixture, write_log,
)
from integrations.workflows.local_frontend.replay import (
    compare_default_replay, prepare_default_replay, verify_saved_controls,
)


class DefaultReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline, self.events = fixture(self.root)
        directory = self.root/"simion/gui_full_population"
        directory.mkdir(parents=True)
        for name in ("local.iob", "local.lua", "local.fly2"):
            (directory/name).write_text("PURE_SOURCE_FIXTURE_NOT_NATIVE", encoding="utf-8")
        self.case = dict(count=3, expected_particle_ids=[3, 11, 67], merge_offset=0,
                         simion_particle_id_offset=0, working_directory=str(directory),
                         iob_path=str(directory/"local.iob"), program_path=str(directory/"local.lua"),
                         particle_input=str(directory/"local.fly2"))

    def prepare(self):
        spec = prepare_default_replay(self.root, self.case)
        write_log(Path(spec["stdout"]), self.events)
        return spec

    def compare(self, spec):
        return compare_default_replay(self.root, [self.baseline], Path(spec["stdout"]))

    def test_saved_controls_check_does_not_create_or_claim_a_flight(self):
        audit = verify_saved_controls(self.root, self.case)
        self.assertEqual(audit["scope"], "saved_controls_only")
        self.assertFalse(audit["native_fly_performed"])
        self.assertEqual(audit["expected_particle_ids"], [3, 11, 67])
        self.assertTrue(audit["controls_verified"])
        self.assertFalse((self.root / "results/default_replay").exists())

    def test_override_free_whole_source_and_all_losses_match_despite_batch_local_ion(self):
        spec = self.prepare()
        self.assertEqual(spec["argument_list"], ["--nogui", "--noprompt", "fly", "local.iob"])
        actual = copy.deepcopy(self.events)
        for row in actual:
            row["ion"] = {3: 1, 11: 2, 67: 3}[row["particle_id"]]
        write_log(Path(spec["stdout"]), actual)
        result = self.compare(spec)
        self.assertTrue(result["passed"])
        self.assertTrue(result["exact_canonical_values"])
        self.assertEqual(result["scheduled_exit_ids"], [3])
        self.assertEqual(result["replay_loss_ids"], [11, 67])
        self.assertEqual(result["mother_count"], 3)
        self.assertTrue(Path(spec["stdout"]).is_file())
        self.assertFalse(result["gui_executed"])

    def test_incomplete_population_and_second_offset_are_rejected(self):
        for change in ({"count": 2}, {"expected_particle_ids": [3, 11]}, {"merge_offset": 2}):
            with self.assertRaises(ValueError):
                prepare_default_replay(self.root, {**self.case, **change})

    def test_state_and_terminal_changes_fail_but_keep_complete_negative_comparison(self):
        spec = self.prepare()
        changed = copy.deepcopy(self.events)
        next(row for row in changed if row["event"] == "local_timeout")["vy_mm_per_us"] += .001
        next(row for row in changed if row["event"] == "local_native_stop")["event"] = "local_timeout"
        write_log(Path(spec["stdout"]), changed)
        result = self.compare(spec)
        self.assertFalse(result["passed"])
        self.assertGreater(result["differing_field_count"], 0)
        self.assertEqual(result["replay_loss_ids"], [11, 67])
        terminal = (Path(spec["evidence_directory"])/"terminal_state_comparison.csv").read_text()
        self.assertIn("67,", terminal)
        self.assertIn("11,", terminal)

    def test_missing_terminal_is_not_relabelled_as_an_ion_loss(self):
        spec = self.prepare()
        write_log(Path(spec["stdout"]), [row for row in self.events if row["event"] != "local_timeout"])
        with self.assertRaisesRegex(ValueError, "unique birth/terminal"):
            self.compare(spec)

    def test_changed_controls_and_cli_overrides_cannot_pass(self):
        spec = self.prepare()
        Path(self.case["program_path"]).write_text("changed", encoding="utf-8")
        result = self.compare(spec)
        self.assertFalse(result["passed"])
        self.assertFalse(result["controls_unchanged"])
        path = Path(spec["evidence_directory"])/"specification.json"
        spec["argument_list"].extend(["--programs", "1"])
        path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "specification differs"):
            self.compare(spec)

    def test_independent_audit_output_does_not_write_sealed_source_results(self):
        output = self.root/"independent_owner/results/default_replay"
        spec = prepare_default_replay(self.root, self.case, evidence_directory=output)
        write_log(Path(spec["stdout"]), self.events)
        result = compare_default_replay(self.root, [self.baseline], Path(spec["stdout"]), evidence_directory=output)
        self.assertTrue(result["passed"])
        self.assertFalse((self.root/"results/default_replay").exists())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            compare_default_replay(self.root, [self.baseline], Path(spec["stdout"]), evidence_directory=output)


if __name__ == "__main__":
    unittest.main()
