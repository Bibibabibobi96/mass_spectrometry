from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class WorkflowEntryLayoutTests(unittest.TestCase):
    def test_active_entries_have_one_role_appropriate_location(self):
        expected = {
            "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1",
            "comsol/run_fixed_particle_retrace.m",
            "workflows/design_candidate/prepare_candidate_consumers.py",
            "workflows/design_candidate/run_candidate_workflow.py",
            "workflows/design_candidate/run_bound_candidate_workflow.py",
            "workflows/design_candidate/run_candidate_contract_build.m",
            "workflows/design_candidate/run_candidate_cad_sync.m",
        }
        for relative in expected:
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)

        removed = {
            "tests/cross_solver/run_mass_spectrum_candidate.ps1",
            "tests/comsol/test_accelerator_mesh_particle_candidate.m",
            "analysis/prepare_candidate_consumers.py",
            "analysis/run_candidate_workflow.py",
            "analysis/run_bound_candidate_workflow.py",
            "tests/comsol/run_candidate_contract_build.m",
            "tests/cad/run_candidate_cad_sync.m",
        }
        for relative in removed:
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)

    def test_profiles_and_candidate_closure_reference_canonical_entries(self):
        profiles = json.loads(
            (PROJECT_ROOT / "config" / "execution_profiles.json").read_text(encoding="utf-8")
        )
        entries = {
            step["entrypoint"]
            for profile in profiles["profiles"]
            for step in profile["steps"]
        }
        self.assertIn(
            "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1", entries
        )
        self.assertIn(
            "workflows/design_candidate/run_bound_candidate_workflow.py", entries
        )

        closure = (PROJECT_ROOT / "analysis" / "candidate_source_closure.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflows/design_candidate/run_candidate_contract_build.m", closure)
        self.assertIn("workflows/design_candidate/run_candidate_cad_sync.m", closure)
        self.assertNotIn("tests/comsol/run_candidate_contract_build.m", closure)
        self.assertNotIn("tests/cad/run_candidate_cad_sync.m", closure)


if __name__ == "__main__":
    unittest.main()
