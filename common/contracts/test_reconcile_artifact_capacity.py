from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from common.contracts.reconcile_artifact_capacity import apply, plan


class ArtifactCapacityPlanTest(unittest.TestCase):
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
