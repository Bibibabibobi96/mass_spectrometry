import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from common.contracts.machine_contracts import load_json, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    analyze_zero_match_higher_order_stage_a as stage_a,
)


CAMPAIGN = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "diagnostics"
    / "zero_match_long_higher_order_stage_a_campaign.json"
)


class ZeroMatchHigherOrderStageATests(unittest.TestCase):
    def test_registered_campaign_is_schema_valid_and_fail_closed(self):
        campaign = load_json(CAMPAIGN)
        validate_schema(
            campaign, "rf_oatof_zero_match_higher_order_stage_a_campaign.schema.json"
        )
        changed = copy.deepcopy(campaign)
        changed["unregistered_interpretation"] = True
        with self.assertRaises(Exception):
            validate_schema(
                changed,
                "rf_oatof_zero_match_higher_order_stage_a_campaign.schema.json",
            )
        missing_stop_rule = copy.deepcopy(campaign)
        del missing_stop_rule["stop_rule"]
        with self.assertRaises(Exception):
            validate_schema(
                missing_stop_rule,
                "rf_oatof_zero_match_higher_order_stage_a_campaign.schema.json",
            )
        self.assertNotIn("minimum", campaign["stop_rule"])
        self.assertEqual(
            campaign["stop_rule"]["threshold_reference"],
            "acceptance_thresholds.minimum_detector_nonlinear_variance_fraction",
        )

    def test_strict_particle_id_folds_and_global_nonlinear_reconstruction(self):
        particle_ids = np.arange(1, 1001, dtype=int)
        source_offset_mm = np.linspace(-1.1, 1.1, len(particle_ids))
        normalized = source_offset_mm / 1.1
        times_us = 30.0 + 1.0e-3 * (0.8 * normalized**2 + 0.4 * normalized**4)
        result = stage_a.cross_validated_global_polynomials(
            particle_ids,
            source_offset_mm,
            times_us,
            fold_count=5,
            model_degrees=(1, 2, 3, 4),
        )
        self.assertEqual(result["fold_assignment"], "particle_id_modulo_5")
        for model in result["models"]:
            self.assertEqual(
                [fold["validation_count"] for fold in model["folds"]], [200] * 5
            )
        self.assertGreater(
            result["nonlinear_variance_fraction_after_global_m1"], 0.99
        )
        self.assertGreater(
            result["m2_to_m4_captured_fraction_of_global_m1_sse"], 0.999999
        )
        self.assertTrue(result["m4_better_than_m1_in_every_fold"])

    def test_fractional_particle_ids_are_rejected_without_truncation(self):
        particle_ids = np.arange(1, 21, dtype=float)
        particle_ids[5] = 6.5
        with self.assertRaisesRegex(ValueError, "exact integers"):
            stage_a.cross_validated_global_polynomials(
                particle_ids,
                np.linspace(-1.0, 1.0, len(particle_ids)),
                np.linspace(30.0, 30.1, len(particle_ids)),
                fold_count=5,
                model_degrees=(1,),
            )

    def test_source_release_error_bounds_reject_nonfinite_and_negative_values(self):
        valid = {"observed": 1.0e-9, "tolerance": 2.0e-9}
        stage_a._require_finite_error_within_tolerance(
            valid, "observed", "tolerance", "test"
        )
        invalid_pairs = (
            (float("nan"), 2.0e-9),
            (float("inf"), 2.0e-9),
            (1.0e-9, float("nan")),
            (1.0e-9, float("inf")),
            (1.0e-9, -1.0),
        )
        for observed, tolerance in invalid_pairs:
            with self.subTest(observed=observed, tolerance=tolerance):
                with self.assertRaisesRegex(ValueError, "tolerance differs"):
                    stage_a._require_finite_error_within_tolerance(
                        {"observed": observed, "tolerance": tolerance},
                        "observed",
                        "tolerance",
                        "test",
                    )

    def test_campaign_path_must_remain_inside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "campaign.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "campaign path escapes"):
                stage_a.compute_stage_a_report(outside)

    def test_manifest_record_identity_mismatch_is_rejected(self):
        expected_path = Path("C:/evidence/checkpoints.csv")
        manifest_path = Path("C:/evidence/run_manifest.json")
        expected = {
            "path": str(expected_path),
            "bytes": 10,
            "sha256": "A" * 64,
        }
        manifest = {
            "inputs": {
                "initial_global_state": {
                    "path": "checkpoints.csv",
                    "bytes": 11,
                    "sha256": "A" * 64,
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "byte count differs"):
            stage_a._require_named_record(
                manifest,
                manifest_path,
                "inputs",
                "initial_global_state",
                expected_path,
                expected,
            )


if __name__ == "__main__":
    unittest.main()
