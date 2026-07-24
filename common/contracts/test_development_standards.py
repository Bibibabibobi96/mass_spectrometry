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

if __name__ == "__main__":
    unittest.main()
