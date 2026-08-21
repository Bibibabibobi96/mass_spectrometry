from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FormalReferenceWorkflowLayoutTests(unittest.TestCase):
    def test_production_entries_have_one_non_test_location(self):
        workflow_root = PROJECT_ROOT / "workflows" / "formal_reference"
        moved_names = {
            "run_formal_validation.ps1",
            "verify_stable_entry.ps1",
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
            "projects.single_reflection_oa_tof_mass_analyzer.workflows.formal_reference."
            "verify_geometry_derivation",
            gate,
        )
        self.assertNotIn("projects.single_reflection_oa_tof_mass_analyzer.tests.cross_solver", gate)

    def test_single_formal_cli_has_explicit_phases_and_serializes_solvers(self):
        runner = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "run_formal_validation.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('Validate','Publish','Recover','Verify')]",
            runner,
        )
        self.assertIn("--recover", runner)
        self.assertIn("--verify-hashes", runner)
        self.assertIn("--project single_reflection_oa_tof_mass_analyzer", runner)
        self.assertIn(
            "projects.single_reflection_oa_tof_mass_analyzer.analysis."
            "publish_formal_release",
            runner,
        )
        self.assertIn("Copy-VerifiedRunInput", runner)
        self.assertIn("Complete-FailedRun", runner)
        self.assertLess(
            runner.index("$runRecordComplete = $false"),
            runner.index("Initialize-RunRecord"),
        )
        self.assertIn("$candidateManifestSource --require-status success", runner)
        self.assertIn("$candidateDiffPath", runner)
        self.assertIn("$candidateMphSource", runner)
        self.assertIn("$candidateSimionSource -Recurse -File", runner)
        self.assertIn("$candidateMph = Copy-VerifiedRunInput", runner)
        self.assertIn("$ion = Join-Path $candidateSimion", runner)
        self.assertIn("$iob = Join-Path $candidateSimion", runner)
        self.assertLess(
            runner.index("common\\comsol\\run_comsol_r2025b.ps1"),
            runner.index("Start-Process -FilePath $SimionExe"),
        )
        self.assertLess(
            runner.index("Start-Process -FilePath $SimionExe"),
            runner.index("analysis.reference_analysis compare"),
        )
        for retired in (
            "run_formal_vnext_validation.ps1",
            "run_oatof_formal_cad_sync.m",
        ):
            self.assertFalse(
                (
                    PROJECT_ROOT
                    / "workflows"
                    / "formal_reference"
                    / retired
                ).exists()
            )
        self.assertFalse(
            (PROJECT_ROOT / "analysis" / "publish_formal_validation.py").exists()
        )
        self.assertFalse(
            (PROJECT_ROOT / "analysis" / "promote_formal_vnext.py").exists()
        )
        self.assertFalse(
            (
                PROJECT_ROOT
                / "workflows"
                / "formal_reference"
                / "run_coupled_baseline_validation.ps1"
            ).exists()
        )
        self.assertTrue(
            (PROJECT_ROOT / "analysis" / "publish_formal_release.py").is_file()
        )

    def test_formal_runtime_accepts_governed_result_generations(self):
        gate = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'formal_n1000_coupled_longitudinal'", gate)
        self.assertIn("'formal_vnext_zero_physics_change_n1000'", gate)
        self.assertIn(
            "$allowedFormalResultStatuses -cnotcontains "
            "[string]$formalAssets.results.status",
            gate,
        )
        self.assertNotIn(
            "$formalAssets.results.status -ne 'formal_n1000_coupled_longitudinal'",
            gate,
        )

    def test_formal_runtime_uses_immutable_simion_manifests_not_git_source_hashes(self):
        gate = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        stable_gate = (
            PROJECT_ROOT / "workflows" / "formal_reference" / "verify_stable_entry.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$formalAssets.simion_manifest", gate)
        self.assertIn("verify_stable_entry.ps1", gate)
        self.assertIn("artifact_workspace_relative -ne 'formal'", stable_gate)
        self.assertIn("$entry.manifests.formal_asset_manifest", stable_gate)
        self.assertIn("$entry.manifests.simion_delivery_manifest", stable_gate)
        self.assertIn("program = 'simion_program'", stable_gate)
        self.assertIn("fly2 = 'simion_fly2'", stable_gate)
        self.assertNotIn(
            "Get-FileHash -LiteralPath $simionLua", gate
        )
        self.assertNotIn(
            "Get-FileHash -LiteralPath $simionFly2", gate
        )


if __name__ == "__main__":
    unittest.main()
