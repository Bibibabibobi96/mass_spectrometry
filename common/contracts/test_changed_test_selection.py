"""Exercise changed-test discovery and failure propagation through the real L1 gate."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MR = "projects/parallel_mirror_dual_stripe_mr_tof"
RF = "projects/rf_multipole_ion_optics"


def powershell_literal(value: str | Path) -> str:
    """Quote a literal PowerShell argument without interpolation."""
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is required")
class ChangedTestSelectionTests(unittest.TestCase):
    def selection(self, root: Path, stage: str, paths: list[str]) -> dict:
        script = (
            ". ./common/gate_catalog_support.ps1; "
            "$routes=@(Read-GateCatalog -RepoRoot $PWD.Path); "
            "$roots=@($routes | Where-Object { $null -ne $_.PSObject.Properties['test_selection'] } "
            "| ForEach-Object { @($_.test_selection.roots) }); "
            "$route=$routes | Where-Object { $_.stage -eq " + powershell_literal(stage) + " }; "
            "Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots $roots "
            "-ChangedPaths @(" + ",".join(map(powershell_literal, paths)) + ") | ConvertTo-Json -Depth 8"
        )
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_existing_modules_and_support_have_explicit_selection(self) -> None:
        for prefix, stage, filename in (
            (MR, "parallel_mirror_dual_stripe_mr_tof_static", "test_simion_event_analysis.py"),
            (RF, "rf_multipole_quadrupole_static", "test_mass_filter_l1.py"),
        ):
            changed = f"{prefix}/tests/analysis/{filename}"
            selected = self.selection(REPO_ROOT, stage, [changed])
            self.assertEqual(selected["Modules"], [changed])
            self.assertFalse(selected["Expanded"])
            mixed = self.selection(REPO_ROOT, stage, [changed, f"{prefix}/analysis/source.py"])
            self.assertFalse(mixed["OnlyTestModules"])
            for path in (f"{prefix}/tests/analysis/test_deleted.py",
                         f"{prefix}/tests/analysis/__init__.py",
                         f"{prefix}/tests/test_support/fixture.py"):
                selected = self.selection(REPO_ROOT, stage, [path])
                self.assertTrue(selected["Expanded"], path)
                self.assertIn(changed, selected["Modules"], path)

    def test_unknown_fixture_and_deleted_test_execute_the_remaining_owner_tests(self) -> None:
        with tempfile.TemporaryDirectory(prefix="changed_owner_discovery_") as directory:
            root = Path(directory)
            known = root / "owner/tests/analysis/test_known.py"
            unknown = root / "owner/tests/new_area/test_remaining.py"
            known.parent.mkdir(parents=True)
            unknown.parent.mkdir(parents=True)
            known.write_text("import unittest\nclass Known(unittest.TestCase):\n"
                             "    def test_pass(self): self.assertTrue(True)\n", encoding="utf-8")
            unknown.write_text("import unittest\nclass Remaining(unittest.TestCase):\n"
                               "    def test_failure(self): self.fail('UNKNOWN_OWNER_TEST_EXECUTED')\n",
                               encoding="utf-8")
            for changed in ("owner/tests/new_area/helper.py", "owner/tests/new_area/test_deleted.py"):
                with self.subTest(changed=changed):
                    script = (
                        ". " + powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1") + "; "
                        "$route=[pscustomobject]@{test_selection=[pscustomobject]@{"
                        "roots=@('owner/tests/analysis/');scope='owner/tests/'}}; "
                        "$selection=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path "
                        "-KnownTestRoots @('owner/tests/analysis/') -ChangedPaths @(" +
                        powershell_literal(changed) + "); "
                        "$selection | ConvertTo-Json -Depth 8"
                    )
                    result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root,
                                            capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    selection = json.loads(result.stdout)
                    self.assertTrue(selection["Expanded"])
                    self.assertIn("owner/tests/new_area/test_remaining.py", selection["Modules"])
                    executed = subprocess.run([sys.executable, "-m", "unittest", *selection["Modules"]],
                                              cwd=root, capture_output=True, text=True,
                                              encoding="utf-8", timeout=30)
                    self.assertNotEqual(executed.returncode, 0)
                    self.assertIn("UNKNOWN_OWNER_TEST_EXECUTED", executed.stderr)
                    self.assertIn("Ran 2 tests", executed.stderr)

    def test_shared_rf_support_keeps_owner_module_sets_disjoint(self) -> None:
        for changed in (f"{RF}/tests/test_support/fixture.py", f"{RF}/tests/__init__.py"):
            all_modules: set[str] = set()
            for owner, directory in (("quadrupole_static", "analysis"), ("hexapole_static", "hexapole"),
                                     ("octupole_static", "octupole"), ("domain_tests", "domain")):
                selected = self.selection(REPO_ROOT, "rf_multipole_" + owner, [changed])
                modules = set(selected["Modules"])
                self.assertTrue(modules)
                self.assertTrue(all(path.startswith(f"{RF}/tests/{directory}/") for path in modules))
                self.assertFalse(all_modules.intersection(modules))
                all_modules.update(modules)

    def test_catalog_import_roots_preserve_and_restore_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory(prefix="changed_import_environment_") as directory:
            root = Path(directory)
            names = ("owner first", "owner second", "existing first", "existing second")
            for index, name in enumerate(names):
                path = root / name
                path.mkdir()
                (path / f"import_root_{index}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
                (path / "import_precedence.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
            for inherited in (None, "", os.pathsep.join(str(root / name) for name in names[2:])):
                for include_roots in (False, True):
                    for exit_code in (0, 7):
                        with self.subTest(inherited=inherited, roots=include_roots, exit_code=exit_code):
                            expected = inherited
                            if include_roots:
                                expected = os.pathsep.join(str(root / name) for name in names[:2])
                                if inherited is not None:
                                    expected += os.pathsep + inherited
                            probe = ["import os, sys", f"assert os.environ.get('PYTHONPATH') == {expected!r}"]
                            if include_roots:
                                probe.extend(["import import_root_0, import_root_1, import_precedence",
                                              "assert import_root_0.VALUE == 0 and import_root_1.VALUE == 1",
                                              "assert import_precedence.VALUE == 0"])
                            if inherited:
                                probe.extend(["import import_root_2, import_root_3",
                                              "assert import_root_2.VALUE == 2 and import_root_3.VALUE == 3"])
                            probe.extend(["print('IMPORT_ROOTS_OBSERVED')", f"sys.exit({exit_code})"])
                            initial = "$null" if inherited is None else powershell_literal(inherited)
                            initial_value = "[NullString]::Value" if inherited is None else "$initial"
                            roots_property = ("; python_path_roots=@('owner first','owner second')"
                                              if include_roots else "")
                            script = (
                                ". " + powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1") + "; "
                                "$initial=" + initial + "; "
                                "[Environment]::SetEnvironmentVariable('PYTHONPATH'," + initial_value + ",'Process'); "
                                "$command=[pscustomobject]@{runner='python';arguments=@('-c'," +
                                powershell_literal("; ".join(probe)) + ")" + roots_property + "}; "
                                "$failed=$false; try { Invoke-GateCatalogCommand -Command $command "
                                "-RepoRoot " + powershell_literal(root) + " -PythonExe " +
                                powershell_literal(sys.executable) + " } catch { $failed=$true }; "
                                "if ($failed -ne " + ("$true" if exit_code else "$false") +
                                ") { throw 'Unexpected command result' }; "
                                "if ([Environment]::GetEnvironmentVariable('PYTHONPATH','Process') -cne $initial) "
                                "{ throw 'PYTHONPATH was not restored' }; "
                                "Write-Output 'PYTHONPATH_RESTORED'; exit 0"
                            )
                            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root,
                                                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            self.assertIn("IMPORT_ROOTS_OBSERVED", result.stdout)
                            self.assertIn("PYTHONPATH_RESTORED", result.stdout)

    def test_exact_selection_retains_existing_discovery_imports_in_real_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="changed_existing_imports_") as directory:
            root = Path(directory)
            modules = ["test_artifact_naming.py", "test_artifact_project.py",
                       "test_particle_state.py", "test_project_registry.py"]
            request = root / "request.json"
            request.write_text(json.dumps({"python_exe": sys.executable,
                                           "changed_paths": ["common/contracts/" + name for name in modules],
                                           "full_scope": False}), encoding="utf-8")
            log = root / "stage.log"
            environment = dict(os.environ, TEMP=directory, TMP=directory, PYTHONDONTWRITEBYTECODE="1")
            environment.pop("PYTHONPATH", None)
            environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = os.environ.get(
                "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH",
                str(REPO_ROOT.parent / "artifacts/common/host_resources.sqlite3"),
            )
            result = subprocess.run([
                "pwsh", "-NoProfile", "-File", str(REPO_ROOT / "common/verify_changed.ps1"),
                "-InternalStage", "common_contracts", "-InternalRequestPath", str(request),
                "-InternalLogPath", str(log),
            ], cwd=REPO_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180)
            output = result.stdout + result.stderr + log.read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("Ran 33 tests", output)
            self.assertIn("GATE_STAGE=PASS NAME=common_contracts", output)

    def copy_checkout(self, root: Path) -> None:
        clone = subprocess.run(["git", "-c", "core.longpaths=true", "clone", "--quiet", "--shared",
                                "-c", "core.longpaths=true", "-c", "core.autocrlf=false",
                                str(REPO_ROOT), str(root)],
                               cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(clone.returncode, 0, clone.stdout + clone.stderr)
        # Include the implementation under test before its eventual commit.
        changed = subprocess.run(["git", "diff", "--name-only", "--no-renames", "HEAD"],
                                 cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                   cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(untracked.returncode, 0, untracked.stderr)
        for relative in changed.stdout.splitlines() + untracked.stdout.splitlines():
            source, target = REPO_ROOT / relative, root / relative
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            elif target.is_file():
                target.unlink()

    def test_expanded_and_full_scope_use_namespace_modules_in_real_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="changed_dispatch_checkout_") as workspace, \
                tempfile.TemporaryDirectory(prefix="changed_dispatch_logs_") as logs:
            root = Path(workspace) / "checkout"
            self.copy_checkout(root)
            fixture_root = "common/contracts/selection_fixture/"
            known = root / fixture_root / "test_known.py"
            unknown = root / fixture_root / "new_area/test_failure.py"
            unknown.parent.mkdir(parents=True)
            (known.parent / "selection_import_probe.py").write_text("VALUE = 17\n", encoding="utf-8")
            known.write_text("import unittest\nfrom selection_import_probe import VALUE\n"
                             "class Known(unittest.TestCase):\n"
                             "    def test_pass(self): self.assertEqual(VALUE, 17)\n", encoding="utf-8")
            unknown.write_text("import unittest\nfrom selection_import_probe import VALUE\n"
                               "class Remaining(unittest.TestCase):\n"
                               "    def test_failure(self): self.fail('NAMESPACE_TEST_EXECUTED')\n",
                               encoding="utf-8")
            catalog_path = root / "common/gate_catalog.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            owner = next(row for row in catalog["routes"] if row["stage"] == "common_contracts")
            owner["test_selection"] = {"roots": [fixture_root]}
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8", newline="\n")
            environment = dict(os.environ, TEMP=logs, TMP=logs, PYTHONDONTWRITEBYTECODE="1")
            environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = os.environ.get(
                "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH",
                str(REPO_ROOT.parent / "artifacts/common/host_resources.sqlite3"),
            )
            for index, changed in enumerate((fixture_root + "new_area/helper.py",
                                             fixture_root + "new_area/test_deleted.py", None)):
                with self.subTest(changed=changed):
                    request = Path(logs) / f"request_{index}.json"
                    request.write_text(json.dumps({"python_exe": sys.executable,
                                                   "changed_paths": [changed] if changed else [],
                                                   "full_scope": changed is None}), encoding="utf-8")
                    log = Path(logs) / f"stage_{index}.log"
                    result = subprocess.run([
                        "pwsh", "-NoProfile", "-File", str(root / "common/verify_changed.ps1"),
                        "-InternalStage", "common_contracts", "-InternalRequestPath", str(request),
                        "-InternalLogPath", str(log),
                    ], cwd=root, env=environment, capture_output=True, text=True,
                        encoding="utf-8", timeout=180)
                    output = result.stdout + result.stderr + log.read_text(encoding="utf-8")
                    self.assertNotEqual(result.returncode, 0, output)
                    self.assertIn("NAMESPACE_TEST_EXECUTED", output)
                    self.assertIn("Ran 2 tests", output)

    def test_real_l1_rejects_existing_and_new_mr_rf_tests(self) -> None:
        # This is an isolated source checkout, not a fake gate or scheduler.
        with tempfile.TemporaryDirectory(prefix="changed_test_checkout_") as workspace, \
                tempfile.TemporaryDirectory(prefix="changed_test_logs_") as logs:
            root = Path(workspace) / "checkout"
            self.copy_checkout(root)
            environment = dict(os.environ, TEMP=logs, TMP=logs, PYTHONDONTWRITEBYTECODE="1")
            environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = os.environ.get(
                "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH",
                str(REPO_ROOT.parent / "artifacts/common/host_resources.sqlite3"),
            )
            cases = (
                (MR, "test_simion_event_analysis.py", "parallel_mirror_dual_stripe_mr_tof_static"),
                (MR, "test_changed_gate_probe.py", "parallel_mirror_dual_stripe_mr_tof_static"),
                (RF, "test_mass_filter_l1.py", "rf_multipole_quadrupole_static"),
                (RF, "test_changed_gate_probe.py", "rf_multipole_quadrupole_static"),
            )
            try:
                for index, (prefix, filename, stage) in enumerate(cases):
                    relative = f"{prefix}/tests/analysis/{filename}"
                    path = root / relative
                    original = path.read_text(encoding="utf-8") if path.is_file() else "import unittest\n"
                    for fails in (True, False):
                        with self.subTest(path=relative, fails=fails):
                            probe = (
                                "\n\nclass ChangedGateFailureProbe(unittest.TestCase):\n"
                                "    def test_changed_gate_failure_probe(self):\n"
                                f"        self.assertFalse({fails!r}, 'CHANGED_TEST_EXECUTED')\n"
                            )
                            path.write_text(original + probe, encoding="utf-8", newline="\n")
                            summary_path = Path(logs) / f"summary_{index}_{fails}.json"
                            result = subprocess.run([
                                "pwsh", "-NoProfile", "-File", str(root / "common/verify_changed.ps1"),
                                "-PythonExe", sys.executable, "-ChangedPath", relative,
                                "-SummaryPath", str(summary_path), "-MaxConcurrency", "1",
                            ], cwd=root, env=environment, capture_output=True, text=True,
                                encoding="utf-8", timeout=1200)
                            output = result.stdout + result.stderr
                            self.assertEqual(result.returncode != 0, fails, output)
                            summary = json.loads(summary_path.read_text(encoding="utf-8"))
                            record = next(row for row in summary["stages"] if row["name"] == stage)
                            self.assertEqual(record["status"], "FAIL" if fails else "PASS", output)
                            module = relative[:-3].replace("/", ".")
                            self.assertIn(module, record["command"]["parameters"]["ChangedTestModules"])
                            self.assertIn(module, output)
                            if fails:
                                self.assertIn("CHANGED_TEST_EXECUTED", output)
                            else:
                                self.assertIn("CHANGED_GATE=PASS", output)
                    if filename == "test_changed_gate_probe.py":
                        path.unlink()
                    else:
                        path.write_text(original, encoding="utf-8", newline="\n")
            finally:
                # Expected failures retain diagnostics; remove only this fixture's
                # reviewed gate directories through their public cleanup owner.
                cleanup = (
                    ". ./common/parallel_gate_support.ps1; "
                    "Get-ChildItem -LiteralPath " + powershell_literal(logs) +
                    " -Directory -Filter 'changed_gate_*' | ForEach-Object { "
                    "Remove-GateTemporaryDirectory -Path $_.FullName -ExpectedNamePrefix 'changed_gate_' }"
                )
                subprocess.run(["pwsh", "-NoProfile", "-Command", cleanup], cwd=root,
                               env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60,
                               check=True)


if __name__ == "__main__":
    unittest.main()
