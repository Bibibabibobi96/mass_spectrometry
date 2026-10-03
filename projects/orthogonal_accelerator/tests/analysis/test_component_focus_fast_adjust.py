from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.orthogonal_accelerator.analysis.component_focus_fast_adjust import (
    _candidate_campaign, _tier, initialize, record_analysis,
)


PROJECT = Path(__file__).resolve().parents[2]
CAMPAIGN = PROJECT / "config" / "two_zone_component_focus_campaign.json"


class ComponentFocusFastAdjustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.campaign_path = self.root / "campaign.json"
        self.campaign_path.write_text(CAMPAIGN.read_text(encoding="utf-8"), encoding="utf-8")
        self.campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_analysis(
        self, name: str, slow: float, axial: float, *, accepted: bool = False,
        cohort_slow: float | None = None, cohort_axial: float | None = None,
        cohort_transverse: float = 0.01,
    ) -> Path:
        cohort_slow = abs(slow) if cohort_slow is None else cohort_slow
        cohort_axial = abs(axial) if cohort_axial is None else cohort_axial
        geometry_ok = cohort_slow <= 0.05 and cohort_transverse <= 0.05
        path = self.root / name
        path.write_text(json.dumps({
            "role": "orthogonal_accelerator_component_focus_analysis",
            "status": "candidate_complete" if accepted else "candidate_incomplete",
            "focus_metrics": {"peak_to_peak_t_ns": 2.0},
            "hard_gate": {"complete_transport_passed": True,
                          "exit_slow_energy_passed": geometry_ok,
                          "exit_axial_energy_passed": accepted,
                          "exit_transverse_energy_passed": geometry_ok,
                          "exit_transverse_velocity_bias_passed": True},
            "exit_energy_assessment": {
                "tolerances": {"maximum_exit_slow_energy_error_per_charge_v": 0.05,
                               "maximum_exit_axial_energy_error_per_charge_v": 0.05,
                               "maximum_exit_transverse_energy_error_per_charge_v": 0.05,
                               "maximum_exit_transverse_velocity_bias_mm_per_us": 0.0001},
                "center_particle": {"slow_energy_residual_per_charge_v": slow,
                                    "axial_energy_residual_per_charge_v": axial,
                                    "delta_vx_mm_per_us": 0.0},
                "cohort": {"maximum_absolute_slow_energy_residual_per_charge_v": cohort_slow,
                           "maximum_absolute_axial_energy_residual_per_charge_v": cohort_axial,
                           "maximum_absolute_transverse_energy_residual_per_charge_v": cohort_transverse,
                           "mean_delta_vx_mm_per_us": 0.0},
            },
        }), encoding="utf-8")
        return path

    def test_geometry_gate_precedes_voltage_search(self) -> None:
        state = initialize(self.campaign_path, 7)
        state = record_analysis(
            state,
            self.write_analysis("geometry_bad.json", -0.4, -1.6, cohort_slow=0.4),
            self.campaign,
        )
        self.assertEqual(state["status"], "exhausted")
        self.assertFalse(state["records"][0]["geometry_acceptable"])
        self.assertEqual(
            state["records"][0]["geometry_diagnostic"],
            "cohort_Ex_Ey_geometry_gate_failed",
        )

    def test_uses_one_real_voltage_probe_then_continuous_axial_solution(self) -> None:
        state = initialize(self.campaign_path, 7)
        initial_y = state["next_parameters"]["instance_center_y_mm"]
        state = record_analysis(state, self.write_analysis("base.json", 0.01, -1.6), self.campaign)
        self.assertEqual(state["phase"], "gain_probe")
        self.assertEqual(state["next_parameters"]["instance_center_y_mm"], initial_y)
        state = record_analysis(state, self.write_analysis("gain.json", 0.01, -0.6), self.campaign)
        self.assertEqual(state["phase"], "solution")
        self.assertEqual(state["next_parameters"]["instance_center_y_mm"], initial_y)
        self.assertIsInstance(state["next_parameters"]["finite_3d_gain_correction_v"], float)
        state = record_analysis(state, self.write_analysis("solution.json", 0.01, -0.01, accepted=True), self.campaign)
        self.assertEqual(state["status"], "accepted")
        self.assertIsNone(state["next_parameters"])

    def test_percentage_tiers_are_not_discrete_final_values(self) -> None:
        self.assertEqual(_tier(1.0), 0.0005)
        self.assertEqual(_tier(5.0), 0.0025)
        self.assertEqual(_tier(20.0), 0.01)

    def test_exhaustion_is_bounded(self) -> None:
        state = initialize(self.campaign_path, 4)
        for name, residuals in (("b", (.01, -1.6)), ("g", (.01, -.6)),
                                ("s", (.01, -.2)), ("g2", (.01, -.1))):
            state = record_analysis(state, self.write_analysis(name + ".json", *residuals), self.campaign)
        self.assertEqual(state["status"], "exhausted")
        self.assertIsNone(state["next_parameters"])

    def test_center_axial_closure_does_not_waive_cohort_axial_gate(self) -> None:
        state = initialize(self.campaign_path, 7)
        state = record_analysis(
            state,
            self.write_analysis("spread.json", 0.01, 0.01, cohort_axial=0.2),
            self.campaign,
        )
        self.assertEqual(state["status"], "exhausted")
        self.assertFalse(state["records"][0]["accepted"])
        self.assertTrue(state["records"][0]["center_axial_energy_passed"])

    def test_candidate_changes_only_runtime_pose_and_voltage_not_pa_identity(self) -> None:
        parameters = {"instance_center_y_mm": 2.0, "finite_3d_gain_correction_v": 25.0}
        candidate = _candidate_campaign(self.campaign, parameters)
        candidate_path = self.root / "candidate.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        self.assertEqual(candidate["release_spec"], self.campaign["release_spec"])
        self.assertEqual(candidate["simion_projection"], self.campaign["simion_projection"])
        self.assertEqual(candidate["geometry_profile_id"], self.campaign["geometry_profile_id"])
        self.assertEqual(candidate["operating_point"]["instance_center_y_mm"], 2.0)
        self.assertEqual(candidate["operating_point"]["finite_3d_gain_correction_v"], 25.0)

    def test_runner_reuses_existing_pa_and_applies_retention(self) -> None:
        runner = (PROJECT / "simion" / "run_component_focus_fast_adjust.ps1").read_text(encoding="utf-8")
        workflow = (PROJECT / "simion" / "run_component_focus_workflow.ps1").read_text(encoding="utf-8")
        self.assertIn("run_component_focus_flight.ps1", runner)
        self.assertNotIn("run_component_focus_pa.ps1", runner)
        self.assertNotIn("Gap1VoltageDropBoundsV", runner)
        self.assertIn("Apply-RunArtifactRetention", runner)
        self.assertIn("best_campaign.json", runner)
        self.assertIn("-InitialAnalysisPath $initialAnalysis", workflow)
        self.assertIn("MR runtime receipt is withheld", workflow)


if __name__ == "__main__":
    unittest.main()
