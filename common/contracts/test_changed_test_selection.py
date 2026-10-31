"""Exercise changed-test discovery and failure propagation through the real L1 gate."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
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


def write_planned_request(root: Path, request: Path, paths: list[str] | None) -> None:
    """Use the parent's real selector once, then exercise only resolved dispatch."""
    command = ("& " + powershell_literal(root / "common/verify.ps1") +
               " -PythonExe " + powershell_literal(sys.executable) +
               " -PlanOnly -InternalRequestPath " + powershell_literal(request))
    command += " -FullScope" if paths is None else " -ChangedPath @(" + ",".join(map(powershell_literal, paths)) + ")"
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


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
            for name in ("verify.ps1", "parallel_gate_support.ps1",
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
            (common / "gate_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            (common / "host_execution_lease.ps1").write_text(
                "function Get-HostResourceBudget {param($Stage,$Role) @{}}\n"
                "function Enter-HostResourceStage {param($Stage,$Role,$Budget) @{}}\n"
                "function Exit-HostResourceStage {param($Lease)}\n"
                "function Enter-HostExecutionLease {param($Role) Set-Content (Join-Path $env:FIXTURE_OWNER_EVENTS ($PID.ToString()+'.enter')) $Role; @{}}\n"
                "function Exit-HostExecutionLease {param($Lease) Set-Content (Join-Path $env:FIXTURE_OWNER_EVENTS ($PID.ToString()+'.exit')) 'released'}\n", encoding="utf-8")
            (common / "verify_documentation.ps1").write_text("param($PythonExe,$StructureOnly,[string[]]$ChangedPath)\n", encoding="utf-8")
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
                "raise SystemExit(1 if os.environ.get('FIXTURE_RUFF_FAIL') else 0)\n",
                encoding="utf-8")
            for name in "abcdef":
                (tests / f"test_{name}.py").write_text(
                    "import os,unittest\nclass Probe(unittest.TestCase):\n"
                    f"    def test_probe(self): self.assertFalse({name!r} == 'b' and "
                    "bool(os.environ.get('FIXTURE_SHARD_FAIL')), 'INTEGRATION_SHARD_FAILURE')\n",
                    encoding="utf-8")
            environment = dict(os.environ, TEMP=str(root / "temporary"), TMP=str(root / "temporary"))
            environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
            for failure in (("", "shard", "ruff", "thin") if gate_name == "Changed" else ("", "shard", "ruff")):
                with self.subTest(failure=failure):
                    events = root / ((failure or "success") + "_events")
                    events.mkdir()
                    environment["FIXTURE_OWNER_EVENTS"] = str(events)
                    environment.pop("FIXTURE_RUFF_FAIL", None)
                    environment.pop("FIXTURE_SHARD_FAIL", None)
                    if failure in {"shard", "ruff"}:
                        environment["FIXTURE_" + failure.upper() + "_FAIL"] = "1"
                    summary = root / ((failure or "success") + ".json")
                    arguments = ["pwsh", "-NoProfile", "-File", str(common / "verify.ps1"), "-Scope", gate_name,
                                 "-PythonExe", sys.executable, "-MaxConcurrency", "4", "-SummaryPath", str(summary)]
                    if gate_name == "Changed":
                        arguments.extend(["-ChangedPath", "integrations/tests/test_a.py" if failure == "thin"
                                          else "integrations/runtime/fixture.py"])
                    result = subprocess.run(
                        arguments,
                        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90,
                    )
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode != 0, failure in {"shard", "ruff"}, output)
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
                    self.assertEqual(len(parts), 4)
                    self.assertCountEqual(modules, [f"integrations.tests.test_{name}" for name in "abcdef"])
                    self.assertEqual(len(modules), len(set(modules)))
                    self.assertFalse(list(events.glob("*.ruff")), output)
                    entered = {path.stem for path in events.glob("*.enter")}
                    exited = {path.stem for path in events.glob("*.exit")}
                    if gate_name == "Changed" and failure:
                        self.assertLessEqual(len(entered), 4, output)
                    else:
                        self.assertEqual(len(entered), 4, output)
                    self.assertEqual(exited, entered, output)
                    self.assertTrue(all(path.read_text(encoding="utf-8-sig").strip() == "GATE"
                                        for path in events.glob("*.enter")), output)
                    self.assertEqual(stages["instrument_assembly_integration"]["status"], "NOT_APPLICABLE", output)
                    if not (gate_name == "Changed" and failure == "ruff"):
                        self.assertEqual(sum(part["status"] == "FAIL" for part in parts), int(failure == "shard"), output)
                    if not (gate_name == "Changed" and failure):
                        self.assertEqual(sum(len(part["test_durations"]) for part in parts), 6, output)
                    if failure == "shard":
                        self.assertIn("TEST_FAILURE_IMMEDIATE=", output)
                        self.assertIn("INTEGRATION_SHARD_FAILURE", output)

    def test_repository_partitions_run_each_module_once_without_ruff_preflight(self) -> None:
        self.check_integration_partitions("Repository")

    def test_changed_scope_partitions_preserve_thin_selection_and_failure_policy(self) -> None:
        self.check_integration_partitions("Changed")

    def selections(self, root: Path, cases: list[dict], *, owner_filter: bool = False) -> list[dict]:
        """Evaluate read-only cases in one host; cross-process tests remain separate."""
        with tempfile.TemporaryDirectory(prefix="selection_cases_") as directory:
            request = Path(directory) / "cases.json"
            request.write_text(json.dumps(cases), encoding="utf-8")
            script = (
                ". " + powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1") + "; "
                "$routes=@(Read-GateCatalog -RepoRoot $PWD.Path); "
                "$roots=@($routes | Where-Object { $null -ne $_.PSObject.Properties['test_selection'] } "
                "| ForEach-Object { @($_.test_selection.roots) }); "
                "$cases=Get-Content -Raw -LiteralPath " + powershell_literal(request) + "|ConvertFrom-Json; "
                "$results=@(foreach($case in $cases){ "
                "$route=@($routes | Where-Object { $_.stage -eq $case.stage }); "
                "if($route.Count-ne1){throw 'selection case must have one real catalog owner'}; "
                "$paths=@($case.paths); " +
                ("$paths=@(Get-GateOwnerChangedPaths -Route $route[0] -ChangedPaths $paths); " if owner_filter else "") +
                "Get-GateChangedTests -Route $route[0] -RepoRoot $PWD.Path -KnownTestRoots $roots -ChangedPaths $paths "
                "}); ConvertTo-Json -InputObject $results -Depth 8"
            )
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root,
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            selected = json.loads(result.stdout)
            self.assertEqual(len(selected), len(cases))
            return selected

    def test_existing_modules_and_support_have_explicit_selection(self) -> None:
        cases = []
        for prefix, stage, filename in (
            (MR, "parallel_mirror_dual_stripe_mr_tof_static", "test_simion_event_analysis.py"),
            (RF, "rf_multipole_quadrupole_static", "test_mass_filter_l1.py"),
            ("projects/single_reflection_oa_tof_mass_analyzer",
             "single_reflection_oa_tof_mass_analyzer_static", "test_simion_delivery_source.py"),
        ):
            changed = f"{prefix}/tests/analysis/{filename}"
            cases.extend(dict(stage=stage, paths=paths) for paths in (
                [changed], [changed, f"{prefix}/analysis/source.py"],
                [f"{prefix}/tests/analysis/test_deleted.py"],
                [f"{prefix}/tests/analysis/__init__.py"], [f"{prefix}/tests/test_support/fixture.py"],
            ))
        results = self.selections(REPO_ROOT, cases)
        for offset in range(0, len(cases), 5):
            changed = cases[offset]["paths"][0]
            self.assertEqual(results[offset]["Modules"], [changed])
            self.assertFalse(results[offset]["Expanded"])
            self.assertFalse(results[offset + 1]["OnlyTestModules"])
            for index in range(offset + 2, offset + 5):
                with self.subTest(paths=cases[index]["paths"]):
                    self.assertTrue(results[index]["Expanded"])
                    self.assertIn(changed, results[index]["Modules"])

    def test_sfi_weighted_partitions_cover_actual_scope_without_duplicates(self) -> None:
        script = r"""
. __SUPPORT__
$route=(Get-Content -LiteralPath __CATALOG__ -Raw|ConvertFrom-Json).routes|
 Where-Object stage -eq 'single_reflection_oa_tof_mass_analyzer_static'
$partitions=@(Get-GateRepositoryTestPartitions -Route $route -RepoRoot $PWD.Path)
$roots=@($route.test_selection.roots)
$selection=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots $roots -FullScope -ChangedPaths @()
@{partitions=$partitions;selected=@($selection.Modules);expanded=$selection.Expanded;
 only_tests=$selection.OnlyTestModules;preflight=$route.repository_integration_command.parameters.PreflightOnly;
 parent_preserved=($null-eq$route.PSObject.Properties['partition_preflight'] -or $route.partition_preflight)}|
 ConvertTo-Json -Depth 12 -Compress
"""
        script = script.replace('__SUPPORT__', powershell_literal(REPO_ROOT / 'common/gate_catalog_support.ps1'))
        script = script.replace('__CATALOG__', powershell_literal(REPO_ROOT / 'common/gate_catalog.json'))
        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        prefix = 'projects/single_reflection_oa_tof_mass_analyzer/tests'
        expected = {path.relative_to(REPO_ROOT).as_posix()[:-3].replace('/', '.')
                    for path in (REPO_ROOT / prefix).rglob('test_*.py')}
        actual = [module for part in data['partitions'] for module in part['modules']]
        route = next(row for row in json.loads((REPO_ROOT / 'common/gate_catalog.json').read_text(encoding='utf-8'))['routes']
                     if row['stage'] == 'single_reflection_oa_tof_mass_analyzer_static')
        self.assertEqual(len(data['partitions']), route['repository_integration_partition']['count'])
        self.assertEqual(set(actual), expected)
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual({path[:-3].replace('/', '.') for path in data['selected']}, expected)
        self.assertTrue(data['expanded'])
        self.assertFalse(data['only_tests'])
        self.assertTrue(data['preflight'])
        self.assertTrue(data['parent_preserved'])

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
                        "$route=[pscustomobject]@{dependency_profile='stdlib';test_selection=[pscustomobject]@{"
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

    def test_quadrupole_numerics_dependency_is_precise_and_unknown_runtime_stays_conservative(self) -> None:
        script = r"""
. __SUPPORT__
$routes=(Get-Content -LiteralPath __CATALOG__ -Raw|ConvertFrom-Json).routes
$roots=@($routes|Where-Object{$null-ne$_.PSObject.Properties['test_selection']}|ForEach-Object{@($_.test_selection.roots)})
$compiler='projects/rf_multipole_ion_optics/runtime/comsol_solver_numerics.ps1'
$four=@('projects/rf_multipole_ion_optics/docs/COMSOL.md',$compiler,
 'projects/rf_multipole_ion_optics/tests/analysis/test_comsol_workflow_architecture_contract.py',
 'projects/rf_multipole_ion_optics/variants/quadrupole/config/comsol_solver_numerics.json')
$cases=@(@{name='four';paths=$four},@{name='deleted';paths=@($compiler)},
 @{name='renamed';paths=@($compiler,'projects/rf_multipole_ion_optics/runtime/unknown_new_name.ps1')},
 @{name='other';paths=@('projects/rf_multipole_ion_optics/runtime/runtime_profile.py')},
 @{name='docs';paths=@('projects/rf_multipole_ion_optics/docs/COMSOL.md')})
$result=@(foreach($case in $cases){
 $selected=@{};foreach($stage in @('rf_multipole_domain_tests','instrument_assembly_integration',
  'rf_multipole_quadrupole_static','rf_multipole_hexapole_static','rf_multipole_octupole_static')){
  $route=$routes|Where-Object stage -eq $stage
  $selected[$stage]=[bool](Get-ChangedRouteReason -Route $route -Paths $case.paths)
 }
 $quad=$routes|Where-Object stage -eq 'rf_multipole_quadrupole_static'
 $paths=@(Get-GateOwnerChangedPaths -Route $quad -ChangedPaths $case.paths)
 $selection=Get-GateChangedTests -Route $quad -ChangedPaths $paths -KnownTestRoots $roots -RepoRoot $PWD.Path
 @{name=$case.name;selected=$selected;modules=if($null-ne$selection){@($selection.Modules)}else{@()}}
})
ConvertTo-Json -InputObject $result -Depth 12 -Compress
"""
        script = script.replace("__SUPPORT__", powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1"))
        script = script.replace("__CATALOG__", powershell_literal(REPO_ROOT / "common/gate_catalog.json"))
        outcome = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        cases = {case["name"]: case for case in json.loads(outcome.stdout)}
        expected = sorted([f"{RF}/tests/analysis/test_comsol_workflow_architecture_contract.py",
                           f"{RF}/tests/analysis/test_comsol_mass_filter_contract.py"])
        for name in ("four", "deleted"):
            with self.subTest(case=name):
                selected = cases[name]["selected"]
                self.assertTrue(selected["rf_multipole_quadrupole_static"])
                self.assertFalse(selected["rf_multipole_domain_tests"])
                self.assertFalse(selected["instrument_assembly_integration"])
                self.assertFalse(selected["rf_multipole_hexapole_static"])
                self.assertFalse(selected["rf_multipole_octupole_static"])
                self.assertEqual(sorted(cases[name]["modules"]), expected)
        for name in ("renamed", "other"):
            with self.subTest(case=name):
                self.assertTrue(all(cases[name]["selected"].values()))
        self.assertFalse(any(cases["docs"]["selected"].values()))

    def test_common_mesh_helpers_select_real_consumers_and_unknown_stays_conservative(self) -> None:
        script = r"""
. __SUPPORT__
$routes=@(Read-GateCatalog -RepoRoot $PWD.Path)
$roots=@($routes|Where-Object{$null-ne$_.PSObject.Properties['test_selection']}|ForEach-Object{@($_.test_selection.roots)})
$configure='common/comsol/configure_comsol_mesh.m';$size='common/comsol/add_comsol_size_feature.m'
$cases=@(@{name='configure';paths=@($configure)},@{name='size';paths=@($size)},
 @{name='typed';paths=@('common/comsol/read_comsol_mesh_size_controls.m')},
 @{name='matlab_test';paths=@('common/comsol/tests/ComsolMeshSizeTest.m')},
 @{name='recorder';paths=@('common/comsol/tests/test_support/MeshSizeRecorder.m')},
 @{name='unknown';paths=@('common/comsol/unknown_new_helper.m')},
 @{name='renamed';paths=@($configure,'common/comsol/unknown_new_helper.m')})
$results=@(foreach($case in $cases){
 $selected=@{};foreach($name in @('rf_multipole_generated_publications','rf_multipole_domain_tests',
 'rf_multipole_quadrupole_static','rf_multipole_hexapole_static','rf_multipole_octupole_static',
 'single_reflection_oa_tof_mass_analyzer_static','transverse_helical_filament_wehnelt_electron_gun_static','instrument_assembly_integration')){
  $route=$routes|Where-Object stage -eq $name;$selected[$name]=[bool](Get-ChangedRouteReason -Route $route -Paths $case.paths)
 }
 $quad=$routes|Where-Object stage -eq 'rf_multipole_quadrupole_static'
 $paths=@(Get-GateOwnerChangedPaths -Route $quad -ChangedPaths $case.paths)
 $tests=Get-GateChangedTests -Route $quad -ChangedPaths $paths -KnownTestRoots $roots -RepoRoot $PWD.Path
 @{name=$case.name;selected=$selected;modules=if($null-ne$tests){@($tests.Modules)}else{@()}}
})
ConvertTo-Json -InputObject $results -Depth 12 -Compress
""".replace("__SUPPORT__", powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1"))
        outcome = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        cases = {item["name"]: item for item in json.loads(outcome.stdout)}
        expected = sorted(f"{RF}/tests/analysis/{name}.py" for name in (
            "test_frozen_matlab_closure", "test_comsol_mesh_report"))
        for name in ("configure", "size", "typed", "matlab_test", "recorder"):
            with self.subTest(case=name):
                selected = cases[name]["selected"]
                self.assertTrue(selected["rf_multipole_quadrupole_static"])
                for nonconsumer in ("rf_multipole_domain_tests", "rf_multipole_hexapole_static",
                                    "rf_multipole_octupole_static", "transverse_helical_filament_wehnelt_electron_gun_static"):
                    self.assertFalse(selected[nonconsumer], (name, nonconsumer))
                self.assertEqual(selected["single_reflection_oa_tof_mass_analyzer_static"], name == "size")
                self.assertEqual(selected["instrument_assembly_integration"], name == "size")
                self.assertEqual(sorted(cases[name]["modules"]), expected)
        for name in ("unknown", "renamed"):
            with self.subTest(case=name):
                selected = cases[name]["selected"]
                self.assertTrue(all(value for key, value in selected.items() if key != "instrument_assembly_integration"))

    def test_mapped_numerics_modules_keep_real_dispatch_failure_propagation(self) -> None:
        self._assert_mapped_modules_keep_real_dispatch_failure_propagation(
            ["test_comsol_workflow_architecture_contract", "test_comsol_mass_filter_contract"],
            "projects/rf_multipole_ion_optics/runtime/comsol_solver_numerics.ps1")

    def test_mesh_modules_keep_real_dispatch_failure_propagation(self) -> None:
        self._assert_mapped_modules_keep_real_dispatch_failure_propagation(
            ["test_frozen_matlab_closure", "test_comsol_mesh_report"],
            "common/comsol/configure_comsol_mesh.m")

    def _assert_mapped_modules_keep_real_dispatch_failure_propagation(self, names, changed_path) -> None:
        with tempfile.TemporaryDirectory(prefix="numerics_route_dispatch_") as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            shutil.copyfile(REPO_ROOT / "common/gate_unittest.py", common / "gate_unittest.py")
            tests = root / RF / "tests/analysis"
            tests.mkdir(parents=True)
            for name in names:
                (tests / (name + ".py")).write_text(
                    "import os,unittest\nclass Probe(unittest.TestCase):\n"
                    " def test_boundary(self): self.assertFalse(os.environ.get('NUMERICS_ROUTE_RED'), 'NUMERICS_ROUTE_RED')\n",
                    encoding="utf-8", newline="\n")
            script = r"""
. __SUPPORT__
$route=((Get-Content __CATALOG__ -Raw|ConvertFrom-Json).routes|Where-Object stage -eq 'rf_multipole_quadrupole_static')
$selection=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots @($route.test_selection.roots) `
 -ChangedPaths @(__CHANGED_PATH__)
$modules=@($selection.Modules|ForEach-Object{$_.Substring(0,$_.Length-3).Replace('/','.')})
$command=ConvertTo-GateExecutionCommand -Command ([pscustomobject]@{runner='python';arguments=@('-m','unittest')+$modules})
Invoke-GateCatalogCommand -Command $command -RepoRoot $PWD.Path -PythonExe __PYTHON__
"""
            script = script.replace("__SUPPORT__", powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1"))
            script = script.replace("__CATALOG__", powershell_literal(REPO_ROOT / "common/gate_catalog.json"))
            script = script.replace("__PYTHON__", powershell_literal(sys.executable))
            script = script.replace("__CHANGED_PATH__", powershell_literal(changed_path))
            for red in (False, True):
                environment = os.environ.copy()
                environment.pop("PYTHONPATH", None)
                environment.pop("NUMERICS_ROUTE_RED", None)
                if red:
                    environment["NUMERICS_ROUTE_RED"] = "1"
                outcome = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root, env=environment,
                                         capture_output=True, text=True, encoding="utf-8", timeout=30)
                with self.subTest(red=red):
                    output = outcome.stdout + outcome.stderr
                    self.assertEqual(outcome.returncode != 0, red, output)
                    self.assertIn(f"Ran {len(names)} tests", output)
                    self.assertIn("TEST_DURATION_SECONDS=", output)
                    if red:
                        self.assertIn("TEST_FAILURE_IMMEDIATE=", output)
                        self.assertIn("NUMERICS_ROUTE_RED", output)

    def test_shared_rf_support_keeps_owner_module_sets_disjoint(self) -> None:
        owners = (("quadrupole_static", "analysis"), ("hexapole_static", "hexapole"),
                  ("octupole_static", "octupole"), ("domain_tests", "domain"))
        cases = [dict(stage="rf_multipole_" + owner, paths=[changed])
                 for changed in (f"{RF}/tests/test_support/fixture.py", f"{RF}/tests/__init__.py")
                 for owner, _ in owners]
        selected = self.selections(REPO_ROOT, cases)
        for offset in (0, 4):
            all_modules: set[str] = set()
            for index, (_, directory) in enumerate(owners):
                modules = set(selected[offset + index]["Modules"])
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
        selected = self.selections(REPO_ROOT, [dict(stage="simion_common", paths=paths)
                                             for paths, _, _ in cases], owner_filter=True)
        for (paths, only, expanded), selection in zip(cases, selected, strict=True):
            with self.subTest(paths=paths):
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
            write_planned_request(REPO_ROOT, request, ["common/contracts/" + name for name in modules])
            log = root / "stage.log"
            environment = dict(os.environ, TEMP=directory, TMP=directory, PYTHONDONTWRITEBYTECODE="1")
            environment.pop("PYTHONPATH", None)
            environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = os.environ.get(
                "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH",
                str(REPO_ROOT.parent / "artifacts/common/host_resources.sqlite3"),
            )
            result = subprocess.run([
                "pwsh", "-NoProfile", "-File", str(REPO_ROOT / "common/verify.ps1"),
                "-InternalStage", "common_contracts", "-InternalRequestPath", str(request),
                "-InternalLogPath", str(log),
            ], cwd=REPO_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180)
            output = result.stdout + result.stderr + log.read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, output)
            executed_modules = {
                test_id.rsplit(".", 2)[0]
                for test_id in re.findall(r"TEST_DURATION_SECONDS=\S+ TEST=(\S+)", output)
            }
            self.assertEqual(executed_modules, {
                "common.contracts." + Path(name).stem for name in modules
            })
            self.assertIn("GATE_STAGE=PASS NAME=common_contracts", output)

    def campaign_leaf_fixture(self, root: Path) -> tuple[str, list[str], str]:
        """Tiny catalog fixture, real planner and SFI owner, inert prerequisites."""
        common = root / "common"
        common.mkdir(parents=True)
        (root / "integrations").mkdir()
        for name in ("verify.ps1", "parallel_gate_support.ps1", "gate_catalog_support.ps1",
                     "require_powershell7.ps1", "gate_unittest.py"):
            shutil.copyfile(REPO_ROOT / "common" / name, common / name)
        owner = "projects/single_reflection_oa_tof_mass_analyzer"
        project = root / owner
        for directory in ("tests/analysis", "tests/simion", "config", "analysis", "docs"):
            (project / directory).mkdir(parents=True)
        shutil.copyfile(REPO_ROOT / owner / "verify_project.ps1", project / "verify_project.ps1")
        (project / "config/project.json").write_text('{"lifecycle_status":"formal_revalidation_pending"}', encoding="utf-8")
        (project / "oatof_lifecycle_preflight.ps1").write_text(
            "Add-Content -LiteralPath $env:LEAF_EVENTS -Value 'preflight'\n", encoding="utf-8")
        for provider, name in ((owner, "resolve_geometry"), (owner, "reflectron_dual_stage_solver"),
                               (owner, "oatof_oaaccelerator_coupling"),
                               ("projects/orthogonal_accelerator", "accelerator_time_focus")):
            path = root / provider / "analysis" / (name + ".py")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Inert theory prerequisite for owner transport only.\n", encoding="utf-8")
        catalog = json.loads((REPO_ROOT / "common/gate_catalog.json").read_text(encoding="utf-8"))
        route = next(x for x in catalog["routes"] if x["stage"] == "single_reflection_oa_tof_mass_analyzer_static")
        peer = next(x for x in catalog["routes"] if x["stage"] == "common_contracts")
        for item in (route, peer):
            item.pop("runtime_dependencies_path", None)
        catalog["routes"] = [route, peer]
        dependency = next(x for x in route["test_selection"]["dependencies"]
                          if any(m.get("exact") == owner + "/analysis/experiment_campaign.py" for m in x["matches"]))
        modules = dependency["modules"]
        for relative in [*modules, owner + "/tests/analysis/test_unrelated.py", "common/contracts/test_cross_owner.py"]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("import os,unittest\nclass Probe(unittest.TestCase):\n"
                            " def test_probe(self): self.assertFalse(os.environ.get('LEAF_FAIL') == __name__, 'LEAF_FAILURE_PROPAGATED')\n", encoding="utf-8")
        leaf = owner + "/analysis/experiment_campaign.py"
        second = owner + "/analysis/second_leaf.py"
        (root / leaf).write_text("# Declared production leaf.\n", encoding="utf-8")
        (root / second).write_text("# Fixture-only second declared dependency.\n", encoding="utf-8")
        (project / "analysis/unmapped.py").write_text("# Unknown production change.\n", encoding="utf-8")
        (project / "docs/PROJECT.md").write_text("# Fixture docs\n", encoding="utf-8")
        route["test_selection"]["dependencies"].append(dict(
            matches=[dict(exact=second, reason="fixture_second_leaf")],
            modules=[owner + "/tests/analysis/test_unrelated.py"], dependency_profile="locked"))
        (common / "gate_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        (common / "host_execution_lease.ps1").write_text(
            "function Get-HostResourceBudget {param($Role,$Stage) @{}}\n"
            "function Enter-HostResourceStage {param($Role,$Stage,$Budget) @{}}\n"
            "function Exit-HostResourceStage {param($Lease)}\n"
            "function Enter-HostExecutionLease {param($Role,$Stage) @{}}\n"
            "function Exit-HostExecutionLease {param($Lease)}\n", encoding="utf-8")
        (common / "verify_repository_hygiene.ps1").write_text("# Inert hygiene prerequisite.\n", encoding="utf-8")
        (common / "verify_documentation.ps1").write_text("param($PythonExe,$StructureOnly,[string[]]$ChangedPath)\n", encoding="utf-8")
        for name in ("verify_repository_text_bytes", "verify_development_standards"):
            (common / (name + ".py")).write_text("# Inert global prerequisite.\n", encoding="utf-8")
        (root / "ruff").mkdir()
        (root / "ruff/__init__.py").write_text("", encoding="utf-8")
        (root / "ruff/__main__.py").write_text("# Inert lint prerequisite.\n", encoding="utf-8")
        return leaf, modules, second

    def test_campaign_leaf_subset_complete_union_and_fallbacks_use_real_planner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="campaign_leaf_plan_") as directory:
            root = Path(directory)
            leaf, modules, second = self.campaign_leaf_fixture(root)
            owner = "projects/single_reflection_oa_tof_mass_analyzer"
            requests = [dict(name="leaf", paths=[leaf]),
                        dict(name="docs_and_test", paths=[leaf, owner + "/docs/PROJECT.md", modules[0]]),
                        dict(name="pure_test", paths=[modules[0]]),
                        dict(name="cross_owner", paths=[leaf, "common/contracts/test_cross_owner.py"]),
                        dict(name="mapped_union", paths=[leaf, second]),
                        dict(name="complete_test_union", paths=[leaf, owner + "/tests/analysis/test_unrelated.py"]),
                        dict(name="unknown", paths=[owner + "/analysis/unmapped.py"]),
                        dict(name="mixed_unknown", paths=[leaf, owner + "/analysis/unmapped.py"]),
                        dict(name="deleted", paths=[leaf]), dict(name="owner", scope="Owner"),
                        dict(name="repository", scope="Repository")]
            (root / "probes.json").write_text(json.dumps(requests), encoding="utf-8")
            script = root / "plan_matrix.ps1"
            script.write_text(r"""param($Root,$Python)
$ErrorActionPreference='Stop';$reports=@{}
foreach($probe in (Get-Content (Join-Path $Root 'probes.json') -Raw|ConvertFrom-Json)){
 $plan=Join-Path $Root ($probe.name+'.json');$source=Join-Path $Root 'projects/single_reflection_oa_tof_mass_analyzer/analysis/experiment_campaign.py'
 if($probe.name-eq'deleted'){Remove-Item -LiteralPath $source}
 try{
  if($probe.name-eq'owner'){& (Join-Path $Root 'common/verify.ps1') -Scope Owner -Owner single_reflection_oa_tof_mass_analyzer -PythonExe $Python -PlanOnly -PlanPath $plan|Out-Null}
  elseif($probe.name-eq'repository'){& (Join-Path $Root 'common/verify.ps1') -Scope Repository -PythonExe $Python -PlanOnly -PlanPath $plan|Out-Null}
  else{& (Join-Path $Root 'common/verify.ps1') -ChangedPath @($probe.paths) -PythonExe $Python -PlanOnly -PlanPath $plan|Out-Null}
  $reports[$probe.name]=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json -Depth 100
 }finally{if($probe.name-eq'deleted'){'# Restored fixture leaf'|Set-Content -LiteralPath $source}}
}
$reports|ConvertTo-Json -Depth 100|Set-Content -LiteralPath (Join-Path $Root 'plans.json') -Encoding utf8
""", encoding="utf-8")
            outcome = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(root), sys.executable],
                                     cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=90)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            plans = json.loads((root / "plans.json").read_text(encoding="utf-8-sig"))
            stage = "single_reflection_oa_tof_mass_analyzer_static"
            expected = {x[:-3].replace("/", ".") for x in modules}
            for name in ("leaf", "docs_and_test", "cross_owner"):
                selected = [x for x in plans[name]["stages"] if x["name"].startswith(stage)]
                self.assertEqual(len(selected), 1, name)
                self.assertEqual(selected[0]["command"]["runner"], "powershell")
                self.assertEqual(set(selected[0]["command"]["parameters"]["SelectedTestModules"]), expected)
                self.assertNotIn("PreflightValidated", selected[0]["command"]["parameters"])
            pure = next(x for x in plans["pure_test"]["stages"] if x["name"] == stage)
            self.assertEqual(pure["command"]["runner"], "python")
            for name in ("mapped_union", "complete_test_union", "unknown", "mixed_unknown", "deleted", "owner", "repository"):
                selected = [x for x in plans[name]["stages"] if x["name"].startswith(stage)]
                parent = next(x for x in selected if x["name"] == stage)
                self.assertTrue(parent["command"]["parameters"]["PreflightOnly"], name)
                shards = [x for x in selected if x["name"] != stage]
                self.assertEqual(len(shards), 4, name)
                actual = [m for x in shards for m in x["command"]["parameters"]["SelectedTestModules"]]
                self.assertEqual(len(actual), len(set(actual)), name)
                self.assertEqual(set(actual), expected | {owner.replace("/", ".") + ".tests.analysis.test_unrelated"}, name)
            self.assertTrue(any(x["name"] == "common_contracts" for x in plans["cross_owner"]["stages"]))

    def test_campaign_leaf_real_owner_runs_preflight_and_propagates_selected_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="campaign_leaf_dispatch_") as directory:
            root = Path(directory)
            leaf, modules, _ = self.campaign_leaf_fixture(root)
            for failed in (False, True):
                environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", LEAF_EVENTS=str(root / (str(failed)+".events")))
                environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
                environment.pop("PYTHONPATH", None)
                environment["LEAF_FAIL"] = modules[0][:-3].replace("/", ".") if failed else ""
                command = ["pwsh", "-NoProfile", "-File", str(root / "common/verify.ps1"), "-ChangedPath", leaf,
                           "-PythonExe", sys.executable, "-MaxConcurrency", "2", "-SummaryPath", str(root / (str(failed)+".json"))]
                outcome = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                                         text=True, encoding="utf-8", timeout=90)
                self.assertEqual(outcome.returncode != 0, failed, outcome.stdout + outcome.stderr)
                self.assertEqual(Path(environment["LEAF_EVENTS"]).read_text().splitlines(), ["preflight"])
                summary = json.loads((root / (str(failed)+".json")).read_text(encoding="utf-8-sig"))
                stages = [x for x in summary["stages"] if x["selected"] and x["name"].startswith("single_reflection")]
                self.assertEqual(len(stages), 1)
                self.assertEqual(stages[0]["status"], "FAIL" if failed else "PASS")
                self.assertEqual(len(stages[0]["test_durations"]), 4)
                if failed:
                    self.assertIn("LEAF_FAILURE_PROPAGATED", outcome.stdout + outcome.stderr)
                    self.assertIn("TEST_FAILURE_IMMEDIATE=", outcome.stdout + outcome.stderr)

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
            # This tiny fixture dispatches one owner stage, not repository shards.
            owner.pop("repository_integration_partition", None)
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
                    write_planned_request(root, request, [changed] if changed else None)
                    log = Path(logs) / f"stage_{index}.log"
                    result = subprocess.run([
                        "pwsh", "-NoProfile", "-File", str(root / "common/verify.ps1"),
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
                    "param($Level,$PythonExe,$StructuralVariant,$FreshnessPrevalidated,$PowerShellSyntaxPrevalidated,$RegistryPrevalidated,"
                    "[string[]]$ChangedTestModules)\n"
                    "& $PythonExe -m unittest @ChangedTestModules\n"
                    "if ($LASTEXITCODE -ne 0) { throw 'OWNER_TEST_FAILURE' }\n",
                    encoding="utf-8")
            # Batch the tiny cases in one PowerShell host. Keep the actual
            # selector and the InternalStage delegate; real CLI exit propagation
            # is still checked independently for both production owners below.
            probes = []
            for index, (prefix, filename, stage) in enumerate(cases):
                relative = f"{prefix}/tests/analysis/{filename}"
                for fails in (True, False):
                    probes.append(dict(relative=relative, stage=stage, fails=fails,
                        request=str(Path(logs) / f"request_{index}_{fails}.json"),
                        log=str(Path(logs) / f"stage_{index}_{fails}.log")))
            probe_path = Path(logs) / "mini_probes.json"
            report_path = Path(logs) / "mini_results.json"
            probe_path.write_text(json.dumps(probes), encoding="utf-8")
            driver = Path(logs) / "mini_dispatch.ps1"
            driver.write_text(r'''param($Repo,$Python,$Probes,$Report)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/parallel_gate_support.ps1')
. (Join-Path $Repo 'common/gate_catalog_support.ps1')
. (Join-Path $Repo 'common/host_execution_lease.ps1')
$results=@()
foreach($probe in (Get-Content -LiteralPath $Probes -Raw|ConvertFrom-Json)){
 $literal=if($probe.fails){'True'}else{'False'}
 $source="import unittest`nclass ChangedGateFailureProbe(unittest.TestCase):`n    def test_probe(self): self.assertFalse($literal, 'CHANGED_TEST_EXECUTED')`n"
 [IO.File]::WriteAllText((Join-Path $Repo $probe.relative),$source,[Text.UTF8Encoding]::new($false))
 & (Join-Path $Repo 'common/verify.ps1') -PythonExe $Python -PlanOnly -InternalRequestPath $probe.request -ChangedPath @($probe.relative)|Out-Null
 $passed=Invoke-ResolvedGateStage -RepoRoot $Repo -Stage $probe.stage -RequestPath $probe.request -LogPath $probe.log
 $expectedPassed=-not [bool]$probe.fails
 if([bool]$passed -ne $expectedPassed){
  $originalLog=Get-Content -LiteralPath $probe.log -Raw
  throw "MINI_GATE_UNEXPECTED_STATE case=$($probe.relative) fails=$($probe.fails) expected_passed=$expectedPassed actual_passed=$passed`n$originalLog"
 }
 $results+=@{relative=$probe.relative;fails=[bool]$probe.fails;exit_code=$(if($passed){0}else{1})}
}
ConvertTo-Json -InputObject @($results) -Depth 8|Set-Content -LiteralPath $Report -Encoding utf8
''', encoding="utf-8", newline="\n")
            dispatched = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(root),
                sys.executable, str(probe_path), str(report_path)], cwd=root, env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=180)
            self.assertEqual(dispatched.returncode, 0, dispatched.stdout + dispatched.stderr)
            results = json.loads(report_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(len(results), len(probes))
            for probe, result in zip(probes, results, strict=True):
                with self.subTest(path=probe["relative"], fails=probe["fails"]):
                    self.assertEqual((result["relative"], result["fails"]), (probe["relative"], probe["fails"]))
                    output = Path(probe["log"]).read_text(encoding="utf-8")
                    self.assertEqual(result["exit_code"] != 0, probe["fails"], output)
                    self.assertIn("CHANGED_TEST_EXECUTED" if probe["fails"] else "Ran 1 test", output)
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
                write_planned_request(root, request, [relative])
                log = Path(logs) / f"real_{index}.log"
                result = subprocess.run([
                    "pwsh", "-NoProfile", "-File", str(root / "common/verify.ps1"),
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
