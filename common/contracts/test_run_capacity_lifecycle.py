from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts import capacity_ledger
from common.contracts import capacity_protection
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.run_capacity_lifecycle import (
    assert_retention_complete,
    finalize_ready,
    register_writing_range,
    register_writing,
    resume_partial_retirements,
    resume_terminal_runs,
    seal_checkpoint,
)
from common.contracts.solver_review_retirement import (
    RECEIPT_NAME, apply_retirement, plan_retirement,
)


class RunCapacityLifecycleTests(unittest.TestCase):
    @staticmethod
    def record_heavy_identity(run: Path, path: Path, sha256: str = "A" * 64) -> None:
        """Install a pre-existing manifest identity without hashing test payload."""

        (run / "run_manifest.json").write_text(json.dumps({
            "outputs": [{
                "path": path.relative_to(run).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256,
            }],
        }), encoding="utf-8")

    def test_prewrite_range_registers_empty_direct_run_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run = root / "projects" / "p" / "runs" / "prewrite"
            run.mkdir(parents=True)
            receipt = register_writing_range(root, run)
            self.assertEqual(receipt["action"], "register_writing_range")
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertEqual(entry["path"], "projects/p/runs/prewrite")
            self.assertEqual(entry["bytes"], 0)
            self.assertEqual(entry["recovery_reason"], "run_package_initialization_incomplete")
            (run / "unexpected.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not contain files"):
                register_writing_range(root, run)

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

    def retired_failed_fixture(self, root: Path, *, retained_evidence: bool = False) -> tuple[Path, Path]:
        run, config = self.fixture(root, "20260101_000000__build__simion__failed")
        document = json.loads(config.read_text())
        document.update(schema_version=2, run_id=run.name, project="p", mode="static_pilot",
                        inputs={}, formal_gate_passed=False,
                        artifact_retention={"policy_version": 1, "class": "solver_review", "reason": "review"})
        if retained_evidence:
            document["capacity_ledger_lifecycle"]["light_evidence_budget_bytes"] = 1024
        config.write_text(json.dumps(document))
        summary = run / "summary.json"
        summary.write_text(json.dumps({"run_id": run.name, "status": "failed"}))
        payload = run / "field.pa"
        payload.write_bytes(b"unrefined copy" * (4096 if retained_evidence else 1))
        evidence = run / "samples.csv"
        if retained_evidence:
            evidence.write_bytes(b"retained observations\n" * 256)
        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}
        (run / "run_manifest.json").write_text(json.dumps({
            "schema_version": 2, "run_id": run.name, "project": "p", "mode": "static_pilot",
            "status": "failed", "formal_eligible": False, "recorded_at_utc": "2026-01-01T00:00:00Z",
            "run_config": record(config), "inputs": {},
            "outputs": [record(summary), record(payload)] + ([record(evidence)] if retained_evidence else []),
            "artifact_retention": document["artifact_retention"],
        }))
        register_writing(root, config)
        seal_checkpoint(root, config, owner="p", writing_stopped=True, retain_payload=True,
                        retention_reason="retain failed preparation evidence")
        with patch("common.contracts.solver_review_retirement._git_document_references", return_value=[]):
            plan = plan_retirement(root, root, run, owner="p",
                                   owner_abandonment_reason="abandoned duplicate; original remains")
            with patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                apply_retirement(plan)
        return run, config

    def test_failed_retirement_finalizes_without_fabricating_retention_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.retired_failed_fixture(root)
            before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
            result = finalize_ready(root, config)
            self.assertEqual((result["status"], result["terminal_status"]), ("ready", "failed"))
            self.assertEqual(load_capacity_ledger(root)["resident_bytes"], sum(map(len, before.values())))
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertEqual((entry["class"], entry["pin"]), ("light_evidence", False))
            self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()})
            self.assertFalse((run / "retention_actions.json").exists())

    def test_retired_payload_remainder_stays_pinned_above_light_budget_and_counts_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.retired_failed_fixture(root, retained_evidence=True)
            before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
            ledger_before = load_capacity_ledger(root)
            old_entry = ledger_before["objects"][0]
            with self.assertRaisesRegex(ValueError, "cannot become light_evidence"):
                finalize_ready(root, config)
            kwargs = dict(owner="p", writing_stopped=True, retain_payload=True,
                          retention_reason="retain failed preparation evidence")
            command = [sys.executable, "-m", "common.contracts.run_capacity_lifecycle",
                       "--action", "seal-stopped-payload", "--artifact-root", str(root),
                       "--run-config", str(config), "--owner", "p", "--confirm-writing-stopped",
                       "--retention-reason", kwargs["retention_reason"]]
            completed = subprocess.run(command, capture_output=True, text=True, check=True,
                                       cwd=Path(__file__).resolve().parents[2], timeout=30)
            result = json.loads(completed.stdout)
            ledger = load_capacity_ledger(root)
            expected_bytes = sum(map(len, before.values()))
            self.assertEqual(result["bytes"], expected_bytes)
            self.assertEqual(ledger["resident_bytes"], expected_bytes)
            self.assertEqual(ledger["objects"][0], {**old_entry, "bytes": expected_bytes})
            self.assertEqual(result["run_status"], "failed")
            self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()})
            self.assertEqual(seal_checkpoint(root, config, **kwargs), result)
            self.assertEqual(load_capacity_ledger(root), ledger)
            with self.assertRaisesRegex(ValueError, "cannot become light_evidence"):
                finalize_ready(root, config)

    def test_retired_payload_remainder_rejects_unexplained_or_unverified_changes(self) -> None:
        cases = ("missing_receipt", "pending_receipt", "owner", "manifest", "preserved_content",
                 "extra_file", "missing_evidence", "original_inventory", "removed_bytes", "ledger_bytes",
                 "unconfirmed", "lease")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_capacity_ledger(root, objects=[])
                run, config = self.retired_failed_fixture(root, retained_evidence=True)
                receipt_path = run / RECEIPT_NAME
                receipt = json.loads(receipt_path.read_text())
                kwargs = dict(owner="p", writing_stopped=True, retain_payload=True,
                              retention_reason="retain failed preparation evidence")
                if case == "missing_receipt":
                    receipt_path.unlink()
                elif case == "pending_receipt":
                    receipt["lifecycle_status"] = "retirement_pending"
                elif case == "owner":
                    receipt["owner"] = "other"
                elif case == "manifest":
                    path = run / "run_manifest.json"
                    path.write_text(path.read_text() + " ")
                elif case == "preserved_content":
                    path = run / "samples.csv"
                    path.write_bytes(b"x" * path.stat().st_size)
                elif case == "extra_file":
                    (run / "unrecorded.txt").write_text("not covered by retirement")
                elif case == "missing_evidence":
                    (run / "samples.csv").unlink()
                elif case == "original_inventory":
                    receipt["original_file_inventory"] = receipt["original_file_inventory"][:-1]
                elif case == "removed_bytes":
                    receipt["removed_bytes"] += 1
                elif case == "ledger_bytes":
                    ledger = load_capacity_ledger(root)
                    ledger["objects"][0]["bytes"] += 1
                    ledger["resident_bytes"] += 1
                    capacity_ledger.resolve_ledger_path(root).write_text(json.dumps(ledger))
                elif case == "unconfirmed":
                    kwargs["writing_stopped"] = False
                elif case == "lease":
                    capacity_protection.create_capacity_protection_lease(
                        root, lease_id="active", owner="p", ttl_seconds=60,
                        protected_paths=[run / "samples.csv"], committed_new_bytes=0,
                    )
                if case in {"pending_receipt", "owner", "original_inventory", "removed_bytes"}:
                    receipt_path.write_text(json.dumps(receipt))
                ledger_before = load_capacity_ledger(root)
                files_before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
                with self.assertRaises((ValueError, OSError)):
                    seal_checkpoint(root, config, **kwargs)
                self.assertEqual(load_capacity_ledger(root), ledger_before)
                self.assertEqual(files_before, {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()})

    def retired_checkpoint_runtime_fixture(self, root: Path) -> tuple[Path, Path]:
        """Use the real owner chain on a tiny sealed private runtime family."""
        run, config = self.fixture(root, "20260101_000000__sim__simion__checkpoint")
        document = json.loads(config.read_text())
        document.update(schema_version=2, run_id=run.name, project="p", mode="runtime_iteration",
                        inputs={}, formal_gate_passed=False)
        config.write_text(json.dumps(document))
        summary = run / "summary.json"
        summary.write_text(json.dumps({"run_id": run.name, "status": "checkpoint"}))
        directory = run / "runtime/native_family"
        directory.mkdir(parents=True)
        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}
        members = []
        for index in range(2):
            payload = directory / f"field.pa{index}"
            payload.write_bytes(b"tiny field" + bytes([index]))
            members.append({"name": payload.name, "bytes": payload.stat().st_size,
                            "sha256": record(payload)["sha256"]})
        checkpoint = run / "runtime_checkpoint.json"
        checkpoint.write_text(json.dumps({
            "schema_version": 1, "status": "prepared", "directory": str(directory), "members": members,
            "runtime_receipt": {"status": "prepared", "run_id": run.name,
                                "controller_path": str(directory / "field.pa0"),
                                "source_responses": [{"response_id": 1}]},
        }))
        (run / "run_manifest.json").write_text(json.dumps({
            "schema_version": 2, "run_id": run.name, "project": "p", "mode": document["mode"],
            "status": "checkpoint", "formal_eligible": False, "recorded_at_utc": "2026-01-01T00:00:00Z",
            "run_config": record(config), "inputs": {}, "outputs": [record(summary), record(checkpoint)],
            "artifact_retention": document["artifact_retention"],
        }))
        register_writing(root, config)
        seal_checkpoint(root, config, owner="p", writing_stopped=True, retain_payload=True,
                        retention_reason="private runtime retained for owner handoff")
        with patch("common.contracts.solver_review_retirement._git_document_references", return_value=[]):
            plan = plan_retirement(root, root, run, owner="p",
                                   owner_abandonment_reason="old runtime experiment explicitly closed",
                                   runtime_checkpoint_path=checkpoint, writing_stopped=True)
            with patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                apply_retirement(plan)
        return run, config

    def test_retired_checkpoint_runtime_seals_light_without_terminalizing_or_reading_pa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.retired_checkpoint_runtime_fixture(root)
            before = {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob("*") if p.is_file()}
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["class"], "rebuildable_payload")
            result = seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual((result["status"], result["run_status"]), ("ready", "checkpoint"))
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertEqual((entry["class"], entry["pin"]), ("light_evidence", False))
            self.assertEqual(load_capacity_ledger(root)["resident_bytes"], sum(map(len, before.values())))
            self.assertEqual(before, {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob("*") if p.is_file()})
            repeated = seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(repeated["bytes"], result["bytes"])
            self.assertFalse((run / "retention_actions.json").exists())
            with self.assertRaisesRegex(ValueError, "sealed run is read-only"):
                register_writing(root, config)

    def test_retired_checkpoint_runtime_closure_rejects_bad_receipt_guards_and_new_heavy(self) -> None:
        for case in ("pending", "changed_checkpoint", "bad_normal", "new_heavy", "lease", "gui", "writer"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_capacity_ledger(root, objects=[])
                run, config = self.retired_checkpoint_runtime_fixture(root)
                if case == "pending":
                    receipt = run / RECEIPT_NAME
                    document = json.loads(receipt.read_text())
                    document["lifecycle_status"] = "retirement_pending"
                    receipt.write_text(json.dumps(document))
                elif case == "changed_checkpoint":
                    (run / "runtime_checkpoint.json").write_text("{}")
                elif case == "bad_normal":
                    (run / "retention_actions.json").write_text("invalid json")
                elif case == "new_heavy":
                    (run / "new.pa").write_bytes(b"new field")
                elif case == "lease":
                    capacity_protection.create_capacity_protection_lease(
                        root, lease_id="checkpoint-reader", owner="test", ttl_seconds=3600, protected_paths=[run])
                elif case == "gui":
                    review = root / "projects/p/reviews/current_gui"
                    review.mkdir(parents=True)
                    (review / "inspection_receipt.json").write_text(json.dumps({"status": "ready", "source_run": run.name}))
                ledger_before = load_capacity_ledger(root)
                with self.assertRaises(ValueError):
                    seal_checkpoint(root, config, owner="p", writing_stopped=case != "writer")
                self.assertEqual(load_capacity_ledger(root), ledger_before)

    def test_retirement_fallback_rejects_corrupt_or_pending_retirement_and_bad_normal_receipt(self) -> None:
        for case in ("corrupt", "pending", "bad_normal"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_capacity_ledger(root, objects=[])
                run, config = self.retired_failed_fixture(root)
                if case == "bad_normal":
                    (run / "retention_actions.json").write_text("invalid json")
                else:
                    receipt = run / RECEIPT_NAME
                    if case == "corrupt":
                        receipt.write_text("invalid json")
                    else:
                        document = json.loads(receipt.read_text())
                        document["lifecycle_status"] = "pending"
                        receipt.write_text(json.dumps(document))
                ledger_before = load_capacity_ledger(root)
                with self.assertRaises(ValueError):
                    finalize_ready(root, config)
                self.assertEqual(load_capacity_ledger(root), ledger_before)

    def test_seal_checkpoint_preserves_bytes_pin_and_readonly_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "paused")
            register_writing(root, config)
            (run / "run_manifest.json").write_text(json.dumps({"status": "checkpoint"}), encoding="utf-8")
            (run / "handoff.json").write_text('{"source":"retained PA owner"}', encoding="utf-8")
            entry = load_capacity_ledger(root)["objects"][0]
            capacity_ledger.record_capacity_object(
                root, path=run, object_class=entry["class"], bytes_count=entry["bytes"],
                status="writing", owner="p", recovery_reason="run_manifest_not_terminal",
                review_deadline="2000-01-01", pin=True, pin_reason="required handoff",
            )
            before = {p.name: p.read_bytes() for p in run.iterdir()}
            result = seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(result["run_status"], "checkpoint")
            self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})
            entry = load_capacity_ledger(root)["objects"][0]
            self.assertTrue(entry["pin"])
            self.assertEqual(entry["pin_reason"], "required handoff")
            self.assertEqual(entry["status"], "ready")
            self.assertEqual(entry["bytes"], sum(map(len, before.values())))
            self.assertEqual(seal_checkpoint(root, config, owner="p", writing_stopped=True), result)
            with self.assertRaisesRegex(ValueError, "new run"):
                register_writing(root, config)

    def test_seal_checkpoint_rejects_unconfirmed_wrong_owner_and_noncheckpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "paused")
            register_writing(root, config)
            for owner, stopped in (("p", False), ("other", True)):
                with self.assertRaisesRegex(ValueError, "owner.*stopped"):
                    seal_checkpoint(root, config, owner=owner, writing_stopped=stopped)
            (run / "run_manifest.json").write_text('{"status":"success"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checkpoint manifest"):
                seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["status"], "writing")

    def test_seal_checkpoint_defers_active_lease_and_keeps_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "paused")
            register_writing(root, config)
            (run / "run_manifest.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
            capacity_protection.create_capacity_protection_lease(
                root, lease_id="reader-or-writer", owner="p", ttl_seconds=60,
                protected_paths=[run / "handoff.json"], committed_new_bytes=0,
            )
            with self.assertRaisesRegex(ValueError, "active protection"):
                seal_checkpoint(root, config, owner="p", writing_stopped=True)
            capacity_protection.delete_capacity_protection_lease(root, lease_id="reader-or-writer")
            capacity_ledger.record_capacity_object(
                root, path=run, object_class="rebuildable_payload", bytes_count=0,
                status="writing", owner="p", recovery_reason="run_manifest_not_terminal",
                review_deadline="2000-01-01", consumers=[root / "projects/p/runs/consumer"],
            )
            before = load_capacity_ledger(root)
            with self.assertRaisesRegex(ValueError, "consumers require owner handoff"):
                seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(load_capacity_ledger(root), before)

    def test_seal_checkpoint_refuses_heavy_payload_without_removing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "paused")
            register_writing(root, config)
            (run / "run_manifest.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
            payload = run / "field.pa0"
            payload.write_bytes(b"retained")
            with self.assertRaisesRegex(ValueError, "not light evidence"):
                seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(payload.read_bytes(), b"retained")
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["status"], "writing")

    def stopped_payload_fixture(self, root: Path, status: str) -> tuple[Path, Path]:
        run, config = self.fixture(root, "retained-" + status)
        document = json.loads(config.read_text(encoding="utf-8"))
        document.update(run_id=run.name, project="p")
        config.write_text(json.dumps(document), encoding="utf-8")
        (run / "run_manifest.json").write_text(json.dumps({
            "run_id": run.name, "project": "p", "status": status,
        }), encoding="utf-8")
        register_writing(root, config)
        (run / "field.pa0").write_bytes(b"sealed heavy fixture")
        return run, config

    def test_stopped_payload_preserves_all_scientific_states_bytes_and_counts_once(self) -> None:
        for status in ("success", "interrupted", "checkpoint"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_capacity_ledger(root, objects=[])
                run, config = self.stopped_payload_fixture(root, status)
                before = {p.name: p.read_bytes() for p in run.iterdir()}
                kwargs = dict(owner="p", writing_stopped=True, retain_payload=True,
                              retention_reason="GUI and next-stage field reuse")
                result = seal_checkpoint(root, config, **kwargs)
                ledger = load_capacity_ledger(root)
                entry = ledger["objects"][0]
                self.assertEqual(result["run_status"], status)
                self.assertEqual((entry["class"], entry["status"], entry["pin"]),
                                 ("rebuildable_payload", "ready", True))
                self.assertEqual(entry["pin_reason"], kwargs["retention_reason"])
                self.assertEqual(ledger["resident_bytes"], sum(map(len, before.values())))
                self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})
                self.assertEqual(seal_checkpoint(root, config, **kwargs), result)
                self.assertEqual(load_capacity_ledger(root), ledger)
                with self.assertRaisesRegex(ValueError, "new run"):
                    register_writing(root, config)

    def test_stopped_payload_rejects_unconfirmed_owner_identity_reason_consumer_and_lease(self) -> None:
        for case in ("unconfirmed", "owner", "identity", "reason", "consumer", "lease"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_capacity_ledger(root, objects=[])
                run, config = self.stopped_payload_fixture(root, "success")
                kwargs = dict(owner="p", writing_stopped=True, retain_payload=True,
                              retention_reason="retained field")
                if case == "unconfirmed":
                    kwargs["writing_stopped"] = False
                elif case == "owner":
                    kwargs["owner"] = "other"
                elif case == "identity":
                    manifest = json.loads((run / "run_manifest.json").read_text())
                    manifest["run_id"] = "different"
                    (run / "run_manifest.json").write_text(json.dumps(manifest))
                elif case == "reason":
                    kwargs["retention_reason"] = " "
                elif case == "consumer":
                    capacity_ledger.record_capacity_object(
                        root, path=run, object_class="rebuildable_payload", bytes_count=0,
                        status="writing", owner="p", recovery_reason="run_manifest_not_terminal",
                        review_deadline="2000-01-01", consumers=[root / "projects/p/runs/consumer"],
                    )
                else:
                    capacity_protection.create_capacity_protection_lease(
                        root, lease_id="active", owner="p", ttl_seconds=60,
                        protected_paths=[run / "field.pa0"], committed_new_bytes=0,
                    )
                ledger = load_capacity_ledger(root)
                before = {p.name: p.read_bytes() for p in run.iterdir()}
                with self.assertRaises(ValueError):
                    seal_checkpoint(root, config, **kwargs)
                self.assertEqual(load_capacity_ledger(root), ledger)
                self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})

    def test_stopped_payload_cli_and_atomic_replay_keep_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.stopped_payload_fixture(root, "interrupted")
            ledger = load_capacity_ledger(root)
            with patch("common.contracts.run_capacity_lifecycle.write_json_atomic", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    seal_checkpoint(root, config, owner="p", writing_stopped=True,
                                    retain_payload=True, retention_reason="GUI")
            self.assertEqual(load_capacity_ledger(root), ledger)
            command = [sys.executable, "-m", "common.contracts.run_capacity_lifecycle",
                       "--action", "seal-stopped-payload", "--artifact-root", str(root),
                       "--run-config", str(config), "--owner", "p", "--confirm-writing-stopped",
                       "--retention-reason", "GUI"]
            result = subprocess.run(command, capture_output=True, text=True, check=True,
                                    cwd=Path(__file__).resolve().parents[2], timeout=30)
            self.assertEqual(json.loads(result.stdout)["run_status"], "interrupted")
            self.assertEqual((run / "field.pa0").read_bytes(), b"sealed heavy fixture")
            (run / "field.pa0").write_bytes(b"changed bytes count")
            with self.assertRaisesRegex(ValueError, "resident bytes changed"):
                seal_checkpoint(root, config, owner="p", writing_stopped=True,
                                retain_payload=True, retention_reason="GUI")

    def test_seal_checkpoint_atomic_failure_is_replayable_through_public_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "paused")
            register_writing(root, config)
            (run / "run_manifest.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
            before = load_capacity_ledger(root)
            with patch("common.contracts.run_capacity_lifecycle.write_json_atomic", side_effect=OSError("interrupted")):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(load_capacity_ledger(root), before)
            command = [sys.executable, "-m", "common.contracts.run_capacity_lifecycle",
                       "--action", "seal-checkpoint", "--artifact-root", str(root),
                       "--run-config", str(config), "--owner", "p", "--confirm-writing-stopped"]
            completed = subprocess.run(command, capture_output=True, text=True, check=False,
                                       cwd=Path(__file__).resolve().parents[2], timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["run_status"], "checkpoint")

    def test_seal_checkpoint_rejects_oversize_light_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_capacity_ledger(root, objects=[])
            run, config = self.fixture(root, "paused")
            register_writing(root, config)
            (run / "run_manifest.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
            with (run / "large.json").open("wb") as stream:
                stream.truncate(26_214_401)
            with self.assertRaisesRegex(ValueError, "not light evidence"):
                seal_checkpoint(root, config, owner="p", writing_stopped=True)
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["status"], "writing")

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
            self.record_heavy_identity(run, heavy)
            heavy_mtime_ns = heavy.stat().st_mtime_ns
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
            self.assertEqual(receipt["approved"], [{
                "path": "simion/field.pa0", "bytes": len(b"rebuildable"),
                "sha256": "A" * 64,
                "mtime_ns": heavy_mtime_ns,
            }])
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

    def test_partial_retirement_sealed_approval_never_adds_another_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = self.fixture(root, "sealed-list")
            approved = run / "one.pa0"
            unlisted = run / "two.pa0"
            approved.write_bytes(b"approved")
            unlisted.write_bytes(b"unlisted")
            self.record_heavy_identity(run, approved)
            approved_mtime_ns = approved.stat().st_mtime_ns
            initialize_capacity_ledger(root, objects=[])
            for path in (approved, unlisted):
                capacity_ledger.record_capacity_object(
                    root, path=path, object_class="rebuildable_payload", bytes_count=path.stat().st_size,
                    status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                    review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
                )
            (run / "partial_retirement_actions.json").write_text(json.dumps({
                "schema_version": 2, "role": "run_partial_retirement_actions", "status": "pending",
                "approved": [{"path": "one.pa0", "bytes": len(b"approved"), "sha256": "A" * 64,
                              "mtime_ns": approved_mtime_ns}],
                "removed_bytes": 0, "preserved": "all unlisted run files",
            }), encoding="utf-8")
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 1, "removed_bytes": len(b"approved"), "blocked_count": 0,
            })
            self.assertFalse(approved.exists())
            self.assertTrue(unlisted.exists())
            receipt = json.loads((run / "partial_retirement_actions.json").read_text(encoding="utf-8"))
            self.assertEqual([item["path"] for item in receipt["approved"]], ["one.pa0"])

    def test_partial_retirement_rejects_same_size_replacement_after_pending_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = self.fixture(root, "identity-change")
            heavy = run / "field.pa0"
            heavy.write_bytes(b"original")
            self.record_heavy_identity(run, heavy)
            approved_mtime_ns = heavy.stat().st_mtime_ns
            initialize_capacity_ledger(root, objects=[])
            capacity_ledger.record_capacity_object(
                root, path=heavy, object_class="rebuildable_payload", bytes_count=heavy.stat().st_size,
                status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
            )
            (run / "partial_retirement_actions.json").write_text(json.dumps({
                "schema_version": 2, "role": "run_partial_retirement_actions", "status": "pending",
                "approved": [{"path": "field.pa0", "bytes": 8, "sha256": "A" * 64,
                              "mtime_ns": approved_mtime_ns}],
                "removed_bytes": 0, "preserved": "all unlisted run files",
            }), encoding="utf-8")
            heavy.write_bytes(b"replaced")
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 0, "removed_bytes": 0, "blocked_count": 1,
            })
            self.assertTrue(heavy.exists())
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["status"], "writing")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = self.fixture(root, "missing-identity")
            heavy = run / "field.pa0"
            heavy.write_bytes(b"untracked")
            initialize_capacity_ledger(root, objects=[])
            capacity_ledger.record_capacity_object(
                root, path=heavy, object_class="rebuildable_payload", bytes_count=heavy.stat().st_size,
                status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
            )
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 0, "removed_bytes": 0, "blocked_count": 1,
            })
            self.assertTrue(heavy.exists())
            self.assertFalse((run / "partial_retirement_actions.json").exists())

    def test_partial_retirement_blocks_pin_lease_and_writing_consumer(self) -> None:
        cases = ("pin", "lease", "consumer")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                run, _ = self.fixture(root, case + "-run")
                heavy = run / "field.pa0"
                heavy.write_bytes(b"protected")
                self.record_heavy_identity(run, heavy)
                initialize_capacity_ledger(root, objects=[])
                kwargs: dict[str, object] = {}
                if case == "pin":
                    kwargs = {"pin": True, "pin_reason": "explicit protection"}
                if case == "consumer":
                    consumer = root / "projects" / "p" / "runs" / "consumer"
                    consumer.mkdir(parents=True)
                    kwargs = {"consumers": [consumer]}
                capacity_ledger.record_capacity_object(
                    root, path=heavy, object_class="rebuildable_payload", bytes_count=heavy.stat().st_size,
                    status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                    review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
                    **kwargs,
                )
                if case == "consumer":
                    capacity_ledger.record_capacity_object(
                        root, path=consumer, object_class="rebuildable_payload", bytes_count=0,
                        status="writing", owner="p", recovery_reason="run_manifest_not_terminal",
                        review_deadline="2026-10-01",
                    )
                if case == "lease":
                    capacity_protection.create_capacity_protection_lease(
                        root, lease_id="partial-retirement-test", owner="test", ttl_seconds=60,
                        protected_paths=[heavy],
                    )
                self.assertEqual(resume_partial_retirements(root), {
                    "completed_count": 0, "removed_bytes": 0, "blocked_count": 1,
                })
                self.assertTrue(heavy.exists())

    def test_partial_retirement_replays_after_unlink_before_ledger_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = self.fixture(root, "interrupted-retirement")
            heavy = run / "field.pa0"
            heavy.write_bytes(b"rebuildable")
            self.record_heavy_identity(run, heavy)
            initialize_capacity_ledger(root, objects=[])
            capacity_ledger.record_capacity_object(
                root, path=heavy, object_class="rebuildable_payload", bytes_count=heavy.stat().st_size,
                status="writing", owner="p", recovery_reason="structured_nonterminal_run_reference",
                review_deadline="2026-10-01", recovery_task="explicit_user_authorized_abandonment",
            )
            original = __import__("common.contracts.run_capacity_lifecycle", fromlist=["write_json_atomic"]).write_json_atomic
            ledger_path = capacity_ledger.resolve_ledger_path(root)

            def interrupt(path: Path, value: dict[str, object]) -> None:
                if path == ledger_path:
                    raise OSError("simulated interruption after unlink")
                original(path, value)

            with patch("common.contracts.run_capacity_lifecycle.write_json_atomic", side_effect=interrupt):
                self.assertEqual(resume_partial_retirements(root), {
                    "completed_count": 0, "removed_bytes": 0, "blocked_count": 1,
                })
            self.assertFalse(heavy.exists())
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["status"], "writing")
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 1, "removed_bytes": len(b"rebuildable"), "blocked_count": 0,
            })
            receipt = json.loads((run / "partial_retirement_actions.json").read_text(encoding="utf-8"))
            self.assertEqual((receipt["status"], receipt["removed_bytes"]), ("complete", len(b"rebuildable")))
            self.assertEqual(load_capacity_ledger(root)["objects"][0]["status"], "retired")
            self.assertEqual(resume_partial_retirements(root), {
                "completed_count": 0, "removed_bytes": 0, "blocked_count": 0,
            })


if __name__ == "__main__":
    unittest.main()
