"""Table-driven source contracts for lightweight MR-TOF analysis runners."""

from __future__ import annotations

import unittest
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT = Path(__file__).resolve().parents[4] / "src/msplatform/components/multi_reflection_tof"
POWERSHELL_UTF8 = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);\n"


CASES = {
    "freeze_bunch_schedule": {
        "path": "src/msplatform/workflows/resources/run_freeze_bunch_pulse_schedule.ps1",
        "session": True,
        "required": (
            "[Parameter(Mandatory)][string]$BunchSourceRunManifest",
            "[Parameter(Mandatory)][string]$StaticPilotRunManifest",
            "[Parameter(Mandatory)][ValidateRange(0.0,[double]::MaxValue)][double]$GuardUs",
            "[Nullable[double]]$PulseOffTimeUs=$null",
            "--require-mode deterministic_bunch_source_materialization",
            "Get-VerifiedOutputRecord",
            "static pilot trial receipt",
            "static pilot log",
            "Copy-VerifiedRunInput",
            "--pulse-off-time-us",
            "caller_common_envelope_verified_against_this_cohort",
            "mr_bunch_source",
            "freeze-schedule",
            "bunch_global_pulse_schedule.json",
            "solver_execution='none'",
        ),
        "forbidden": ("$GuardUs=", "simion.exe", "run_iob", "refine"),
    },
    "source_z_timing_diagnostic": {
        "path": "src/msplatform/workflows/resources/run_source_z_energy_timing_diagnostic.ps1",
        "session": True,
        "required": (
            "[Parameter(Mandatory)][string]$FlightRunPath",
            "Copy-VerifiedRunInput",
            "Apply-RunArtifactRetention",
            "source_z_energy_timing_diagnostic",
            "terminal_plane_diagnostic=$data.terminal_plane_diagnostic",
            "central_plane_focus_history=$data.central_plane_focus_history",
            "solver_execution='none'",
            "source_or_peak_filtering='none'",
            "-RetentionClass compact",
        ),
        "forbidden": ("simion.exe", "run_iob_flight", "pa:refine", "Remove-Item"),
    },
    "publish_bunch_source": {
        "path": "src/msplatform/workflows/resources/run_publish_bunch_source.ps1",
        "session": True,
        "required": (
            "[Parameter(Mandatory)][string]$SourceDefinitionPath",
            "[Parameter(Mandatory)][string]$GeometryContractPath",
            "Copy-VerifiedRunInput -Source $sourceDefinition",
            "Copy-VerifiedRunInput -Source $geometryContract",
            "--geometry-contract $frozenGeometry",
            "Apply-RunArtifactRetention",
            "bunch_source_states.csv",
            "bunch_source.fly2",
            "bunch_source_receipt.json",
            "solver_execution='none'",
        ),
        "forbidden": ("simion.exe", "run_iob", "refine"),
    },
    "single_center_timestep": {
        "path": "src/msplatform/workflows/resources/run_single_center_timestep_convergence.ps1",
        "session": True,
        "required": (
            "[ValidateCount(3,3)]",
            "msplatform.execution.manifest_verification",
            "--require-mode finite_3d_two_prism_voltage_trial",
            "Copy-VerifiedRunInput",
            "single_center_timestep_convergence",
            "acceptance_threshold=$null",
            "Apply-RunArtifactRetention",
        ),
        "forbidden": ("SIMION.exe", "refine"),
    },
    "target_operating_chain": {
        "path": "src/msplatform/workflows/resources/run_target_operating_point_chain.ps1",
        "required": (
            "run_mirror_exact_k_operating_point.ps1",
            "run_dual_stripe_operating_seed.ps1",
            "ExactKRunManifest = $exactManifest",
            "target_drift_period_ratio",
            "target_half_oscillation_count",
            "qualification = [string]$stripeSummary.qualification",
            "ContractPath",
            "refuses to overwrite",
        ),
        "forbidden": ("[double]$K", "25.5"),
    },
}


