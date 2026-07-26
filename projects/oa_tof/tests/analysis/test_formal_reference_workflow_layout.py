from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FormalReferenceWorkflowLayoutTests(unittest.TestCase):
    def test_production_entries_have_one_non_test_location(self):
        workflow_root = PROJECT_ROOT / "workflows" / "formal_reference"
        moved_names = {
            "run_coupled_baseline_validation.ps1",
            "run_formal_validation.ps1",
            "run_oatof_formal_cad_sync.m",
            "prepare_formal_vnext.py",
            "run_formal_vnext.py",
            "verify_geometry_contract.ps1",
            "verify_geometry_derivation.py",
        }
        self.assertEqual(
            {path.name for path in workflow_root.iterdir() if path.is_file()},
            moved_names,
        )
        for old_root in (
            PROJECT_ROOT / "tests" / "cross_solver",
            PROJECT_ROOT / "tests" / "cad",
        ):
            self.assertFalse(
                any((old_root / name).exists() for name in moved_names)
            )

    def test_gate_and_diagnostic_reference_the_canonical_geometry_gate(self):
        canonical = (
            "workflows\\formal_reference\\verify_geometry_contract.ps1"
        )
        verify_project = (PROJECT_ROOT / "verify_project.ps1").read_text(
            encoding="utf-8"
        )
        diagnostic = (
            PROJECT_ROOT
            / "simion"
            / "workbench"
            / "run_ideal_field_diagnostic.ps1"
        ).read_text(encoding="utf-8")
        self.assertEqual(verify_project.count(canonical), 2)
        self.assertEqual(diagnostic.count(canonical), 1)
        self.assertNotIn(
            "tests\\cross_solver\\verify_geometry_contract.ps1",
            verify_project + diagnostic,
        )

    def test_geometry_helper_uses_the_workflow_namespace(self):
        gate = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "projects.oa_tof.workflows.formal_reference."
            "verify_geometry_derivation",
            gate,
        )
        self.assertNotIn("projects.oa_tof.tests.cross_solver", gate)


if __name__ == "__main__":
    unittest.main()
