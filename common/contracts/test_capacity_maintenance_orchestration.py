"""Behavior tests for the daily ledger-only maintenance orchestration."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

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
    def test_cli_preview_and_unleased_apply_never_run_mutations(self) -> None:
        mutators = (
            "activate_owner_dispositions", "_register_workspace_scratch_scope",
            "_resume_source_scratch_dispositions", "_reconcile_execution_alias_root",
        )
        for apply_requested in (False, True):
            with self.subTest(apply=apply_requested), ExitStack() as stack:
                mocks = [stack.enter_context(patch.object(capacity, name)) for name in mutators]
                planner = stack.enter_context(patch.object(capacity, "plan", return_value={}))
                stack.enter_context(patch.dict(os.environ, {}, clear=True))
                stack.enter_context(patch.object(sys, "argv", [
                    "capacity", "--artifact-root", "unused", "--execution-mode", "maintenance",
                    *(["--apply"] if apply_requested else []),
                ]))
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(redirect_stderr(io.StringIO()))
                if apply_requested:
                    with self.assertRaises(SystemExit):
                        capacity.main()
                    planner.assert_not_called()
                else:
                    capacity.main()
                    planner.assert_called_once()
                for mutation in mocks:
                    mutation.assert_not_called()

    def test_maintenance_reserves_peak_and_deletes_without_payload_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, size in (("large", 20), ("small", 10)):
                (root / name).mkdir()
                (root / name / "payload.pa0").write_bytes(b"x" * size)
            capacity_ledger.initialize_capacity_ledger(root, objects=[
                _object("large", bytes_count=20), _object("small", bytes_count=10),
                _object("active", bytes_count=80, pin=True),
            ])
            create_capacity_protection_lease(
                root, lease_id="next", owner="workflow", ttl_seconds=600,
                protected_paths=[root / "active"], committed_new_bytes=20,
            )
            with patch.object(capacity, "file_sha256", side_effect=AssertionError("payload hash")):
                receipt = capacity.plan(
                    root, target_bytes=100, minimum_free_bytes=0, execution_mode="maintenance",
                )
                self.assertEqual(receipt["planned_bytes"], 30)
                applied = capacity.apply(receipt)
            self.assertTrue(applied["satisfied_after_apply"])
            self.assertEqual(applied["removed_bytes"], 30)
            self.assertEqual(applied["measured_after_bytes"], 80)
            compact = capacity._compact_maintenance_output(applied)
            self.assertEqual(compact["owner_usage_summary"][0]["bytes"], 80)

    def test_apply_rechecks_commitments_added_after_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[
                _object("active", bytes_count=80, pin=True),
            ])
            receipt = capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0, execution_mode="maintenance",
            )
            self.assertTrue(receipt["satisfied"])
            create_capacity_protection_lease(
                root, lease_id="next", owner="workflow", ttl_seconds=600,
                protected_paths=[root / "active"], committed_new_bytes=30,
            )
            applied = capacity.apply(receipt)
            self.assertFalse(applied["satisfied_after_apply"])
            self.assertEqual(applied["management_summary_after_apply"]["capacity_gap_bytes"], 10)

    def test_unhandled_published_cache_is_not_reported_as_evictable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = _object("legacy", bytes_count=80, object_class="published_cache")
            cache["identity"] = "A" * 64
            capacity_ledger.initialize_capacity_ledger(root, objects=[cache])
            receipt = capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0, execution_mode="maintenance",
            )
            self.assertTrue(receipt["satisfied"])
            self.assertEqual(receipt["candidate_count"], 0)
            action = receipt["management_summary"]["blocked_owner_actions"][0]
            self.assertEqual(action["action"], "register_owner_retirement")
            self.assertEqual(action["reason"], "published_cache_manager_unavailable")

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
            self.assertEqual(summary["capacity_gap_bytes"], 68)
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

    def test_default_cli_output_is_bounded_aggregate_without_object_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[
                    _object(
                        f"historical/object-{index:04d}", bytes_count=1,
                        status="writing", owner="historical-owner",
                    )
                    for index in range(1000)
                ],
            )
            output = io.StringIO()
            with patch.object(
                sys, "argv", [
                    "reconcile_artifact_capacity", "--artifact-root", str(root),
                    "--execution-mode", "maintenance",
                ],
            ), redirect_stdout(output):
                capacity.main()

            rendered = output.getvalue()
            document = json.loads(rendered)
            self.assertLess(len(rendered), 5_000)
            self.assertNotIn("blocked_owner_actions", document)
            self.assertNotIn("management_summary", document)
            self.assertNotIn("object-0000", rendered)
            self.assertEqual(document["governed"], {"object_count": 1000, "bytes": 1000})
            self.assertEqual(document["owner_action_summary"], [{
                "owner": "historical-owner",
                "action": "recover_or_disposition",
                "reason": "writing_requires_owner_recovery",
                "object_count": 1000,
                "bytes": 1000,
            }])


if __name__ == "__main__":
    unittest.main()
