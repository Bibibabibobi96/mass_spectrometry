from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGED_GATE = REPO_ROOT / "common" / "verify_changed.ps1"
ROUTE_TABLE = REPO_ROOT / "common" / "gate_catalog.json"
INTEGRATION_GATE = REPO_ROOT / "common" / "verify_repository_integration.ps1"
PARALLEL_GATE_SUPPORT = REPO_ROOT / "common" / "parallel_gate_support.ps1"
LIGHTWEIGHT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lightweight-gate.yml"
DOCUMENTATION_GATE = REPO_ROOT / "common" / "verify_documentation.ps1"
MULTIPOLE_GATE = (
    REPO_ROOT / "projects" / "rf_multipole_ion_optics" / "verify_project.ps1"
)


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

    def test_catalog_invoker_reads_current_native_exit_code(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        for gate in (CHANGED_GATE, INTEGRATION_GATE):
            assignment = next(
                line for line in gate.read_text(encoding="utf-8").splitlines()
                if line.startswith("$catalogCommandInvoker = ")
            )
            with self.subTest(gate=gate.name):
                script = r"""
$ErrorActionPreference='Stop'
. ./common/gate_catalog_support.ps1
$pythonProbe='__PYTHON__'
& $pythonProbe -c 'pass'
__ASSIGNMENT__
$invoke={
  param($Command)
  & $catalogCommandInvoker -Command $Command -RepoRoot $PWD.Path -PythonExe $pythonProbe
}.GetNewClosure()
& $invoke -Command ([pscustomobject]@{runner='python';arguments=@('-c','pass')})
$rejected=$false
try {
  & $invoke -Command ([pscustomobject]@{runner='python';arguments=@('-c','raise SystemExit(7)')})
} catch { $rejected=$_.Exception.Message -like '*exit code 7*' }
if(-not $rejected){throw 'Catalog accepted a failed native command'}
Write-Output 'CATALOG_FAILURE_PROPAGATION=PASS'
""".replace("__PYTHON__", sys.executable.replace("'", "''")).replace(
                    "__ASSIGNMENT__", assignment
                )
                result = subprocess.run(
                    [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                    timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("CATALOG_FAILURE_PROPAGATION=PASS", result.stdout)

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
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(CHANGED_GATE)},[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Changed gate failed PowerShell parsing'}}
$commands=@($ast.FindAll({{
 param($node)
 $node-is[Management.Automation.Language.CommandAst]-and
 $node.GetCommandName()-eq'Add-ChangedStageItem'-and
 $node.Extent.Text.Contains("'existing_python_source_changed'")
}},$true))
if($commands.Count-ne1){{throw 'Expected exactly one changed Ruff action'}}
$action=$commands[0].CommandElements[-1].ScriptBlock.GetScriptBlock()
& $action
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
        """The real stage action must not fall back to checkout/PATH discovery."""
        pwsh = shutil.which("pwsh")
        with tempfile.TemporaryDirectory(prefix="documentation_python_") as directory:
            root = Path(directory)
            (root / "common").mkdir()
            (root / "common/verify_documentation.ps1").write_text(
                "param([Parameter(Mandatory=$true)][string]$PythonExe)\n"
                "& $PythonExe -c 'import sys; print(\"DOCUMENTATION_PYTHON_VERSION=\" "
                "+ str(sys.version_info.major) + \".\" + str(sys.version_info.minor))'\n"
                "if($LASTEXITCODE-ne0){throw 'Selected Python failed'}\n",
                encoding="utf-8",
            )
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            command = r"""
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(__GATE__,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Integration gate failed PowerShell parsing'}
$assignment=$ast.Find({param($node)
  $node-is[Management.Automation.Language.AssignmentStatementAst]-and
  $node.Left.Extent.Text-eq'$stageCommands'
},$true)
$PythonExe=__PYTHON__
. ([scriptblock]::Create($assignment.Extent.Text))
. __SUPPORT__
Invoke-GateCatalogCommand -Command $stageCommands.documentation -RepoRoot __FIXTURE__ -PythonExe $PythonExe
""".replace("__GATE__", quote(INTEGRATION_GATE)).replace(
                "__FIXTURE__", quote(root)
            ).replace("__PYTHON__", quote(sys.executable)).replace(
                "__SUPPORT__", quote(REPO_ROOT / "common/gate_catalog_support.ps1"))
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, capture_output=True, text=True,
                encoding="utf-8", timeout=30, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("DOCUMENTATION_PYTHON_VERSION=3.11", completed.stdout)

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
                "-SummaryPath", self.summary_path,
            ],
            cwd=REPO_ROOT,
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

    def test_extracted_mechanisms_keep_automatic_regression_routes(self) -> None:
        for implementation, stage, module in (
            ("common/contracts/expected_values.py", "expected_values_tests",
             "common.contracts.test_expected_values"),
            ("common/analysis/longitudinal_fit.py", "longitudinal_fit_tests",
             "common.analysis.test_longitudinal_fit"),
        ):
            with self.subTest(implementation=implementation):
                self.assertIn(stage, self.routed_stages(implementation))
                route = next(row for row in self.routes if row["stage"] == stage)
                self.assertIn(route["repository_integration_group"], {"fast", "regression", "covered"})
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
        gate_route = next(row for row in self.routes if row["stage"] == "gate_contract_tests")
        self.assertIn("common.contracts.test_parallel_gate_support", gate_route["command"]["arguments"])

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
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        changed_module = (
            "integrations/tests/test_repository_bindings.py"
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
                changed_module,
                "-SummaryPath", self.summary_path,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True, encoding="utf-8",
            timeout=90,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "GATE_STAGE=RUN NAME=instrument_assembly_integration REASON=changed_test_modules",
            completed.stdout,
        )
        self.assertNotIn("INTEGRATION_GATE=PASS", completed.stdout)

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
                self.assertIn("instrument_assembly_integration", selected[1].split(","))

    @staticmethod
    def _runtime_dependency_plan(repo: Path, changed_path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-File", str(repo / "common/verify_changed.ps1"),
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
            for name in ("verify_changed.ps1", "gate_catalog_support.ps1", "parallel_gate_support.ps1",
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
        self.assertIn("instrument_assembly_integration", stages)
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
            {"Level": "Static", "PythonExe": "{python}"},
        )
        self.assertNotIn("SimionExe", json.dumps(route))

    def test_plan_mode_is_fail_closed_for_dependency_selection(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")

        def profile_for(path: str) -> str:
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(CHANGED_GATE),
                    "-PythonExe",
                    sys.executable,
                    "-ChangedPath",
                    path,
                    "-PlanOnly",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True, encoding="utf-8",
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            match = re.search(r"DEPENDENCY_PROFILE=(stdlib|locked)", completed.stdout)
            self.assertIsNotNone(match, completed.stdout)
            return match.group(1)

        self.assertEqual(profile_for("CHANGELOG.md"), "stdlib")
        for path in ("README.md", "projects/rf_multipole_ion_optics/README.md",
                     "common/contracts/README.md"):
            with self.subTest(documentation=path):
                self.assertEqual(profile_for(path), "stdlib")
        # These routes run real Ruff and nested changed-Python gates, even if
        # the author's own change is only PowerShell or workflow YAML.
        for path in ("common/gate_catalog_support.ps1", "common/verify_changed.ps1",
                     "common/contracts/test_verify_changed.py", ".github/workflows/lightweight-gate.yml"):
            with self.subTest(gate_contract_path=path):
                self.assertIn("gate_contract_tests", self.routed_stages(path))
                self.assertEqual(profile_for(path), "locked")
        self.assertEqual(profile_for("pyproject.toml"), "locked")
        self.assertEqual(profile_for("config/project_registry.json"), "locked")
        self.assertEqual(
            profile_for("projects/rf_multipole_ion_optics/config/project.json"),
            "locked",
        )

    def test_history_text_snapshots_use_only_the_documentation_fast_path(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        project = "projects/parallel_mirror_dual_stripe_mr_tof/"
        snapshot = project + "docs/history/20261015__cad-exchange/CAD.before.txt"
        cases = (
            (("common/contracts/README.md",), False, True),
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
        for paths, full_scope, documentation_only in cases:
            with self.subTest(paths=paths, full_scope=full_scope):
                quote = lambda value: "'" + value.replace("'", "''") + "'"
                command = f"& {quote(str(CHANGED_GATE))} -PythonExe {quote(sys.executable)} -PlanOnly"
                command += " -FullScope" if full_scope else " -ChangedPath @(" + ",".join(map(quote, paths)) + ")"
                completed = subprocess.run(
                    [pwsh, "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                    capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                mode = "DOCUMENTATION_ONLY" if documentation_only else "FULL_CHANGED_SCOPE"
                self.assertIn(f"EXECUTION_MODE={mode}", completed.stdout)
                if documentation_only:
                    self.assertIn(
                        "EFFECTIVE_STAGES=repository_hygiene,repository_text_bytes,documentation",
                        completed.stdout,
                    )
                    self.assertRegex(completed.stdout, r"SELECTED_STAGES=[^\r\n]*\bdocumentation\b")

    def test_ci_fallback_uses_full_scope_without_a_second_path_table(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("verify_changed.ps1", workflow)
        for option in ("-FullScope -PlanOnly -MaxConcurrency 2", "-ChangedPath $scope.changed_paths -PlanOnly -MaxConcurrency 2"):
            self.assertIn(option, workflow)
        for option in ("-FullScope -MaxConcurrency 2", "-ChangedPath @($scope.changed_paths) -MaxConcurrency 2"):
            self.assertIn(option, workflow)
        self.assertIn("dependency_profile == 'locked'", workflow)
        self.assertIn("changed_scope.json", workflow)
        self.assertNotIn("$fallbackChangedPaths", workflow)
        self.assertNotIn("projects/rf_quadrupole_ion_optics/README.md", workflow)

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
            {"gate_contract_tests": "changed_scope_contract_tests_changed"},
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
        self.assertEqual(routed, {"cloc_contract_tests": "cloc_entrypoint_changed"})

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
            "development_standards", "ruff_changed_python", "gate_contract_tests",
        })

    def test_full_scope_does_not_repeat_contract_tests(self) -> None:
        routes_by_stage = {route["stage"]: route for route in self.routes}
        for stage in ("gate_contract_tests", "cloc_contract_tests", "expected_values_tests"):
            route = routes_by_stage[stage]
            self.assertEqual(route["repository_integration_group"], "covered")
            self.assertFalse(route["run_on_full_scope"])
            self.assertEqual(route["full_scope_coverage_stage"], "common_contracts")
        self.assertIn("covered_by_", self.source)

    def test_changed_scope_reuses_selected_contract_coverage(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        cases = (
            (["common/contracts/expected_values.py"], "expected_values_tests", True),
            (["common/contracts/test_expected_values.py"], "expected_values_tests", False),
            (["common/contracts/test_verify_changed.py"], "gate_contract_tests", False),
            (["common/contracts/test_report_cloc_delta.py"], "cloc_contract_tests", True),
            (["common/contracts/file_identity.py", "pyproject.toml"], "python_dependency_contract", True),
            (["common/verify_changed.ps1"], "gate_contract_tests", False),
            (["common/report_cloc_delta.ps1"], "cloc_contract_tests", False),
            (["pyproject.toml"], "python_dependency_contract", False),
        )
        for paths, subset, covered in cases:
            with self.subTest(paths=paths):
                quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                command = (
                    f"& {quote(CHANGED_GATE)} -PythonExe {quote(sys.executable)} "
                    "-PlanOnly -ChangedPath @(" + ",".join(map(quote, paths)) + ")"
                )
                completed = subprocess.run(
                    [pwsh, "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                    capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
                self.assertIsNotNone(selected, completed.stdout)
                stages = selected.group(1).split(",")
                self.assertEqual("common_contracts" in stages, covered)
                self.assertEqual(subset in stages, not covered)

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

        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        self.assertIn("Read-GateCatalog", integration_source)
        self.assertIn("repository_integration_group -eq 'regression'", integration_source)


    def test_gate_entrypoints_run_their_contract_tests(self) -> None:
        for path in (
            "common/verify_changed.ps1",
            "common/parallel_gate_support.ps1",
            "common/gate_catalog.json",
            "common/gate_catalog_support.ps1",
            "common/contracts/test_verify_changed.py",
            "common/verify_repository_integration.ps1",
            "common/require_powershell7.ps1",
            ".github/workflows/lightweight-gate.yml",
        ):
            self.assertIn("gate_contract_tests", self.routed_stages(path))

    def test_generated_publications_fail_before_long_test_suites(self) -> None:
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

        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        fast_barrier = integration_source.index(
            "Invoke-ParallelIntegrationGroup $fastFailStages"
        )
        full_regression = integration_source.index(
            "Invoke-ParallelIntegrationGroup $fullRegressionStages"
        )
        self.assertLess(fast_barrier, full_regression)

        quadrupole_source = MULTIPOLE_GATE.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('Freshness','Core','Static','Formal')]",
            quadrupole_source,
        )
        self.assertIn("[switch]$FreshnessPrevalidated", quadrupole_source)
        self.assertIn("MULTIPOLE_FRESHNESS=PREVALIDATED", quadrupole_source)
        self.assertIn("[ValidateSet('All','quadrupole','hexapole','octupole')]", quadrupole_source)
        freshness_return = quadrupole_source.index(
            "if ($Level -eq 'Freshness')"
        )
        analysis_suite = quadrupole_source.index(
            "if ($Level -eq 'Core')"
        )
        self.assertLess(freshness_return, analysis_suite)

    def test_rf_quadrupole_uses_core_in_l1_and_static_in_l2(self) -> None:
        quadrupole_route = next(
            route
            for route in self.routes
            if route["stage"] == "rf_multipole_quadrupole_static"
        )
        self.assertEqual(
            quadrupole_route["command"]["parameters"],
            {
                "Level": "Core",
                "StructuralVariant": "quadrupole",
                "FreshnessPrevalidated": True,
                "PythonExe": "{python}",
            },
        )
        self.assertEqual(
            quadrupole_route["repository_integration_command"]["parameters"],
            {
                "Level": "Static",
                "StructuralVariant": "quadrupole",
                "FreshnessPrevalidated": True,
                "PythonExe": "{python}",
            },
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
            self.assertNotIn(forbidden, self.source)
            self.assertNotIn(forbidden, serialized_commands)
        for command in commands:
            level = str(command.get("parameters", {}).get("Level", "")).casefold()
            self.assertNotIn(level, {"candidate", "formal"})

    def test_parallel_scheduler_is_bounded_isolated_and_deterministic(self) -> None:
        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        for source in (self.source, integration_source):
            self.assertIn(
                "[ValidateRange(0, 32)][int]$MaxConcurrency = 0",
                source,
            )
            self.assertIn("parallel_gate_support.ps1", source)
            self.assertIn("Resolve-GateConcurrency", source)
        self.assertIn("PYTHONDONTWRITEBYTECODE", self.parallel_source)
        self.assertIn("RUFF_NO_CACHE", self.parallel_source)
        self.assertIn("MPLCONFIGDIR", self.parallel_source)
        self.assertIn("GATE_MATPLOTLIB_CACHE=READY", self.parallel_source)
        self.assertIn("__import__('matplotlib.font_manager')", self.parallel_source)
        self.assertIn("Start-Process", self.parallel_source)
        self.assertIn("(Get-Command pwsh).Source", self.parallel_source)
        self.assertIn("$record.Process.WaitForExit()", self.parallel_source)
        self.assertIn("GATE_PROCESS=START", self.parallel_source)
        self.assertIn("GATE_PROCESS=COMPLETE", self.parallel_source)
        self.assertIn("LOG_REPLAY=PENDING", self.parallel_source)
        self.assertIn("foreach ($item in $Items)", self.parallel_source)
        self.assertIn("missing_stage_log_serial_fallback", self.parallel_source)
        self.assertIn("& $InvokeInlineStage $item", self.parallel_source)
        self.assertIn("$failed.Add", self.parallel_source)
        self.assertIn("DIAGNOSTIC_TAIL_BEGIN", self.parallel_source)
        self.assertIn("DIAGNOSTIC_TAIL_END", self.parallel_source)
        self.assertIn("-Tail 80", self.parallel_source)

    def test_parallel_scheduler_validates_temporary_cleanup_target(self) -> None:
        self.assertIn("GetFullPath([IO.Path]::GetTempPath())", self.parallel_source)
        self.assertIn("ExpectedNamePrefix", self.parallel_source)
        self.assertIn(
            "Refusing to remove unverified gate temporary directory",
            self.parallel_source,
        )
        self.assertIn(
            "Remove-GateTemporaryDirectory -Path $groupRoot",
            self.parallel_source,
        )

    def test_documentation_is_exclusive_and_freshness_is_a_barrier(self) -> None:
        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        documentation = integration_source.index(
            "Invoke-IntegrationStage 'documentation'"
        )
        fast_group = integration_source.index(
            "Invoke-ParallelIntegrationGroup $fastFailStages"
        )
        full_group = integration_source.index(
            "Invoke-ParallelIntegrationGroup $fullRegressionStages"
        )
        self.assertLess(documentation, fast_group)
        self.assertLess(fast_group, full_group)

        changed_documentation = self.source.index(
            "Invoke-ChangedGateStage $documentation.Name"
        )
        changed_pre_barrier = self.source.index(
            "Invoke-ChangedStageGroup $preFreshnessBarrier"
        )
        changed_post_barrier = self.source.index(
            "Invoke-ChangedStageGroup $postFreshnessStages"
        )
        self.assertLess(changed_documentation, changed_pre_barrier)
        self.assertLess(changed_pre_barrier, changed_post_barrier)

if __name__ == "__main__":
    unittest.main()
