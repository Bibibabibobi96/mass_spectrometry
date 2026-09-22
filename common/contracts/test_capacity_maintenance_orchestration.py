"""Behavior tests for the daily ledger-only maintenance orchestration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts import capacity_ledger
from common.contracts import reconcile_artifact_capacity as capacity
from common.contracts.capacity_protection import create_capacity_protection_lease


DEADLINE = "2026-10-22"


def _object(
    path: str, *, bytes_count: int, status: str = "ready", pin: bool = False,
    owner: str = "fixture-owner", object_class: str = "rebuildable_payload",
) -> dict:
    """Create one complete v3 lifecycle object for an isolated fixture."""

    result = {
        "path": path, "class": object_class, "bytes": bytes_count,
        "status": status, "pin": pin, "owner": owner,
        "retention_reason": "finite fixture retention", "review_deadline": DEADLINE,
        "retirement_route": "owner_managed_disposition",
    }
    if pin:
        result["pin_reason"] = "fixture protection"
    if status == "writing":
        result.update(
            recovery_reason="fixture incomplete write",
            recovery_task="fixture owner must recover or retire",
            recovery_evidence_paths=[path],
        )
    return result


class CapacityMaintenanceOrchestrationTests(unittest.TestCase):
    def test_plan_reports_all_governed_groups_and_owner_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            scratch = parent / "simulation_repo" / "scratch"
            generated = parent / "simulation_repo" / "generated"
            scratch.mkdir(parents=True)
            generated.mkdir()
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[
                    _object("retire", bytes_count=12, owner="owner-a"),
                    _object("writing", bytes_count=7, status="writing", owner="owner-b"),
                    _object("pinned", bytes_count=5, pin=True, owner="owner-c"),
                    _object("leased", bytes_count=3, owner="owner-d"),
                ],
                external_scopes=[
                    {"role": "repository_scratch", "path": str(scratch.resolve()), "bytes": 11},
                    {"role": "repository_generated", "path": str(generated.resolve()), "bytes": 13},
                ],
            )
            create_capacity_protection_lease(
                root, lease_id="mrtof-current", owner="mrtof", ttl_seconds=600,
                protected_paths=[root / "leased"], committed_new_bytes=17,
            )

            receipt = capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance",
            )

            summary = receipt["management_summary"]
            self.assertEqual([item["path"] for item in receipt["planned"]], [str(root / "retire")])
            self.assertEqual(summary["capacity_gap_bytes"], 51)
            self.assertEqual(summary["next_active_commitments"]["committed_new_bytes"], 17)
            self.assertEqual(
                summary["external_scope_groups"],
                [
                    {"role": "repository_generated", "path": str(generated.resolve()), "bytes": 13},
                    {"role": "repository_scratch", "path": str(scratch.resolve()), "bytes": 11},
                ],
            )
            actions = {(item["owner"], item["action"]) for item in summary["blocked_owner_actions"]}
            self.assertIn(("owner-b", "recover_or_disposition"), actions)
            self.assertIn(("owner-c", "review_pin_for_release"), actions)
            self.assertIn(("owner-d", "wait_for_or_release_protection_lease"), actions)
            leased = next(item for item in summary["blocked_owner_actions"] if item["owner"] == "owner-d")
            self.assertEqual(leased["protection_lease_ids"], ["mrtof-current"])
            self.assertEqual(sum(item["bytes"] for item in summary["governed_object_groups"]), 27)

    def test_apply_continues_after_one_target_failure_and_preserves_resume_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad").mkdir()
            (root / "bad" / "payload.bin").write_bytes(b"x" * 9)
            (root / "good").mkdir()
            (root / "good" / "payload.bin").write_bytes(b"y" * 7)
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[
                    _object("bad", bytes_count=10, owner="owner-bad"),
                    _object("good", bytes_count=7, owner="owner-good"),
                ],
            )
            receipt = capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance",
            )

            applied = capacity.apply(receipt)

            self.assertEqual(len(applied["failed"]), 1)
            self.assertIn("bad", applied["failed"][0]["path"])
            self.assertFalse((root / "good").exists())
            ledger = capacity_ledger.load_capacity_ledger(root)
            self.assertEqual(
                {item["path"]: item["status"] for item in ledger["objects"]},
                {"bad": "retirement_pending", "good": "retired"},
            )
            self.assertEqual(applied["management_summary_after_apply"]["resumable_retirement_count"], 1)


if __name__ == "__main__":
    unittest.main()
