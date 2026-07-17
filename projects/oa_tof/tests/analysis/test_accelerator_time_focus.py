from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR / "analysis"))

from accelerator_time_focus import derive, focus_drift_mm


class AcceleratorTimeFocusTest(unittest.TestCase):
    def test_formal_engineering_rounding_has_submicron_focus_residual(self) -> None:
        drift = focus_drift_mm(2240.0, 1760.0, 3.0, 16.83)
        self.assertAlmostEqual(drift, 0.000544666187299)
        self.assertLess(drift, 0.001)

    def test_grid_aligned_candidate_preserves_global_focus(self) -> None:
        contract_path = (
            PROJECT_DIR
            / "config"
            / "candidates"
            / "accelerator_grid_aligned_strict_focus.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        result = derive(contract)

        for actual, expected in zip(
            result["ring_centers_local_mm"], [5.8, 8.6, 11.4, 14.2, 17.0], strict=True
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(result["focus_drift_after_grid2_mm"], 0.12918680341103)
        self.assertAlmostEqual(result["assembly_translation_z_mm"], -0.098642137223724)
        self.assertAlmostEqual(
            result["focus_global_z_mm"], result["reference_global_focus_z_mm"], places=12
        )

    def test_derived_geometry_rejects_unequal_pitch_contract(self) -> None:
        contract = {
            "design": {
                "target_global_focus_z_mm": 19.83,
                "local_geometry_mm": {
                    "d1": 3.0,
                    "d2": 16.8,
                    "ring_count": 5,
                    "ring_pitch": 2.79,
                },
                "electrodes_V": {"repeller": 2240.0, "grid1": 1760.0},
            }
        }
        with self.assertRaisesRegex(ValueError, "equal"):
            derive(contract)


if __name__ == "__main__":
    unittest.main()
