"""Regression checks for evidence protection and audited retention failures."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts import artifact_retention as retention
from common.contracts.file_identity import file_sha256


class RetentionSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "runs" / "test"
        self.run.mkdir(parents=True)
        self.config = self.run / "run_config.json"
        self.config.write_text(json.dumps({
            "schema_version": 2,
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        }), encoding="utf-8")

    def test_canonical_evidence_survives_large_file_threshold(self) -> None:
        for name in ("particle_state.csv", "particle_events.csv", "metrics.json", "summary.json"):
            with self.subTest(name=name):
                self.assertEqual(retention.classify_file(Path(name), bytes_count=2**30), "required_evidence")

    def test_compressed_trajectory_and_pa_work_array_are_not_optional(self) -> None:
        for name, role in (("trajectory_samples.csv.gz", "dense_trajectory"), ("field.pa_", "solver_native_binary")):
            self.assertEqual(retention.classify_file(Path(name), bytes_count=1), role)
        self.assertEqual(retention.classify_file(Path("trajectory_metrics.csv.gz"), bytes_count=1), "required_evidence")

    def test_final_interrupted_manifest_blocks_direct_retention(self) -> None:
        (self.run / "run_manifest.json").write_text('{"status":"interrupted"}', encoding="utf-8")
        payload = self.run / "field.pa0"
        payload.write_bytes(b"retained")
        with self.assertRaisesRegex(ValueError, "terminal manifest"):
            retention.apply_retention(self.config)
        self.assertTrue(payload.exists())

    def test_checkpoint_allows_preterminal_retention(self) -> None:
        (self.run / "run_manifest.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
        payload = self.run / "field.pa0"
        payload.write_bytes(b"transient")
        action = json.loads(retention.apply_retention(self.config).read_text())
        self.assertEqual(action["status"], "complete")
        self.assertFalse(payload.exists())

    def test_unlink_failure_leaves_pending_identity_receipt(self) -> None:
        payload = self.run / "field.pa0"
        payload.write_bytes(b"transient")
        original_sha = file_sha256(payload)
        with patch.object(retention, "_unlink_rebuildable_file", side_effect=OSError("busy")):
            with self.assertRaisesRegex(OSError, "busy"):
                retention.apply_retention(self.config)
        action = json.loads((self.run / "retention_actions.json").read_text())
        self.assertEqual(action["status"], "pending")
        self.assertEqual(action["removed"][0]["sha256"], original_sha)
        self.assertEqual(action["removed_file_count"], 0)
        self.assertTrue(payload.exists())

    def test_prior_receipt_cannot_be_overwritten(self) -> None:
        retention.apply_retention(self.config)
        with self.assertRaisesRegex(ValueError, "already has"):
            retention.apply_retention(self.config)
