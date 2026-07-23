import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parent / "run_simion_finite_3d_transport.ps1"
REPO_ROOT = Path(__file__).parents[2]


class SimionRunnerContractTests(unittest.TestCase):
    def test_build_and_fly_are_serialized_without_nested_command_reentry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Start-Process -FilePath $simion", source)
        self.assertIn("Start-Sleep -Milliseconds 500", source)
        self.assertIn("'--nogui','--noprompt','fly'", source)
        self.assertNotIn("simion_run_fly.lua", source)
        self.assertFalse((RUNNER.parent / "simion_run_fly.lua").exists())
        self.assertFalse(
            (
                REPO_ROOT
                / "projects/rf_quadrupole_collision_cooling/tests/simion/run_fly.lua"
            ).exists()
        )

    def test_validator_console_output_cannot_pollute_case_return_value(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("--solver 'SIMION 2020' --output $stateReport | Out-Null", source)

    def test_axial_mode_keeps_rf_on_in_both_paired_cases(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Invoke-TransportCase 'axial_acceleration_rf_on' 1 1", source)
        self.assertIn("Invoke-TransportCase 'zero_axial_drop_rf_on' 1 0", source)
        self.assertIn("--segmented-rods", source)

    def test_quadrupole_uses_the_shared_adapter_without_field_screen(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[ValidateSet('high-order','quadrupole')][string]$Adapter", source)
        self.assertIn("common.multipole.prepare_quadrupole_finite_3d_inputs", source)
        self.assertIn("[string]$ParticleTablePath", source)
        self.assertIn("if($Adapter -eq 'high-order')", source)

    def test_tool_paths_are_parameters_not_absolute_literals(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$SimionExe", source)
        self.assertIn("[string]$TemplateIob", source)
        self.assertIn("[string]$AxialAccelerationContractPath", source)
        self.assertNotIn("C:\\Program Files\\SIMION-2020", source)

    def test_exception_path_closes_failed_manifest(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Complete-FailedRun", source)

    def test_detector_surface_comparison_uses_cell_scaled_numerical_tolerance(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$surfaceToleranceMm=[Math]::Max(1e-6*$CellMm,1e-9)", source)
        self.assertIn("-$CellMm-$surfaceToleranceMm", source)
        self.assertNotIn("-$CellMm-0.001", source)

    def test_failed_acceleration_analysis_is_not_masked_by_missing_metrics(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        failure = source.index("SIMION axial-acceleration functional analysis failed.")
        read = source.index("$metricsDoc=Get-Content", failure)
        self.assertLess(failure, read)

    def test_quadrupole_project_runner_retains_only_specialized_modes(self) -> None:
        source = (
            REPO_ROOT
            / "projects/rf_quadrupole_collision_cooling/tests/simion/run_transport_candidate.ps1"
        ).read_text(encoding="utf-8")
        self.assertNotIn("[ValidateSet('transport_no_collision'", source)
        self.assertNotIn("'axial_acceleration_reference'", source)
        self.assertNotIn("'endplate_acceleration_reference'", source)
        self.assertIn("'transport_interface_readiness'", source)
        self.assertIn("'mass_filter_reference'", source)


if __name__ == "__main__":
    unittest.main()
