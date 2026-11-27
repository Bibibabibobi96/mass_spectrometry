"""SI detector peak semantics independent of backend and Store orchestration."""
import copy
import unittest

import numpy as np

from msplatform.analysis.native_detector_peak import analyze_native_detector_peak
from msplatform.analysis.peak_metrics import AnalysisSettings, compute_nominal_mass_peak_metrics


def fixture():
    initial = [dict(particle_id=i, species_id="ion", time_s=i * 1e-7,
                    lineage_status="primary_birth", weight=1.0) for i in range(1, 5)]
    events = [dict(particle_id=row["particle_id"], species_id="ion", event_kind="detector",
                   surface_id="detector", physical_outcome="detected", attribution_status="known", time_s=row["time_s"] + (10 + row["particle_id"]) * 1e-6)
              for row in initial]
    return dict(schema_version=2, metadata=dict(initial_state_basis="native_birth_verified"),
        execution_status="succeeded", data_integrity=dict(status="complete",
            detector_observation=dict(status="complete")), initial_states=initial, events=events)


class NativeDetectorPeakTests(unittest.TestCase):
    def analyze(self, data):
        return analyze_native_detector_peak(data, species_id="ion", surface_id="detector",
                                            nominal_mass_da=524, settings=AnalysisSettings(), declared_surface_ids=("detector",))

    def test_flight_time_uses_each_birth_and_preserves_cohort(self):
        data = fixture()
        result = self.analyze(data)
        expected, _ = compute_nominal_mass_peak_metrics(np.array([11., 12., 13., 14.]), 524, AnalysisSettings())
        self.assertAlmostEqual(result["metrics"]["mean_tof_us"], expected["mean_tof_us"])
        self.assertEqual(result["summary"]["time_basis"], "flight_time_from_verified_birth")
        self.assertEqual(result["summary"]["mother_count"], 4)
        self.assertEqual(result["summary"]["detector_observed_count"], 4)

    def test_zero_hits_is_observed_but_peak_is_unavailable(self):
        data = fixture()
        data["events"] = []
        result = self.analyze(data)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["metrics"])
        self.assertEqual(result["summary"]["not_detected_count"], 4)

    def test_undeclared_surface_is_not_a_zero_hit_result(self):
        with self.assertRaisesRegex(ValueError, "not declared"):
            analyze_native_detector_peak(fixture(), species_id="ion", surface_id="other",
                nominal_mass_da=524, settings=AnalysisSettings(), declared_surface_ids=("detector",))

    def test_incomplete_unknown_duplicate_and_unequal_weight_refuse(self):
        for mutation in ("unknown", "duplicate", "weight", "snapshot"):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(fixture())
                if mutation == "unknown":
                    data["data_integrity"]["detector_observation"]["status"] = "unavailable"
                elif mutation == "duplicate":
                    data["events"].append(copy.deepcopy(data["events"][0]))
                elif mutation == "weight":
                    data["initial_states"][0]["weight"] = 2.0
                else:
                    data["metadata"]["initial_state_basis"] = "snapshot"
                with self.assertRaises(ValueError):
                    self.analyze(data)


if __name__ == "__main__":
    unittest.main()
