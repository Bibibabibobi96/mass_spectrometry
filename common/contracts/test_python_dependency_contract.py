from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


REPO_ROOT = Path(__file__).resolve().parents[2]


class PythonDependencyContractTests(unittest.TestCase):
    def test_declared_dependencies_have_compatible_unique_lock_entries(self) -> None:
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        self.assertEqual(project["requires-python"], ">=3.11,<3.12")
        declared_lines = list(project["dependencies"])
        for optional_lines in project.get("optional-dependencies", {}).values():
            declared_lines.extend(optional_lines)

        locked: dict[str, Requirement] = {}
        for line in (REPO_ROOT / "requirements-lock.txt").read_text(
            encoding="utf-8"
        ).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            requirement = Requirement(stripped)
            name = canonicalize_name(requirement.name)
            self.assertNotIn(name, locked, f"duplicate locked dependency: {name}")
            locked[name] = requirement

        for declared_line in declared_lines:
            declared = Requirement(declared_line)
            name = canonicalize_name(declared.name)
            self.assertIn(name, locked, f"declared dependency is not locked: {name}")
            lock = locked[name]
            exact_versions = [
                spec.version
                for spec in lock.specifier
                if spec.operator == "==" and "*" not in spec.version
            ]
            self.assertEqual(
                len(exact_versions), 1, f"lock entry must pin one exact version: {name}"
            )
            self.assertTrue(
                declared.specifier.contains(exact_versions[0], prereleases=True),
                f"locked version violates pyproject constraint: {name}",
            )
            self.assertEqual(
                str(declared.marker) if declared.marker else None,
                str(lock.marker) if lock.marker else None,
                f"environment marker differs between declaration and lock: {name}",
            )


if __name__ == "__main__":
    unittest.main()
