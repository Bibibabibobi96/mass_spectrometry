from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts import capacity_ledger, capacity_protection, legacy_owner_disposition
from msplatform.execution.run_capacity_lifecycle import resume_partial_retirements
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.legacy_owner_disposition import retire_misplaced_light_run


class OwnerDispositionAuthoringTests(unittest.TestCase):
    def _run(self, root: Path, name: str = "abandoned") -> tuple[Path, Path, Path]:
        run = root / "projects" / "instrument" / "runs" / name
        run.mkdir(parents=True)
        (run / "run_config.json").write_text('{"source":"fixture"}\n', encoding="utf-8")
        preserved = run / "summary.json"
        preserved.write_text('{"result":"keep"}\n', encoding="utf-8")
        heavy = run / "simion" / "field.pa0"
        heavy.parent.mkdir()
        heavy.write_bytes(b"rebuildable payload")
        (run / "run_manifest.json").write_text(json.dumps({"outputs": [{
            "path": "simion/field.pa0", "bytes": heavy.stat().st_size, "sha256": "A" * 64,
        }]}), encoding="utf-8")
        return run, heavy, preserved

    def _initialize(self, root: Path, run: Path, heavy: Path, preserved: Path, **extra: object) -> None:
        capacity_ledger.initialize_capacity_ledger(root, objects=[
            {"path": heavy.relative_to(root).as_posix(), "class": "rebuildable_payload",
             "bytes": heavy.stat().st_size, "status": "writing", "pin": False,
             "owner": "instrument", "recovery_reason": "run_contract_missing_or_invalid",
             "review_deadline": "2026-10-22", **extra},
            {"path": preserved.relative_to(root).as_posix(), "class": "light_evidence",
             "bytes": preserved.stat().st_size, "status": "writing", "pin": False,
             "owner": "instrument", "recovery_reason": "run_contract_missing_or_invalid",
             "review_deadline": "2026-10-22"},
        ], external_scopes=[])

    def _author(self, root: Path, run: Path) -> dict[str, object]:
        return legacy_owner_disposition.author_owner_disposition(
            root, target_path=run.relative_to(root).as_posix(),
            authority_evidence_path=(run / "run_config.json").relative_to(root).as_posix(),
        )

    def test_partial_authorization_marks_only_heavy_file_for_existing_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            ledger_before = (root / "common" / "capacity_ledger.json").read_bytes()
            created = self._author(root, run)
            document_path = Path(str(created["document_path"]))
            document = json.loads(document_path.read_text(encoding="utf-8"))
            self.assertEqual(document["scope"], "partial_run_heavy_files")
            self.assertEqual(document["disposition"]["files"], [{
                "path": "simion/field.pa0", "bytes": heavy.stat().st_size,
            }])
            self.assertEqual((root / "common" / "capacity_ledger.json").read_bytes(), ledger_before)
            self.assertFalse(self._author(root, run)["created"])

            self.assertEqual(legacy_owner_disposition.activate_owner_dispositions(root)["activated_count"], 1)
            by_path = {item["path"]: item for item in capacity_ledger.load_capacity_ledger(root)["objects"]}
            self.assertEqual(by_path[heavy.relative_to(root).as_posix()]["recovery_task"], "explicit_user_authorized_abandonment")
            self.assertNotIn("recovery_task", by_path[preserved.relative_to(root).as_posix()])
            self.assertEqual(resume_partial_retirements(root)["completed_count"], 1)
            self.assertFalse(heavy.exists())
            self.assertTrue(preserved.exists())
            self.assertTrue(document_path.exists())

    def test_rejects_whole_range_and_missing_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, _ = self._run(root)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": run.relative_to(root).as_posix(), "class": "rebuildable_payload",
                "bytes": sum(item.stat().st_size for item in run.rglob("*") if item.is_file()),
                "status": "writing", "pin": False, "owner": "instrument",
                "recovery_reason": "run_contract_missing_or_invalid", "review_deadline": "2026-10-22",
            }], external_scopes=[])
            with self.assertRaisesRegex(ValueError, "no classified eligible heavy ledger file"):
                self._author(root, run)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            (run / "run_manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lacks one manifest identity"):
                self._author(root, run)

    def test_rejects_active_lease_pin_and_consumer(self) -> None:
        for case in ("lease", "pin", "consumer"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "artifacts"
                run, heavy, preserved = self._run(root)
                extra: dict[str, object] = {}
                if case == "pin":
                    extra = {"pin": True, "pin_reason": "must retain"}
                if case == "consumer":
                    consumer = root / "projects" / "instrument" / "runs" / "consumer"
                    consumer.mkdir(parents=True)
                    extra = {"consumers": [consumer.relative_to(root).as_posix()]}
                self._initialize(root, run, heavy, preserved, **extra)
                if case == "consumer":
                    capacity_ledger.record_capacity_object(
                        root, path=consumer, object_class="rebuildable_payload", bytes_count=0,
                        status="writing", owner="instrument",
                        recovery_reason="run_contract_missing_or_invalid", review_deadline="2026-10-22",
                    )
                if case == "lease":
                    capacity_protection.create_capacity_protection_lease(
                        root, lease_id="protect-run", owner="fixture", ttl_seconds=300,
                        protected_paths=[heavy],
                    )
                with self.assertRaisesRegex(ValueError, "(eligible owner-managed|active protection)"):
                    self._author(root, run)

    def test_rejects_gui_pa_and_evidence_outside_exact_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, _, _ = self._run(root)
            review = root / "projects" / "instrument" / "reviews"
            review.mkdir(parents=True)
            (review / "iob.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence must be a regular file in the target"):
                legacy_owner_disposition.author_owner_disposition(
                    root, target_path=run.relative_to(root).as_posix(),
                    authority_evidence_path=(review / "iob.json").relative_to(root).as_posix(),
                )
            with self.assertRaisesRegex(ValueError, "exact project run"):
                legacy_owner_disposition.author_owner_disposition(
                    root, target_path=review.relative_to(root).as_posix(),
                    authority_evidence_path=(review / "iob.json").relative_to(root).as_posix(),
                )

    def test_cli_replays_sealed_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            arguments = ["--workspace-root", str(root), "--target-path", run.relative_to(root).as_posix(),
                         "--authority-evidence-path", (run / "run_config.json").relative_to(root).as_posix()]
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(legacy_owner_disposition.main(arguments), 0)
            self.assertTrue(json.loads(stdout.getvalue())["created"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(legacy_owner_disposition.main(arguments), 0)

    def test_partial_activation_failure_discards_earlier_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            second = heavy.with_name("z-field.pa0")
            second.write_bytes(b"second payload")
            manifest = json.loads((run / "run_manifest.json").read_text())
            manifest["outputs"].append({"path": "simion/z-field.pa0", "bytes": second.stat().st_size, "sha256": "B" * 64})
            (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            other, other_heavy, _ = self._run(root, "independent")
            for path in (second, other_heavy):
                capacity_ledger.record_capacity_object(
                    root, path=path, object_class="rebuildable_payload", bytes_count=path.stat().st_size,
                    status="writing", owner="instrument", recovery_reason="run_contract_missing_or_invalid",
                    review_deadline="2026-10-22")
            self._author(root, run)
            self._author(root, other)
            capacity_ledger.record_capacity_object(
                root, path=second, object_class="rebuildable_payload", bytes_count=second.stat().st_size,
                status="writing", owner="instrument", recovery_reason="run_contract_missing_or_invalid",
                review_deadline="2026-10-22", pin=True, pin_reason="new protection")
            before = capacity_ledger.load_capacity_ledger(root)
            outcome = legacy_owner_disposition.activate_owner_dispositions(root)
            self.assertEqual((outcome["activated_count"], outcome["failed_count"]), (1, 1))
            after = capacity_ledger.load_capacity_ledger(root)
            for path in (heavy, second):
                relative = path.relative_to(root).as_posix()
                self.assertEqual(next(row for row in before["objects"] if row["path"] == relative),
                                 next(row for row in after["objects"] if row["path"] == relative))
            other_entry = next(row for row in after["objects"] if row["path"] == other_heavy.relative_to(root).as_posix())
            self.assertEqual(other_entry["recovery_task"], "explicit_user_authorized_abandonment")
            self.assertTrue(heavy.exists() and second.exists() and other_heavy.exists())


class MisplacedLightRunRecoveryTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        from common.contracts.write_run_manifest import build_run_manifest, file_record
        source = root / "projects/p/runs/runs/20261017_000000__analysis__python__misplaced"
        source.mkdir(parents=True)
        config = dict(schema_version=2, project="p", run_id=source.name, mode="target_authoring", inputs={},
                      artifact_retention=dict(policy_version=1, **{"class": "compact"}, reason=None),
                      capacity_ledger_lifecycle=dict(schema_version=1, enabled=True, artifact_root=str(root),
                                                     light_evidence_budget_bytes=26214400))
        (source / "run_config.json").write_text(json.dumps(config))
        (source / "summary.json").write_text('{"status":"success"}')
        (source / "result.json").write_text('{"target":340}')
        (source / "retention_actions.json").write_text(json.dumps(dict(schema_version=1,
            role="artifact_retention_actions", status="complete", retention_class="compact")))
        manifest = build_run_manifest(source / "run_config.json", "success",
                                      output_paths=[source / n for n in ("summary.json", "result.json", "retention_actions.json")])
        (source / "run_manifest.json").write_text(json.dumps(manifest))
        backup = root / "projects/p/runs/20261017_000001__analysis__python__backup"
        snapshot = backup / "inputs/misplaced_run_snapshot"
        shutil.copytree(source, snapshot)
        (backup / "results").mkdir()
        inventory = [dict(path=p.name, bytes=p.stat().st_size, sha256=file_record(p)["sha256"],
                          backup_record=file_record(snapshot / p.name)) for p in sorted(source.iterdir())]
        (backup / "results/misplaced_run_backup_receipt.json").write_text(json.dumps(dict(schema_version=1,
            role="misplaced_light_run_backup", source_run=str(source), source_manifest=file_record(source / "run_manifest.json"),
            inventory=inventory)))
        backup_config = dict(schema_version=1, project="p", run_id=backup.name, mode="misplaced_light_run_backup",
                             inputs={p.name: str(p) for p in snapshot.iterdir()})
        (backup / "run_config.json").write_text(json.dumps(backup_config))
        self.seal_backup(backup)
        total = sum(p.stat().st_size for p in source.iterdir())
        initialize_capacity_ledger(root, objects=[dict(path=source.relative_to(root).as_posix(),
            **{"class": "light_evidence"}, bytes=total, status="ready", pin=False, owner="runs")])
        return source, backup, backup / "run_manifest.json"

    @staticmethod
    def seal_backup(backup: Path) -> None:
        from common.contracts.write_run_manifest import build_run_manifest
        manifest = build_run_manifest(backup / "run_config.json", "success",
                                      output_paths=[backup / "results/misplaced_run_backup_receipt.json"])
        (backup / "run_manifest.json").write_text(json.dumps(manifest))

    def test_exact_backup_dry_run_apply_and_replay_preserve_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, backup, manifest = self.fixture(root)
            original = {p.name: p.read_bytes() for p in source.iterdir()}
            before = load_capacity_ledger(root)
            result = retire_misplaced_light_run(root, source / "run_config.json", backup_manifest=manifest, owner="p")
            self.assertTrue(result["dry_run"])
            self.assertFalse(Path(result["journal_path"]).exists())
            self.assertEqual(load_capacity_ledger(root), before)
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, original)
            result = retire_misplaced_light_run(root, source / "run_config.json", backup_manifest=manifest, owner="p", apply=True)
            self.assertEqual(result["status"], "complete")
            self.assertFalse(source.exists())
            self.assertFalse(source.parent.exists())
            ledger = load_capacity_ledger(root)
            self.assertEqual(ledger["resident_bytes"], 0)
            self.assertEqual(ledger["objects"][0]["owner"], "runs")
            self.assertEqual(ledger["objects"][0]["class"], "light_evidence")
            self.assertEqual({p.name: p.read_bytes() for p in (backup / "inputs/misplaced_run_snapshot").iterdir()}, original)
            replay = retire_misplaced_light_run(root, source / "run_config.json", backup_manifest=manifest, owner="p", apply=True)
            self.assertTrue(replay["replayed"])
            self.assertEqual(load_capacity_ledger(root), ledger)

    def test_rejects_ordinary_scope_owner_changed_content_incomplete_backup_and_protection(self):
        for scenario in ("ordinary", "owner", "ledger_owner", "changed", "omitted", "backup_changed", "pinned", "consumer", "lease"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, backup, manifest = self.fixture(root)
                owner, config_path = "p", source / "run_config.json"
                if scenario == "ordinary":
                    config_path = source.parent.parent / source.name / "run_config.json"
                elif scenario == "owner":
                    owner = "other"
                elif scenario in ("ledger_owner", "pinned"):
                    ledger = load_capacity_ledger(root)
                    if scenario == "ledger_owner":
                        ledger["objects"][0]["owner"] = "p"
                    else:
                        ledger["objects"][0].update(pin=True, pin_reason="keep")
                    from msplatform.execution.recorded_file_removal import write_json_atomic
                    write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
                elif scenario == "changed":
                    (source / "result.json").write_text('{"target":360}')
                elif scenario == "omitted":
                    proof_path = backup / "results/misplaced_run_backup_receipt.json"
                    proof = json.loads(proof_path.read_text())
                    proof["inventory"] = [r for r in proof["inventory"] if r["path"] != "result.json"]
                    proof_path.write_text(json.dumps(proof))
                    self.seal_backup(backup)
                elif scenario == "backup_changed":
                    (backup / "inputs/misplaced_run_snapshot/result.json").write_text("changed")
                elif scenario == "consumer":
                    capacity_ledger.record_capacity_object(root, path="projects/p/runs/consumer", object_class="light_evidence",
                        bytes_count=0, status="writing", owner="p", recovery_reason="active", review_deadline="2099-01-01",
                        consumers=[source])
                else:
                    capacity_protection.create_capacity_protection_lease(root, lease_id="protected", owner="test", ttl_seconds=600,
                        committed_new_bytes=0, protected_paths=[source])
                before = capacity_ledger.resolve_ledger_path(root).read_bytes()
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    retire_misplaced_light_run(root, config_path, backup_manifest=manifest, owner=owner, apply=True)
                self.assertTrue(source.exists())
                self.assertEqual(capacity_ledger.resolve_ledger_path(root).read_bytes(), before)

    def test_partial_deletion_and_publication_interruptions_resume_without_resetting_bytes(self):
        from msplatform.execution.recorded_file_removal import remove_recorded_files, write_json_atomic
        for scenario in ("remove", "ledger_pending", "ledger_final", "journal_complete"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, _, manifest = self.fixture(root)
                initial_bytes = load_capacity_ledger(root)["resident_bytes"]
                def interrupted_remove(directory, records, **kwargs):
                    next(remove_recorded_files(directory, records, **kwargs))
                    raise OSError("injected removal interruption")
                    yield  # Iterator protocol matches the public executor.
                def interrupted_write(path, document):
                    if ((scenario == "ledger_pending" and path == capacity_ledger.resolve_ledger_path(root)
                         and document["objects"][0]["status"] == "retirement_pending")
                        or (scenario == "ledger_final" and path == capacity_ledger.resolve_ledger_path(root)
                            and document["objects"][0]["status"] == "retired")
                        or (scenario == "journal_complete" and document.get("role") == "misplaced_light_run_retirement"
                            and document.get("status") == "complete")):
                        raise OSError("injected publication interruption")
                    write_json_atomic(path, document)
                with patch("common.contracts.legacy_owner_disposition.write_json_atomic", side_effect=interrupted_write), \
                     patch("common.contracts.legacy_owner_disposition.remove_recorded_files",
                           side_effect=interrupted_remove if scenario == "remove" else remove_recorded_files):
                    with self.assertRaises(OSError):
                        retire_misplaced_light_run(root, source / "run_config.json", backup_manifest=manifest, owner="p", apply=True)
                self.assertIn(load_capacity_ledger(root)["resident_bytes"], (initial_bytes, 0))
                result = retire_misplaced_light_run(root, source / "run_config.json", backup_manifest=manifest, owner="p", apply=True)
                self.assertEqual(result["status"], "complete")
                self.assertEqual(load_capacity_ledger(root)["resident_bytes"], 0)
                self.assertFalse(source.exists())

    def test_public_cli_requires_explicit_action_and_host_lease_for_apply(self):
        from common.contracts.legacy_owner_disposition import main
        arguments = ["lifecycle", "--action", "retire-misplaced-light-run", "--artifact-root", "unused",
                     "--run-config", "config.json", "--backup-manifest", "backup.json", "--owner", "p"]
        with patch.object(sys, "argv", arguments), patch(
                "common.contracts.legacy_owner_disposition.retire_misplaced_light_run", return_value={}) as retire:
            self.assertEqual(main(), 0)
            self.assertFalse(retire.call_args.kwargs["apply"])
        with patch.object(sys, "argv", arguments + ["--apply"]), patch.dict(os.environ, {
                "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": ""}), patch(
                "common.contracts.legacy_owner_disposition.retire_misplaced_light_run") as retire:
            with self.assertRaises(SystemExit):
                main()
            retire.assert_not_called()


if __name__ == "__main__":
    unittest.main()
