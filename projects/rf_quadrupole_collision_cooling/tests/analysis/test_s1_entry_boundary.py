from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import rebuild_s1_entry_boundary as module  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
