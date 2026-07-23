import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parent / "run_simion_finite_3d_transport.ps1"


class SimionRunnerContractTests(unittest.TestCase):
    def test_build_and_fly_are_serialized_without_nested_command_reentry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Start-Process -FilePath $simion", source)
        self.assertIn("Start-Sleep -Milliseconds 500", source)
        self.assertIn("'--nogui','--noprompt','fly'", source)
        self.assertNotIn("simion_run_fly.lua", source)

    def test_validator_console_output_cannot_pollute_case_return_value(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("--solver 'SIMION 2020' --output $stateReport | Out-Null", source)

    def test_axial_mode_keeps_rf_on_in_both_paired_cases(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Invoke-TransportCase 'axial_acceleration_rf_on' 1 1", source)
        self.assertIn("Invoke-TransportCase 'zero_axial_drop_rf_on' 1 0", source)
        self.assertIn("--segmented-rods", source)


if __name__ == "__main__":
    unittest.main()
