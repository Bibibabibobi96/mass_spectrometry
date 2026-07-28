import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[2] / "analysis" / "compare_rf_rod_region_swept_mesh.py"
SPEC = importlib.util.spec_from_file_location("compare_rf_rod_region_swept_mesh", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def field_table(layers: int) -> pd.DataFrame:
    rows = []
    for z_value in (10.0, 45.6):
        for theta in np.arange(4) * np.pi / 2:
            rows.append(
                {
                    "sample_z_mm": z_value,
                    "sample_radius_mm": 1.0,
                    "theta_rad": theta,
                    "Ex_V_per_m": np.cos(theta),
                    "Ey_V_per_m": -np.sin(theta),
                    "Ez_V_per_m": (2e-5 if layers == 20 else 1e-5),
                }
            )
    return pd.DataFrame(rows)


class SweptMeshComparisonTests(unittest.TestCase):
    def test_accepts_converged_reference(self) -> None:
        reference = field_table(40).query("sample_z_mm == 10").drop(columns=["sample_z_mm", "Ez_V_per_m"])
        contract = {
            "acceptance": {
                "maximum_relative_vector_rms_to_converged_2d": 1e-3,
                "maximum_relative_vector_rms_20_to_40_layers": 1e-4,
                "maximum_axial_to_transverse_field_rms": 1e-4,
            }
        }
        report = MODULE.compare(reference, field_table(20), field_table(40), contract)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["selected_reference"]["axial_layers"], 40)

    def test_rejects_coordinate_mismatch(self) -> None:
        reference = field_table(40).query("sample_z_mm == 10").drop(columns=["sample_z_mm", "Ez_V_per_m"])
        fine = field_table(40)
        fine.loc[0, "theta_rad"] += 0.1
        contract = {"acceptance": {
            "maximum_relative_vector_rms_to_converged_2d": 1e-3,
            "maximum_relative_vector_rms_20_to_40_layers": 1e-4,
            "maximum_axial_to_transverse_field_rms": 1e-4,
        }}
        with self.assertRaisesRegex(ValueError, "do not share theta_rad"):
            MODULE.compare(reference, field_table(20), fine, contract)

    def test_localized_candidate_requires_every_group(self) -> None:
        reference = field_table(40)
        candidate = reference.copy()
        candidate.loc[candidate["sample_z_mm"] == 45.6, "Ex_V_per_m"] *= 1.0002
        contract = {
            "acceptance": {"maximum_axial_to_transverse_field_rms": 1e-4},
            "localized_transverse_mesh": {"maximum_relative_vector_rms_to_full_vacuum_reference": 1e-4},
        }
        report = MODULE.localized_comparison(reference, candidate, contract)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["every_axial_section_relative_vector_rms"])


if __name__ == "__main__":
    unittest.main()
