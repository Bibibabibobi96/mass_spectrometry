from __future__ import annotations

import copy
import subprocess
import sys
import unittest

from build_project_registry import (
    DEFAULT_OUTPUT,
    ContractError,
    REPO_ROOT,
    build_registry,
    descriptor_paths,
    serialized,
    validate_descriptor,
    validate_legacy_identity_mappings,
)
from machine_contracts import load_json, validate_schema


class ProjectRegistryTests(unittest.TestCase):
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

    def test_legacy_identity_rejects_active_id_and_wrong_artifact_root(self) -> None:
        descriptors = [
            {
                "project_id": "current_project",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_1",
                        "project_id": "other_active_project",
                        "artifact_root": "artifacts/projects/other_active_project",
                    }
                ],
            },
            {"project_id": "other_active_project"},
        ]
        with self.assertRaisesRegex(ContractError, "still active"):
            validate_legacy_identity_mappings(descriptors)

        descriptors.pop()
        descriptors[0]["legacy_identities"][0]["project_id"] = "retired_project"
        with self.assertRaisesRegex(ContractError, "legacy artifact root must be"):
            validate_legacy_identity_mappings(descriptors)

    def test_legacy_identity_rejects_duplicate_ids_and_mapping_ids(self) -> None:
        descriptors = [
            {
                "project_id": "current_a",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_shared",
                        "project_id": "retired_shared",
                        "artifact_root": "artifacts/projects/retired_shared",
                    }
                ],
            },
            {
                "project_id": "current_b",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_other",
                        "project_id": "retired_shared",
                        "artifact_root": "artifacts/projects/retired_shared",
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
                "artifact_root": "artifacts/projects/retired_other",
            }
        )
        with self.assertRaisesRegex(ContractError, "duplicate legacy mapping_id"):
            validate_legacy_identity_mappings(descriptors)


if __name__ == "__main__":
    unittest.main()
