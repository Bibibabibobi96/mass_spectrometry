from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.verify_method_comparator import (
    verify,
    verify_field_region_matrix,
)


class MethodComparatorTest(unittest.TestCase):
    def test_b_c_only_change_governed_field_flag_and_identities(self) -> None:
        campaign = Path(__file__).parents[1] / "config/diagnostics/long_focus_native_method_comparator_n835_campaign.json"
        with tempfile.TemporaryDirectory() as directory:
            receipt = verify(campaign, Path(directory) / "receipt.json")
        self.assertEqual(receipt["b_c_frozen_identity_assertion"], "pass")
        self.assertEqual(receipt["historical_arm_a"]["particle_count"], 835)
        self.assertFalse(receipt["pa_discretization_identical_to_historical"])
        campaign_rows = json.loads(campaign.read_text(encoding="utf-8"))["experiments"]
        self.assertEqual(
            campaign_rows[0]["single_flight_pulse_offset_rf_periods"],
            campaign_rows[1]["single_flight_pulse_offset_rf_periods"],
        )
        base_pulse = 45.416793965641695
        offset = campaign_rows[0]["single_flight_pulse_offset_rf_periods"]
        self.assertAlmostEqual(base_pulse + offset / 1.1, 45.5585544411, places=12)

    def test_short_focus_field_region_matrix_is_frozen_2x2(self) -> None:
        integration = Path(__file__).parents[1]
        campaign = integration / "config/diagnostics/short_focus_winner_field_region_attribution_n1000_campaign.json"
        registry = integration / "config/simion_single_flight.json"
        manifest = (
            integration.parents[2]
            / "artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "runs/20260814_185300__analysis__python__r03-winner-postselection-republish__n1000/run_manifest.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            receipt = verify_field_region_matrix(
                campaign, registry, manifest, Path(directory) / "receipt.json"
            )
        self.assertTrue(receipt["only_governed_stage_flags_and_run_identities_differ"])
        self.assertEqual(set(receipt["controlled_matrix"]), {"RR", "IR", "RI", "II"})
        self.assertEqual(
            receipt["global_piecewise"]["classification"],
            "extra_oracle_not_2x2_causal_arm",
        )


if __name__ == "__main__":
    unittest.main()
