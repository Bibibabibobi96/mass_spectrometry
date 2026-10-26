from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.artifact_identity_archive import (
    READ_ONLY_IDENTITY_POLICY,
    assert_new_run_project_allowed,
    historical_project_identities,
    legacy_artifact_location,
    load_retired_project_descriptors,
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
CONSOLIDATED = "consolidated_project"


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


def retirement_fixture(repository: Path) -> tuple[dict, Path]:
    """Freeze an original owner and its already archived alias in a small fixture."""
    path = repository / "projects" / CONSOLIDATED / "docs/history/retired_projects" / CURRENT / "config/project.json"
    path.parent.mkdir(parents=True)
    alias = {**_location("archived_verified"), **READ_ONLY_IDENTITY_POLICY,
             "migration_kind": "administrative_rename_only"}
    previous = {"project_id": CURRENT, "legacy_identities": [alias]}
    path.write_bytes((json.dumps(previous) + "\n").encode("utf-8"))
    descriptor = {
        "project_id": CONSOLIDATED,
        "retired_project_descriptors": [{
            "project_id": CURRENT,
            "path": path.relative_to(repository).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
            "source_commit": "a" * 40,
            **READ_ONLY_IDENTITY_POLICY,
        }],
    }
    active = repository / "projects" / CONSOLIDATED / "config/project.json"
    active.parent.mkdir(parents=True)
    active.write_text(json.dumps(descriptor), encoding="utf-8")
    return descriptor, path


class ArtifactIdentityArchiveTests(unittest.TestCase):
    def test_retired_owner_and_archived_alias_keep_original_locations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            descriptor, frozen = retirement_fixture(repository)
            original = frozen.read_bytes()
            previous = load_retired_project_descriptors(descriptor, repository)
            identities = list(historical_project_identities(descriptor, repository))
            self.assertEqual([item.project_id for item in identities], [CURRENT, LEGACY])
            self.assertEqual([item.artifact_owner_project_id for item in identities], [CURRENT, CURRENT])
            self.assertIsNone(identities[0].legacy_mapping)
            mapping = previous[0]["legacy_identities"][0]
            location = legacy_artifact_location(mapping, identities[1].artifact_owner_project_id)
            self.assertEqual(location["active_root"], mapping["artifact_location"]["archive_root"])
            self.assertIn(f"projects/{CURRENT}/archive/", str(location["active_root"]))
            with self.assertRaisesRegex(ValueError, "legacy archive location differs"):
                legacy_artifact_location(mapping, CONSOLIDATED)
            self.assertEqual(frozen.read_bytes(), original)

    def test_retired_descriptor_requires_raw_identity_and_read_only_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            descriptor, frozen = retirement_fixture(repository)
            reference = descriptor["retired_project_descriptors"][0]
            reference["new_runs_allowed"] = True
            with self.assertRaisesRegex(ValueError, "new_runs_allowed"):
                load_retired_project_descriptors(descriptor, repository)
            reference["new_runs_allowed"] = False
            reference["path"] = "../project.json"
            with self.assertRaisesRegex(ValueError, "descriptor path differs"):
                load_retired_project_descriptors(descriptor, repository)
            reference["path"] = frozen.relative_to(repository).as_posix()
            frozen.write_bytes(frozen.read_bytes().replace(b"\n", b"\r\n"))
            with self.assertRaisesRegex(ValueError, "frozen retired descriptor identity differs"):
                load_retired_project_descriptors(descriptor, repository)

    def test_new_run_guard_rejects_only_explicitly_retired_owners_and_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            retirement_fixture(repository)
            before = {path: path.read_bytes() for path in repository.rglob("*") if path.is_file()}
            for project in (CURRENT, LEGACY):
                with self.assertRaisesRegex(ValueError, "new runs are forbidden"):
                    assert_new_run_project_allowed(repository, project)
            for project in (CONSOLIDATED, "instrument_assembly", "existing_fixture"):
                assert_new_run_project_allowed(repository, project)
            after = {path: path.read_bytes() for path in repository.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    @unittest.skipUnless(shutil.which("pwsh") and sys.version_info[:2] == (3, 11), "requires pwsh and Python 3.11")
    def test_run_package_guard_precedes_directory_and_capacity_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            repository = fixture / "repo"
            retirement_fixture(repository)
            source = Path(__file__).resolve().parent
            scripts = repository / "common/contracts"
            scripts.mkdir(parents=True)
            for name in ("artifact_identity_archive.py", "artifact_naming.py", "file_identity.py"):
                shutil.copyfile(source / name, scripts / name)
            ledger = fixture / "artifacts/common/fixture.sqlite3"
            ledger.parent.mkdir(parents=True)
            ledger.write_bytes(b"untouched ledger fixture")
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f"""
$ErrorActionPreference='Stop'
. {quote(source / 'run_artifact_support.ps1')}
$script:capacityCalls=0
function Invoke-RunCapacityLifecycleAdapter {{ $script:capacityCalls++; throw 'CAPACITY_CALLED' }}
foreach($owner in @('{CURRENT}','{LEGACY}')) {{
  $rejected=$false
  try {{
    New-RunPackage -Python {quote(sys.executable)} -RepoRoot {quote(repository)} `
      -ArtifactRoot (Join-Path {quote(fixture / 'artifacts/projects')} $owner) `
      -RunId '20261026_120000__test__python__retired-owner' -Project $owner `
      -Mode 'fixture' -Software @('python') -RetentionContractEnabled -CapacityLedgerLifecycleEnabled | Out-Null
  }} catch {{
    if($_.Exception.Message -notmatch 'retired project identity') {{ throw }}
    $rejected=$true
  }}
  if(-not $rejected) {{ throw 'retired owner was accepted' }}
}}
if($script:capacityCalls -ne 0) {{ throw 'capacity mutation reached' }}
Write-Output 'RETIRED_RUN_GUARD=PASS'
"""
            process = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=repository, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertIn("RETIRED_RUN_GUARD=PASS", process.stdout)
            self.assertFalse((fixture / "artifacts/projects").exists())
            self.assertEqual(ledger.read_bytes(), b"untouched ledger fixture")

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
                (workspace / mapping["artifact_location"]["archive_root"]).resolve(),
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
