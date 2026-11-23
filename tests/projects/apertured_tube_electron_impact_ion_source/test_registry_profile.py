"""Project capability binding; full registry freshness belongs to its common owner."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tools.repository.build_project_registry import validate_descriptor

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT / "src/msplatform/components/apertured_tube_electron_impact_ion_source"

class RegistryProfileTests(unittest.TestCase):
    def test_shared_registry_accepts_and_exposes_profile(self) -> None:
        path = PROJECT_ROOT/"config/project.json"
        project = json.loads(path.read_text(encoding="utf-8"))
        validate_descriptor(project, path, REPO_ROOT)
        execution = json.loads((PROJECT_ROOT/project["contracts"]["execution"]).read_text(encoding="utf-8"))
        self.assertEqual(execution["profiles"], [])
        self.assertEqual(project["capabilities"][0]["modes"], ["build_only_smoke"])
        self.assertTrue((REPO_ROOT/"src/msplatform/workflows/resources/ei_verify.ps1").is_file())
