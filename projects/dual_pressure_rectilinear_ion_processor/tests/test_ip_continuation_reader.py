"""IP continuation reader contracts; inert plans, no native files."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from msplatform.results.ip_continuation import native_data_directory


class IPContinuationDataDirectoryTests(unittest.TestCase):
    def test_no_plan_uses_this_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            self.assertEqual(native_data_directory(run), run / "simion")

    def test_explicit_complete_origin_and_invalid_plans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "inputs").mkdir()
            plan_path = run / "inputs/simion_whole_unit_replay_plan.json"
            origin = run / "parent/simion/events.csv"
            valid = {"role": "simion_whole_unit_replay_plan", "status": "ready",
                     "reusable_unit_count": 1, "replay_unit_count": 0,
                     "units": [{"terminal_outputs": [{"path": str(origin)}]}]}

            def check(plan: dict) -> Path:
                plan_path.write_text(json.dumps(plan), encoding="utf-8")
                return native_data_directory(run)

            self.assertEqual(check(valid), origin.parent)
            for key, invalid in (("role", "other"), ("status", "failed"),
                                 ("reusable_unit_count", 0), ("replay_unit_count", 1)):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "complete population"):
                    check({**valid, key: invalid})
            for paths in ([], [origin, origin], [run / "parent/other/events.csv"]):
                with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "events reference differs"):
                    check({**valid, "units": [{"terminal_outputs": [{"path": str(p)} for p in paths]}]})


if __name__ == "__main__":
    unittest.main()
