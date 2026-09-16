"""Static contract tests for the one-ion accelerator-exit runner."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_accelerator_exit_flight.ps1"


class AcceleratorExitRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8-sig")

    def test_runner_is_a_new_fixed_input_exit_mode(self) -> None:
        for token in (
            "CalibratedFocusRunPath",
            "accelerator_source_to_safe_exit",
            "two_zone_accelerator_first_time_focus",
            "source_to_accelerator_exit_diagnostic_only",
            "particle_count=1",
            "source_direction_project='+y'",
            "source_slow_kinetic_energy_per_charge_v",
            "validate_positive_particle_count",
        ):
            self.assertIn(token, self.source)
        for forbidden in (
            "AcceleratorFamilyRunPath",
            "FirstGapDropV",
            "compose_standalone_pa",
            "fast_adjust",
            ":refine",
            "integration",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_runner_consumes_only_manifest_bound_standalone_pas(self) -> None:
        for key in (
            "standalone_analyzer_pa",
            "standalone_accelerator_pa",
            "standalone_detector_pa",
            "baseline_contract",
            "trial_contract",
            "reviewed_contract",
            "operating_point",
            "voltage_map",
            "resolved_iob_pose",
        ):
            self.assertIn(f"Get-PublishedFocusInput '{key}'", self.source)
        for key in (
            "standalone_analyzer_pa",
            "standalone_accelerator_pa",
            "standalone_detector_pa",
            "operating_point",
            "voltage_map",
            "resolved_iob_pose",
            "focus_operating_point_materialization",
        ):
            self.assertIn(
                f"Get-PublishedFocusInput '{key}' -RequirePublishedOutput",
                self.source,
            )
        for key in ("baseline_contract", "trial_contract", "reviewed_contract"):
            self.assertNotIn(
                f"Get-PublishedFocusInput '{key}' -RequirePublishedOutput",
                self.source,
            )
        self.assertIn("direct standalone .pa inputs only", self.source)
        self.assertIn("Assert-FileIdentity", self.source)
        self.assertIn("PA before flight", self.source)
        self.assertIn("PA after flight", self.source)
        self.assertIn("upstream PA after flight", self.source)

    def test_runner_uses_short_execution_alias_and_leaves_reviewable_iob(self) -> None:
        for token in (
            "short_pa_path_support.ps1",
            "-UseShortExecutionPath",
            "New-ShortPaCopy",
            "Remove-ShortPaCopyDirectory",
            "build_three_component_iob.lua",
            "read_only_voltageized",
            "Remove-IobSeedPlaceholderCompanions",
            "mrtof_accelerator_exit.iob",
            '"iob_input_$name.pa"',
            "IOB=$(Get-ArtifactPath $iob)",
        ):
            self.assertIn(token, self.source)

    def test_runner_freezes_source_field_grid_geometry_and_numerics(self) -> None:
        for token in (
            "accelerator_exit_simion_analysis.py",
            "'materialize'",
            "'analyze'",
            "field_and_grid_identity",
            "geometry_identity",
            "numerics_identity",
            "trajectory_profile_id",
            "trajectory_quality",
            "maximum_step_us",
            "full_path_timeout_us",
            "load_operating_point",
            "spec_from_file_location",
            "drift_kinetic_energy_ev",
            "voltage_trial_sha256",
            "source_fly2_sha256",
            "refine_performed=$false",
        ):
            self.assertIn(token, self.source)
        self.assertNotIn("source_slow_kinetic_energy_per_charge_v-ne5.0", self.source)

    def test_runner_freezes_direct_analysis_dependencies_and_optional_calibration(self) -> None:
        for token in (
            "two_prism_simion_trial.py",
            "simion_event_analysis.py",
            "simion_candidate_reference.py",
            "accelerator_focus_voltage_trial.py",
            "particle_physics.py",
            "Test-RunFilesIdentical",
            "parser_matches_upstream_focus",
        ):
            self.assertIn(token, self.source)
        self.assertIn("if($null-ne$calibrationEvidenceRecord)", self.source)
        self.assertNotIn("Get-PublishedFocusInput 'focus_calibration_manifest'", self.source)

    def test_runner_uses_public_lifecycle_and_stage_boundaries(self) -> None:
        for token in (
            "New-RunPackage",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "Complete-FailedRun",
            "Enter-HostExecutionLease -Role SIMION -Stage prepare",
            "Update-HostResourceStage -Lease $lease -Stage flight",
            "Update-HostResourceStage -Lease $lease -Stage postprocess",
            "run_iob_flight.lua",
        ):
            self.assertIn(token, self.source)
        self.assertLess(self.source.index("-Stage prepare"), self.source.index("-Stage flight"))
        self.assertLess(self.source.index("-Stage flight"), self.source.index("-Stage postprocess"))

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
