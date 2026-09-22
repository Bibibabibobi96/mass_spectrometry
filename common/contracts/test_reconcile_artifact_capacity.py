from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch
from pathlib import Path

from common.contracts.capacity_protection import (
    CapacityProtectionLeaseError,
    create_capacity_protection_lease as _create_capacity_protection_lease,
    load_capacity_protection_leases,
    renew_capacity_protection_lease,
)
from common.contracts import capacity_ledger
from common.contracts import reconcile_artifact_capacity as normal_capacity
from common.contracts import legacy_capacity_backfill as capacity
from common.contracts.legacy_capacity_backfill import (
    _current_generation_pointers,
    _directory_bytes,
    apply,
    audit_checkpoint_terminalization,
    main,
    plan as _plan,
    snapshot_published_pa_cache_keys,
)


def plan(*args, **kwargs):
    """Legacy fixture helper: exhaustive behavior is explicit in tests only."""

    kwargs.setdefault("execution_mode", "legacy-backfill")
    return _plan(*args, **kwargs)


def create_capacity_protection_lease(root: Path, **kwargs):
    """Give lease-focused fixtures the calibrated ledger required in production."""

    if capacity_ledger.load_capacity_ledger(root) is None:
        capacity_ledger.initialize_capacity_ledger(root, objects=[])
    return _create_capacity_protection_lease(root, **kwargs)


class MaintenanceTargetCliTest(unittest.TestCase):
    def test_maintenance_reaches_target_with_large_payload_and_resumes_pending_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            objects = [
                {"path": "small/old", "bytes": 1},
                {"path": "large/new", "bytes": 100},
                {"path": "protected/largest", "bytes": 1000, "pin": True, "pin_reason": "active input"},
                {"path": "pending/tiny", "bytes": 1, "status": "retirement_pending"},
            ]
            capacity_ledger.initialize_capacity_ledger(root, objects=[
                {"class": "rebuildable_payload", "status": "ready", "pin": False, **item}
                for item in objects
            ])
            receipt = normal_capacity.plan(
                root, target_bytes=1002, minimum_free_bytes=0, execution_mode="maintenance",
            )
            self.assertTrue(receipt["satisfied"])
            self.assertEqual([Path(item["path"]).relative_to(root).as_posix() for item in receipt["planned"]],
                             ["pending/tiny", "large/new"])

    def test_target_changes_only_requested_maintenance_plan(self) -> None:
        policy = normal_capacity._capacity_policy()
        for arguments, expected in (
            (["--execution-mode", "maintenance", "--maintenance-target-gib", "600"], 600),
            (["--execution-mode", "maintenance"], policy["target_gib"]),
            ([], policy["target_gib"]),
        ):
            with self.subTest(arguments=arguments), patch.object(
                sys, "argv", ["capacity", "--artifact-root", "unused", *arguments]
            ), patch.object(normal_capacity, "plan", return_value={}) as planner, redirect_stdout(io.StringIO()):
                normal_capacity.main()
                self.assertEqual(planner.call_args.kwargs["target_bytes"], int(expected * normal_capacity.GIB))
                self.assertEqual(planner.call_args.kwargs["minimum_free_bytes"], int(policy["minimum_free_gib"] * normal_capacity.GIB))

    def test_invalid_target_rejected_before_plan_or_lease_mutation(self) -> None:
        policy = normal_capacity._capacity_policy()
        cases = [
            ["--maintenance-target-gib", "600"],
            ["--execution-mode", "maintenance", "--create-protection-lease", "test", "--maintenance-target-gib", "600"],
        ]
        cases.extend(
            ["--execution-mode", "maintenance", "--maintenance-target-gib", value]
            for value in (str(policy["target_gib"] + 1), "nan", "inf", "-inf", "0", "-1")
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), patch.object(
                sys, "argv", ["capacity", "--artifact-root", "unused", *arguments]
            ), patch.object(normal_capacity, "plan") as planner, patch.object(
                normal_capacity, "_lease_action"
            ) as lease_action, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                normal_capacity.main()
            self.assertEqual(raised.exception.code, 2)
            planner.assert_not_called()
            lease_action.assert_not_called()


