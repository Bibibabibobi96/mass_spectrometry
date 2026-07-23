"""Repository-registry checks for the EI-source execution profile."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


class RegistryProfileTests(unittest.TestCase):
    """Require the shared registry/schema path instead of an EI-only format."""

    def test_shared_registry_accepts_and_exposes_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project_registry.json"
            command = [
                sys.executable,
                "-m",
                "common.contracts.build_project_registry",
                "--output",
                str(output),
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except subprocess.TimeoutExpired as exc:
                self.fail(
                    f"project-registry build timed out after {exc.timeout}s: {command}"
                )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            registry = json.loads(output.read_text(encoding="utf-8"))

        project = next(
            item
            for item in registry["projects"]
            if item["project_id"] == "electron_impact_ion_source"
        )
        self.assertEqual(
            project["contracts"]["execution"], "config/execution_profiles.json"
        )
        self.assertEqual(
            project["capabilities"][0]["modes"], ["build_only_smoke"]
        )

        profile_path = PROJECT_ROOT / project["contracts"]["execution"]
        execution = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(execution["role"], "project_execution_profiles")
        self.assertEqual(len(execution["profiles"]), 1)
        profile = execution["profiles"][0]
        self.assertEqual(profile["mode"], "build_only_smoke")
        self.assertEqual(profile["evidence_levels"], ["plan"])


if __name__ == "__main__":
    unittest.main()
