from __future__ import annotations

import copy
import unittest

from build_project_registry import (
    DEFAULT_OUTPUT,
    ContractError,
    REPO_ROOT,
    build_registry,
    descriptor_paths,
    serialized,
    validate_descriptor,
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

    def test_project_id_must_match_directory(self) -> None:
        path = REPO_ROOT / "projects" / "oa_tof" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        descriptor["project_id"] = "wrong_project"
        with self.assertRaisesRegex(ContractError, "differs from directory"):
            validate_descriptor(descriptor, path, REPO_ROOT)

    def test_schema_rejects_unknown_maturity(self) -> None:
        path = REPO_ROOT / "projects" / "oa_tof" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        descriptor["lifecycle_status"] = "finished"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")


if __name__ == "__main__":
    unittest.main()