class ArtifactCapacityPlanTest(unittest.TestCase):
    def test_capacity_ledger_requires_explicit_initialized_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialized = capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[{
                    "path": "reports/baseline.json",
                    "class": "light_evidence",
                    "bytes": 11,
                    "status": "ready",
                    "pin": True,
                    "pin_reason": "unique calibrated baseline",
                }],
            )
            self.assertTrue(initialized["complete"])
            self.assertEqual(initialized["resident_bytes"], 11)
            with self.assertRaises(FileExistsError):
                capacity_ledger.initialize_capacity_ledger(root, objects=[])
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(
                    root,
                    objects=[{
                        "path": "bad/object", "class": "legacy_payload",
                        "bytes": 1, "status": "ready", "pin": False,
                    }],
                    overwrite=True,
                )
            self.assertEqual(
                capacity_ledger.load_capacity_ledger(root)["resident_bytes"], 11,
            )

    def test_ledger_enforces_four_states_pin_reason_cache_identity_and_disjoint_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            with self.assertRaisesRegex(ValueError, "class/status"):
                capacity_ledger.record_capacity_object(
                    root, path="legacy", object_class="rebuildable_payload",
                    bytes_count=1, status="superseded",
                )
            with self.assertRaisesRegex(ValueError, "pin_reason"):
                capacity_ledger.record_capacity_object(
                    root, path="pinned", object_class="light_evidence",
                    bytes_count=1, pin=True,
                )
            with self.assertRaisesRegex(ValueError, "generation identity"):
                capacity_ledger.record_capacity_object(
                    root, path="cache/generation", object_class="published_cache",
                    bytes_count=1,
                )
            capacity_ledger.record_capacity_object(
                root, path="objects/parent", object_class="rebuildable_payload",
                bytes_count=1,
            )
            with self.assertRaisesRegex(ValueError, "ranges cannot overlap"):
                capacity_ledger.record_capacity_object(
                    root, path="objects/parent/child", object_class="light_evidence",
                    bytes_count=1,
                )
            with self.assertRaisesRegex(ValueError, "ranges cannot overlap"):
                capacity_ledger.record_capacity_object(
                    root, path="objects", object_class="light_evidence", bytes_count=1,
                )

    def test_ledger_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            link = root / "outside-link"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except OSError as exc:
                if os.name != "nt":
                    self.skipTest(f"host cannot create a test symlink: {exc}")
                created = subprocess.run(
                    ["cmd", "/d", "/c", "mklink", "/J", str(link), outside],
                    cwd=root, text=True, capture_output=True, check=False, timeout=30,
                )
                if created.returncode != 0:
                    self.skipTest(f"host cannot create a test junction: {created.stderr}")
            try:
                capacity_ledger.initialize_capacity_ledger(root, objects=[])
                with self.assertRaisesRegex(ValueError, "below artifact root"):
                    capacity_ledger.record_capacity_object(
                        root, path=link / "payload", object_class="rebuildable_payload",
                        bytes_count=1,
                    )
            finally:
                if link.is_symlink():
                    link.unlink()
                elif link.exists():
                    os.rmdir(link)

    def test_pending_query_and_lease_registration_fail_closed_without_valid_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "pending state is unknown"):
                capacity_ledger.pending_disposal_targets(root)
            with self.assertRaisesRegex(ValueError, "pending state is unknown"):
                _create_capacity_protection_lease(
                    root, lease_id="missing-ledger", owner="test", ttl_seconds=60,
                    protected_paths=[root / "payload"],
                )
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir(exist_ok=True)
            ledger.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pending state is unknown"):
                capacity_ledger.pending_disposal_targets(root)

    def test_maintenance_selects_only_ready_unpinned_heavy_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = root / "common" / "capacity_ledger.json"
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[
                    {
                        "path": "evidence/report", "class": "light_evidence",
                        "bytes": 1, "status": "ready", "pin": False,
                    },
                    {
                        "path": "runs/writing", "class": "rebuildable_payload",
                        "bytes": 2, "status": "writing", "pin": False,
                        "owner": "test", "recovery_reason": "fixture_incomplete",
                        "review_deadline": "2026-09-27",
                    },
                    {
                        "path": "cache/generation", "class": "published_cache",
                        "bytes": 3, "status": "ready", "pin": False,
                        "identity": "e" * 64,
                    },
                    {
                        "path": "runs/pinned", "class": "rebuildable_payload",
                        "bytes": 4, "status": "ready", "pin": True,
                        "pin_reason": "unique evidence",
                    },
                ],
            )
            receipt = plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance", capacity_ledger=ledger,
            )
            self.assertEqual(
                [item["path"] for item in receipt["planned"]],
                [str((root / "cache" / "generation").resolve())],
            )
            create_capacity_protection_lease(
                root, lease_id="consumer", owner="test", ttl_seconds=60,
                protected_paths=[root / "cache" / "generation"],
            )
            with self.assertRaisesRegex(ValueError, "not eligible"):
                capacity_ledger.retire_capacity_object(
                    root, path="cache/generation", bytes_removed=3,
                )
            protected_receipt = plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance", capacity_ledger=ledger,
            )
            self.assertEqual(protected_receipt["planned"], [])

    def test_startup_import_does_not_load_legacy_reconciliation(self) -> None:
        script = """
import sys
import tempfile
from pathlib import Path
from common.contracts import reconcile_artifact_capacity as capacity
with tempfile.TemporaryDirectory() as temporary:
    assert Path(temporary).is_dir()
assert 'common.contracts.reconcile_interrupted_compact_runs' not in sys.modules
assert 'common.contracts.legacy_capacity_backfill' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_startup_uses_ledger_and_lease_without_scanning_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "projects").mkdir()
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir(exist_ok=True)
            ledger.write_text(json.dumps({
                "schema_version": 2,
                "role": "artifact_capacity_ledger",
                "status": "calibrated",
                "complete": True,
                "artifact_root": str(root),
                "resident_bytes": 1000,
                "external_scopes": [],
                "objects": [{
                    "path": "projects/existing", "class": "light_evidence",
                    "bytes": 1000, "status": "ready", "pin": False,
                }],
            }), encoding="utf-8")
            create_capacity_protection_lease(
                root, lease_id="current", owner="test", ttl_seconds=3600,
                protected_paths=[root / "projects"], committed_new_bytes=100,
            )
            with patch.object(capacity, "_directory_bytes", side_effect=AssertionError("startup scanned")):
                receipt = plan(
                    root, target_bytes=2000, minimum_free_bytes=0,
                    maximum_new_artifact_bytes=100,
                    execution_mode="startup",
                    capacity_ledger=ledger,
                    capacity_protection_lease_id="current",
                )
            self.assertTrue(receipt["satisfied"])
            self.assertEqual(receipt["measurement_mode"], "STARTUP_LEDGER")
            self.assertFalse(receipt["candidate_discovery_performed"])

    def test_startup_warns_on_unrelated_overdue_writing_but_blocks_required_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "scratch/old", "class": "rebuildable_payload",
                "bytes": 1, "status": "writing", "pin": False,
                "owner": "old", "recovery_reason": "review",
                "review_deadline": "2000-01-01",
            }])
            required = root / "projects" / "current"
            create_capacity_protection_lease(
                root, lease_id="current", owner="test", ttl_seconds=3600,
                protected_paths=[required], committed_new_bytes=0,
            )
            warning = normal_capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                execution_mode="startup",
                protected_paths=[required], capacity_protection_lease_id="current",
            )
            self.assertTrue(warning["satisfied"])
            self.assertEqual(warning["overdue_writing_object_count"], 1)
            self.assertEqual(warning["blocking_overdue_writing_object_count"], 0)
            capacity_ledger.record_capacity_object(
                root, path=required, object_class="rebuildable_payload", bytes_count=1,
                status="writing", owner="current", recovery_reason="review",
                review_deadline="2000-01-01",
            )
            blocked = normal_capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                execution_mode="startup",
                protected_paths=[required], capacity_protection_lease_id="current",
            )
            self.assertFalse(blocked["satisfied"])
            self.assertEqual(blocked["blocking_reason"], "WRITING_RECOVERY_REVIEW_OVERDUE")

    def test_startup_fails_closed_without_trusted_ledger_or_current_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = plan(
                root, target_bytes=2000, minimum_free_bytes=0,
                maximum_new_artifact_bytes=100, execution_mode="startup",
            )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["blocking_reason"], "SAFETY_DECISION_UNAVAILABLE")
            self.assertFalse(receipt["candidate_discovery_performed"])

    def test_increased_commitment_survives_failed_startup_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            started = datetime.now(timezone.utc)
            create_capacity_protection_lease(
                root, lease_id="growing", owner="workflow", ttl_seconds=120,
                protected_paths=[root / "future"], committed_new_bytes=100,
                now=started,
            )
            renew_capacity_protection_lease(
                root, lease_id="growing", owner="workflow", ttl_seconds=300,
                committed_new_bytes=200,
                now=datetime.fromtimestamp(started.timestamp() + 60, timezone.utc),
            )
            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=150)):
                receipt = plan(
                    root, target_bytes=1000, minimum_free_bytes=0,
                    maximum_new_artifact_bytes=200, execution_mode="startup",
                    capacity_protection_lease_id="growing",
                )
            self.assertFalse(receipt["satisfied"])
            leases = load_capacity_protection_leases(
                root, now=datetime.fromtimestamp(started.timestamp() + 120, timezone.utc),
            )
            self.assertEqual(leases["committed_new_bytes"], 200)

    def test_lease_pending_check_reads_only_the_capacity_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "common").mkdir()
            (root / "common" / "capacity_ledger.json").write_text(json.dumps({
                "schema_version": 2,
                "role": "artifact_capacity_ledger",
                "status": "calibrated",
                "complete": True,
                "artifact_root": str(root),
                "resident_bytes": 10,
                "external_scopes": [],
                "objects": [{
                    "path": "projects/p/cache/key",
                    "class": "rebuildable_payload",
                    "bytes": 10,
                    "status": "retirement_pending",
                }],
            }), encoding="utf-8")
            target = root / "projects" / "p" / "cache" / "key"
            target.parent.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "disposal became pending"):
                create_capacity_protection_lease(
                    root, lease_id="pending", owner="test", ttl_seconds=60,
                    protected_paths=[target],
                )

    def test_maintenance_uses_ledger_and_applies_one_object_without_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "projects" / "p" / "runs" / "rebuildable"
            target.mkdir(parents=True)
            payload = target / "payload.pa0"
            payload.write_bytes(b"payload")
            payload_bytes = payload.stat().st_size
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir(exist_ok=True)
            ledger.write_text(json.dumps({
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": payload_bytes,
                "external_scopes": [],
                "objects": [{
                    "path": "projects/p/runs/rebuildable",
                    "class": "rebuildable_payload", "bytes": payload_bytes,
                    "status": "ready",
                }],
            }), encoding="utf-8")
            with patch.object(capacity, "_directory_bytes", side_effect=AssertionError("maintenance scanned")):
                receipt = plan(
                    root, target_bytes=1, minimum_free_bytes=0,
                    execution_mode="maintenance", capacity_ledger=ledger,
                )
                self.assertEqual(receipt["measurement_mode"], "LEDGER_MAINTENANCE")
                applied = apply(receipt)
            self.assertFalse(target.exists())
            self.assertEqual(applied["removed_bytes"], payload_bytes)

    def test_ledger_object_api_allows_only_three_classes_and_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir()
            ledger.write_text(json.dumps({
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": 0,
                "external_scopes": [], "objects": [],
            }), encoding="utf-8")
            self.assertEqual(
                capacity.record_capacity_object(
                    root, path="evidence/report.json", object_class="light_evidence",
                    bytes_count=10,
                )["class"],
                "light_evidence",
            )
            capacity.record_capacity_object(
                root, path="cache/key", object_class="published_cache", bytes_count=20,
                identity="a" * 64,
            )
            capacity.record_capacity_object(
                root, path="runs/old", object_class="rebuildable_payload", bytes_count=30,
                status="ready", pin=True, pin_reason="unique scientific evidence",
            )
            with self.assertRaises(ValueError):
                capacity.record_capacity_object(
                    root, path="runs/bad", object_class="solver_review", bytes_count=1,
                )
            with self.assertRaises(ValueError):
                capacity.record_capacity_object(
                    root, path="runs/pending", object_class="rebuildable_payload",
                    bytes_count=1, status="retirement_pending",
                )
            with self.assertRaises(ValueError):
                capacity.retire_capacity_object(root, path="runs/old", bytes_removed=30)

    def test_ledger_retirement_updates_resident_bytes_without_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger_path = root / "common" / "capacity_ledger.json"
            ledger_path.parent.mkdir()
            ledger_path.write_text(json.dumps({
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": 0,
                "external_scopes": [], "objects": [],
            }), encoding="utf-8")
            capacity.record_capacity_object(
                root, path="runs/old", object_class="rebuildable_payload",
                bytes_count=30, status="ready",
            )
            with self.assertRaisesRegex(ValueError, "one complete object"):
                capacity.retire_capacity_object(
                    root, path="runs/old", bytes_removed=20,
                )
            with patch.object(capacity, "_directory_bytes", side_effect=AssertionError("ledger scanned")):
                entry = capacity.retire_capacity_object(
                    root, path="runs/old", bytes_removed=30,
                )
            self.assertEqual(entry["status"], "retired")
            self.assertEqual(entry["bytes"], 30)
            ledger = json.loads(ledger_path.read_text())
            self.assertEqual(ledger["resident_bytes"], 0)

    def test_touch_updates_only_ready_cache_last_used_time_monotonically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(
                root,
                objects=[{
                    "path": "cache/generation", "class": "published_cache",
                    "bytes": 7, "status": "ready", "pin": False,
                    "identity": "f" * 64,
                }, {
                    "path": "runs/payload", "class": "rebuildable_payload",
                    "bytes": 3, "status": "ready", "pin": False,
                }],
            )
            touched = capacity_ledger.touch_capacity_object(
                root, path="cache/generation", when_epoch=100.5,
            )
            self.assertEqual(touched["last_used_epoch"], 100.5)
            self.assertEqual(touched["bytes"], 7)
            self.assertEqual(touched["identity"], "f" * 64)
            self.assertEqual(touched["status"], "ready")
            with self.assertRaisesRegex(ValueError, "move backwards"):
                capacity_ledger.touch_capacity_object(
                    root, path="cache/generation", when_epoch=100,
                )
            with self.assertRaisesRegex(ValueError, "ready published_cache"):
                capacity_ledger.touch_capacity_object(
                    root, path="runs/payload", when_epoch=101,
                )
            with self.assertRaisesRegex(ValueError, "finite nonnegative"):
                capacity_ledger.touch_capacity_object(
                    root, path="cache/generation", when_epoch=float("nan"),
                )

    def test_pa_manager_approves_exact_unpinned_generation_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / ("a" * 64)
            target.mkdir(parents=True)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(),
                "class": "published_cache", "bytes": 7, "status": "ready",
                "pin": False, "identity": "b" * 64,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            files = [{"path": "payload.pa0", "bytes": 7, "sha256": "c" * 64}]
            kwargs = {
                "path": target, "expected_identity": "b" * 64,
                "expected_bytes": 7,
                "disposition_id": "d" * 64, "manifest_sha256": "e" * 64,
                "files": files, "commit_owner_retirement": lambda _: None,
            }
            requested = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance",
            )
            self.assertEqual(requested["planned"][0]["operation"], "request_retirement")
            approved = capacity_ledger.approve_published_cache_retirement(root, **kwargs)
            self.assertEqual(approved["class"], "rebuildable_payload")
            self.assertFalse(approved["pin"])
            self.assertIn(target.resolve(), capacity_ledger.pending_disposal_targets(root))
            self.assertEqual(
                capacity_ledger.approve_published_cache_retirement(root, **kwargs), approved,
            )
            with self.assertRaisesRegex(ValueError, "not eligible"):
                capacity_ledger.retire_capacity_object(root, path=target)
            normal = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance",
            )
            self.assertEqual(normal["planned"][0]["operation"], "retire_approved_disposition")
            with self.assertRaisesRegex(ValueError, "conflicts"):
                capacity_ledger.approve_published_cache_retirement(
                    root, **{**kwargs, "disposition_id": "f" * 64},
                )

    def test_maintenance_delegates_published_cache_then_executes_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_key = "a" * 64
            generation = "b" * 64
            target = root / "common" / "simion" / "pa_family_cache" / cache_key
            target.mkdir(parents=True)
            (target / "payload.pa0").write_bytes(b"payload")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(),
                "class": "published_cache", "bytes": 7, "status": "ready",
                "pin": False, "identity": generation,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            planned = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            self.assertEqual(planned["planned"][0]["operation"], "request_retirement")

            def approve(cache_root, actual_key, actual_generation):
                self.assertEqual(Path(cache_root), target.parent)
                self.assertEqual(actual_key, cache_key)
                self.assertEqual(actual_generation, generation)
                return capacity_ledger.approve_published_cache_retirement(
                    root, path=target, expected_identity=generation,
                    expected_bytes=7, disposition_id="d" * 64,
                    manifest_sha256="e" * 64,
                    files=[{"path": "payload.pa0", "bytes": 7, "sha256": "f" * 64}],
                    commit_owner_retirement=lambda _: None,
                )

            with patch(
                "common.simion.pa_family_cache.approve_pa_family_cache_retirement",
                side_effect=approve,
            ) as manager:
                applied = normal_capacity.apply(planned)
            manager.assert_called_once_with(target.parent, cache_key, generation)
            self.assertEqual(applied["removed_bytes"], 7)
            self.assertFalse(target.exists())
            entry = capacity_ledger.load_capacity_ledger(root)["objects"][0]
            self.assertEqual(entry["status"], "retired")
            self.assertIn("disposition", entry)

    def test_approved_recovers_target_removed_before_complete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / ("a" * 64)
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(), "class": "published_cache",
                "bytes": 3, "status": "ready", "pin": False, "identity": "b" * 64,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            capacity_ledger.approve_published_cache_retirement(
                root, path=target, expected_identity="b" * 64, expected_bytes=3,
                disposition_id="d" * 64, manifest_sha256="e" * 64,
                files=[{"path": "one.bin", "bytes": 3, "sha256": "1" * 64}],
                commit_owner_retirement=lambda _: None,
            )
            planned = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            original_write = normal_capacity.write_json_atomic
            interrupted = False

            def interrupt_complete(path, value):
                nonlocal interrupted
                if value.get("status") == "complete" and not interrupted:
                    interrupted = True
                    raise RuntimeError("injected approved complete-receipt interruption")
                return original_write(path, value)

            with patch.object(normal_capacity, "write_json_atomic", interrupt_complete):
                with self.assertRaisesRegex(RuntimeError, "approved complete-receipt"):
                    normal_capacity.apply(planned)
            self.assertFalse(target.exists())
            resumed = normal_capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            normal_capacity.apply(resumed)
            self.assertEqual(
                capacity_ledger.load_capacity_ledger(root)["objects"][0]["status"],
                "retired",
            )
            self.assertNotIn(target.resolve(), capacity_ledger.pending_disposal_targets(root))

    def test_approved_disposition_resumes_same_receipt_without_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / ("a" * 64)
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            (target / "two.bin").write_bytes(b"defg")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(), "class": "published_cache",
                "bytes": 7, "status": "ready", "pin": False, "identity": "b" * 64,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            capacity_ledger.approve_published_cache_retirement(
                root, path=target, expected_identity="b" * 64, expected_bytes=7,
                disposition_id="d" * 64,
                manifest_sha256="e" * 64,
                files=[
                    {"path": "one.bin", "bytes": 3, "sha256": "1" * 64},
                    {"path": "two.bin", "bytes": 4, "sha256": "2" * 64},
                ], commit_owner_retirement=lambda _: None,
            )
            receipt = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance",
            )
            original = normal_capacity._delete_approved_file
            calls = 0

            def interrupt_after_delete(*args, **kwargs):
                nonlocal calls
                original(*args, **kwargs)
                calls += 1
                if calls == 1:
                    raise RuntimeError("injected disposal interruption")

            with patch.object(normal_capacity, "_delete_approved_file", interrupt_after_delete):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    normal_capacity.apply(receipt)
            fixed = (
                root / "common" / "capacity_disposal_receipts"
                / f"ledger_disposition_{'d' * 64}.json"
            )
            self.assertTrue(fixed.is_file())
            resumed = normal_capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0, execution_mode="maintenance",
            )
            self.assertEqual(resumed["planned"][0]["must_resume"], True)
            with patch.object(normal_capacity, "file_sha256", side_effect=AssertionError("rehash")):
                normal_capacity.apply(resumed)
            self.assertFalse(target.exists())
            self.assertEqual(capacity_ledger.load_capacity_ledger(root)["objects"][0]["status"], "retired")

    def test_complete_disposition_receipt_resumes_only_ledger_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / ("a" * 64)
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(), "class": "published_cache",
                "bytes": 3, "status": "ready", "pin": False, "identity": "b" * 64,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            capacity_ledger.approve_published_cache_retirement(
                root, path=target, expected_identity="b" * 64, expected_bytes=3,
                disposition_id="d" * 64, manifest_sha256="e" * 64,
                files=[{"path": "one.bin", "bytes": 3, "sha256": "1" * 64}],
                commit_owner_retirement=lambda _: None,
            )
            planned = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            original_finalize = capacity_ledger.finalize_retirement
            calls = 0

            def fail_first_finalize(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("injected post-disposal finalize interruption")
                return original_finalize(*args, **kwargs)

            with patch.object(
                capacity_ledger, "finalize_retirement", fail_first_finalize,
            ):
                with self.assertRaisesRegex(RuntimeError, "post-disposal finalize"):
                    normal_capacity.apply(planned)
                self.assertFalse(target.exists())
                resumed = normal_capacity.plan(
                    root, target_bytes=100, minimum_free_bytes=0,
                    execution_mode="maintenance",
                )
                normal_capacity.apply(resumed)
            entry = capacity_ledger.load_capacity_ledger(root)["objects"][0]
            self.assertEqual(entry["status"], "retired")
            self.assertIn("disposition", entry)

    def test_approved_disposition_rejects_unlisted_extra_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / ("a" * 64)
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            (target / "extra.bin").write_bytes(b"")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(), "class": "published_cache",
                "bytes": 3, "status": "ready", "pin": False, "identity": "b" * 64,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            capacity_ledger.approve_published_cache_retirement(
                root, path=target, expected_identity="b" * 64, expected_bytes=3,
                disposition_id="d" * 64,
                manifest_sha256="e" * 64,
                files=[{"path": "one.bin", "bytes": 3, "sha256": "1" * 64}],
                commit_owner_retirement=lambda _: None,
            )
            receipt = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance",
            )
            with self.assertRaisesRegex(ValueError, "sealed file inventory"):
                normal_capacity.apply(receipt)

    def test_plain_rebuildable_retirement_resumes_one_fixed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "runs" / "rebuildable"
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            (target / "two.bin").write_bytes(b"defg")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(),
                "class": "rebuildable_payload", "bytes": 7,
                "status": "ready", "pin": False,
            }])
            planned = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            original = normal_capacity._delete_ledger_file
            calls = 0

            def interrupt_after_delete(*args, **kwargs):
                nonlocal calls
                original(*args, **kwargs)
                calls += 1
                if calls == 1:
                    raise RuntimeError("injected ordinary disposal interruption")

            with patch.object(normal_capacity, "_delete_ledger_file", interrupt_after_delete):
                with self.assertRaisesRegex(RuntimeError, "injected ordinary"):
                    normal_capacity.apply(planned)
            fixed_receipts = list(
                (root / normal_capacity.DISPOSAL_RECEIPT_DIRECTORY).glob("ledger_*.json")
            )
            self.assertEqual(len(fixed_receipts), 1)
            resumed = normal_capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            self.assertTrue(resumed["planned"][0]["must_resume"])
            with patch.object(
                normal_capacity, "_inventory_target",
                side_effect=AssertionError("ordinary retirement rescanned target"),
            ):
                normal_capacity.apply(resumed)
            self.assertFalse(target.exists())
            self.assertEqual(
                capacity_ledger.load_capacity_ledger(root)["objects"][0]["status"],
                "retired",
            )
            self.assertEqual(
                list((root / normal_capacity.DISPOSAL_RECEIPT_DIRECTORY).glob("ledger_*.json")),
                fixed_receipts,
            )

    def test_plain_rebuildable_retirement_uses_its_recorded_identity_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "runs" / "rebuildable"
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(),
                "class": "rebuildable_payload", "bytes": 3,
                "status": "ready", "pin": False,
            }])
            planned = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            original = normal_capacity.remove_recorded_files

            def checked_remove(root_path, records, **kwargs):
                self.assertTrue(kwargs.get("identities_verified"))
                return original(root_path, records, **kwargs)

            with patch.object(normal_capacity, "remove_recorded_files", checked_remove):
                normal_capacity.apply(planned)
            self.assertFalse(target.exists())

    def test_plain_recovers_target_removed_before_complete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "runs" / "rebuildable"
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"abc")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(),
                "class": "rebuildable_payload", "bytes": 3,
                "status": "ready", "pin": False,
            }])
            planned = normal_capacity.plan(
                root, target_bytes=0, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            original_write = normal_capacity.write_json_atomic
            interrupted = False

            def interrupt_complete(path, value):
                nonlocal interrupted
                if value.get("status") == "complete" and not interrupted:
                    interrupted = True
                    raise RuntimeError("injected plain complete-receipt interruption")
                return original_write(path, value)

            with patch.object(normal_capacity, "write_json_atomic", interrupt_complete):
                with self.assertRaisesRegex(RuntimeError, "plain complete-receipt"):
                    normal_capacity.apply(planned)
            self.assertFalse(target.exists())
            resumed = normal_capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            normal_capacity.apply(resumed)
            self.assertEqual(
                capacity_ledger.load_capacity_ledger(root)["objects"][0]["status"],
                "retired",
            )

    def test_direct_retire_rejects_manager_approved_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / ("a" * 64)
            target.mkdir(parents=True)
            (target / "one.bin").write_bytes(b"x")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(), "class": "published_cache",
                "bytes": 1, "status": "ready", "pin": False, "identity": "b" * 64,
                "manager": capacity_ledger.PA_CACHE_MANAGER,
            }])
            capacity_ledger.approve_published_cache_retirement(
                root, path=target, expected_identity="b" * 64, expected_bytes=1,
                disposition_id="d" * 64, manifest_sha256="e" * 64,
                files=[{"path": "one.bin", "bytes": 1, "sha256": "f" * 64}],
                commit_owner_retirement=lambda _: None,
            )
            with self.assertRaisesRegex(ValueError, "not eligible"):
                capacity_ledger.retire_capacity_object(root, path=target)

    def test_record_rejects_missing_or_uncalibrated_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "uncalibrated"):
                capacity.record_capacity_object(
                    root, path="cache/key", object_class="published_cache",
                    bytes_count=1, identity="b" * 64,
                )
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir(exist_ok=True)
            ledger.write_text(json.dumps({
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "artifact_root": str(root), "resident_bytes": 0,
                "external_scopes": [], "objects": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "uncalibrated"):
                capacity.record_capacity_object(
                    root, path="cache/key", object_class="published_cache",
                    bytes_count=1, identity="b" * 64,
                )

    def test_loader_rejects_duplicate_paths_and_resident_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir()
            base = {
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": 1,
                "external_scopes": [],
                "objects": [{
                    "path": "cache/key", "class": "published_cache", "bytes": 1,
                    "status": "ready", "pin": False, "identity": "c" * 64,
                }],
            }
            ledger.write_text(json.dumps({**base, "resident_bytes": 2}), encoding="utf-8")
            self.assertIsNone(capacity._load_capacity_ledger(root, ledger))
            duplicate = dict(base)
            duplicate["resident_bytes"] = 2
            duplicate["objects"] = [*base["objects"], dict(base["objects"][0])]
            ledger.write_text(json.dumps(duplicate), encoding="utf-8")
            self.assertIsNone(capacity._load_capacity_ledger(root, ledger))
            ledger.write_text(
                json.dumps({**base, "unclassified_bytes": 1}), encoding="utf-8",
            )
            self.assertIsNone(capacity._load_capacity_ledger(root, ledger))

    def test_ledger_removal_does_not_hold_decision_lock_during_io(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "cache" / "old"
            target.mkdir(parents=True)
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir()
            ledger.write_text(json.dumps({
                "schema_version": 2, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": 7,
                "external_scopes": [],
                "objects": [{
                    "path": "cache/old", "class": "rebuildable_payload", "bytes": 7,
                    "status": "ready", "pin": False,
                }],
            }), encoding="utf-8")

            def remove_without_global_lock(*args, **kwargs):
                with capacity.protection.capacity_decision_lock(root, timeout_seconds=0.01):
                    pass
                target.rmdir()
                return root / "receipt.json", 7

            with patch.object(capacity, "_remove_tree_with_receipt", side_effect=remove_without_global_lock):
                result = capacity._apply_ledger_object(root, {
                    "path": str(target), "operation": "retire_ledger_object",
                }, ledger)
            self.assertEqual(result["bytes"], 7)
            document = json.loads(ledger.read_text())
            self.assertEqual(document["objects"][0]["status"], "retired")
            self.assertEqual(document["resident_bytes"], 0)

    def test_legacy_cli_uses_shared_policy_and_rejects_capacity_overrides(self) -> None:
        shared = normal_capacity._capacity_policy()
        with patch.object(capacity, "plan", return_value={"satisfied": True}) as planned, \
                patch("sys.argv", ["capacity", "--artifact-root", "."]), \
                redirect_stdout(io.StringIO()):
            main()
        self.assertEqual(planned.call_args.kwargs["target_bytes"], shared["target_gib"] * capacity.GIB)
        self.assertEqual(planned.call_args.kwargs["minimum_free_bytes"], shared["minimum_free_gib"] * capacity.GIB)
        self.assertEqual(planned.call_args.kwargs["execution_mode"], "legacy-backfill")
        for option in ("--target-gib", "--minimum-free-gib"):
            with self.subTest(option=option), patch("sys.argv", [
                "capacity", "--artifact-root", ".", option, "999999",
            ]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(raised.exception.code, 2)

    def test_policy_rejects_invalid_watermarks(self) -> None:
        original = normal_capacity._capacity_policy()
        for field, value in (("target_gib", 0), ("minimum_free_gib", -1),
                             ("target_gib", float("nan")), ("minimum_free_gib", True)):
            with self.subTest(field=field, value=value), \
                    patch.object(normal_capacity, "_load_object", return_value={**original, field: value}), \
                    self.assertRaisesRegex(RuntimeError, field):
                normal_capacity._capacity_policy()

    def _success_build_run(self, root: Path, name: str) -> tuple[Path, Path, Path]:
        run = root / "projects" / "p" / "runs" / name
        run.mkdir(parents=True)
        config = run / "run_config.json"
        summary = run / "summary.json"
        recorded = run / "recorded.pa0"
        removable = run / "unrecorded.pa0"
        config.write_text(json.dumps({"schema_version": 2, "run_id": name}), encoding="utf-8")
        summary.write_text(json.dumps({"status": "success"}), encoding="utf-8")
        recorded.write_bytes(b"recorded")
        removable.write_bytes(b"rebuildable")
        def record(path: Path) -> dict[str, object]:
            return {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": capacity.file_sha256(path),
            }
        (run / "run_manifest.json").write_text(json.dumps({
            "status": "success", "recorded_at_utc": "2026-01-01T00:00:00Z",
            "run_config": record(config),
            "outputs": [record(summary), record(recorded)], "inputs": {},
        }), encoding="utf-8")
        return run, recorded, removable

    def _legacy_solver_review_build(
        self, root: Path, name: str
    ) -> tuple[Path, Path, Path]:
        run, recorded, removable = self._success_build_run(root, name)
        retention = {
            "policy_version": 1,
            "class": "solver_review",
            "reason": "Legacy solver review retained for exact authorized retirement.",
        }
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["artifact_retention"] = retention
        config_path.write_text(json.dumps(config), encoding="utf-8")
        summary_path = run / "summary.json"
        summary_path.write_text(
            json.dumps(capacity.LEGACY_INITIALIZATION_SUMMARY), encoding="utf-8"
        )
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifact_retention"] = retention
        manifest["run_config"] = {
            "path": config_path.name,
            "bytes": config_path.stat().st_size,
            "sha256": capacity.file_sha256(config_path),
        }
        manifest["outputs"] = [
            record
            for record in manifest["outputs"]
            if Path(record["path"]).name != summary_path.name
        ]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return run, recorded, removable

    def test_old_unmanaged_run_is_first_but_recent_or_actively_referenced_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = root / "projects" / "p" / "runs"
            old = runs / "old-unmanaged"
            old.mkdir(parents=True)
            (old / "payload.bin").write_bytes(b"old")
            referenced = runs / "referenced-unmanaged"
            referenced.mkdir()
            (referenced / "payload.bin").write_bytes(b"referenced")
            active = runs / "active"
            active.mkdir()
            (active / "run_manifest.json").write_text(
                json.dumps({"status": "checkpoint", "source_run_id": referenced.name}),
                encoding="utf-8",
            )
            policy = json.loads(Path(capacity.POLICY_PATH).read_text(encoding="utf-8"))
            policy["unmanaged_run_grace_seconds"] = 0
            with patch.object(capacity, "_capacity_policy", return_value=policy):
                receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            selected = [item for item in receipt["planned"] if item["reason"] == "old_unmanaged_unreferenced_run"]
            self.assertEqual([item["path"] for item in selected], [str(old)])
            self.assertEqual(selected[0]["deletion_priority"], policy["unmanaged_run_deletion_priority"])

    def test_success_build_payload_requires_explicit_run_and_excludes_manifest_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, recorded, removable = self._success_build_run(
                root, "20260101_000000__build__simion__rebuildable"
            )
            self.assertEqual(plan(root, minimum_free_bytes=0, target_bytes=0)["planned"], [])
            receipt = plan(
                root, minimum_free_bytes=0, target_bytes=0, rebuildable_success_build_runs=[run]
            )
            selected = next(
                item for item in receipt["planned"]
                if item["reason"] == "explicit_rebuildable_unreferenced_success_build_payload"
            )
            self.assertEqual(selected["bytes"], removable.stat().st_size)
            self.assertEqual([item["path"] for item in selected["removable"]], [removable.name])
            self.assertNotEqual(recorded, removable)

    def test_explicit_legacy_solver_review_build_allows_verified_checkpoint_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, recorded, removable = self._legacy_solver_review_build(
                root, "20260101_000000__build__simion__legacy-review"
            )
            manifest = json.loads(
                (run / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertNotIn(
                "summary.json",
                {Path(record["path"]).name for record in manifest["outputs"]},
            )

            receipt = plan(
                root,
                minimum_free_bytes=0,
                target_bytes=0,
                rebuildable_success_build_runs=[run],
            )

            selected = next(
                item
                for item in receipt["planned"]
                if item["reason"]
                == "explicit_rebuildable_unreferenced_success_build_payload"
            )
            self.assertEqual(
                [item["path"] for item in selected["removable"]], [removable.name]
            )
            self.assertTrue(recorded.is_file())
            debt = receipt["checkpoint_terminalization_audit"]["findings"]
            self.assertEqual(debt[0]["status"], "terminal_manifest_summary_status_debt")
            self.assertEqual(debt[0]["manifest_status"], "success")
            self.assertEqual(debt[0]["summary_status"], "checkpoint")

    def test_legacy_checkpoint_requires_exact_initialization_summary_and_solver_review(self) -> None:
        cases = (
            "config_not_solver_review",
            "manifest_not_solver_review",
            "summary_extra_field",
            "summary_reason_changed",
            "summary_role_changed",
            "summary_schema_changed",
            "summary_running",
            "formal_manifest",
            "formal_config",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                run, _, _ = self._legacy_solver_review_build(
                    root, f"20260101_000000__build__simion__{case}"
                )
                config_path = run / "run_config.json"
                summary_path = run / "summary.json"
                manifest_path = run / "run_manifest.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if case == "config_not_solver_review":
                    config["artifact_retention"]["class"] = "compact"
                elif case == "manifest_not_solver_review":
                    manifest["artifact_retention"]["class"] = "compact"
                elif case.startswith("summary_"):
                    summary = dict(capacity.LEGACY_INITIALIZATION_SUMMARY)
                    if case == "summary_extra_field":
                        summary["unexpected"] = True
                    elif case == "summary_reason_changed":
                        summary["reason"] = f"{summary['reason']} "
                    elif case == "summary_role_changed":
                        summary["role"] = "run_package_checkpoint_summary"
                    elif case == "summary_schema_changed":
                        summary["schema_version"] = 2
                    elif case == "summary_running":
                        summary["status"] = "running"
                    summary_path.write_text(json.dumps(summary), encoding="utf-8")
                elif case == "formal_manifest":
                    manifest["formal_eligible"] = True
                elif case == "formal_config":
                    config["formal_gate_passed"] = True
                config_path.write_text(json.dumps(config), encoding="utf-8")
                manifest["run_config"] = {
                    "path": config_path.name,
                    "bytes": config_path.stat().st_size,
                    "sha256": capacity.file_sha256(config_path),
                }
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                receipt = plan(
                    root,
                    minimum_free_bytes=0,
                    target_bytes=0,
                    rebuildable_success_build_runs=[run],
                )

                self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_unmanaged_run_with_any_summary_is_not_treated_as_evidence_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "projects" / "p" / "runs" / "summary-only"
            run.mkdir(parents=True)
            (run / "summary.json").write_text(
                json.dumps({"status": "success"}), encoding="utf-8"
            )
            (run / "payload.bin").write_bytes(b"evidence")
            policy = json.loads(Path(capacity.POLICY_PATH).read_text(encoding="utf-8"))
            policy["unmanaged_run_grace_seconds"] = 0

            with patch.object(capacity, "_capacity_policy", return_value=policy):
                receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_run_enumeration_uses_only_direct_project_run_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct = root / "projects" / "p" / "runs" / "direct"
            direct.mkdir(parents=True)
            (direct / "summary.json").write_text(
                json.dumps({"status": "checkpoint"}), encoding="utf-8"
            )
            nested = direct / "results" / "runs" / "nested"
            nested.mkdir(parents=True)
            (nested / "summary.json").write_text(
                json.dumps({"status": "success"}), encoding="utf-8"
            )
            archived = root / "projects" / "p" / "archive" / "runs" / "archived"
            archived.mkdir(parents=True)
            (archived / "summary.json").write_text(
                json.dumps({"status": "failed"}), encoding="utf-8"
            )

            audit = audit_checkpoint_terminalization(root)

            self.assertEqual(audit["findings"], [])
            policy = capacity._capacity_policy()
            from common.contracts import reconcile_interrupted_compact_runs as compact

            with patch.object(
                compact,
                "inspect_run",
                return_value={"removable_bytes": 0},
            ) as inspected:
                capacity._compact_candidates(root, (), policy)
            self.assertEqual(
                [call.args[0] for call in inspected.call_args_list], [direct.absolute()]
            )

    def test_nested_and_archived_run_records_do_not_create_active_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "8" * 64
            cache = self._cache(root, "role", key, age=time.time() - 100)
            direct = root / "projects" / "p" / "runs" / "terminal"
            nested = direct / "results"
            nested.mkdir(parents=True)
            (direct / "run_manifest.json").write_text(
                json.dumps({"status": "success"}), encoding="utf-8"
            )
            (nested / "run_config.json").write_text(
                json.dumps({"input_cache_key": key}), encoding="utf-8"
            )
            archived = root / "projects" / "p" / "archive" / "runs" / "old"
            archived.mkdir(parents=True)
            (archived / "run_config.json").write_text(
                json.dumps({"input_cache_key": key}), encoding="utf-8"
            )

            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            self.assertIn(str(cache), [item["path"] for item in receipt["planned"]])
            self.assertNotIn(key, receipt["protected_cache_keys"])

    def test_nested_and_archived_runs_are_not_unmanaged_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct = root / "projects" / "p" / "runs" / "direct-unmanaged"
            direct.mkdir(parents=True)
            (direct / "payload.bin").write_bytes(b"direct")
            container = root / "projects" / "p" / "runs" / "container"
            container.mkdir()
            (container / "summary.json").write_text(
                json.dumps({"status": "checkpoint"}), encoding="utf-8"
            )
            nested = container / "results" / "runs" / "nested-unmanaged"
            nested.mkdir(parents=True)
            (nested / "payload.bin").write_bytes(b"nested")
            archived = root / "projects" / "p" / "archive" / "runs" / "archived"
            archived.mkdir(parents=True)
            (archived / "payload.bin").write_bytes(b"archived")
            policy = capacity._capacity_policy()
            policy["unmanaged_run_grace_seconds"] = 0

            with patch.object(capacity, "_capacity_policy", return_value=policy):
                receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            candidates = {
                item["path"]
                for item in receipt["planned"]
                if item["reason"] == "old_unmanaged_unreferenced_run"
            }
            self.assertEqual(candidates, {str(direct)})

    def test_explicit_success_nonbuild_run_remains_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _, _ = self._success_build_run(
                root, "20260101_000000__simulate__simion__scientific-result"
            )

            receipt = plan(
                root, minimum_free_bytes=0, target_bytes=0, rebuildable_success_build_runs=[run]
            )

            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_explicit_success_build_outside_registered_run_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _, _ = self._success_build_run(
                root / "staging", "20260101_000000__build__simion__unregistered"
            )

            receipt = plan(
                root,
                minimum_free_bytes=0,
                target_bytes=0,
                rebuildable_success_build_runs=[run],
            )

            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_active_run_reference_blocks_explicit_success_build_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _, _ = self._success_build_run(
                root, "20260101_000000__build__simion__in-use"
            )
            active = root / "projects" / "p" / "runs" / "active"
            active.mkdir()
            (active / "run_manifest.json").write_text(
                json.dumps({"status": "checkpoint", "source_run_id": run.name}),
                encoding="utf-8",
            )
            receipt = plan(
                root, minimum_free_bytes=0, target_bytes=0, rebuildable_success_build_runs=[run]
            )
            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_apply_preserves_receipts_for_unmanaged_run_and_success_build_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unmanaged = root / "projects" / "p" / "runs" / "unmanaged"
            unmanaged.mkdir(parents=True)
            (unmanaged / "payload.bin").write_bytes(b"unmanaged")
            run, recorded, removable = self._success_build_run(
                root, "20260101_000000__build__simion__retire"
            )
            policy = json.loads(Path(capacity.POLICY_PATH).read_text(encoding="utf-8"))
            policy["unmanaged_run_grace_seconds"] = 0
            with patch.object(capacity, "_capacity_policy", return_value=policy):
                receipt = plan(
                    root, minimum_free_bytes=0, target_bytes=0,
                    rebuildable_success_build_runs=[run],
                )
                applied = apply(receipt)
            self.assertFalse(unmanaged.exists())
            unmanaged_action = next(
                item for item in applied["removed"] if item["path"] == str(unmanaged)
            )
            disposal = json.loads(Path(unmanaged_action["disposal_receipt"]).read_text(encoding="utf-8"))
            self.assertEqual(disposal["status"], "complete")
            self.assertRegex(disposal["files"][0]["sha256"], r"^[0-9A-F]{64}$")
            self.assertTrue(recorded.exists())
            self.assertFalse(removable.exists())
            retirement = json.loads((run / "capacity_retirement_actions.json").read_text(encoding="utf-8"))
            self.assertEqual(retirement["status"], "complete")
            self.assertRegex(retirement["removed"][0]["sha256"], r"^[0-9A-F]{64}$")

    def test_multiple_owner_leases_union_cache_keys_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = self._cache(root, "role", "6" * 64, age=time.time() - 100)
            run = self._run(
                root, "protected-failure", status="failed", age=time.time() - 200
            )
            create_capacity_protection_lease(
                root, lease_id="owner-a", owner="run-a", ttl_seconds=3600,
                protected_cache_keys=["6" * 64],
            )
            create_capacity_protection_lease(
                root, lease_id="owner-b", owner="run-b", ttl_seconds=3600,
                protected_paths=[run],
            )

            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            planned = {item["path"] for item in receipt["planned"]}
            self.assertNotIn(str(cache), planned)
            self.assertNotIn(str(run), planned)
            self.assertIn("6" * 64, receipt["protected_cache_keys"])
            self.assertIn(str(run.resolve()), receipt["protected_paths"])
            self.assertEqual(
                [item["status"] for item in receipt["protection_lease_audit"]],
                ["active", "active"],
            )

    def test_expired_lease_is_ignored_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = self._cache(root, "role", "7" * 64, age=time.time() - 100)
            create_capacity_protection_lease(
                root, lease_id="expired", owner="dead-run", ttl_seconds=1,
                protected_cache_keys=["7" * 64],
                now=datetime(2000, 1, 1, tzinfo=timezone.utc),
            )

            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            self.assertIn(str(cache), [item["path"] for item in receipt["planned"]])
            self.assertEqual(
                receipt["protection_lease_audit"][0]["status"], "expired_ignored"
            )

    def test_active_lease_renews_atomically_and_can_release_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protected = root / "projects" / "p" / "runs" / "handoff"
            protected.mkdir(parents=True)
            started = datetime(2026, 1, 1, tzinfo=timezone.utc)
            created = create_capacity_protection_lease(
                root,
                lease_id="cross-step",
                owner="producer-consumer-chain",
                ttl_seconds=120,
                protected_cache_keys=["a" * 64],
                protected_paths=[protected],
                committed_new_bytes=100,
                now=started,
            )

            renewed = renew_capacity_protection_lease(
                root,
                lease_id="cross-step",
                owner="producer-consumer-chain",
                ttl_seconds=300,
                committed_new_bytes=40,
                now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            )

            self.assertTrue(renewed["renewed"])
            self.assertEqual(
                renewed["protected_cache_keys"], created["protected_cache_keys"]
            )
            self.assertEqual(renewed["protected_paths"], created["protected_paths"])
            self.assertEqual(renewed["created_at_utc"], created["created_at_utc"])
            self.assertEqual(renewed["expires_at_utc"], "2026-01-01T00:06:00Z")
            self.assertEqual(renewed["committed_new_bytes"], 40)
            self.assertFalse(renewed["bootstrap_renewal"])
            loaded = load_capacity_protection_leases(
                root, now=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
            )
            self.assertEqual(loaded["audit"][0]["status"], "active")
            self.assertEqual(loaded["protected_cache_keys"], {"a" * 64})

    def test_missing_ledger_allows_only_exact_scope_bootstrap_renewal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protected = root / "projects" / "p" / "runs" / "active"
            protected.mkdir(parents=True)
            started = datetime(2026, 1, 1, tzinfo=timezone.utc)
            create_capacity_protection_lease(
                root, lease_id="bootstrap", owner="same-owner", ttl_seconds=120,
                protected_paths=[protected], committed_new_bytes=100, now=started,
            )
            (root / "common" / "capacity_ledger.json").unlink()
            with self.assertRaisesRegex(ValueError, "cannot expand protection scope"):
                renew_capacity_protection_lease(
                    root, lease_id="bootstrap", owner="same-owner", ttl_seconds=300,
                    protected_paths=[root / "new-scope"],
                    now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                )
            for commitment in (99, 101):
                with self.subTest(commitment=commitment), self.assertRaisesRegex(
                    ValueError, "cannot change committed_new_bytes",
                ):
                    renew_capacity_protection_lease(
                        root, lease_id="bootstrap", owner="same-owner", ttl_seconds=300,
                        committed_new_bytes=commitment,
                        now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                    )
            renewed = renew_capacity_protection_lease(
                root, lease_id="bootstrap", owner="same-owner", ttl_seconds=300,
                protected_paths=[protected], committed_new_bytes=100,
                now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            )
            self.assertTrue(renewed["bootstrap_renewal"])
            self.assertEqual(renewed["renewal_mode"], "bootstrap_missing_capacity_ledger")
            self.assertFalse(renewed["scope_extended"])

    def test_bootstrap_renewal_does_not_accept_a_damaged_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = datetime(2026, 1, 1, tzinfo=timezone.utc)
            create_capacity_protection_lease(
                root, lease_id="damaged", owner="same-owner", ttl_seconds=120,
                protected_cache_keys=["a" * 64], now=started,
            )
            (root / "common" / "capacity_ledger.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pending state is unknown"):
                renew_capacity_protection_lease(
                    root, lease_id="damaged", owner="same-owner", ttl_seconds=300,
                    now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                )

    def test_lease_renewal_rejects_wrong_owner_and_expired_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = datetime(2026, 1, 1, tzinfo=timezone.utc)
            create_capacity_protection_lease(
                root, lease_id="owned", owner="chain", ttl_seconds=60,
                protected_cache_keys=["a" * 64], now=started,
            )
            with self.assertRaisesRegex(ValueError, "owner differs"):
                renew_capacity_protection_lease(
                    root, lease_id="owned", owner="other", ttl_seconds=60,
                    now=datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc),
                )
            with self.assertRaisesRegex(ValueError, "expired"):
                renew_capacity_protection_lease(
                    root, lease_id="owned", owner="chain", ttl_seconds=60,
                    now=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
                )

    def test_lease_renewal_cannot_shorten_existing_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = datetime(2026, 1, 1, tzinfo=timezone.utc)
            create_capacity_protection_lease(
                root, lease_id="long-lived", owner="chain", ttl_seconds=600,
                protected_cache_keys=["a" * 64], now=started,
            )

            with self.assertRaisesRegex(ValueError, "must extend"):
                renew_capacity_protection_lease(
                    root, lease_id="long-lived", owner="chain", ttl_seconds=60,
                    now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                )

    def test_malformed_active_lease_fails_closed_with_cli_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lease = create_capacity_protection_lease(
                root, lease_id="malformed", owner="run", ttl_seconds=3600,
                protected_cache_keys=["8" * 64],
            )
            path = Path(lease["path"])
            document = json.loads(path.read_text(encoding="utf-8"))
            document["unexpected"] = True
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(CapacityProtectionLeaseError) as raised:
                plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertEqual(raised.exception.audit["status"], "invalid")

            stderr = io.StringIO()
            with patch("sys.argv", [
                "legacy_capacity_backfill", "--artifact-root", str(root),
            ]), redirect_stderr(stderr), self.assertRaises(SystemExit) as exited:
                main()
            self.assertEqual(exited.exception.code, 2)
            self.assertIn("artifact_capacity_protection_lease_audit", stderr.getvalue())

    def test_pinned_cache_survives_unsatisfied_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = self._cache(root, "role", "9" * 64, age=time.time() - 100)
            create_capacity_protection_lease(
                root, lease_id="pin", owner="active-run", ttl_seconds=3600,
                protected_cache_keys=["9" * 64],
            )

            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["planned"], [])
            applied = apply(receipt)

            self.assertTrue(cache.exists())
            self.assertEqual(applied["removed"], [])
            self.assertFalse(applied["satisfied_after_apply"])

    def test_apply_refreshes_leases_created_after_the_initial_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = self._cache(root, "role", "b" * 64, age=time.time() - 100)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertIn(str(cache), [item["path"] for item in receipt["planned"]])
            create_capacity_protection_lease(
                root, lease_id="late-pin", owner="new-run", ttl_seconds=3600,
                protected_cache_keys=["b" * 64],
            )

            applied = apply(receipt)

            self.assertTrue(cache.exists())
            self.assertEqual(applied["removed"], [])

    def test_cli_creates_renews_and_deletes_named_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capacity_ledger.initialize_capacity_ledger(Path(temporary), objects=[])
            output = io.StringIO()
            with patch("sys.argv", [
                "legacy_capacity_backfill", "--artifact-root", temporary,
                "--create-protection-lease", "cli-run", "--lease-owner", "test",
                "--lease-ttl-seconds", "60", "--protect-cache-key", "a" * 64,
                "--committed-new-bytes", "100",
            ]), redirect_stdout(output):
                main()
            created = json.loads(output.getvalue())
            self.assertTrue(Path(created["path"]).is_file())
            self.assertEqual(created["committed_new_bytes"], 100)

            output = io.StringIO()
            with patch("sys.argv", [
                "legacy_capacity_backfill", "--artifact-root", temporary,
                "--renew-protection-lease", "cli-run", "--lease-owner", "test",
                "--lease-ttl-seconds", "120", "--protect-cache-key", "b" * 64,
                "--committed-new-bytes", "200",
            ]), redirect_stdout(output):
                main()
            renewed = json.loads(output.getvalue())
            self.assertTrue(renewed["renewed"])
            self.assertEqual(renewed["protected_cache_keys"], ["a" * 64, "b" * 64])
            self.assertEqual(renewed["committed_new_bytes"], 200)

            output = io.StringIO()
            with patch("sys.argv", [
                "legacy_capacity_backfill", "--artifact-root", temporary,
                "--delete-protection-lease", "cli-run",
            ]), redirect_stdout(output):
                main()
            deleted = json.loads(output.getvalue())
            self.assertTrue(deleted["deleted"])
            self.assertFalse(Path(created["path"]).exists())

    def test_cli_apply_requires_shared_host_execution_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "sys.argv",
            [
                "legacy_capacity_backfill",
                "--artifact-root",
                temporary,
                "--apply",
            ],
        ), patch.dict(
            os.environ,
            {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": ""},
        ), self.assertRaises(SystemExit) as raised:
            main()
        self.assertEqual(raised.exception.code, 2)

    def test_pa_snapshot_skips_child_removed_before_recursive_scandir(self) -> None:
        root = Path("capacity-root").absolute()
        child = Mock(path=str(root / "temporary"), name="temporary")
        child.is_symlink.return_value = False
        child.is_dir.return_value = True
        entries = MagicMock()
        entries.__enter__.return_value = iter([child])
        with patch(
            "common.contracts.legacy_capacity_backfill.os.scandir",
            side_effect=[entries, FileNotFoundError("temporary child removed")],
        ):
            self.assertEqual(_current_generation_pointers(root), [])

    def test_pa_snapshot_does_not_hide_permission_or_other_io_errors(self) -> None:
        root = Path("capacity-root").absolute()
        for error_type in (PermissionError, OSError):
            with self.subTest(error=error_type), patch(
                "common.contracts.legacy_capacity_backfill.os.scandir",
                side_effect=error_type("unreadable directory"),
            ), self.assertRaises(error_type):
                _current_generation_pointers(root)

    def test_cache_identity_reader_does_not_downgrade_permission_error(self) -> None:
        path = Path("cache") / "current_generation.json"
        for error_type in (PermissionError, OSError):
            with self.subTest(error=error_type), patch.object(
                Path, "read_text", side_effect=error_type("identity unreadable")
            ), self.assertRaises(error_type):
                capacity._load_cache_identity_object(path)

    def test_measurement_skips_child_removed_before_recursive_scandir(self) -> None:
        root = Path("capacity-root").absolute()
        child = Mock(path=str(root / "temporary"))
        child.is_symlink.return_value = False
        child.is_dir.return_value = True
        survivor = Mock()
        survivor.is_symlink.return_value = False
        survivor.is_dir.return_value = False
        survivor.is_file.return_value = True
        survivor.stat.return_value.st_size = 123
        entries = MagicMock()
        entries.__enter__.return_value = iter([child, survivor])
        with patch(
            "common.contracts.legacy_capacity_backfill.os.scandir",
            side_effect=[entries, FileNotFoundError("temporary child removed")],
        ):
            self.assertEqual(_directory_bytes(root), {root: 123})

    def test_measurement_skips_file_removed_during_metadata_lookup(self) -> None:
        root = Path("capacity-root").absolute()
        for method in ("is_symlink", "is_dir", "is_file", "stat"):
            with self.subTest(method=method):
                child = Mock()
                child.is_symlink.return_value = False
                child.is_dir.return_value = False
                child.is_file.return_value = True
                getattr(child, method).side_effect = FileNotFoundError("file removed")
                entries = MagicMock()
                entries.__enter__.return_value = iter([child])
                with patch(
                    "common.contracts.legacy_capacity_backfill.os.scandir",
                    return_value=entries,
                ):
                    self.assertEqual(_directory_bytes(root), {root: 0})

    def test_measurement_does_not_hide_permission_or_other_io_errors(self) -> None:
        root = Path("capacity-root").absolute()
        for error_type in (PermissionError, OSError):
            for operation in ("scandir", "stat"):
                with self.subTest(error=error_type, operation=operation):
                    child = Mock(path=str(root / "child"))
                    child.is_symlink.return_value = False
                    child.is_dir.return_value = operation == "scandir"
                    child.is_file.return_value = True
                    child.stat.side_effect = error_type("unreadable child")
                    entries = MagicMock()
                    entries.__enter__.return_value = iter([child])
                    with patch(
                        "common.contracts.legacy_capacity_backfill.os.scandir",
                        side_effect=[entries, error_type("unreadable directory")],
                    ), self.assertRaises(error_type):
                        _directory_bytes(root)

    def test_measurement_does_not_hide_missing_root(self) -> None:
        with patch(
            "common.contracts.legacy_capacity_backfill.os.scandir",
            side_effect=FileNotFoundError("artifact root missing"),
        ), self.assertRaises(FileNotFoundError):
            _directory_bytes(Path("capacity-root").absolute())

    def _run(self, root: Path, name: str, *, status: str, age: float,
             manifest: bool = True, formal_eligible: bool = False) -> Path:
        run = root / "projects" / "p" / "runs" / name
        run.mkdir(parents=True)
        (run / "payload.bin").write_bytes(b"x" * 1024)
        summary = {"status": status, "formal_eligible": formal_eligible}
        (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        if manifest:
            (run / "run_manifest.json").write_text(json.dumps(summary), encoding="utf-8")
        os.utime(run, (age, age))
        return run

    def _cache(self, root: Path, role: str, key: str, *, age: float, published: bool = True,
               manifest_role: str | None = None) -> Path:
        entry = root / "projects" / "p" / "cache" / role / key
        entry.mkdir(parents=True)
        (entry / "payload.pa0").write_bytes(b"x" * 1024)
        if published:
            generation = entry / "generations" / "g"
            generation.mkdir(parents=True)
            (generation / "cache_manifest.json").write_text(
                json.dumps({"schema_version": 3, "cache_key": key, "generation_sha256": "g",
                            "role": manifest_role or role}),
                encoding="utf-8",
            )
            (entry / "current_generation.json").write_text(json.dumps({"generation_relative_path": "generations/g"}), encoding="utf-8")
            # Publication time is the eviction-age authority for a selected
            # generation, rather than the cache directory's incidental mtime.
            os.utime(generation / "cache_manifest.json", (age, age))
        os.utime(entry, (age, age))
        return entry

    def _common_pa_family_cache(
        self, root: Path, key: str, *, age: float
    ) -> Path:
        entry = root / "common" / "simion" / "pa_family_cache" / key
        generation_name = "f" * 64
        generation = entry / "generations" / generation_name
        generation.mkdir(parents=True)
        (generation / "payload.pa0").write_bytes(b"x" * 1024)
        (generation / "cache_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "simion_pa_family_cache",
                    "cache_key": key,
                    "generation_sha256": generation_name,
                }
            ),
            encoding="utf-8",
        )
        (entry / "current_generation.json").write_text(
            json.dumps(
                {"cache_key": key, "generation_sha256": generation_name}
            ),
            encoding="utf-8",
        )
        os.utime(generation / "cache_manifest.json", (age, age))
        os.utime(entry, (age, age))
        return entry

    def test_common_pa_family_cache_is_an_l2_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = self._common_pa_family_cache(
                root, "9" * 64, age=time.time() - 100
            )
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            selected = next(
                item for item in receipt["planned"] if item["path"] == str(cache)
            )
            self.assertEqual(selected["level"], "L2")
            self.assertEqual(selected["cache_role"], "simion_pa_family_cache")

    def test_level_then_oldest_order_and_formal_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = time.time()
            old_l2 = self._cache(root, "role", "a" * 64, age=now - 300)
            new_l2 = self._cache(root, "role", "b" * 64, age=now - 100)
            l1 = self._cache(root, "role", "b-old", age=now - 500, published=False)
            formal = self._cache(root / "formal", "role", "c" * 64, age=now - 900)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertEqual([item["path"] for item in receipt["planned"]], [str(old_l2), str(new_l2)])
            self.assertNotIn(str(l1), [item["path"] for item in receipt["planned"]])
            self.assertNotIn(str(formal), [item["path"] for item in receipt["planned"]])

    def test_cache_precedes_compact_and_explicit_build_retirement(self) -> None:
        policy = capacity._capacity_policy()
        cache_priorities = [policy["default_l2_deletion_priority"],
                            *policy["l2_role_deletion_priorities"].values()]
        compact_priority = capacity._deletion_priority(level="L3", cache_role=None, policy=policy)
        self.assertLess(max(cache_priorities), compact_priority)
        self.assertLess(compact_priority, policy["explicit_success_build_payload_deletion_priority"])

    def test_policy_priority_precedes_age_and_same_priority_is_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = time.time()
            older_important = self._cache(
                root, "main", "1" * 64, age=now - 900,
                manifest_role="simion_single_flight_accelerator_main_pa_cache",
            )
            newer_disposable = self._cache(
                root, "collision", "2" * 64, age=now - 100,
                manifest_role="simion_single_flight_accelerator_entrance_zone_collision_pa_cache",
            )
            old_unknown = self._cache(root, "unknown", "3" * 64, age=now - 500)
            new_unknown = self._cache(root, "unknown", "4" * 64, age=now - 200)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            planned = receipt["planned"]
            self.assertEqual(
                [item["path"] for item in planned],
                [str(newer_disposable), str(older_important), str(old_unknown), str(new_unknown)],
            )
            self.assertEqual([item["deletion_priority"] for item in planned], [30, 90, 100, 100])

    def test_failed_and_interrupted_evidence_survives_capacity_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = time.time()
            older = self._run(root, "older", status="interrupted", age=now - 900)
            newer = self._run(root, "newer", status="failed", age=now - 100, manifest=False)
            successful = self._run(root, "successful", status="success", age=now - 1200)
            formal = self._run(root, "formal", status="failed", age=now - 1300, formal_eligible=True)
            cache = self._cache(root, "role", "a" * 64, age=now - 200)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            planned = [Path(item["path"]) for item in receipt["planned"]]
            self.assertNotIn(older, planned)
            self.assertNotIn(newer, planned)
            self.assertNotIn(successful, planned)
            self.assertNotIn(formal, planned)
            self.assertEqual(planned, [cache])
            applied = apply(receipt)
            self.assertFalse(applied["satisfied_after_apply"])
            self.assertTrue(older.is_dir())
            self.assertTrue(newer.is_dir())
            self.assertIn(cache, planned)

    def test_scratch_nested_cache_and_runs_are_not_cleanup_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "projects" / "p" / "scratch" / "recovery"
            cache = self._cache(scratch, "role", "c" * 64, age=time.time() - 1000)
            run = scratch / "runs" / "unmanaged"
            run.mkdir(parents=True)
            payload = run / "recovery_trace.csv"
            payload.write_bytes(b"unique recovery evidence")
            live_cache = self._cache(root, "role", "d" * 64, age=time.time() - 1000)
            policy = capacity._capacity_policy()
            policy["unmanaged_run_grace_seconds"] = 0
            with patch.object(capacity, "_capacity_policy", return_value=policy):
                receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
                self.assertEqual([item["path"] for item in receipt["planned"]], [str(live_cache)])
                result = apply(receipt)
            self.assertFalse(result["satisfied_after_apply"])
            self.assertTrue(cache.is_dir())
            self.assertEqual(payload.read_bytes(), b"unique recovery evidence")

    def test_archived_terminal_run_is_never_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archived = self._run(
                root / "projects" / "p" / "archive" / "migration",
                "failed", status="interrupted", age=time.time() - 1000,
            )
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertNotIn(str(archived), [item["path"] for item in receipt["planned"]])

    def test_any_live_status_keeps_a_run_out_of_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = self._run(root, "inconsistent-live", status="failed", age=time.time() - 1000)
            (run / "run_manifest.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_terminal_failure_summary_preserves_checkpoint_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = self._run(
                root, "checkpoint-then-failed", status="failed",
                age=time.time() - 1000,
            )
            (run / "run_manifest.json").write_text(
                json.dumps({"status": "checkpoint", "formal_eligible": False}),
                encoding="utf-8",
            )
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            consumer = root / "projects" / "p" / "runs" / "consumer"
            consumer.mkdir()
            (consumer / "run_config.json").write_text(
                json.dumps({"source_run_path": str(run)}), encoding="utf-8",
            )
            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])
            refreshed = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertNotIn(str(run), [item["path"] for item in refreshed["planned"]])

    def test_terminal_summary_without_terminal_manifest_stays_active_and_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "c" * 64
            cache = self._cache(root, "role", key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "summary-only-terminal"
            run.mkdir(parents=True)
            (run / "run_config.json").write_text(
                json.dumps({"input_cache_key": key}), encoding="utf-8"
            )
            (run / "summary.json").write_text(
                json.dumps({"status": "failed"}), encoding="utf-8"
            )

            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            self.assertNotIn(str(cache), [item["path"] for item in receipt["planned"]])
            audit = receipt["checkpoint_terminalization_audit"]
            self.assertEqual(audit["finding_count"], 1)
            self.assertEqual(audit["findings"][0]["manifest_status"], "missing")
            self.assertEqual(
                audit["findings"][0]["status"],
                "explicit_terminalization_required",
            )

            (run / "run_manifest.json").write_text(
                json.dumps({"status": "failed"}), encoding="utf-8"
            )
            terminal = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertIn(str(cache), [item["path"] for item in terminal["planned"]])
            self.assertEqual(
                terminal["checkpoint_terminalization_audit"]["finding_count"], 0
            )

    def test_checkpoint_terminalization_audit_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "projects" / "p" / "runs" / "legacy-checkpoint"
            run.mkdir(parents=True)
            manifest = run / "run_manifest.json"
            manifest.write_text(
                json.dumps({"status": "checkpoint"}), encoding="utf-8"
            )
            (run / "summary.json").write_text(
                json.dumps({"status": "success"}), encoding="utf-8"
            )

            report = audit_checkpoint_terminalization(root)

            self.assertEqual(report["finding_count"], 1)
            self.assertEqual(report["findings"][0]["manifest_status"], "checkpoint")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["status"],
                "checkpoint",
            )

    def test_checkpoint_terminalization_audit_distinguishes_invalid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "projects" / "p" / "runs" / "invalid-manifest"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text("{", encoding="utf-8")
            (run / "summary.json").write_text(
                json.dumps({"status": "failed"}), encoding="utf-8"
            )

            report = audit_checkpoint_terminalization(root)

            self.assertEqual(report["finding_count"], 1)
            self.assertEqual(
                report["findings"][0]["manifest_status"],
                "unreadable_or_invalid",
            )

    def test_no_reconciliation_report_still_includes_terminalization_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "projects" / "p" / "runs" / "legacy-checkpoint"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(
                json.dumps({"status": "checkpoint"}), encoding="utf-8"
            )
            (run / "summary.json").write_text(
                json.dumps({"status": "success"}), encoding="utf-8"
            )

            report = plan(
                root,
                target_bytes=1024,
                minimum_free_bytes=0,
                known_measured_bytes=0,
                maximum_new_artifact_bytes=0,
            )

            self.assertEqual(report["measurement_mode"], "SAFE_NO_RECONCILIATION")
            self.assertEqual(
                report["checkpoint_terminalization_audit"]["finding_count"], 1
            )

    def test_nonterminal_manifest_protects_referenced_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "d" * 64
            protected = self._cache(root, "role", key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "live"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(json.dumps({"status": "running", "cache_key": key}), encoding="utf-8")
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertNotIn(str(protected), [item["path"] for item in receipt["planned"]])

    def test_active_hashes_are_intersected_with_closed_cache_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_key = "d" * 64
            ordinary_file_sha = "e" * 64
            protected = self._cache(root, "role", real_key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "live"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "status": "checkpoint",
                        "cache_key": real_key,
                        "input_file_sha256": ordinary_file_sha,
                    }
                ),
                encoding="utf-8",
            )

            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)

            self.assertNotIn(str(protected), [item["path"] for item in receipt["planned"]])
            self.assertEqual(receipt["active_cache_key_count"], 1)
            self.assertIn(real_key, receipt["protected_cache_keys"])
            self.assertNotIn(ordinary_file_sha, receipt["protected_cache_keys"])

    def test_closed_pointer_outside_registered_cache_location_is_not_a_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "f" * 64
            entry = root / "projects" / "p" / "scratch" / "task" / "cache" / "role" / key
            generation = entry / "generations" / "g"
            generation.mkdir(parents=True)
            (generation / "cache_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "role": "role",
                        "cache_key": key,
                        "generation_sha256": "g",
                    }
                ),
                encoding="utf-8",
            )
            (entry / "current_generation.json").write_text(
                json.dumps({"generation_relative_path": "generations/g"}),
                encoding="utf-8",
            )

            self.assertNotIn(key, capacity._published_cache_keys(root))

    def test_startup_snapshot_protects_only_valid_published_pa_families(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = time.time()
            integration_key = "1" * 64
            integration_cache = self._cache(
                root, "integration-pa", integration_key, age=now - 300,
                manifest_role="simion_test_pa_cache",
            )
            common_key = "2" * 64
            common_entry = root / "projects" / "p" / "cache" / "common-pa" / common_key
            common_generation = common_entry / "generations" / ("a" * 64)
            common_generation.mkdir(parents=True)
            (common_generation / "cache_manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "role": "simion_pa_family_cache",
                "cache_key": common_key,
                "generation_sha256": "a" * 64,
            }), encoding="utf-8")
            (common_entry / "current_generation.json").write_text(json.dumps({
                "cache_key": common_key,
                "generation_sha256": "a" * 64,
            }), encoding="utf-8")
            self._cache(
                root, "not-pa", "3" * 64, age=now - 200,
                manifest_role="rebuildable_trajectory_cache",
            )
            self._cache(root, "staging", "b-unpublished", age=now - 500, published=False)
            damaged = self._cache(
                root, "damaged-pa", "4" * 64, age=now - 100,
                manifest_role="simion_damaged_pa_cache",
            )
            (damaged / "current_generation.json").write_text(
                json.dumps({"generation_relative_path": "generations/missing"}),
                encoding="utf-8",
            )

            snapshot = snapshot_published_pa_cache_keys(root)
            self.assertEqual(
                snapshot["protected_cache_keys"], [integration_key, common_key]
            )
            receipt = plan(
                root, minimum_free_bytes=0, target_bytes=0,
                protected_cache_keys=snapshot["protected_cache_keys"],
            )
            self.assertNotIn(
                str(integration_cache), [item["path"] for item in receipt["planned"]]
            )

    def test_active_run_config_protects_cache_not_named_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "7" * 64
            candidate = self._cache(root, "role", key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "preparing"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(json.dumps({"status": "checkpoint"}))
            (run / "run_config.json").write_text(json.dumps({"input_cache_key": key}))
            result = apply(plan(root, target_bytes=0, minimum_free_bytes=0))
            self.assertEqual(result["removed"], [])
            self.assertTrue(candidate.exists())

    def test_config_only_preparation_protects_itself_and_input_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "6" * 64
            cache = self._cache(root, "role", key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "preparing"
            run.mkdir(parents=True)
            config = run / "run_config.json"
            config.write_text(json.dumps({"input_cache_key": key}))
            policy = capacity._capacity_policy()
            policy["unmanaged_run_grace_seconds"] = 0
            with patch.object(capacity, "_capacity_policy", return_value=policy):
                result = apply(plan(root, target_bytes=0, minimum_free_bytes=0))
            self.assertEqual(result["removed"], [])
            self.assertTrue(cache.is_dir())
            self.assertTrue(config.is_file())

    def test_success_manifest_does_not_protect_reconstructible_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "e" * 64
            candidate = self._cache(root, "role", key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "finished"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(
                json.dumps({"status": "success", "cache_key": key}), encoding="utf-8"
            )
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertIn(str(candidate), [item["path"] for item in receipt["planned"]])

    def test_l2_cache_eviction_uses_last_successful_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = time.time()
            recently_consumed_old_cache = self._cache(root, "role", "a" * 64, age=now - 900)
            unused_newer_cache = self._cache(root, "role", "b" * 64, age=now - 100)
            run = root / "projects" / "p" / "runs" / "successful-consumer"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(
                json.dumps({
                    "status": "success",
                    "recorded_at_utc": "2099-09-03T12:00:00Z",
                    "cache_key": "a" * 64,
                }),
                encoding="utf-8",
            )
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            planned = receipt["planned"]
            self.assertEqual(
                [item["path"] for item in planned[:2]],
                [str(unused_newer_cache), str(recently_consumed_old_cache)],
            )
            self.assertEqual(planned[0]["eviction_time_basis"], "generation_publication_time")
            self.assertEqual(planned[1]["eviction_time_basis"], "last_successful_cache_consumption")
            self.assertEqual(planned[1]["last_successful_use_at_utc"], "2099-09-03T12:00:00Z")

    def test_headroom_is_counted_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "e" * 64, age=time.time() - 100)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=2048, required_headroom_bytes=4096)
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["planned"][0]["path"], str(candidate))

    def test_trajectory_csv_is_inclusive_in_capacity_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            states = (
                root / "projects" / "p" / "runs" / "completed" / "results"
                / "pre_pulse_time_series_states.csv"
            )
            states.parent.mkdir(parents=True)
            states.write_bytes(b"trajectory-state\n" * 64)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=10_000_000)
            self.assertEqual(receipt["measured_bytes"], states.stat().st_size)

    def test_directory_measurement_ignores_file_and_directory_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload.bin"
            payload.write_bytes(b"x" * 128)
            external = root.parent / f"capacity_external_{time.time_ns()}"
            external.mkdir()
            try:
                (external / "outside.bin").write_bytes(b"y" * 256)
                try:
                    (root / "payload-link.bin").symlink_to(payload)
                    (root / "external-link").symlink_to(external, target_is_directory=True)
                except OSError:
                    self.skipTest("symlink creation is unavailable on this host")
                receipt = plan(root, minimum_free_bytes=0, target_bytes=10_000_000)
                self.assertEqual(receipt["measured_bytes"], payload.stat().st_size)
            finally:
                shutil.rmtree(external, ignore_errors=True)

    def test_minimum_free_space_tightens_the_same_ordered_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "f" * 64, age=time.time() - 100)
            # The artifact watermark alone is satisfied, but the host volume
            # is 512 bytes short of its governed free-space floor.
            with patch(
                "common.contracts.legacy_capacity_backfill.shutil.disk_usage",
                return_value=shutil._ntuple_diskusage(10_000, 9_700, 300),
            ):
                receipt = plan(root, target_bytes=10_000, minimum_free_bytes=812)
            self.assertEqual(receipt["free_deficit_bytes"], 512)
            self.assertEqual(receipt["planned"][0]["path"], str(candidate))

    def test_apply_refreshes_plan_and_protects_a_newly_live_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "9" * 64
            candidate = self._cache(root, "role", key, age=time.time() - 100)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=0)
            self.assertIn(str(candidate), [item["path"] for item in receipt["planned"]])
            run = root / "projects" / "p" / "runs" / "newly-live"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(
                json.dumps({"status": "running", "cache_key": key}), encoding="utf-8"
            )
            applied = apply(receipt)
            self.assertTrue(candidate.exists())
            self.assertEqual(applied["removed"], [])

    def test_cache_disposal_records_file_identity_before_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "8" * 64, age=time.time() - 100)
            expected = capacity.file_sha256(candidate / "payload.pa0")
            original_remove = capacity.remove_recorded_files
            def checked_remove(root_path: Path, records: object, **kwargs: object) -> object:
                receipts = list((root / capacity.DISPOSAL_RECEIPT_DIRECTORY).glob("cache_*.json"))
                self.assertEqual(len(receipts), 1)
                record = json.loads(receipts[0].read_text())
                self.assertEqual(record["status"], "pending")
                self.assertIn(expected, [item["sha256"] for item in record["files"]])
                return original_remove(root_path, records, **kwargs)
            with patch.object(capacity, "remove_recorded_files", side_effect=checked_remove):
                applied = apply(plan(root, minimum_free_bytes=0, target_bytes=0))
            receipt = json.loads(Path(applied["removed"][0]["disposal_receipt"]).read_text())
            self.assertEqual(receipt["status"], "complete")
            self.assertFalse(candidate.exists())

    def test_cache_disposal_keeps_file_created_after_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "8" * 64, age=time.time() - 100)
            added = candidate / "new_scientific_input.csv"
            original_write = capacity._write_json_atomic
            def publish_and_add(path: Path, value: dict) -> None:
                original_write(path, value)
                if value.get("status") == "pending" and not added.exists():
                    added.write_bytes(b"new evidence")
            with patch.object(capacity, "_write_json_atomic", side_effect=publish_and_add), \
                    self.assertRaisesRegex(ValueError, "retained unlisted files"):
                apply(plan(root, minimum_free_bytes=0, target_bytes=0))
            self.assertEqual(added.read_bytes(), b"new evidence")
            receipts = list((root / capacity.DISPOSAL_RECEIPT_DIRECTORY).glob("cache_*.json"))
            receipt = json.loads(receipts[0].read_text())
            self.assertEqual(receipt["status"], "pending")
            self.assertNotIn(added.name, [record["path"] for record in receipt["files"]])

    def test_resume_pending_cache_disposal_removes_only_recorded_survivors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "7" * 64, age=time.time() - 100)
            receipt_path = (
                root / capacity.DISPOSAL_RECEIPT_DIRECTORY / "cache_interrupted.json"
            )
            files = capacity._file_disposal_records(
                candidate, sorted(path for path in candidate.rglob("*") if path.is_file())
            )
            # Reproduce an interrupted removal: one recorded file is already
            # gone, while another remains with its frozen identity.
            (candidate / files[0]["path"]).unlink()
            receipt_path.parent.mkdir(parents=True)
            capacity._write_json_atomic(
                receipt_path,
                {
                    "schema_version": 1,
                    "role": "artifact_capacity_disposal_receipt",
                    "status": "pending",
                    "reason": "inactive_reconstructible_published_cache",
                    "target_path": str(candidate),
                    "files": files,
                    "removed_bytes": sum(item["bytes"] for item in files),
                },
            )

            resumed = capacity.resume_pending_disposals(root)

            self.assertEqual(len(resumed), 1)
            self.assertFalse(candidate.exists())
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "complete")
            self.assertIn("resumed_at_utc", receipt)

    def test_resume_pending_cache_disposal_rejects_unlisted_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "6" * 64, age=time.time() - 100)
            files = capacity._file_disposal_records(
                candidate, sorted(path for path in candidate.rglob("*") if path.is_file())
            )
            receipt_path = (
                root / capacity.DISPOSAL_RECEIPT_DIRECTORY / "cache_interrupted.json"
            )
            receipt_path.parent.mkdir(parents=True)
            capacity._write_json_atomic(
                receipt_path,
                {
                    "schema_version": 1,
                    "role": "artifact_capacity_disposal_receipt",
                    "status": "pending",
                    "reason": "inactive_reconstructible_published_cache",
                    "target_path": str(candidate),
                    "files": files,
                    "removed_bytes": sum(item["bytes"] for item in files),
                },
            )
            added = candidate / "new_evidence.txt"
            added.write_text("preserve", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "retained unlisted files"):
                capacity.resume_pending_disposals(root)

            self.assertEqual(added.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(json.loads(receipt_path.read_text())["status"], "pending")

    def test_safe_launch_receipt_avoids_the_exhaustive_walk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "common.contracts.legacy_capacity_backfill._directory_bytes",
                side_effect=AssertionError("full walk must not run"),
            ), patch(
                "common.contracts.legacy_capacity_backfill._active_cache_keys",
                side_effect=AssertionError("manifest scan must not run"),
            ), patch(
                "common.contracts.legacy_capacity_backfill.shutil.disk_usage",
                return_value=shutil._ntuple_diskusage(10_000, 9_000, 9_000),
            ):
                receipt = plan(
                    root, target_bytes=1_000, minimum_free_bytes=500,
                    known_measured_bytes=700, maximum_new_artifact_bytes=200,
                )
                applied = apply(receipt)
            self.assertEqual(receipt["measurement_mode"], "SAFE_NO_RECONCILIATION")
            self.assertEqual(applied["removed"], [])
            self.assertTrue(applied["satisfied_after_apply"])

    def test_current_measurement_skips_reconciliation_then_rechecks_on_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "common.contracts.legacy_capacity_backfill._active_cache_keys",
                side_effect=AssertionError("manifest scan must not run"),
            ), patch(
                "common.contracts.legacy_capacity_backfill._cache_candidates",
                side_effect=AssertionError("cache scan must not run"),
            ), patch(
                "common.contracts.legacy_capacity_backfill._compact_candidates",
                side_effect=AssertionError("compact scan must not run"),
            ), patch(
                "common.contracts.legacy_capacity_backfill.shutil.disk_usage",
                return_value=shutil._ntuple_diskusage(10_000, 9_000, 9_000),
            ):
                receipt = plan(root, target_bytes=1_000, minimum_free_bytes=500)
                applied = apply(receipt)
            self.assertEqual(receipt["measurement_mode"], "FULL_NO_RECONCILIATION")
            self.assertEqual(applied["removed"], [])
            self.assertTrue(applied["satisfied_after_apply"])
            self.assertEqual(applied["measured_after_bytes"], 0)

    def test_apply_falls_back_to_ordered_planner_when_measurement_grows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = plan(root, minimum_free_bytes=0, target_bytes=1_000)
            self.assertEqual(receipt["measurement_mode"], "FULL_NO_RECONCILIATION")
            (root / "new_payload.bin").write_bytes(b"x" * 2_000)
            applied = apply(receipt)
            self.assertTrue(applied["applied"])
            self.assertFalse(applied["satisfied_after_apply"])
            self.assertIn("candidate_count", applied)


if __name__ == "__main__":
    unittest.main()
