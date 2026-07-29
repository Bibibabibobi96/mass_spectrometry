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
            "comsol/verify_oatof_comsol_sync.m",
            "simion/workbench/verify_formal_runtime.lua",
            "simion/workbench/verify_iob_runtime_contract.lua",
            "simion/workbench/verify_iob_runtime_contract.ps1",
            "simion/workbench/run_parameterized_geometry_smoke.ps1",
            "workflows/design_candidate/prepare_candidate_consumers.py",
            "workflows/design_candidate/run_candidate.py",
            "workflows/design_candidate/run_candidate_workflow.py",
            "workflows/design_candidate/run_candidate_contract_build.m",
            "workflows/design_candidate/run_candidate_cad_sync.m",
        }
        for relative in expected:
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)

        removed = {
            "tests/cross_solver/run_mass_spectrum_candidate.ps1",
            "tests/comsol/test_accelerator_mesh_particle_candidate.m",
            "tests/comsol/verify_oatof_comsol_sync.m",
            "tests/simion/verify_formal_runtime.lua",
            "tests/simion/verify_iob_runtime_contract.lua",
            "tests/simion/verify_iob_runtime_contract.ps1",
            "tests/simion/test_parameterized_geometry_build.ps1",
            "analysis/prepare_candidate_consumers.py",
            "analysis/run_candidate_workflow.py",
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
            "workflows/design_candidate/run_candidate.py", entries
        )

        closure = (PROJECT_ROOT / "analysis" / "candidate_source_closure.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflows/design_candidate/run_candidate.py", closure)
        self.assertIn("workflows/design_candidate/run_candidate_contract_build.m", closure)
        self.assertIn("workflows/design_candidate/run_candidate_cad_sync.m", closure)
        self.assertIn("comsol/verify_oatof_comsol_sync.m", closure)
        self.assertIn("simion/workbench/verify_iob_runtime_contract.lua", closure)
        self.assertIn("simion/workbench/verify_iob_runtime_contract.ps1", closure)
        self.assertNotIn("tests/comsol/run_candidate_contract_build.m", closure)
        self.assertNotIn("tests/cad/run_candidate_cad_sync.m", closure)
        self.assertNotIn("tests/comsol/verify_oatof_comsol_sync.m", closure)
        self.assertNotIn("tests/simion/verify_iob_runtime_contract", closure)

        core = (
            PROJECT_ROOT
            / "workflows"
            / "design_candidate"
            / "run_candidate_workflow.py"
        ).read_text(encoding="utf-8")
        lifecycle = (
            PROJECT_ROOT / "analysis" / "candidate_run_lifecycle.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("native_receipts", core)
        self.assertNotIn("def main(", core)
        self.assertNotIn("def main(", lifecycle)

    def test_candidate_gate_uses_production_parameterized_geometry_runner(self):
        gate = (PROJECT_ROOT / "verify_project.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "simion\\workbench\\run_parameterized_geometry_smoke.ps1",
            gate,
        )
        self.assertNotIn(
            "tests\\simion\\test_parameterized_geometry_build.ps1",
            gate,
        )


if __name__ == "__main__":
    unittest.main()
