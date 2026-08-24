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
    def test_n1000_full_population_is_the_exact_n2000_prefix(self) -> None:
        repository = Path(__file__).parents[3]
        source_root = repository / "common" / "multipole" / "sources"
        with (source_root / "rf_multipole_steady_candidate_v1_2000.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            parent_rows = list(csv.DictReader(handle))
        with (source_root / "rf_multipole_steady_candidate_v1_n1000.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            child_rows = list(csv.DictReader(handle))
        self.assertEqual(len(parent_rows), 2000)
        self.assertEqual(len(child_rows), 1000)
        self.assertEqual(child_rows, parent_rows[:1000])

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
            )
            first = output.read_bytes()
            build([source], [checkpoints], output, receipt_path, target_count=2)
            self.assertEqual(first, output.read_bytes())
        self.assertEqual(receipt["candidate_eligible_count"], 2)
        self.assertFalse(receipt["selection_uses_detector_outcome"])
        self.assertRegex(receipt["selected_lineage_sha256"], r"^[0-9A-F]{64}$")
        self.assertNotIn("selected_lineage", receipt)
        self.assertNotIn("execution_batch_count", receipt)
        self.assertNotIn("execution_batch_plan", receipt)
        self.assertNotIn("execution_batches", receipt)

    def test_all_eligible_keeps_the_complete_conditional_population(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            checkpoints = root / "checkpoints.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for particle_id in range(1, 7):
                    writer.writerow({
                        "particle_id": particle_id, "birth_time_s": particle_id * 1e-9,
                        "x_mm": 0, "y_mm": 0, "z_mm": -1.5, "vx_m_s": 0,
                        "vy_m_s": 0, "vz_m_s": 1000, "mass_amu": 100,
                        "charge_state": 1,
                    })
            checkpoints.write_text(
                "particle_id,event,pulse_eligibility\n"
                "1,pre_pulse_state,eligible\n2,pre_pulse_state,eligible\n"
                "3,pre_pulse_state,outside_transverse_bore\n"
                "4,pre_pulse_state,eligible\n5,pre_pulse_state,eligible\n"
                "6,pre_pulse_state,eligible\n",
                encoding="utf-8",
            )
            receipt = build(
                [source], [checkpoints], root / "selected.csv", root / "receipt.json",
                target_count=None, selection_mode="all_eligible",
            )
            self.assertEqual(receipt["selected_count"], 5)
            self.assertEqual(receipt["unselected_eligible_count"], 0)
            self.assertIsNone(receipt["selection_seed"])
            self.assertNotIn("execution_batch_plan", receipt)
            self.assertEqual(
                receipt["selected_population_contract"]["efficiency_denominator"],
                "candidate_launched_count",
            )

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
