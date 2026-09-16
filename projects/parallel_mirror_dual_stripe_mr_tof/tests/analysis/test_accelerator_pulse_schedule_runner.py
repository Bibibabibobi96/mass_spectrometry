from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis" / "run_freeze_accelerator_pulse_schedule.ps1"
)


class AcceleratorPulseScheduleRunnerTest(unittest.TestCase):
    def test_runner_freezes_a_manifest_bound_diagnostic_schedule(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "CenterRunManifest",
            "finite_3d_two_prism_voltage_trial",
            "accelerator_global_pulse_schedule_freeze",
            "Copy-VerifiedRunInput",
            "freeze-pulse-schedule",
            "ion_time_of_flight_us_from_common_tob_zero_release",
            "pending_multi_particle_safe_exit_envelope",
            "Write-VerifiedRunManifest",
        ):
            self.assertIn(token, source)
        self.assertNotIn("AcceleratorPulseOffTimeUs", source)
        self.assertNotIn("SIMION-2020", source)


if __name__ == "__main__":
    unittest.main()
