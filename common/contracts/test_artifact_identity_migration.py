from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.artifact_identity_migration import (
    apply_migration,
    build_plan,
    legacy_artifact_location,
    prune_migration,
    relocated_manifest_path,
    resolve_legacy_artifact_root,
    rollback_migration,
    validate_plan,
    verify_inventory,
)
from common.contracts.machine_contracts import validate_schema
from common.contracts.verify_artifact_layout import verify_project


CURRENT = "rf_hexapole_ion_optics"
LEGACY = "rf_hexapole_ion_guide"
ARCHIVE_ID = "20260801_120000__migration-snapshot__repo__rf-hexapole-ion-guide"
ACTIVE_RUN = "20260722_120000__sim__python__active-evidence"
HISTORY_RUN = "20260722_120001__sim__python__history-evidence"
ANOMALY_RUN = "20260722_120002__sim__python__identity-anomaly"


class ArtifactIdentityMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary.name)
        self.repository = workspace / "simulation_repo"
        self.artifacts = workspace / "artifacts" / "projects"
        descriptor = self.repository / "projects" / CURRENT / "config" / "project.json"
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            json.dumps(
                {
                    "project_id": CURRENT,
                    "legacy_identities": [
                        {
                            "mapping_id": "hex-rename",
                            "project_id": LEGACY,
                            "migration_kind": "administrative_rename_only",
                            "artifact_root": f"artifacts/projects/{LEGACY}",
                            "artifact_access": "read_only",
                            "new_runs_allowed": False,
                            "verification_identity": "recorded_project_id",
                            "claim_policy": "preserve_original_status_and_claim_limits_no_promotion",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        project_docs = self.repository / "projects" / CURRENT / "docs"
        (project_docs / "history").mkdir(parents=True)
        (project_docs / "PROJECT.md").write_text(ACTIVE_RUN, encoding="utf-8")
        (project_docs / "history" / "old.md").write_text(HISTORY_RUN, encoding="utf-8")
        (self.artifacts / CURRENT).mkdir(parents=True)
        (self.artifacts / CURRENT / "00_README.txt").write_text(
            f"PROJECT: {CURRENT}\n", encoding="utf-8"
        )
        legacy = self.artifacts / LEGACY
        legacy.mkdir(parents=True)
        (legacy / "00_README.txt").write_text(f"PROJECT: {LEGACY}\n", encoding="utf-8")
        for run_id in (ACTIVE_RUN, HISTORY_RUN, ANOMALY_RUN):
            run = legacy / "runs" / run_id
            (run / "results").mkdir(parents=True)
            (run / "run_config.json").write_text(
                json.dumps({"run_id": run_id, "project": LEGACY}), encoding="utf-8"
            )
            (run / "summary.json").write_text(
                json.dumps({"status": "success"}), encoding="utf-8"
            )
            (run / "results" / "metrics.csv").write_text("x\n1\n", encoding="utf-8")
            (run / "results" / "model.mph").write_bytes(b"rebuildable-model")
            (run / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run_id,
                        "project": LEGACY,
                        "status": "success",
                        "outputs": [
                            {
                                "path": str(run / "results" / "model.mph"),
                                "bytes": len(b"rebuildable-model"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        anomaly_manifest_path = (
            legacy / "runs" / ANOMALY_RUN / "run_manifest.json"
        )
        anomaly_manifest = json.loads(
            anomaly_manifest_path.read_text(encoding="utf-8")
        )
        anomaly_manifest["schema_version"] = 2
        anomaly_manifest["outputs"][0]["sha256"] = "0" * 64
        retained_iob = anomaly_manifest_path.parent / "results" / "retained.iob"
        retained_iob.write_bytes(b"v2-retained-workbench")
        anomaly_manifest["outputs"].append(
            {
                "path": str(retained_iob),
                "bytes": retained_iob.stat().st_size,
                "retention_role": "lightweight_optional",
            }
        )
        anomaly_manifest_path.write_text(
            json.dumps(anomaly_manifest), encoding="utf-8"
        )
        scratch = legacy / "scratch" / "20260801_120000__repo__old-work"
        scratch.mkdir(parents=True)
        (scratch / "temporary.txt").write_text("temporary", encoding="utf-8")
        protected_binaries = (
            legacy / "archive" / "old-snapshot" / "model.mph",
            legacy / "formal" / "published-model.mph",
            legacy / "models" / "top-level-model.mph",
            legacy / "runs" / ACTIVE_RUN / "inputs" / "solver-input.iob",
            legacy
            / "runs"
            / ACTIVE_RUN
            / "frozen_input_snapshot"
            / "solver-input.pa0",
        )
        for path in protected_binaries:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"protected-evidence")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def plan(self) -> dict:
        return build_plan(self.repository, self.artifacts, CURRENT, ARCHIVE_ID)

    def test_plan_freezes_complete_inventory_and_reference_classes(self) -> None:
        plan = self.plan()
        validate_plan(plan)
        validate_schema(plan, "artifact_identity_migration.schema.json")
        records = {record["path"]: record for record in plan["files"]}
        active_model = records[f"runs/{ACTIVE_RUN}/results/model.mph"]
        history_model = records[f"runs/{HISTORY_RUN}/results/model.mph"]
        anomaly_model = records[f"runs/{ANOMALY_RUN}/results/model.mph"]
        retained_iob = records[f"runs/{ANOMALY_RUN}/results/retained.iob"]
        self.assertEqual(active_model["reference_classes"], ["active"])
        self.assertEqual(history_model["reference_classes"], ["history"])
        self.assertEqual(anomaly_model["disposition"], "retain")
        self.assertEqual(anomaly_model["reason"], "manifest_identity_anomaly")
        self.assertEqual(retained_iob["disposition"], "retain")
        self.assertEqual(plan["inventory"]["identity_anomaly_count"], 1)
        self.assertEqual(plan["inventory"]["identity_anomaly_file_count"], 1)
        self.assertEqual(plan["identity_anomalies"][0]["path"], anomaly_model["path"])
        self.assertEqual(
            plan["identity_anomalies"][0]["mismatches"], ["sha256_mismatch"]
        )
        self.assertEqual(active_model["disposition"], "prune_after_verified_migration")
        self.assertEqual(
            records[f"runs/{ACTIVE_RUN}/results/metrics.csv"]["disposition"], "retain"
        )
        for protected in (
            "archive/old-snapshot/model.mph",
            "formal/published-model.mph",
            "models/top-level-model.mph",
            f"runs/{ACTIVE_RUN}/inputs/solver-input.iob",
            f"runs/{ACTIVE_RUN}/frozen_input_snapshot/solver-input.pa0",
        ):
            self.assertEqual(records[protected]["disposition"], "retain", protected)
        self.assertGreater(plan["inventory"]["prune_candidate_bytes"], 0)

    def test_inventory_rejects_content_change(self) -> None:
        plan = self.plan()
        target = self.artifacts / LEGACY / "runs" / ACTIVE_RUN / "results" / "metrics.csv"
        target.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "byte count differs|SHA-256 differs"):
            verify_inventory(plan, self.artifacts, "source")

    def test_inventory_rejects_recorded_project_identity_change(self) -> None:
        plan = self.plan()
        manifest = self.artifacts / LEGACY / "runs" / ACTIVE_RUN / "run_manifest.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["project"] = CURRENT
        manifest.write_text(json.dumps(value), encoding="utf-8")
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "recorded project identity differs"):
            verify_inventory(plan, self.artifacts, "source")

    def test_relocated_manifest_path_requires_exact_old_prefix(self) -> None:
        old = self.artifacts / LEGACY
        new = self.artifacts / CURRENT / "archive" / ARCHIVE_ID / "legacy-project-root"
        result = relocated_manifest_path(str(old / "runs" / "a" / "summary.json"), old, new)
        self.assertEqual(
            result, new.resolve() / "runs" / "a" / "summary.json"
        )
        with self.assertRaises(ValueError):
            relocated_manifest_path(str(self.artifacts / "other" / "file.json"), old, new)

    def test_apply_preserves_bytes_and_rollback_restores_source(self) -> None:
        plan = self.plan()
        original_manifest = (
            self.artifacts / LEGACY / "runs" / ACTIVE_RUN / "run_manifest.json"
        ).read_bytes()
        archive = apply_migration(plan, self.artifacts)
        self.assertFalse((self.artifacts / LEGACY).exists())
        relocated = archive / "legacy-project-root" / "runs" / ACTIVE_RUN / "run_manifest.json"
        self.assertEqual(relocated.read_bytes(), original_manifest)
        verify_inventory(plan, self.artifacts, "destination")
        rollback_migration(plan, self.artifacts)
        self.assertEqual(
            (self.artifacts / LEGACY / "runs" / ACTIVE_RUN / "run_manifest.json").read_bytes(),
            original_manifest,
        )

    def test_rollback_restores_partial_pruning_quarantine(self) -> None:
        plan = self.plan()
        apply_migration(plan, self.artifacts)
        with self.assertRaisesRegex(RuntimeError, "after quarantine move"):
            prune_migration(plan, self.artifacts, interrupt_after_moves=1)

        rollback_migration(plan, self.artifacts)

        verify_inventory(plan, self.artifacts, "source")
        archive = self.artifacts / Path(plan["destination_root"]).parent
        self.assertFalse(archive.exists())

    def test_plan_rejects_noncanonical_artifact_projects_root(self) -> None:
        alternate = self.repository.parent / "alternate-artifacts" / "projects"
        alternate.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "repository sibling artifacts/projects"):
            build_plan(self.repository, alternate, CURRENT, ARCHIVE_ID)

    def test_prune_removes_only_preclassified_files_and_records_hashes(self) -> None:
        plan = self.plan()
        archive = apply_migration(plan, self.artifacts)
        validate_schema(
            json.loads(
                (archive / "archive_manifest.json").read_text(encoding="utf-8")
            ),
            "artifact_identity_archive_manifest.schema.json",
        )
        result = prune_migration(plan, self.artifacts)
        validate_schema(result, "artifact_identity_pruning_journal.schema.json")
        payload = archive / "legacy-project-root"
        self.assertFalse((payload / "runs" / ACTIVE_RUN / "results" / "model.mph").exists())
        self.assertTrue((payload / "runs" / ACTIVE_RUN / "results" / "metrics.csv").is_file())
        self.assertTrue((payload / "runs" / ACTIVE_RUN / "run_manifest.json").is_file())
        self.assertEqual(result["removed_file_count"], 3)
        self.assertTrue(all(len(record["sha256"]) == 64 for record in result["removed"]))
        with self.assertRaisesRegex(ValueError, "cannot be rolled back"):
            rollback_migration(plan, self.artifacts)

    def test_apply_refuses_existing_destination(self) -> None:
        plan = self.plan()
        destination = self.artifacts / Path(plan["destination_root"]).parent
        destination.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            apply_migration(plan, self.artifacts)

    def test_legacy_plan_is_rejected_without_anomaly_audit(self) -> None:
        plan = self.plan()
        plan["schema_version"] = 1
        plan.pop("identity_anomalies")
        plan["inventory"].pop("identity_anomaly_count")
        plan["inventory"].pop("identity_anomaly_file_count")
        with self.assertRaisesRegex(ValueError, "migration manifest identity differs"):
            validate_plan(plan)

    def test_multiple_legacy_identities_require_explicit_selection(self) -> None:
        descriptor = self.repository / "projects" / CURRENT / "config" / "project.json"
        value = json.loads(descriptor.read_text(encoding="utf-8"))
        second = dict(value["legacy_identities"][0])
        second["mapping_id"] = "older-rename"
        second["project_id"] = "rf_hexapole_older_name"
        second["artifact_root"] = "artifacts/projects/rf_hexapole_older_name"
        value["legacy_identities"].append(second)
        descriptor.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "selection must resolve exactly once"):
            build_plan(self.repository, self.artifacts, CURRENT, ARCHIVE_ID)
        plan = build_plan(
            self.repository, self.artifacts, CURRENT, ARCHIVE_ID, legacy_project_id=LEGACY
        )
        self.assertEqual(plan["legacy_project_id"], LEGACY)

    def test_prune_resumes_after_partial_quarantine(self) -> None:
        plan = self.plan()
        archive = apply_migration(plan, self.artifacts)
        with self.assertRaisesRegex(RuntimeError, "after quarantine move"):
            prune_migration(plan, self.artifacts, interrupt_after_moves=1)
        journal = json.loads(
            (archive / "pruning_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(journal["state"], "in_progress")
        result = prune_migration(plan, self.artifacts)
        self.assertEqual(result["state"], "complete")

    def test_prune_resumes_after_partial_delete(self) -> None:
        plan = self.plan()
        archive = apply_migration(plan, self.artifacts)
        with self.assertRaisesRegex(RuntimeError, "during delete"):
            prune_migration(plan, self.artifacts, interrupt_after_deletes=1)
        journal = json.loads(
            (archive / "pruning_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(journal["state"], "deleting")
        result = prune_migration(plan, self.artifacts)
        self.assertEqual(result["state"], "complete")

    def test_complete_journal_reconciles_archive_publication_after_interrupt(self) -> None:
        plan = self.plan()
        archive = apply_migration(plan, self.artifacts)
        with self.assertRaisesRegex(RuntimeError, "after complete journal"):
            prune_migration(
                plan,
                self.artifacts,
                interrupt_after_complete_journal=True,
            )
        wrapper = json.loads(
            (archive / "archive_manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(wrapper["deletion_performed"])
        result = prune_migration(plan, self.artifacts)
        self.assertEqual(result["state"], "complete")
        wrapper = json.loads(
            (archive / "archive_manifest.json").read_text(encoding="utf-8")
        )
        self.assertTrue(wrapper["deletion_performed"])
        self.assertEqual(wrapper["pruning_manifest"], "pruning_manifest.json")

    def test_artifact_layout_accepts_only_complete_identity_archive(self) -> None:
        plan = self.plan()
        archive = apply_migration(plan, self.artifacts)
        verify_project(
            self.artifacts / CURRENT,
            verify_hashes=True,
            repository_root=self.repository,
        )
        with self.assertRaisesRegex(RuntimeError, "after quarantine move"):
            prune_migration(plan, self.artifacts, interrupt_after_moves=1)
        with self.assertRaisesRegex(AssertionError, "pruning journal is incomplete"):
            verify_project(
                self.artifacts / CURRENT,
                verify_hashes=False,
                repository_root=self.repository,
            )
        prune_migration(plan, self.artifacts)
        verify_project(
            self.artifacts / CURRENT,
            verify_hashes=True,
            repository_root=self.repository,
        )
        self.assertTrue((archive / "pruning_manifest.json").is_file())

    def test_location_state_switch_removes_old_root_fallback(self) -> None:
        pending = {
            "mapping_id": "hex-rename",
            "project_id": LEGACY,
            "artifact_location": {
                "schema_version": 1,
                "state": "source_pending_relocation",
                "source_root": f"artifacts/projects/{LEGACY}",
                "archive_id": ARCHIVE_ID,
                "archive_root": (
                    f"artifacts/projects/{CURRENT}/archive/{ARCHIVE_ID}/"
                    "legacy-project-root"
                ),
                "migration_manifest": (
                    f"artifacts/projects/{CURRENT}/archive/{ARCHIVE_ID}/"
                    "identity_migration_manifest.json"
                ),
            },
        }
        self.assertEqual(
            resolve_legacy_artifact_root(
                self.repository.parent, pending, CURRENT
            ),
            (self.artifacts / LEGACY).resolve(),
        )
        plan = self.plan()
        archive = apply_migration(plan, self.artifacts)
        archived = json.loads(json.dumps(pending))
        archived["artifact_location"]["state"] = "archived_verified"
        del archived["artifact_location"]["source_root"]
        self.assertEqual(
            resolve_legacy_artifact_root(
                self.repository.parent, archived, CURRENT
            ),
            (archive / "legacy-project-root").resolve(),
        )
        location = legacy_artifact_location(archived, CURRENT)
        self.assertEqual(location["state"], "archived_verified")
        self.assertNotIn("source_root", archived["artifact_location"])


if __name__ == "__main__":
    unittest.main()
