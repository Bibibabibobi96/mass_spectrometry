from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts import capacity_ledger
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.run_capacity_lifecycle import (
    assert_retention_complete,
    finalize_ready,
    register_writing,
    resume_partial_retirements,
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
            self.assertEqual(result, {
                "checked_count": 2, "finalized_count": 1, "blocked_count": 1,
                "migrated_count": 0, "migrated_bytes": 0,
            })
            statuses = {item["path"]: item["status"] for item in load_capacity_ledger(root)["objects"]}
            self.assertEqual(statuses["projects/p/runs/terminal"], "ready")
            self.assertEqual(statuses["projects/p/runs/checkpoint"], "writing")
            self.assertEqual(resume_terminal_runs(root), {
                "checked_count": 1, "finalized_count": 0, "blocked_count": 1,
                "migrated_count": 0, "migrated_bytes": 0,
            })

    def test_maintenance_consolidates_sealed_legacy_compact_run_without_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, config = self.fixture(root, "legacy-terminal")
            # This fixture deliberately removes only the newer lifecycle opt-in;
            # its manifest and completed compact retention receipt are real.
            legacy_config = json.loads(config.read_text(encoding="utf-8"))
            legacy_config.pop("capacity_ledger_lifecycle")
            legacy_config.pop("artifact_retention")
            config.write_text(json.dumps(legacy_config), encoding="utf-8")
            (run / "retention_actions.json").write_text(json.dumps({
                "schema_version": 1, "role": "artifact_retention_actions",
                "status": "complete", "retention_class": "compact",
            }), encoding="utf-8")
            (run / "run_manifest.json").write_text(json.dumps({
                "status": "success", "artifact_retention": {"class": "compact"},
            }), encoding="utf-8")
            payload = run / "results.json"
            payload.write_text("{}", encoding="utf-8")
            entries = []
            for path in run.rglob("*"):
                if path.is_file():
                    entries.append({
                        "path": path.relative_to(root).as_posix(), "class": "light_evidence",
                        "bytes": path.stat().st_size, "status": "writing", "pin": False,
                        "owner": "p", "retention_reason": "legacy", "review_deadline": "2026-10-22",
                        "retirement_route": "owner_managed_disposition",
                        "recovery_reason": "run_contract_missing_or_invalid",
                    })
            initialize_capacity_ledger(root, objects=entries)
            result = resume_terminal_runs(root)
            self.assertEqual(result["migrated_count"], 1)
            ledger = load_capacity_ledger(root)
            self.assertEqual(len(ledger["objects"]), 1)
            self.assertEqual(ledger["objects"][0]["path"], run.relative_to(root).as_posix())
            self.assertEqual(ledger["objects"][0]["status"], "ready")

    def test_maintenance_consolidates_terminal_legacy_light_evidence_without_retention_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "projects" / "p" / "runs" / "legacy-light"
            run.mkdir(parents=True)
            (run / "run_config.json").write_text(json.dumps({"run_id": "legacy-light"}), encoding="utf-8")
            (run / "run_manifest.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
            (run / "summary.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
            entries = []
            for path in run.rglob("*"):
                if path.is_file():
                    entries.append({
                        "path": path.relative_to(root).as_posix(), "class": "light_evidence",
                        "bytes": path.stat().st_size, "status": "writing", "pin": False,
                        "owner": "p", "retention_reason": "legacy", "review_deadline": "2026-10-22",
                        "retirement_route": "owner_managed_disposition",
                        "recovery_reason": "run_contract_missing_or_invalid",
                    })
            initialize_capacity_ledger(root, objects=entries)
            result = resume_terminal_runs(root)
            self.assertEqual(result["migrated_count"], 1)
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertEqual(entry["class"], "light_evidence")
            self.assertEqual(entry["status"], "ready")
            self.assertIn("terminal manifest", entry["retention_reason"])

    def test_partial_retirement_removes_only_authorized_heavy_file_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = self.fixture(root, "mixed-historical")
            heavy = run / "simion" / "field.pa0"
            heavy.parent.mkdir()
            heavy.write_bytes(b"rebuildable")
            preserved = run / "summary.json"
            initialize_capacity_ledger(root, objects=[])
            capacity_ledger.record_capacity_object(
                root, path=heavy, object_class="rebuildable_payload", bytes_count=heavy.stat().st_size,
                status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
            )
            capacity_ledger.record_capacity_object(
                root, path=preserved, object_class="light_evidence", bytes_count=preserved.stat().st_size,
                status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                review_deadline="2026-10-01",
            )

            result = resume_partial_retirements(root)
            self.assertEqual(result, {"completed_count": 1, "removed_bytes": len(b"rebuildable"), "blocked_count": 0})
            self.assertFalse(heavy.exists())
            self.assertTrue(preserved.exists())
            receipt = json.loads((run / "partial_retirement_actions.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["preserved"], "all unlisted run files")
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertEqual((entry["status"], entry["bytes"]), ("retired", len(b"rebuildable")))
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 0, "removed_bytes": 0, "blocked_count": 0,
            })

    def test_partial_retirement_preserves_file_when_active_consumer_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = self.fixture(root, "consumer-protected")
            heavy = run / "field.pa0"
            heavy.write_bytes(b"protected")
            consumer = root / "projects" / "p" / "runs" / "current"
            consumer.mkdir(parents=True)
            initialize_capacity_ledger(root, objects=[])
            capacity_ledger.record_capacity_object(
                root, path=heavy, object_class="rebuildable_payload", bytes_count=heavy.stat().st_size,
                status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
                consumers=[consumer],
            )
            capacity_ledger.record_capacity_object(
                root, path=consumer, object_class="rebuildable_payload", bytes_count=0,
                status="ready", owner="p",
            )
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 0, "removed_bytes": 0, "blocked_count": 1,
            })
            self.assertTrue(heavy.exists())


if __name__ == "__main__":
    unittest.main()