class ManagedAnalysisRunnerContractTests(unittest.TestCase):
    def test_powershell_utf8_diagnostics_override_legacy_console_encoding(self) -> None:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required")
        legacy = "[Console]::OutputEncoding=[Text.Encoding]::GetEncoding(936);"
        failure = "throw ('IDENTITY_REJECTED '+[char]0x6D4B+[char]0x8BD5)"
        for reset in (False, True):
            with self.subTest(utf8_reset=reset):
                result = subprocess.run(
                    [shell, "-NoProfile", "-NonInteractive", "-Command",
                     legacy + (POWERSHELL_UTF8 if reset else "") + failure],
                    cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=30, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                if reset:
                    self.assertIn("IDENTITY_REJECTED \u6d4b\u8bd5", result.stdout.decode("utf-8"))
                else:
                    with self.assertRaises(UnicodeDecodeError):
                        result.stdout.decode("utf-8")

    def test_source_z_diagnostic_checks_actual_flight_identity(self) -> None:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for the production identity regression")
        source = (PROJECT.parents[3] / CASES["source_z_timing_diagnostic"]["path"]).read_text(encoding="utf-8-sig")
        start = source.index("$sourceManifestData=Get-Content")
        check = source[start:source.index("$sourceObservation=", start)]
        valid = {
            "status": "success", "project": PROJECT.name,
            "mode": "finite_3d_two_prism_voltage_trial",
        }
        with TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "run_manifest.json"
            for field in (None, "new", "mixed_owner", "mixed_mode", "status", "project", "mode"):
                with self.subTest(changed_field=field):
                    document = dict(valid)
                    if field == "new":
                        document.update(project="instrument_assembly", mode="oa_mr")
                    elif field == "mixed_owner":
                        document["project"] = "instrument_assembly"
                    elif field == "mixed_mode":
                        document["mode"] = "oa_mr"
                    elif field is not None:
                        document[field] = "wrong_identity"
                    manifest.write_text(json.dumps(document), encoding="utf-8")
                    script = (
                        POWERSHELL_UTF8
                        + "Set-StrictMode -Version Latest; $ErrorActionPreference='Stop'\n"
                        + "$projectId='" + PROJECT.name + "'\n"
                        + "$sourceManifest='" + str(manifest).replace("'", "''") + "'\n"
                        + check + "Write-Output 'IDENTITY_ACCEPTED'"
                    )
                    result = subprocess.run(
                        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
                        cwd=PROJECT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        timeout=30,
                        check=False,
                    )
                    if field in (None, "new"):
                        self.assertEqual(result.returncode, 0, result.stdout)
                        self.assertEqual(result.stdout.strip(), "IDENTITY_ACCEPTED")
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn("IDENTITY_ACCEPTED", result.stdout)
                        self.assertIn(
                            "Flight source manifest has the wrong status, project, or mode.",
                            result.stdout,
                        )

    def test_default_contracts_resolve_beside_the_installed_workflow_resources(self) -> None:
        runners = (
            "run_downstream_fixed_grid_workpoint.ps1",
            "run_dual_stripe_operating_seed.ps1",
            "run_mirror_exact_k_operating_point.ps1",
            "run_native_candidate_chain.ps1",
            "run_target_operating_point_chain.ps1",
            "run_two_prism_segmented_coverage.ps1",
        )
        default = (
            "Join-Path $packageRoot "
            "'components\\multi_reflection_tof\\simion_candidate_two_zone.json'"
        )
        for runner in runners:
            with self.subTest(runner=runner):
                source = (PROJECT.parents[3] / "src/msplatform/workflows/resources" / runner).read_text(
                    encoding="utf-8-sig"
                )
                self.assertEqual(source.count(default), 1)
                self.assertNotIn("Join-Path $PSScriptRoot '..\\..\\src", source)
                if runner != "run_native_candidate_chain.ps1":
                    self.assertIn("if ($ContractPath)", source)
                if runner not in {
                    "run_downstream_fixed_grid_workpoint.ps1",
                    "run_native_candidate_chain.ps1",
                }:
                    self.assertIn("Resolve-Path -LiteralPath $ContractPath", source)

    def test_runners_require_explicit_context_and_use_isolated_installed_python(self) -> None:
        runners = [case["path"] for case in CASES.values()] + [
            "src/msplatform/workflows/resources/run_dual_stripe_operating_seed.ps1",
            "src/msplatform/workflows/resources/run_mirror_exact_k_operating_point.ps1",
            "src/msplatform/workflows/resources/run_mirror_fixed_grid_voltage_correction.ps1",
            "src/msplatform/workflows/resources/run_mirror_l0_l1_candidate.ps1",
            "src/msplatform/workflows/resources/run_two_prism_segmented_continuation.ps1",
            "src/msplatform/workflows/resources/run_two_prism_segmented_coverage.ps1",
        ]
        for runner in runners:
            with self.subTest(runner=runner):
                source = (PROJECT.parents[3] / runner).read_text(encoding="utf-8-sig")
                for parameter in ("WorkspaceRoot", "ArtifactRoot", "PythonExe"):
                    self.assertIn(f"[Parameter(Mandatory)][string]${parameter}", source)
                for forbidden in (".venv", "PYTHONPATH", "SIMULATION_PYTHON_EXE", "Get-RunPythonImportRoots"):
                    self.assertNotIn(forbidden, source)
                self.assertIn("from pathlib import Path;import msplatform", source)
                if not runner.endswith("run_target_operating_point_chain.ps1"):
                    self.assertIn("run_artifact_support.ps1", source)

    def test_real_pwsh_preflights_reject_missing_inputs_without_checkout_or_pythonpath(self) -> None:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required")
        resource_root = PROJECT.parents[3] / "src/msplatform/workflows/resources"
        arguments = {
            "run_dual_stripe_operating_seed.ps1": ["-MirrorRunManifest", "missing.json"],
            "run_mirror_exact_k_operating_point.ps1": ["-MirrorRunManifest", "missing.json"],
            "run_mirror_fixed_grid_voltage_correction.ps1": [
                "-CoarseRefinementRunPath", "missing-coarse", "-FixedGridRunPath", "missing-fixed",
            ],
            "run_mirror_l0_l1_candidate.ps1": ["-ContractPath", "missing.json"],
            "run_single_center_timestep_convergence.ps1": [
                "-RunManifestPaths", "missing-1.json,missing-2.json,missing-3.json",
            ],
            "run_source_z_energy_timing_diagnostic.ps1": ["-FlightRunPath", "missing-run"],
            "run_target_operating_point_chain.ps1": [
                "-AcceleratorComponentContractPath", "missing-oa.json",
                "-AcceleratorGeometryProfileId", "profile", "-MirrorRunManifest", "missing.json",
            ],
            "run_two_prism_segmented_continuation.ps1": [
                "-CoverageRunManifest", "missing.json", "-AngleToleranceDeg", "1",
                "-PositiveMirrorTurnYToleranceMm", "1", "-P2RootToleranceV", "1",
                "-InitialP1StepV", "1", "-MinimumP1StepV", "1", "-MaximumP1StepV", "1",
                "-P1StepGrowthFactor", "1", "-P2InitialHalfWidthV", "1",
                "-P2BracketExpansionFactor", "1", "-P2BracketMaximumExpansions", "1",
                "-MaximumInnerIterations", "1", "-MaximumOuterIterations", "1",
                "-MaximumTransportEvaluations", "1", "-MaximumNodesPerDirection", "1",
                "-RelativeTolerance", "1", "-AbsoluteTolerance", "1",
                "-MaximumStepMmPerSqrtV", "1", "-EventSamplesPerStep", "1",
                "-RootTimeToleranceMmPerSqrtV", "1", "-BoundaryRootToleranceMm", "1",
                "-MomentumToleranceSqrtV", "1", "-NormalEnergyToleranceV", "1",
                "-MaximumSteps", "1", "-StageAMaximumReducedTimeMmPerSqrtV", "1",
                "-StageBMaximumReducedTimeMmPerSqrtV", "1",
            ],
            "run_two_prism_segmented_coverage.ps1": [
                "-AcceleratorComponentContractPath", "missing-oa.json",
                "-AcceleratorGeometryProfileId", "profile", "-FixedMirrorStripeRunManifest", "missing.json",
                "-AcceleratorExitRunManifest", "missing-exit.json", "-SobolSampleCount", "1",
                "-LocalP1ValuesV", "1", "-LocalP2ValuesV", "1", "-WorkerCount", "1",
                "-RelativeTolerance", "1", "-AbsoluteTolerance", "1",
                "-MaximumStepMmPerSqrtV", "1", "-EventSamplesPerStep", "1",
                "-RootTimeToleranceMmPerSqrtV", "1", "-BoundaryRootToleranceMm", "1",
                "-MomentumToleranceSqrtV", "1", "-NormalEnergyToleranceV", "1",
                "-MaximumSteps", "1", "-StageAMaximumReducedTimeMmPerSqrtV", "1",
                "-StageBMaximumReducedTimeMmPerSqrtV", "1",
            ],
            "run_freeze_bunch_pulse_schedule.ps1": [
                "-BunchSourceRunManifest", "missing-source.json", "-StaticPilotRunManifest", "missing-pilot.json",
                "-PilotTrialReceiptPath", "missing-receipt.json", "-PilotLogPath", "missing.log",
                "-GuardUs", "0.002",
            ],
            "run_publish_bunch_source.ps1": [
                "-SourceDefinitionPath", "missing-source.json", "-GeometryContractPath", "missing-geometry.json",
                "-AcceleratorProviderReceiptPath", "missing-provider.json",
            ],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            foreign = root / "foreign/msplatform"
            foreign.mkdir(parents=True)
            (foreign / "__init__.py").write_text("raise RuntimeError('foreign PYTHONPATH loaded')\n", encoding="utf-8")
            for name, specific in arguments.items():
                with self.subTest(runner=name):
                    result = subprocess.run(
                        [
                            shell, "-NoProfile", "-NonInteractive", "-File", str(resource_root / name),
                            *specific, "-WorkspaceRoot", str(root), "-ArtifactRoot", str(root / "artifacts"),
                            "-PythonExe", sys.executable,
                        ],
                        cwd=root, env=dict(os.environ, PYTHONPATH=str(foreign.parent)),
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=30, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("foreign PYTHONPATH loaded", result.stdout + result.stderr)
                    self.assertFalse((root / "artifacts").exists())

    def test_runner_contract_matrix(self) -> None:
        for name, case in CASES.items():
            with self.subTest(case=name):
                source = (PROJECT.parents[3] / case["path"]).read_text(encoding="utf-8-sig")
                for token in case["required"]:
                    self.assertIn(token, source, token)
                if case.get("session"):
                    for token in (
                        "Enter-ArtifactWorkflowCapacitySession",
                        "Update-ArtifactWorkflowCapacitySession",
                        "Exit-ArtifactWorkflowCapacitySession",
                        "-RemainingCommittedNewBytes 0",
                    ):
                        self.assertIn(token, source, token)
                lowered = source.lower()
                for token in case["forbidden"]:
                    haystack = lowered if token.lower() == token else source
                    self.assertNotIn(token, haystack, token)

if __name__ == "__main__":
    unittest.main()
