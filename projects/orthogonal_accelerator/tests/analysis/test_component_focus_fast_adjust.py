from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.orthogonal_accelerator.analysis.component_focus_fast_adjust import (
    ComponentFocusFastAdjustError,
    _candidate_campaign,
    initialize,
    record_analysis,
)


PROJECT = Path(__file__).resolve().parents[2]
CAMPAIGN = PROJECT / "config" / "two_zone_component_focus_campaign.json"


class ComponentFocusFastAdjustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.campaign_path = self.root / "campaign.json"
        self.campaign_path.write_text(CAMPAIGN.read_text(encoding="utf-8"), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_analysis(self, name: str, p2p_ns: float, *, accepted: bool = False) -> Path:
        path = self.root / name
        path.write_text(json.dumps({
            "role": "orthogonal_accelerator_component_focus_analysis",
            "status": "candidate_complete" if accepted else "candidate_incomplete",
            "focus_metrics": {"peak_to_peak_t_ns": p2p_ns},
            "hard_gate": {
                "complete_transport_passed": accepted,
            },
        }), encoding="utf-8")
        return path

    def test_searches_at_most_five_direct_p2p_candidates_and_accepts_transport_gate(self) -> None:
        state = initialize(self.campaign_path, [100.0, 1500.0], 5)
        seed = state["next_gap1_voltage_drop_v"]
        self.assertGreater(seed, 100.0)
        state = record_analysis(state, self.write_analysis("one.json", 7.0))
        self.assertLess(state["next_gap1_voltage_drop_v"], seed)
        state = record_analysis(state, self.write_analysis("two.json", 4.0))
        self.assertGreater(state["next_gap1_voltage_drop_v"], seed)
        state = record_analysis(state, self.write_analysis("three.json", 2.0))
        self.assertEqual(len(state["records"]), 3)
        self.assertEqual(state["status"], "running")
        state = record_analysis(state, self.write_analysis("four.json", 1.2, accepted=True))
        self.assertEqual(state["status"], "accepted")
        self.assertIsNone(state["next_gap1_voltage_drop_v"])

    def test_exhaustion_is_bounded_and_does_not_rebuild_or_change_pa_plan(self) -> None:
        state = initialize(self.campaign_path, [100.0, 1500.0], 3)
        for index in range(3):
            state = record_analysis(state, self.write_analysis(f"{index}.json", 7.0 - index))
        self.assertEqual(state["status"], "exhausted")
        self.assertIsNone(state["next_gap1_voltage_drop_v"])
        self.assertEqual(len(state["records"]), 3)

    def test_candidate_changes_only_voltage_table_and_preserves_final_energy(self) -> None:
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        original = campaign["operating_point"]["electrode_voltages_v"]
        candidate = _candidate_campaign(campaign, original[1] - original[2] + 50.0)
        self.assertEqual(candidate["release_spec"], campaign["release_spec"])
        self.assertEqual(candidate["simion_projection"], campaign["simion_projection"])
        voltages = candidate["operating_point"]["electrode_voltages_v"]
        self.assertEqual(len(voltages), 9)
        self.assertAlmostEqual(voltages[1] - voltages[2], original[1] - original[2] + 50.0)
        self.assertAlmostEqual(voltages[4], voltages[2] * 5.0 / 6.0)

    def test_rejects_seed_outside_explicit_bounds(self) -> None:
        with self.assertRaisesRegex(ComponentFocusFastAdjustError, "outside controller bounds"):
            initialize(self.campaign_path, [100.0, 200.0], 5)

    def test_runner_reuses_only_the_existing_flight_runner_and_withholds_mr_receipt_on_exhaustion(self) -> None:
        runner = (PROJECT / "simion" / "run_component_focus_fast_adjust.ps1").read_text(encoding="utf-8")
        workflow = (PROJECT / "simion" / "run_component_focus_workflow.ps1").read_text(encoding="utf-8")
        self.assertIn("run_component_focus_flight.ps1", runner)
        self.assertNotIn("run_component_focus_pa.ps1", runner)
        self.assertNotIn("build_component_focus_pa.lua", runner)
        self.assertNotIn("Copy-Item -LiteralPath $controller", runner)
        self.assertIn("published_read_only_native_fast_adjust_family__no_build_copy_or_refine", runner)
        self.assertIn('$childRunId="$RootRunId`__fast-adjust-trial$index`__r$(\'{0:d2}\' -f ($index + 2))"', runner)
        self.assertIn("-InitialAnalysisPath $initialAnalysis", workflow)
        self.assertIn("status -ne 'accepted'", workflow)
        self.assertIn("MR runtime receipt is withheld", workflow)
        self.assertIn("--campaign $acceptedCampaign", workflow)
        self.assertIn("status='candidate_complete'", workflow)
        self.assertIn('$fastAdjustRunId="$RunId`__fast-adjust__r01"', workflow)
        self.assertIn('-RootRunId $RunId', workflow)


if __name__ == "__main__":
    unittest.main()
