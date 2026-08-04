from __future__ import annotations

import math
import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_apertures import (
    _pair_event,
)


def _state(time_us: float, x_mm: float) -> dict[str, float]:
    return {
        "time_us": time_us,
        "x_mm": x_mm,
        "y_mm": 0.0,
        "z_mm": 0.0,
        "vx_mm_per_us": 1.0,
        "vy_mm_per_us": 0.0,
        "vz_mm_per_us": 0.0,
    }


class SingleFlightApertureComparisonTests(unittest.TestCase):
    def test_pair_event_preserves_common_and_unique_identities(self) -> None:
        metrics, rows = _pair_event(
            {1: _state(10.0, 1.0), 2: _state(20.0, 2.0)},
            {2: _state(20.002, 2.1), 3: _state(30.0, 3.0)},
        )
        self.assertEqual(metrics["common_particles"], 1)
        self.assertEqual(metrics["wide_only_particles"], 1)
        self.assertEqual(metrics["small_only_particles"], 1)
        self.assertAlmostEqual(metrics["jaccard_identity"], 1 / 3)
        self.assertEqual(rows[0]["particle_id"], 2)
        self.assertAlmostEqual(rows[0]["delta_time_small_minus_wide_ns"], 2.0)
        self.assertAlmostEqual(metrics["position_vector_rms_mm"], 0.1)

    def test_pair_event_supports_detector_rows_without_velocity(self) -> None:
        wide = _state(1.0, 0.0)
        small = _state(1.001, 0.0)
        for state in (wide, small):
            state["vx_mm_per_us"] = math.nan
            state["vy_mm_per_us"] = math.nan
            state["vz_mm_per_us"] = math.nan
        metrics, _ = _pair_event({7: wide}, {7: small})
        self.assertIsNone(metrics["velocity_vector_rms_m_s"])
        self.assertAlmostEqual(metrics["rms_delta_time_ns"], 1.0)


if __name__ == "__main__":
    unittest.main()
