from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from common.contracts import capacity_ledger
from common.contracts import reconcile_artifact_capacity as capacity
from common.contracts.capacity_protection import create_capacity_protection_lease


READY_DUTIES = {
    "owner": "fixture_owner",
    "retention_reason": "finite test fixture retention",
    "review_deadline": "2026-10-22",
    "retirement_route": "owner_managed_disposition",
}
WRITING_DUTIES = {
    **READY_DUTIES,
    "recovery_reason": "fixture interrupted write",
    "recovery_task": "fixture owner must recover or retire",
    "recovery_evidence_paths": ["incomplete"],
}


class DailyCapacityReconcileTest(unittest.TestCase):
    def test_loading_calibrated_ledger_does_not_resolve_payload_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "projects/p/runs/r1", "class": "light_evidence",
                "bytes": 1, "status": "ready", "pin": False,
                **READY_DUTIES,
            }])
            with patch.object(
                capacity_ledger, "capacity_object_path",
                side_effect=AssertionError("startup touched a payload path"),
            ):
                loaded = capacity_ledger.load_capacity_ledger(root)
            self.assertIsNotNone(loaded)

    def test_ledger_rejects_nested_ranges_even_when_names_sort_between_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            objects = [
                {"path": path, "class": "light_evidence", "bytes": 1,
                 "status": "ready", "pin": False, **READY_DUTIES}
                for path in ("a", "a-b", "a/c")
            ]
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=objects)

    def test_writing_recovery_responsibility_is_required_preserved_and_ready_forbids_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[{
                    "path": "incomplete", "class": "rebuildable_payload", "bytes": 1,
                    "status": "writing", "pin": False,
                }])
            document = capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "incomplete", "class": "rebuildable_payload", "bytes": 1,
                "status": "writing", "pin": False, "owner": "workflow-a",
                "recovery_reason": "run_manifest_not_terminal",
                "review_deadline": "2026-09-27",
                "retention_reason": "finite test fixture retention",
                "retirement_route": "owner_managed_disposition",
                "recovery_task": "workflow-a must recover or retire",
                "recovery_evidence_paths": ["incomplete"],
                "consumers": ["projects/p/runs/consumer"],
            }])
            self.assertEqual(document["objects"][0]["owner"], "workflow-a")
            self.assertEqual(document["objects"][0]["review_deadline"], "2026-09-27")
            self.assertEqual(
                document["objects"][0]["consumers"],
                ["projects/p/runs/consumer"],
            )
            with self.assertRaisesRegex(ValueError, "ready ledger objects cannot carry"):
                capacity_ledger.record_capacity_object(
                    root, path="ready", object_class="rebuildable_payload",
                    bytes_count=1, status="ready", owner="workflow-a",
                    retention_reason="fixture", recovery_reason="not_allowed",
                    review_deadline="2026-09-27", retirement_route="owner_managed_disposition",
                )
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[{
                    "path": "unknown", "class": "light_evidence", "bytes": 1,
                    "status": "ready", "pin": False, "arbitrary_extra": True,
                }], overwrite=True)
            ready = capacity_ledger.record_capacity_object(
                root, path="incomplete", object_class="light_evidence",
                bytes_count=1, status="ready", **READY_DUTIES,
            )
            self.assertTrue(capacity_ledger.RECOVERY_FIELDS.isdisjoint(ready))

    def test_policy_is_minimal_and_uses_exact_light_evidence_budget(self) -> None:
        policy = json.loads(capacity.POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(policy), {
            "schema_version", "role", "description", "target_gib",
            "minimum_free_gib", "light_evidence_budget_bytes",
            "startup_gate_target_seconds", "startup_gate_deadline_seconds",
            "eviction_order",
        })
        self.assertEqual(policy["light_evidence_budget_bytes"], 26_214_400)
        self.assertEqual(capacity._capacity_policy(), policy)

    def test_formal_policy_is_exactly_600_gib_and_legacy_v1_ledger_fails_closed(self) -> None:
        self.assertEqual(capacity._capacity_policy()["target_gib"], 600)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = {
                "schema_version": 1, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": 0, "objects": [],
            }
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir()
            ledger.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIsNone(capacity_ledger.load_capacity_ledger(root))

    def test_external_scope_bytes_contribute_to_startup_resident_projection_without_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            workspace = parent / "simulation_repo"
            scratch = workspace / "scratch"
            generated = workspace / "generated"
            scratch.mkdir(parents=True)
            generated.mkdir()
            scopes = [
                {"role": "repository_scratch", "path": str(scratch.resolve()), "bytes": 40},
                {"role": "repository_generated", "path": str(generated.resolve()), "bytes": 60},
            ]
            capacity_ledger.initialize_capacity_ledger(root, objects=[], external_scopes=scopes)
            create_capacity_protection_lease(
                root, lease_id="current", owner="test", ttl_seconds=60,
                protected_paths=[root / "future"], committed_new_bytes=1,
            )
            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=10_000)):
                receipt = capacity.plan(
                    root, target_bytes=100, minimum_free_bytes=0,
                    protected_paths=[root / "future"], capacity_protection_lease_id="current",
                )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["resident_bytes"], 100)
            self.assertEqual(receipt["projected_bytes"], 101)
            self.assertEqual(receipt["blocking_reason"], "TARGET_CAPACITY_EXCEEDED")

    def test_daily_module_has_no_legacy_imports(self) -> None:
        source = Path(capacity.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "legacy_capacity_backfill", "reconcile_interrupted_compact_runs",
            "solver_review_retirement", "artifact_retention", "verify_run_manifest",
        ):
            self.assertNotIn(forbidden, source)
        script = """
import sys
from common.contracts import reconcile_artifact_capacity
for name in (
    'common.contracts.legacy_capacity_backfill',
    'common.contracts.reconcile_interrupted_compact_runs',
    'common.contracts.solver_review_retirement',
    'common.contracts.artifact_retention',
    'common.contracts.verify_run_manifest',
):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2], text=True,
            capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_startup_uses_ledger_plus_all_commitments_and_current_scope_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = root / "inputs" / "current"
            other = root / "inputs" / "other"
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "resident", "class": "rebuildable_payload", "bytes": 100,
                "status": "ready", "pin": False,
                **READY_DUTIES,
            }])
            create_capacity_protection_lease(
                root, lease_id="current", owner="workflow", ttl_seconds=3600,
                protected_paths=[required], committed_new_bytes=40,
            )
            create_capacity_protection_lease(
                root, lease_id="other", owner="other", ttl_seconds=3600,
                protected_paths=[other], committed_new_bytes=10,
            )
            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=75)):
                receipt = capacity.plan(
                    root, target_bytes=150, minimum_free_bytes=25,
                    protected_paths=[required], execution_mode="startup",
                    capacity_protection_lease_id="current",
                )
            self.assertTrue(receipt["satisfied"])
            self.assertEqual(receipt["projected_bytes"], 150)
            self.assertEqual(receipt["required_free_bytes"], 75)
            self.assertEqual(receipt["current_lease_committed_new_bytes"], 40)
            self.assertEqual(receipt["other_leases_committed_new_bytes"], 10)
            self.assertEqual(receipt["total_active_lease_committed_new_bytes"], 50)

            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=10_000)):
                blocked = capacity.plan(
                    root, target_bytes=10_000, minimum_free_bytes=0,
                    protected_paths=[other], execution_mode="startup",
                    capacity_protection_lease_id="current",
                )
            self.assertFalse(blocked["satisfied"])
            self.assertEqual(blocked["blocking_reason"], "CURRENT_LEASE_SCOPE_INCOMPLETE")
            self.assertEqual(blocked["missing_current_lease_paths"], [str(other.resolve())])

    def test_startup_requires_lease_and_rejects_active_legacy_unknown_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            with self.assertRaisesRegex(ValueError, "requires capacity_protection_lease_id"):
                capacity.plan(root, target_bytes=1, minimum_free_bytes=0)
            create_capacity_protection_lease(
                root, lease_id="current", owner="workflow", ttl_seconds=3600,
                protected_paths=[root / "current"], committed_new_bytes=0,
            )
            create_capacity_protection_lease(
                root, lease_id="legacy", owner="legacy", ttl_seconds=3600,
                protected_paths=[root / "legacy"], committed_new_bytes=1,
            )
            legacy_path = root / "common" / "capacity_protection_leases" / "legacy.json"
            document = json.loads(legacy_path.read_text(encoding="utf-8"))
            document.pop("committed_new_bytes")
            legacy_path.write_text(json.dumps(document), encoding="utf-8")
            receipt = capacity.plan(
                root, target_bytes=1, minimum_free_bytes=0,
                capacity_protection_lease_id="current",
            )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["blocking_reason"], "ACTIVE_LEASE_COMMITMENT_UNKNOWN")
            self.assertEqual(receipt["active_legacy_unknown_commitment_count"], 1)

    def test_startup_reports_writing_recovery_and_blocks_overdue_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "active-run", "class": "rebuildable_payload", "bytes": 1,
                "status": "writing", "pin": False, "owner": "workflow-a",
                "recovery_reason": "run_manifest_not_terminal",
                "review_deadline": (date.today() - timedelta(days=1)).isoformat(),
                "retention_reason": "finite test fixture retention",
                "retirement_route": "owner_managed_disposition",
                "recovery_task": "workflow-a must recover or retire",
                "recovery_evidence_paths": ["active-run"],
            }])
            create_capacity_protection_lease(
                root, lease_id="current", owner="workflow-a", ttl_seconds=3600,
                protected_paths=[root / "active-run"], committed_new_bytes=0,
            )
            receipt = capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                protected_paths=[root / "active-run"],
                capacity_protection_lease_id="current",
            )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["blocking_reason"], "WRITING_RECOVERY_REVIEW_OVERDUE")
            self.assertEqual(receipt["writing_object_count"], 1)
            self.assertEqual(receipt["overdue_writing_object_count"], 1)
            self.assertEqual(receipt["overdue_writing_objects"][0]["owner"], "workflow-a")

    def test_normal_api_and_cli_do_not_accept_duplicate_budget_estimates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(TypeError):
                capacity.plan(
                    root, target_bytes=1, minimum_free_bytes=0,
                    maximum_new_artifact_bytes=1,
                )
            for option in (
                "--maximum-new-artifact-bytes", "--target-gib", "--minimum-free-gib",
            ):
                with self.subTest(option=option), patch.object(sys, "argv", [
                    "reconcile_artifact_capacity", "--artifact-root", str(root),
                    option, "1",
                ]):
                    with self.assertRaises(SystemExit) as raised:
                        capacity.main()
                    self.assertEqual(raised.exception.code, 2)

    def test_maintenance_reads_only_ready_unpinned_heavy_ledger_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[
                {
                    "path": "evidence", "class": "light_evidence", "bytes": 1,
                    "status": "ready", "pin": False,
                    **READY_DUTIES,
                },
                {
                    "path": "cache", "class": "published_cache", "bytes": 2,
                    "status": "ready", "pin": False, "identity": "a" * 64,
                    "manager": capacity_ledger.PA_CACHE_MANAGER,
                    "owner": capacity_ledger.PA_CACHE_MANAGER,
                    "retention_reason": "finite PA fixture retention",
                    "review_deadline": "2026-10-22",
                    "retirement_route": "pa_manager_disposition",
                },
                {
                    "path": "writing", "class": "rebuildable_payload", "bytes": 4,
                    "status": "writing", "pin": False, "owner": "test",
                    "recovery_reason": "fixture_incomplete",
                    "review_deadline": "2026-09-27",
                    "retention_reason": "finite test fixture retention",
                    "retirement_route": "owner_managed_disposition",
                    "recovery_task": "test must recover or retire",
                    "recovery_evidence_paths": ["writing"],
                },
                {
                    "path": "rebuildable", "class": "rebuildable_payload", "bytes": 3,
                    "status": "ready", "pin": False,
                    **READY_DUTIES,
                },
            ])
            receipt = capacity.plan(
                root, target_bytes=1, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            self.assertEqual(
                [item["class"] for item in receipt["planned"]],
                ["rebuildable_payload", "published_cache"],
            )
            self.assertEqual(receipt["candidate_count"], 2)


if __name__ == "__main__":
    unittest.main()
