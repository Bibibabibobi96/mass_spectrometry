from __future__ import annotations

import unittest
import pandas as pd


from projects.rf_quadrupole_collision_cooling.analysis import compare_s1_capture_to_oatof_ideal_source as module


class S1CaptureIdealComparisonTests(unittest.TestCase):
    def test_enrich_capture_derives_energy_time_and_direction(self) -> None:
        capture = pd.DataFrame([{
            "particle_id": 7, "instrument_time_us": 55.0,
            "x_mm": -48.8, "y_mm": 0.0, "z_mm": -18.4,
            "vx_m_s": 2000.0, "vy_m_s": 100.0, "vz_m_s": 0.0,
            "inside_oatof_ideal_reference_volume": 1,
        }])
        entry = pd.DataFrame([{
            "particle_id": 7, "instrument_time_us": 50.0,
            "mass_amu": 100.0, "charge_state": 1,
        }])
        result = module.enrich_capture(capture, entry)
        self.assertTrue(result.iloc[0]["inside_reference"])
        self.assertAlmostEqual(result.iloc[0]["storage_duration_us"], 5.0)
        self.assertGreater(result.iloc[0]["energy_eV"], 0.0)
        self.assertGreater(result.iloc[0]["angle_deg"], 0.0)

    def test_unknown_particle_id_is_rejected(self) -> None:
        capture = pd.DataFrame([{
            "particle_id": 9, "instrument_time_us": 55.0,
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "vx_m_s": 1, "vy_m_s": 0, "vz_m_s": 0,
            "inside_oatof_ideal_reference_volume": 0,
        }])
        entry = pd.DataFrame([{
            "particle_id": 7, "instrument_time_us": 50.0,
            "mass_amu": 100.0, "charge_state": 1,
        }])
        with self.assertRaisesRegex(ValueError, "subset"):
            module.enrich_capture(capture, entry)


if __name__ == "__main__":
    unittest.main()
