from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.build_steady_state_source import (
    SOURCE_COLUMNS,
    build,
)


class SteadyStateSourceTests(unittest.TestCase):
    def test_selection_uses_only_prepulse_eligibility_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            checkpoints = root / "checkpoints.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for particle_id in range(1, 5):
                    writer.writerow({
                        "particle_id": particle_id, "birth_time_s": particle_id * 1e-9,
                        "x_mm": 0, "y_mm": 0, "z_mm": -1.5, "vx_m_s": 0,
                        "vy_m_s": 0, "vz_m_s": 1000, "mass_amu": 100,
                        "charge_state": 1,
                    })
            checkpoints.write_text(
                "particle_id,event,pulse_eligibility\n"
                "1,pre_pulse_state,eligible\n"
                "2,pre_pulse_state,outside_transverse_bore\n"
                "3,pre_pulse_state,eligible\n"
                "4,multipole_handoff,\n",
                encoding="utf-8",
            )
            output = root / "selected.csv"
            receipt_path = root / "receipt.json"
            receipt = build(
                [source], [checkpoints], output, receipt_path, target_count=2,
                batch_directory=root / "batches", batch_count=2,
            )
            first = output.read_bytes()
            build([source], [checkpoints], output, receipt_path, target_count=2)
            self.assertEqual(first, output.read_bytes())
        self.assertEqual(receipt["candidate_eligible_count"], 2)
        self.assertFalse(receipt["selection_uses_detector_outcome"])
        self.assertRegex(receipt["selected_lineage_sha256"], r"^[0-9A-F]{64}$")
        self.assertNotIn("selected_lineage", receipt)
        self.assertEqual(receipt["execution_batch_count"], 2)
        self.assertEqual([item["global_particle_id_offset"] for item in receipt["execution_batches"]], [0, 1])

    def test_detector_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            checkpoints = root / "checkpoints.csv"
            source.write_text(",".join(SOURCE_COLUMNS) + "\n", encoding="utf-8")
            checkpoints.write_text(
                "particle_id,event,pulse_eligibility\n1,detector_crossing,\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "terminate before detector"):
                build([source], [checkpoints], root / "out.csv", root / "receipt.json", 1)


if __name__ == "__main__":
    unittest.main()
