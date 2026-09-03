"""Static guardrails for the reviewed-IOB center-flight entry."""
from __future__ import annotations

import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_three_component_center_flight.ps1"


class ThreeComponentCenterFlightRunnerTest(unittest.TestCase):
    def test_runner_freezes_reviewed_iob_and_requires_exact_center_source(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "GeometryReviewRunPath", "mrtof_three_component_candidate.iob",
            "three_component_geometry_review.json", "prototype_input_manifest.json",
            "simion_prototype_contract.json", "mrtof_candidate_center.fly2", "Test-RunFilesIdentical",
            "run_iob_flight.lua", "simion_event_analysis.py",
            "three_component_simion_flight_manifest.py", "center_fly2",
        ):
            self.assertIn(token, source)

    def test_runner_is_n1_and_capacity_gated_before_native_flight(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("particle_count=1", source)
        self.assertIn("Invoke-ArtifactCapacityGate", source)
        self.assertLess(source.index("capacity_preflight"), source.index("native_center_flight"))
        self.assertIn("candidate_prototype_event_chain_only", source)
        self.assertNotIn("mass_resolution", source)


if __name__ == "__main__":
    unittest.main()
