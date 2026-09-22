from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.run_capacity_lifecycle import (
    assert_retention_complete,
    finalize_ready,
    register_writing,
    resume_terminal_runs,
)


class RunCapacityLifecycleTests(unittest.TestCase):
    def fixture(self, root: Path, run_id: str) -> tuple[Path, Path]:
        run = root / "projects" / "p" / "runs" / run_id
        run.mkdir(parents=True)
        config = run / "run_config.json"
        config.write_text(json.dumps({
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            "capacity_ledger_lifecycle": {
                "schema_version": 1,
                "enabled": True,
                "artifact_root": str(root),
                "light_evidence_budget_bytes": 26_214_400,
            }
        }), encoding="utf-8")
        (run / "summary.json").write_text("{}", encoding="utf-8")
        return run, config

    def test_writing_requires_retention_before_terminal_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "run-one")
            writing = register_writing(root, config)
            self.assertEqual(writing["status"], "writing")
            with self.assertRaisesRegex(ValueError, "retention receipt"):
                assert_retention_complete(root, config)
            ledger = load_capacity_ledger(root)
            self.assertEqual(ledger["objects"][0]["status"], "writing")

            (run / "retention_actions.json").write_text(json.dumps({
                "schema_version": 1,
                "role": "artifact_retention_actions",
                "status": "complete",
                "retention_class": "compact",
            }), encoding="utf-8")
            (run / "run_manifest.json").write_text(json.dumps({
                "status": "failed",
            }), encoding="utf-8")
            ready = finalize_ready(root, config)
            self.assertEqual(ready["status"], "ready")
            ledger = load_capacity_ledger(root)
            self.assertEqual(ledger["objects"][0]["class"], "light_evidence")
            self.assertEqual(ledger["objects"][0]["status"], "ready")
            self.assertEqual(ledger["objects"][0]["bytes"], ready["bytes"])

    def test_oversize_fails_closed_and_remains_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "run-two")
            register_writing(root, config)
            evidence = run / "oversized_summary.json"
            with evidence.open("wb") as stream:
                stream.truncate(26_214_401)
            (run / "retention_actions.json").write_text(json.dumps({
                "schema_version": 1,
                "role": "artifact_retention_actions",
                "status": "complete",
                "retention_class": "compact",
            }), encoding="utf-8")
            (run / "run_manifest.json").write_text(json.dumps({
                "status": "success",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "largest_files=.*oversized_summary"):
                finalize_ready(root, config)
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertEqual(entry["status"], "writing")
            self.assertEqual(entry["class"], "rebuildable_payload")
            self.assertTrue(evidence.exists())

    def test_small_heavy_role_fails_closed_and_remains_writing(self) -> None:
        for filename, role in (
            ("payload.pa0", "solver_native_binary"),
            ("simion__batch01.trace.log", "dense_trajectory"),
        ):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_capacity_ledger(root, objects=[])
                run, config = self.fixture(root, filename.replace(".", "-"))
                register_writing(root, config)
                (run / filename).write_bytes(b"small")
                (run / "retention_actions.json").write_text(json.dumps({
                    "schema_version": 1,
                    "role": "artifact_retention_actions",
                    "status": "complete",
                    "retention_class": "compact",
                }), encoding="utf-8")
                (run / "run_manifest.json").write_text(json.dumps({
                    "status": "success",
                }), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, rf"forbidden_files=.*{filename}.*{role}",
                ):
                    finalize_ready(root, config)
                entry = load_capacity_ledger(root)["objects"][0]
                self.assertEqual(entry["status"], "writing")
                self.assertEqual(entry["class"], "rebuildable_payload")

    def test_maintenance_resumes_only_already_terminal_opted_in_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            terminal, terminal_config = self.fixture(root, "terminal")
            checkpoint, _ = self.fixture(root, "checkpoint")
            register_writing(root, terminal_config)
            register_writing(root, checkpoint / "run_config.json")
            (terminal / "retention_actions.json").write_text(json.dumps({
                "schema_version": 1, "role": "artifact_retention_actions",
                "status": "complete", "retention_class": "compact",
            }), encoding="utf-8")
            (terminal / "run_manifest.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")

            result = resume_terminal_runs(root)
            self.assertEqual(result, {"checked_count": 2, "finalized_count": 1, "blocked_count": 1})
            statuses = {item["path"]: item["status"] for item in load_capacity_ledger(root)["objects"]}
            self.assertEqual(statuses["projects/p/runs/terminal"], "ready")
            self.assertEqual(statuses["projects/p/runs/checkpoint"], "writing")
            self.assertEqual(resume_terminal_runs(root), {
                "checked_count": 1, "finalized_count": 0, "blocked_count": 1,
            })


if __name__ == "__main__":
    unittest.main()
