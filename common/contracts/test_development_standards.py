import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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


class DevelopmentStandardsCoverageTests(unittest.TestCase):
    def test_default_and_complexity_review_do_not_run_consumer_audit(self):
        for arguments in ([], ["--show-review"]):
            with self.subTest(arguments=arguments), patch.object(
                standards, "check_python", return_value=([], [])
            ), patch.object(standards, "check_powershell", return_value=[]), patch.object(
                standards, "check_matlab", return_value=[]
            ), patch.object(standards, "audit_consumers") as audit, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(standards.main(arguments), 0)
                audit.assert_not_called()
                self.assertIn("CONSUMER_AUDIT=NOT_REQUESTED", output.getvalue())
                self.assertNotIn("PRIVATE_NO_CALLS=0", output.getvalue())

    def test_explicit_consumer_audit_reuses_hard_check_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            (common / "subject.py").write_text("def _unused():\n    return 1\n", encoding="utf-8")
            with patch.object(standards, "REPO_ROOT", root), patch.object(
                standards, "SOURCE_ROOTS", (common,)
            ), patch.object(standards.ast, "parse", wraps=ast.parse) as parse, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(standards.main(["--audit-consumers"]), 0)
                self.assertEqual(parse.call_count, 1)
                self.assertIn("CONSUMER_AUDIT=STATIC_MODULE_REFERENCES", output.getvalue())
                self.assertIn("PRIVATE_NO_CALLS=1", output.getvalue())

    def test_integrations_are_part_of_python_and_powershell_scan_roots(self):
        integration_root = standards.REPO_ROOT / "integrations"
        self.assertIn(integration_root, standards.SOURCE_ROOTS)
        python_paths = standards.active_files(".py")
        powershell_paths = standards.active_files(".ps1")
        self.assertTrue(any(path.is_relative_to(integration_root) for path in python_paths))
        self.assertTrue(any(path.is_relative_to(integration_root) for path in powershell_paths))

    def test_repository_entrypoints_do_not_repair_import_paths_at_runtime(self):
        for relative_path in (
            "projects/apertured_tube_electron_impact_ion_source/analysis/resolve_contract.py",
            "integrations/runtime/refresh_repository_bindings.py",
        ):
            source = (standards.REPO_ROOT / relative_path).read_text(encoding="utf-8")
            tree = ast.parse(source)
            self.assertEqual(
                [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "sys"
                    and node.func.value.attr == "path"
                ],
                [],
                relative_path,
            )


