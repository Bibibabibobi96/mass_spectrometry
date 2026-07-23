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

    def test_source_is_explicit_verified_s3_pulse_capture_run(self) -> None:
        self.assertIn("ParameterSetName = 'SourceRun'", self.runner)
        self.assertIn("ParameterSetName = 'SourceManifest'", self.runner)
        self.assertIn("[string]$SourceRunId", self.runner)
        self.assertIn("[string]$SourceManifest", self.runner)
        self.assertGreaterEqual(self.runner.count("--require-status success"), 2)
        self.assertIn(
            "rf_to_oatof_s3_shared_clock_pulse_capture_n100", self.runner
        )
        self.assertIn(
            "The source manifest must belong to the RF project artifact runs directory",
            self.runner,
        )

    def test_manifest_covered_source_state_and_frozen_contracts_are_copied(self) -> None:
        required_source_roles = (
            "$sourceRunConfiguration.inputs.particle_source",
            "$sourceRunConfiguration.inputs.pulse_schedule",
            "$sourceRunConfiguration.inputs.s2_contract",
            "$sourceRunConfiguration.inputs.shared_physical_port_joint_geometry",
            "$sourceRunConfiguration.inputs.oatof_baseline",
            "s3_pulse_left_limit_state.csv",
            "s3_particle_terminal_census.csv",
        )
        for role in required_source_roles:
            self.assertIn(role, self.runner)
        self.assertIn("$manifestInputPaths -notcontains", self.runner)
        self.assertIn("$manifestOutputPaths -notcontains", self.runner)
        self.assertIn("source_s3_run_manifest.json", self.runner)
        self.assertIn("source_s3_run_config.json", self.runner)
        self.assertIn("plot_shared_pulse_geometry_snapshot.py", self.runner)
        self.assertIn("snapshot_analysis = $snapshotAnalysis", self.runner)
        self.assertIn("Copy-CheckpointInput", self.runner)
        self.assertIn("Get-FileHash -LiteralPath $Destination", self.runner)
        self.assertNotIn(
            "config\\rf_to_oatof_s2_passive_connector.json", self.runner
        )

    def test_runner_calls_existing_analysis_and_freezes_all_outputs(self) -> None:
        for argument in (
            "--exit-state $sourceExit",
            "--capture-state $capture",
            "--terminal-census $terminal",
            "--pulse-schedule $pulseSchedule",
            "--oatof-baseline $oatofBaseline",
            "--s2-contract $s2Contract",
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

    def test_lifecycle_is_verified_and_never_promotes_stage(self) -> None:
        self.assertGreaterEqual(
            self.runner.count("Write-VerifiedRunManifest"), 2
        )
        self.assertIn("Complete-RfFailedRun", self.runner)
        self.assertIn("--require-status failed", self.runner)
        self.assertIn("diagnostic_only = $true", self.runner)
        self.assertIn("s3_stage_passed = $false", self.runner)
        self.assertIn("formal_gate_passed = $false", self.runner)
        self.assertIn("solver_rerun = $false", self.runner)
        self.assertIn("STATUS=PASS RUN_ID={0} SOURCE_RUN_ID={1}", self.runner)
        self.assertNotIn("' +\n    'S3_STAGE_PASS", self.runner)
        for commercial_entry in (
            "run_comsol_r2025b.ps1",
            "SIMION-2020",
            "simion.exe",
            "matlab.exe",
        ):
            self.assertNotIn(commercial_entry, self.runner)


if __name__ == "__main__":
    unittest.main()
