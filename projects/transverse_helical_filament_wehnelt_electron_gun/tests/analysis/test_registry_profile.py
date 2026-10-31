"""Project capability binding; full registry freshness belongs to its common owner."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from common.contracts.build_project_registry import validate_descriptor
from common.contracts.particle_physics import ELECTRON_MASS_U

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]

class RegistryProfileTests(unittest.TestCase):
    def test_shared_registry_accepts_and_exposes_profile(self) -> None:
        path = PROJECT_ROOT/"config/project.json"
        project = json.loads(path.read_text(encoding="utf-8"))
        validate_descriptor(project, path, REPO_ROOT)
        execution = json.loads((PROJECT_ROOT/project["contracts"]["execution"]).read_text(encoding="utf-8"))
        profile = execution["profiles"][0]
        self.assertEqual(profile["mode"], "build_only_smoke")
        self.assertEqual(profile["action"], "build")
        self.assertEqual(profile["qualification_support"], ["none"])
        self.assertEqual([step["step_id"] for step in profile["steps"]], ["commercial_build_only"])
        self.assertEqual(profile["steps"][0]["entrypoint"], "run_build_only_smoke.ps1")
        self.assertEqual(profile["supported_operating_points"][0]["mass"], {"value": ELECTRON_MASS_U, "unit": "Da"})
        self.assertIn("does not run either solver", " ".join(profile["limitations"]))
