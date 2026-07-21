from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import plot_s1_loss_atlas as module  # noqa: E402


class S1LossAtlasTests(unittest.TestCase):
    def test_terminal_log_maps_solver_rows_back_to_particle_ids(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            log = Path(root) / "simion.log"
            log.write_text(
                "TRACE: handoff_terminal_raw ion=1 instance=4 instrument_time_us=85 "
                "x_mm=10 y_mm=2 z_mm=0 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=-1\n"
                "TRACE: handoff_terminal_raw ion=2 instance=1 instrument_time_us=86 "
                "x_mm=-2 y_mm=3 z_mm=-49 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=-1\n",
                encoding="utf-8",
            )
            mapping = pd.DataFrame({"solver_row_index": [1, 2], "particle_id": [7, 11]})
            result = module.parse_terminal_log(log, mapping)
            self.assertEqual(result["particle_id"].tolist(), [7, 11])
            self.assertEqual(result["detector_hit"].tolist(), [True, False])


if __name__ == "__main__":
    unittest.main()
