"""Focused tests for the atomic prepared-stage capacity handoff."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts import capacity_ledger


IDENTITY = "a" * 64
PUBLISHED_DUTIES = {
    "owner": "common.simion.pa_family_cache",
    "retention_reason": "active native PA generation",
    "review_deadline": "2026-10-22",
    "retirement_route": "pa_manager_disposition",
}
WRITING_DUTIES = {
    "retention_reason": "prepared native PA publication",
    "review_deadline": "2026-10-22",
    "retirement_route": "pa_manager_disposition",
    "recovery_task": "resume or retire the exact PA transaction",
    "recovery_evidence_paths": ["staging/prepared/transaction.json"],
}


class CapacityLedgerHandoffTest(unittest.TestCase):
    def _root(self, temporary: str) -> Path:
        root = Path(temporary)
        (root / "cache" / "key").mkdir(parents=True)
        return root

    def _stage(
        self, root: Path, *, owner: str = "publisher", size: int = 17,
        consumer: str = "cache/key",
    ) -> None:
        capacity_ledger.record_capacity_object(
            root,
            path="staging/prepared",
            object_class="rebuildable_payload",
            bytes_count=size,
            status="writing",
            owner=owner,
            **WRITING_DUTIES,
            recovery_reason="prepared cache publication",
            consumers=[consumer],
        )

    def _handoff(self, root: Path, **kwargs: object) -> dict[str, object]:
        duties = {
            f"published_{field}": value for field, value in PUBLISHED_DUTIES.items()
        }
        return capacity_ledger.handoff_prepared_cache_stage(
            root, **duties, **kwargs,
        )

    def test_handoff_replaces_stage_without_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            self._stage(root)

            result = self._handoff(
                root,
                stage_path="staging/prepared",
                stage_owner="publisher",
                stage_bytes=17,
                published_path="cache/key",
                published_identity=IDENTITY,
                published_bytes=19,
            )

            self.assertEqual(result["resident_bytes"], 19)
            self.assertEqual(result["stage"]["status"], "retired")
            self.assertNotIn("owner", result["stage"])
            self.assertEqual(result["published"]["status"], "ready")
            self.assertEqual(result["published"]["identity"], IDENTITY)
            self.assertIsNotNone(capacity_ledger.load_capacity_ledger(root))

    def test_competing_hit_retires_only_duplicate_stage_and_retry_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[{
                    "path": "cache/key",
                    "class": "published_cache",
                    "bytes": 17,
                "status": "ready",
                "pin": False,
                "identity": IDENTITY,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
                **PUBLISHED_DUTIES,
                }],
            )
            self._stage(root)
            self.assertEqual(capacity_ledger.load_capacity_ledger(root)["resident_bytes"], 34)

            first = self._handoff(
                root,
                stage_path="staging/prepared",
                stage_owner="publisher",
                stage_bytes=17,
                published_path="cache/key",
                published_identity=IDENTITY,
                published_bytes=17,
            )
            second = self._handoff(
                root,
                stage_path="staging/prepared",
                stage_owner="publisher",
                stage_bytes=17,
                published_path="cache/key",
                published_identity=IDENTITY,
                published_bytes=17,
            )

            self.assertEqual(first, second)
            self.assertEqual(second["resident_bytes"], 17)
            self.assertEqual(len(capacity_ledger.load_capacity_ledger(root)["objects"]), 2)

    def test_handoff_pins_published_cache_in_the_same_ledger_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            self._stage(root)

            first = self._handoff(
                root,
                stage_path="staging/prepared",
                stage_owner="publisher",
                stage_bytes=17,
                published_path="cache/key",
                published_identity=IDENTITY,
                published_bytes=19,
                published_pin_reason="stable native PA family",
            )
            second = self._handoff(
                root,
                stage_path="staging/prepared",
                stage_owner="publisher",
                stage_bytes=17,
                published_path="cache/key",
                published_identity=IDENTITY,
                published_bytes=19,
                published_pin_reason="stable native PA family",
            )

            self.assertEqual(first, second)
            self.assertTrue(second["published"]["pin"])
            self.assertEqual(
                second["published"]["pin_reason"], "stable native PA family"
            )

    def test_handoff_rejects_pin_policy_change_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            self._stage(root)
            self._handoff(
                root,
                stage_path="staging/prepared",
                stage_owner="publisher",
                stage_bytes=17,
                published_path="cache/key",
                published_identity=IDENTITY,
                published_bytes=19,
                published_pin_reason="stable native PA family",
            )

            with self.assertRaisesRegex(ValueError, "retry declaration"):
                self._handoff(
                    root,
                    stage_path="staging/prepared",
                    stage_owner="publisher",
                    stage_bytes=17,
                    published_path="cache/key",
                    published_identity=IDENTITY,
                    published_bytes=19,
                )

    def test_handoff_fails_closed_on_stage_or_landed_key_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            self._stage(root)
            with self.assertRaisesRegex(ValueError, "must be landed"):
                self._handoff(
                    root,
                    stage_path="staging/prepared",
                    stage_owner="publisher",
                    stage_bytes=17,
                    published_path="cache/key",
                    published_identity=IDENTITY,
                    published_bytes=17,
                )
            (root / "cache" / "key").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "exactly match"):
                self._handoff(
                    root,
                    stage_path="staging/prepared",
                    stage_owner="other",
                    stage_bytes=17,
                    published_path="cache/key",
                    published_identity=IDENTITY,
                    published_bytes=17,
                )
            with self.assertRaisesRegex(ValueError, "exactly match"):
                self._handoff(
                    root,
                    stage_path="staging/prepared",
                    stage_owner="publisher",
                    stage_bytes=18,
                    published_path="cache/key",
                    published_identity=IDENTITY,
                    published_bytes=17,
                )

    def test_handoff_rejects_wrong_consumer_and_competing_key_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            self._stage(root, consumer="cache/other")
            with self.assertRaisesRegex(ValueError, "exactly match"):
                self._handoff(
                    root,
                    stage_path="staging/prepared",
                    stage_owner="publisher",
                    stage_bytes=17,
                    published_path="cache/key",
                    published_identity=IDENTITY,
                    published_bytes=17,
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[{
                    "path": "cache/key",
                    "class": "published_cache",
                    "bytes": 17,
                    "status": "ready",
                    "pin": False,
                    "identity": "b" * 64,
                    "manager": capacity_ledger.PA_CACHE_MANAGER,
                    **PUBLISHED_DUTIES,
                }],
            )
            self._stage(root)
            with self.assertRaisesRegex(ValueError, "conflicts"):
                self._handoff(
                    root,
                    stage_path="staging/prepared",
                    stage_owner="publisher",
                    stage_bytes=17,
                    published_path="cache/key",
                    published_identity=IDENTITY,
                    published_bytes=17,
                )


if __name__ == "__main__":
    unittest.main()
