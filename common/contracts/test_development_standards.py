import ast
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from common import verify_development_standards as standards


class MatlabBuildOnlyContractTests(unittest.TestCase):
    example_path = standards.REPO_ROOT / "common" / "example.m"

    def test_unmarked_matlab_may_create_a_study(self):
        source = "model.study.create('std1');"
        self.assertEqual(standards.check_matlab_source(self.example_path, source), [])

    def test_marked_matlab_rejects_solver_operations(self):
        source = "\n".join(
            (
                "% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY",
                "model.study.create('std1');",
                "mphsave(model, outputPath);",
            )
        )
        errors = standards.check_matlab_source(self.example_path, source)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("MATLAB_BUILD_ONLY" in error for error in errors))

    def test_marked_matlab_allows_geometry_run(self):
        source = "\n".join(
            (
                "% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY",
                "geom.feature.create('vac', 'Cylinder');",
                "geom.run;",
                "mphgeominfo(model, 'geom1');",
            )
        )
        self.assertEqual(standards.check_matlab_source(self.example_path, source), [])

    def test_marked_matlab_ignores_forbidden_words_in_comments(self):
        source = "\n".join(
            (
                "% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY",
                "% Never call model.study.create or mphsave from this task.",
                "geom.run;",
            )
        )
        self.assertEqual(standards.check_matlab_source(self.example_path, source), [])


class PowerShellRuntimeContractTests(unittest.TestCase):
    example_path = standards.REPO_ROOT / "common" / "example.py"

    def check(self, source: str) -> list[str]:
        return standards.check_legacy_powershell_launchers(
            self.example_path, ast.parse(source)
        )

    def test_rejects_legacy_powershell_command_argv(self):
        errors = self.check(
            'subprocess.run(["powershell", "-File", "task.ps1"], cwd=root, timeout=30)'
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("legacy PowerShell", errors[0])

    def test_rejects_powershell_exe_command_preview(self):
        errors = self.check('argv = ["powershell.exe", "-NoProfile", "-File", task]')
        self.assertEqual(len(errors), 1)
        self.assertIn("legacy PowerShell", errors[0])

    def test_allows_pwsh_and_explanatory_text(self):
        source = '''
"""Explain why Windows PowerShell 5.1 is unsupported."""
command = ["pwsh.exe", "-NoProfile", "-File", task]
'''
        self.assertEqual(self.check(source), [])


class LightweightGateIntegrationTests(unittest.TestCase):
    repo_root = standards.REPO_ROOT

    def test_local_hook_and_ci_share_the_development_standards_gate(self):
        hook = (self.repo_root / ".githooks" / "pre-commit").read_text(
            encoding="utf-8"
        )
        workflow = (
            self.repo_root / ".github" / "workflows" / "lightweight-gate.yml"
        ).read_text(encoding="utf-8")
        integration = (
            self.repo_root / "common" / "verify_repository_integration.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("common/verify_development_standards.py", hook)
        self.assertIn('"3.11"', hook)
        normalized_workflow = workflow.replace("\\", "/")
        self.assertIn("common/verify_changed.ps1", normalized_workflow)
        self.assertIn("common/verify_repository_integration.ps1", normalized_workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("RF quadrupole L1 uses the measured ~21 s Core contract gate", workflow)
        self.assertIn("timeout-minutes: 8", workflow)
        self.assertNotIn("timeout-minutes: 5", workflow)
        self.assertIn("github.event.before", workflow)
        self.assertIn('git cat-file -e "$before^{commit}"', workflow)
        self.assertIn("$baseAvailable = $LASTEXITCODE -eq 0", workflow)
        self.assertNotIn("-not (& git cat-file", workflow)
        self.assertIn('"$before..$after"', workflow)
        self.assertIn("-ChangedPath $scope.changed_paths", workflow)
        self.assertIn("-ChangedPath @($scope.changed_paths)", workflow)
        self.assertIn("-FullScope", workflow)
        self.assertNotIn("$fallbackChangedPaths", workflow)
        self.assertIn("verify_development_standards.py", integration)
        self.assertIn("Read-GateCatalog", integration)
        self.assertIn("repository_integration_group -eq 'regression'", integration)
        self.assertNotIn("verify_lightweight.ps1", hook)
        self.assertFalse((self.repo_root / "common" / "verify_lightweight.ps1").exists())

    def test_repository_root_temporary_directories_fail_hygiene(self):
        hygiene = (
            self.repo_root / "common" / "verify_repository_hygiene.ps1"
        ).read_text(encoding="utf-8")
        adapter_test = (
            self.repo_root / "common" / "integration" / "test_adapter_contract.py"
        ).read_text(encoding="utf-8")
        family_test = (
            self.repo_root
            / "integrations"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "tests"
            / "test_family_source_closure_workflow.py"
        ).read_text(encoding="utf-8")
        self.assertIn("@('.tmp', 'scratch')", hygiene)
        self.assertIn("repository root must not contain temporary directory", hygiene)
        self.assertNotIn('REPO_ROOT / ".tmp"', adapter_test)
        self.assertNotIn('REPO_ROOT / ".tmp"', family_test)

    def test_hygiene_accepts_a_standalone_ci_checkout(self):
        hygiene = (
            self.repo_root / "common" / "verify_repository_hygiene.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$workspaceManaged", hygiene)
        self.assertIn("standalone_repository_checkout", hygiene)
        self.assertIn("if ($workspaceManaged)", hygiene)
        artifacts_enumeration = (
            "Get-ChildItem -Force -LiteralPath $artifactsRoot"
        )
        self.assertGreater(
            hygiene.index(artifacts_enumeration),
            hygiene.index("if ($workspaceManaged)"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            common = checkout / "common"
            common.mkdir(parents=True)
            script = common / "verify_repository_hygiene.ps1"
            shutil.copy2(
                self.repo_root / "common" / "verify_repository_hygiene.ps1",
                script,
            )
            subprocess.run(
                ["git", "init", "--quiet", str(checkout)],
                cwd=checkout,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                cwd=checkout,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("standalone_repository_checkout", completed.stdout)
            self.assertIn("REPOSITORY_HYGIENE=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
