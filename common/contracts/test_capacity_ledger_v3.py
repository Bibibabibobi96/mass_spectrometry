"""Managed-range requirements for capacity-ledger schema v3."""

from __future__ import annotations

import base64
import copy
import json
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path

from common.contracts import capacity_ledger


IDENTITY = "a" * 64
READY_RANGE = {
    "owner": "parallel_mirror_dual_stripe_mr_tof",
}
WRITING_RANGE = {
    **READY_RANGE,
    "review_deadline": "2026-10-22",
    "recovery_reason": "publication interrupted before verification",
    "recovery_task": "owner must resume or retire the exact transaction",
    "recovery_evidence_paths": ["transactions/tx/transaction.json"],
}


class CapacityLedgerV3Test(unittest.TestCase):
    def key_recovery_fixture(self, root):
        from common.contracts.file_identity import file_sha256
        from common.contracts.recorded_file_removal import write_json_atomic
        document = capacity_ledger.initialize_capacity_ledger(root, objects=[dict(
            path="projects/example/scratch/old/empty.log", **{"class": "rebuildable_payload"},
            bytes=0, status="retired", pin=False, owner="example")])
        ledger = capacity_ledger.resolve_ledger_path(root)
        raw = ledger.read_bytes()
        directory = root/"common/capacity_disposal_receipts"
        backup, receipt = directory/"original_raw.json", directory/"original_recovery.json"
        digest = file_sha256(ledger)
        write_json_atomic(backup, dict(schema_version=1, role="capacity_ledger_damaged_raw_backup",
            bytes=len(raw), sha256=digest, base64=base64.b64encode(raw).decode()))
        write_json_atomic(receipt, dict(schema_version=1, role="capacity_ledger_retired_path_recovery",
            status="complete", original_sha256=digest, raw_backup_path=str(backup)))
        ledger.write_bytes(raw.replace(b'"path":', b'"pAth":'))
        return document, ledger, receipt, dict(receipt_path=receipt,
            expected_ledger_sha256=file_sha256(ledger), expected_receipt_sha256=file_sha256(receipt))

    def test_path_key_restore_preserves_every_other_raw_byte_and_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original, ledger, _, args = self.key_recovery_fixture(root)
            raw = ledger.read_bytes()
            result = capacity_ledger.restore_retired_path_key(root, **args)
            self.assertTrue(result["dry_run"])
            self.assertEqual(ledger.read_bytes(), raw)
            result = capacity_ledger.restore_retired_path_key(root, **args, apply=True)
            self.assertEqual(ledger.read_bytes(), raw.replace(b'"pAth":', b'"path":', 1))
            self.assertEqual(capacity_ledger.load_capacity_ledger(root), original)
            self.assertEqual(base64.b64decode(json.loads(Path(result["raw_backup_path"]).read_bytes())["base64"]), raw)
            self.assertTrue(capacity_ledger.restore_retired_path_key(root, **args, apply=True)["replayed"])

    def test_path_key_restore_rejects_other_changes_and_reappeared_payload(self):
        from common.contracts.file_identity import file_sha256
        for mode in ("resident", "record", "live", "bytes", "two_keys", "reappeared", "receipt", "backup"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                _, ledger, receipt, args = self.key_recovery_fixture(root)
                document = json.loads(ledger.read_bytes())
                item = document["objects"][0]
                if mode == "resident":document["resident_bytes"] = 1
                elif mode == "record":item["owner"] = "different"
                elif mode == "live":item["status"] = "ready"
                elif mode == "bytes":item["bytes"] = 1
                elif mode == "two_keys":document["objects"].append(dict(item))
                elif mode == "reappeared":
                    path = root/item["pAth"];path.parent.mkdir(parents=True);path.touch()
                elif mode == "receipt":receipt.write_text("{}")
                elif mode == "backup":(receipt.parent/"original_raw.json").write_text("{}")
                ledger.write_text(json.dumps(document))
                args["expected_ledger_sha256"] = file_sha256(ledger)
                before = ledger.read_bytes()
                with self.assertRaises((ValueError, KeyError)):
                    capacity_ledger.restore_retired_path_key(root, **args, apply=True)
                self.assertEqual(ledger.read_bytes(), before)

    def test_path_key_restore_replays_both_atomic_publication_boundaries(self):
        from common.contracts.recorded_file_removal import write_json_atomic
        for boundary in ("replace", "complete"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                original, ledger, _, args = self.key_recovery_fixture(root)
                def publish(path, value):
                    if boundary == "complete" and value.get("role") == "capacity_ledger_retired_key_recovery" and value["status"] == "complete":
                        raise OSError("injected complete failure")
                    write_json_atomic(path, value)
                real_replace = capacity_ledger.os.replace
                def replace(source, destination):
                    if boundary == "replace" and Path(destination) == ledger:
                        raise OSError("injected rename")
                    return real_replace(source, destination)
                with patch.object(capacity_ledger, "write_json_atomic", side_effect=publish), \
                     patch.object(capacity_ledger.os, "replace", side_effect=replace):
                    with self.assertRaises(OSError):
                        capacity_ledger.restore_retired_path_key(root, **args, apply=True)
                self.assertEqual(capacity_ledger.restore_retired_path_key(root, **args, apply=True)["status"], "complete")
                self.assertEqual(capacity_ledger.load_capacity_ledger(root), original)

    def test_path_key_restore_preserves_conflicting_evidence_after_pre_rename_interruption(self):
        for damaged in ("raw_backup", "pending_journal"):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                _, ledger, authority, args = self.key_recovery_fixture(root)
                real_replace = capacity_ledger.os.replace
                def interrupt(source, destination):
                    if Path(destination) == ledger:
                        raise OSError("injected before ledger rename")
                    return real_replace(source, destination)
                with patch.object(capacity_ledger.os, "replace", side_effect=interrupt):
                    with self.assertRaisesRegex(OSError, "before ledger rename"):
                        capacity_ledger.restore_retired_path_key(root, **args, apply=True)
                stem = "ledger_key_recovery_" + args["expected_ledger_sha256"]
                backup = authority.parent / (stem + "_raw.json")
                journal = authority.parent / (stem + ".json")
                path = backup if damaged == "raw_backup" else journal
                document = json.loads(path.read_bytes())
                document["sha256" if damaged == "raw_backup" else "resident_bytes"] = (
                    "F"*64 if damaged == "raw_backup" else 1)
                path.write_text(json.dumps(document), encoding="utf-8")
                snapshots = {item:item.read_bytes() for item in (ledger, authority, backup, journal)}
                for apply in (False, True):
                    with self.assertRaisesRegex(ValueError, "conflicts"):
                        capacity_ledger.restore_retired_path_key(root, **args, apply=apply)
                    self.assertEqual({item:item.read_bytes() for item in snapshots}, snapshots)

    def test_path_key_replay_rederives_exact_candidate_instead_of_trusting_journal_digest(self):
        from common.contracts.file_identity import file_sha256
        for damaged in ("ledger_and_journal", "replay_backup"):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                _, ledger, authority, args = self.key_recovery_fixture(root)
                result = capacity_ledger.restore_retired_path_key(root, **args, apply=True)
                backup = Path(result["raw_backup_path"])
                journal = authority.parent / ("ledger_key_recovery_" + args["expected_ledger_sha256"] + ".json")
                if damaged == "ledger_and_journal":
                    document = json.loads(ledger.read_bytes())
                    document["objects"][0]["owner"] = "different_but_schema_valid"
                    ledger.write_text(json.dumps(document), encoding="utf-8")
                    self.assertIsNotNone(capacity_ledger.load_capacity_ledger(root))
                    prior = json.loads(journal.read_bytes())
                    prior.update(status="pending", candidate_sha256=file_sha256(ledger))
                    journal.write_text(json.dumps(prior), encoding="utf-8")
                    message = "changed more than the original key"
                else:
                    saved = json.loads(backup.read_bytes())
                    saved["bytes"] += 1
                    backup.write_text(json.dumps(saved), encoding="utf-8")
                    message = "raw evidence differs"
                snapshots = {item:item.read_bytes() for item in (ledger, authority, backup, journal)}
                for apply in (False, True):
                    with self.assertRaisesRegex(ValueError, message):
                        capacity_ledger.restore_retired_path_key(root, **args, apply=apply)
                    self.assertEqual({item:item.read_bytes() for item in snapshots}, snapshots)

    def recovery_fixture(self, root):
        from common.contracts.file_identity import file_sha256
        from common.contracts.recorded_file_removal import write_json_atomic
        relative = "projects/example/runs/retired"
        disposition = dict(id="A"*64, generation="B"*64, manifest_path="run_config.json",
                           files=[dict(path="logs/old.log", bytes=7), dict(path="logs/ok.log", bytes=3)])
        document = capacity_ledger.initialize_capacity_ledger(root, objects=[dict(
            path=relative, **{"class": "rebuildable_payload"}, bytes=10, status="retired", pin=False,
            owner="example", disposition=disposition)])
        receipt = root/"common/capacity_disposal_receipts"/("ledger_disposition_"+"A"*64+".json")
        write_json_atomic(receipt, dict(schema_version=1, role="artifact_capacity_disposal_receipt",
            status="complete", reason="manager_approved_disposition", target_path=str(root/relative),
            disposition=disposition, removed=["logs/ok.log", "logs/old.log"], removed_bytes=10,
            deleting_path=None, owner_disposition_authorization=dict(owner="example",target_path=relative,
                authority_evidence=dict(path="run_config.json"))))
        damaged = copy.deepcopy(document)
        damaged["objects"][0]["disposition"]["files"][0]["path"] = "logs/\udc94broken.log"
        raw = (json.dumps(damaged, ensure_ascii=False)+"\n").encode("utf-8",errors="surrogateescape")
        ledger = capacity_ledger.resolve_ledger_path(root)
        ledger.write_bytes(raw)
        return document, ledger, receipt, dict(receipt_path=receipt,
            expected_ledger_sha256=file_sha256(ledger),expected_receipt_sha256=file_sha256(receipt))

    def test_restore_retired_path_dryrun_atomic_publication_and_preserved_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original, ledger, receipt, args = self.recovery_fixture(root)
            raw = ledger.read_bytes()
            before = set(root.rglob("*"))
            preview = capacity_ledger.restore_retired_disposition_paths(root, **args)
            self.assertTrue(preview["dry_run"])
            self.assertEqual(set(root.rglob("*")), before)
            self.assertEqual(ledger.read_bytes(), raw)
            result = capacity_ledger.restore_retired_disposition_paths(root, **args, apply=True)
            self.assertEqual(result["status"], "complete")
            backup=json.loads(Path(result["raw_backup_path"]).read_text())
            self.assertEqual(base64.b64decode(backup["base64"],validate=True), raw)
            self.assertEqual(backup["bytes"], len(raw))
            self.assertTrue(all(p.suffix==".json" for p in receipt.parent.iterdir()))
            self.assertEqual(capacity_ledger.load_capacity_ledger(root), original)
            self.assertEqual(capacity_ledger.restore_retired_disposition_paths(root, **args, apply=True)["status"], "complete")

    def test_restore_retired_path_rejects_corrupt_base64_backup(self):
        from common.contracts.recorded_file_removal import write_json_atomic
        for corruption in ("base64", "bytes", "content", "sha256"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve()
                _,ledger,_,args=self.recovery_fixture(root)
                result=capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                backup_path=Path(result["raw_backup_path"])
                backup=json.loads(backup_path.read_text())
                if corruption=="base64":
                    backup["base64"]="!bad"
                elif corruption=="content":
                    backup["base64"]=base64.b64encode(b"changed").decode("ascii")
                elif corruption=="sha256":
                    backup["sha256"]="F"*64
                else:
                    backup["bytes"]+=1
                write_json_atomic(backup_path,backup)
                before=ledger.read_bytes()
                with self.assertRaises(ValueError):
                    capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                self.assertEqual(ledger.read_bytes(),before)

    def test_restore_retired_path_rejects_other_damage_and_identity_changes(self):
        from common.contracts.file_identity import file_sha256
        mutations = {
            "owner": lambda d: d["objects"][0].update(owner="other"),
            "active": lambda d: d["objects"][0].update(status="ready"),
            "pin": lambda d: d["objects"][0].update(pin=True),
            "resident": lambda d: d.update(resident_bytes=99),
            "generation": lambda d: d["objects"][0]["disposition"].update(generation="C"*64),
            "bytes": lambda d: d["objects"][0]["disposition"]["files"][0].update(bytes=8),
            "validpath": lambda d: d["objects"][0]["disposition"]["files"][0].update(path="logs/different.log"),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve()
                _, ledger, _, args=self.recovery_fixture(root)
                d=json.loads(ledger.read_bytes().decode("utf-8",errors="surrogateescape"))
                mutation(d)
                raw=json.dumps(d,ensure_ascii=False).encode("utf-8",errors="surrogateescape")
                ledger.write_bytes(raw)
                args["expected_ledger_sha256"]=file_sha256(ledger)
                with self.assertRaises(ValueError):
                    capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                self.assertEqual(ledger.read_bytes(),raw)
        for change in ("valid", "ledger_sha", "receipt_sha"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve()
                original,ledger,receipt,args=self.recovery_fixture(root)
                if change=="valid":
                    from common.contracts.recorded_file_removal import write_json_atomic
                    write_json_atomic(ledger,original)
                    args["expected_ledger_sha256"]=file_sha256(ledger)
                elif change=="ledger_sha":
                    ledger.write_bytes(ledger.read_bytes()+b" ")
                else:
                    receipt.write_bytes(receipt.read_bytes()+b" ")
                before=ledger.read_bytes()
                with self.assertRaises(ValueError):
                    capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                self.assertEqual(ledger.read_bytes(),before)

    def test_restore_retired_path_rejects_receipt_conflicts_and_locked_cas_change(self):
        from common.contracts.file_identity import file_sha256
        from common.contracts.recorded_file_removal import write_json_atomic
        changes = {
            "owner": lambda r: r["owner_disposition_authorization"].update(owner="other"),
            "target": lambda r: r.update(target_path=str(Path(r["target_path"]).parent/"other")),
            "generation": lambda r: r["disposition"].update(generation="C"*64),
            "id": lambda r: r["disposition"].update(id="D"*64),
            "pending": lambda r: r.update(status="pending"),
            "removed": lambda r: r.update(removed=[]),
            "count": lambda r: r["disposition"]["files"].pop(),
            "bytes": lambda r: r.update(removed_bytes=11),
        }
        for name, mutate in changes.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve()
                _,ledger,receipt,args=self.recovery_fixture(root)
                value=json.loads(receipt.read_text())
                mutate(value)
                write_json_atomic(receipt,value)
                args["expected_receipt_sha256"]=file_sha256(receipt)
                raw=ledger.read_bytes()
                with self.assertRaises(ValueError):
                    capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                self.assertEqual(ledger.read_bytes(),raw)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            _,ledger,_,args=self.recovery_fixture(root)
            changed=ledger.read_bytes()+b" "
            def publish(path,value):
                write_json_atomic(path,value)
                if value.get("role")=="capacity_ledger_retired_path_recovery":
                    ledger.write_bytes(changed)
            with patch.object(capacity_ledger,"write_json_atomic",side_effect=publish):
                with self.assertRaisesRegex(ValueError,"source changed"):
                    capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
            self.assertEqual(ledger.read_bytes(),changed)

    def test_restore_retired_path_publication_failures_replay_from_pending(self):
        from common.contracts.recorded_file_removal import write_json_atomic
        for failure in ("ledger", "complete"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve()
                original,ledger,_,args=self.recovery_fixture(root)
                def publish(path,value):
                    if ((failure=="ledger" and path==ledger) or
                            (failure=="complete" and value.get("role")=="capacity_ledger_retired_path_recovery"
                             and value.get("status")=="complete")):
                        raise OSError("injected publication failure")
                    write_json_atomic(path,value)
                with patch.object(capacity_ledger,"write_json_atomic",side_effect=publish):
                    with self.assertRaises(OSError):
                        capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                result=capacity_ledger.restore_retired_disposition_paths(root,**args,apply=True)
                self.assertEqual(result["status"],"complete")
                self.assertEqual(capacity_ledger.load_capacity_ledger(root),original)

    def test_v3_rejects_resident_ranges_without_an_owner_or_writing_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing_ready = {
                "path": "cache/key", "class": "published_cache", "bytes": 1,
                "status": "ready", "pin": False, "identity": IDENTITY,
            }
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[missing_ready])
            missing_writing = {
                "path": "transactions/tx", "class": "rebuildable_payload", "bytes": 1,
                "status": "writing", "pin": False, **READY_RANGE,
                "recovery_reason": "interrupted",
            }
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[missing_writing])

    def test_v3_accepts_governed_ready_and_writing_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = capacity_ledger.initialize_capacity_ledger(root, objects=[
                {
                    "path": "cache/key", "class": "published_cache", "bytes": 7,
                    "status": "ready", "pin": False, "identity": IDENTITY,
                    "manager": capacity_ledger.PA_CACHE_MANAGER, **READY_RANGE,
                },
                {
                    "path": "transactions/tx", "class": "rebuildable_payload", "bytes": 3,
                    "status": "writing", "pin": False, **WRITING_RANGE,
                },
            ])
            self.assertEqual(document["schema_version"], 3)
            self.assertEqual(document["resident_bytes"], 10)
            self.assertIsNotNone(capacity_ledger.load_capacity_ledger(root))

    def test_v3_recording_refuses_unowned_ranges_and_preserves_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            with self.assertRaisesRegex(ValueError, "managed ranges require"):
                capacity_ledger.record_capacity_object(
                    root, path="transactions/tx", object_class="rebuildable_payload",
                    bytes_count=1, status="writing",
                )
            entry = capacity_ledger.record_capacity_object(
                root, path="transactions/tx", object_class="rebuildable_payload",
                bytes_count=1, status="writing", **WRITING_RANGE,
            )
            self.assertEqual(entry["recovery_evidence_paths"], ["transactions/tx/transaction.json"])

    def test_v3_requires_the_pa_manager_but_drops_duplicated_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            object_record = {
                "path": "cache/key", "class": "published_cache", "bytes": 1,
                "status": "ready", "pin": False, "identity": IDENTITY,
                "manager": "unknown.manager", **READY_RANGE,
            }
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[object_record])
            object_record["manager"] = capacity_ledger.PA_CACHE_MANAGER
            object_record["retirement_route"] = "owner_managed_disposition"
            document = capacity_ledger.initialize_capacity_ledger(root, objects=[object_record])
            self.assertNotIn("retirement_route", document["objects"][0])

    def test_v2_transition_requires_explicit_complete_duty_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2 = {
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root.resolve()), "resident_bytes": 1,
                "objects": [{
                    "path": "cache/key", "class": "published_cache", "bytes": 1,
                    "status": "ready", "pin": False, "identity": IDENTITY,
                }], "external_scopes": [],
            }
            with self.assertRaisesRegex(ValueError, "cover exactly"):
                capacity_ledger.migrate_v2_ledger_document(root, v2, lifecycle_by_path={})
            migrated = capacity_ledger.migrate_v2_ledger_document(
                root, v2, lifecycle_by_path={"cache/key": READY_RANGE},
            )
            self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["objects"][0]["manager"], capacity_ledger.PA_CACHE_MANAGER)


class ProjectCacheApprovalTest(unittest.TestCase):
    def test_exact_owner_approval_preserves_bytes_and_rechecks_consumers(self):
        from common.contracts import capacity_protection
        from unittest.mock import Mock
        owner = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        relative = "projects/"+owner+"/cache/simion_single_flight_accelerator_main/"+"a"*64
        for scenario in ("valid", "basis_valid", "basis_owner", "owner", "consumer", "ancestor", "namespace", "pin"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target_relative = relative.replace("simion_single_flight_accelerator_main", "simion_pa_basis") if scenario.startswith("basis_") else relative
                target = root / target_relative
                target.mkdir(parents=True)
                entry = dict(path=target_relative, **{"class":"published_cache"}, bytes=7,
                             status="ready", pin=scenario=="pin", identity="b"*64,
                             owner="other" if scenario=="basis_owner" else owner)
                if scenario=="pin":
                    entry["pin_reason"]="retained"
                entries=[entry]
                if scenario=="consumer":
                    entries.append(dict(path="projects/"+owner+"/runs/live", **{"class":"rebuildable_payload"},
                        bytes=0,status="writing",pin=False,**WRITING_RANGE,consumers=[relative]))
                capacity_ledger.initialize_capacity_ledger(root, objects=entries)
                if scenario=="ancestor":
                    capacity_protection.create_capacity_protection_lease(root,lease_id="test",owner=owner,
                        ttl_seconds=60,protected_paths=[target.parent])
                callback=Mock()
                arguments=dict(path=target,expected_identity="b"*64,expected_bytes=7,
                    disposition_id="c"*64,manifest_sha256="d"*64,
                    files=[dict(path="payload.pa",bytes=7,sha256="e"*64)],
                    expected_project_owner=owner if scenario!="owner" else "other",commit_owner_retirement=callback)
                if scenario=="namespace":
                    arguments["path"]=root/"unregistered"
                if scenario not in {"valid", "basis_valid"}:
                    with self.assertRaises(ValueError):
                        capacity_ledger.approve_published_cache_retirement(root,**arguments)
                    callback.assert_not_called()
                else:
                    approved=capacity_ledger.approve_published_cache_retirement(root,**arguments)
                    self.assertEqual(approved["class"],"rebuildable_payload")
                    self.assertEqual(capacity_ledger.load_capacity_ledger(root)["resident_bytes"],7)
                    self.assertEqual(capacity_ledger.approve_published_cache_retirement(root,**arguments),approved)
                    self.assertEqual(callback.call_count,2)


if __name__ == "__main__":
    unittest.main()
