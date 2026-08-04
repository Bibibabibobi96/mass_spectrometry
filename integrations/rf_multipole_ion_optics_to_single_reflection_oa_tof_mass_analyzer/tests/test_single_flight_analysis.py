from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import analyze


class SingleFlightAnalysisTests(unittest.TestCase):
    def test_preserves_original_ion_identity_at_all_checkpoints(self) -> None:
        text = "\n".join([
            "TRACE: single_flight_handoff ion=2 instrument_time_us=10 x_mm=-67.8 y_mm=0 z_mm=-18.4 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: local_accelerator_exit ion=2 instrument_time_us=41 x_mm=-67 y_mm=0 z_mm=20 vx_mm_per_us=2 vy_mm_per_us=0 vz_mm_per_us=20",
            "TRACE: detector_crossing ion=2 t=70 x=49 y=0 z=19.83 r=0 zmax=19.83",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            path.write_text(text, encoding="utf-8")
            rows, summary = analyze(path, 3, 100.0)
        self.assertEqual({row["particle_id"] for row in rows}, {2})
        self.assertEqual(summary["census"], {"launched": 3, "multipole_handoff": 1, "local_accelerator_exit": 1, "detector_crossing": 1})
        self.assertIsNone(summary["instrument_clock_peak"])
        self.assertFalse(summary["instrument_clock_peak_is_resolution_claim"])


if __name__ == "__main__":
    unittest.main()
