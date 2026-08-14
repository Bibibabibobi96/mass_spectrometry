from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.verify_method_comparator import (
    verify,
    verify_field_region_matrix,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.select_pulse_offset import select


class MethodComparatorTest(unittest.TestCase):
    def test_pulse_selector_uses_detector_blind_lexicographic_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = []
            metrics = [
                (0.0, 900, 0.01, 0.8, 0.7),
                (0.0625, 901, 0.9, 0.1, 0.0),
            ]
            for index, (offset, count, centroid, quantile, minimum) in enumerate(metrics):
                path = root / f"candidate_{index}.json"
                path.write_text(json.dumps({"spatial_window_peak": {
                    "detector_blind_selection_metrics": {
                        "detector_results_used": False,
                        "accepted_count": count,
                        "normalized_2d_centroid_distance": centroid,
                        "quantile_normalized_edge_margin": quantile,
                        "minimum_normalized_edge_margin": minimum,
                    }
                }}), encoding="utf-8")
                candidates.append((offset, path))
            receipt = select(candidates)
        self.assertEqual(receipt["selected_offset_rf_periods"], 0.0625)
        self.assertFalse(receipt["selection_uses_detector_outcome"])
        self.assertFalse(receipt["detector_results_used"])

    def test_pulse_selector_ignores_empty_or_negative_pulse_relative_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = []
            for index, pulse_times in enumerate(([], [-1.0, -0.25])):
                path = root / f"candidate_{index}.json"
                path.write_text(json.dumps({
                    "pulse_effective_peak": None,
                    "diagnostic_pulse_relative_times_us": pulse_times,
                    "spatial_window_peak": {
                        "detector_blind_selection_metrics": {
                            "detector_results_used": False,
                            "accepted_count": 10 + index,
                            "normalized_2d_centroid_distance": 0.1,
                            "quantile_normalized_edge_margin": 0.5,
                            "minimum_normalized_edge_margin": 0.4,
                        }
                    },
                }), encoding="utf-8")
                candidates.append((index * 0.0625, path))
            receipt = select(candidates)
        self.assertEqual(receipt["selected_offset_rf_periods"], 0.0625)
        self.assertNotIn("pulse_effective_peak", receipt)

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
