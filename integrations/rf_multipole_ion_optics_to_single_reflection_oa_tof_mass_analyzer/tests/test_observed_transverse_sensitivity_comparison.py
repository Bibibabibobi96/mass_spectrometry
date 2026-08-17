from __future__ import annotations

import unittest

import pandas as pd

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_observed_transverse_sensitivity import (
    compare_frames,
)


def _frame(offset: float = 0.0, count: int = 100) -> pd.DataFrame:
    rows = []
    for particle_id in range(1, count + 1):
        for event in (
            "source_release",
            "multipole_handoff",
            "pre_pulse_state",
            "local_accelerator_exit",
            "detector_crossing",
        ):
            rows.append(
                {
                    "particle_id": particle_id,
                    "event": event,
                    "instrument_time_us": 10.0 + particle_id * 1e-3 + offset,
                    "x_mm": float(particle_id) + offset,
                    "y_mm": offset,
                    "z_mm": 0.0,
                    "vx_mm_per_us": 1.0 + offset,
                    "vy_mm_per_us": 2.0,
                    "vz_mm_per_us": 3.0,
                }
            )
    return pd.DataFrame(rows)


class ObservedTransverseSensitivityComparisonTests(unittest.TestCase):
    def test_strict_100_particle_detector_pair(self) -> None:
        peak = {"mean_tof_us": 1.0, "std_tof_ns": 2.0, "direct_fwhm_tof_ns": 3.0, "mass_resolution": 4.0}
        result, rows = compare_frames(_frame(), _frame(1e-3), peak, peak)
        self.assertEqual(result["status"], "FUNCTIONAL_ONLY")
        self.assertFalse(result["formal_gate_passed"])
        self.assertEqual(len(rows), 100)
        self.assertAlmostEqual(rows[0]["delta_time_full_minus_collapsed_ns"], 1.0)
        self.assertEqual(result["detector_identity"]["transverse_collapsed_particles"], 100)
        self.assertAlmostEqual(result["peak_metrics"]["full_minus_collapsed"]["std_tof_pct"], 0.0)

    def test_missing_detector_velocity_is_published_as_null(self) -> None:
        peak = {"mean_tof_us": 1.0, "std_tof_ns": 2.0, "direct_fwhm_tof_ns": 3.0, "mass_resolution": 4.0}
        c_frame = _frame()
        d_frame = _frame(1e-3)
        for frame in (c_frame, d_frame):
            frame[["vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us"]] = float("nan")
        result, rows = compare_frames(c_frame, d_frame, peak, peak)
        self.assertIsNone(rows[0]["delta_vx_full_minus_collapsed_m_s"])
        velocity = result["paired_detector_deltas_full_minus_collapsed"]["velocity_delta_norm_m_s"]
        self.assertEqual(velocity["available_count"], 0)
        self.assertIsNone(velocity["rms"])

    def test_missing_detector_id_fails_closed(self) -> None:
        peak = {"mean_tof_us": 1.0, "std_tof_ns": 2.0, "direct_fwhm_tof_ns": 3.0, "mass_resolution": 4.0}
        with self.assertRaisesRegex(ContractError, "exactly 1..100"):
            compare_frames(_frame(), _frame(count=99), peak, peak)


if __name__ == "__main__":
    unittest.main()
