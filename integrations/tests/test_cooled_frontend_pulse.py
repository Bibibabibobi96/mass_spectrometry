from __future__ import annotations

import copy
import math
import unittest

from integrations.workflows.cooled_frontend.pulse import (
    freeze_common_pulse_decision, propose_common_pulse,
)


def ray(time: float, y: float) -> dict:
    return dict(pulse_time_us=time, exit_y_mm=y, exit_time_us=time+1.,
                evidence={"path": f"reference-{time}.csv", "sha256": "a"*64})


class CommonPulseTests(unittest.TestCase):
    def test_native_bracket_proposes_a_new_check_without_using_population_outcomes(self):
        rows = [ray(101., -2.), ray(105., 6.)]
        before = copy.deepcopy(rows)
        result = propose_common_pulse(rows, target_y_mm=0., release_start_us=100.)
        self.assertEqual(result["proposal_time_us"], 102.)
        self.assertTrue(result["native_check_required"])
        self.assertTrue(result["pressure_arms_share_clock"])
        self.assertFalse(result["selection_uses_mother_terminal_outcome"])
        self.assertEqual(rows, before)

    def test_no_extrapolation_or_duplicate_clocks_or_nonfinite_states(self):
        for rows in ([ray(101., 1.), ray(102., 2.)], [ray(101., -1.), ray(101., 1.)],
                     [ray(101., math.nan)], [ray(99., 0.)],
                     [{**ray(101., 0.), "evidence": {}}],
                     [{**ray(101., 0.), "exit_time_us": 100.}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                propose_common_pulse(rows, target_y_mm=0., release_start_us=100.)

    def test_missing_or_nonunique_native_exit_is_a_clear_negative_result(self):
        for row in (dict(status="no_unique_exit", phase="trial_a", pulse_time_us=101., evidence={"raw_logs": ["native.log"]}),
                    dict(status="no_unique_exit", phase="trial_a", evidence={"raw_logs": ["native.log"]}),
                    {"pulse_time_us": 101., "evidence": {"raw_logs": ["native.log"]}}):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "no unique measured exit"):
                propose_common_pulse([row], target_y_mm=0., release_start_us=100.)

    def test_exact_native_hit_needs_no_interpolated_claim(self):
        result = propose_common_pulse([ray(101., 0.)], target_y_mm=0., release_start_us=100.)
        self.assertFalse(result["native_check_required"])
        self.assertEqual(result["proposal_basis"], "recorded_reference_exit_at_target")

    def test_frozen_common_clock_reports_the_actual_residual_without_acceptance_threshold(self):
        result = freeze_common_pulse_decision(ray(102., .12), target_y_mm=0.,
                                             release_start_us=100., field_identity={"fields": ["frozen"]},
                                             voltage_calibration=dict(inner_correction_v=-1., release_hp_common_correction_v=.2))
        self.assertEqual(result["actual_pulse_time_us"], 102.)
        self.assertEqual(result["reference_centering_residual_mm"], .12)
        self.assertNotIn("passed", result)
        self.assertTrue(result["pressure_arms_share_clock"])


if __name__ == "__main__":
    unittest.main()
