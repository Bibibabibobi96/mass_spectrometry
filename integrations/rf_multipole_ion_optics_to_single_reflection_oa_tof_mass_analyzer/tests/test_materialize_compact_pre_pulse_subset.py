from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_compact_pre_pulse_subset import (
    materialize_compact_pre_pulse_subset,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    ATTRIBUTION_COLUMNS,
    GLOBAL_COLUMNS,
    materialize_pre_pulse_restart,
)


def _id_sha256(values: list[int]) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest().upper()


class MaterializeCompactPrePulseSubsetTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        state = root / "compact.csv"
        ids = [2, 7]
        with state.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for particle_id in ids:
                velocity = (4000.0, 0.0, float(particle_id))
                writer.writerow({
                    "particle_id": particle_id, "instrument_time_us": "5",
                    "mass_amu": "100", "charge_state": "1", "position_x_mm": "-10",
                    "position_y_mm": "0", "position_z_mm": particle_id,
                    "velocity_x_m_s": velocity[0], "velocity_y_m_s": velocity[1],
                    "velocity_z_m_s": velocity[2],
                    "kinetic_energy_eV": format(kinetic_energy_ev(100, *velocity), ".17g"),
                })
        receipt = root / "compact_receipt.json"
        receipt.write_text(json.dumps({
            "schema_version": 1, "role": "rf_oatof_compact_pre_pulse_trace_handoff_receipt",
            "status": "success", "pulse_disabled": True, "detector_results_used": False,
            "selection_uses_detector_outcome": False,
            "selection": {"mother_population_count": 10, "pulse_eligible_particle_ids": ids},
            "pulse_target_state": {"sha256": hashlib.sha256(state.read_bytes()).hexdigest().upper(),
                "particle_count": 2, "ordered_particle_id_sha256": _id_sha256(ids),
                "source_state_epoch": "pulse_effective_time", "coordinate_frame": "oatof_global_cartesian",
                "clock_basis": "canonical_instrument_time_us", "clock_authority": "detector_blind_native_trace_selection",
                "pulse_effective_time_us": 5.0},
        }) + "\n", encoding="utf-8")
        return state, receipt

    def test_materializes_explicit_source_id_as_attribution_preserving_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, receipt = self._fixture(root)
            output, output_receipt = root / "subset.csv", root / "subset.json"
            result = materialize_compact_pre_pulse_subset(state, receipt, output, output_receipt, ordered_source_particle_ids=[7])
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            _, global_rows, row_map = materialize_pre_pulse_restart(output, 5.0, return_row_map=True)
        self.assertEqual(list(rows[0]), ATTRIBUTION_COLUMNS)
        self.assertEqual(rows[0]["simulation_particle_id"], "1")
        self.assertEqual(rows[0]["source_particle_id"], "7")
        self.assertEqual(global_rows[0]["particle_id"], "1")
        self.assertEqual(row_map, [{"simulation_particle_id": "1", "source_particle_id": "7"}])
        self.assertEqual(result["selection"]["mother_population_count"], 10)
        self.assertEqual(result["pulse_target_state"]["ordered_particle_id_sha256"], _id_sha256([7]))

    def test_rejects_source_id_not_in_detector_blind_compact_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, receipt = self._fixture(root)
            with self.assertRaisesRegex(Exception, "source particle IDs"):
                materialize_compact_pre_pulse_subset(state, receipt, root / "subset.csv", root / "subset.json", ordered_source_particle_ids=[3])


if __name__ == "__main__":
    unittest.main()
