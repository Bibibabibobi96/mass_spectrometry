from __future__ import annotations

from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT / "analysis" / "run_freeze_bunch_pulse_schedule.ps1"


class FreezeBunchPulseScheduleRunnerTests(unittest.TestCase):
    def test_runner_requires_guard_and_binds_both_verified_parent_runs(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$BunchSourceRunManifest", source)
        self.assertIn("[Parameter(Mandatory)][string]$StaticPilotRunManifest", source)
        self.assertIn("[Parameter(Mandatory)][ValidateRange(0.0,[double]::MaxValue)][double]$GuardUs", source)
        self.assertNotIn("$GuardUs=", source)
        self.assertIn("--require-mode deterministic_bunch_source_materialization", source)
        self.assertIn("Get-VerifiedOutputRecord", source)
        self.assertIn("static pilot trial receipt", source)
        self.assertIn("static pilot log", source)
        self.assertIn("Copy-VerifiedRunInput", source)

    def test_runner_reuses_schedule_core_and_never_runs_simion(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("bunch_source_and_schedule", source)
        self.assertIn("freeze-schedule", source)
        self.assertIn("bunch_global_pulse_schedule.json", source)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertIn("solver_execution='none'", source)
        self.assertNotIn("simion.exe", source.lower())
        self.assertNotIn("run_iob", source.lower())
        self.assertNotIn("refine", source.lower())


if __name__ == "__main__":
    unittest.main()