class LightweightGateIntegrationTests(unittest.TestCase):
    repo_root = standards.REPO_ROOT

    def test_local_hook_and_ci_share_the_development_standards_gate(self):
        hook = (self.repo_root / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        workflow = (
            self.repo_root / ".github" / "workflows" / "lightweight-gate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("common/verify_development_standards.py", hook)
        self.assertIn('"3.11"', hook)
        normalized_workflow = workflow.replace("\\", "/")
        self.assertIn("common/verify_changed.ps1", normalized_workflow)
        self.assertIn("common/verify_repository_integration.ps1", normalized_workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("fetch-depth: 0", workflow)

    def test_hygiene_allows_only_canonical_shared_iob_seed_binaries(self):
        hygiene = (
            self.repo_root / "common" / "verify_repository_hygiene.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$sharedIobSeedPrefix", hygiene)
        self.assertIn("iob_seed_placeholder_01.pa0", hygiene)
        self.assertIn("10_instance_seed.iob", hygiene)
        self.assertIn("-not $isSharedIobSeed", hygiene)

    def test_hygiene_allows_only_registered_artifact_root_directories(self):
        hygiene = (
            self.repo_root / "common" / "verify_repository_hygiene.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("@('projects', 'common')", hygiene)
        self.assertIn("artifacts root contains unregistered entry", hygiene)
        self.assertNotIn("verify_artifact_layout $artifactProjectsRoot", hygiene)
        self.assertNotIn("verify_artifact_layout.py $artifactProjectsRoot", hygiene)

    def test_hygiene_accepts_a_standalone_ci_checkout(self):
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
            for name in ("tmp", "new", "artifacts", "scratch", "unregistered-output"):
                with self.subTest(directory=name):
                    debris = checkout / name
                    debris.mkdir()
                    rejected = subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(script)],
                        cwd=checkout, capture_output=True, text=True, timeout=30,
                    )
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn("unregistered directory", rejected.stderr)
                    debris.rmdir()
            (checkout / "debug.log").write_text("failed test output", encoding="utf-8")
            rejected = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                cwd=checkout, capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("tool artifact", rejected.stderr)


class StagedDevelopmentStandardsTests(unittest.TestCase):
    def git(self, root: Path, *arguments: str) -> subprocess.CompletedProcess:
        environment = dict(os.environ)
        environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
        return subprocess.run(
            ["git", *arguments], cwd=root, timeout=30, capture_output=True,
            text=True, encoding="utf-8", env=environment,
        )

    def prepare(self, root: Path) -> Path:
        common = root / "common"
        common.mkdir()
        hooks = root / ".githooks"
        hooks.mkdir()
        checker = common / "verify_development_standards.py"
        shutil.copyfile(standards.REPO_ROOT / "common/verify_development_standards.py", checker)
        shutil.copyfile(standards.REPO_ROOT / ".githooks/pre-commit", hooks / "pre-commit")
        (hooks / "pre-commit").chmod(0o755)
        self.assertEqual(self.git(root, "init", "--quiet").returncode, 0)
        self.assertEqual(self.git(root, "config", "core.autocrlf", "false").returncode, 0)
        self.assertEqual(self.git(root, "config", "core.hooksPath", ".githooks").returncode, 0)
        self.assertEqual(self.git(root, "add", "--", "common", ".githooks").returncode, 0)
        return checker

    def run_hook(self, root: Path) -> subprocess.CompletedProcess:
        # A disposable repository commit exercises Git's actual hook path,
        # including Git versions predating the standalone `git hook` command.
        return self.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "--quiet", "-m", "Check staged development standards")

    def test_actual_hook_checks_index_not_worktree_in_both_directions(self):
        good = "def sample(values=None):\n    return values\n"
        bad = "def sample(values=[]):\n    return values\n"
        for staged, worktree, accepted in ((bad, good, False), (good, bad, True)):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.prepare(root)
                subject = root / "common" / "subject with spaces.py"
                subject.write_text(staged, encoding="utf-8", newline="\n")
                self.assertEqual(self.git(root, "add", "--", str(subject)).returncode, 0)
                subject.write_text(worktree, encoding="utf-8", newline="\n")
                completed = self.run_hook(root)
                output = completed.stdout + completed.stderr
                self.assertEqual(completed.returncode == 0, accepted, output)
                self.assertIn("CONSUMER_AUDIT=NOT_REQUESTED", output)
                self.assertEqual("mutable default argument" in output, not accepted)

    def test_hook_executes_staged_checker_when_worktree_checker_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checker = self.prepare(root)
            checker.write_text("raise RuntimeError('unstaged checker must not execute')\n", encoding="utf-8")
            completed = self.run_hook(root)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("DEVELOPMENT_STANDARDS=PASS", completed.stdout + completed.stderr)

    def test_unstaged_checker_repair_cannot_hide_a_staged_rule_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checker = self.prepare(root)
            source = checker.read_text(encoding="utf-8")
            checker.write_text(source + "\ndef accidental(values=[]):\n    return values\n", encoding="utf-8", newline="\n")
            self.assertEqual(self.git(root, "add", "--", "common/verify_development_standards.py").returncode, 0)
            checker.write_text(source, encoding="utf-8", newline="\n")
            completed = self.run_hook(root)
            output = completed.stdout + completed.stderr
            self.assertNotEqual(completed.returncode, 0, output)
            self.assertIn("mutable default argument in accidental", output)

    def test_unmerged_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            blob = self.git(root, "rev-parse", ":common/verify_development_standards.py").stdout.strip()
            indexed = subprocess.run(
                ["git", "update-index", "--index-info"], cwd=root, timeout=30, check=True,
                input=f"100644 {blob} 1\tcommon/conflicted.py\n100644 {blob} 2\tcommon/conflicted.py\n".encode("ascii"),
                capture_output=True,
            )
            self.assertEqual(indexed.returncode, 0)
            with self.assertRaisesRegex(ValueError, "unmerged index"):
                standards.staged_sources(root)

    def test_index_snapshot_checks_powershell_matlab_and_excludes_deleted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            (root / "common/bad.ps1").write_text("Write-Output 'missing policy'\n", encoding="utf-8", newline="\n")
            (root / "common/bad.m").write_text("% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY\nmodel.study.create('s');\n", encoding="utf-8", newline="\n")
            deleted = root / "common/deleted.py"
            deleted.write_text("def example(values=[]):\n    return values\n", encoding="utf-8", newline="\n")
            self.assertEqual(self.git(root, "add", "--", "common").returncode, 0)
            self.assertEqual(self.git(root, "rm", "--cached", "--", "common/deleted.py").returncode, 0)
            completed = self.run_hook(root)
            output = completed.stdout + completed.stderr
            self.assertNotEqual(completed.returncode, 0, output)
            self.assertIn("PowerShell omits", output)
            self.assertIn("MATLAB_BUILD_ONLY creates a study", output)
            self.assertNotIn("deleted.py", output)


class ConsumerAuditTests(unittest.TestCase):
    def write(self, root: Path, relative: str, source: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_four_categories_preserve_cli_callbacks_and_test_only_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "common/subject.py", "\n".join(
                f"def {name}():\n    return 1" for name in
                ("_formal", "_only_test", "_cli", "_dead", "_callback")))
            self.write(root, "projects/example/config/execution_profiles.json",
                       '{"profiles":[{"steps":[{"entrypoint":"entry.py"}]}]}')
            self.write(root, "projects/example/entry.py",
                       "from common.subject import _formal as run\nrun()")
            self.write(root, "common/test_subject.py",
                       "from common.subject import _only_test\n_only_test()")
            self.write(root, "common/independent_cli.py",
                       "from common.subject import _cli\nif __name__ == '__main__':\n    _cli()")
            self.write(root, "projects/example/callbacks.json", '{"callback":"_callback"}')
            result = {row["symbol"]: row for row in standards.audit_consumers(root)}
            parsed = {path: ast.parse(path.read_text(encoding="utf-8")) for path in root.rglob("*.py")}
            self.assertEqual(result, {row["symbol"]: row for row in standards.audit_consumers(root, parsed=parsed)})
            self.assertEqual(result["_formal"]["category"], "formal_reachable")
            self.assertEqual(result["_only_test"]["category"], "test_only_reachable")
            self.assertEqual(result["_cli"]["category"], "cli_callback_uncertain")
            self.assertEqual(result["_callback"]["category"], "cli_callback_uncertain")
            self.assertEqual(result["_dead"]["category"], "private_no_calls")
            self.assertIn("manual_confirmation", result["_dead"]["reason"])
            self.assertEqual(result["_formal"]["consumer_modules"], "projects.example.entry")

    def test_relative_lazy_imports_and_cycles_reach_declared_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "projects/example/config/execution_profiles.json",
                       '{"profiles":[{"entrypoint":"analysis/entry.py"}]}')
            self.write(root, "projects/example/analysis/entry.py", """
def run():
    from . import helpers as dependency
    return dependency._helper()
run()
""")
            self.write(root, "projects/example/analysis/helpers.py", """
from . import entry
def _helper():
    return 1
""")
            result = standards.audit_consumers(root)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["category"], "formal_reachable")

    def test_literal_powershell_module_and_qualified_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "projects/example/config/execution_profiles.json",
                       '{"profiles":[{"entrypoint":"run.ps1"}]}')
            self.write(root, "projects/example/run.ps1", "& $python -m projects.example.entry")
            self.write(root, "projects/example/entry.py", "import common.subject as api\napi._work()")
            self.write(root, "common/subject.py", "def _work():\n    return 1")
            self.assertEqual(standards.audit_consumers(root)[0]["category"], "formal_reachable")

    def test_decorators_reflection_and_cross_language_names_are_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "common/decorated.py", "@staticmethod\ndef _registered():\n    return 1")
            self.write(root, "common/reflected.py", "def _reflect():\n    return 1\nregistry=globals()")
            self.write(root, "common/external.py", "def _callback():\n    return 1")
            self.write(root, "projects/example/callback.lua", "callback = '_callback'")
            self.assertTrue(all(row["category"] == "cli_callback_uncertain"
                                for row in standards.audit_consumers(root)))

    def test_gate_catalog_production_command_is_root_but_unittest_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "common/gate_catalog.json", '''{"routes":[
                {"command":{"runner":"python","arguments":["common/entry.py"]}},
                {"command":{"runner":"python","arguments":["-m","unittest","common.test_case"]}}
            ]}''')
            self.write(root, "common/entry.py", "from common.subject import _production\n_production()")
            self.write(root, "common/test_case.py", "from common.subject import _tested\n_tested()")
            self.write(root, "common/subject.py", "def _production():\n    pass\ndef _tested():\n    pass")
            result = {row["symbol"]: row for row in standards.audit_consumers(root)}
            self.assertEqual(result["_production"]["category"], "formal_reachable")
            self.assertEqual(result["_tested"]["category"], "test_only_reachable")

    def test_same_import_alias_in_multiple_scopes_cannot_hide_a_consumer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "projects/example/config/execution_profiles.json",
                       '{"profiles":[{"entrypoint":"entry.py"}]}')
            self.write(root, "projects/example/entry.py", """
import common.first as dependency
dependency._first()
def other():
    import common.second as dependency
    return dependency._second()
""")
            self.write(root, "common/first.py", "def _first():\n    return 1")
            self.write(root, "common/second.py", "def _second():\n    return 2")
            result = standards.audit_consumers(root)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(row["category"] == "formal_reachable" for row in result))

    def test_history_syntax_errors_and_public_functions_are_not_dead_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "common/history/old.py", "def _archived():\n    pass")
            self.write(root, "common/broken.py", "def :")
            self.write(root, "common/public.py", "def public_api():\n    pass")
            self.assertEqual(standards.audit_consumers(root), [])


if __name__ == "__main__":
    unittest.main()
