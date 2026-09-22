"""Finite-lifecycle requirements for capacity-ledger schema v3."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts import capacity_ledger


IDENTITY = "a" * 64
READY_DUTIES = {
    "owner": "parallel_mirror_dual_stripe_mr_tof",
    "retention_reason": "current GUI-inspectable native PA generation",
    "review_deadline": "2026-10-22",
    "retirement_route": "pa_manager_disposition",
}
WRITING_DUTIES = {
    **READY_DUTIES,
    "recovery_reason": "publication interrupted before verification",
    "recovery_task": "owner must resume or retire the exact transaction",
    "recovery_evidence_paths": ["transactions/tx/transaction.json"],
}


class CapacityLedgerV3Test(unittest.TestCase):
    def test_v3_rejects_resident_objects_without_finite_lifecycle_duties(self) -> None:
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
                "status": "writing", "pin": False, **READY_DUTIES,
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
                    "manager": capacity_ledger.PA_CACHE_MANAGER, **READY_DUTIES,
                },
                {
                    "path": "transactions/tx", "class": "rebuildable_payload", "bytes": 3,
                    "status": "writing", "pin": False, **WRITING_DUTIES,
                },
            ])
            self.assertEqual(document["schema_version"], 3)
            self.assertEqual(document["resident_bytes"], 10)
            self.assertIsNotNone(capacity_ledger.load_capacity_ledger(root))

    def test_v3_recording_refuses_unowned_writes_and_preserves_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            with self.assertRaisesRegex(ValueError, "resident ledger objects require"):
                capacity_ledger.record_capacity_object(
                    root, path="transactions/tx", object_class="rebuildable_payload",
                    bytes_count=1, status="writing",
                )
            entry = capacity_ledger.record_capacity_object(
                root, path="transactions/tx", object_class="rebuildable_payload",
                bytes_count=1, status="writing", **WRITING_DUTIES,
            )
            self.assertEqual(entry["recovery_evidence_paths"], ["transactions/tx/transaction.json"])

    def test_v3_rejects_ungoverned_published_cache_manager_or_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            object_record = {
                "path": "cache/key", "class": "published_cache", "bytes": 1,
                "status": "ready", "pin": False, "identity": IDENTITY,
                "manager": "unknown.manager", **READY_DUTIES,
            }
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[object_record])
            object_record["manager"] = capacity_ledger.PA_CACHE_MANAGER
            object_record["retirement_route"] = "owner_managed_disposition"
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[object_record])

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
                root, v2, lifecycle_by_path={"cache/key": READY_DUTIES},
            )
            self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["objects"][0]["manager"], capacity_ledger.PA_CACHE_MANAGER)


if __name__ == "__main__":
    unittest.main()
