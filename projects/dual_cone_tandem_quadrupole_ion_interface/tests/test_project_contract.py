"""Static ownership and registration checks for the COMSOL-to-SIMION chain."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.build_project_registry import validate_descriptor
from common.contracts.machine_contracts import REPO_ROOT, validate_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_prototype_leaves_c0_independent_and_limits_flight_stage(self) -> None:
        source = (PROJECT_ROOT / "workflows/gas_assisted_transport/run_gas_field_prototype.ps1").read_text(encoding="utf-8")
        c0 = source.index("'run_c0_gem_smoke.ps1'")
        prepare = source.index("$lease=Enter-HostExecutionLease")
        assembly = source.index("& $SimionExe --nogui --noprompt lua build_simion_runtime_iob.lua")
        flight = source.index("$lease=Update-HostResourceStage -Lease $lease -Stage flight")
        native_fly = source.index("$flyOutput=& $SimionExe")
        checked_exit = source.index("if($exitCode-ne 0)")
        postprocess = source.index("$lease=Update-HostResourceStage -Lease $lease -Stage postprocess")
        self.assertEqual([c0, prepare, assembly, flight, native_fly, checked_exit, postprocess],
                         sorted([c0, prepare, assembly, flight, native_fly, checked_exit, postprocess]))
        self.assertIn("-Stage prepare", source[prepare:assembly])
        self.assertLess(postprocess, source.index("$failureStage='analysis'"))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_simion_compact_retention_preserves_normal_outputs_without_exemptions(self) -> None:
        source = (PROJECT_ROOT / "workflows/gas_assisted_transport/run_gas_field_prototype.ps1").read_text(encoding="utf-8")
        block = source[source.index("  $retention=Apply-RunArtifactRetention"):
                       source.index("  $capacityTerminal=Update-ArtifactWorkflowCapacitySession")]
        self.assertNotIn("-PreservePaths", block)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "runs/20260914_170000__test__simion__compact"
            run.mkdir(parents=True)
            config = run / "run_config.json"
            config.write_text(json.dumps({
                "schema_version": 2, "run_id": run.name,
                "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            }), encoding="utf-8")
            outputs = (
                "results/trajectory_rz_projection.png", "results/terminal_plane_metrics.json",
                "results/terminal_plane_transmitted.csv", "results/prototype_run_report.json",
                "logs/simion_fly.log",
            )
            for relative in (*outputs, "simion/geometry.pa0"):
                path = run / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture\n")
            def quote(path: Path) -> str:
                return "'" + str(path).replace("'", "''") + "'"
            command = (
                f"$ErrorActionPreference='Stop';$repoRoot={quote(REPO_ROOT)};"
                f"$python={quote(Path(sys.executable))};$package=@{{run_config={quote(config)}}};"
                ". (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1');\n" + block
            )
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-Command", command],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(all((run / path).is_file() for path in outputs))
            self.assertFalse((run / "simion/geometry.pa0").exists())
            actions = json.loads((run / "retention_actions.json").read_text(encoding="utf-8"))
            self.assertEqual(actions["preserved"], [])
            self.assertEqual(actions["removed_file_count"], 1)

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
                "gas_field_driven_simion_transport",
            },
        )
        self.assertTrue(
            all(profile["evidence_levels"] == ["plan"] for profile in profiles["profiles"])
        )
        run_steps = [
            step
            for profile in profiles["profiles"]
            for step in profile["steps"]
            if step["kind"] == "run"
        ]
        self.assertEqual(len(run_steps), 2)
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

    def test_capacity_session_migration_covers_both_normal_runners(self) -> None:
        runners = {
            "comsol": (
                PROJECT_ROOT
                / "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1"
            ).read_text(encoding="utf-8"),
            "simion": (
                PROJECT_ROOT
                / "workflows/gas_assisted_transport/run_gas_field_prototype.ps1"
            ).read_text(encoding="utf-8"),
        }
        for name, source in runners.items():
            with self.subTest(name=name):
                self.assertIn("-CapacityLedgerLifecycleEnabled", source)
                self.assertEqual(source.count("Enter-ArtifactWorkflowCapacitySession"), 1)
                self.assertGreaterEqual(
                    source.count("Update-ArtifactWorkflowCapacitySession"), 1,
                )
                self.assertEqual(source.count("Exit-ArtifactWorkflowCapacitySession"), 1)
                self.assertIn("-RemainingCommittedNewBytes 0", source)
                self.assertNotIn("Invoke-ArtifactCapacityGate", source)
                self.assertNotIn("-TargetBytes", source)
                self.assertNotIn("-MinimumFreeBytes", source)
        self.assertIn("-CommittedNewBytes 1073741824", runners["comsol"])
        self.assertIn("-CommittedNewBytes 536870912", runners["simion"])
        self.assertIn("$manifestPath", runners["simion"])
        self.assertIn("$sourceGasRuntime", runners["simion"])

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
