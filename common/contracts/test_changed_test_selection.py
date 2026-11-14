"""Exercise owner test selection and failure propagation through public verification."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


    def partial_python_partition_fixture(self, root: Path) -> tuple[str, list[str]]:
        """Real planner/dispatch with five tiny tests and an unselected failing peer."""
        common = root / "common"
        tests = common / "contracts"
        tests.mkdir(parents=True)
        (root / "integrations").mkdir()
        (root / "projects").mkdir()
        for name in ("verify.ps1", "parallel_gate_support.ps1", "gate_catalog_support.ps1",
                     "require_powershell7.ps1", "gate_unittest.py"):
            shutil.copyfile(REPO_ROOT / "common" / name, common / name)
        (common / "host_execution_lease.ps1").write_text(
            "function Get-HostResourceBudget {param($Role,$Stage) @{}}\n"
            "function Enter-HostResourceStage {param($Role,$Stage,$Budget) @{}}\n"
            "function Exit-HostResourceStage {param($Lease)}\n", encoding="utf-8")
        (common / "verify_repository_hygiene.ps1").write_text("# Inert global check.\n", encoding="utf-8")
        (common / "verify_documentation.ps1").write_text(
            "param($PythonExe,$StructureOnly,[string[]]$ChangedPath)\n", encoding="utf-8")
        for name in ("verify_repository_text_bytes", "verify_development_standards"):
            (common / (name + ".py")).write_text("# Inert global check.\n", encoding="utf-8")
        (root / "ruff").mkdir()
        (root / "ruff/__init__.py").write_text("", encoding="utf-8")
        (root / "ruff/__main__.py").write_text("# Inert global lint.\n", encoding="utf-8")
        leaf = "common/contracts/partition_leaf.py"
        (root / leaf).write_text("# Explicit fixture dependency.\n", encoding="utf-8")
        (tests / "fixture_import.py").write_text("VALUE = 17\n", encoding="utf-8")
        (common / "prerequisite.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "(Path(os.environ['PARTIAL_EVENTS'])/'prerequisite').write_text('ready')\n", encoding="utf-8")
        body = """import json,os,time,unittest
from pathlib import Path
from fixture_import import VALUE
KEY = '__KEY__'
def event(kind):
    root=Path(os.environ['PARTIAL_EVENTS'])
    (root/(KEY+'.'+kind)).write_text(json.dumps({'time':time.perf_counter_ns(),'pid':os.getpid()}))
class Probe(unittest.TestCase):
    def test_probe(self):
        root=Path(os.environ['PARTIAL_EVENTS'])
        self.assertEqual((root/'prerequisite').read_text(), 'ready')
        self.assertEqual(VALUE, 17)
        event('start')
        try:
            if KEY in ('a','b'):
                buddy='b' if KEY=='a' else 'a'
                deadline=time.monotonic()+5
                while not (root/(buddy+'.start')).exists() and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertTrue((root/(buddy+'.start')).exists(), 'SECOND_WORKER_NOT_STARTED')
            time.sleep(1.0 if KEY=='b' and os.environ.get('PARTIAL_FAIL') else .2)
            self.assertFalse(KEY=='a' and os.environ.get('PARTIAL_FAIL'), 'PARTIAL_FAILURE')
        finally:
            event('done')
"""
        modules = ["common/contracts/test_" + name + ".py" for name in "abcde"]
        for name, relative in zip("abcde", modules):
            (root / relative).write_text(body.replace("__KEY__", name), encoding="utf-8")
        (tests / "test_unselected.py").write_text(
            "raise AssertionError('UNSELECTED_OWNER_TEST_MUST_NOT_RUN')\n", encoding="utf-8")
        catalog = json.loads((REPO_ROOT / "common/gate_catalog.json").read_text(encoding="utf-8"))
        route = next(x for x in catalog["routes"] if x["stage"] == "common_contracts")
        route["requires_stages"] = ["partition_prerequisite"]
        route["test_selection"]["dependencies"] = [dict(matches=[dict(exact=leaf, reason="fixture_leaf")],
                                                       modules=modules, dependency_profile="stdlib")]
        route["repository_integration_partition"]["count"] = 3
        route["repository_integration_partition"]["measured_seconds"] = {
            "test_a": 120, "test_b": 110, "test_c": 100, "test_d": 10, "test_e": 1}
        prerequisite = dict(stage="partition_prerequisite", dependency_profile="stdlib",
                            repository_integration_group="fast",
                            matches=[dict(exact="common/prerequisite.py", reason="fixture_prerequisite")],
                            command=dict(runner="python", arguments=["common/prerequisite.py"]))
        catalog["routes"] = [prerequisite, route]
        (common / "gate_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        return leaf, modules

    def test_heavy_partial_python_dispatch_preserves_union_prerequisite_and_failure_drain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="heavy_partial_dispatch_") as directory:
            root = Path(directory)
            leaf, modules = self.partial_python_partition_fixture(root)
            # Hold b until the real parent records failure, rather than assuming
            # its relative sleep exceeds a's process/receipt completion delay.
            for relative in modules:
                path = root / relative
                body = path.read_text(encoding="utf-8").replace(
                    "            time.sleep(1.0 if KEY=='b' and os.environ.get('PARTIAL_FAIL') else .2)",
                    """            if KEY=='b' and os.environ.get('PARTIAL_FAIL'):
                deadline=float(os.environ['PARTIAL_DISPATCH_DEADLINE'])
                while not (root/'parent.observed_failure').exists():
                    if time.monotonic() >= deadline:
                        raise AssertionError('PARENT_FAILURE_NOT_OBSERVED')
                    time.sleep(.01)
            else:
                time.sleep(.2)""")
                path.write_text(body, encoding="utf-8")
            with (root / "common/parallel_gate_support.ps1").open("a", encoding="utf-8") as stream:
                stream.write(r"""
