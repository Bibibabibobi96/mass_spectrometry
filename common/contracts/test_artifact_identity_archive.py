from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.artifact_identity_archive import (
    legacy_artifact_location,
    relocated_manifest_path,
    resolve_legacy_artifact_root,
    validate_identity_archive_manifest,
    validate_plan,
    validate_pruning_journal,
    verify_pruned_inventory,
)
from common.contracts.file_identity import file_sha256


CURRENT = "current_project"
LEGACY = "legacy_project"
ARCHIVE_ID = "20260728_000000__migration-snapshot__repo__legacy-project"


def _location(state: str) -> dict:
    location = {
        "schema_version": 1,
        "state": state,
        "archive_id": ARCHIVE_ID,
        "archive_root": f"artifacts/projects/{CURRENT}/archive/{ARCHIVE_ID}/legacy-project-root",
        "migration_manifest": f"artifacts/projects/{CURRENT}/archive/{ARCHIVE_ID}/identity_migration_manifest.json",
    }
    if state == "source_pending_relocation":
        location["source_root"] = f"artifacts/projects/{LEGACY}"
    return {"mapping_id": "rename", "project_id": LEGACY, "artifact_location": location}


def _plan(records: list[dict]) -> dict:
    prune = [record for record in records if record["disposition"] == "prune_after_verified_migration"]
    return {
        "schema_version": 2,
        "role": "artifact_identity_migration_manifest",
        "migration_id": ARCHIVE_ID,
        "status": "relocated_verified",
        "current_project_id": CURRENT,
        "legacy_project_id": LEGACY,
        "legacy_mapping_id": "rename",
        "source_root": LEGACY,
        "destination_root": f"{CURRENT}/archive/{ARCHIVE_ID}/legacy-project-root",
        "identity_anomalies": [],
        "inventory": {
            "file_count": len(records),
            "bytes": sum(record["bytes"] for record in records),
            "prune_candidate_file_count": len(prune),
            "prune_candidate_bytes": sum(record["bytes"] for record in prune),
            "identity_anomaly_count": 0,
            "identity_anomaly_file_count": 0,
        },
        "files": records,
    }


class ArtifactIdentityArchiveTests(unittest.TestCase):
    def test_location_contract_has_one_active_root(self) -> None:
        pending = legacy_artifact_location(_location("source_pending_relocation"), CURRENT)
        archived = legacy_artifact_location(_location("archived_verified"), CURRENT)
        self.assertEqual(pending["active_root"], f"artifacts/projects/{LEGACY}")
        self.assertTrue(str(archived["active_root"]).endswith("legacy-project-root"))

    def test_archived_root_requires_matching_frozen_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            mapping = _location("archived_verified")
            manifest = _plan([
                {
                    "path": "run_manifest.json",
                    "bytes": 2,
                    "sha256": "A" * 64,
                    "disposition": "retain",
                    "reason": None,
                }
            ])
            manifest_path = workspace / mapping["artifact_location"]["migration_manifest"]
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                resolve_legacy_artifact_root(workspace, mapping, CURRENT),
                workspace / mapping["artifact_location"]["archive_root"],
            )

    def test_plan_rejects_duplicate_and_lowercase_hashes(self) -> None:
        record = {
            "path": "a.json", "bytes": 1, "sha256": "a" * 64,
            "disposition": "retain", "reason": None,
        }
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_plan(_plan([record]))
        record["sha256"] = "A" * 64
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_plan(_plan([record, dict(record)]))

    def test_archive_wrapper_and_exact_prefix_mapping(self) -> None:
        plan = _plan([{
            "path": "a.json", "bytes": 1, "sha256": "A" * 64,
            "disposition": "retain", "reason": None,
        }])
        wrapper = {
            "schema_version": 1,
            "role": "artifact_identity_archive_manifest",
            "archive_id": ARCHIVE_ID,
            "project": CURRENT,
            "reason": "migration-snapshot",
            "recorded_at_utc": "2026-07-28T00:00:00+00:00",
            "source_layout": "retired-project-root",
            "replacement_layout": "current-project-archive",
            "legacy_project_id": LEGACY,
            "payload": "legacy-project-root",
            "identity_migration_manifest": "identity_migration_manifest.json",
            "deletion_performed": False,
        }
        validate_identity_archive_manifest(wrapper, plan)
        old = Path("C:/old/root")
        new = Path("C:/new/root")
        self.assertEqual(relocated_manifest_path(str(old / "runs/a.json"), old, new), new / "runs/a.json")
        with self.assertRaises(ValueError):
            relocated_manifest_path("C:/other/a.json", old, new)

    def test_completed_pruning_is_verified_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projects = Path(directory)
            payload = projects / CURRENT / "archive" / ARCHIVE_ID / "legacy-project-root"
            payload.mkdir(parents=True)
            retained = payload / "retained.json"
            retained.write_text("{}", encoding="utf-8")
            records = [
                {
                    "path": "retained.json", "bytes": 2, "sha256": file_sha256(retained),
                    "disposition": "retain", "reason": None,
                },
                {
                    "path": "scratch/model.pa0", "bytes": 100, "sha256": "B" * 64,
                    "disposition": "prune_after_verified_migration",
                    "reason": "rebuildable_solver_or_cad_binary",
                },
            ]
            plan = _plan(records)
            removed = [{
                "original_path": f"{LEGACY}/scratch/model.pa0",
                "archive_path": "legacy-project-root/scratch/model.pa0",
                "quarantine_path": ".prune-quarantine/scratch/model.pa0",
                "bytes": 100,
                "sha256": "B" * 64,
                "reason": "rebuildable_solver_or_cad_binary",
            }]
            journal = {
                "schema_version": 1,
                "role": "artifact_identity_pruning_journal",
                "archive_id": ARCHIVE_ID,
                "state": "complete",
                "removed_file_count": 1,
                "removed_bytes": 100,
                "removed": removed,
            }
            (payload.parent / "pruning_manifest.json").write_text(json.dumps(journal), encoding="utf-8")
            validate_pruning_journal(journal, plan)
            verify_pruned_inventory(plan, projects)


if __name__ == "__main__":
    unittest.main()
