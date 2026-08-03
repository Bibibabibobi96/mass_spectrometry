from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_project_registry import (
    DEFAULT_OUTPUT,
    ContractError,
    REPO_ROOT,
    build_registry,
    consistent_profile_identity,
    descriptor_paths,
    serialized,
    validate_descriptor,
    validate_legacy_identity_mappings,
)
from machine_contracts import load_json, validate_schema
from file_identity import repository_text_sha256


def pending_location(current: str, retired: str, suffix: str) -> dict:
    archive_id = f"20260801_130000__migration-snapshot__repo__{suffix}"
    archive = f"artifacts/projects/{current}/archive/{archive_id}"
    return {
        "schema_version": 1,
        "state": "source_pending_relocation",
        "source_root": f"artifacts/projects/{retired}",
        "archive_id": archive_id,
        "archive_root": f"{archive}/legacy-project-root",
        "migration_manifest": f"{archive}/identity_migration_manifest.json",
    }


class ProjectRegistryTests(unittest.TestCase):
    def test_registry_and_multipole_profile_hashes_are_lf_crlf_equivalent(
        self,
    ) -> None:
        project_id = "rf_hexapole_ion_optics"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            lf_root = base / "lf"
            crlf_root = base / "crlf"
            lf_project = lf_root / "projects" / project_id
            lf_project.parent.mkdir(parents=True)
            shutil.copytree(REPO_ROOT / "projects" / project_id, lf_project)
            for path in lf_project.rglob("*.json"):
                path.write_bytes(
                    path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                )

            profiles_path = lf_project / "config" / "design_profiles.json"
            profiles = load_json(profiles_path)
            for profile in profiles["profiles"]:
                request_path = lf_project / profile["design_request"]
                envelope_path = lf_project / profile["optimization_envelope"]
                envelope = load_json(envelope_path)
                envelope["reference"]["design_request_sha256"] = (
                    repository_text_sha256(request_path)
                )
                envelope_path.write_text(
                    json.dumps(envelope, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
            for profile in profiles["profiles"]:
                profile["sha256"] = {
                    label: repository_text_sha256(lf_project / profile[label])
                    for label in (
                        "design_request",
                        "design_variables",
                        "optimization_envelope",
                    )
                }
            modes_path = lf_project / profiles["operating_mode_registry"]
            profiles["operating_mode_registry_sha256"] = (
                repository_text_sha256(modes_path)
            )
            profiles_path.write_text(
                json.dumps(profiles, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            execution = load_json(lf_project / "config" / "execution_profiles.json")
            for execution_profile in execution["profiles"]:
                for step in execution_profile["steps"]:
                    entrypoint = (lf_project / step["entrypoint"]).resolve()
                    if not entrypoint.exists():
                        entrypoint.parent.mkdir(parents=True, exist_ok=True)
                        entrypoint.touch()

            shutil.copytree(lf_root, crlf_root)
            for path in (crlf_root / "projects" / project_id).rglob("*.json"):
                path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

            lf_registry = build_registry(lf_root)
            crlf_registry = build_registry(crlf_root)
            self.assertEqual(lf_registry, crlf_registry)
            descriptor_path = lf_project / "config" / "project.json"
            self.assertEqual(
                lf_registry["generated_from"][0]["sha256"],
                repository_text_sha256(descriptor_path),
            )

    def test_multipole_registration_uses_one_consistent_profile_identity(self) -> None:
        identities = [
            {
                "project_id": "rf_hexapole_ion_optics",
                "family_id": "rf_multipole_ion_optics",
                "radial_order_n": 3,
                "electrode_count": 6,
            },
            {
                "project_id": "rf_hexapole_ion_optics",
                "family_id": "rf_multipole_ion_optics",
                "radial_order_n": 3,
                "electrode_count": 6,
            },
        ]
        profiles_path = REPO_ROOT / "profiles.json"
        self.assertEqual(
            consistent_profile_identity(identities, profiles_path),
            identities[0],
        )
        identities[1] = {**identities[1], "radial_order_n": 4}
        with self.assertRaisesRegex(ContractError, "design profile identities differ"):
            consistent_profile_identity(identities, profiles_path)
        with self.assertRaisesRegex(ContractError, "require an identity"):
            consistent_profile_identity([], profiles_path)

    def test_rf_multipole_descriptors_do_not_register_legacy_baselines(self) -> None:
        project_ids = (
            "rf_quadrupole_ion_optics",
            "rf_hexapole_ion_optics",
            "rf_octupole_ion_optics",
        )
        for project_id in project_ids:
            path = REPO_ROOT / "projects" / project_id / "config" / "project.json"
            descriptor = load_json(path)
            self.assertIsNone(descriptor["contracts"]["baseline"])
            validate_descriptor(descriptor, path, REPO_ROOT)

    def test_all_project_directories_have_descriptors(self) -> None:
        project_directories = sorted(path.name for path in (REPO_ROOT / "projects").iterdir() if path.is_dir())
        described = sorted(path.parents[1].name for path in descriptor_paths(REPO_ROOT))
        self.assertEqual(project_directories, described)

    def test_registry_is_current_and_deterministic(self) -> None:
        registry = build_registry()
        self.assertEqual(
            [project["project_id"] for project in registry["projects"]],
            sorted(project["project_id"] for project in registry["projects"]),
        )
        self.assertEqual(DEFAULT_OUTPUT.read_text(encoding="utf-8"), serialized(registry))
        commands = (
            [
                sys.executable,
                str(REPO_ROOT / "common" / "contracts" / "build_project_registry.py"),
                "--check",
            ],
            [sys.executable, "-m", "common.contracts.build_project_registry", "--check"],
        )
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_project_id_must_match_directory(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        descriptor["project_id"] = "wrong_project"
        with self.assertRaisesRegex(ContractError, "differs from directory"):
            validate_descriptor(descriptor, path, REPO_ROOT)

    def test_schema_rejects_unknown_maturity(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        descriptor["lifecycle_status"] = "finished"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

    def test_formal_project_retains_contracts_and_identity_requirement(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        self.assertEqual(descriptor["lifecycle_status"], "formal")
        self.assertIn("science", descriptor["contracts"])
        self.assertIn("solver_numerics", descriptor["contracts"])
        validate_descriptor(descriptor, path, REPO_ROOT)

        descriptor["formal_assets"]["identity_contract"] = None
        with self.assertRaisesRegex(ContractError, "identity contract"):
            validate_descriptor(descriptor, path, REPO_ROOT)

    def test_legacy_identity_schema_freezes_recorded_evidence_semantics(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        legacy = descriptor["legacy_identities"][0]
        self.assertEqual(legacy["verification_identity"], "recorded_project_id")
        self.assertEqual(legacy["artifact_access"], "read_only")
        self.assertFalse(legacy["new_runs_allowed"])

        legacy["verification_identity"] = "current_project_id"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

        descriptor = copy.deepcopy(load_json(path))
        legacy = descriptor["legacy_identities"][0]
        legacy.pop("artifact_location")
        legacy["artifact_root"] = "artifacts/projects/oa_tof"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

    def test_legacy_identity_rejects_active_id_and_wrong_artifact_location(self) -> None:
        descriptors = [
            {
                "project_id": "current_project",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_1",
                        "project_id": "other_active_project",
                        "artifact_location": pending_location(
                            "current_project", "other_active_project", "other-active"
                        ),
                    }
                ],
            },
            {"project_id": "other_active_project"},
        ]
        with self.assertRaisesRegex(ContractError, "still active"):
            validate_legacy_identity_mappings(descriptors)

        descriptors.pop()
        descriptors[0]["legacy_identities"][0]["project_id"] = "retired_project"
        with self.assertRaisesRegex(ContractError, "legacy artifact location differs"):
            validate_legacy_identity_mappings(descriptors)

    def test_multipole_relocation_has_one_governed_archive(self) -> None:
        for project_id in (
            "rf_quadrupole_ion_optics",
            "rf_hexapole_ion_optics",
            "rf_octupole_ion_optics",
        ):
            descriptor = load_json(
                REPO_ROOT / "projects" / project_id / "config" / "project.json"
            )
            mapping = descriptor["legacy_identities"][0]
            location = mapping["artifact_location"]
            self.assertIn(
                location["state"], {"source_pending_relocation", "archived_verified"}
            )
            if location["state"] == "source_pending_relocation":
                self.assertEqual(
                    location["source_root"],
                    f"artifacts/projects/{mapping['project_id']}",
                )
            else:
                self.assertNotIn("source_root", location)
            self.assertNotIn("artifact_root", mapping)
            self.assertTrue(location["archive_root"].startswith(
                f"artifacts/projects/{project_id}/archive/"
            ))
            self.assertEqual(
                location["migration_manifest"],
                location["archive_root"].removesuffix("/legacy-project-root")
                + "/identity_migration_manifest.json",
            )

    def test_legacy_identity_rejects_duplicate_ids_and_mapping_ids(self) -> None:
        descriptors = [
            {
                "project_id": "current_a",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_shared",
                        "project_id": "retired_shared",
                        "artifact_location": pending_location(
                            "current_a", "retired_shared", "retired-shared-a"
                        ),
                    }
                ],
            },
            {
                "project_id": "current_b",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_other",
                        "project_id": "retired_shared",
                        "artifact_location": pending_location(
                            "current_b", "retired_shared", "retired-shared-b"
                        ),
                    }
                ],
            },
        ]
        with self.assertRaisesRegex(ContractError, "duplicate legacy project_id"):
            validate_legacy_identity_mappings(descriptors)

        descriptors[1]["legacy_identities"][0].update(
            {
                "mapping_id": "rename_shared",
                "project_id": "retired_other",
                "artifact_location": pending_location(
                    "current_b", "retired_other", "retired-other"
                ),
            }
        )
        with self.assertRaisesRegex(ContractError, "duplicate legacy mapping_id"):
            validate_legacy_identity_mappings(descriptors)


if __name__ == "__main__":
    unittest.main()
