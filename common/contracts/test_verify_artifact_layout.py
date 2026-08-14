from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.verify_artifact_layout import (
    verify_artifacts_root,
    verify_cache,
    verify_formal,
    verify_integration_cache_entry,
)


RUN_ID = "20260721_120000__sim__cross__formal-validation__n100"


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


class ArtifactLayoutIdentityTests(unittest.TestCase):
    def write_reusable_cache(
        self, entry: Path, role: str, project_id: str, names: tuple[str, ...]
    ) -> Path:
        identity = {
            "schema_version": 2,
            "role": role,
            "project_id": project_id,
            "solver": {
                "name": "SIMION",
                "product_version": "2020",
                "executable_sha256": "E" * 64,
            },
            "critical_options": {"refine_convergence": "5e-7"},
        }
        key_input = json.dumps(identity, separators=(",", ":"))
        entry = entry.parent / hashlib.sha256(key_input.encode()).hexdigest()
        entry.mkdir(parents=True)
        records = []
        for name in names:
            path = entry / name
            path.write_text(f"cached {name}\n", encoding="utf-8")
            item = record(path, entry)
            item.pop("path")
            records.append({"name": name, **item})
        write_json(
            entry / "cache_manifest.json",
            {
                "schema_version": 2,
                "role": role,
                "cache_key": entry.name,
                "cache_key_input": key_input,
                "identity": identity,
                "files": records,
            },
        )
        return entry

    def test_artifacts_root_rejects_files_beside_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory) / "artifacts"
            projects = artifacts / "projects"
            projects.mkdir(parents=True)
            verify_artifacts_root(projects)
            (artifacts / "probe.txt").write_text("stray\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "unexpected top-level"):
                verify_artifacts_root(projects)

    def test_content_addressed_pa_cache_is_narrow_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "rf_hexapole_ion_optics"
            basis = project / "cache" / "simion_pa_basis" / ("A" * 64)
            basis.mkdir(parents=True)
            records = []
            for index in range(3):
                path = basis / f"quad_monolithic.pa{index}"
                path.write_text(f"basis {index}\n", encoding="utf-8")
                records.append({"name": path.name, **record(path, basis)})
                records[-1].pop("path")
            write_json(
                basis / "manifest.json",
                {
                    "schema_version": 1,
                    "role": "multipole_simion_pa_basis_cache",
                    "fingerprint_sha256": "A" * 64,
                    "identity": {"project_id": project.name},
                    "files": records,
                },
            )

            verify_cache(project, verify_hashes=True)
            (basis / "unexpected.bin").write_bytes(b"unexpected")
            with self.assertRaisesRegex(AssertionError, "cache inventory differs"):
                verify_cache(project, verify_hashes=True)

    def test_integration_pa_caches_are_registered_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "integration"
            frontend = (
                project / "cache" / "simion_single_flight_frontend" / ("a" * 64)
            )
            downstream = (
                project / "cache" / "simion_oatof_downstream_pa" / ("b" * 64)
            )
            overlay = (
                project / "cache" / "simion_accelerator_overlay" / ("c" * 64)
            )
            frontend.mkdir(parents=True)
            downstream.mkdir(parents=True)
            overlay.mkdir(parents=True)
            (frontend / "frontend.pa0").write_text("pa\n", encoding="utf-8")
            (downstream / "reflectron.pa0").write_text("pa\n", encoding="utf-8")
            (downstream / "reflectron.pa1").write_text("basis\n", encoding="utf-8")
            (overlay / "accelerator_overlay.gem").write_text(
                "gem\n", encoding="utf-8"
            )
            for electrode in range(20):
                (overlay / f"accelerator_overlay.pa{electrode}").write_text(
                    f"basis {electrode}\n", encoding="utf-8"
                )
            write_json(
                overlay / "cache_manifest.json",
                {
                    "schema_version": 1,
                    "role": "simion_accelerator_overlay_pa_cache",
                    "cache_key": "c" * 64,
                    "basis_count": 20,
                },
            )
            write_json(
                overlay / "basis_build.json",
                {
                    "schema_version": 1,
                    "role": "simion_accelerator_overlay_basis_build",
                    "status": "pass",
                    "basis_array_count": 20,
                },
            )
            verify_cache(project)
            (frontend.parent / "not-a-hash").mkdir()
            with self.assertRaisesRegex(AssertionError, "content-addressed"):
                verify_cache(project)

    def test_accelerator_overlay_cache_rejects_wrong_basis_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "integration"
            overlay = (
                project / "cache" / "simion_accelerator_overlay" / ("d" * 64)
            )
            overlay.mkdir(parents=True)
            (overlay / "accelerator_overlay.gem").write_text(
                "gem\n", encoding="utf-8"
            )
            for electrode in range(20):
                (overlay / f"accelerator_overlay.pa{electrode}").write_text(
                    f"basis {electrode}\n", encoding="utf-8"
                )
            write_json(
                overlay / "cache_manifest.json",
                {
                    "schema_version": 1,
                    "role": "simion_accelerator_overlay_pa_cache",
                    "cache_key": "d" * 64,
                    "basis_count": 20,
                },
            )
            write_json(
                overlay / "basis_build.json",
                {
                    "schema_version": 1,
                    "role": "simion_accelerator_overlay_pa_cache",
                    "status": "pass",
                    "basis_array_count": 20,
                },
            )
            with self.assertRaisesRegex(AssertionError, "cache identity differs"):
                verify_cache(project)

    def test_reusable_integration_cache_verifies_identity_and_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "integration"
            entry = project / "cache" / "simion_single_flight_frontend" / ("e" * 64)
            entry = self.write_reusable_cache(
                entry,
                "simion_single_flight_frontend_pa_cache",
                project.name,
                ("frontend.gem", "frontend.pa#", "frontend.pa0"),
            )
            verify_cache(project, verify_hashes=True)
            verify_integration_cache_entry(
                entry,
                expected_role="simion_single_flight_frontend_pa_cache",
                expected_key=entry.name,
                expected_project_id=project.name,
            )
            (entry / "frontend.pa0").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "byte count differs"):
                verify_cache(project, verify_hashes=True)

    def test_reusable_downstream_cache_role_must_match_registered_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "integration"
            entry = (
                project
                / "cache"
                / "simion_oatof_downstream_pa"
                / ("f" * 64)
            )
            entry = self.write_reusable_cache(
                entry,
                "simion_single_flight_frontend_pa_cache",
                project.name,
                ("flight_tube_ground.pa0",),
            )
            with self.assertRaisesRegex(AssertionError, "not registered"):
                verify_cache(project, verify_hashes=True)

    def test_reusable_cache_rejects_missing_solver_or_extra_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "integration"
            entry = (
                project / "cache" / "simion_accelerator_overlay" / ("1" * 64)
            )
            entry = self.write_reusable_cache(
                entry,
                "simion_accelerator_overlay_pa_cache",
                project.name,
                ("accelerator_overlay.pa0",),
            )
            manifest_path = entry / "cache_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["identity"]["solver"].pop("product_version")
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(AssertionError, "identity differs"):
                verify_integration_cache_entry(
                    entry,
                    expected_role="simion_accelerator_overlay_pa_cache",
                    expected_key=entry.name,
                    expected_project_id=project.name,
                )
            manifest["identity"]["solver"]["product_version"] = "2020"
            write_json(manifest_path, manifest)
            (entry / "unexpected.bin").write_bytes(b"unexpected")
            with self.assertRaisesRegex(AssertionError, "inventory differs"):
                verify_integration_cache_entry(
                    entry,
                    expected_role="simion_accelerator_overlay_pa_cache",
                    expected_key=entry.name,
                    expected_project_id=project.name,
                )

    def make_formal(
        self,
        artifacts: Path,
        project_id: str,
        validation_record: dict[str, object],
        *,
        legacy_primary_name: bool = False,
    ) -> tuple[Path, Path]:
        project = artifacts / project_id
        run = project / "runs" / RUN_ID
        run.mkdir(parents=True)
        for name in ("run_config.json", "summary.json", "run_manifest.json"):
            (run / name).write_text(f"{name}\n", encoding="utf-8")
        formal = project / "formal"
        formal.mkdir()
        asset = formal / "results.sha256"
        asset.write_text("formal result identity\n", encoding="utf-8")
        assets = {"formal_results_manifest": record(asset, formal)}
        if legacy_primary_name:
            legacy_model = formal / "comsol" / "old_model.mph"
            legacy_model.parent.mkdir()
            legacy_model.write_text("legacy model identity\n", encoding="utf-8")
            assets["comsol_model"] = record(legacy_model, formal)
        manifest = {
            "schema_version": 1,
            "role": "formal_asset_manifest",
            "project": project_id,
            "source_run": {
                "run_id": RUN_ID,
                "path": f"runs/{RUN_ID}",
                "run_config": record(run / "run_config.json", project),
                "summary": record(run / "summary.json", project),
                "run_manifest": record(run / "run_manifest.json", project),
            },
            "validation_contract": validation_record,
            "assets": assets,
        }
        write_json(formal / "asset_manifest.json", manifest)
        return project, asset

    def test_active_project_requires_and_hashes_repository_validation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            artifacts = root / "artifacts" / "projects"
            validation = repository / "projects" / "active" / "config" / "formal.json"
            validation.parent.mkdir(parents=True)
            validation.write_text("active validation\n", encoding="utf-8")
            write_json(
                validation.parent / "project.json",
                {"project_id": "active"},
            )
            project, _ = self.make_formal(
                artifacts, "active", record(validation, repository)
            )

            verify_formal(project, verify_hashes=True, repository_root=repository)
            validation.write_text("tampered validation\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "byte count differs"):
                verify_formal(
                    project, verify_hashes=True, repository_root=repository
                )

    def test_read_only_renamed_root_keeps_asset_checks_without_retired_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            artifacts = root / "artifacts" / "projects"
            descriptor_path = (
                repository / "projects" / "current" / "config" / "project.json"
            )
            descriptor = {
                "project_id": "current",
                "legacy_identities": [
                    {
                        "project_id": "retired",
                        "artifact_location": {
                            "schema_version": 1,
                            "state": "source_pending_relocation",
                            "source_root": "artifacts/projects/retired",
                            "archive_id": "20260801_130000__migration-snapshot__repo__retired",
                            "archive_root": (
                                "artifacts/projects/current/archive/"
                                "20260801_130000__migration-snapshot__repo__retired/"
                                "legacy-project-root"
                            ),
                            "migration_manifest": (
                                "artifacts/projects/current/archive/"
                                "20260801_130000__migration-snapshot__repo__retired/"
                                "identity_migration_manifest.json"
                            ),
                        },
                        "migration_kind": "administrative_rename_only",
                        "artifact_access": "read_only",
                        "new_runs_allowed": False,
                        "verification_identity": "recorded_project_id",
                        "claim_policy": "preserve_original_status_and_claim_limits_no_promotion",
                    }
                ],
            }
            write_json(descriptor_path, descriptor)
            historical_validation = {
                "path": "projects/retired/config/formal_validation.json",
                "bytes": 123,
                "sha256": "A" * 64,
            }
            project, asset = self.make_formal(
                artifacts,
                "retired",
                historical_validation,
                legacy_primary_name=True,
            )
            self.assertFalse(
                (
                    repository
                    / "projects"
                    / "retired"
                    / "config"
                    / "formal_validation.json"
                ).exists()
            )

            verify_formal(project, verify_hashes=True, repository_root=repository)
            descriptor["legacy_identities"][0]["artifact_access"] = "write"
            write_json(descriptor_path, descriptor)
            with self.assertRaisesRegex(
                AssertionError, "invalid legacy identity field artifact_access"
            ):
                verify_formal(
                    project, verify_hashes=True, repository_root=repository
                )
            descriptor["legacy_identities"][0]["artifact_access"] = "read_only"
            write_json(descriptor_path, descriptor)
            asset.write_text("tampered asset\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "byte count differs"):
                verify_formal(
                    project, verify_hashes=True, repository_root=repository
                )

    def test_unmapped_retired_source_is_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            artifacts = root / "artifacts" / "projects"
            (repository / "projects").mkdir(parents=True)
            project, _ = self.make_formal(
                artifacts,
                "retired",
                {
                    "path": "projects/retired/config/formal_validation.json",
                    "bytes": 123,
                    "sha256": "A" * 64,
                },
            )
            with self.assertRaisesRegex(AssertionError, "manifest file is missing"):
                verify_formal(
                    project, verify_hashes=True, repository_root=repository
                )


if __name__ == "__main__":
    unittest.main()
