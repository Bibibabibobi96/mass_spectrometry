from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from queue import Empty, Queue
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGED_GATE = REPO_ROOT / "common" / "verify.ps1"
ROUTE_TABLE = REPO_ROOT / "common" / "gate_catalog.json"
PARALLEL_GATE_SUPPORT = REPO_ROOT / "common" / "parallel_gate_support.ps1"
LIGHTWEIGHT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lightweight-gate.yml"


class ChangedGateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        summary_directory = tempfile.TemporaryDirectory(prefix="changed_gate_summary_test_")
        self.addCleanup(summary_directory.cleanup)
        self.summary_path = str(Path(summary_directory.name) / "summary.json")

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CHANGED_GATE.read_text(encoding="utf-8")
        cls.parallel_source = PARALLEL_GATE_SUPPORT.read_text(encoding="utf-8")
        cls.route_contract = json.loads(ROUTE_TABLE.read_text(encoding="utf-8"))
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            raise unittest.SkipTest("PowerShell Core is unavailable")
        result = subprocess.run(
            [pwsh, "-NoProfile", "-Command",
             ". ./common/gate_catalog_support.ps1; "
             "$routes=@(Read-GateCatalog -RepoRoot $PWD.Path); "
             "ConvertTo-Json -Depth 32 -Compress -InputObject $routes"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.routes = json.loads(result.stdout)

    def plan(self, *arguments):
        cache = getattr(type(self), "_plans", {})
        if arguments not in cache:
            with tempfile.TemporaryDirectory(prefix="software_gate_plan_") as directory:
                request = Path(directory) / "request.json"
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(CHANGED_GATE),
                    "-PythonExe", sys.executable, "-PlanOnly", "-InternalRequestPath", str(request), *arguments],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=40)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                cache[arguments] = (json.loads(request.read_text(encoding="utf-8-sig")), result.stdout)
            type(self)._plans = cache
        return cache[arguments]

    def batch_plan_outputs(self, cases):
        # Exercise every real planner case; share only the PowerShell host.
        payload = json.dumps([{"paths":list(paths),"full":full} for paths,full in cases])
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = f"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$cases={quote(payload)}|ConvertFrom-Json
$index=0
foreach($case in $cases){{
 $parameters=@{{PythonExe={quote(sys.executable)};PlanOnly=$true}}
 if($case.full){{$parameters.FullScope=$true}}else{{$parameters.ChangedPath=@($case.paths)}}
 $output=@(& {quote(CHANGED_GATE)} @parameters)
 if($LASTEXITCODE-ne0){{throw "Planner case $index failed"}}
 Write-Output ('PLAN_CASE_JSON='+(@{{index=$index;output=($output-join"`n")}}|ConvertTo-Json -Compress))
 $index++
}}
"""
        result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=REPO_ROOT,
            capture_output=True,text=True,encoding="utf-8",timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        records=[json.loads(line.removeprefix("PLAN_CASE_JSON=")) for line in result.stdout.splitlines() if line.startswith("PLAN_CASE_JSON=")]
        self.assertEqual([record["index"] for record in records],list(range(len(cases))))
        return [record["output"] for record in records]

    def test_repository_and_full_changed_preserve_core_static_distinction(self):
        changed, _ = self.plan("-FullScope")
        repository, output = self.plan("-Scope", "Repository")
        self.assertIn("EXECUTION_MODE=REPOSITORY", output)
        for stage in ("rf_multipole_quadrupole_static",):
            core = next(row for row in changed["stages"] if row["name"] == stage)
            full = next(row for row in repository["stages"] if row["name"] == stage)
            self.assertEqual(core["command"]["parameters"]["Level"], "Core")
            self.assertEqual(full["command"]["parameters"]["Level"], "Static")
        self.assertEqual(len({row["name"] for row in repository["stages"]}), len(repository["stages"]))

    def test_owner_scope_selects_complete_owner_checks_without_unrelated_project_scan(self):
        request, _ = self.plan("-Scope", "Owner", "-Owner", "orthogonal_accelerator")
        stages = {row["name"]:row for row in request["stages"]}
        owner_route = next(route for route in self.routes if route.get("project_id")=="orthogonal_accelerator")
        self.assertIn(owner_route["stage"], stages)
        expected = owner_route.get("repository_integration_command", owner_route["command"])
        actual = stages[owner_route["stage"]]["command"]
        self.assertEqual(actual["script"], expected["script"])
        for key, value in expected.get("parameters", {}).items():
            if key != "PythonExe":
                self.assertEqual(actual["parameters"][key], value)
        unrelated = {route["stage"] for route in self.routes if route.get("project_id") not in (None,"orthogonal_accelerator")}
        self.assertFalse(unrelated.intersection(stages), unrelated.intersection(stages))
        lint = stages["ruff_changed_python"]["command"]["arguments"][3:]
        self.assertTrue(lint)
        self.assertTrue(all("orthogonal_accelerator" in value for value in lint),lint)
        standards = stages["development_standards"]["command"]["arguments"]
        self.assertIn("--path", standards)
        selected = [standards[index+1] for index,value in enumerate(standards) if value=="--path"]
        self.assertTrue(selected)
        self.assertTrue(all(value.startswith("projects/orthogonal_accelerator/") for value in selected),selected)

    def test_owner_group_and_stage_alias_bind_the_actual_source_owner(self):
        contracts,_=self.plan("-Scope","Owner","-Owner","common/contracts")
        self.assertTrue({"common_contracts","project_registry"}<={row["name"] for row in contracts["stages"]})
        project,_=self.plan("-Scope","Owner","-Owner","rf_multipole_ion_optics")
        self.assertIn("rf_multipole_domain_tests",{row["name"] for row in project["stages"]})
        alias,_=self.plan("-Scope","Owner","-Owner","rf_multipole_domain_tests")
        standards=next(row for row in alias["stages"] if row["name"]=="development_standards")
        arguments=standards["command"]["arguments"]
        selected=[arguments[index+1] for index,value in enumerate(arguments) if value=="--path"]
        self.assertIn("projects/rf_multipole_ion_optics/core/ideal_transport.py",selected)
        self.assertTrue(all(path.startswith("projects/rf_multipole_ion_optics/") for path in selected),selected)

    def test_unknown_owner_is_rejected_during_selection_before_resource_admission(self):
        with tempfile.TemporaryDirectory(prefix="unknown_owner_plan_") as directory:
            ledger = Path(directory)/"ledger.sqlite3"
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-File",str(CHANGED_GATE),
                "-PythonExe",sys.executable,"-Scope","Owner","-Owner","no_such_owner","-PlanOnly"],
                cwd=REPO_ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30,
                env={**os.environ,"MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH":str(ledger)})
            self.assertNotEqual(result.returncode,0)
            self.assertIn("owner",result.stderr.lower())
            self.assertFalse(ledger.exists())

    def test_short_analysis_batches_preserve_each_declared_module_once(self):
        request, _ = self.plan("-Scope", "Repository")
        expected = [module for route in self.routes if route.get("execution_batch") == "analysis"
                    for module in route["command"]["arguments"][2:]]
        actual = [module for row in request["stages"] if row["name"].startswith("analysis_")
                  for module in row["command"]["arguments"][2:]]
        self.assertCountEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_common_contract_dependencies_select_modules_without_retired_routes(self):
        cases = (("common/contracts/expected_values.py", "common.contracts.test_expected_values"),
                 ("common/report_cloc_delta.ps1", "common.contracts.test_report_cloc_delta"),
                 ("common/verify.ps1", "common.contracts.test_verify_changed"),
                 ("pyproject.toml", "common.contracts.test_python_dependency_contract"),
                 ("common/contracts/schemas/oatof_three_zone_stage_report.schema.json", "common.contracts.test_machine_contracts_paths"))
        for path, module in cases:
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                owner = next(row for row in request["stages"] if row["name"] == "common_contracts")
                modules = [value.removesuffix(".py").replace("/", ".") for value in owner["command"]["arguments"]]
                self.assertIn(module, modules)
                self.assertEqual(len(owner["command"]["arguments"]), len(set(owner["command"]["arguments"])))

    def routed_stages(self, path: str) -> dict[str, str]:
        selected: dict[str, str] = {}
        for route in self.routes:
            for match in route["matches"]:
                matched = (
                    ("exact" in match and path.casefold() == match["exact"].casefold())
                    or (
                        "prefix" in match
                        and path.casefold().startswith(match["prefix"].casefold())
                    )
                    or (
                        "regex" in match
                        and re.search(match["regex"], path, re.IGNORECASE) is not None
                    )
                )
                if matched:
                    selected[route["stage"]] = match["reason"]
                    break
        return selected




    def test_changed_ruff_argfile_handles_long_paths_and_cleans_after_failure(self) -> None:
        """Run the actual changed-file action with native Ruff, including F821."""
        pwsh = shutil.which("pwsh")
        with tempfile.TemporaryDirectory(prefix="changed_ruff_argfile_") as directory:
            root = Path(directory)
            temporary_files = root / "temporary arguments"
            temporary_files.mkdir()
            valid = root / "valid # 场 path.py"
            invalid = root / "invalid # 场 path.py"
            valid.write_text("value = 1\n", encoding="utf-8")
            invalid.write_text("missing_name()\n", encoding="utf-8")
            paths = [str(valid)]
            # Exercise more than CreateProcessW's 32,767 UTF-16 characters,
            # without creating hundreds of redundant fixture files.
            while sum(len(path) + 3 for path in paths) <= 32767:
                paths += paths
            for failed in (False, True):
                with self.subTest(failed=failed):
                    selected = paths + ([str(invalid)] if failed else [])
                    path_list = root / "paths.json"
                    path_list.write_text(json.dumps(selected), encoding="utf-8")
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    command = f"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$env:RUFF_NO_CACHE='true';$env:RAYON_NUM_THREADS='1'
$env:TMP={quote(temporary_files)};$env:TEMP={quote(temporary_files)}
$PythonExe={quote(sys.executable)}
$existingPythonFiles=@(Get-Content -Raw -LiteralPath {quote(path_list)}|ConvertFrom-Json)
. {quote(REPO_ROOT / 'common/gate_catalog_support.ps1')}
$command=[pscustomobject]@{{runner='python';arguments=@('-m','ruff','check')+$existingPythonFiles}}
try{{Invoke-GateCatalogCommand -Command $command -RepoRoot {quote(REPO_ROOT)} -PythonExe $PythonExe}}
catch{{if($LASTEXITCODE-ne{int(failed)}){{throw}}}}
$nativeExitCode=$LASTEXITCODE
if($nativeExitCode-ne{int(failed)}){{throw "Unexpected native Ruff exit $nativeExitCode"}}
if(@(Get-ChildItem -LiteralPath {quote(temporary_files)} -Force).Count){{throw 'Ruff argument file leaked'}}
Write-Output "CHANGED_RUFF_NATIVE_EXIT=$nativeExitCode"
exit 0
"""
                    completed = subprocess.run(
                        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                        cwd=REPO_ROOT, capture_output=True, text=True,
                        encoding="utf-8", timeout=30, check=False,
                    )
                    output = completed.stdout + completed.stderr
                    self.assertEqual(completed.returncode, 0, output)
                    self.assertIn(f"CHANGED_RUFF_NATIVE_EXIT={int(failed)}", output)
                    self.assertIn("F821" if failed else "All checks passed!", output)
                    self.assertEqual(list(temporary_files.iterdir()), [])

    def test_integration_documentation_action_forwards_selected_python(self) -> None:
        request, _ = self.plan("-Scope", "Repository")
        documentation = next(stage for stage in request["stages"] if stage["name"] == "documentation")
        self.assertEqual(documentation["command"]["parameters"]["PythonExe"], sys.executable)

    def test_documentation_only_fast_path_runs_without_project_gates(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        fixture_directory = tempfile.TemporaryDirectory(prefix="documentation_changed_gate_")
        self.addCleanup(fixture_directory.cleanup)
        fixture_root = Path(fixture_directory.name)
        common = fixture_root / "common"
        common.mkdir()
        (fixture_root / "projects").mkdir()
        (fixture_root / "integrations").mkdir()
        for name in ("verify.ps1", "parallel_gate_support.ps1", "gate_catalog_support.ps1", "require_powershell7.ps1"):
            shutil.copyfile(REPO_ROOT / "common" / name, common / name)
        (common / "host_execution_lease.ps1").write_text("function Get-HostResourceBudget {param($Role,$Stage) @{}}\nfunction Enter-HostResourceStage {param($Role,$Stage,$Budget) @{}}\nfunction Exit-HostResourceStage {param($Lease)}\n",encoding="utf-8")
        (common / "gate_catalog.json").write_text('{"schema_version":2,"role":"repository_gate_catalog","routes":[{"stage":"unrelated_project","dependency_profile":"locked","repository_integration_group":"regression","matches":[{"exact":"projects/unrelated/source.py","reason":"unrelated"}],"command":{"runner":"python","arguments":["-c","print(42)"]}}]}',encoding="utf-8")
        (common / "verify_repository_hygiene.ps1").write_text("Write-Output 'REPOSITORY_HYGIENE=PASS'\n",encoding="utf-8")
        (common / "verify_repository_text_bytes.py").write_text("print('TEXT_BYTES_FIXTURE=PASS')\n",encoding="utf-8")
        (common / "verify_documentation.ps1").write_text("param($PythonExe,[switch]$StructureOnly,[string[]]$ChangedPath)\nWrite-Output 'DOCUMENTATION_FIXTURE=PASS'\n",encoding="utf-8")
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(common / "verify.ps1"),
                "-PythonExe",
                sys.executable,
                "-ChangedPath",
                "CHANGELOG.md",
                "-SummaryPath", self.summary_path,
            ],
            cwd=fixture_root,
            capture_output=True,
            text=True, encoding="utf-8",
            # This executes all three real documentation gates under host
            # admission; it checks routing, not a 30-second performance SLA.
            timeout=180,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.count("REPOSITORY_HYGIENE=PASS"), 1)
        self.assertIn("GATE_STAGE=RUN NAME=documentation", completed.stdout)
        self.assertIn("GATE_STAGE=RUN NAME=repository_text_bytes", completed.stdout)
        self.assertLess(
            completed.stdout.index("GATE_STAGE=RUN NAME=repository_text_bytes"),
            completed.stdout.index("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY"),
        )
        self.assertIn("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY", completed.stdout)
        self.assertNotIn("GATE_STAGE=RUN NAME=rf_multipole_domain_tests", completed.stdout)
        self.assertNotIn(
            "GATE_STAGE=RUN NAME=rf_multipole_quadrupole_static",
            completed.stdout,
        )

    def test_accelerator_provider_and_shared_geometry_route_to_consumers(self) -> None:
        provider = self.routed_stages("projects/orthogonal_accelerator/analysis/accelerator_time_focus.py")
        self.assertTrue({
            "orthogonal_accelerator_static", "single_reflection_oa_tof_mass_analyzer_static",
                    } <= provider.keys())
        primitives = self.routed_stages("common/simion/gem_primitives.py")
        self.assertTrue({
            "simion_common", "orthogonal_accelerator_static",
                    } <= primitives.keys())

    def test_accelerator_test_only_routes_preserve_actual_shared_fixture_consumers(self) -> None:
        downstream = {"instrument_assembly_integration", "parallel_mirror_dual_stripe_mr_tof_static",
                      "single_reflection_oa_tof_mass_analyzer_static"}
        prefix = "projects/orthogonal_accelerator/"
        for relative in ("tests/analysis/test_component_focus_analysis.py",
                         "tests/analysis/test_two_zone_geometry.py"):
            with self.subTest(relative=relative):
                stages = self.routed_stages(prefix + relative)
                self.assertIn("orthogonal_accelerator_static", stages)
                self.assertFalse(downstream & stages.keys())
        # The integration fixture imports this actual provider test module;
        # package initialization also affects that import boundary.
        for relative in ("tests/analysis/test_bare_three_zone_component.py",
                         "tests/__init__.py", "tests/analysis/__init__.py"):
            with self.subTest(relative=relative):
                stages = self.routed_stages(prefix + relative)
                self.assertTrue(any(name == "instrument_assembly_integration" or name.startswith("instrument_assembly_integration__tests_") for name in stages), stages)
                self.assertIn("orthogonal_accelerator_static", stages)
                self.assertNotIn("parallel_mirror_dual_stripe_mr_tof_static", stages)
                self.assertNotIn("single_reflection_oa_tof_mass_analyzer_static", stages)
        self.assertTrue(downstream <= self.routed_stages(
            prefix + "analysis/component_focus_analysis.py").keys())

    def test_extracted_mechanisms_keep_automatic_regression_routes(self) -> None:
        for implementation, stage, module in (
            ("common/contracts/expected_values.py", "common_contracts",
             "common.contracts.test_expected_values"),
            ("common/analysis/longitudinal_fit.py", "longitudinal_fit_tests",
             "common.analysis.test_longitudinal_fit"),
        ):
            with self.subTest(implementation=implementation):
                self.assertIn(stage, self.routed_stages(implementation))
                route = next(row for row in self.routes if row["stage"] == stage)
                self.assertIn(route["repository_integration_group"], {"fast", "regression", "covered"})
                if stage == "common_contracts":
                    request, _ = self.plan("-ChangedPath", implementation)
                    command = next(row["command"] for row in request["stages"] if row["name"] == stage)
                    self.assertIn(module, [arg.removesuffix(".py").replace("/", ".") for arg in command["arguments"]])
                else:
                    self.assertIn(module, route["command"]["arguments"])
        self.assertTrue({
            "single_reflection_oa_tof_mass_analyzer_static",
                    } <= self.routed_stages("common/analysis/longitudinal_fit.py").keys())
        self.assertIn("orthogonal_accelerator_static",
                      self.routed_stages("common/contracts/expected_values.py"))
        self.assertTrue({"single_reflection_oa_tof_mass_analyzer_static", "instrument_assembly_integration"}
                        <= self.routed_stages("common/analysis/field_comparison.py").keys())

    def test_host_scheduler_and_adapters_keep_regression_routes(self) -> None:
        for path, expected in (
            ("common/host_resource_scheduler.py", {"host_resource_scheduler_tests", "host_resource_adapter_tests"}),
            ("common/host_resource_policy.json", {"host_resource_scheduler_tests", "host_resource_adapter_tests"}),
            ("common/comsol/run_comsol_r2025b.ps1", {"livelink_resource_stages_tests"}),
        ):
            with self.subTest(path=path):
                self.assertTrue(expected <= self.routed_stages(path).keys())
        gate_route = next(row for row in self.routes if row["stage"] == "common_contracts")
        self.assertEqual(gate_route["command"]["runner"], "python")

    def test_python_host_bridge_uses_one_shared_scheduler_stage_in_l1_and_l2(self) -> None:
        stage = "host_resource_scheduler_tests"
        for path in ("common/host_resource_python.py", "common/host_resource_python.ps1",
                     "common/test_host_resource_python.py"):
            expected = {stage}
            if path == "common/host_resource_python.py":
                expected.add("instrument_assembly_integration")
            self.assertEqual(set(self.routed_stages(path)), expected, path)
        routes = [route for route in self.routes if route["stage"] == stage]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["dependency_profile"], "locked")
        self.assertEqual(routes[0]["repository_integration_group"], "fast")
        self.assertEqual(routes[0]["command"]["arguments"],
                         ["-m", "unittest", "common.test_host_resource_scheduler", "common.test_host_resource_python"])
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        result = subprocess.run([pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PythonExe", sys.executable,
                                 "-PlanOnly", "-ChangedPath", "common/host_resource_python.ps1"],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
        self.assertIsNotNone(selected, result.stdout)
        self.assertEqual(selected[1].split(",").count(stage), 1)
        script = (f". '{REPO_ROOT}/common/gate_catalog_support.ps1';"
                  f"$routes=@(Read-GateCatalog -RepoRoot '{REPO_ROOT}');"
                  "$stages=@($routes|Where-Object repository_integration_group -eq 'fast'|ForEach-Object stage);"
                  "ConvertTo-Json -Compress -InputObject $stages")
        result = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout).count(stage), 1)

    def test_integration_test_module_change_runs_only_that_module(self) -> None:
        request, _ = self.plan("-ChangedPath", "integrations/tests/test_repository_bindings.py")
        integration = [row for row in request["stages"] if row["name"].startswith("instrument_assembly_integration")]
        self.assertEqual(len(integration), 1)
        command = integration[0]["command"]
        modules = command.get("parameters", {}).get("ChangedTestModules", command.get("arguments", [])[2:])
        modules = [value.removesuffix(".py").replace("/", ".") for value in modules]
        self.assertEqual(modules, ["integrations.tests.test_repository_bindings"])
        self.assertFalse(command.get("parameters", {}).get("PreflightOnly", False))


    def test_integration_source_routes_full_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        integration_root = (
            "integrations/"
        )
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(CHANGED_GATE),
                "-PythonExe",
                sys.executable,
                "-ChangedPath",
                integration_root + "runtime/refresh_repository_bindings.py",
                "-PlanOnly",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True, encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("EXECUTION_MODE=FULL_CHANGED_SCOPE", completed.stdout)
        self.assertIn("instrument_assembly_integration", completed.stdout)
        for index in range(1, 5):
            self.assertIn(f"instrument_assembly_integration__tests_{index:02d}", completed.stdout)

    def test_routes_project_config_to_its_own_static_gate(self) -> None:
        project_gates = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "projects").glob("*/verify_project.ps1")
        )
        project_routes = [route for route in self.routes if "project_id" in route]
        routed_gates = sorted(route["command"]["script"] for route in project_routes)
        self.assertEqual(routed_gates, project_gates)
        self.assertEqual(
            len(project_routes),
            len({route["project_id"] for route in project_routes}),
        )
        for route in project_routes:
            project_id = route["project_id"]
            self.assertEqual(
                route["command"]["script"],
                f"projects/{project_id}/verify_project.ps1",
            )
            selected = self.routed_stages(
                f"projects/{project_id}/config/example.json"
            )
            self.assertIn(route["stage"], selected)

    def test_catalog_declares_dependency_and_l2_ownership_for_every_stage(self) -> None:
        self.assertEqual(self.route_contract["schema_version"], 2)
        self.assertEqual(self.route_contract["role"], "repository_gate_catalog")
        for route in self.routes:
            self.assertIn(route["dependency_profile"], {"stdlib", "locked"})
            self.assertIn(
                route["repository_integration_group"],
                {"fast", "regression", "covered"},
            )
        integration_gates = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "integrations").rglob(
                "verify_integration.ps1"
            )
        )
        routed_integrations = sorted(
            route["command"]["script"]
            for route in self.routes
            if route["command"].get("script", "").startswith("integrations/")
        )
        self.assertEqual(routed_integrations, integration_gates)

    def test_multipole_variants_have_separate_routes_and_one_project_registration(self) -> None:
        stages = {f"rf_multipole_{variant}_static" for variant in ("quadrupole", "hexapole", "octupole")}
        project_routes = [route for route in self.routes if route.get("project_id") == "rf_multipole_ion_optics"]
        self.assertEqual([route["stage"] for route in project_routes], ["rf_multipole_generated_publications"])
        for variant in ("quadrupole", "hexapole", "octupole"):
            expected = f"rf_multipole_{variant}_static"
            test_directory = "analysis" if variant == "quadrupole" else variant
            paths = (
                f"projects/rf_multipole_ion_optics/variants/{variant}/config/design_request.json",
                f"projects/rf_multipole_ion_optics/tests/{test_directory}/test_contract.py",
            )
            for path in paths:
                with self.subTest(path=path):
                    selected = self.routed_stages(path)
                    self.assertEqual(stages.intersection(selected), {expected})
                    self.assertIn("rf_multipole_generated_publications", selected)
            route = next(route for route in self.routes if route["stage"] == expected)
            self.assertEqual(route["command"]["script"], "projects/rf_multipole_ion_optics/verify_project.ps1")
            self.assertEqual(route["command"]["parameters"]["StructuralVariant"], variant)
            self.assertEqual(route["requires_stages"], ["rf_multipole_generated_publications"])
        for path in (
            "projects/rf_multipole_ion_optics/config/project.json",
            "projects/rf_multipole_ion_optics/analysis/resolve_contract.py",
            "projects/rf_multipole_ion_optics/tests/test_support/historical_contracts.py",
            "projects/rf_multipole_ion_optics/tests/domain/run_production_probe.ps1",
        ):
            with self.subTest(path=path):
                self.assertTrue(stages.issubset(self.routed_stages(path)))
        for old in ("rf_quadrupole_ion_optics", "rf_hexapole_ion_optics", "rf_octupole_ion_optics"):
            self.assertFalse(any(route.get("project_id") == old for route in self.routes))
            self.assertFalse(any(route["command"].get("script") == f"projects/{old}/verify_project.ps1" for route in self.routes))

    def test_variant_plan_includes_freshness_and_only_its_static_selection(self) -> None:
        stages = {f"rf_multipole_{variant}_static" for variant in ("quadrupole", "hexapole", "octupole")}
        for variant in ("quadrupole", "hexapole", "octupole"):
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(CHANGED_GATE),
                 "-PythonExe", sys.executable, "-PlanOnly", "-ChangedPath",
                 f"projects/rf_multipole_ion_optics/variants/{variant}/config/design_request.json"],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
            self.assertIsNotNone(selected, completed.stdout)
            selected_stages = set(selected.group(1).split(","))
            self.assertEqual(stages.intersection(selected_stages), {f"rf_multipole_{variant}_static"})
            self.assertIn("rf_multipole_generated_publications", selected_stages)

    def test_direct_integration_gate_owns_only_its_tests(self) -> None:
        for path in ("integrations/tests/test_dependencies.py",
                     "integrations/config/runtime_dependencies.json",
                     "integrations/verify_integration.ps1",
                     "integrations/workflows/local_frontend/prepare.py",
                     "integrations/runtime/dependencies.ps1",
                     "integrations/runtime/single_flight_frontend.py",
                     "integrations/analysis/plot_single_flight_spatial_six_panel.py"):
            with self.subTest(path=path):
                self.assertEqual(set(self.routed_stages(path)), {"instrument_assembly_integration"})


    def test_direct_integration_gate_routes_its_declared_frozen_dependencies(self) -> None:
        inventory = json.loads((REPO_ROOT / "integrations/config/runtime_dependencies.json").read_text(encoding="utf-8"))
        for group in inventory["providers"]:
            for dependency in group["files"]:
                with self.subTest(dependency=dependency["id"]):
                    self.assertIn("instrument_assembly_integration", self.routed_stages(dependency["source_repo_path"]))

    def test_runtime_dependency_paths_select_the_real_integration_plan(self) -> None:
        # These newly consumed geometry/export paths previously escaped L1 routing.
        paths = [
            "common/comsol/add_comsol_size_feature.m",
            "projects/single_reflection_oa_tof_mass_analyzer/analysis/compare_vector_field_samples.py",
            "common/analysis/field_comparison.py",
            "projects/single_reflection_oa_tof_mass_analyzer/comsol/build_and_export_paired_accelerator_field.m",
            "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_accelerator_geometry.m",
            "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_grid_geometry.m",
            "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_read_cartesian_release.m",
            "projects/single_reflection_oa_tof_mass_analyzer/simion/export_paired_accelerator_field.lua",
        ]
        for path in paths:
            with self.subTest(path=path):
                result = self._runtime_dependency_plan(REPO_ROOT, path)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("instrument_assembly_integration", result.stdout)
                selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
                self.assertIsNotNone(selected, result.stdout)
                self.assertTrue(any(name == "instrument_assembly_integration" or name.startswith("instrument_assembly_integration__tests_") for name in selected[1].split(",")), selected[1])

    @staticmethod
    def _runtime_dependency_plan(repo: Path, changed_path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-File", str(repo / "common/verify.ps1"),
             "-PythonExe", sys.executable, "-PlanOnly", "-ChangedPath", changed_path],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_runtime_inventory_changes_route_without_editing_the_catalog(self) -> None:
        # Copy only the real plan/parser boundary; no gate stage or solver executes.
        with tempfile.TemporaryDirectory(prefix="gate_inventory_") as directory:
            repo = Path(directory)
            (repo / "common").mkdir()
            (repo / "projects").mkdir()
            (repo / "integrations/config").mkdir(parents=True)
            for name in ("verify.ps1", "gate_catalog_support.ps1", "parallel_gate_support.ps1",
                         "host_execution_lease.ps1", "require_powershell7.ps1"):
                shutil.copyfile(REPO_ROOT / "common" / name, repo / "common" / name)
            gate = repo / "integrations/verify_integration.ps1"
            gate.write_text("throw 'PlanOnly must not execute stages'\n", encoding="utf-8")
            inventory_path = "integrations/config/runtime_dependencies.json"
            route = dict(stage="instrument_assembly_integration", dependency_profile="locked",
                         repository_integration_group="regression",
                         matches=[dict(prefix="integrations/", reason="integration_changed")],
                         runtime_dependencies_path=inventory_path,
                         command=dict(runner="powershell", script="integrations/verify_integration.ps1"))
            (repo / "common/gate_catalog.json").write_text(json.dumps(dict(
                schema_version=2, role="repository_gate_catalog", routes=[route])), encoding="utf-8")
            inventory = dict(schema_version=2, role="integration_runtime_dependencies", providers=[
                dict(files=[dict(source_repo_path="common/first_dependency.py")])])
            target = repo / inventory_path
            first = repo / "common/first_dependency.py"
            added = repo / "common/added_dependency.py"
            first.write_text("", encoding="utf-8")
            added.write_text("", encoding="utf-8")
            target.write_text(json.dumps(inventory), encoding="utf-8")
            result = self._runtime_dependency_plan(repo, "common/added_dependency.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
            self.assertIsNotNone(selected, result.stdout)
            self.assertNotIn("instrument_assembly_integration", selected[1].split(","))
            inventory["providers"][0]["files"].append(dict(source_repo_path="common/added_dependency.py"))
            target.write_text(json.dumps(inventory), encoding="utf-8")
            result = self._runtime_dependency_plan(repo, "common/added_dependency.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("instrument_assembly_integration", re.search(
                r"SELECTED_STAGES=([^\s]+)", result.stdout)[1].split(","))
            for case in ("missing_inventory", "unknown_schema", "unknown_role", "missing_source"):
                with self.subTest(case=case):
                    changed = json.loads(json.dumps(inventory))
                    if case == "missing_inventory":
                        target.unlink()
                    else:
                        if case == "unknown_schema":
                            changed["schema_version"] = 999
                        elif case == "unknown_role":
                            changed["role"] = "unknown_inventory"
                        else:
                            changed["providers"][0]["files"][0]["source_repo_path"] = "common/missing.py"
                        target.write_text(json.dumps(changed), encoding="utf-8")
                    result = self._runtime_dependency_plan(repo, "common/added_dependency.py")
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("dependency", result.stderr)
                    self.assertNotIn("SELECTED_STAGES=", result.stdout)

    def test_direct_integration_test_plan_selects_its_own_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PlanOnly",
             "-PythonExe", sys.executable, "-ChangedPath", "integrations/tests/test_dependencies.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
        self.assertIsNotNone(selected, completed.stdout)
        stages = selected.group(1).split(",")
        self.assertTrue(any(name == "instrument_assembly_integration" or name.startswith("instrument_assembly_integration__tests_") for name in stages), stages)
        self.assertNotIn("rf_multipole_to_single_reflection_oatof_integration", stages)

    def test_mrtof_uses_fast_changed_gate_and_complete_solver_free_l2_gate(self) -> None:
        route = next(
            item for item in self.routes
            if item.get("project_id") == "parallel_mirror_dual_stripe_mr_tof"
        )
        self.assertEqual(
            route["command"]["parameters"],
            {"Level": "Core", "PythonExe": "{python}"},
        )
        self.assertEqual(
            route["repository_integration_command"]["parameters"],
            {"Level": "Static", "PythonExe": "{python}", "PreflightOnly": True},
        )
        self.assertEqual(route["repository_integration_partition"]["parameter"], "SelectedTestModules")
        self.assertNotIn("SimionExe", json.dumps(route))

    def test_l2_mr_partitions_cover_the_actual_owner_discovery_once(self) -> None:
        script = (". ./common/gate_catalog_support.ps1; "
                  "$route=@(Read-GateCatalog -RepoRoot $PWD.Path | Where-Object "
                  "stage -eq 'parallel_mirror_dual_stripe_mr_tof_static')[0]; "
                  "$groups=@(Get-GateRepositoryTestPartitions -Route $route -RepoRoot $PWD.Path); "
                  "ConvertTo-Json -Compress -Depth 8 -InputObject @($groups | ForEach-Object { "
                  "[pscustomobject]@{modules=@($_.modules);seconds=$_.seconds} })")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        groups = json.loads(result.stdout)
        names = [name for group in groups for name in group["modules"]]
        test_root = REPO_ROOT / "projects/parallel_mirror_dual_stripe_mr_tof/tests"
        expected = [".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
                    for path in test_root.rglob("test_*.py")]
        self.assertCountEqual(names, expected)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(group["seconds"] > 0 for group in groups))

    def test_l1_partitions_only_semantically_complete_owner_commands(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        script = r'''. ./common/gate_catalog_support.ps1
$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'common/verify.ps1'),[ref]$null,[ref]$errors)
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Test-CompletePartitionOwnerCommand'},$true)
Invoke-Expression $node.Extent.Text
$routes=@(Read-GateCatalog -RepoRoot $PWD.Path)
$mr=$routes|Where-Object stage -eq 'parallel_mirror_dual_stripe_mr_tof_static'
$integration=$routes|Where-Object stage -eq 'instrument_assembly_integration'
$full=$mr.repository_integration_command|ConvertTo-Json -Depth 16|ConvertFrom-Json -Depth 16
$full.parameters.PSObject.Properties.Remove('PreflightOnly')
@{mr_core=(Test-CompletePartitionOwnerCommand $mr $mr.command);mr_full=(Test-CompletePartitionOwnerCommand $mr $full);integration_full=(Test-CompletePartitionOwnerCommand $integration $integration.command)}|ConvertTo-Json -Compress
'''
        result = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(mr_core=False, mr_full=True, integration_full=True))
        result = subprocess.run([pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PythonExe", sys.executable,
            "-PlanOnly", "-ChangedPath", "projects/parallel_mirror_dual_stripe_mr_tof/analysis/native_corridor_plan.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("parallel_mirror_dual_stripe_mr_tof_static", result.stdout)
        self.assertNotIn("parallel_mirror_dual_stripe_mr_tof_static__tests_", result.stdout)

    def test_mr_partition_preflight_cannot_claim_a_full_gate(self) -> None:
        gate = REPO_ROOT / "projects/parallel_mirror_dual_stripe_mr_tof/verify_project.ps1"
        module = "projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_drift_phase_contract"
        script = ("& '" + str(gate).replace("'", "''") + "' -Level Static -PythonExe '" +
                  sys.executable.replace("'", "''") + "' -SelectedTestModules @('" + module +
                  "') -PreflightValidated")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MRTOF_TEST_PARTITION=PASS PREFLIGHT_PREVALIDATED=True FULL_PROJECT_GATE=False", result.stdout)
        self.assertNotIn("PROJECT_REGISTRY=PASS", result.stdout)
        self.assertNotIn("PROJECT_GATE=PASS", result.stdout)
        invalid = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(gate),
                                  "-Level", "Static", "-PreflightValidated"], cwd=REPO_ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertNotEqual(invalid.returncode, 0)

    def test_plan_mode_is_fail_closed_for_dependency_selection(self) -> None:
        cases=[("CHANGELOG.md","stdlib"),("README.md","stdlib"),
               ("projects/rf_multipole_ion_optics/README.md","stdlib"),("common/contracts/README.md","stdlib")]
        cases += [(path,"locked") for path in ("common/gate_catalog_support.ps1","common/verify.ps1",
                  "common/contracts/test_verify_changed.py",".github/workflows/lightweight-gate.yml",
                  "pyproject.toml","config/project_registry.json","projects/rf_multipole_ion_optics/config/project.json")]
        outputs=self.batch_plan_outputs([((path,),False) for path,_ in cases])
        for (path,expected),output in zip(cases,outputs):
            with self.subTest(path=path):
                match=re.search(r"DEPENDENCY_PROFILE=(stdlib|locked)",output)
                self.assertIsNotNone(match,output)
                self.assertEqual(match.group(1),expected)


    def test_history_text_snapshots_use_only_the_documentation_fast_path(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        project = "projects/parallel_mirror_dual_stripe_mr_tof/"
        snapshot = project + "docs/history/20261015__cad-exchange/CAD.before.txt"
        cases = (
            (("common/contracts/README.md",), False, True),
            (("docs/DEVELOPMENT_STANDARDS.md",), False, False),
            (("common/contracts/artifact_capacity_policy.json",), False, False),
            (("config/unknown_scope.json",), False, False),
            ((project + "docs/CAD.md", snapshot), False, True),
            ((snapshot,), False, True),
            (("docs/history/20261015__milestone/PROJECT.before.txt",), False, True),
            (("integrations/example/docs/history/20261015__milestone/PROJECT.before.txt",), False, True),
            ((project + "docs/CAD.before.txt",), False, False),
            ((project + "config/project.json",), False, False),
            ((project + "docs/history/x/snapshot_manifest.json",), False, False),
            ((project + "docs/history/x/old.py",), False, False),
            ((project + "docs/history/x/nested/CAD.before.txt",), False, False),
            ((project + "docs/history/CAD.before.txt",), False, False),
            ((snapshot, project + "analysis/simion_event_analysis.py"), False, False),
            ((), True, False),
        )
        outputs=self.batch_plan_outputs([(paths,full) for paths,full,_ in cases])
        for (paths,full_scope,documentation_only),output in zip(cases,outputs):
            with self.subTest(paths=paths,full_scope=full_scope):
                mode = "DOCUMENTATION_ONLY" if documentation_only else "FULL_CHANGED_SCOPE"
                self.assertIn(f"EXECUTION_MODE={mode}", output)
                if documentation_only:
                    self.assertIn(
                        "EFFECTIVE_STAGES=repository_hygiene,repository_text_bytes,documentation",
                        output,
                    )
                    self.assertRegex(output, r"SELECTED_STAGES=[^\r\n]*\bdocumentation\b")
                else:
                    self.assertRegex(output, r"EFFECTIVE_STAGES=[^\r\n]*\bdevelopment_standards\b")

    def test_real_development_stage_uses_changed_paths_and_removes_transport_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standards_changed_stage_") as directory:
            root = Path(directory)
            request, log = root / "request.json", root / "stage.log"
            from common.contracts.test_changed_test_selection import write_planned_request
            write_planned_request(REPO_ROOT, request, ["common/contracts/test_expected_values.py"])
            result = subprocess.run([
                shutil.which("pwsh"), "-NoProfile", "-File", str(CHANGED_GATE),
                "-InternalStage", "development_standards", "-InternalRequestPath", str(request),
                "-InternalLogPath", str(log),
            ], cwd=REPO_ROOT, timeout=60, capture_output=True, text=True, encoding="utf-8",
                env=dict(os.environ, TEMP=directory, TMP=directory, PYTHONDONTWRITEBYTECODE="1"))
            output = result.stdout + result.stderr + (log.read_text(encoding="utf-8") if log.exists() else "")
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("DEVELOPMENT_SCOPE=CHANGED REASON=explicit_changed_paths", output)
            self.assertIn("GATE_STAGE=PASS NAME=development_standards", output)
            self.assertEqual(list(root.glob("tmp*.tmp")), [])

    def test_internal_stage_executes_resolved_command_without_replanning(self) -> None:
        from common.contracts.test_changed_test_selection import write_planned_request
        with tempfile.TemporaryDirectory(prefix="resolved_gate_stage_") as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            (root / "projects").mkdir()
            (root / "integrations").mkdir()
            for name in ("verify.ps1", "parallel_gate_support.ps1", "gate_catalog_support.ps1",
                         "require_powershell7.ps1"):
                shutil.copyfile(REPO_ROOT / "common" / name, common / name)
            (common / "host_execution_lease.ps1").write_text(
                "function Get-HostResourceBudget { param($Stage,$Role) return @{} }\n"
                "function Enter-HostResourceStage { param($Role,$Stage,$Budget) return @{} }\n"
                "function Exit-HostResourceStage { param($Lease) }\n", encoding="utf-8")
            catalog = {"schema_version": 2, "role": "repository_gate_catalog", "routes": [{
                "stage": "probe", "dependency_profile": "stdlib", "repository_integration_group": "fast",
                "matches": [{"exact": "probe.py", "reason": "probe_changed"}],
                "command": {"runner": "python", "arguments": ["-c", "print('RESOLVED_STAGE_RAN')"]},
            }]}
            catalog_path = common / "gate_catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            request = root / "request.json"
            write_planned_request(root, request, ["probe.py"])
            # The already planned child must not rediscover catalog/routes or
            # enumerate unrelated test modules after the parent planned them.
            catalog_path.unlink()
            for failed in (False, True):
                planned = json.loads(request.read_text(encoding="utf-8-sig"))
                probe = next(stage for stage in planned["stages"] if stage["name"] == "probe")
                probe["command"]["arguments"][-1] = "print('RESOLVED_STAGE_RAN'); raise SystemExit(" + str(7 if failed else 0) + ")"
                request.write_text(json.dumps(planned), encoding="utf-8")
                for gate in ("verify.ps1",):
                    log = root / "stage.log"
                    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(common / gate),
                        "-InternalStage", "probe", "-InternalRequestPath", str(request), "-InternalLogPath", str(log)],
                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode != 0, failed, result.stdout + result.stderr)
                    self.assertIn("RESOLVED_STAGE_RAN", log.read_text(encoding="utf-8"))
                    sidecar = json.loads(log.with_name("stage.log.result.json").read_text(encoding="utf-8"))
                    self.assertEqual(sidecar["status"], "FAIL" if failed else "PASS")

    def test_specialized_schemas_use_owner_and_metadata_without_directory_fanout(self) -> None:
        stages = self.routed_stages("common/contracts/schemas/oatof_three_zone_stage_report.schema.json")
        self.assertEqual(set(stages), {"common_contracts", "single_reflection_oa_tof_mass_analyzer_static"})
        for path in ("common/contracts/schemas/future_unknown.schema.json",
                     "common/contracts/machine_contracts.py", "common/contracts/run_artifact_support.ps1"):
            with self.subTest(path=path):
                self.assertIn("common_contracts", self.routed_stages(path))
                self.assertIn("rf_multipole_quadrupole_static", self.routed_stages(path))
        actual_consumer = self.routed_stages("common/contracts/schemas/multipole_resolved_design.schema.json")
        self.assertIn("instrument_assembly_integration", actual_consumer)



    def test_ci_command_wall_clock_preserves_live_output_exit_and_summary(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        programs = re.findall(r"(?ms)^          @'\n(.*?)^          '@ \| & \$python -$", workflow)
        self.assertEqual(len(programs), 2)
        fixture = r'''param($PlanPath,$MaxConcurrency,$SummaryPath)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
@{role='ci_gate_fixture';elapsed_seconds=0.005}|ConvertTo-Json|Set-Content -LiteralPath $SummaryPath -Encoding utf8
Write-Output ('CI_FIXTURE_ARGUMENTS='+(@{plan_path=$PlanPath}|ConvertTo-Json -Compress))
Write-Output 'CI_FIRST_OUTPUT_BEFORE_EXIT'
while(-not(Test-Path -LiteralPath $env:CI_FIXTURE_RELEASE)){Start-Sleep -Milliseconds 10}
if($env:CI_FIXTURE_EXIT-ne'0'){[Console]::Error.WriteLine('CI_NATIVE_FAILURE')}
exit ([int]$env:CI_FIXTURE_EXIT)
'''
        with tempfile.TemporaryDirectory(prefix="ci_command_clock_") as directory:
            root = Path(directory).resolve()
            common = root / "common"
            common.mkdir()
            for name in ("verify.ps1",):
                (common / name).write_text(fixture, encoding="utf-8")
            for job, full_scope, code in ((0, False, 0), (0, False, 7), (0, True, 0), (1, False, 0), (1, False, 7)):
                with self.subTest(job=job, full_scope=full_scope, code=code):
                    scope = {"full_scope": full_scope, "changed_paths": ["owner/含空格 file.py", "docs/README.md"]}
                    (root / "changed_scope.json").write_text(json.dumps(scope), encoding="utf-8")
                    release = root / f"release_{job}_{full_scope}_{code}"
                    environment = dict(os.environ, RUNNER_TEMP=str(root), PUBLIC_GATE_POWERSHELL=shutil.which("pwsh"),
                        PUBLIC_GATE_PYTHON=sys.executable, CI_FIXTURE_RELEASE=str(release), CI_FIXTURE_EXIT=str(code))
                    process = subprocess.Popen([sys.executable, "-c", textwrap.dedent(programs[job])], cwd=root,
                        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                    lines: list[str] = []
                    observed: Queue[str] = Queue()

                    def read_output() -> None:
                        for line in process.stdout:
                            lines.append(line)
                            observed.put(line)

                    reader = threading.Thread(target=read_output, daemon=True)
                    reader.start()
                    try:
                        deadline = time.monotonic() + 30
                        found = False
                        while time.monotonic() < deadline and not found:
                            try:
                                found = "CI_FIRST_OUTPUT_BEFORE_EXIT" in observed.get(timeout=0.1)
                            except Empty:
                                if process.poll() is not None:
                                    break
                        self.assertTrue(found, "CI wrapper buffered or lost the running gate's output")
                        self.assertIsNone(process.poll(), "root exited before the live-output observation")
                    finally:
                        release.touch()
                        process.wait(timeout=30)
                        reader.join(timeout=5)
                    stderr = process.stderr.read()
                    process.stdout.close()
                    process.stderr.close()
                    self.assertEqual(process.returncode, code, "".join(lines) + stderr)
                    prefix = "changed" if job == 0 else "integration"
                    timing = json.loads((root / f"{prefix}_gate_command_timing.json").read_text())
                    self.assertEqual(timing["exit_code"], code)
                    self.assertGreater(timing["elapsed_wall_seconds"], 0.005)
                    self.assertEqual(timing["environment"]["python_executable"], sys.executable)
                    summary = json.loads(Path(timing["summary_path"]).read_text(encoding="utf-8-sig"))
                    self.assertEqual(summary, {"role": "ci_gate_fixture", "elapsed_seconds": 0.005})
                    arguments = json.loads(next(line.split("=", 1)[1] for line in lines if line.startswith("CI_FIXTURE_ARGUMENTS=")))
                    if job == 0:
                        self.assertEqual(timing["scope"], scope)
                    self.assertEqual(Path(arguments["plan_path"]), root / "software_gate_plan.json")
                    if code:
                        self.assertIn("CI_NATIVE_FAILURE", stderr)
        self.assertIn("${{ runner.temp }}/changed_gate_command_timing.json", workflow)
        self.assertIn("${{ runner.temp }}/integration_gate_command_timing.json", workflow)

    def test_ci_temp_setup_gives_python_canonical_fixture_paths(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        scripts = re.findall(
            r"(?m)^      - name: Configure canonical test temporary directory\n"
            r"        shell: pwsh\n        run: \|\n((?:          .+\n)+)",
            workflow,
        )
        self.assertEqual(len(scripts), 2, "Both CI jobs must prepare their fixture root")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner_temp = root / "runner temporary directory"
            runner_temp.mkdir()
            environment_file = root / "github_env"
            environment = {
                key: value for key, value in os.environ.items()
                if key.casefold() not in {"runner_temp", "github_env", "path"}
            }
            environment.update(
                RUNNER_TEMP=str(runner_temp), GITHUB_ENV=str(environment_file),
                PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
            )
            for index, script in enumerate(scripts):
                with self.subTest(job=index):
                    environment_file.write_text("", encoding="utf-8")
                    result = subprocess.run(
                        [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command",
                         textwrap.dedent(script)], cwd=REPO_ROOT, env=environment,
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    exported = dict(
                        line.split("=", 1)
                        for line in environment_file.read_text(encoding="utf-8-sig").splitlines()
                    )
                    self.assertEqual(set(exported), {"TEMP", "TMP"})
                    child_environment = {
                        key: value for key, value in environment.items()
                        if key.casefold() not in {"temp", "tmp"}
                    }
                    child_environment.update(exported)
                    probe = subprocess.run(
                        [sys.executable, "-c",
                         "from pathlib import Path; import tempfile; "
                         "assert Path(tempfile.gettempdir()) == Path.cwd(); "
                         "assert Path(tempfile.mkdtemp()).parent == Path.cwd()"],
                        cwd=runner_temp, env=child_environment, capture_output=True,
                        text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)

    def test_documentation_gate_accepts_workspace_artifact_links(self) -> None:
        from tempfile import TemporaryDirectory

        from common.documentation_links import inspect_repository

        with TemporaryDirectory(prefix="documentation_gate_test_") as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "--quiet", str(root)], check=True, cwd=root, timeout=30)
            (root / "README.md").write_text(
                "# Entry\n[evidence](../artifacts/projects/example/runs/run/summary.json)\n"
                "[not evidence](../artifacts_other/missing.json)\n",
                encoding="utf-8",
            )
            report = inspect_repository(root)
            self.assertEqual(len(report["errors"]), 1)
            self.assertIn("artifacts_other/missing.json", report["errors"][0])

    def test_shared_dependencies_route_to_actual_consumers(self) -> None:
        multipole = self.routed_stages("projects/rf_multipole_ion_optics/runtime/simion_particle_source.py")
        self.assertTrue(
            {
                "rf_multipole_domain_tests",
                "rf_multipole_generated_publications",
                "rf_multipole_quadrupole_static",
                "rf_multipole_hexapole_static",
                "rf_multipole_octupole_static",
            }.issubset(multipole)
        )
        self.assertNotIn("single_reflection_oa_tof_mass_analyzer_static", multipole)

        for shared_path in (
            "common/simion/particle_source.py",
            "common/comsol/create_multipole_round_rods.m",
        ):
            routed = self.routed_stages(shared_path)
            self.assertIn("rf_multipole_domain_tests", routed)
            if shared_path.startswith("common/simion/"):
                self.assertIn("instrument_assembly_integration", routed)
            for project_id in (
                "rf_multipole_quadrupole",
                "rf_multipole_hexapole",
                "rf_multipole_octupole",
            ):
                self.assertIn(f"{project_id}_static", routed)

    def test_common_contracts_routes_to_declared_direct_consumers(self) -> None:
        routed = self.routed_stages("common/contracts/machine_contracts.py")
        self.assertIn("common_contracts", routed)
        self.assertIn("rf_multipole_generated_publications", routed)
        self.assertIn("instrument_assembly_integration", routed)
        for project_id in (
            "single_reflection_oa_tof_mass_analyzer",
            "rf_multipole_quadrupole",
            "rf_multipole_hexapole",
            "rf_multipole_octupole",
            "dual_cone_tandem_quadrupole_ion_interface",
            "transverse_helical_filament_wehnelt_electron_gun",
            "apertured_tube_electron_impact_ion_source",
        ):
            self.assertIn(f"{project_id}_static", routed)

    def test_common_contract_tests_do_not_route_to_runtime_consumers(self) -> None:
        routed = self.routed_stages("common/contracts/test_verify_changed.py")
        self.assertEqual(
            routed,
            {"common_contracts": routed["common_contracts"]},
        )

    def test_multipole_tests_do_not_route_to_runtime_consumers(self) -> None:
        initializer_routes = self.routed_stages("projects/rf_multipole_ion_optics/tests/__init__.py")
        self.assertTrue({"rf_multipole_domain_tests", "rf_multipole_quadrupole_static",
                         "rf_multipole_hexapole_static", "rf_multipole_octupole_static"}.issubset(initializer_routes))
        for filename in ("test_simion_geometry.py", "test_simion_rf_drive.lua",
                         "test_comsol_stationary_solver_smoke.m"):
            with self.subTest(filename=filename):
                self.assertEqual(
                    self.routed_stages(f"projects/rf_multipole_ion_optics/tests/domain/{filename}"),
                    {"rf_multipole_domain_tests": "rf_multipole_domain_tests_changed"},
                )

    def test_multipole_domain_and_shared_kernels_keep_actual_consumers(self) -> None:
        variants = {f"rf_multipole_{variant}_static" for variant in ("quadrupole", "hexapole", "octupole")}
        domain_stages = variants | {
            "rf_multipole_generated_publications", "rf_multipole_domain_tests",
        }
        for path in (
            "projects/rf_multipole_ion_optics/core/family_contract.py",
            "projects/rf_multipole_ion_optics/runtime/design_profile.py",
            "projects/rf_multipole_ion_optics/analysis/campaign_analysis.py",
            "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m",
            "projects/rf_multipole_ion_optics/simion/simion_geometry.py",
            "projects/rf_multipole_ion_optics/config/contracts/family_contract.json",
            "projects/rf_multipole_ion_optics/config/sources/rf_multipole_family_mother_sample_v1.json",
        ):
            with self.subTest(path=path):
                self.assertTrue((REPO_ROOT / path).is_file(), path)
                self.assertTrue(domain_stages <= self.routed_stages(path).keys(), path)
        resource_consumers = domain_stages | {
            "livelink_resource_stages_tests", "instrument_assembly_integration",
            "parallel_mirror_dual_stripe_mr_tof_static",
            "single_reflection_oa_tof_mass_analyzer_static",
            "dual_pressure_rectilinear_ion_processor_static",
            "dual_cone_tandem_quadrupole_ion_interface_static",
            "transverse_helical_filament_wehnelt_electron_gun_static",
        }
        self.assertTrue(resource_consumers <= self.routed_stages("common/resource_budget_support.ps1").keys())
        rf_consumers = domain_stages | {
            "simion_common", "instrument_assembly_integration",
            "dual_pressure_rectilinear_ion_processor_static",
            "dual_cone_tandem_quadrupole_ion_interface_static",
        }
        self.assertTrue(rf_consumers <= self.routed_stages("common/simion/rf_drive.lua").keys())
        serialized = json.dumps(self.route_contract)
        self.assertNotIn("common/multipole", serialized)
        self.assertNotIn("common.multipole", serialized)

    def test_domain_test_plan_avoids_production_and_freshness_stages(self) -> None:
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(CHANGED_GATE),
             "-PythonExe", sys.executable, "-PlanOnly", "-ChangedPath",
             "projects/rf_multipole_ion_optics/tests/domain/test_simion_geometry.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
        self.assertIsNotNone(selected, completed.stdout)
        domain_stages = {name for name in selected.group(1).split(",") if name.startswith("rf_multipole_")}
        self.assertEqual(domain_stages, {"rf_multipole_domain_tests"})

    def test_simion_tests_use_their_direct_test_stage(self) -> None:
        self.assertEqual(
            self.routed_stages("common/simion/test_resource_scheduler.py"),
            {"simion_common": "common_simion_changed"},
        )

    def test_livelink_tests_use_their_direct_fast_stages(self) -> None:
        self.assertEqual(
            self.routed_stages("common/comsol/test_livelink_resource_stages.py"),
            {"livelink_resource_stages_tests": "livelink_resource_tests_changed"},
        )
        for path in (
            "common/comsol/run_comsol_r2025b.ps1",
            "common/comsol/test_unclassified_support.py",
        ):
            with self.subTest(path=path):
                self.assertIn("rf_multipole_domain_tests", self.routed_stages(path))
                self.assertIn("rf_multipole_generated_publications", self.routed_stages(path))
        self.assertEqual(
            self.routed_stages("common/comsol/test_livelink_environment.ps1"),
            {"livelink_environment": "livelink_environment_test_changed"},
        )
        self.assertEqual(
            self.routed_stages(
                "common/comsol/test_livelink_failure_classification.ps1"
            ),
            {
                "livelink_failure_classification": (
                    "livelink_failure_classifier_test_changed"
                )
            },
        )

    def test_cloc_entrypoint_routes_to_its_focused_contract_tests(self) -> None:
        routed = self.routed_stages("common/report_cloc_delta.ps1")
        self.assertEqual(set(routed), {"common_contracts"})

    def test_comsol_readme_does_not_expand_mixed_changed_scope(self) -> None:
        self.assertEqual(self.routed_stages("common/comsol/README.md"), {})
        consumers = {
            "rf_multipole_generated_publications", "rf_multipole_domain_tests",
            "single_reflection_oa_tof_mass_analyzer_static", "rf_multipole_quadrupole_static",
            "rf_multipole_hexapole_static", "rf_multipole_octupole_static",
            "transverse_helical_filament_wehnelt_electron_gun_static",
        }
        for path in ("common/comsol/run_comsol_r2025b.ps1", "common/comsol/livelink_environment.ps1"):
            self.assertTrue(consumers <= self.routed_stages(path).keys(), path)
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        command = (
            f"& '{CHANGED_GATE}' -PythonExe '{sys.executable}' -PlanOnly "
            "-ChangedPath @('common/gate_catalog.json',"
            "'common/contracts/test_verify_changed.py','common/comsol/README.md')"
        )
        result = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
        self.assertIsNotNone(selected, result.stdout)
        self.assertEqual(set(selected[1].split(",")), {
            "repository_hygiene", "repository_text_bytes", "documentation",
            "development_standards", "ruff_changed_python", "common_contracts",
        })





    def test_partial_contract_coverage_keeps_uncovered_modules(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PythonExe", sys.executable,
             "-PlanOnly", "-ChangedPath", "common/contracts/test_changed_test_selection.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
        self.assertIsNotNone(selected, completed.stdout)
        self.assertIn("common_contracts", selected.group(1).split(","))

    def test_integration_changes_route_only_to_connection_gates(self) -> None:
        routed = self.routed_stages("common/integration/connection_profiles.py")
        self.assertEqual(
            set(routed),
            {
                "integration_common",
                "instrument_assembly_integration",
            },
        )
        interface_route = self.routed_stages(
            "projects/rf_multipole_ion_optics/variants/hexapole/config/interfaces/output_port.json"
        )
        self.assertNotIn("rf_multipole_to_single_reflection_oatof_integration", interface_route)

        self.assertIn("common_contracts", {route["stage"] for route in self.routes})


    def test_gate_entrypoints_run_their_contract_tests(self) -> None:
        for path in (
            "common/verify.ps1",
            "common/parallel_gate_support.ps1",
            "common/gate_catalog.json",
            "common/gate_catalog_support.ps1",
            "common/contracts/test_verify_changed.py",
            "common/verify.ps1",
            "common/require_powershell7.ps1",
            ".github/workflows/lightweight-gate.yml",
        ):
            self.assertIn("common_contracts", self.routed_stages(path))

    def test_generated_publications_have_priority_and_explicit_successors(self) -> None:
        stage_order = [route["stage"] for route in self.routes]
        freshness = stage_order.index("rf_multipole_generated_publications")
        common_contracts = stage_order.index("common_contracts")
        rf_multipole_domain_tests = stage_order.index("rf_multipole_domain_tests")
        self.assertLess(freshness, common_contracts)
        self.assertLess(freshness, rf_multipole_domain_tests)
        freshness_route = self.routes[freshness]
        self.assertEqual(
            freshness_route["command"]["parameters"],
            {"Level": "Freshness", "PythonExe": "{python}", "StructuralVariant": "All"},
        )

        self.assertEqual(
            freshness_route["repository_integration_group"], "fast"
        )
        quadrupole_route = next(
            route
            for route in self.routes
            if route["stage"] == "rf_multipole_quadrupole_static"
        )
        self.assertEqual(
            quadrupole_route["repository_integration_group"], "regression"
        )
        self.assertEqual(
            quadrupole_route["requires_stages"],
            ["rf_multipole_generated_publications"],
        )



    def test_excludes_commercial_and_formal_gate_levels(self) -> None:
        # Watching a launcher source path must select its mock regression, not
        # be confused with executing that launcher as a gate command.
        commands = [
            route[key] for route in self.routes
            for key in ("command", "repository_integration_command") if key in route
        ]
        serialized_commands = json.dumps(commands)
        for forbidden in (
            "-Level Candidate",
            "-Level Formal",
            "run_comsol_r2025b",
            "simion.exe",
        ):
            self.assertNotIn(forbidden, serialized_commands)
        for command in commands:
            level = str(command.get("parameters", {}).get("Level", "")).casefold()
            self.assertNotIn(level, {"candidate", "formal"})



    def test_parallel_scheduler_validates_temporary_cleanup_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cleanup_contract_") as directory:
            root = Path(directory)
            safe = root / "gate_fixture_safe"
            unrelated = root / "unrelated"
            safe.mkdir(); unrelated.mkdir()
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f"""
$ErrorActionPreference='Stop'
. {quote(PARALLEL_GATE_SUPPORT)}
foreach($target in @({quote(unrelated)},{quote(REPO_ROOT)})){{
 $blocked=$false
 try{{Remove-GateTemporaryDirectory -Path $target -ExpectedNamePrefix 'gate_fixture_'}}catch{{$blocked=$true}}
 if(-not$blocked){{throw 'Unowned cleanup target accepted'}}
}}
Remove-GateTemporaryDirectory -Path {quote(safe)} -ExpectedNamePrefix 'gate_fixture_'
if(Test-Path -LiteralPath {quote(safe)}){{throw 'Owned cleanup failed'}}
if(-not(Test-Path -LiteralPath {quote(unrelated)})){{throw 'Unrelated folder deleted'}}
"""
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],
                cwd=REPO_ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)




if __name__ == "__main__":
    unittest.main()
