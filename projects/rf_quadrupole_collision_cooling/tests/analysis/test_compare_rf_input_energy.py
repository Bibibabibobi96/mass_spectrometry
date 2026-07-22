from __future__ import annotations

import unittest

import numpy as np
import pandas as pd


from projects.rf_quadrupole_collision_cooling.analysis import compare_rf_input_energy as module


class RfInputEnergyComparisonTests(unittest.TestCase):
    def test_describe_reports_rms_and_energy(self) -> None:
        events = pd.DataFrame([
            {"event": "handoff", "kinetic_energy_eV": 5.0, "radial_position_mm": 0.3,
             "divergence_angle_deg": 4.0, "global_time_us": 30.0},
            {"event": "handoff", "kinetic_energy_eV": 5.2, "radial_position_mm": 0.4,
             "divergence_angle_deg": 3.0, "global_time_us": 32.0},
        ])
        result = module.describe(events)
        self.assertAlmostEqual(result["mean_energy_eV"], 5.1)
        self.assertAlmostEqual(result["rms_radial_position_mm"], np.sqrt(0.125))
        self.assertEqual(result["transmitted"], 2)


if __name__ == "__main__":
    unittest.main()
