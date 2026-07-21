import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[2] / "analysis" / "compare_rf_continuous_shield_3d.py"
SPEC = importlib.util.spec_from_file_location("compare_rf_continuous_shield_3d", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def table(scale: float = 1.0) -> pd.DataFrame:
    theta = np.arange(4) * np.pi / 2
    return pd.DataFrame(
        {
            "sample_z_mm": 85.4,
            "sample_radius_mm": 1.0,
            "theta_rad": theta,
            "evaluation_z_mm": 85.4,
            "evaluation_radius_mm": 1.0,
            "x_mm": np.cos(theta),
            "y_mm": np.sin(theta),
            "Ex_V_per_m": scale * np.ones(4),
            "Ey_V_per_m": np.zeros(4),
            "Ez_V_per_m": np.zeros(4),
        }
    )


class CompareContinuousShield3DTests(unittest.TestCase):
    def test_vector_rms_comparison(self) -> None:
        result = MODULE.compare(table(1.1), table(1.0))
        self.assertTrue(np.isclose(result.iloc[0]["delta_vector_rms_relative_to_reference"], 0.1))
        self.assertFalse(bool(result.iloc[0]["boundary_inset_used"]))

    def test_coordinate_mismatch_is_rejected(self) -> None:
        candidate = table()
        candidate.loc[0, "x_mm"] += 0.01
        with self.assertRaisesRegex(ValueError, "do not share x_mm"):
            MODULE.compare(candidate, table())


if __name__ == "__main__":
    unittest.main()
