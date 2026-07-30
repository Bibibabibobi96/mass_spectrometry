from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGED_GATE = REPO_ROOT / "common" / "verify_changed.ps1"
INTEGRATION_GATE = REPO_ROOT / "common" / "verify_repository_integration.ps1"
LIGHTWEIGHT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lightweight-gate.yml"
QUADRUPOLE_GATE = (
    REPO_ROOT / "projects" / "rf_quadrupole_ion_optics" / "verify_project.ps1"
)


class ChangedGateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CHANGED_GATE.read_text(encoding="utf-8")

    def test_accepts_explicit_paths_and_discovers_worktree_changes(self) -> None:
        self.assertIn("[string[]]$ChangedPath", self.source)
        self.assertIn("git -C $repoRoot diff --name-only", self.source)
        self.assertIn("git -C $repoRoot ls-files --others --exclude-standard", self.source)
        self.assertIn("ChangedPath must be inside repository", self.source)
        self.assertIn("Changed-files gate cannot determine Git HEAD", self.source)
        self.assertIn("CHANGED_GATE_INPUT_SOURCE", self.source)

    def test_reports_run_skip_reasons_and_elapsed_time(self) -> None:
        self.assertIn("GATE_STAGE=RUN", self.source)
        self.assertIn("GATE_STAGE=SKIP", self.source)
        self.assertIn("ELAPSED_SECONDS", self.source)
        self.assertIn("repository_hygiene' 'always", self.source)

    def test_documentation_only_fast_path_is_narrow_and_explicit(self) -> None:
        self.assertIn("$isDocumentationOnly", self.source)
        self.assertIn("GetExtension($_).ToLowerInvariant() -ne '.md'", self.source)
        self.assertIn("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY", self.source)
        fast_path = self.source.index("if ($isDocumentationOnly)")
        development_gate = self.source.index("if ($hasCodeChange)")
        self.assertLess(fast_path, development_gate)

    def test_documentation_only_fast_path_runs_without_project_gates(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(CHANGED_GATE),
                "-PythonExe",
                sys.executable,
                "-ChangedPath",
                "CHANGELOG.md",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("GATE_STAGE=RUN NAME=documentation", completed.stdout)
        self.assertIn("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY", completed.stdout)
        self.assertNotIn("GATE_STAGE=RUN NAME=multipole_common", completed.stdout)
        self.assertNotIn(
            "GATE_STAGE=RUN NAME=rf_quadrupole_ion_optics_static",
            completed.stdout,
        )

    def test_deleted_python_paths_select_scope_but_are_not_passed_to_ruff(self) -> None:
        self.assertIn("$changedPython =", self.source)
        self.assertIn("$existingPythonFiles =", self.source)
        self.assertIn("Test-Path -LiteralPath $_ -PathType Leaf", self.source)
        self.assertIn("$existingPythonFiles.Count -gt 0", self.source)
        self.assertIn("@existingPythonFiles", self.source)
        self.assertIn("only_deleted_python_paths_changed", self.source)
        self.assertNotIn("@pythonFiles", self.source)

    def test_routes_project_config_to_its_own_static_gate(self) -> None:
        self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/", self.source)
        self.assertIn("projects/rf_quadrupole_ion_optics/", self.source)
        self.assertIn("projects/rf_hexapole_ion_optics/", self.source)
        self.assertIn("projects/rf_octupole_ion_optics/", self.source)
        self.assertIn("projects/transverse_helical_filament_wehnelt_electron_gun/", self.source)
        self.assertIn("projects/apertured_tube_electron_impact_ion_source/", self.source)

    def test_ci_fallback_uses_current_rf_project_paths(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("common/integration/README.md", workflow)
        self.assertIn("integrations/registry.json", workflow)
        for project_id in (
            "rf_quadrupole_ion_optics",
            "rf_hexapole_ion_optics",
            "rf_octupole_ion_optics",
        ):
            self.assertIn(f"projects/{project_id}/README.md", workflow)
        for legacy_id in (
            "rf_quadrupole_collision_cooling",
            "rf_hexapole_ion_guide",
            "rf_octupole_ion_guide",
        ):
            self.assertNotIn(f"projects/{legacy_id}/README.md", workflow)

    def test_multipole_common_routes_only_its_direct_family(self) -> None:
        self.assertIn("$hasMultipoleChange", self.source)
        self.assertIn("multipole_common", self.source)
        self.assertIn("multipole_foundation", self.source)
        self.assertIn("common_multipole_direct_dependency_changed", self.source)
        self.assertNotIn("single_reflection_oa_tof_mass_analyzer = (Test-PathPrefix 'projects/single_reflection_oa_tof_mass_analyzer/') -or $hasMultipoleChange", self.source)

    def test_common_contracts_routes_to_declared_direct_consumers(self) -> None:
        self.assertIn("common_contracts_direct_dependency_changed", self.source)
        self.assertIn("single_reflection_oa_tof_mass_analyzer = (Test-PathPrefix 'projects/single_reflection_oa_tof_mass_analyzer/') -or $hasContractsChange", self.source)
        self.assertIn("rf_quadrupole_ion_optics = (Test-PathPrefix 'projects/rf_quadrupole_ion_optics/') -or $hasContractsChange", self.source)
        self.assertIn("transverse_helical_filament_wehnelt_electron_gun = (Test-PathPrefix 'projects/transverse_helical_filament_wehnelt_electron_gun/') -or $hasContractsChange", self.source)
        self.assertIn("apertured_tube_electron_impact_ion_source = (Test-PathPrefix 'projects/apertured_tube_electron_impact_ion_source/') -or $hasContractsChange", self.source)

    def test_integration_changes_route_only_to_connection_gates(self) -> None:
        self.assertIn("$hasCommonIntegrationChange", self.source)
        self.assertIn("$hasIntegrationInstanceChange", self.source)
        self.assertIn("$hasComponentPortChange", self.source)
        self.assertIn("$hasIntegrationSchemaChange", self.source)
        self.assertIn("integration_common", self.source)
        self.assertIn(
            "rf_multipole_to_single_reflection_oatof_integration",
            self.source,
        )
        self.assertIn(
            "integrations\\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\\verify_integration.ps1",
            self.source,
        )

        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        self.assertIn("integration_common", integration_source)
        self.assertIn(
            "rf_multipole_to_single_reflection_oatof_integration",
            integration_source,
        )

    def test_handoff_publisher_routes_only_its_direct_integration_consumer(
        self,
    ) -> None:
        self.assertIn("$hasIntegrationHandoffPublisherChange", self.source)
        self.assertIn(
            "$_ -eq 'common/multipole/publish_three_mode_binding.py'",
            self.source,
        )
        integration_change_start = self.source.index("$hasIntegrationChange =")
        integration_change_end = self.source.index(
            "$hasSolidWorksChange",
            integration_change_start,
        )
        integration_change_block = self.source[
            integration_change_start:integration_change_end
        ]
        self.assertIn(
            "$hasIntegrationHandoffPublisherChange",
            integration_change_block,
        )
        self.assertNotIn("$hasMultipoleChange", integration_change_block)

    def test_gate_entrypoints_run_their_contract_tests(self) -> None:
        self.assertIn("$hasGateContractChange", self.source)
        self.assertIn("gate_contract_tests", self.source)
        self.assertIn("common.contracts.test_verify_changed", self.source)
        self.assertIn("common.contracts.test_development_standards", self.source)
        gate_contract_start = self.source.index("if ($hasGateContractChange)")
        gate_contract_end = self.source.index("} else { Skip-ChangedGateStage 'gate_contract_tests'", gate_contract_start)
        gate_contract_block = self.source[gate_contract_start:gate_contract_end]
        self.assertIn("Push-Location $repoRoot", gate_contract_block)
        self.assertIn("finally { Pop-Location }", gate_contract_block)
        for path in (
            "common/verify_changed.ps1",
            "common/verify_repository_integration.ps1",
            "common/verify_lightweight.ps1",
            "common/require_powershell7.ps1",
            ".github/workflows/lightweight-gate.yml",
        ):
            self.assertIn(path, self.source)

    def test_generated_publications_fail_before_long_test_suites(self) -> None:
        freshness = self.source.index(
            "Invoke-ChangedGateStage 'rf_quadrupole_generated_publications'"
        )
        common_contracts = self.source.index(
            "Invoke-ChangedGateStage 'common_contracts'"
        )
        multipole_common = self.source.index(
            "Invoke-ChangedGateStage 'multipole_common'"
        )
        self.assertLess(freshness, common_contracts)
        self.assertLess(freshness, multipole_common)
        self.assertIn("-Level Freshness -PythonExe $PythonExe", self.source)

        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        integration_freshness = integration_source.index(
            "Invoke-IntegrationStage 'rf_quadrupole_generated_publications'"
        )
        integration_contracts = integration_source.index(
            "Invoke-IntegrationStage 'common_contracts'"
        )
        self.assertLess(integration_freshness, integration_contracts)

        quadrupole_source = QUADRUPOLE_GATE.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('Freshness','Core','Static','Formal')]",
            quadrupole_source,
        )
        freshness_return = quadrupole_source.index(
            "if ($Level -eq 'Freshness')"
        )
        analysis_suite = quadrupole_source.index(
            "if ($Level -eq 'Core')"
        )
        self.assertLess(freshness_return, analysis_suite)

    def test_rf_quadrupole_uses_core_in_l1_and_static_in_l2(self) -> None:
        self.assertIn("$project -eq 'rf_quadrupole_ion_optics'", self.source)
        self.assertIn("& $projectScript -Level Core -PythonExe $PythonExe", self.source)
        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        self.assertIn(
            "rf_quadrupole_ion_optics\\verify_project.ps1') -Level Static",
            integration_source,
        )

    def test_excludes_commercial_and_formal_gate_levels(self) -> None:
        self.assertNotIn("-Level Candidate", self.source)
        self.assertNotIn("-Level Formal", self.source)
        self.assertNotIn("run_comsol_r2025b", self.source)
        self.assertNotIn("simion.exe", self.source)


if __name__ == "__main__":
    unittest.main()
