"""Static guardrails for the reviewed-IOB center-flight entry."""
from __future__ import annotations

import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_three_component_center_flight.ps1"


class ThreeComponentCenterFlightRunnerTest(unittest.TestCase):
    def test_runner_consumes_audited_prism_point_and_requires_exact_center_source(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "TwoPrismOperatingPointRunPath", "finite_3d_two_prism_operating_point_audit",
            "mrtof_three_component_candidate.iob", "prototype_input_manifest.json",
            "full_mrtof_center_fly2", "full_center_source",
            "mrtof_three_component_candidate.mirror_cycle_counter.lua",
            "run_iob_flight.lua", "simion_event_analysis",
            "single_center_phase_space_handoff_candidate__K25_pending",
            "continue_past_drift_phase_origin",
            "integer_K_same-side-turn_y_samples",
            "read_only_voltageized",
        ):
            self.assertIn(token, source)
        self.assertNotIn("mrtof_candidate_center.fly2", source)
        self.assertNotIn("source_key='center_fly2'", source)
        inputs_start = source.index("$configuration.inputs")
        parameters_start = source.index("$configuration.parameters", inputs_start)
        self.assertNotIn("source_key", source[inputs_start:parameters_start])
        self.assertIn("source_key = 'full_mrtof_center_fly2'", source[parameters_start:])
        self.assertIn("program = Join-Path $PSScriptRoot 'mrtof_candidate.lua'", source)
        self.assertIn("counter = Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'", source)
        self.assertNotIn("-PreserveRawOutputs", source)

    def test_runner_is_n1_and_capacity_gated_before_native_flight(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("particle_count = 1", source)
        self.assertIn("Invoke-ArtifactCapacityGate", source)
        self.assertLess(source.index("capacity_preflight"), source.index("native_center_flight"))
        self.assertIn("candidate_prototype_event_chain_only", source)
        self.assertNotIn("mass_resolution", source)
        self.assertNotIn("$flightLauncher,'--'", source)


if __name__ == "__main__":
    unittest.main()
