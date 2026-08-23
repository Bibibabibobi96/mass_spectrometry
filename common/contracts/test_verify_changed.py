from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGED_GATE = REPO_ROOT / "common" / "verify_changed.ps1"
ROUTE_TABLE = REPO_ROOT / "common" / "gate_catalog.json"
INTEGRATION_GATE = REPO_ROOT / "common" / "verify_repository_integration.ps1"
PARALLEL_GATE_SUPPORT = REPO_ROOT / "common" / "parallel_gate_support.ps1"
LIGHTWEIGHT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lightweight-gate.yml"
QUADRUPOLE_GATE = (
    REPO_ROOT / "projects" / "rf_quadrupole_ion_optics" / "verify_project.ps1"
)


class ChangedGateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CHANGED_GATE.read_text(encoding="utf-8")
        cls.parallel_source = PARALLEL_GATE_SUPPORT.read_text(encoding="utf-8")
        cls.route_contract = json.loads(ROUTE_TABLE.read_text(encoding="utf-8"))
        cls.routes = cls.route_contract["routes"]

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

    def test_accepts_explicit_paths_and_discovers_worktree_changes(self) -> None:
        self.assertIn("[string[]]$ChangedPath", self.source)
        self.assertIn("[switch]$FullScope", self.source)
        self.assertIn("FullScope and ChangedPath are mutually exclusive", self.source)
        self.assertIn("git -C $repoRoot diff --name-only", self.source)
        self.assertIn("git -C $repoRoot ls-files --others --exclude-standard", self.source)
        self.assertIn("ChangedPath must be inside repository", self.source)
        self.assertIn("Changed-files gate cannot determine Git HEAD", self.source)
        self.assertIn("CHANGED_GATE_INPUT_SOURCE", self.source)
        self.assertIn("gate_catalog_support.ps1", self.source)
        self.assertIn("Read-GateCatalog", self.source)
        self.assertIn("FULL_SCOPE", self.source)

    def test_reports_run_skip_reasons_and_elapsed_time(self) -> None:
        self.assertIn("GATE_STAGE=RUN", self.source)
        self.assertIn("GATE_STAGE=SKIP", self.source)
        self.assertIn("ELAPSED_SECONDS", self.source)
        self.assertIn("repository_hygiene' 'always", self.source)

    def test_documentation_only_fast_path_is_narrow_and_explicit(self) -> None:
        self.assertIn("$isDocumentationOnly", self.source)
        self.assertIn("GetExtension($_).ToLowerInvariant() -ne '.md'", self.source)
        self.assertIn("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY", self.source)
        parallel_gate = self.source.index(
            "Invoke-ChangedStageGroup $preFreshnessBarrier"
        )
        documentation_gate = self.source.index(
            "Invoke-ChangedGateStage $documentation.Name"
        )
        fast_path = self.source.index("if ($isDocumentationOnly)", documentation_gate)
        self.assertLess(documentation_gate, fast_path)
        self.assertLess(fast_path, parallel_gate)

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
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("GATE_STAGE=RUN NAME=documentation", completed.stdout)
        self.assertIn("GATE_STAGE=RUN NAME=repository_text_bytes", completed.stdout)
        self.assertLess(
            completed.stdout.index("GATE_STAGE=RUN NAME=repository_text_bytes"),
            completed.stdout.index("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY"),
        )
        self.assertIn("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY", completed.stdout)
        self.assertNotIn("GATE_STAGE=RUN NAME=multipole_common", completed.stdout)
        self.assertNotIn(
            "GATE_STAGE=RUN NAME=rf_quadrupole_ion_optics_static",
            completed.stdout,
        )

    def test_deleted_python_paths_select_scope_but_are_not_passed_to_ruff(self) -> None:
        self.assertIn("$changedPython =", self.source)
        self.assertIn("$existingPythonFiles =", self.source)
        self.assertIn("Test-Path -LiteralPath $_ -PathType Leaf", self.source)
        self.assertIn("$existingPythonFiles.Count -gt 0", self.source)
        self.assertIn("@existingPythonFiles", self.source)
        self.assertIn("only_deleted_python_paths_changed", self.source)
        self.assertNotIn("@pythonFiles", self.source)

    def test_internal_route_closure_carries_its_command_invoker(self) -> None:
        self.assertIn(
            "$catalogCommandInvoker = "
            "${function:Invoke-GateCatalogCommand}.GetNewClosure()",
            self.source,
        )
        self.assertIn("$routeCommandInvoker = {", self.source)
        self.assertIn("& $catalogCommandInvoker -Command $Command", self.source)
        self.assertIn("}.GetNewClosure()", self.source)
        self.assertIn("& $routeCommandInvoker -Command $command", self.source)

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
            for path in (REPO_ROOT / "integrations").glob(
                "*/verify_integration.ps1"
            )
        )
        routed_integrations = sorted(
            route["command"]["script"]
            for route in self.routes
            if route["command"].get("script", "").startswith("integrations/")
        )
        self.assertEqual(routed_integrations, integration_gates)

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
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            match = re.search(r"DEPENDENCY_PROFILE=(stdlib|locked)", completed.stdout)
            self.assertIsNotNone(match, completed.stdout)
            return match.group(1)

        self.assertEqual(profile_for("CHANGELOG.md"), "stdlib")
        self.assertEqual(profile_for("common/gate_catalog_support.ps1"), "stdlib")
        self.assertEqual(profile_for("pyproject.toml"), "locked")
        self.assertEqual(profile_for("config/project_registry.json"), "locked")
        self.assertEqual(
            profile_for("projects/rf_hexapole_ion_optics/config/project.json"),
            "locked",
        )

    def test_plan_mode_reports_documentation_fast_path_effective_stages(self) -> None:
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
                "common/contracts/README.md",
                "-PlanOnly",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("EXECUTION_MODE=DOCUMENTATION_ONLY", completed.stdout)
        self.assertIn(
            "EFFECTIVE_STAGES=repository_hygiene,repository_text_bytes,documentation",
            completed.stdout,
        )

    def test_ci_fallback_uses_full_scope_without_a_second_path_table(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("verify_changed.ps1", workflow)
        self.assertEqual(workflow.count("-FullScope"), 2)
        self.assertEqual(workflow.count("-MaxConcurrency 2"), 5)
        self.assertEqual(workflow.count("-PlanOnly"), 2)
        self.assertIn("dependency_profile == 'locked'", workflow)
        self.assertIn("changed_scope.json", workflow)
        self.assertNotIn("$fallbackChangedPaths", workflow)
        self.assertNotIn("projects/rf_quadrupole_ion_optics/README.md", workflow)

    def test_shared_dependencies_route_to_actual_consumers(self) -> None:
        multipole = self.routed_stages("common/multipole/simion_particle_source.py")
        self.assertTrue(
            {
                "multipole_common",
                "multipole_foundation",
                "rf_multipole_to_single_reflection_oatof_integration",
                "rf_quadrupole_generated_publications",
                "rf_quadrupole_ion_optics_static",
                "rf_hexapole_ion_optics_static",
                "rf_octupole_ion_optics_static",
            }.issubset(multipole)
        )
        self.assertNotIn("single_reflection_oa_tof_mass_analyzer_static", multipole)

        for shared_path in (
            "common/simion/particle_source.py",
            "common/comsol/create_multipole_round_rods.m",
        ):
            routed = self.routed_stages(shared_path)
            self.assertIn("multipole_common", routed)
            self.assertIn("multipole_foundation", routed)
            self.assertIn(
                "rf_multipole_to_single_reflection_oatof_integration", routed
            )
            for project_id in (
                "rf_quadrupole_ion_optics",
                "rf_hexapole_ion_optics",
                "rf_octupole_ion_optics",
            ):
                self.assertIn(f"{project_id}_static", routed)

    def test_common_contracts_routes_to_declared_direct_consumers(self) -> None:
        routed = self.routed_stages("common/contracts/machine_contracts.py")
        self.assertIn("common_contracts", routed)
        self.assertIn("rf_quadrupole_generated_publications", routed)
        self.assertIn("rf_multipole_to_single_reflection_oatof_integration", routed)
        for project_id in (
            "single_reflection_oa_tof_mass_analyzer",
            "rf_quadrupole_ion_optics",
            "rf_hexapole_ion_optics",
            "rf_octupole_ion_optics",
            "transverse_helical_filament_wehnelt_electron_gun",
            "apertured_tube_electron_impact_ion_source",
        ):
            self.assertIn(f"{project_id}_static", routed)

    def test_cloc_entrypoint_routes_to_its_focused_contract_tests(self) -> None:
        routed = self.routed_stages("common/report_cloc_delta.ps1")
        self.assertEqual(routed, {"cloc_contract_tests": "cloc_entrypoint_changed"})

    def test_full_scope_does_not_repeat_contract_tests(self) -> None:
        routes_by_stage = {route["stage"]: route for route in self.routes}
        for stage in ("gate_contract_tests", "cloc_contract_tests"):
            route = routes_by_stage[stage]
            self.assertFalse(route["run_on_full_scope"])
            self.assertEqual(route["full_scope_coverage_stage"], "common_contracts")
        self.assertIn("covered_by_", self.source)

    def test_integration_changes_route_only_to_connection_gates(self) -> None:
        routed = self.routed_stages("common/integration/connection_profiles.py")
        self.assertEqual(
            set(routed),
            {
                "integration_common",
                "rf_multipole_to_single_reflection_oatof_integration",
            },
        )
        interface_route = self.routed_stages(
            "projects/rf_hexapole_ion_optics/config/interfaces/output_port.json"
        )
        self.assertIn(
            "rf_multipole_to_single_reflection_oatof_integration",
            interface_route,
        )

        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        self.assertIn("Read-GateCatalog", integration_source)
        self.assertIn("repository_integration_group -eq 'regression'", integration_source)

    def test_handoff_publisher_routes_only_its_direct_integration_consumer(
        self,
    ) -> None:
        routed = self.routed_stages(
            "common/multipole/publish_three_mode_binding.py"
        )
        self.assertIn(
            "rf_multipole_to_single_reflection_oatof_integration",
            routed,
        )
        self.assertNotIn("single_reflection_oa_tof_mass_analyzer_static", routed)

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
        freshness = stage_order.index("rf_quadrupole_generated_publications")
        common_contracts = stage_order.index("common_contracts")
        multipole_common = stage_order.index("multipole_common")
        self.assertLess(freshness, common_contracts)
        self.assertLess(freshness, multipole_common)
        freshness_route = self.routes[freshness]
        self.assertEqual(
            freshness_route["command"]["parameters"],
            {"Level": "Freshness", "PythonExe": "{python}"},
        )

        self.assertEqual(
            freshness_route["repository_integration_group"], "fast"
        )
        quadrupole_route = next(
            route
            for route in self.routes
            if route.get("project_id") == "rf_quadrupole_ion_optics"
        )
        self.assertEqual(
            quadrupole_route["repository_integration_group"], "regression"
        )
        self.assertEqual(
            quadrupole_route["requires_stages"],
            ["rf_quadrupole_generated_publications"],
        )

        integration_source = INTEGRATION_GATE.read_text(encoding="utf-8")
        fast_barrier = integration_source.index(
            "Invoke-ParallelIntegrationGroup $fastFailStages"
        )
        full_regression = integration_source.index(
            "Invoke-ParallelIntegrationGroup $fullRegressionStages"
        )
        self.assertLess(fast_barrier, full_regression)

        quadrupole_source = QUADRUPOLE_GATE.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('Freshness','Core','Static','Formal')]",
            quadrupole_source,
        )
        self.assertIn("[switch]$FreshnessPrevalidated", quadrupole_source)
        self.assertIn("QUADRUPOLE_FRESHNESS=PREVALIDATED", quadrupole_source)
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
            if route.get("project_id") == "rf_quadrupole_ion_optics"
        )
        self.assertEqual(
            quadrupole_route["command"]["parameters"],
            {
                "Level": "Core",
                "FreshnessPrevalidated": True,
                "PythonExe": "{python}",
            },
        )
        self.assertEqual(
            quadrupole_route["repository_integration_command"]["parameters"],
            {
                "Level": "Static",
                "FreshnessPrevalidated": True,
                "PythonExe": "{python}",
            },
        )

    def test_excludes_commercial_and_formal_gate_levels(self) -> None:
        serialized_routes = json.dumps(self.route_contract)
        for forbidden in (
            "-Level Candidate",
            "-Level Formal",
            "run_comsol_r2025b",
            "simion.exe",
        ):
            self.assertNotIn(forbidden, self.source)
            self.assertNotIn(forbidden, serialized_routes)

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
