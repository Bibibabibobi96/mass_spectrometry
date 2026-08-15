from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.screening_promotion_gate import (
    evaluate_campaign_n100_paired_promotion,
)


CAMPAIGN = Path(__file__).resolve().parents[1] / "config" / "pulse_resolution_direct_baseline_successor_r09_campaign.json"


class ScreeningPromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        rng = np.random.default_rng(20260812)
        self.ids = np.arange(1, 101)
        self.hit = np.ones(100, dtype=bool)
        self.hit[[3, 44, 81]] = False
        self.baseline_tof = 32230.0 + rng.normal(0.0, 0.8, 100)
        self.baseline_tof[~self.hit] = np.nan

    def arm(self, arm_id: str, tof: np.ndarray, *, reverse: bool = False) -> dict[str, object]:
        order = np.arange(99, -1, -1) if reverse else np.arange(100)
        return {
            "arm_id": arm_id,
            "particle_ids": self.ids[order],
            "hit_status": self.hit[order],
            "pulse_effective_tof_ns": tof[order],
            "pulse_eligible_status": np.ones(100, dtype=bool)[order],
        }

    def test_promotes_same_ids_when_both_widths_improve_and_both_are_single_mode(self) -> None:
        candidate_tof = 32230.0 + 0.8 * (self.baseline_tof - 32230.0)
        receipt = evaluate_campaign_n100_paired_promotion(
            self.campaign,
            self.arm("baseline", self.baseline_tof),
            self.arm("candidate", candidate_tof, reverse=True),
        )
        self.assertTrue(receipt["promoted"])
        self.assertEqual(receipt["decision"], "promote")
        self.assertEqual(receipt["failure_reasons"], [])
        self.assertEqual(receipt["pairing"]["population_count"], 100)
        self.assertEqual(receipt["pairing"]["eligible_paired_count"], 100)
        self.assertAlmostEqual(receipt["improvements"]["direct_fwhm_relative"], 0.2, places=10)
        self.assertAlmostEqual(receipt["improvements"]["sample_sigma_relative"], 0.2, places=12)
        self.assertEqual(receipt["baseline"]["nonhit_count"], 3)
        self.assertTrue(receipt["baseline"]["nonhit_rows_retained"])
        json.dumps(receipt)

    def test_rejects_when_either_width_improvement_is_below_fifteen_percent(self) -> None:
        candidate_tof = 32230.0 + 0.9 * (self.baseline_tof - 32230.0)
        receipt = evaluate_campaign_n100_paired_promotion(
            self.campaign,
            self.arm("baseline", self.baseline_tof),
            self.arm("candidate", candidate_tof),
        )
        codes = {reason["code"] for reason in receipt["failure_reasons"]}
        self.assertFalse(receipt["promoted"])
        self.assertIn("direct_fwhm_improvement_below_minimum", codes)
        self.assertIn("sample_sigma_improvement_below_minimum", codes)

    def test_rejects_multimodal_candidate(self) -> None:
        candidate_tof = self.baseline_tof.copy()
        detected = np.flatnonzero(self.hit)
        candidate_tof[detected[: len(detected) // 2]] -= 5.0
        candidate_tof[detected[len(detected) // 2 :]] += 5.0
        receipt = evaluate_campaign_n100_paired_promotion(
            self.campaign,
            self.arm("baseline", self.baseline_tof),
            self.arm("candidate", candidate_tof),
        )
        codes = {reason["code"] for reason in receipt["failure_reasons"]}
        self.assertIn("candidate_not_single_mode", codes)

    def test_rejects_omitted_nonhit_row_and_changed_id_cohort(self) -> None:
        baseline = self.arm("baseline", self.baseline_tof)
        baseline["particle_ids"] = baseline["particle_ids"][:-1]
        baseline["hit_status"] = baseline["hit_status"][:-1]
        baseline["pulse_effective_tof_ns"] = baseline["pulse_effective_tof_ns"][:-1]
        receipt = evaluate_campaign_n100_paired_promotion(
            self.campaign,
            baseline,
            self.arm("candidate", self.baseline_tof),
        )
        codes = {reason["code"] for reason in receipt["failure_reasons"]}
        self.assertIn("population_count_not_n100", codes)
        self.assertIn("cohort_id_mismatch", codes)

    def test_rejects_changed_pulse_eligible_cohort(self) -> None:
        baseline = self.arm("baseline", self.baseline_tof)
        candidate = self.arm("candidate", self.baseline_tof)
        candidate["pulse_eligible_status"][7] = False
        receipt = evaluate_campaign_n100_paired_promotion(self.campaign, baseline, candidate)
        codes = {reason["code"] for reason in receipt["failure_reasons"]}
        self.assertIn("pulse_eligible_cohort_mismatch", codes)

    def test_ineligible_detector_hits_remain_in_census_but_not_peak(self) -> None:
        baseline = self.arm("baseline", self.baseline_tof)
        candidate = self.arm("candidate", 32230.0 + 0.8 * (self.baseline_tof - 32230.0))
        eligible = np.zeros(100, dtype=bool)
        eligible[:50] = True
        baseline["pulse_eligible_status"] = eligible
        candidate["pulse_eligible_status"] = eligible
        receipt = evaluate_campaign_n100_paired_promotion(self.campaign, baseline, candidate)
        self.assertEqual(receipt["baseline"]["population_count"], 100)
        self.assertEqual(receipt["baseline"]["hit_count"], 97)
        self.assertEqual(receipt["baseline"]["pulse_eligible_count"], 50)
        self.assertEqual(receipt["baseline"]["pulse_eligible_hit_count"], 48)
        self.assertEqual(receipt["baseline"]["pulse_ineligible_hit_count"], 49)
        self.assertEqual(receipt["pairing"]["population_count"], 100)
        self.assertEqual(receipt["pairing"]["eligible_paired_count"], 50)
        self.assertEqual(receipt["baseline"]["peak"]["detected_particles_used"], 48)

    def test_rejects_missing_detected_tail_instead_of_filtering_it(self) -> None:
        candidate_tof = 32230.0 + 0.8 * (self.baseline_tof - 32230.0)
        candidate_tof[np.flatnonzero(self.hit)[-1]] = np.nan
        receipt = evaluate_campaign_n100_paired_promotion(
            self.campaign,
            self.arm("baseline", self.baseline_tof),
            self.arm("candidate", candidate_tof),
        )
        codes = {reason["code"] for reason in receipt["failure_reasons"]}
        self.assertIn("detected_particle_missing_tof", codes)
        self.assertFalse(receipt["promoted"])

    def test_rejects_campaign_threshold_drift(self) -> None:
        self.campaign["pulse_resolution_optimization"]["screening_promotion"]["sigma_relative_improvement_minimum"] = (
            0.1
        )
        receipt = evaluate_campaign_n100_paired_promotion(
            self.campaign,
            self.arm("baseline", self.baseline_tof),
            self.arm("candidate", self.baseline_tof),
        )
        codes = {reason["code"] for reason in receipt["failure_reasons"]}
        self.assertIn("campaign_contract_invalid", codes)


if __name__ == "__main__":
    unittest.main()
