from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    PROJECT_ROOT
    / "tests"
    / "analysis"
    / "run_rf_oatof_checkpoint_diagnostic.ps1"
)


class RfOatofCheckpointRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_source_is_explicit_verified_pulse_capture_run(self) -> None:
        self.assertIn("ParameterSetName = 'SourceRun'", self.runner)
        self.assertIn("ParameterSetName = 'SourceManifest'", self.runner)
        self.assertIn("[string]$SourceRunId", self.runner)
        self.assertIn("[string]$SourceManifest", self.runner)
        self.assertIn("[string]$DownstreamRunId", self.runner)
        self.assertGreaterEqual(self.runner.count("--require-status success"), 3)
        self.assertIn(
            "rf_to_oatof_pulse_capture_n100", self.runner
        )
        self.assertIn(
            "The source manifest must belong to the RF project artifact runs directory",
            self.runner,
        )
        self.assertIn(
            "The downstream run must belong to the RF project artifact runs directory",
            self.runner,
        )
        for binding in (
            "$downstreamManifestDocument.mode -ne 'rf_to_oatof_analyzer_transport_n100'",
            "$downstreamManifestDocument.run_id -ne $DownstreamRunId",
            "$downstreamRunConfiguration.run_id -ne $DownstreamRunId",
            "$downstreamRunConfiguration.parameters.source_run_id",
            "$sourceManifestDocument.run_id",
        ):
            self.assertIn(binding, self.runner)

    def test_manifest_covered_source_state_and_frozen_contracts_are_copied(self) -> None:
        required_source_roles = (
            "$sourceRunConfiguration.inputs.particle_source",
            "$sourceRunConfiguration.inputs.pulse_schedule",
            "$sourceRunConfiguration.inputs.resolved_connection",
            "$sourceRunConfiguration.inputs.shared_physical_port_joint_geometry",
            "$sourceRunConfiguration.inputs.oatof_baseline",
            "$sourceRunConfiguration.inputs.rf_resolved_geometry",
            "$sourceRunConfiguration.inputs.timing_state",
            "pulse_capture_pulse_left_limit_state.csv",
            "pulse_capture_particle_terminal_census.csv",
            "pulse_capture_local_accelerator_exit.csv",
            "$downstreamRunConfiguration.inputs.row_map",
            "results\\simion_downstream_particles.csv",
        )
        for role in required_source_roles:
            self.assertIn(role, self.runner)
        self.assertIn("$manifestInputPaths -notcontains", self.runner)
        self.assertIn("$manifestOutputPaths -notcontains", self.runner)
        self.assertIn("source_pulse_capture_run_manifest.json", self.runner)
        self.assertIn("source_pulse_capture_run_config.json", self.runner)
        self.assertIn("downstream_run_manifest.json", self.runner)
        self.assertIn("downstream_run_config.json", self.runner)
        self.assertIn("$downstreamManifestOutputPaths -notcontains", self.runner)
        for frozen in (
            "pre_pulse_interface_entry_state.csv",
            "pulse_capture_local_accelerator_exit.csv",
            "simion_row_map.csv",
            "simion_downstream_particles.csv",
            "resolved_design_official.json",
        ):
            self.assertIn(frozen, self.runner)
        self.assertIn("plot_shared_pulse_geometry_snapshot.py", self.runner)
        self.assertIn("snapshot_analysis = $snapshotAnalysis", self.runner)
        self.assertIn("Copy-CheckpointInput", self.runner)
        self.assertIn("Get-FileHash -LiteralPath $Destination", self.runner)
        self.assertIn(
            "$sourceRunConfiguration.inputs.resolved_connection", self.runner
        )

    def test_runner_calls_existing_analysis_and_freezes_all_outputs(self) -> None:
        for argument in (
            "--exit-state $sourceExit",
            "--capture-state $capture",
            "--terminal-census $terminal",
            "--interface-entry-state $interfaceEntry",
            "--local-exit-state $localExit",
            "--downstream-row-map $downstreamRowMap",
            "--downstream-state $downstreamState",
            "--pulse-schedule $pulseSchedule",
            "--oatof-baseline $oatofBaseline",
            "--resolved-connection $resolvedConnection",
            "--rf-resolved-geometry $rfResolvedGeometry",
            "--joint-contract $jointContract",
            "--contract $contract",
            "--metrics $metrics",
            "--particles $particles",
            "--figure $figure",
        ):
            self.assertIn(argument, self.runner)
        self.assertIn("rf-oatof-checkpoints__metrics.json", self.runner)
        self.assertIn("rf-oatof-checkpoints__particles.csv", self.runner)
        self.assertIn("rf-oatof-checkpoints__state-comparison.png", self.runner)
        self.assertIn("$analysisLog", self.runner)
        self.assertIn("-Outputs $outputs", self.runner)
        self.assertIn("exclusive_particle_outcomes.denominator", self.runner)
        self.assertIn(
            "exclusive_particle_outcomes.classes_are_mutually_exclusive_and_exhaustive",
            self.runner,
        )
        self.assertIn("stage_membership.detector_hit", self.runner)

    def test_lifecycle_is_verified_and_never_promotes_stage(self) -> None:
        self.assertIn("[string]$PythonExe", self.runner)
        self.assertIn(
            "common\\contracts\\run_artifact_support.ps1", self.runner
        )
        self.assertIn("New-RunPackage -Python $python", self.runner)
        self.assertGreaterEqual(
            self.runner.count("Write-VerifiedRunManifest"), 2
        )
        self.assertIn("Complete-FailedRun", self.runner)
        self.assertIn("--require-status failed", self.runner)
        self.assertIn("diagnostic_only = $true", self.runner)
        self.assertIn("pulse_capture_stage_passed = $false", self.runner)
        self.assertIn("formal_gate_passed = $false", self.runner)
        self.assertIn("solver_rerun = $false", self.runner)
        self.assertIn("STATUS=PASS RUN_ID={0} SOURCE_RUN_ID={1}", self.runner)
        self.assertNotIn("' +\n    'PULSE_CAPTURE_STAGE_PASS", self.runner)
        for commercial_entry in (
            "run_comsol_r2025b.ps1",
            "SIMION-2020",
            "simion.exe",
            "matlab.exe",
        ):
            self.assertNotIn(commercial_entry, self.runner)


if __name__ == "__main__":
    unittest.main()
