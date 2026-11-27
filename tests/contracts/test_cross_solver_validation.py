"""The scientific comparison is independent of historical artifact ownership."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from msplatform.analysis.cross_solver_validation import validate_cross_solver_metrics
from msplatform.results.cross_solver_history import read_cross_solver_record


class CrossSolverValidationTests(unittest.TestCase):
    def test_retired_verifier_module_is_not_an_importable_wrapper(self):
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.oa_formal.verify_formal_validation"))

    def test_historical_reader_rejects_unknown_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps({"schema_version": 6}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported historical"):
                read_cross_solver_record(path, Path(directory))

    def test_v5_complete_metrics_and_mismatch(self):
        record = {"schema_version": 5, "comsol": {"metrics": {"mean_tof_us": 2.0}},
                  "simion": {"metrics": {"mean_tof_us": 2.01}}, "comparison": {"difference_ns": 10.0}}
        comparison = {"status": "PASS", "left": {"metrics": {"mean_tof_us": 2.0}},
                      "right": {"metrics": {"mean_tof_us": 2.01}}, "comparison": {"difference_ns": 10.0}}
        validate_cross_solver_metrics(record, comparison)
        for change in ("status", "left", "right", "comparison"):
            bad = copy.deepcopy(comparison)
            if change == "status":
                bad[change] = "FAIL"
            elif change == "comparison":
                bad[change]["difference_ns"] = 11.0
            else:
                bad[change]["metrics"]["mean_tof_us"] += 0.01
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_cross_solver_metrics(record, bad)

    def test_legacy_metrics_keep_original_tolerances_and_field_mapping(self):
        metrics = {key: 1.0 for key in (
            "mean_tof_us", "direct_fwhm_tof_ns", "direct_fwhm_mass_Da", "mass_resolution",
            "tof_skewness", "hwhm_asymmetry_right_over_left", "significant_kde_modes")}
        detector = {key: 1.0 for key in ("impact_centroid_x_mm", "impact_centroid_y_mm", "impact_rms_radius_mm")}
        side = {**metrics, **detector}
        comparison_keys = (
            "mean_tof_difference_right_minus_left_ns", "standardized_kde_overlap", "standardized_ks_distance",
            "standardized_ks_pvalue", "paired_standardized_tof_correlation",
            "bootstrap_absolute_resolution_difference_pct_p2p5", "bootstrap_absolute_resolution_difference_pct_median",
            "bootstrap_absolute_resolution_difference_pct_p97p5")
        compared = {key: 1.0 for key in comparison_keys}
        landing = {key: 1.0 for key in ("centroid_distance_mm", "paired_mean_landing_distance_mm",
                                         "paired_rms_landing_distance_mm", "paired_max_landing_distance_mm")}
        record_comparison = {key: value for key, value in compared.items()
                             if key != "mean_tof_difference_right_minus_left_ns"}
        record_comparison.update(mean_tof_difference_simion_minus_comsol_ns=1.0,
                                 detector_centroid_distance_mm=1.0, paired_mean_landing_distance_mm=1.0,
                                 paired_rms_landing_distance_mm=1.0, paired_max_landing_distance_mm=1.0,
                                 comsol_resolution_higher_than_simion_pct=0.0)
        record = {"schema_version": 4, "comsol": dict(side), "simion": dict(side),
                  "comparison": record_comparison}
        comparison = {"status": "PASS", "left": {"metrics": {**metrics, "detector": detector}},
                      "right": {"metrics": {**metrics, "detector": detector}},
                      "comparison": {**compared, "detector_landing": landing}}
        validate_cross_solver_metrics(record, comparison)
        comparison["left"]["metrics"]["mean_tof_us"] += 1e-5
        with self.assertRaisesRegex(ValueError, "comsol.mean_tof_us mismatch"):
            validate_cross_solver_metrics(record, comparison)


if __name__ == "__main__":
    unittest.main()
