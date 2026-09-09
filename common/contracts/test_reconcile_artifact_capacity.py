from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, Mock, patch
from pathlib import Path

from common.contracts.reconcile_artifact_capacity import (
    _current_generation_pointers,
    _directory_bytes,
    apply,
    plan,
    snapshot_published_pa_cache_keys,
)


class ArtifactCapacityPlanTest(unittest.TestCase):
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
            receipt = plan(root, target_bytes=0)
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
            receipt = plan(root, target_bytes=0, staging_grace_seconds=0)
            self.assertEqual([item["path"] for item in receipt["planned"]], [str(l1), str(old_l2), str(new_l2)])
            self.assertNotIn(str(formal), [item["path"] for item in receipt["planned"]])

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
            receipt = plan(root, target_bytes=0, staging_grace_seconds=0)
            planned = receipt["planned"]
            self.assertEqual(
                [item["path"] for item in planned],
                [str(newer_disposable), str(older_important), str(old_unknown), str(new_unknown)],
            )
            self.assertEqual([item["deletion_priority"] for item in planned], [30, 90, 100, 100])

    def test_failed_and_interrupted_runs_are_first_and_ordered_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = time.time()
            older = self._run(root, "older", status="interrupted", age=now - 900)
            newer = self._run(root, "newer", status="failed", age=now - 100, manifest=False)
            successful = self._run(root, "successful", status="success", age=now - 1200)
            formal = self._run(root, "formal", status="failed", age=now - 1300, formal_eligible=True)
            cache = self._cache(root, "role", "a" * 64, age=now - 200)
            receipt = plan(root, target_bytes=0, staging_grace_seconds=0)
            planned = [Path(item["path"]) for item in receipt["planned"]]
            self.assertEqual(planned[:2], [older, newer])
            self.assertNotIn(successful, planned)
            self.assertNotIn(formal, planned)
            self.assertLess(receipt["planned"][0]["deletion_priority"], receipt["planned"][2]["deletion_priority"])
            self.assertIn(cache, planned)

    def test_archived_terminal_run_is_never_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archived = self._run(
                root / "projects" / "p" / "archive" / "migration",
                "failed", status="interrupted", age=time.time() - 1000,
            )
            receipt = plan(root, target_bytes=0)
            self.assertNotIn(str(archived), [item["path"] for item in receipt["planned"]])

    def test_any_live_status_keeps_a_run_out_of_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = self._run(root, "inconsistent-live", status="failed", age=time.time() - 1000)
            (run / "run_manifest.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
            receipt = plan(root, target_bytes=0)
            self.assertNotIn(str(run), [item["path"] for item in receipt["planned"]])

    def test_nonterminal_manifest_protects_referenced_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = "d" * 64
            protected = self._cache(root, "role", key, age=time.time() - 100)
            run = root / "projects" / "p" / "runs" / "live"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(json.dumps({"status": "running", "cache_key": key}), encoding="utf-8")
            receipt = plan(root, target_bytes=0)
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
                root, target_bytes=0, staging_grace_seconds=0,
                protected_cache_keys=snapshot["protected_cache_keys"],
            )
            self.assertNotIn(
                str(integration_cache), [item["path"] for item in receipt["planned"]]
            )

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
            receipt = plan(root, target_bytes=0)
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
            receipt = plan(root, target_bytes=0, staging_grace_seconds=0)
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
            receipt = plan(root, target_bytes=2048, required_headroom_bytes=4096)
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
            receipt = plan(root, target_bytes=10_000_000)
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
                receipt = plan(root, target_bytes=10_000_000)
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
            receipt = plan(root, target_bytes=0, staging_grace_seconds=0)
            self.assertIn(str(candidate), [item["path"] for item in receipt["planned"]])
            run = root / "projects" / "p" / "runs" / "newly-live"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text(
                json.dumps({"status": "running", "cache_key": key}), encoding="utf-8"
            )
            applied = apply(receipt)
            self.assertTrue(candidate.exists())
            self.assertEqual(applied["removed"], [])

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
            receipt = plan(root, target_bytes=1_000)
            self.assertEqual(receipt["measurement_mode"], "FULL_NO_RECONCILIATION")
            (root / "new_payload.bin").write_bytes(b"x" * 2_000)
            applied = apply(receipt)
            self.assertTrue(applied["applied"])
            self.assertFalse(applied["satisfied_after_apply"])
            self.assertIn("candidate_count", applied)


if __name__ == "__main__":
    unittest.main()
