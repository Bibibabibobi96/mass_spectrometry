import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[2] / "analysis" / "analyze_rf_continuous_shield_3d.py"
SPEC = importlib.util.spec_from_file_location("analyze_rf_continuous_shield_3d", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ContinuousShield3DAnalysisTests(unittest.TestCase):
    def test_characterize_recovers_quadrupole_and_axial_ratio(self) -> None:
        theta = np.arange(72) * 2.0 * np.pi / 72
        potential = 20.0 * np.cos(2.0 * theta) + 0.2 * np.cos(6.0 * theta)
        samples = pd.DataFrame(
            {
                "shield_inner_radius_mm": 19.776,
                "mesh_hmax_mm": 0.5,
                "sample_z_mm": 85.4,
                "sample_radius_mm": 3.6,
                "theta_rad": theta,
                "potential_V": potential,
                "Ex_V_per_m": np.full(72, 3.0),
                "Ey_V_per_m": np.full(72, 4.0),
                "Ez_V_per_m": np.full(72, 1.0),
            }
        )
        row = MODULE.characterize(samples).iloc[0]
        self.assertTrue(np.isclose(row["order_2_amplitude_V"], 20.0))
        self.assertTrue(np.isclose(row["order_6_relative_to_order_2"], 0.01))
        self.assertTrue(np.isclose(row["axial_to_transverse_rms"], 0.2))

    def test_characterize_rejects_missing_axial_field(self) -> None:
        samples = pd.DataFrame({"shield_inner_radius_mm": [19.776]})
        with self.assertRaisesRegex(ValueError, "missing columns"):
            MODULE.characterize(samples)


if __name__ == "__main__":
    unittest.main()
