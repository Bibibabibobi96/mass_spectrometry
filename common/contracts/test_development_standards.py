import ast
import unittest

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
        lightweight = (self.repo_root / "common" / "verify_lightweight.ps1").read_text(
            encoding="utf-8"
        )
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
        self.assertIn("timeout-minutes: 5", workflow)
        self.assertIn("github.event.before", workflow)
        self.assertIn('git cat-file -e "$before^{commit}"', workflow)
        self.assertIn("$baseAvailable = $LASTEXITCODE -eq 0", workflow)
        self.assertNotIn("-not (& git cat-file", workflow)
        self.assertIn('"$before..$after"', workflow)
        self.assertIn("-ChangedPath $changedPaths", workflow)
        self.assertIn("$fallbackChangedPaths", workflow)
        self.assertIn("verify_changed.ps1", lightweight)
        self.assertNotIn("exit $LASTEXITCODE", lightweight)
        self.assertIn("Changed-scope gate failed", lightweight)
        self.assertIn("verify_development_standards.py", integration)
        self.assertIn("electron_impact_static", integration)
        self.assertIn("projects\\electron_impact_ion_source\\verify_project.ps1", integration)
        self.assertNotIn("verify_lightweight.ps1", hook)


if __name__ == "__main__":
    unittest.main()
