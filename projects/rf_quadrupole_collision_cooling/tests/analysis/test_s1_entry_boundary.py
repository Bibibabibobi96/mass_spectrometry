from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd


from projects.rf_quadrupole_collision_cooling.analysis import rebuild_s1_entry_boundary as module


class S1EntryBoundaryTests(unittest.TestCase):
    def test_legacy_comparison_rejects_any_non_x_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "old.csv"
            new = root / "new.csv"
            pd.DataFrame([{"particle_id": 1, "position_x_mm": -62.8, "velocity_x_m_s": 1.0}]).to_csv(old, index=False)
            pd.DataFrame([{"particle_id": 1, "position_x_mm": -67.8, "velocity_x_m_s": 2.0}]).to_csv(new, index=False)
            with self.assertRaisesRegex(ValueError, "fields other than position_x_mm"):
                module._compare_legacy_rows(module._read_rows(old), module._read_rows(new))

    def test_legacy_comparison_accepts_a_rigid_x_only_repair(self) -> None:
        old = [{"particle_id": "1", "position_x_mm": "-62.8", "velocity_x_m_s": "1"}]
        new = [{"particle_id": "1", "position_x_mm": "-67.8", "velocity_x_m_s": "1"}]
        result = module._compare_legacy_rows(old, new)
        self.assertTrue(result["only_position_x_changed"])
        self.assertAlmostEqual(result["rigid_position_x_shift_mm"], -5.0)

    def test_legacy_25_comparison_maps_rf_phase_and_labels_schema(self) -> None:
        old = {name: "1" for name in module.LEGACY_25_COLUMNS}
        old["position_x_mm"] = "-62.8"
        old["source_rf_phase_rad"] = "1.25"
        new = {name: value for name, value in old.items() if name != "source_rf_phase_rad"}
        new["position_x_mm"] = "-67.8"
        new["phase_rad"] = "1.25"
        result = module._compare_legacy_rows([old], [new])
        self.assertEqual(
            result["comparison_source_schema"],
            "legacy_25_column_component_handoff",
        )


if __name__ == "__main__":
    unittest.main()
