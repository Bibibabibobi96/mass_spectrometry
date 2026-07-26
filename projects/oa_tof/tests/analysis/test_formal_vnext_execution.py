"""Pure lifecycle tests for the staged Formal vNext runner."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projects.oa_tof.tests.analysis.test_formal_vnext_preparation import FormalVnextPreparationTest
from projects.oa_tof.workflows.formal_reference.prepare_formal_vnext import prepare_formal_vnext
from projects.oa_tof.workflows.formal_reference.run_formal_vnext import (
    FormalVnextExecutionError,
    STAGE_ORDER,
    run_formal_vnext,
)


class FormalVnextExecutionTest(unittest.TestCase):
    def _prepared_plan(self, root: Path) -> Path:
        fixture = FormalVnextPreparationTest("runTest")
        candidate = fixture._candidate(root)
        prepare_formal_vnext(
            candidate, "20260726_130000__sim__cross__formal-vnext__n1000", root
        )
        return next((root / "scratch").glob("*/formal_vnext_plan.json"))

    def test_stages_are_ordered_and_success_never_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "oa_tof"
            plan = self._prepared_plan(root)
            observed: list[str] = []

            def fake(stage: dict, run_root: Path) -> dict:
                self.assertTrue(run_root.is_dir())
                observed.append(stage["stage_id"])
                return {"formal_modified": False, "promotion_authorized": False}

            run_root, summary = run_formal_vnext(plan, fake)
            self.assertEqual(observed, list(STAGE_ORDER))
            self.assertEqual(summary["formal_vnext_decision"], "revalidated_not_promoted")
            self.assertFalse(summary["promotion_authorized"])
            self.assertEqual((run_root / "run_manifest.json").is_file(), True)
            self.assertFalse((root / "formal").exists())

    def test_stage_failure_closes_run_and_skips_later_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "oa_tof"
            plan = self._prepared_plan(root)
            observed: list[str] = []

            def fake(stage: dict, _run_root: Path) -> dict:
                observed.append(stage["stage_id"])
                if stage["stage_id"] == "simion_n1000_gui_runtime":
                    raise RuntimeError("simion fixture failure")
                return {}

            with self.assertRaises(FormalVnextExecutionError) as raised:
                run_formal_vnext(plan, fake)
            self.assertEqual(observed, list(STAGE_ORDER[:3]))
            summary = (raised.exception.run_root / "summary.json").read_text(encoding="utf-8")
            self.assertIn('"status": "failed"', summary)
            self.assertIn('"failure_stage": "simion_n1000_gui_runtime"', summary)
            self.assertFalse((root / "formal").exists())

    def test_forbidden_formal_read_is_rejected_before_run_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "oa_tof"
            plan_path = self._prepared_plan(root)
            text = plan_path.read_text(encoding="utf-8").replace(
                '"formal_asset_read_allowed": false', '"formal_asset_read_allowed": true'
            )
            plan_path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not read"):
                run_formal_vnext(plan_path, lambda *_: {})
            self.assertFalse(any((root / "runs").glob("*formal-vnext*")))


if __name__ == "__main__":
    unittest.main()
