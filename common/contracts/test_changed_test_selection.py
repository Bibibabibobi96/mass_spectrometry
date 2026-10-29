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
    def test_ip_and_single_reflection_owners_report_failure_and_per_test_duration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project_gate_fixture_") as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            for name in ("require_powershell7.ps1", "gate_unittest.py"):
                shutil.copyfile(REPO_ROOT / "common" / name, common / name)
            (common / "host_execution_lease.ps1").write_text(
                "function Enter-HostExecutionLease { param($Role,$Stage) return @{} }\n"
                "function Exit-HostExecutionLease { param($Lease) }\n", encoding="utf-8")
            single = "single_reflection_oa_tof_mass_analyzer"
            for project, relative_tests in (("dual_pressure_rectilinear_ion_processor", "tests"),
                                             (single, "tests/analysis")):
                project_root = root / "projects" / project
                tests = project_root / relative_tests
                tests.mkdir(parents=True)
                shutil.copyfile(REPO_ROOT / "projects" / project / "verify_project.ps1",
                                project_root / "verify_project.ps1")
                if project == single:
                    (project_root / "oatof_lifecycle_preflight.ps1").write_text("", encoding="utf-8")
                    config = project_root / "config"
                    config.mkdir()
                    (config / "project.json").write_text(
                        '{"lifecycle_status":"formal_revalidation_pending"}', encoding="utf-8")
                    for owner, module in ((single, "resolve_geometry"),
                                          (single, "reflectron_dual_stage_solver"),
                                          (single, "oatof_oaaccelerator_coupling"),
                                          ("orthogonal_accelerator", "accelerator_time_focus")):
                        path = root / "projects" / owner / "analysis" / (module + ".py")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("# Inert theory preflight for owner-runner wiring only.\n", encoding="utf-8")
                for fails in (False, True):
                    with self.subTest(project=project, fails=fails):
                        (tests / "test_probe.py").write_text(
                            "import unittest\nclass Probe(unittest.TestCase):\n"
                            f"    def test_probe(self): self.assertFalse({fails!r}, 'PROJECT_OWNER_PROBE')\n",
                            encoding="utf-8")
                        result = subprocess.run(
                            ["pwsh", "-NoProfile", "-File", str(project_root / "verify_project.ps1"),
                             "-PythonExe", sys.executable], cwd=root, capture_output=True, text=True,
                            encoding="utf-8", timeout=60,
                        )
                        output = result.stdout + result.stderr
                        self.assertEqual(result.returncode != 0, fails, output)
                        self.assertIn("TEST_DURATION_SECONDS=", output)
                        self.assertIn("Ran 1 test", output)
                        if fails:
                            self.assertIn("TEST_FAILURE_IMMEDIATE=", output)
                            self.assertIn("PROJECT_OWNER_PROBE", output)
                        else:
                            self.assertIn("PROJECT_GATE=PASS", output)

    def test_integration_owner_reports_failure_and_per_test_duration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="integration_gate_fixture_") as directory:
            root = Path(directory)
            for subdir in ("common", "integrations/runtime", "integrations/analysis",
                           "integrations/workflows", "integrations/tests"):
                (root / subdir).mkdir(parents=True)
            shutil.copyfile(REPO_ROOT / "integrations/verify_integration.ps1", root / "integrations/verify_integration.ps1")
            for name in ("require_powershell7.ps1", "gate_unittest.py"):
                shutil.copyfile(REPO_ROOT / "common" / name, root / "common" / name)
            (root / "common/host_execution_lease.ps1").write_text(
                "function Enter-HostExecutionLease { param($Role) return @{} }\n"
                "function Exit-HostExecutionLease { param($Lease) }\n", encoding="utf-8")
            (root / "integrations/tests/test_probe.py").write_text(
                "import unittest\nclass Probe(unittest.TestCase):\n"
                "    def test_failure(self): self.fail('INTEGRATION_OWNER_PROBE')\n", encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(root / "integrations/verify_integration.ps1"),
                 "-PythonExe", sys.executable], cwd=root, capture_output=True, text=True,
                encoding="utf-8", timeout=60,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("TEST_FAILURE_IMMEDIATE=", output)
            self.assertIn("INTEGRATION_OWNER_PROBE", output)
            self.assertIn("TEST_DURATION_SECONDS=", output)

    def check_integration_partitions(self, gate_name: str) -> None:
        with tempfile.TemporaryDirectory(prefix="integration_partition_fixture_") as directory:
            root = Path(directory)
            common = root / "common"
            tests = root / "integrations/tests"
            for path in (common, tests, root / "temporary", root / "ruff", root / "projects"):
                path.mkdir(parents=True)
            for name in ("verify_repository_integration.ps1", "verify_changed.ps1", "parallel_gate_support.ps1",
                         "gate_catalog_support.ps1", "require_powershell7.ps1", "gate_unittest.py"):
                shutil.copyfile(REPO_ROOT / "common" / name, common / name)
            shutil.copyfile(REPO_ROOT / "integrations/verify_integration.ps1",
                            root / "integrations/verify_integration.ps1")
            catalog = json.loads((REPO_ROOT / "common/gate_catalog.json").read_text(encoding="utf-8"))
            route = next(route for route in catalog["routes"] if route["stage"] == "instrument_assembly_integration")
            # The source inventory is tested separately; this fixture isolates
            # the real catalog's partition and the real owner's execution.
            route.pop("runtime_dependencies_path")
            catalog["routes"] = [route]
            if gate_name == "l1":
                for stage in ("project_registry", "rf_multipole_generated_publications"):
                    catalog["routes"].append(dict(stage=stage, dependency_profile="stdlib",
                        repository_integration_group="fast", matches=[dict(exact="unused-fixture", reason="unused")],
                        command=dict(runner="python", arguments=["-c", "pass"])))
                catalog["routes"].append(dict(stage="fixture_covered_modules", dependency_profile="stdlib",
                    repository_integration_group="covered", run_on_full_scope=False,
                    full_scope_coverage_stage="instrument_assembly_integration",
                    matches=[dict(exact="integrations/runtime/fixture.py", reason="fixture_source")],
                    command=dict(runner="python", arguments=["-m", "unittest", "integrations/tests/test_a.py", "fixture_extra"],
                                 python_path_roots=["integrations/tests/"])))
            (common / "gate_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            (common / "host_execution_lease.ps1").write_text(
                "function Get-HostResourceBudget {param($Stage,$Role) @{}}\n"
                "function Enter-HostResourceStage {param($Stage,$Role,$Budget) @{}}\n"
                "function Exit-HostResourceStage {param($Lease)}\n"
                "function Enter-HostExecutionLease {param($Role) Set-Content (Join-Path $env:FIXTURE_OWNER_EVENTS ($PID.ToString()+'.enter')) $Role; @{}}\n"
                "function Exit-HostExecutionLease {param($Lease) Set-Content (Join-Path $env:FIXTURE_OWNER_EVENTS ($PID.ToString()+'.exit')) 'released'}\n", encoding="utf-8")
            (common / "verify_documentation.ps1").write_text("param($PythonExe)\n", encoding="utf-8")
            (common / "verify_repository_hygiene.ps1").write_text("# inert hygiene fixture\n", encoding="utf-8")
            (root / "integrations/runtime").mkdir()
            (root / "integrations/runtime/fixture.py").write_text("pass\n", encoding="utf-8")
            (root / "fixture_extra.py").write_text(
                "import unittest\nclass Extra(unittest.TestCase):\n"
                "    def test_extra(self): self.assertTrue(True)\n", encoding="utf-8")
            for name in ("verify_repository_text_bytes", "verify_development_standards"):
                (common / (name + ".py")).write_text("pass\n", encoding="utf-8")
            (root / "ruff/__init__.py").write_text("", encoding="utf-8")
            (root / "ruff/__main__.py").write_text(
                "import os,sys\nfrom pathlib import Path\n"
                "owner = 'integrations/runtime' in sys.argv\n"
                "if owner: (Path(os.environ['FIXTURE_OWNER_EVENTS'])/(str(os.getpid())+'.ruff')).write_text('owner')\n"
                "print('RUFF_OWNER_CHECK' if owner else 'RUFF_GLOBAL_CHECK')\n"
                "raise SystemExit(1 if owner and os.environ.get('FIXTURE_PREFLIGHT_FAIL') else 0)\n",
                encoding="utf-8")
            for name in "abcdef":
                (tests / f"test_{name}.py").write_text(
                    "import os,unittest\nclass Probe(unittest.TestCase):\n"
                    f"    def test_probe(self): self.assertFalse({name!r} == 'b' and "
                    "bool(os.environ.get('FIXTURE_SHARD_FAIL')), 'INTEGRATION_SHARD_FAILURE')\n",
                    encoding="utf-8")
            environment = dict(os.environ, TEMP=str(root / "temporary"), TMP=str(root / "temporary"))
            environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
            for failure in (("", "shard", "preflight", "thin") if gate_name == "l1" else ("", "shard", "preflight")):
                with self.subTest(failure=failure):
                    events = root / ((failure or "success") + "_events")
                    events.mkdir()
                    environment["FIXTURE_OWNER_EVENTS"] = str(events)
                    environment.pop("FIXTURE_PREFLIGHT_FAIL", None)
                    environment.pop("FIXTURE_SHARD_FAIL", None)
                    if failure in {"shard", "preflight"}:
                        environment["FIXTURE_" + failure.upper() + "_FAIL"] = "1"
                    summary = root / ((failure or "success") + ".json")
                    gate = "verify_changed.ps1" if gate_name == "l1" else "verify_repository_integration.ps1"
                    arguments = ["pwsh", "-NoProfile", "-File", str(common / gate),
                                 "-PythonExe", sys.executable, "-MaxConcurrency", "4", "-SummaryPath", str(summary)]
                    if gate_name == "l1":
                        arguments.extend(["-ChangedPath", "integrations/tests/test_a.py" if failure == "thin"
                                          else "integrations/runtime/fixture.py"])
                    result = subprocess.run(
                        arguments,
                        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90,
                    )
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode != 0, failure in {"shard", "preflight"}, output)
                    report = json.loads(summary.read_text(encoding="utf-8"))
                    stages = {stage["name"]: stage for stage in report["stages"]}
                    parts = [stage for name, stage in stages.items()
                             if name.startswith("instrument_assembly_integration__tests_")]
                    modules = [module for part in parts for module in part["command"]["parameters"]["SelectedTestModules"]]
                    if failure == "thin":
                        self.assertFalse(parts, output)
                        selected = stages["instrument_assembly_integration"]
                        self.assertEqual(selected["command"]["arguments"], ["-m", "common.gate_unittest", "integrations/tests/test_a.py"])
                        self.assertEqual(len(selected["test_durations"]), 1, output)
                        self.assertFalse(list(events.glob("*.ruff")), output)
                        continue
                    if gate_name == "l1":
                        covered = stages["fixture_covered_modules"]
                        self.assertEqual(covered["command"]["arguments"], ["-m", "common.gate_unittest", "fixture_extra"])
                        self.assertEqual(covered["command"]["python_path_roots"], ["integrations/tests/"])
                        self.assertEqual(covered["selection_reason"], "partially_covered_by_instrument_assembly_integration")
                        if not failure:
                            self.assertEqual(len(covered["test_durations"]), 1, output)
                    self.assertEqual(len(parts), 4)
                    self.assertCountEqual(modules, [f"integrations.tests.test_{name}" for name in "abcdef"])
                    self.assertEqual(len(modules), len(set(modules)))
                    self.assertEqual(len(list(events.glob("*.ruff"))), 1, output)
                    entered = {path.stem for path in events.glob("*.enter")}
                    exited = {path.stem for path in events.glob("*.exit")}
                    if gate_name == "l1" and failure == "shard":
                        self.assertGreaterEqual(len(entered), 2, output)
                        self.assertLessEqual(len(entered), 5, output)
                    else:
                        self.assertEqual(len(entered), 1 if failure == "preflight" else 5, output)
                    self.assertEqual(exited, entered, output)
                    self.assertTrue(all(path.read_text(encoding="utf-8-sig").strip() == "GATE"
                                        for path in events.glob("*.enter")), output)
                    if failure == "preflight":
                        self.assertTrue(all(part["status"] == "BLOCKED" for part in parts), output)
                    else:
                        self.assertEqual(stages["instrument_assembly_integration"]["status"], "PASS", output)
                        self.assertEqual(sum(part["status"] == "FAIL" for part in parts), int(failure == "shard"), output)
                        if not (gate_name == "l1" and failure == "shard"):
                            self.assertEqual(sum(len(part["test_durations"]) for part in parts), 6, output)
                        if failure:
                            self.assertIn("TEST_FAILURE_IMMEDIATE=", output)
                            self.assertIn("INTEGRATION_SHARD_FAILURE", output)

    def test_integration_l2_partitions_run_each_module_once_after_one_preflight(self) -> None:
        self.check_integration_partitions("l2")

    def test_integration_l1_reuses_full_partitions_and_preserves_thin_selection(self) -> None:
        self.check_integration_partitions("l1")

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

    def test_simion_owner_impact_selection_matrix(self) -> None:
        test = "common/simion/test_voltage_waveforms.py"
        cases = (
            ([test, "common/contracts/test_particle_state.py"], True, False),
            ([test, "common/simion/README.md"], True, False),
            ([test, "common/simion/pa_asset.py"], False, True),
            ([test, "common/simion/helper.py"], False, True),
            ([test, "common/simion/test_removed.py"], False, True),
            ([test, "common/simion/unknown/new.py"], False, True),
        )
        for paths, only, expanded in cases:
            with self.subTest(paths=paths):
                script = (
                    ". ./common/gate_catalog_support.ps1; "
                    "$routes=@(Read-GateCatalog -RepoRoot $PWD.Path); "
                    "$roots=@($routes | Where-Object { $null -ne $_.PSObject.Properties['test_selection'] } "
                    "| ForEach-Object { @($_.test_selection.roots) }); "
                    "$route=$routes | Where-Object { $_.stage -eq 'simion_common' }; "
                    "$paths=@(" + ",".join(map(powershell_literal, paths)) + "); "
                    "$owner=@(Get-GateOwnerChangedPaths -Route $route -ChangedPaths $paths); "
                    "Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots $roots "
                    "-ChangedPaths $owner | ConvertTo-Json -Depth 8"
                )
                result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                        capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                selection = json.loads(result.stdout)
                self.assertEqual(selection["OnlyTestModules"], only)
                self.assertEqual(selection["Expanded"], expanded)
                self.assertIn(test, selection["Modules"])

    def test_support_file_matches_exact_path(self) -> None:
        script = (
            ". " + powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1") + "; "
            "$route=[pscustomobject]@{test_selection=[pscustomobject]@{"
            "roots=@('owner/tests/analysis/');support_paths=@('owner/tests/__init__.py')}}; "
            "$selection=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path "
            "-KnownTestRoots @('owner/tests/analysis/') "
            "-ChangedPaths @('owner/tests/__init__.py.other'); "
            "if ($null -ne $selection) { throw 'support file matched unrelated path' }"
        )
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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

    def test_changed_mr_rf_modules_reach_owner_and_propagate_failure(self) -> None:
        # Exercise real catalog selection and internal dispatch with tiny owner fixtures.
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
            for prefix in (MR, RF):
                (root / prefix / "verify_project.ps1").write_text(
                    "param($Level,$PythonExe,$StructuralVariant,$FreshnessPrevalidated,"
                    "[string[]]$ChangedTestModules)\n"
                    "& $PythonExe -m unittest @ChangedTestModules\n"
                    "if ($LASTEXITCODE -ne 0) { throw 'OWNER_TEST_FAILURE' }\n",
                    encoding="utf-8")
            for index, (prefix, filename, stage) in enumerate(cases):
                relative = f"{prefix}/tests/analysis/{filename}"
                path = root / relative
                for fails in (True, False):
                    with self.subTest(path=relative, fails=fails):
                        path.write_text(
                            "import unittest\nclass ChangedGateFailureProbe(unittest.TestCase):\n"
                            f"    def test_probe(self): self.assertFalse({fails!r}, 'CHANGED_TEST_EXECUTED')\n",
                            encoding="utf-8")
                        request = Path(logs) / f"request_{index}_{fails}.json"
                        request.write_text(json.dumps({"python_exe": sys.executable,
                                                       "changed_paths": [relative],
                                                       "full_scope": False}), encoding="utf-8")
                        log = Path(logs) / f"stage_{index}_{fails}.log"
                        result = subprocess.run([
                            "pwsh", "-NoProfile", "-File", str(root / "common/verify_changed.ps1"),
                            "-InternalStage", stage, "-InternalRequestPath", str(request),
                            "-InternalLogPath", str(log),
                        ], cwd=root, env=environment, capture_output=True, text=True,
                            encoding="utf-8", timeout=180)
                        output = result.stdout + result.stderr + log.read_text(encoding="utf-8")
                        self.assertEqual(result.returncode != 0, fails, output)
                        self.assertIn("CHANGED_TEST_EXECUTED" if fails else "Ran 1 test", output)
            # Keep the shared runner paired with the actual project gates copied below.
            shutil.copyfile(REPO_ROOT / "common/gate_unittest.py", root / "common/gate_unittest.py")
            # Check both actual project gates still consume and propagate a new test.
            for index, (prefix, stage) in enumerate((
                (MR, "parallel_mirror_dual_stripe_mr_tof_static"),
                (RF, "rf_multipole_quadrupole_static"),
            )):
                shutil.copyfile(REPO_ROOT / prefix / "verify_project.ps1", root / prefix / "verify_project.ps1")
                if prefix == MR:
                    # This test exercises the changed-module wiring, not the
                    # unrelated scientific Core suite, which its owner gate runs.
                    # Retain the real owner's exact Core names and assert that
                    # the selected module is merged without duplicate execution.
                    for core in ("test_drift_phase_contract", "test_prism_analytic",
                                 "test_native_corridor_plan", "test_native_corridor_freeze"):
                        (root / prefix / "tests/analysis" / f"{core}.py").write_text(
                            "import unittest\nclass CoreProbe(unittest.TestCase):\n"
                            "    def test_core(self): self.assertTrue(True)\n", encoding="utf-8")
                relative = f"{prefix}/tests/analysis/test_changed_gate_probe.py"
                (root / relative).write_text(
                    "import unittest\nclass Probe(unittest.TestCase):\n"
                    "    def test_failure(self): self.fail('REAL_OWNER_PROBE')\n", encoding="utf-8")
                request = Path(logs) / f"real_{index}.json"
                request.write_text(json.dumps({"python_exe": sys.executable,
                                               "changed_paths": [relative],
                                               "full_scope": False}), encoding="utf-8")
                log = Path(logs) / f"real_{index}.log"
                result = subprocess.run([
                    "pwsh", "-NoProfile", "-File", str(root / "common/verify_changed.ps1"),
                    "-InternalStage", stage, "-InternalRequestPath", str(request),
                    "-InternalLogPath", str(log),
                ], cwd=root, env=environment, capture_output=True, text=True,
                    encoding="utf-8", timeout=300)
                output = result.stdout + result.stderr + log.read_text(encoding="utf-8")
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn("REAL_OWNER_PROBE", output)
                if prefix == MR:
                    module_line = next(line for line in output.splitlines() if "PROJECT_TEST_MODULES=" in line)
                    self.assertEqual(module_line.count("test_changed_gate_probe"), 1)
                    for core in ("test_drift_phase_contract", "test_prism_analytic",
                                 "test_native_corridor_plan", "test_native_corridor_freeze"):
                        self.assertIn(core, module_line)


if __name__ == "__main__":
    unittest.main()
