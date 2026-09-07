"""Static guardrails for the rebuilt-IOb first-prism diagnostic runner."""
from __future__ import annotations

import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_three_component_first_prism_flight.ps1"


class ThreeComponentFirstPrismRunnerTest(unittest.TestCase):
    def test_runner_rebuilds_matching_iob_and_binds_source_bytes(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "mrtof_first_prism_l0.iob", "mrtof_first_prism_l0.fly2",
            "mrtof_first_prism_entry_center.fly2", "Test-RunFilesIdentical",
            "mrtof_three_component_candidate.iob", "inspect_three_component_iob.lua",
            "run_iob_flight.lua", "first_prism_l0_result.py",
            "first_prism_iob_fly2", "Invoke-ArtifactCapacityGate",
            "mrtof_analyzer.pa#", "mrtof_accelerator.pa#",
        ):
            self.assertIn(token, source)

    def test_runner_does_not_claim_a_return_or_resolution(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("prototype_first_prism_interface_only", source)
        self.assertIn("No return, K=25, transmission, time focus, or resolution claim", source)
        self.assertNotIn("build_iob'", source)


if __name__ == "__main__":
    unittest.main()