$script:FixtureOriginalStageRecorder=${function:Set-GateStageResult}
function Set-GateStageResult {
    param($Summary, [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Collections.IDictionary]$Result)
    & $script:FixtureOriginalStageRecorder @PSBoundParameters
    if($env:PARTIAL_FAIL-and$null-ne$Summary-and$Name.StartsWith('common_contracts__tests_')-and
        $Result.Contains('status')-and$Result.status-eq'FAIL'){
        $observed=@{time=[long]([Diagnostics.Stopwatch]::GetTimestamp()*(1.0e9/[Diagnostics.Stopwatch]::Frequency));pid=$PID;stage=$Name}
        [IO.File]::WriteAllText((Join-Path $env:PARTIAL_EVENTS 'parent.observed_failure'),
            ($observed|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    }
}
""")
            catalog_path = root / "common/gate_catalog.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            (root / "common/original_owner.ps1").write_text(
                "param($PythonExe,[switch]$PreflightOnly,[string[]]$SelectedTestModules)\n"
                "throw 'Original owner must not execute for a pure Python test subset'\n", encoding="utf-8")
            cases = [(preflight, failed) for preflight in ("missing", True, False) for failed in (False, True)]
            for preflight, failed in cases:
                with self.subTest(partition_preflight=preflight, failed=failed):
                    current = json.loads(json.dumps(catalog))
                    route = next(row for row in current["routes"] if row["stage"] == "common_contracts")
                    if preflight is not False:
                        # Match a real PS owner whose pure test selection is
                        # converted to Python; a Python discovery owner itself
                        # must declare preflight=false to be a valid catalog.
                        route["command"] = dict(runner="powershell", script="common/original_owner.ps1",
                                                parameters=dict(PythonExe="{python}"))
                        route["repository_integration_command"] = dict(
                            runner="powershell", script="common/original_owner.ps1",
                            parameters=dict(PythonExe="{python}", PreflightOnly=True))
                        route["repository_integration_partition"]["parameter"] = "SelectedTestModules"
                    if preflight == "missing":
                        route.pop("partition_preflight", None)
                    else:
                        route["partition_preflight"] = preflight
                    catalog_path.write_text(json.dumps(current), encoding="utf-8")
                    case = f"{preflight}_{'failed' if failed else 'success'}"
                    events = root / (case + "_events")
                    events.mkdir()
                    environment = dict(os.environ, PARTIAL_EVENTS=str(events),
                                       PARTIAL_DISPATCH_DEADLINE=str(time.monotonic() + 45))
                    environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
                    environment.pop("PARTIAL_FAIL", None)
                    if failed:
                        environment["PARTIAL_FAIL"] = "1"
                    summary = root / (case + ".json")
                    command = ["pwsh", "-NoProfile", "-File", str(root / "common/verify.ps1"),
                               "-PythonExe", sys.executable, "-ChangedPath", leaf, "-MaxConcurrency", "2",
                               "-SummaryPath", str(summary)]
                    if preflight is not False:
                        command = ["pwsh", "-NoProfile", "-Command",
                                   "& " + powershell_literal(root / "common/verify.ps1") +
                                   " -PythonExe " + powershell_literal(sys.executable) + " -ChangedPath @(" +
                                   ",".join(map(powershell_literal, modules)) + ") -MaxConcurrency 2 -SummaryPath " +
                                   powershell_literal(summary)]
                    result = subprocess.run(
                        command, cwd=root, env=environment,
                        capture_output=True, text=True, encoding="utf-8", timeout=60)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode != 0, failed, output)
                    stages = {x["name"]: x for x in json.loads(summary.read_text(encoding="utf-8"))["stages"]}
                    parent = stages["common_contracts"]
                    self.assertEqual(parent["status"], "NOT_APPLICABLE", output)
                    self.assertEqual(parent["selection_reason"], "selected_partial_python_tests_partitioned")
                    parts = [x for name, x in stages.items() if name.startswith("common_contracts__tests_")]
                    self.assertEqual(len(parts), 3)
                    actual = [m for part in parts for m in part["command"]["arguments"][2:]]
                    self.assertCountEqual(actual, [m[:-3].replace("/", ".") for m in modules])
                    self.assertEqual(len(actual), len(set(actual)))
                    for part in parts:
                        self.assertEqual(part["selection_reason"], "selected_partial_python_test_partition")
                        self.assertEqual(part["dependency_profile"], "stdlib" if preflight is False else "locked")
                        self.assertEqual(part["requires_stages"], ["partition_prerequisite"])
                        self.assertEqual(part["command"]["python_path_roots"], ["common/contracts/"])
                    self.assertEqual(stages["partition_prerequisite"]["status"], "PASS", output)
                    starts = {p.stem: json.loads(p.read_text()) for p in events.glob("*.start")}
                    done = {p.stem: json.loads(p.read_text()) for p in events.glob("*.done")}
                    self.assertEqual(set(starts), set(done), output)
                    executed = [row["test"] for stage in stages.values() for row in stage["test_durations"]]
                    self.assertEqual(len(executed), len(set(executed)), output)
                    self.assertEqual(len(executed), len(starts), output)
                    self.assertIn("a", starts)
                    self.assertIn("b", starts)
                    timeline = sorted([(v["time"], 1) for v in starts.values()] +
                                      [(v["time"], -1) for v in done.values()])
                    active = peak = 0
                    for _, delta in timeline:
                        active += delta
                        peak = max(peak, active)
                    self.assertEqual(peak, 2, output)
                    if failed:
                        self.assertIn("PARTIAL_FAILURE", output)
                        self.assertCountEqual([part["status"] for part in parts], ["FAIL", "PASS", "BLOCKED"])
                        self.assertGreater(done["b"]["time"], done["a"]["time"])
                        observed = json.loads((events / "parent.observed_failure").read_text())
                        self.assertLess(done["a"]["time"], observed["time"])
                        self.assertLess(observed["time"], done["b"]["time"])
                        self.assertNotIn("c", starts, output)
                    else:
                        self.assertEqual(set(starts), set("abcde"))
                        self.assertEqual(sum(len(p["test_durations"]) for p in parts), 5)

    def test_partial_python_partition_cost_guards_and_complete_owner_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory(prefix="partial_partition_plans_") as directory:
            root = Path(directory)
            leaf, modules = self.partial_python_partition_fixture(root)
            weights = {"test_a": 120, "test_b": 110, "test_c": 100, "test_d": 10, "test_e": 1}
            cases = [dict(name="heavy", weights=weights),
                     dict(name="short", weights={k: v / 100 for k, v in weights.items()}),
                     dict(name="unknown", weights={k: v for k, v in weights.items() if k != "test_e"}),
                     dict(name="estimated", weights={}, default_seconds=120),
                     dict(name="estimated_short", weights={}, default_seconds=1),
                     dict(name="serial", weights=weights, concurrency=1),
                     dict(name="inherited", weights=weights, token="inherited_fixture_grant"),
                     dict(name="no_benefit", weights={"test_a": 341}, modules=modules[:1]),
                     dict(name="only_tests", weights=weights, paths=modules),
                     dict(name="owner", weights=weights, scope="Owner"),
                     dict(name="repository", weights=weights, scope="Repository")]
            request = root / "cases.json"
            request.write_text(json.dumps(cases), encoding="utf-8")
            script = r"""
$ErrorActionPreference='Stop'
$catalog=Get-Content common/gate_catalog.json -Raw|ConvertFrom-Json -AsHashtable
$originalToken=$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN
try {
 foreach($case in @(Get-Content __CASES__ -Raw|ConvertFrom-Json -AsHashtable)) {
  $current=$catalog|ConvertTo-Json -Depth 32|ConvertFrom-Json -AsHashtable
  $route=$current.routes|Where-Object stage -eq common_contracts
  $route.repository_integration_partition.measured_seconds=$case.weights
  if($case.ContainsKey('default_seconds')){$route.repository_integration_partition.default_seconds=$case.default_seconds}
  if($case.ContainsKey('modules')){$route.test_selection.dependencies[0].modules=$case.modules}
  $current|ConvertTo-Json -Depth 32|Set-Content common/gate_catalog.json -Encoding UTF8
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=if($case.ContainsKey('token')){$case.token}else{$null}
  $arguments=@{PythonExe=__PYTHON__;PlanOnly=$true;PlanPath=(Join-Path $PWD ($case.name+'.json'));
    MaxConcurrency=$(if($case.ContainsKey('concurrency')){$case.concurrency}else{2})}
  if($case.ContainsKey('scope')){
   $arguments.Scope=$case.scope
   if($case.scope-eq'Owner'){$arguments.Owner=@('common/contracts')}
  }else{$arguments.ChangedPath=if($case.ContainsKey('paths')){$case.paths}else{@(__LEAF__)}}
  & common/verify.ps1 @arguments|Out-Null
 }
}finally{$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=$originalToken}
"""
            script = script.replace("__CASES__", powershell_literal(request)).replace(
                "__PYTHON__", powershell_literal(sys.executable)).replace("__LEAF__", powershell_literal(leaf))
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root,
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for case in cases:
                with self.subTest(case=case["name"]):
                    plan = json.loads((root / (case["name"] + ".json")).read_text(encoding="utf-8-sig"))
                    parts = [s for s in plan["stages"] if s["name"].startswith("common_contracts__tests_")]
                    is_complete = case["name"] in {"owner", "repository"}
                    partitioned = case["name"] in {"heavy", "unknown", "estimated", "only_tests"} or is_complete
                    self.assertEqual(len(parts), 3 if partitioned else 0)
                    stages = {s["name"]: s for s in plan["stages"] + plan["skipped_stages"]}
                    if partitioned:
                        actual = [m for part in parts for m in part["command"]["arguments"][2:]]
                        expected = [m[:-3].replace("/", ".") for m in modules]
                        if is_complete:
                            expected.append("common.contracts.test_unselected")
                        self.assertCountEqual(actual, expected)
                        expected_reason = "complete_owner_test_partition" if is_complete else "selected_partial_python_test_partition"
                        self.assertTrue(all(p["reason"] == expected_reason for p in parts))
                        if not is_complete:
                            self.assertTrue(all(p["dependency_profile"] == ("locked" if case["name"] == "only_tests" else "stdlib") for p in parts))
                    else:
                        selected = stages["common_contracts"]
                        self.assertTrue(selected["selected"])
                        expected = case.get("modules", modules)
                        self.assertEqual(selected["command"]["arguments"][2:], expected)
                        self.assertEqual(selected["dependency_profile"], "stdlib")
                        self.assertEqual(selected["requires_stages"], ["partition_prerequisite"])


    def test_partial_partition_rejects_invalid_declared_default_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="partial_invalid_cost_") as directory:
            root = Path(directory)
            leaf, _ = self.partial_python_partition_fixture(root)
            catalog_path = root / "common/gate_catalog.json"
            original = json.loads(catalog_path.read_text(encoding="utf-8"))
            for invalid in (0, -1):
                with self.subTest(default_seconds=invalid):
                    catalog = json.loads(json.dumps(original))
                    route = next(row for row in catalog["routes"] if row["stage"] == "common_contracts")
                    route["repository_integration_partition"]["default_seconds"] = invalid
                    route["repository_integration_partition"]["measured_seconds"] = {}
                    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(root / "common/verify.ps1"),
                        "-PythonExe", sys.executable, "-ChangedPath", leaf, "-MaxConcurrency", "2", "-PlanOnly"],
                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("Invalid repository integration test partition", result.stdout + result.stderr)
                    self.assertFalse((root / "events").exists())

    def selected_powershell_fixture(self, root: Path) -> tuple[str, list[str]]:
        """Reuse the small Python fixture with the real integration replacement CLI."""
        _, originals = self.partial_python_partition_fixture(root)
        tests = root / "integrations/tests"
        tests.mkdir()
        for relative in originals + ["common/contracts/test_unselected.py"]:
            source = root / relative
            body = source.read_text(encoding="utf-8").replace(
                "from fixture_import import VALUE", "from integrations.tests.fixture_import import VALUE")
            body = body.replace("if KEY in ('a','b'):", "if KEY in ('a','b') and os.environ.get('PARTIAL_PARALLEL'):")
            body = body.replace("class Probe(unittest.TestCase):", """def wait_for_event(name):
    deadline=float(os.environ['PARTIAL_DISPATCH_DEADLINE'])
    while not (Path(os.environ['PARTIAL_EVENTS'])/name).exists():
        if time.monotonic() >= deadline:
            raise AssertionError('DISPATCH_EVENT_NOT_OBSERVED: '+name)
        time.sleep(.01)
class Probe(unittest.TestCase):""")
            body = body.replace("            time.sleep(1.0 if KEY=='b' and os.environ.get('PARTIAL_FAIL') else .2)", """            if os.environ.get('PARTIAL_FAIL'):
                late=bool(os.environ.get('PARTIAL_LATE_FAILURE'))
                if KEY=='a' and late:
                    wait_for_event('c.start')
                elif (KEY=='b' and not late) or (KEY=='c' and late):
                    wait_for_event('parent.observed_failure')
            elif os.environ.get('PARTIAL_PARALLEL'):
                time.sleep(.2)""")
            body = body.replace("self.assertEqual(VALUE, 17)",
                                "self.assertEqual(VALUE, 17); self.assertEqual(len(list(root.glob('ruff.*'))), 1)")
            (tests / source.name).write_text(body, encoding="utf-8")
        with (root / "common/parallel_gate_support.ps1").open("a", encoding="utf-8") as stream:
            stream.write(r"""
$script:FixtureOriginalStageRecorder=${function:Set-GateStageResult}
function Set-GateStageResult {
    param($Summary, [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Collections.IDictionary]$Result)
    & $script:FixtureOriginalStageRecorder @PSBoundParameters
    if($env:PARTIAL_FAIL-and$null-ne$Summary-and$Name.StartsWith('instrument_assembly_integration__tests_')-and
        $Result.Contains('status')-and$Result.status-eq'FAIL'){
        $observed=@{time=[long]([Diagnostics.Stopwatch]::GetTimestamp()*(1.0e9/[Diagnostics.Stopwatch]::Frequency));pid=$PID;stage=$Name}
        [IO.File]::WriteAllText((Join-Path $env:PARTIAL_EVENTS 'parent.observed_failure'),
            ($observed|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    }
}
""")
        shutil.copyfile(root / "common/contracts/fixture_import.py", tests / "fixture_import.py")
        shutil.copyfile(REPO_ROOT / "integrations/verify_integration.ps1", root / "integrations/verify_integration.ps1")
        with (root / "common/host_execution_lease.ps1").open("a", encoding="utf-8") as stream:
            stream.write("function Enter-HostExecutionLease {param($Role,$Stage) @{}}\n"
                         "function Exit-HostExecutionLease {param($Lease)}\n")
        (root / "ruff/__main__.py").write_text(
            "import os,sys\nfrom pathlib import Path\n"
            "kind='owner' if 'integrations/runtime' in sys.argv else 'root'\n"
            "(Path(os.environ['PARTIAL_EVENTS'])/('ruff.'+kind)).write_text('ready')\n",
            encoding="utf-8")
        leaf = "integrations/runtime/field_plan.py"
        (root / leaf).parent.mkdir()
        (root / leaf).write_text("# Known small source for the replacement consumer.\n", encoding="utf-8")
        modules = ["integrations/tests/test_" + name + ".py" for name in "abcde"]
        path = root / "common/gate_catalog.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        current = json.loads((REPO_ROOT / "common/gate_catalog.json").read_text(encoding="utf-8"))
        route = next(x for x in current["routes"] if x["stage"] == "instrument_assembly_integration")
        route.pop("runtime_dependencies_path")
        route["requires_stages"] = ["partition_prerequisite"]
        route["test_selection"]["module_parameter"] = "SelectedTestModules"
        route["test_selection"]["dependencies"] = [dict(matches=[dict(exact=leaf, reason="fixture_field_plan")],
                                                       modules=modules, dependency_profile="stdlib")]
        route["repository_integration_partition"]["count"] = 4
        route["repository_integration_partition"]["measured_seconds"] = {
            "test_a": 120, "test_b": 110, "test_c": 100, "test_d": 10, "test_e": 1}
        catalog["routes"] = [catalog["routes"][0], route]
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return leaf, modules

    def check_selected_powershell_dispatch(self, mode: str) -> None:
        with tempfile.TemporaryDirectory(prefix="powershell_subset_" + mode + "_") as directory:
            root = Path(directory)
            leaf, modules = self.selected_powershell_fixture(root)
            catalog_path = root / "common/gate_catalog.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            route = catalog["routes"][1]
            weights = route["repository_integration_partition"]["measured_seconds"]
            if mode == "unknown":
                weights.pop("test_e")
            elif mode == "short":
                route["repository_integration_partition"]["measured_seconds"] = {k: v / 100 for k, v in weights.items()}
            elif mode == "no_shared_ruff":
                leaf = "integrations/runtime/field_plan.json"
                (root / leaf).write_text("{}", encoding="utf-8")
                route["test_selection"]["dependencies"][0]["matches"][0]["exact"] = leaf
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            events = root / "events"
            events.mkdir()
            environment = dict(os.environ, PARTIAL_EVENTS=str(events))
            for key in ("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", "PARTIAL_PARALLEL", "PARTIAL_FAIL", "PARTIAL_LATE_FAILURE", "PARTIAL_DISPATCH_DEADLINE"):
                environment.pop(key, None)
            parallel = mode in {"heavy", "unknown", "failed", "late_failure"}
            if parallel:
                environment["PARTIAL_PARALLEL"] = "1"
            if mode in {"failed", "late_failure"}:
                environment["PARTIAL_FAIL"] = "1"
            if mode == "late_failure":
                environment["PARTIAL_LATE_FAILURE"] = "1"
            if mode == "inherited":
                environment["MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN"] = "fixture_inherited_grant"
            summary = root / "summary.json"
            # Keep the existing 60s total subprocess budget; reserve its last 5s
            # for ordinary child/owner shutdown after a failed event condition.
            environment["PARTIAL_DISPATCH_DEADLINE"] = str(time.monotonic() + 55)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(root / "common/verify.ps1"),
                 "-PythonExe", sys.executable, "-ChangedPath", leaf, "-MaxConcurrency",
                 "1" if mode == "serial" else "2", "-SummaryPath", str(summary)], cwd=root,
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode != 0, mode in {"failed", "late_failure"}, output)
            stages = {x["name"]: x for x in json.loads(summary.read_text(encoding="utf-8"))["stages"]}
            parent = stages["instrument_assembly_integration"]
            parts = [x for name, x in stages.items() if name.startswith("instrument_assembly_integration__tests_")]
            self.assertEqual(len(parts), 4 if parallel else 0, output)
            executed = parts if parallel else [parent]
            actual = [m for part in executed for m in part["command"]["parameters"]["SelectedTestModules"]]
            self.assertCountEqual(actual, [m[:-3].replace("/", ".") for m in modules])
            self.assertEqual(len(actual), len(set(actual)))
            for part in executed:
                self.assertEqual(part["command"]["script"], "integrations/verify_integration.ps1")
                self.assertNotIn("ChangedTestModules", part["command"]["parameters"])
                self.assertEqual(part["command"]["parameters"]["PythonExe"], sys.executable)
                self.assertEqual(part["dependency_profile"], "stdlib")
                self.assertIn("partition_prerequisite", part["requires_stages"])
                if mode != "no_shared_ruff":
                    self.assertTrue(part["command"]["parameters"]["PreflightValidated"])
                    self.assertIn("ruff_changed_python", part["requires_stages"])
                    self.assertEqual(stages["ruff_changed_python"]["status"], "PASS")
                    if part["started_at"]:
                        self.assertLessEqual(stages["ruff_changed_python"]["finished_at"], part["started_at"])
                else:
                    self.assertFalse(part["command"]["parameters"].get("PreflightValidated", False))
            self.assertEqual(len(list(events.glob("ruff.*"))), 1, output)
            self.assertTrue((events / ("ruff.owner" if mode == "no_shared_ruff" else "ruff.root")).exists())
            starts = {p.stem: json.loads(p.read_text()) for p in events.glob("*.start")}
            done = {p.stem: json.loads(p.read_text()) for p in events.glob("*.done")}
            self.assertEqual(set(starts), set(done), output)
            self.assertTrue({"a", "b"}.issubset(starts))
            if not parallel:
                self.assertEqual(len({row["pid"] for row in starts.values()}), 1, output)
            timeline = sorted([(v["time"], 1) for v in starts.values()] + [(v["time"], -1) for v in done.values()])
            active = peak = 0
            for _, delta in timeline:
                active += delta
                peak = max(peak, active)
            self.assertEqual(peak, 2 if parallel else 1, output)
            if mode in {"failed", "late_failure"}:
                observed = json.loads((events / "parent.observed_failure").read_text(encoding="utf-8"))
                print("SELECTED_POWERSHELL_DISPATCH_EVIDENCE=" + json.dumps(dict(
                    mode=mode, source=str(Path(__file__).resolve()), starts=starts, done=done,
                    observed_failure=observed, statuses=[p["status"] for p in parts])), flush=True)
                self.assertIn("PARTIAL_FAILURE", output)
                self.assertGreater(observed["time"], done["a"]["time"])
                if mode == "failed":
                    self.assertCountEqual([p["status"] for p in parts], ["FAIL", "PASS", "BLOCKED", "BLOCKED"])
                    self.assertEqual(set(starts), {"a", "b"})
                    self.assertGreater(done["b"]["time"], observed["time"])
                else:
                    self.assertCountEqual([p["status"] for p in parts], ["FAIL", "PASS", "PASS", "BLOCKED"])
                    self.assertEqual(set(starts), {"a", "b", "c"})
                    self.assertLess(done["b"]["time"], starts["c"]["time"])
                    self.assertLess(starts["c"]["time"], done["a"]["time"])
                    self.assertGreater(done["c"]["time"], observed["time"])
            else:
                self.assertEqual(set(starts), set("abcde"))
                self.assertEqual(sum(len(p["test_durations"]) for p in executed), 5)

    def test_selected_powershell_heavy_subset_partitions_and_failure_drain(self) -> None:
        for mode in ("heavy", "failed"):
            with self.subTest(mode=mode):
                self.check_selected_powershell_dispatch(mode)

    def test_selected_powershell_dispatches_ready_work_before_a_late_failure(self) -> None:
        self.check_selected_powershell_dispatch("late_failure")

    def test_selected_powershell_cost_fallbacks_keep_one_real_subset_and_ruff(self) -> None:
        for mode in ("short", "unknown", "serial", "inherited", "no_shared_ruff"):
            with self.subTest(mode=mode):
                self.check_selected_powershell_dispatch(mode)

    def test_selected_powershell_full_owner_and_repository_keep_complete_coverage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="powershell_complete_plan_") as directory:
            root = Path(directory)
            _, modules = self.selected_powershell_fixture(root)
            script = r"""
$ErrorActionPreference='Stop'
foreach($scope in @('Owner','Repository')){
 $arguments=@{Scope=$scope;PythonExe=__PYTHON__;PlanOnly=$true;MaxConcurrency=2;
   PlanPath=(Join-Path $PWD ($scope+'.json'))}
 if($scope-eq'Owner'){$arguments.Owner=@('instrument_assembly')}
 & common/verify.ps1 @arguments|Out-Null
}
""".replace("__PYTHON__", powershell_literal(sys.executable))
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=root,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for scope in ("Owner", "Repository"):
                plan = json.loads((root / (scope + ".json")).read_text(encoding="utf-8"))
                parts = [p for p in plan["stages"] if p["name"].startswith("instrument_assembly_integration__tests_")]
                self.assertEqual(len(parts), 4)
                actual = [m for p in parts for m in p["command"]["parameters"]["SelectedTestModules"]]
                self.assertCountEqual(actual, [m[:-3].replace("/", ".") for m in modules] +
                                      ["integrations.tests.test_unselected"])
                self.assertEqual(len(actual), len(set(actual)))
                for part in parts:
                    self.assertEqual(part["reason"], "complete_owner_test_partition")
                    self.assertEqual(part["command"]["script"], "integrations/verify_integration.ps1")
                    self.assertTrue(part["command"]["parameters"]["PreflightValidated"])
                    self.assertNotIn("ChangedTestModules", part["command"]["parameters"])

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

    def test_dual_cone_operation_and_terminal_analysis_select_actual_consumers(self) -> None:
        paths = ["src/msplatform/backends/simion/dual_cone_stage_execution.py",
                 "src/msplatform/workflows/dual_cone_stages.py",
                 "src/msplatform/backends/simion/dual_cone_stages.py",
                 "src/msplatform/workflows/dual_cone_transport.py",
                 "src/msplatform/backends/simion/dual_cone_transport_execution.py",
                 "src/msplatform/backends/simion/dual_cone_geometry.py",
                 "src/msplatform/analysis/terminal_plane.py"]
        cases = [dict(stage="common_contracts", paths=[path]) for path in paths]
        cases.append(dict(stage="simion_common", paths=[paths[-1]]))
        selected = self.selections(REPO_ROOT, cases)
        for result in selected[:-1]:
            self.assertIn("common/contracts/test_dual_cone_transport_execution.py", result["Modules"])
            self.assertIn("common/contracts/test_dual_cone_transport.py", result["Modules"])
            self.assertIn("common/contracts/test_dual_cone_stages.py", result["Modules"])
            self.assertIn("common/contracts/test_dual_cone_managed_stages.py", result["Modules"])
        self.assertEqual(selected[-1]["Modules"], ["common/simion/test_analyze_terminal_plane.py"])

    def test_single_reflection_frontend_producer_selects_actual_owner_consumers(self) -> None:
        path = 'src/msplatform/workflows/single_reflection_flight/frontend_fields.py'
        result, = self.selections(REPO_ROOT, [dict(stage='instrument_assembly_integration', paths=[path])])
        for module in ('test_single_reflection_field_stage', 'test_single_reflection_execute',
                       'test_dependencies', 'test_native_path_consumers'):
            self.assertIn('integrations/tests/' + module + '.py', result['Modules'])
        self.assertEqual(result['Reason'], 'declared_owner_module_dependencies')

    def test_unmapped_simion_source_preserves_native_exclusions(self) -> None:
        paths = ["src/msplatform/execution/recovery.py",
                 "src/msplatform/backends/simion/gem_primitives.py",
                 "src/msplatform/backends/simion/aperture.py"]
        cases = [dict(stage="simion_common", paths=[path]) for path in paths]
        excluded = "common/simion/test_dirichlet_patch_basis.py"
        expected = {path.relative_to(REPO_ROOT).as_posix()
                    for path in (REPO_ROOT / "common/simion").rglob("test_*.py")} - {excluded}
        for path, result in zip(paths, self.selections(REPO_ROOT, cases, owner_filter=True)):
            with self.subTest(path=path):
                self.assertEqual(result["Reason"], "explicit_discovery_preserves_native_exclusions")
                self.assertTrue(result["OnlyTestModules"])
                self.assertFalse(result["CompleteOwner"])
                self.assertCountEqual(result["Modules"], expected)
        # Exercise the public command planner as well as its actual owner filter.
        with tempfile.TemporaryDirectory(prefix="native_exclusion_plan_") as directory:
            request = Path(directory) / "plan.json"
            write_planned_request(REPO_ROOT, request, [paths[0]])
            plan = json.loads(request.read_text(encoding="utf-8"))
        stage = next(stage for stage in plan["stages"] if stage["name"] == "simion_common")
        self.assertEqual(stage["command"]["arguments"][:2], ["-m", "common.gate_unittest"])
        self.assertCountEqual(stage["command"]["arguments"][2:], expected)
        self.assertEqual(stage["resource_role"], "GATE")

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
            # Augmentation keeps the original owner command and must still
            # include explicitly changed tests in mixed production changes.
            if offset < 10:
                self.assertEqual(results[offset + 1]["Modules"], [changed])
                self.assertFalse(results[offset + 1]["OnlyTestModules"])
                self.assertFalse(results[offset + 1]["CompleteOwner"])
            else:
                # Replacement subsets cannot narrow unknown production scope.
                self.assertIsNone(results[offset + 1])
            for index in range(offset + 2, offset + 5):
                with self.subTest(paths=cases[index]["paths"]):
                    self.assertTrue(results[index]["Expanded"])
                    self.assertIn(changed, results[index]["Modules"])

    def test_augmentation_does_not_override_a_replacement_partition_parameter(self) -> None:
        changed = f"{MR}/tests/analysis/test_workpoint_controller_state.py"
        script = r"""
. __SUPPORT__
$route=(Read-GateCatalog -RepoRoot $PWD.Path)|Where-Object stage -eq 'parallel_mirror_dual_stripe_mr_tof_static'
$route.repository_integration_partition.parameter='ChangedTestModules'
$selected=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots @($route.test_selection.roots) `
 -ChangedPaths @(__TEST__, 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/unknown_source.py')
@{selection=$selected}|ConvertTo-Json -Depth 8 -Compress
""".replace("__SUPPORT__", powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1"))
        script = script.replace("__TEST__", powershell_literal(changed))
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNone(json.loads(result.stdout)["selection"])

    def test_mr_workpoint_sources_augment_core_with_actual_consumers(self) -> None:
        stage = "parallel_mirror_dual_stripe_mr_tof_static"
        dependencies = (
            ("workpoint_controller_state.py", ("test_workpoint_controller_state", "test_downstream_workpoint_iteration_runner")),
            ("downstream_workpoint_iteration.py", ("test_downstream_workpoint_iteration",
             "test_downstream_workpoint_checkpoint", "test_downstream_workpoint_iteration_runner")),
            ("run_downstream_workpoint_iteration.ps1", ("test_downstream_workpoint_iteration_runner",
             "test_static_workpoint_iteration", "test_prism_runner_contract_matrix")),
        )
        with tempfile.TemporaryDirectory(prefix="mr_source_augmentation_") as directory:
            root = Path(directory)
            cases = [dict(name=str(index), paths=[f"{MR}/analysis/{source}"],
                          modules=sorted(f"{MR}/tests/analysis/{name}.py" for name in modules))
                     for index, (source, modules) in enumerate(dependencies)]
            cases.append(dict(name="union", paths=[path for case in cases for path in case["paths"]],
                              modules=sorted({module for case in cases for module in case["modules"]})))
            cases.append(dict(name="unknown", paths=[f"{MR}/analysis/unmapped_source.py"], modules=[]))
            request = root / "cases.json"
            request.write_text(json.dumps(cases), encoding="utf-8")
            script = r"""
$ErrorActionPreference='Stop'
$results=@(foreach($case in (Get-Content -LiteralPath __CASES__ -Raw|ConvertFrom-Json)){
 $plan=Join-Path __OUT__ ($case.name+'.json')
 & __VERIFY__ -PythonExe __PYTHON__ -ChangedPath @($case.paths) -PlanOnly -PlanPath $plan|Out-Null
 $item=(Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json).stages|Where-Object name -eq __STAGE__
 @{name=$case.name;run=$item.selected;command=$item.command;reason=$item.reason}
})
ConvertTo-Json -InputObject $results -Depth 16 -Compress
"""
            for token, value in (("__CASES__", request), ("__OUT__", root),
                                 ("__VERIFY__", REPO_ROOT / "common/verify.ps1"),
                                 ("__PYTHON__", sys.executable), ("__STAGE__", stage)):
                script = script.replace(token, powershell_literal(value))
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            results = json.loads(result.stdout)
            self.assertEqual(len(results), len(cases))
            for case, item in zip(cases, results, strict=True):
                with self.subTest(source=case["name"]):
                    self.assertTrue(item["run"])
                    command = item["command"]
                    self.assertEqual(command["runner"], "powershell")
                    self.assertEqual(command["parameters"]["Level"], "Core")
                    self.assertNotIn("SelectedTestModules", command["parameters"])
                    selected = command["parameters"].get("ChangedTestModules", [])
                    self.assertCountEqual(selected, [module[:-3].replace("/", ".") for module in case["modules"]])
                    self.assertEqual(len(selected), len(set(selected)))

    def test_installed_mirror_l0_and_search_augment_core_with_actual_consumers(self) -> None:
        stage = 'parallel_mirror_dual_stripe_mr_tof_static'
        domain = 'src/msplatform/components/parallel_mirror_dual_stripe_mr_tof/mirror_l0.py'
        workflow = 'src/msplatform/workflows/mr_design.py'
        math_modules = sorted(f"{MR}/tests/analysis/{name}.py" for name in (
            'test_dual_stripe_l0_math', 'test_fixed_grid_mirror_stripe_handoff',
            'test_joint_mirror_stripe_l0', 'test_mirror_exact_k_operating_point',
            'test_simion_candidate_reference', 'test_two_prism_segmented_transport',
            'test_two_prism_segmented_voltage_seed', 'test_mirror_l0_l1_runner',
            'test_prism_runner_contract_matrix'))
        search_modules = sorted(f"{MR}/tests/analysis/{name}.py" for name in (
            'test_simion_candidate_reference', 'test_mirror_l0_l1_runner',
            'test_dual_stripe_l0_math', 'test_fixed_grid_mirror_stripe_handoff',
            'test_prism_runner_contract_matrix'))
        runner_modules = sorted(f"{MR}/tests/analysis/{name}.py" for name in (
            'test_mirror_l0_l1_runner', 'test_prism_runner_contract_matrix'))
        stripe_runner_modules = sorted([*runner_modules,
            f"{MR}/tests/analysis/test_managed_analysis_runner_contracts.py",
            f"{MR}/tests/analysis/test_native_candidate_condition_runner.py"])
        changed_test = f"{MR}/tests/analysis/test_two_prism_segmented_coverage.py"
        cases = [
            dict(stage=stage, paths=[domain], modules=math_modules),
            dict(stage=stage, paths=[workflow], modules=search_modules),
            dict(stage=stage, paths=[domain, workflow, changed_test],
                 modules=sorted([*math_modules, changed_test])),
            dict(stage=stage, paths=[f"{MR}/analysis/mirror_l0.py"], modules=None),
        ]
        for runner in ('run_dual_stripe_operating_seed.ps1',
                       'run_mirror_exact_k_operating_point.ps1',
                       'run_mirror_l0_l1_candidate.ps1',
                       'run_two_prism_segmented_continuation.ps1',
                       'run_two_prism_segmented_coverage.ps1'):
            # Only the four changed Stripe source lists gain these two tests.
            expected = (runner_modules if runner == 'run_mirror_l0_l1_candidate.ps1'
                        else stripe_runner_modules)
            cases.append(dict(stage=stage, paths=[f"{MR}/analysis/{runner}"], modules=expected))
        # Combination and runner mappings use the existing selector boundary in
        # one host. Keep real public CLI coverage for each new canonical path.
        for case, selected in zip(cases, self.selections(REPO_ROOT, cases), strict=True):
            with self.subTest(paths=case['paths']):
                if case['modules'] is None:
                    self.assertIsNone(selected)
                else:
                    self.assertCountEqual(selected['Modules'], case['modules'])
                    self.assertEqual(len(selected['Modules']), len(set(selected['Modules'])))
                    self.assertFalse(selected['CompleteOwner'])
                    self.assertFalse(selected['OnlyTestModules'])
        with tempfile.TemporaryDirectory(prefix='mr_l0_public_plans_') as directory:
            for index, case in enumerate(cases[:2]):
                with self.subTest(public_path=case['paths'][0]):
                    request = Path(directory) / f'plan-{index}.json'
                    write_planned_request(REPO_ROOT, request, case['paths'])
                    plan = json.loads(request.read_text(encoding='utf-8-sig'))
                    selected = [row for row in plan['stages'] if row['selected'] and row['name'] == stage]
                    self.assertEqual(len(selected), 1)
                    command = selected[0]['command']
                    self.assertEqual(command['runner'], 'powershell')
                    self.assertEqual(command['script'], MR + '/verify_project.ps1')
                    self.assertEqual(command['parameters']['Level'], 'Core')
                    self.assertNotIn('SelectedTestModules', command['parameters'])
                    modules = command['parameters']['ChangedTestModules']
                    self.assertCountEqual(modules, [name[:-3].replace('/', '.') for name in case['modules']])
                    self.assertEqual(len(modules), len(set(modules)))

    def test_installed_operating_pa_cache_and_composer_select_actual_consumers(self) -> None:
        cache = 'src/msplatform/backends/simion/operating_pa_cache.py'
        composer = 'src/msplatform/backends/simion/resources/compose_standalone_pa.lua'
        common = 'common/simion/'
        common_composer = [common + name for name in (
            'test_operating_pa_cache.py', 'test_standalone_pa_composition_tools.py',
            'test_export_standalone_pa.py')]
        mr = [MR + '/tests/analysis/test_static_field_binding.py']
        local = ['integrations/tests/test_dependencies.py']
        cases = [
            dict(stage='simion_common', paths=[cache], modules=[common + 'test_operating_pa_cache.py']),
            dict(stage='simion_common', paths=[composer], modules=common_composer),
            dict(stage='simion_common', paths=[cache, composer], modules=common_composer),
            dict(stage='parallel_mirror_dual_stripe_mr_tof_static', paths=[cache], modules=mr),
            dict(stage='parallel_mirror_dual_stripe_mr_tof_static', paths=[composer], modules=mr),
            dict(stage='instrument_assembly_integration', paths=[composer], modules=local),
            dict(stage='parallel_mirror_dual_stripe_mr_tof_static',
                 paths=['src/msplatform/components/parallel_mirror_dual_stripe_mr_tof/operating_pa_identity.py'],
                 modules=None),
        ]
        for case, selected in zip(cases, self.selections(REPO_ROOT, cases), strict=True):
            with self.subTest(stage=case['stage'], paths=case['paths']):
                if case['modules'] is None:
                    self.assertIsNone(selected)
                else:
                    self.assertCountEqual(selected['Modules'], case['modules'])
                    self.assertEqual(len(selected['Modules']), len(set(selected['Modules'])))
                    self.assertFalse(selected['CompleteOwner'])
                    self.assertFalse(selected['OnlyTestModules'])

    def test_installed_mr_prism_phase_sources_augment_core_with_actual_consumers(self) -> None:
        stage = 'parallel_mirror_dual_stripe_mr_tof_static'
        canonical = 'src/msplatform/components/parallel_mirror_dual_stripe_mr_tof/'
        dependencies = {
            'drift_phase_contract': [
                'test_downstream_fixed_grid_workpoint',
                'test_drift_phase_contract',
                'test_dual_stripe_l0_math',
                'test_fixed_grid_mirror_stripe_handoff',
                'test_ip_prism_distance_study',
                'test_joint_flight_preparation',
                'test_joint_mirror_stripe_l0',
                'test_mirror_exact_k_operating_point',
                'test_mirror_l0_l1_runner',
                'test_prepared_joint_trial',
                'test_prism_analytic',
                'test_prism_mirror_transport',
                'test_prism_runner_contract_matrix',
                'test_simion_candidate_reference',
                'test_simion_event_analysis',
                'test_static_field_binding',
                'test_static_workpoint_iteration',
                'test_two_prism_segmented_coverage',
                'test_two_prism_segmented_transport',
                'test_two_prism_segmented_voltage_continuation',
                'test_two_prism_segmented_voltage_seed',
                'test_two_prism_simion_trial',
            ],
            'prism_analytic': [
                'test_mirror_l0_l1_runner',
                'test_prism_analytic',
                'test_prism_mirror_transport',
                'test_prism_runner_contract_matrix',
                'test_two_prism_segmented_coverage',
                'test_two_prism_segmented_transport',
                'test_two_prism_segmented_voltage_continuation',
                'test_two_prism_segmented_voltage_seed',
            ],
            'prism_l0': [
                'test_mirror_l0_l1_runner',
                'test_prism_analytic',
                'test_prism_l0',
                'test_prism_mirror_transport',
                'test_prism_runner_contract_matrix',
                'test_two_prism_segmented_coverage',
                'test_two_prism_segmented_transport',
                'test_two_prism_segmented_voltage_continuation',
                'test_two_prism_segmented_voltage_seed',
            ],
        }
        cases = [dict(stage=stage, paths=[canonical + name + '.py'],
                      modules=sorted(f"{MR}/tests/analysis/{module}.py" for module in modules))
                 for name, modules in dependencies.items()]
        cases.append(dict(stage=stage, paths=[path for case in cases for path in case['paths']],
                          modules=sorted({module for case in cases for module in case['modules']})))
        consumers = {
            'dual_stripe_l0': None,
            'dual_stripe_operating_seed': [
                'test_dual_stripe_l0_math',
                'test_fixed_grid_mirror_stripe_handoff',
                'test_mirror_l0_l1_runner',
                'test_prism_runner_contract_matrix',
            ],
            'joint_flight_preparation': [
                'test_ip_prism_distance_study',
                'test_joint_flight_preparation',
                'test_prepared_joint_trial',
            ],
            'mirror_exact_k_operating_point': [
                'test_mirror_exact_k_operating_point',
                'test_mirror_l0_l1_runner',
                'test_prism_runner_contract_matrix',
            ],
            'simion_event_analysis': [
                'test_simion_candidate_reference',
                'test_simion_event_analysis',
            ],
            'two_prism_segmented_transport': [
                'test_two_prism_segmented_coverage',
                'test_two_prism_segmented_transport',
                'test_two_prism_segmented_voltage_continuation',
                'test_two_prism_segmented_voltage_seed',
            ],
            'two_prism_simion_trial': [
                'test_downstream_fixed_grid_workpoint',
                'test_mr_provider_trial_transport',
                'test_prepared_joint_trial',
                'test_static_field_binding',
                'test_static_workpoint_iteration',
                'test_two_prism_simion_trial',
            ],
        }
        cases.extend(dict(stage=stage, paths=[f"{MR}/analysis/{name}.py"],
                          modules=(None if modules is None else
                                   sorted(f"{MR}/tests/analysis/{module}.py" for module in modules)))
                     for name, modules in consumers.items())
        for name in dependencies:
            cases.append(dict(stage=stage, paths=[f"{MR}/analysis/{name}.py"], modules=None))
        for case, selected in zip(cases, self.selections(REPO_ROOT, cases), strict=True):
            with self.subTest(paths=case['paths']):
                if case['modules'] is None:
                    self.assertIsNone(selected)
                else:
                    self.assertCountEqual(selected['Modules'], case['modules'])
                    self.assertEqual(len(selected['Modules']), len(set(selected['Modules'])))
                    self.assertFalse(selected['CompleteOwner'])
                    self.assertFalse(selected['OnlyTestModules'])

    def test_installed_mr_stripe_and_native_analysis_select_actual_consumers(self) -> None:
        stage = 'parallel_mirror_dual_stripe_mr_tof_static'
        canonical = 'src/msplatform/components/parallel_mirror_dual_stripe_mr_tof/dual_stripe_l0.py'
        workflow = 'src/msplatform/workflows/mr_design.py'
        stripe_names = [
            'test_downstream_fixed_grid_workpoint',
            'test_downstream_workpoint_iteration',
            'test_dual_stripe_l0_math',
            'test_fixed_grid_mirror_stripe_handoff',
            'test_joint_mirror_stripe_l0',
            'test_managed_analysis_runner_contracts',
            'test_measured_component_source',
            'test_mirror_exact_k_operating_point',
            'test_mirror_l0_l1_runner',
            'test_native_candidate_condition_runner',
            'test_prepared_joint_trial',
            'test_prism_runner_contract_matrix',
            'test_simion_candidate_reference',
            'test_static_field_binding',
            'test_static_workpoint_iteration',
            'test_two_prism_simion_trial',
        ]
        search_names = [
            'test_dual_stripe_l0_math',
            'test_fixed_grid_mirror_stripe_handoff',
            'test_mirror_l0_l1_runner',
            'test_prism_runner_contract_matrix',
            'test_simion_candidate_reference',
        ]
        runner_names = [
            'test_managed_analysis_runner_contracts',
            'test_mirror_l0_l1_runner',
            'test_native_candidate_condition_runner',
            'test_prism_runner_contract_matrix',
        ]
        cases = [
            dict(stage=stage, paths=[canonical], modules=stripe_names),
            dict(stage=stage, paths=[workflow], modules=search_names),
            dict(stage=stage, paths=[canonical, workflow],
                 modules=sorted(set(stripe_names + search_names))),
            # Deleted production sources cannot authorize stale leaf selection.
            dict(stage=stage, paths=[MR + '/analysis/dual_stripe_l0.py'], modules=None),
        ]
        for runner in [
            'run_dual_stripe_operating_seed.ps1',
            'run_mirror_exact_k_operating_point.ps1',
            'run_two_prism_segmented_continuation.ps1',
            'run_two_prism_segmented_coverage.ps1',
        ]:
            cases.append(dict(stage=stage, paths=[MR + '/analysis/' + runner], modules=runner_names))
        for case in cases:
            if case['modules'] is not None:
                case['modules'] = sorted(f"{MR}/tests/analysis/{name}.py" for name in case['modules'])
        for case, selected in zip(cases, self.selections(REPO_ROOT, cases), strict=True):
            with self.subTest(paths=case['paths']):
                if case['modules'] is None:
                    self.assertIsNone(selected)
                else:
                    self.assertCountEqual(selected['Modules'], case['modules'])
                    self.assertEqual(len(selected['Modules']), len(set(selected['Modules'])))
                    self.assertFalse(selected['CompleteOwner'])
                    self.assertFalse(selected['OnlyTestModules'])

    def test_weighted_partitions_cover_each_actual_owner_scope_once(self) -> None:
        script = r"""
. __SUPPORT__
$routes=(Get-Content -LiteralPath __CATALOG__ -Raw|ConvertFrom-Json).routes
$roots=@($routes|ForEach-Object {if($null-ne$_.PSObject.Properties['test_selection']){$_.test_selection.roots}})
$results=@{}
foreach($route in @($routes|Where-Object stage -in @('parallel_mirror_dual_stripe_mr_tof_static',
 'instrument_assembly_integration','single_reflection_oa_tof_mass_analyzer_static','rf_multipole_quadrupole_static'))){
$selection=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots $roots -FullScope -ChangedPaths @()
$partitions=@(Get-GateRepositoryTestPartitions -Route $route -RepoRoot $PWD.Path -Modules $selection.Modules)
$results[$route.stage]=@{partitions=$partitions;selected=@($selection.Modules);expanded=$selection.Expanded;
 only_tests=$selection.OnlyTestModules;preflight=$route.repository_integration_command.parameters.PreflightOnly;
 parent_preserved=($null-eq$route.PSObject.Properties['partition_preflight'] -or $route.partition_preflight)}
}
$planPath=Join-Path ([IO.Path]::GetTempPath()) (([guid]::NewGuid().ToString('N'))+'.json')
try{
 & (Join-Path $PWD.Path 'common/verify.ps1') -Scope Repository -PlanOnly -PlanPath $planPath|Out-Null
 if($LASTEXITCODE-ne0){throw 'Actual Repository planning failed'}
 $plan=Get-Content -LiteralPath $planPath -Raw|ConvertFrom-Json
 foreach($name in @($results.Keys)){
  $children=@($plan.stages|Where-Object {$_.name.StartsWith($name+'__tests_')})
  $results[$name].actual_planned_modules=@($children|ForEach-Object {$_.command.parameters.SelectedTestModules})
 }
}finally{Remove-Item -LiteralPath $planPath -ErrorAction SilentlyContinue}
$results|ConvertTo-Json -Depth 12 -Compress
"""
        script = script.replace('__SUPPORT__', powershell_literal(REPO_ROOT / 'common/gate_catalog_support.ps1'))
        script = script.replace('__CATALOG__', powershell_literal(REPO_ROOT / 'common/gate_catalog.json'))
        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        routes = json.loads((REPO_ROOT / 'common/gate_catalog.json').read_text(encoding='utf-8'))['routes']
        known_roots = {root for row in routes for root in row.get('test_selection', {}).get('roots', [])}
        for name, selected in data.items():
            with self.subTest(owner=name):
                route = next(row for row in routes if row['stage'] == name)
                owned_roots = set(route['test_selection']['roots'])
                expected = {path.relative_to(REPO_ROOT).as_posix()[:-3].replace('/', '.')
                            for path in (REPO_ROOT / route['test_selection']['scope']).rglob('test_*.py')
                            if not any(path.relative_to(REPO_ROOT).as_posix().startswith(root)
                                       for root in known_roots - owned_roots)}
                actual = [module for part in selected['partitions'] for module in part['modules']]
                self.assertEqual(len(selected['partitions']), route['repository_integration_partition']['count'])
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(actual), len(set(actual)))
                self.assertCountEqual(selected['actual_planned_modules'], actual)
                self.assertEqual({path[:-3].replace('/', '.') for path in selected['selected']}, expected)
                self.assertTrue(selected['expanded'])
                self.assertFalse(selected['only_tests'])
                self.assertTrue(selected['preflight'])
                self.assertEqual(selected['parent_preserved'], name != 'instrument_assembly_integration')

    def test_partition_weights_are_owner_local_and_unknown_modules_keep_default(self) -> None:
        script = r"""
. __SUPPORT__
$results=@{}
foreach($owner in @('first','second')){
 $weight=if($owner-eq'first'){100}else{10}
 $route=[pscustomobject]@{stage=$owner;test_selection=[pscustomobject]@{scope='unused/'};
  repository_integration_partition=[pscustomobject]@{count=2;default_seconds=7;
   measured_seconds=[pscustomobject]@{test_same_name=$weight}}}
 $results[$owner]=@(Get-GateRepositoryTestPartitions -Route $route -RepoRoot $PWD.Path `
  -Modules @("$owner/tests/test_same_name.py","$owner/tests/new_area/test_unknown.py"))
}
$results|ConvertTo-Json -Depth 8 -Compress
""".replace('__SUPPORT__', powershell_literal(REPO_ROOT / 'common/gate_catalog_support.ps1'))
        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for owner, groups in json.loads(result.stdout).items():
            self.assertCountEqual([module for group in groups for module in group['modules']],
                                  [f'{owner}.tests.test_same_name', f'{owner}.tests.new_area.test_unknown'])
            self.assertCountEqual([group['seconds'] for group in groups], [100 if owner == 'first' else 10, 7])

    def test_installed_rf_science_and_executor_select_their_actual_consumers(self) -> None:
        science = {f"{RF}/tests/analysis/{name}.py" for name in (
            "test_quadrupole_l0", "test_mass_filter_l1",
            "test_mass_filter_response_comparison", "test_workflow_architecture_contract")}
        executor = {f"{RF}/tests/analysis/{name}.py" for name in (
            "test_compare_particle_state_evidence", "test_frozen_matlab_closure",
            "test_frozen_particle_policy_package", "test_interface_postprocess_child",
            "test_interface_public_owner", "test_same_solver_numerical_convergence")}
        domain = {f"{RF}/tests/domain/{name}.py" for name in (
            "test_published_design_freshness", "test_simion_runner_contract")}
        cases = [("src/msplatform/components/rf_multipole/" + name + ".py", science)
                 for name in ("mass_filter_theory", "finite_length_transport")]
        cases += [("src/msplatform/workflows/rf_mass_filter/" + name + ".py", science)
                  for name in ("__init__", "reference", "finite_length")]
        cases += [("src/msplatform/execution/" + name, executor) for name in (
            "inputs.py", "resources/__init__.py", "resources/frozen_python_package.ps1")]
        transport = {f"{RF}/tests/analysis/{name}.py" for name in (
            "test_compare_particle_state_evidence", "test_phase4_design_consumer")}
        cases.append(("src/msplatform/workflows/rf_transport_comparison.py", transport))
        with tempfile.TemporaryDirectory(prefix="installed_rf_consumer_plans_") as directory:
            for index, (path, expected) in enumerate(cases):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    parameters = stages["rf_multipole_quadrupole_static"]["command"]["parameters"]
                    self.assertEqual(parameters["Level"], "Core")
                    self.assertCountEqual(parameters["ChangedTestModules"],
                        [name[:-3].replace("/", ".") for name in expected])
                    if expected == transport:
                        common = stages["common_contracts"]["command"]["arguments"]
                        self.assertIn("common/contracts/test_installed_scientific_core.py", common)
                        self.assertIn("common/contracts/test_scientific_core_boundaries.py", common)
                    if expected == executor:
                        arguments = stages["rf_multipole_domain_tests"]["command"]["arguments"]
                        self.assertEqual(arguments[:2], ["-m", "common.gate_unittest"])
                        self.assertCountEqual(arguments[2:], domain)
                        common = stages["common_contracts"]["command"]["arguments"]
                        self.assertIn("common/contracts/test_installed_scientific_core.py", common)
                        self.assertIn("common/contracts/test_scientific_core_boundaries.py", common)
                        if path.endswith("/inputs.py"):
                            self.assertIn("common/contracts/test_frozen_inputs.py", common)

    def test_rf_event_and_axis_exporter_select_actual_consumers(self) -> None:
        rf_paths = (
            "src/msplatform/components/rf_multipole/event_table.py",
            "src/msplatform/backends/simion/rf_ion11_source.py",
            "src/msplatform/workflows/rf_event_table_validation.py",
        )
        axis = "src/msplatform/backends/simion/resources/export_axis_basis.lua"
        with tempfile.TemporaryDirectory(prefix="rf_event_consumer_plans_") as directory:
            for index, path in enumerate((*rf_paths, axis)):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    common = stages["common_contracts"]["command"]["arguments"]
                    self.assertIn("common/contracts/test_installed_scientific_core.py", common)
                    if path in rf_paths:
                        self.assertIn("common/contracts/test_particle_state.py", common)
                        rf = stages["rf_multipole_quadrupole_static"]["command"]["parameters"]
                        for name in ("test_rf_event_original_witness", "test_frozen_particle_policy_package",
                                     "test_cross_solver_gate_contract"):
                            self.assertIn(f"projects.rf_multipole_ion_optics.tests.analysis.{name}",
                                          rf["ChangedTestModules"])
                        if path == rf_paths[0]:
                            ip = stages["dual_pressure_rectilinear_ion_processor_static"]
                            self.assertEqual(ip["command"]["script"],
                                "projects/dual_pressure_rectilinear_ion_processor/verify_project.ps1")
                            ip_gate = (REPO_ROOT / ip["command"]["script"]).read_text(encoding="utf-8")
                            self.assertIn("common.gate_unittest discover", ip_gate)
                            self.assertTrue((REPO_ROOT / "projects/dual_pressure_rectilinear_ion_processor/tests/test_functional.py").is_file())
                            modules = set()
                            for name, stage in stages.items():
                                if name.startswith("instrument_assembly_integration"):
                                    modules.update(stage["command"]["parameters"].get("SelectedTestModules", []))
                            self.assertIn("integrations.tests.test_multipole_ip_prepare", modules)
                    else:
                        tof = stages["single_reflection_oa_tof_mass_analyzer_static"]["command"]["parameters"]
                        for name in ("test_reflectron_voltage_compensation", "test_compensation_powershell_adapter"):
                            self.assertIn(f"projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.{name}",
                                          tof["SelectedTestModules"])

    def test_canonical_file_identity_selects_frozen_project_consumers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="file_identity_project_plan_") as directory:
            request = Path(directory) / "plan.json"
            write_planned_request(REPO_ROOT, request, ["src/msplatform/io/file_identity.py"])
            stages = {row["name"]: row for row in json.loads(
                request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
            rf = stages["rf_multipole_quadrupole_static"]["command"]["parameters"]
            self.assertIn("projects.rf_multipole_ion_optics.tests.analysis.test_frozen_particle_policy_package",
                          rf["ChangedTestModules"])
            tof = stages["single_reflection_oa_tof_mass_analyzer_static"]["command"]["parameters"]
            self.assertIn("projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_publish_ideal_acceptance_aperture_comparison",
                          tof["SelectedTestModules"])

    def test_installed_rf_convergence_selects_source_and_comparison_consumers(self) -> None:
        expected = {f"{RF}.tests.analysis.{name}".replace("/", ".") for name in (
            "test_cross_solver_gate_contract", "test_frozen_particle_policy_package",
            "test_generate_interface_particle_table", "test_same_solver_numerical_convergence",
            "test_simion_transport_runner_source", "test_workflow_architecture_contract")}
        paths = (
            "src/msplatform/workflows/rf_convergence_comparison.py",
            "src/msplatform/components/rf_multipole/paired_particle_source_bundle.py",
            "src/msplatform/components/rf_multipole/particle_source_binding.py",
        )
        with tempfile.TemporaryDirectory(prefix="rf_convergence_consumer_plans_") as directory:
            for index, path in enumerate(paths):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    parameters = stages["rf_multipole_quadrupole_static"]["command"]["parameters"]
                    self.assertTrue(expected.issubset(parameters["ChangedTestModules"]))
                    common = stages["common_contracts"]["command"]["arguments"]
                    self.assertIn("common/contracts/test_installed_scientific_core.py", common)
                    self.assertIn("common/contracts/test_scientific_core_boundaries.py", common)

    def test_mr_prepared_field_selects_its_actual_project_consumer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mr_prepared_field_plan_") as directory:
            request = Path(directory) / "plan.json"
            write_planned_request(REPO_ROOT, request, ["src/msplatform/backends/simion/mr_prepared_field.py"])
            stages = {row["name"]: row for row in json.loads(
                request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
            parameters = stages["parallel_mirror_dual_stripe_mr_tof_static"]["command"]["parameters"]
            self.assertIn("projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prepared_joint_trial",
                          parameters["ChangedTestModules"])
            self.assertIn("projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_joint_flight_preparation",
                          parameters["ChangedTestModules"])
            self.assertTrue(any(name.startswith("instrument_assembly_integration") for name in stages))

    def test_measured_source_dependencies_select_their_real_consumers(self) -> None:
        paths = (
            "src/msplatform/workflows/prepared_joint/source.py",
            "src/msplatform/workflows/prepared_joint/ip_mr_connection.py",
            "src/msplatform/backends/simion/resources/mrtof_measured_source_runtime.lua",
            "src/msplatform/io/strict_json.py",
            "src/msplatform/execution/resources/frozen_python_package.ps1",
        )
        with tempfile.TemporaryDirectory(prefix="measured_source_consumer_plans_") as directory:
            for index, path in enumerate(paths):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    mr = stages["parallel_mirror_dual_stripe_mr_tof_static"]["command"]["parameters"]
                    self.assertIn(
                        "projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prepared_joint_trial",
                        mr["ChangedTestModules"])
                    integration = set()
                    for name, stage in stages.items():
                        if name.startswith("instrument_assembly_integration"):
                            integration.update(stage["command"]["parameters"].get("SelectedTestModules", []))
                    self.assertIn("integrations.tests.test_prepared_joint_execute", integration)
                    if path.endswith("strict_json.py"):
                        self.assertIn("rf_multipole_domain_tests", stages)
                    if not path.endswith("frozen_python_package.ps1"):
                        self.assertIn(
                            "projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_measured_component_source",
                            mr["ChangedTestModules"])
                        self.assertIn("integrations.tests.test_accelerator_interface", integration)

    def test_installed_ip_reader_selects_its_actual_project_and_installation(self) -> None:
        paths = ("src/msplatform/results/ip_continuation.py",
                 "src/msplatform/backends/simion/ip_exit.py")
        with tempfile.TemporaryDirectory(prefix="ip_reader_consumer_plans_") as directory:
            for index, path in enumerate(paths):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    self.assertIn("dual_pressure_rectilinear_ion_processor_static", stages)
                    common = stages["common_contracts"]["command"]["arguments"]
                    self.assertIn("common/contracts/test_installed_scientific_core.py", common)
                    self.assertIn("common/contracts/test_scientific_core_boundaries.py", common)

    def test_candidate_split_keeps_all_prior_mapped_tests_in_real_plans(self) -> None:
        paths = (
            'src/msplatform/execution/resources/frozen_python_package.ps1',
            'src/msplatform/workflows/single_reflection_mass_spectrum.py',
            'common/contracts/test_support/run_artifact_workflow.py',
            'src/msplatform/backends/comsol/matlab/add_comsol_size_feature.m',
        )
        prefix = 'projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.'
        expected = {prefix + name for name in ('test_candidate_workflow',
                    'test_candidate_causal_workflow', 'test_candidate_postprocess_workflow')}
        with tempfile.TemporaryDirectory(prefix='candidate_split_plans_') as directory:
            # Each request is still the real public PlanOnly entry with a distinct
            # output; script invocations have independent PowerShell script scope.
            requests = [Path(directory) / f'plan-{index}.json' for index in range(len(paths))]
            calls = []
            for index, (path, request) in enumerate(zip(paths, requests, strict=True)):
                command = ("& " + powershell_literal(REPO_ROOT / 'common/verify.ps1') +
                           " -PythonExe " + powershell_literal(sys.executable) +
                           " -PlanOnly -InternalRequestPath " + powershell_literal(request) +
                           " -ChangedPath @(" + powershell_literal(path) + ")")
                calls.append("try { " +
                             "$global:LASTEXITCODE=0; " +
                             "if ($null -eq $initialPython) { Remove-Item Env:SIMULATION_PYTHON_EXE -ErrorAction SilentlyContinue } " +
                             "else { $env:SIMULATION_PYTHON_EXE=$initialPython }; " + command + " | Out-Null; " +
                             "if ($global:LASTEXITCODE -ne 0) { throw ('planner returned nonzero exit code: ' + $global:LASTEXITCODE) }; " +
                             "if (-not (Test-Path -LiteralPath " + powershell_literal(request) + ")) " +
                             "{ throw 'planner did not write the request' }; " +
                             "$cases += @{index=" + str(index) + "; error=$null} } " +
                             "catch { $cases += @{index=" + str(index) + "; error=$_.ToString()} }")
            script = "$ErrorActionPreference='Stop'; $initialPython=[Environment]::GetEnvironmentVariable('SIMULATION_PYTHON_EXE','Process'); $cases=@(); " + '; '.join(calls) + "; ConvertTo-Json -InputObject @($cases) -Depth 5 -Compress"
            result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding='utf-8', timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            outcomes = json.loads(result.stdout)
            self.assertEqual([case['index'] for case in outcomes], list(range(len(paths))))
            for index, path in enumerate(paths):
                with self.subTest(path=path):
                    self.assertIsNone(outcomes[index]['error'], outcomes[index]['error'])
                    request = requests[index]
                    stages = [row for row in json.loads(request.read_text(encoding='utf-8-sig'))['stages']
                              if row['selected'] and (row['name']=='single_reflection_oa_tof_mass_analyzer_static'
                              or row['name'].startswith('single_reflection_oa_tof_mass_analyzer_static__tests_'))]
                    self.assertTrue(stages)
                    modules = [module for row in stages for module in row['command'].get('parameters', {}).get('SelectedTestModules', [])]
                    self.assertTrue(expected <= set(modules), (path, modules))
                    self.assertEqual(len(modules), len(set(modules)))

    def test_migrated_ip_tof_paths_select_real_consumers(self) -> None:
        project = "projects.single_reflection_oa_tof_mass_analyzer.tests.analysis."
        consumer_paths = (
            "src/msplatform/workflows/single_reflection_mass_spectrum.py",
            "src/msplatform/results/single_reflection_particle_table.py",
            "src/msplatform/execution/resources/frozen_python_package.ps1",
        )
        with tempfile.TemporaryDirectory(prefix="migrated_ip_tof_plans_") as directory:
            for index, path in enumerate((*consumer_paths, "src/msplatform/analysis/particle_styles.py")):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    if path in consumer_paths:
                        params = stages["single_reflection_oa_tof_mass_analyzer_static"]["command"]["parameters"]
                        selected = set(params["SelectedTestModules"])
                        expected = {project + "test_mass_spectrum_input_admission", project + "test_candidate_workflow",
                                    project + "test_candidate_causal_workflow", project + "test_candidate_postprocess_workflow"}
                        if path != consumer_paths[2]:
                            expected.add(project + "test_peak_metrics")
                        if path == consumer_paths[1]:
                            expected.update({project + "test_analyze_comsol_detector_events",
                                             project + "test_solver_diagnostics"})
                        self.assertTrue(expected <= selected, (path, selected))
                    else:
                        self.assertIn("dual_pressure_rectilinear_ion_processor_static", stages)
                        args = stages["rf_multipole_domain_tests"]["command"]["arguments"]
                        self.assertIn("projects/rf_multipole_ion_optics/tests/domain/test_exit_state_plot.py", args)

    def test_installed_reflectron_fit_selects_its_workflow_and_installation_consumers(self) -> None:
        project = "projects/single_reflection_oa_tof_mass_analyzer"
        expected = [f"{project}.tests.analysis.{name}".replace("/", ".") for name in (
            "test_reflectron_voltage_fit", "test_reflectron_voltage_compensation",
            "test_compensation_powershell_adapter")]
        paths = (
            "src/msplatform/backends/simion/optimize_reflectron_ring_voltages.py",
            "src/msplatform/backends/simion/resources/reflectron_voltage_fit_authoring.json",
        )
        with tempfile.TemporaryDirectory(prefix="installed_reflectron_consumer_plans_") as directory:
            for index, path in enumerate(paths):
                with self.subTest(path=path):
                    request = Path(directory) / f"plan-{index}.json"
                    write_planned_request(REPO_ROOT, request, [path])
                    stages = {row["name"]: row for row in json.loads(
                        request.read_text(encoding="utf-8-sig"))["stages"] if row["selected"]}
                    parameters = stages["single_reflection_oa_tof_mass_analyzer_static"]["command"]["parameters"]
                    self.assertCountEqual(parameters["SelectedTestModules"], expected)
                    common = stages["common_contracts"]["command"]["arguments"]
                    self.assertIn("common/contracts/test_installed_scientific_core.py", common)
                    self.assertIn("common/contracts/test_scientific_core_boundaries.py", common)

    def test_changed_mixed_deleted_and_shared_inputs_preserve_original_core_contract(self) -> None:
        mr_test = f"{MR}/tests/analysis/test_mirror_fixed_grid_voltage_correction.py"
        rf_test = f"{RF}/tests/analysis/test_mass_filter_l1.py"
        cases = [("mr_mixed", [f"{MR}/analysis/unknown_partition_probe.py", mr_test]),
                 ("rf_mixed", [f"{RF}/runtime/unknown_partition_probe.ps1", rf_test]),
                 ("rf_gate", [f"{RF}/verify_project.ps1"]),
                 ("rf_deleted", [f"{RF}/tests/analysis/test_deleted_partition_probe.py"]),
                 ("rf_shared", [f"{RF}/tests/test_support/partition_probe.py"])]
        with tempfile.TemporaryDirectory(prefix="partition_core_plans_") as directory:
            root = Path(directory)
            probes = root / "probes.json"
            probes.write_text(json.dumps(cases), encoding="utf-8")
            script = r"""
$results=@{}
foreach($probe in (Get-Content __PROBES__ -Raw|ConvertFrom-Json)){
 $plan=Join-Path __OUTPUT__ ($probe[0]+'.json')
 & __GATE__ -PlanOnly -ChangedPath @($probe[1]) -PlanPath $plan|Out-Null
 if($LASTEXITCODE-ne0){throw 'Changed planning failed'}
 $results[$probe[0]]=(Get-Content $plan -Raw|ConvertFrom-Json).stages
}
$results|ConvertTo-Json -Depth 20 -Compress
""".replace('__PROBES__', powershell_literal(probes)).replace('__OUTPUT__', powershell_literal(root))
            script = script.replace('__GATE__', powershell_literal(REPO_ROOT / 'common/verify.ps1'))
            result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            expected_rf = {path.relative_to(REPO_ROOT).with_suffix('').as_posix().replace('/', '.')
                           for path in (REPO_ROOT / RF / 'tests/analysis').rglob('test_*.py')}
            for name, stages in json.loads(result.stdout).items():
                owner = 'parallel_mirror_dual_stripe_mr_tof_static' if name == 'mr_mixed' else 'rf_multipole_quadrupole_static'
                selected = [stage for stage in stages if stage['name'].startswith(owner) and stage['selected']]
                self.assertEqual(len(selected), 1, name)
                parameters = selected[0]['command']['parameters']
                self.assertEqual(parameters['Level'], 'Core', name)
                self.assertNotIn('SelectedTestModules', parameters)
                self.assertNotIn('PreflightOnly', parameters)
                expected = ({mr_test[:-3].replace('/', '.')} if name == 'mr_mixed' else
                            {rf_test[:-3].replace('/', '.')} if name == 'rf_mixed' else expected_rf)
                if name == 'rf_gate':
                    expected = {f"{RF}/tests/analysis/test_cross_solver_gate_contract".replace('/', '.')}
                self.assertCountEqual(parameters['ChangedTestModules'], expected, name)

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

    def test_installed_mesh_resources_select_only_actual_owner_modules(self) -> None:
        script = r"""
. __SUPPORT__
$routes=@(Read-GateCatalog -RepoRoot $PWD.Path)
$roots=@($routes|Where-Object{$null-ne$_.PSObject.Properties['test_selection']}|ForEach-Object{@($_.test_selection.roots)})
$base='src/msplatform/backends/comsol/matlab/'
$names=@('configure_comsol_mesh.m','add_comsol_size_feature.m','read_comsol_mesh_size_controls.m')
$result=@(foreach($name in $names){
 $path=$base+$name;$owners=@{}
 foreach($stage in @('common_contracts','rf_multipole_quadrupole_static','single_reflection_oa_tof_mass_analyzer_static','instrument_assembly_integration','rf_multipole_domain_tests','rf_multipole_hexapole_static','rf_multipole_octupole_static','transverse_helical_filament_wehnelt_electron_gun_static','apertured_tube_electron_impact_ion_source_static')){
  $route=$routes|Where-Object stage -eq $stage
  $selected=[bool](Get-ChangedRouteReason -Route $route -Paths @($path));$modules=@()
  if($selected){$paths=@(Get-GateOwnerChangedPaths -Route $route -ChangedPaths @($path));$tests=Get-GateChangedTests -Route $route -ChangedPaths $paths -KnownTestRoots $roots -RepoRoot $PWD.Path;if($null-ne$tests){$modules=@($tests.Modules)}}
  $owners[$stage]=@{selected=$selected;modules=$modules}
 }
 @{name=$name;owners=$owners}
})
ConvertTo-Json -InputObject $result -Depth 12 -Compress
""".replace("__SUPPORT__", powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1"))
        outcome = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        for case in json.loads(outcome.stdout):
            with self.subTest(name=case['name']):
                owners = case['owners']; shared = case['name'] != 'configure_comsol_mesh.m'
                self.assertEqual(owners['common_contracts']['modules'], ['common/contracts/test_installed_scientific_core.py'])
                self.assertCountEqual(owners['rf_multipole_quadrupole_static']['modules'], [
                    f"{RF}/tests/analysis/test_frozen_matlab_closure.py", f"{RF}/tests/analysis/test_comsol_mesh_report.py"])
                for stage in ('rf_multipole_domain_tests','rf_multipole_hexapole_static','rf_multipole_octupole_static',
                              'transverse_helical_filament_wehnelt_electron_gun_static','apertured_tube_electron_impact_ion_source_static'):
                    self.assertFalse(owners[stage]['selected'], stage)
                self.assertEqual(owners['single_reflection_oa_tof_mass_analyzer_static']['selected'], shared)
                self.assertEqual(owners['instrument_assembly_integration']['selected'], shared)
                if shared:
                    self.assertCountEqual(owners['single_reflection_oa_tof_mass_analyzer_static']['modules'], [
                        'projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_workflow.py',
                        'projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_causal_workflow.py',
                        'projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_postprocess_workflow.py',
                        'projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_paired_accelerator_field_adapters.py'])
                    self.assertEqual(owners['instrument_assembly_integration']['modules'],
                                     ['integrations/tests/test_paired_accelerator_static_field_execute.py'])

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
                if name in ("configure", "size", "typed"):
                    # Retired source authorities intentionally select the full owner.
                    # Deleted files must never regain a stale leaf-only mapping.
                    retired = {"configure": "configure_comsol_mesh.m", "size": "add_comsol_size_feature.m",
                               "typed": "read_comsol_mesh_size_controls.m"}[name]
                    self.assertFalse((REPO_ROOT / "common/comsol" / retired).exists())
                    self.assertIsNone(cases[name]["modules"])
                else:
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

    def test_rf_gate_consumer_mapping_keeps_real_dispatch_failure_propagation(self) -> None:
        self._assert_mapped_modules_keep_real_dispatch_failure_propagation(
            ["test_cross_solver_gate_contract"], f"{RF}/verify_project.ps1")

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
            # Declared leaf mappings apply only to an existing authority.
            # This opaque fixture file is selected, never executed.
            authority = root / changed_path
            authority.parent.mkdir(parents=True, exist_ok=True)
            authority.write_text("# Test-only mapped authority, never executed.\n", encoding="utf-8")
            original_authority = authority.read_bytes()
            selection_script = r"""
. __SUPPORT__
$route=((Get-Content __CATALOG__ -Raw|ConvertFrom-Json).routes|Where-Object stage -eq 'rf_multipole_quadrupole_static')
$selection=Get-GateChangedTests -Route $route -RepoRoot $PWD.Path -KnownTestRoots @($route.test_selection.roots) `
 -ChangedPaths @(__CHANGED_PATH__)
"""
            script = selection_script + r"""
$modules=@($selection.Modules|ForEach-Object{$_.Substring(0,$_.Length-3).Replace('/','.')})
$command=ConvertTo-GateExecutionCommand -Command ([pscustomobject]@{runner='python';arguments=@('-m','unittest')+$modules})
Invoke-GateCatalogCommand -Command $command -RepoRoot $PWD.Path -PythonExe __PYTHON__
"""
            for token, value in (
                ("__SUPPORT__", REPO_ROOT / "common/gate_catalog_support.ps1"),
                ("__CATALOG__", REPO_ROOT / "common/gate_catalog.json"),
                ("__PYTHON__", sys.executable), ("__CHANGED_PATH__", changed_path),
            ):
                script = script.replace(token, powershell_literal(value))
                selection_script = selection_script.replace(token, powershell_literal(value))
            authority.unlink()
            try:
                deleted = subprocess.run(["pwsh", "-NoProfile", "-Command", selection_script +
                    "if($null-ne$selection){throw 'Deleted authority reused a stale leaf mapping'}"],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(deleted.returncode, 0, deleted.stdout + deleted.stderr)
            finally:
                authority.write_bytes(original_authority)
            self.assertEqual(authority.read_bytes(), original_authority)
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
                    self.assertCountEqual(
                        re.findall(r"TEST_DURATION_SECONDS=\S+ TEST=(\S+)", output),
                        [f"{RF.replace('/', '.')}.tests.analysis.{name}.Probe.test_boundary" for name in names],
                    )
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

    def test_integration_ip_provider_tests_keep_only_real_fixture_consumers(self) -> None:
        integration = ["integrations/tests/test_single_reflection_owner_recovery.py"]
        ip = "projects/dual_pressure_rectilinear_ion_processor/"
        consumers = integration + [
            RF + "/tests/analysis/test_comsol_owner_finalization.py",
            RF + "/tests/analysis/test_owner_finalization_recovery.py",
            RF + "/tests/analysis/test_simion_powershell_owner.py",
            "projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_workflow.py",
            "projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_compensation_powershell_adapter.py",
            ip + "tests/test_owner_finalization_recovery.py",
        ]
        # Missing ordinary test paths are classified without deleting real files.
        cases = [consumers, consumers + [ip + "tests/test_removed.py"],
                 consumers + [ip + "tests/nested/test_removed.py"]]
        shared = ("analysis/retained_provider.py", "analysis/unknown_provider.py",
                  "tests/test_support/unknown_helper.py", "tests/test_support/test_helper.py",
                  "tests/nested/support/test_helper.py", "tests/__init__.py",
                  "tests/test_component_exit.py",
                  "tests/test_functional.py")
        cases.extend(consumers + [ip + path] for path in shared)
        selected = self.selections(REPO_ROOT, [
            dict(stage="instrument_assembly_integration", paths=paths) for paths in cases
        ], owner_filter=True)
        for index, selection in enumerate(selected):
            with self.subTest(paths=cases[index]):
                if index < 3:
                    self.assertIsNotNone(selection)
                    self.assertCountEqual(selection["Modules"], integration)
                    self.assertTrue(selection["OnlyTestModules"])
                    self.assertFalse(selection["CompleteOwner"])
                    self.assertFalse(selection["Expanded"])
                else:
                    self.assertIsNone(selection, "Provider or shared fixture must retain the full owner")

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
            # This fixture exercises Python module transport through the real
            # owner. Plain-Lua physics callbacks have their own project tests.
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
                changed_paths = [relative]
                if prefix == MR:
                    second = f"{prefix}/tests/analysis/test_mixed_gate_second.py"
                    (root / second).write_text(
                        "import unittest\nclass SecondProbe(unittest.TestCase):\n"
                        "    def test_second(self): self.assertTrue(True)\n", encoding="utf-8")
                    unknown_source = f"{prefix}/analysis/unknown_gate_fixture.py"
                    (root / unknown_source).write_text("# Unmapped production authority.\n", encoding="utf-8")
                    # An explicitly changed Core module must still run once.
                    changed_paths += [second, f"{prefix}/tests/analysis/test_prism_analytic.py",
                                      unknown_source, f"{prefix}/docs/PROJECT.md"]
                for fails in ((True, False) if prefix == MR else (True,)):
                    with self.subTest(actual_owner=prefix, mixed=prefix == MR, fails=fails):
                        (root / relative).write_text(
                            "import unittest\nclass Probe(unittest.TestCase):\n"
                            f"    def test_failure(self): self.assertFalse({fails!r}, 'REAL_OWNER_PROBE')\n",
                            encoding="utf-8")
                        request = Path(logs) / f"real_{index}_{fails}.json"
                        write_planned_request(root, request, changed_paths)
                        log = Path(logs) / f"real_{index}_{fails}.log"
                        # pwsh initializes ProgramFiles at startup; isolate the
                        # optional installed-Lua discovery inside that process.
                        command = ("$env:ProgramFiles=" + powershell_literal(Path(logs) / "no_installed_lua") +
                                   "; & " + powershell_literal(root / "common/verify.ps1") +
                                   " -InternalStage " + powershell_literal(stage) +
                                   " -InternalRequestPath " + powershell_literal(request) +
                                   " -InternalLogPath " + powershell_literal(log))
                        result = subprocess.run([
                            "pwsh", "-NoProfile", "-Command", command,
                        ], cwd=root, env=environment, capture_output=True, text=True,
                            encoding="utf-8", timeout=300)
                        output = result.stdout + result.stderr + log.read_text(encoding="utf-8")
                        self.assertEqual(result.returncode != 0, fails, output)
                        if fails:
                            self.assertIn("REAL_OWNER_PROBE", output)
                        if prefix == MR:
                            module_line = next(line for line in output.splitlines() if "PROJECT_TEST_MODULES=" in line)
                            modules = module_line.split("PROJECT_TEST_MODULES=", 1)[1].strip().split(",")
                            self.assertEqual(len(modules), 6, module_line)
                            self.assertEqual(len(modules), len(set(modules)), module_line)
                            for name in ("test_changed_gate_probe", "test_mixed_gate_second",
                                         "test_drift_phase_contract", "test_prism_analytic",
                                         "test_native_corridor_plan", "test_native_corridor_freeze"):
                                self.assertEqual(sum(module.endswith("." + name) for module in modules), 1, module_line)
                            self.assertIn("Ran 6 tests", output)

    def test_scalar_adapter_and_freezers_augment_core_with_actual_consumers(self) -> None:
        stage = "parallel_mirror_dual_stripe_mr_tof_static"
        adapter = "src/msplatform/backends/simion/resources/scalar_field_adapter.lua"
        lookup = "src/msplatform/backends/simion/resources.py"
        prepared = MR + "/analysis/prepared_joint_trial.py"
        provider = MR + "/simion/run_native_static_field_provider.ps1"
        consumers = [MR + "/tests/analysis/" + name + ".py" for name in (
            "test_static_field_binding", "test_native_memory_consumer_crop",
            "test_prepared_joint_trial", "test_native_static_field_provider_runner")]
        cases = [
            dict(stage=stage, paths=[adapter], modules=consumers),
            dict(stage=stage, paths=[lookup], modules=consumers),
            dict(stage=stage, paths=[prepared], modules=[consumers[2]]),
            dict(stage=stage, paths=[provider], modules=[consumers[3]]),
            dict(stage=stage, paths=[adapter, lookup, prepared, provider, consumers[1]],
                 modules=consumers),
        ]
        for case, selected in zip(cases, self.selections(REPO_ROOT, cases), strict=True):
            with self.subTest(paths=case["paths"]):
                self.assertIsNotNone(selected)
                self.assertCountEqual(selected["Modules"], case["modules"])
                self.assertEqual(len(selected["Modules"]), len(set(selected["Modules"])))
                self.assertFalse(selected["CompleteOwner"])
                self.assertFalse(selected["OnlyTestModules"])



    def test_rf_ip_consumer_and_birth_admission_select_actual_consumers(self) -> None:
        source = 'src/msplatform/workflows/multipole_ip/continuous.py'
        backend = 'src/msplatform/backends/simion/tracking_execution.py'
        consumer = 'integrations/tests/test_multipole_ip_continuous.py'
        selected = self.selections(REPO_ROOT, [
            dict(stage='common_contracts', paths=[source]),
            dict(stage='common_contracts', paths=[backend]),
            dict(stage='instrument_assembly_integration', paths=[consumer])])
        for row in selected[:2]:
            self.assertTrue({'common/contracts/test_simion_birth_admission.py',
                             'common/contracts/test_rf_ip_composed.py',
                             'common/contracts/test_installed_scientific_core.py'} <= set(row['Modules']))
        self.assertIn('common/contracts/test_simion_tracking_execution.py', selected[1]['Modules'])
        self.assertEqual(selected[2]['Modules'], [consumer])

    def test_scalar_support_changes_select_actual_consumers(self) -> None:
        paths = ['src/msplatform/components/shape_query.py',
                 'src/msplatform/backends/comsol/assembly_scalar_fill.py',
                 'src/msplatform/backends/comsol/assembly_field_export.py',
                 'src/msplatform/backends/comsol/matlab/sample_scalar_grid_blocks.m']
        selected = self.selections(REPO_ROOT, [dict(stage='common_contracts', paths=[path]) for path in paths])
        fill = {'common/contracts/test_assembly_scalar_fill.py', 'common/contracts/test_scalar_pa_fill.py',
                'common/contracts/test_assembly_scalar_owner_fill.py'}
        self.assertTrue((fill | {'common/contracts/test_shape_query.py', 'common/contracts/test_oa_geometry_compiler.py',
                                 'common/contracts/test_installed_scientific_core.py'}) <= set(selected[0]['Modules']))
        self.assertTrue((fill | {'common/contracts/test_installed_scientific_core.py'}) <= set(selected[1]['Modules']))
        for row in selected[2:]:
            self.assertTrue({'common/contracts/test_comsol_world_scalar_contract.py',
                             'common/contracts/test_comsol_world_scalar_managed.py',
                             'common/contracts/test_assembly_scalar_owner_fill.py',
                             'common/contracts/test_installed_scientific_core.py'} <= set(row['Modules']))
        self.assertTrue({'common/contracts/test_python_dependency_contract.py',
                         'common/contracts/test_scientific_core_boundaries.py'} <= set(selected[2]['Modules']))
        script = (
            '. ' + powershell_literal(REPO_ROOT / 'common/gate_catalog_support.ps1') + '; '
            "$r=@(Read-GateCatalog -RepoRoot $PWD.Path|Where-Object stage -eq 'common_contracts')[0]; "
            "if(-not(Get-ChangedRouteReason -Route $r -Paths @('" + paths[3] + "'))){throw 'missing helper route'}"
        )
        result = subprocess.run(['pwsh','-NoProfile','-Command',script], cwd=REPO_ROOT,
                                capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        oa = self.selections(REPO_ROOT, [dict(stage='instrument_assembly_integration',
            paths=['src/msplatform/backends/simion/oa_compiler.py'])])[0]
        self.assertIn('integrations/tests/test_rf_oa_compiler.py', oa['Modules'])

    def test_shared_geometry_changes_select_cad_and_comsol_consumers(self) -> None:
        paths = ["src/msplatform/components/geometry_members.py",
                 "src/msplatform/backends/comsol/assembly_geometry.py",
                 "src/msplatform/backends/comsol/geometry_execution.py",
                 "src/msplatform/backends/comsol/ip_prism.py",
                 "src/msplatform/components/dual_pressure_rectilinear_ion_processor/convex_geometry.py",
                 "src/msplatform/backends/comsol/matlab/assembly_geometry_stage.m"]
        selected = self.selections(REPO_ROOT, [dict(stage="common_contracts", paths=[path]) for path in paths])
        for path, row in zip(paths, selected, strict=True):
            with self.subTest(path=path):
                self.assertTrue({"common/contracts/test_comsol_assembly_geometry.py",
                                 "common/contracts/test_comsol_assembly_geometry_execution.py",
                                 "common/contracts/test_ip_comsol_projection.py",
                                 "common/contracts/test_installed_scientific_core.py"} <= set(row["Modules"]))
        self.assertTrue({"common/contracts/test_geometry_members.py", "common/contracts/test_step_export.py",
                         "common/contracts/test_ip_step_projection.py", "common/contracts/test_mr_step_projection.py",
                         "common/contracts/test_step_probe_culling.py",
                         "common/contracts/test_step_probe_culling_kernel.py"} <= set(selected[0]["Modules"]))

    def test_joint_geometry_changes_select_actual_consumers(self) -> None:
        common = "common_contracts"
        integration = "instrument_assembly_integration"
        mr = "parallel_mirror_dual_stripe_mr_tof_static"
        mr_test = MR + "/tests/analysis/test_mr_compiler.py"
        cases = [
            dict(stage=common, paths=["src/msplatform/backends/simion/operations.py"]),
            dict(stage=common, paths=["src/msplatform/backends/simion/resources/iob_core.lua"]),
            dict(stage=common, paths=["integrations/tests/test_ip_compiler.py"]),
            dict(stage=common, paths=["common/contracts/test_dual_cone_iob.py"]),
            dict(stage=integration, paths=["src/msplatform/backends/simion/ip_compiler.py"]),
            dict(stage=integration, paths=["src/msplatform/components/dual_pressure_rectilinear_ion_processor/provider.py"]),
            dict(stage=mr, paths=["src/msplatform/backends/simion/mr_compiler.py"]),
            dict(stage=mr, paths=[MR + "/tests/analysis/fixtures/mr_legacy_analyzer.gem.txt"]),
            dict(stage=common, paths=["src/msplatform/gas/field.py"]),
        ]
        selected = self.selections(REPO_ROOT, cases)
        for row in selected[:2]:
            for module in ("test_joint_geometry_plan.py", "test_joint_geometry_iob.py"):
                self.assertIn("common/contracts/" + module, row["Modules"])
        self.assertIn("common/contracts/test_joint_geometry_plan.py", selected[2]["Modules"])
        self.assertIn("common/contracts/test_dual_cone_iob.py", selected[3]["Modules"])
        self.assertIn("common/contracts/test_joint_geometry_iob.py", selected[3]["Modules"])
        for row in selected[4:6]:
            self.assertIn("integrations/tests/test_ip_compiler.py", row["Modules"])
            self.assertIn("integrations/tests/test_selected_ip_provider.py", row["Modules"])
            self.assertIn("integrations/tests/test_multipole_ip_prepare.py", row["Modules"])
        for row in selected[6:8]:
            self.assertIn(mr_test, row["Modules"])
        self.assertIn("common/contracts/test_gas.py", selected[8]["Modules"])
        self.assertNotIn("common/contracts/test_joint_geometry_plan.py", selected[8]["Modules"])
        extra_cases = [
            dict(stage=common, paths=["src/msplatform/backends/simion/model.py"]),
            dict(stage=common, paths=["src/msplatform/backends/simion/rf_field_execution.py"]),
            dict(stage=common, paths=["src/msplatform/backends/simion/resources/model_drive.lua"]),
            dict(stage=common, paths=["integrations/tests/test_ip_compiler.py"]),
            dict(stage=common, paths=["src/msplatform/components/orthogonal_accelerator/provider.py"]),
            dict(stage=common, paths=["src/msplatform/components/orthogonal_accelerator/two_zone_geometry.py"]),
            dict(stage=mr, paths=["src/msplatform/components/orthogonal_accelerator/provider.py"]),
            dict(stage=mr, paths=["src/msplatform/components/orthogonal_accelerator/two_zone_geometry.py"]),
            dict(stage=mr, paths=[MR + "/tests/analysis/test_mr_provider_trial_transport.py"]),
        ]
        extra = self.selections(REPO_ROOT, extra_cases)
        for row in extra[:4]:
            self.assertIn("common/contracts/test_joint_ip_model.py", row["Modules"])
        for row in extra[4:6]:
            self.assertIn("common/contracts/test_geometry_members.py", row["Modules"])
        for row in extra[6:9]:
            self.assertIn(MR + "/tests/analysis/test_mr_provider_trial_transport.py", row["Modules"])
        self.assertIn(mr_test, extra[8]["Modules"])
        script = (
            ". " + powershell_literal(REPO_ROOT / "common/gate_catalog_support.ps1") + "; "
            "$r=@(Read-GateCatalog -RepoRoot $PWD.Path|Where-Object stage -eq "
            "'dual_pressure_rectilinear_ion_processor_static')[0]; "
            "foreach($p in @('src/msplatform/backends/simion/ip_assembly_geometry.py',"
            "'src/msplatform/components/dual_pressure_rectilinear_ion_processor/assembly_interface.py')) "
            "{if(-not (Get-ChangedRouteReason -Route $r -Paths @($p))){throw $p}}"
        )
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
