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
    def _cache(self, root: Path, role: str, key: str, *, age: float, published: bool = True) -> Path:
        entry = root / "projects" / "p" / "cache" / role / key
        entry.mkdir(parents=True)
        (entry / "payload.pa0").write_bytes(b"x" * 1024)
        if published:
            generation = entry / "generations" / "g"
            generation.mkdir(parents=True)
            (generation / "cache_manifest.json").write_text(
                json.dumps({"schema_version": 3, "cache_key": key, "generation_sha256": "g"}),
                encoding="utf-8",
            )
            (entry / "current_generation.json").write_text(json.dumps({"generation_relative_path": "generations/g"}), encoding="utf-8")
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

    def test_headroom_is_counted_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._cache(root, "role", "e" * 64, age=time.time() - 100)
            receipt = plan(root, target_bytes=2048, required_headroom_bytes=4096)
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["planned"][0]["path"], str(candidate))

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


if __name__ == "__main__":
    unittest.main()
