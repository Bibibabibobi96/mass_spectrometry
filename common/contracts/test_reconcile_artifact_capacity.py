from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch
from pathlib import Path

from common.contracts.capacity_protection import CapacityProtectionLeaseError, create_capacity_protection_lease
from common.contracts import reconcile_artifact_capacity as capacity
from common.contracts.reconcile_artifact_capacity import (
    _current_generation_pointers,
    _directory_bytes,
    apply,
    main,
    plan,
    snapshot_published_pa_cache_keys,
)


class ArtifactCapacityPlanTest(unittest.TestCase):
    def test_cli_watermarks_follow_policy_and_explicit_overrides(self) -> None:
        policy = capacity._capacity_policy()
        policy.update(target_gib=37, minimum_free_gib=11)
        for extra, expected in (([], (37, 11)),
                                (["--target-gib", "9", "--minimum-free-gib", "0"], (9, 0))):
            with self.subTest(extra=extra), patch.object(capacity, "_capacity_policy", return_value=policy), \
                    patch.object(capacity, "plan", return_value={"satisfied": True}) as planned, \
                    patch("sys.argv", ["capacity", "--artifact-root", ".", *extra]), \
                    redirect_stdout(io.StringIO()):
                main()
            self.assertEqual(planned.call_args.kwargs["target_bytes"], expected[0] * capacity.GIB)
            self.assertEqual(planned.call_args.kwargs["minimum_free_bytes"], expected[1] * capacity.GIB)

    def test_policy_rejects_invalid_watermarks(self) -> None:
        original = capacity._capacity_policy()
        for field, value in (("target_gib", 0), ("minimum_free_gib", -1),
                             ("target_gib", float("nan")), ("minimum_free_gib", True)):
            with self.subTest(field=field, value=value), \
                    patch.object(capacity, "_load_object", return_value={**original, field: value}), \
                    self.assertRaisesRegex(RuntimeError, field):
                capacity._capacity_policy()

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
                "reconcile_artifact_capacity", "--artifact-root", str(root),
                "--target-gib", "1", "--minimum-free-gib", "0",
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

    def test_cli_creates_and_deletes_named_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with patch("sys.argv", [
                "reconcile_artifact_capacity", "--artifact-root", temporary,
                "--create-protection-lease", "cli-run", "--lease-owner", "test",
                "--lease-ttl-seconds", "60", "--protect-cache-key", "a" * 64,
            ]), redirect_stdout(output):
                main()
            created = json.loads(output.getvalue())
            self.assertTrue(Path(created["path"]).is_file())

            output = io.StringIO()
            with patch("sys.argv", [
                "reconcile_artifact_capacity", "--artifact-root", temporary,
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
                "reconcile_artifact_capacity",
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
            "common.contracts.reconcile_artifact_capacity.os.scandir",
            side_effect=[entries, FileNotFoundError("temporary child removed")],
        ):
            self.assertEqual(_current_generation_pointers(root), [])

    def test_pa_snapshot_does_not_hide_permission_or_other_io_errors(self) -> None:
        root = Path("capacity-root").absolute()
        for error_type in (PermissionError, OSError):
            with self.subTest(error=error_type), patch(
                "common.contracts.reconcile_artifact_capacity.os.scandir",
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
            "common.contracts.reconcile_artifact_capacity.os.scandir",
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
                    "common.contracts.reconcile_artifact_capacity.os.scandir",
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
                        "common.contracts.reconcile_artifact_capacity.os.scandir",
                        side_effect=[entries, error_type("unreadable directory")],
                    ), self.assertRaises(error_type):
                        _directory_bytes(root)

    def test_measurement_does_not_hide_missing_root(self) -> None:
        with patch(
            "common.contracts.reconcile_artifact_capacity.os.scandir",
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
                "common.contracts.reconcile_artifact_capacity.shutil.disk_usage",
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
                "common.contracts.reconcile_artifact_capacity._directory_bytes",
                side_effect=AssertionError("full walk must not run"),
            ), patch(
                "common.contracts.reconcile_artifact_capacity._active_cache_keys",
                side_effect=AssertionError("manifest scan must not run"),
            ), patch(
                "common.contracts.reconcile_artifact_capacity.shutil.disk_usage",
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
                "common.contracts.reconcile_artifact_capacity._active_cache_keys",
                side_effect=AssertionError("manifest scan must not run"),
            ), patch(
                "common.contracts.reconcile_artifact_capacity._cache_candidates",
                side_effect=AssertionError("cache scan must not run"),
            ), patch(
                "common.contracts.reconcile_artifact_capacity._compact_candidates",
                side_effect=AssertionError("compact scan must not run"),
            ), patch(
                "common.contracts.reconcile_artifact_capacity.shutil.disk_usage",
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
