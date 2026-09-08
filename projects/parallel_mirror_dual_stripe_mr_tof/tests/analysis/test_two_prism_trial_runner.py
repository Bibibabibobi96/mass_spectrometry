from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"


class TwoPrismTrialRunnerTest(unittest.TestCase):
    def test_downstream_trials_reuse_pa_and_protect_the_fly2(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Stripe1VoltageV",
            "Stripe2VoltageV",
            "ContinueMainDrift",
            "read_only_voltageized",
            "temporary_voltageized_analyzer__immutable_family",
            "downstream_trial_source.input.fly2",
            "Test-RunFilesIdentical",
            "build_three_component_iob.lua",
        ):
            self.assertIn(token, source)
        self.assertIn("voltageize_analyzer_pa0.lua", source)
        self.assertIn("Remove-TemporarySolverDirectory", source)
        self.assertNotIn("Copy-RequiredInput $sourceAnalyzer", source)
        self.assertNotIn("Copy-RequiredInput $sourceAccelerator", source)


if __name__ == "__main__":
    unittest.main()
