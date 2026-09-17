"""Static contract tests for the managed finite-3D accelerator energy calibration."""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "run_accelerator_exit_energy_calibration.ps1"
)


class AcceleratorExitEnergyCalibrationRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8-sig")

    def test_runner_consumes_only_the_two_parent_manifests_and_current_contract(self) -> None:
        for token in (
            "[string]$ExactKRunManifest = ''",
            "[string]$FixedMirrorStripeRunManifest = ''",
            "[Parameter(Mandatory)][string]$AcceleratorExitRunManifest",
            "[double]$PreviousCumulativeCorrectionV = 0.0",
            "simion_candidate_two_zone.json",
            "analytic_mirror_exact_k_operating_point",
            "dual_stripe_fixed_grid_native_downstream_seed",
            "Provide exactly one operating authority manifest.",
            "accelerator_source_to_safe_exit",
        ):
            self.assertIn(token, self.source)
        self.assertNotIn("StripeSeedRunManifest", self.source)
        self.assertNotIn("FocusRunManifest", self.source)

    def test_parent_manifests_and_unique_observation_are_verified_and_frozen(self) -> None:
        for token in (
            "common.contracts.verify_run_manifest",
            "--require-status', 'success'",
            "--require-project', $projectId",
            "accelerator_exit_observation.json",
            "$observationRecords.Count -ne 1",
            "Copy-VerifiedRunInput",
            "Assert-FrozenHash",
            "parent_operating_authority_run_manifest.json",
            "parent_operating_authority_summary.json",
            "parent_accelerator_exit_run_manifest.json",
            "Test-RunFilesIdentical",
        ):
            self.assertIn(token, self.source)

    def test_runner_uses_public_compact_lifecycle_and_fails_closed(self) -> None:
        for token in (
            "New-RunPackage",
            "-RetentionClass compact",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "Complete-FailedRun",
            "artifact_capacity_gate_startup.json",
            "artifact_capacity_gate_terminal.json",
        ):
            self.assertIn(token, self.source)
        self.assertIn("(Split-Path -Parent $authorityManifest)", self.source)
        self.assertIn("(Split-Path -Parent $exitManifest)", self.source)

    def test_only_analysis_call_is_inside_the_resource_lease(self) -> None:
        self.assertEqual(
            self.source.count("Enter-HostExecutionLease -Role GATE -Stage theory_compute"),
            1,
        )
        lease_block = re.search(
            r"\$lease = \$null\s+try \{(?P<body>.*?)\}\s+finally \{",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(lease_block)
        self.assertIn("Invoke-ProjectPython -Arguments $arguments", lease_block.group("body"))
        self.assertNotIn("verify_run_manifest", lease_block.group("body"))

    def test_runner_forwards_cli_inputs_and_publishes_proposal_and_summary(self) -> None:
        for token in (
            "accelerator_exit_energy_calibration.py",
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_energy_calibration",
            "'--contract'",
            "'--exact-k-manifest'",
            "'--fixed-mirror-stripe-manifest'",
            "'--accelerator-exit-observation'",
            "'--previous-cumulative-correction-v'",
            "'--output'",
            "accelerator_exit_energy_calibration_proposal.json",
            "mrtof_accelerator_finite_3d_energy_correction_proposal",
            "mrtof_accelerator_finite_3d_energy_calibration",
            "unity_response_first_correction_only__real_simion_exit_required",
        ):
            self.assertIn(token, self.source)
        for field in (
            "target_axial_energy_per_charge_v",
            "measured_axial_hamiltonian_per_charge_v",
            "measured_minus_target_axial_energy_v",
            "correction_increment_v",
            "proposed_cumulative_correction_v",
            "required_next_action",
        ):
            self.assertIn(field, self.source)
        self.assertNotIn("SIMION 2020", self.source)
        self.assertNotIn(":refine", self.source)

    def test_powershell_parses(self) -> None:
        command = (
            "$errors=$null;$tokens=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{RUNNER}',"
            "[ref]$tokens,[ref]$errors);"
            "if($errors.Count){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            cwd=RUNNER.parents[4],
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
