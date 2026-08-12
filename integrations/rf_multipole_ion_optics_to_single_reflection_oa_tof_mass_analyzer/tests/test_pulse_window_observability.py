from __future__ import annotations

import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.pulse_window_observability import (
    build_lua_extension,
    parse_observation_log,
    predeclared_times_us,
)


class PulseWindowObservabilityTests(unittest.TestCase):
    def test_schedule_contains_center_endpoints_and_respects_spacing(self) -> None:
        times = predeclared_times_us(31.81366987147908)
        self.assertEqual(len(times), 181)
        self.assertAlmostEqual(times[0], 31.31366987147908)
        self.assertAlmostEqual(times[90], 31.81366987147908)
        self.assertAlmostEqual(times[-1], 32.31366987147908)
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:], strict=False)) * 1000, 5.68)

    def test_lua_holds_accelerator_off_and_terminates_after_exact_sampling(self) -> None:
        lua = build_lua_extension((1.0, 1.005, 1.01))
        self.assertIn("handoff_pulse_mode=2", lua)
        self.assertIn("remaining=target-single_flight_instrument_time_us()", lua)
        self.assertIn("pulse_window_state particle_id=%d", lua)
        self.assertIn("pulse_window_complete[ion_number]=true; ion_splat=1", lua)
        self.assertNotIn("detector_crossing", lua)

    def test_parser_accepts_exact_states_and_complete_terminal_census(self) -> None:
        text = "\n".join((
            "TRACE: pulse_window_state particle_id=1 sample_index=1 instrument_time_us=1 x_mm=2 y_mm=3 z_mm=4 vx_mm_per_us=5 vy_mm_per_us=6 vz_mm_per_us=7 alive=1 instance=3",
            "TRACE: pulse_window_terminal particle_id=1 instrument_time_us=1.01 reason=window_complete instance=3",
            "TRACE: pulse_window_terminal particle_id=2 instrument_time_us=.9 reason=native_splat_before_window instance=3",
        ))
        states, terminals = parse_observation_log(text, (1.0, 1.005, 1.01), launched_count=2)
        self.assertEqual(len(states), 1)
        self.assertEqual(len(terminals), 2)

    def test_parser_rejects_detector_outcome_and_incomplete_census(self) -> None:
        with self.assertRaisesRegex(ValueError, "detector outcome"):
            parse_observation_log("TRACE: detector_crossing", (1.0, 1.005, 1.01), launched_count=1)
        with self.assertRaisesRegex(ValueError, "terminal census"):
            parse_observation_log("", (1.0, 1.005, 1.01), launched_count=1)


if __name__ == "__main__":
    unittest.main()
