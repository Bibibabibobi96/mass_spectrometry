"""Static ownership and capability checks for the supported preparation chain."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts.build_project_registry import validate_descriptor
from common.contracts.machine_contracts import REPO_ROOT, validate_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_actual_scheduler_source_table_loads_frozen_budget_observation(self) -> None:
        source = (PROJECT_ROOT / 'workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1').read_text(encoding='utf-8')
        start = source.index('  $schedulerFiles=[ordered]@{')
        end = source.index('  foreach($key in $sourceFiles.Keys)', start)
        # Evaluate the actual owner table, never the commercial owner/task.
        script = "$ErrorActionPreference='Stop'\n" + source[start:end] + r'''
foreach($relative in $schedulerFiles.Values){
  $destination=Join-Path $env:FROZEN_DEPENDENCY_TEST_ROOT $relative
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
  Copy-Item -LiteralPath (Join-Path $env:DEPENDENCY_TEST_REPO $relative) -Destination $destination
}
Set-Location $env:FROZEN_DEPENDENCY_TEST_ROOT
. ./common/resource_budget_support.ps1
if((Get-Command New-RepositoryProcessObservation).ScriptBlock.File -ne
    (Join-Path $env:FROZEN_DEPENDENCY_TEST_ROOT 'common/resource_budget_support.ps1')){
  throw 'Observation did not load from the frozen source table'
}
$observation=New-RepositoryProcessObservation
if($null -ne $observation.usage){throw 'Unbudgeted observation created usage output'}
Write-Output 'FROZEN_BUDGET_OBSERVATION=PASS'
'''
        with tempfile.TemporaryDirectory(prefix='dual_cone_budget_closure_') as directory:
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                cwd=directory,
                env=dict(os.environ, FROZEN_DEPENDENCY_TEST_ROOT=directory,
                         DEPENDENCY_TEST_REPO=str(REPO_ROOT)),
                capture_output=True, text=True, encoding='utf-8', timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('FROZEN_BUDGET_OBSERVATION=PASS', result.stdout)

    def test_descriptor_and_execution_profiles_are_valid(self) -> None:
        descriptor_path = PROJECT_ROOT / "config/project.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        validate_descriptor(descriptor, descriptor_path, REPO_ROOT)
        profiles = json.loads(
            (PROJECT_ROOT / "config/execution_profiles.json").read_text(encoding="utf-8")
        )
        validate_schema(profiles, "execution_profiles.schema.json")
        self.assertEqual(
            {profile["mode"] for profile in profiles["profiles"]},
            {
                "axisymmetric_gas_flow_screening",
            },
        )
        self.assertTrue(
            all(profile["action"] == "run" and profile["qualification_support"] == ["none"] for profile in profiles["profiles"])
        )
        run_steps = [
            step
            for profile in profiles["profiles"]
            for step in profile["steps"]
            if step["kind"] == "run"
        ]
        self.assertEqual(len(run_steps), 1)
        self.assertTrue(all("-RunId" in step["arguments"] for step in run_steps))
        comsol_runner = (
            PROJECT_ROOT
            / "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1"
        ).read_text(encoding="utf-8")
        for token in (
            "New-RunPackage",
            "Enter-HostResourceStage -Role COMSOL -Stage prepare",
            "Enter-HostResourceStage -Role COMSOL -Stage postprocess",
            "run_comsol_r2025b.ps1",
            "& $frozen.comsol_launcher",
            "livelink_r2025b\\comsolstartup.m",
            "livelink_failure_classification.ps1",
            "livelink_environment.ps1",
            "resolve_comsol_64.ps1",
            "-RunId $RunId",
            "host_resource_scheduler.py",
            "host_resource_policy.json",
            "require_powershell7.ps1",
            "SIMULATION_PYTHON_EXE",
            "Enter-ArtifactWorkflowCapacitySession",
            "Update-ArtifactWorkflowCapacitySession",
            "Exit-ArtifactWorkflowCapacitySession",
            "-CapacityLedgerLifecycleEnabled",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "Complete-FailedRun",
            "Invoke-HostExecutionCompletionNotification",
            "$configuration.input_identity",
            "sha256=Get-RunFileSha256 -Path $frozen[$key]",
            "--science $frozen.gas_flow_science",
            "--numerics $frozen.comsol_solver_numerics",
            "--geometry $frozen.resolved_geometry",
            "Get-HostResourceBudget -Role COMSOL -Stage postprocess",
        ):
            self.assertIn(token, comsol_runner)
        self.assertNotIn("Enter-HostExecutionLease -Role COMSOL", comsol_runner)
        self.assertNotIn("Test-RunFilesIdentical", comsol_runner)
        self.assertNotIn("-PreservePaths @($field", comsol_runner)

    def test_comsol_capacity_session_uses_public_owner(self) -> None:
        source = (PROJECT_ROOT / "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1").read_text(encoding="utf-8")
        self.assertIn("-CapacityLedgerLifecycleEnabled", source)
        self.assertEqual(source.count("Enter-ArtifactWorkflowCapacitySession"), 1)
        self.assertGreaterEqual(source.count("Update-ArtifactWorkflowCapacitySession"), 1)
        self.assertEqual(source.count("Exit-ArtifactWorkflowCapacitySession"), 1)
        self.assertIn("-RemainingCommittedNewBytes 0", source)
        self.assertIn("-CommittedNewBytes 1073741824", source)
        self.assertNotIn("Invoke-ArtifactCapacityGate", source)
        self.assertNotIn("-TargetBytes", source)
        self.assertNotIn("-MinimumFreeBytes", source)

    def test_retired_python_integrator_is_not_an_active_entry(self) -> None:
        profiles = (PROJECT_ROOT / "config/execution_profiles.json").read_text(
            encoding="utf-8"
        )
        descriptor = (PROJECT_ROOT / "config/project.json").read_text(encoding="utf-8")
        self.assertNotIn("pressure_drag_screening", profiles)
        self.assertNotIn("pressure_drag_screening", descriptor)
        for relative in (
            "analysis/reduced_order_transport.py",
            "analysis/run_reduced_order_transport.py",
            "config/modes/pressure_drag_screening.json",
        ):
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
