import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from common.contracts import capacity_ledger
from common.contracts.file_identity import file_sha256
from common.contracts.historical_source_scratch_retirement import apply, plan


def auth(path, owner, source, *, targets, consumers=None, protected_paths=None):
    path.write_text(json.dumps({
        "schema_version": 1,
        "role": "historical_source_scratch_retirement_authorization",
        "status": "approved", "owner": owner, "source_root": str(source.resolve()),
        "retirement_authorized": True, "retirement_targets": targets,
        "active_consumers": [] if consumers is None else consumers,
        "protected_paths": [] if protected_paths is None else protected_paths,
    }), encoding="utf-8")


class SourceScratchRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        parent = Path(self.temp.name)
        self.root = parent / "artifacts"; self.root.mkdir()
        self.source = parent / "simulation_repo" / "scratch"
        (self.source / "old-five-zone" / "nested").mkdir(parents=True)
        (self.source / "old-five-zone" / "nested" / "old.bin").write_bytes(b"old")
        (self.source / "current-accelerator").mkdir()
        (self.source / "current-accelerator" / "keep.bin").write_bytes(b"current")
        self.evidence = parent / "authorization.json"
        auth(self.evidence, "owner", self.source, targets=["old-five-zone"])
        capacity_ledger.initialize_capacity_ledger(self.root, objects=[], external_scopes=[
            {"role": "repository_scratch", "path": str(self.source.resolve()), "bytes": 10},
            {"role": "repository_generated", "path": str((parent / "simulation_repo" / "generated").resolve()), "bytes": 0},
        ])

    def tearDown(self):
        self.temp.cleanup()

    def disposition(self):
        return plan(self.root, source_root=self.source, owner="owner", evidence=self.evidence,
                    evidence_sha256=file_sha256(self.evidence))

    def test_only_exact_authorized_child_is_retired_and_scope_root_stays(self):
        disposition = self.disposition()
        self.assertEqual(disposition["targets"], ["old-five-zone"])
        self.assertEqual([x["path"] for x in disposition["files"]], ["old-five-zone/nested/old.bin"])
        self.assertEqual(disposition["bytes"], 3)
        self.assertEqual(disposition["external_scope_bytes_after"], 7)
        done = apply(disposition)
        self.assertEqual(done["status"], "complete")
        self.assertFalse((self.source / "old-five-zone").exists())
        self.assertTrue((self.source / "current-accelerator" / "keep.bin").exists())
        self.assertTrue(self.source.exists())
        self.assertEqual(capacity_ledger.load_capacity_ledger(self.root)["external_scopes"][0]["bytes"], 7)

    def test_exact_top_level_file_is_retired_without_touching_sibling(self):
        obsolete = self.source / "obsolete.json"
        obsolete.write_bytes(b"obsolete")
        auth(self.evidence, "owner", self.source, targets=["obsolete.json"])
        disposition = self.disposition()
        self.assertEqual(disposition["files"], [{
            "target": "obsolete.json", "path": "obsolete.json", "bytes": 8,
        }])
        done = apply(disposition)
        self.assertEqual(done["status"], "complete")
        self.assertFalse(obsolete.exists())
        self.assertTrue((self.source / "current-accelerator" / "keep.bin").exists())

    def test_requires_exact_normalized_and_nonoverlapping_authorized_targets(self):
        for targets, reason in [(["old-five-zone/.."], "normalized"),
                                (["old-five-zone", "old-five-zone/nested"], "overlap"),
                                ([], "retirement_targets")]:
            auth(self.evidence, "owner", self.source, targets=targets)
            with self.assertRaisesRegex(ValueError, reason):
                self.disposition()

    def test_rejects_consumers_and_protection(self):
        auth(self.evidence, "owner", self.source, targets=["old-five-zone"], consumers=["run-x"])
        with self.assertRaisesRegex(ValueError, "consumers"):
            self.disposition()
        auth(self.evidence, "owner", self.source, targets=["old-five-zone"], protected_paths=["old-five-zone"])
        with self.assertRaisesRegex(ValueError, "protects"):
            self.disposition()

    def test_rejects_symlink_in_target_inventory_without_os_symlink_privilege(self):
        original = Path.is_symlink

        def simulated_symlink(path):
            return path.name == "old.bin" or original(path)

        with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=simulated_symlink):
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                self.disposition()

    def test_pending_receipt_resumes_idempotently_without_touching_sibling(self):
        disposition = self.disposition()
        receipt = Path(disposition["receipt"]); receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({**disposition, "status": "pending", "removal_progress": [{
            "path": "old-five-zone/nested/old.bin", "outcome": "missing_at_resume"}]}), encoding="utf-8")
        (self.source / "old-five-zone" / "nested" / "old.bin").unlink()
        self.assertEqual(apply(disposition)["status"], "complete")
        self.assertEqual(apply(disposition)["status"], "complete")
        self.assertTrue((self.source / "current-accelerator" / "keep.bin").exists())

    def test_apply_rechecks_immutable_authorization_evidence(self):
        disposition = self.disposition()
        receipt = Path(disposition["receipt"]); receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({**disposition, "status": "pending", "removal_progress": []}), encoding="utf-8")
        auth(self.evidence, "owner", self.source, targets=["current-accelerator"])
        with self.assertRaisesRegex(ValueError, "identity"):
            apply(disposition)

    def test_large_payload_is_not_hashed_for_inventory_or_removal(self):
        disposition = self.disposition()
        self.assertNotIn("sha256", disposition["files"][0])
        with mock.patch(
            "common.contracts.historical_source_scratch_retirement.file_sha256",
            side_effect=lambda path: file_sha256(path),
        ) as digest:
            apply(disposition)
        self.assertEqual(digest.call_count, 1)


if __name__ == "__main__":
    unittest.main()
