from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import audit_s2_particle_chain as module


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class S2ParticleChainAuditTests(unittest.TestCase):
    def test_audit_distinguishes_aperture_crossing_from_wall_contact(self) -> None:
        contract = json.loads(
            (PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json").read_text(
                encoding="utf-8"
            )
        )
        contract["functional_candidate"]["source_particles"] = 2
        source_rows = [self._source_row(1), self._source_row(2)]
        event_rows = [
            self._event_row(1, "oatof_entry", "transmitted", 0.4, 0.4),
            self._event_row(
                2,
                "downstream_entry_wall",
                "lost",
                0.6,
                0.4,
                reason="outside_rectangular_oatof_entry",
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            events = root / "events.csv"
            config = root / "contract.json"
            self._write_rows(source, source_rows)
            self._write_rows(events, event_rows)
            config.write_text(json.dumps(contract), encoding="utf-8")
            result = module.audit(source, events, config)
        self.assertEqual(result["oatof_entry_crossings"], 1)
        self.assertEqual(result["downstream_entry_wall_losses"], 1)

    @staticmethod
    def _source_row(particle_id: int) -> dict[str, object]:
        return {
            "particle_id": particle_id,
            "frame_id": "oatof_global",
            "clock_epoch_id": "instrument_clock_epoch.v1",
            "instrument_time_us": 30.0,
            "lineage_age_us": 29.0,
            "particle_age_us": 29.0,
            "mass_amu": 100.0,
            "charge_state": 1,
            "position_x_mm": -68.8,
        }

    @staticmethod
    def _event_row(
        particle_id: int,
        event: str,
        status: str,
        y_mm: float,
        z_offset_mm: float,
        reason: str = "none",
    ) -> dict[str, object]:
        velocity = 3100.0
        energy = 0.5 * 100.0 * module.ATOMIC_MASS_KG * velocity**2 / module.ELEMENTARY_CHARGE_C
        return {
            "particle_id": particle_id,
            "event": event,
            "status": status,
            "terminal_reason": reason,
            "frame_id": "oatof_global",
            "clock_epoch_id": "instrument_clock_epoch.v1",
            "instrument_time_us": 30.33,
            "lineage_age_us": 29.33,
            "particle_age_us": 29.33,
            "last_component_elapsed_time_us": 0.33,
            "mass_amu": 100.0,
            "charge_state": 1,
            "position_x_mm": -67.8,
            "position_y_mm": y_mm,
            "position_z_mm": -18.42918680341103 + z_offset_mm,
            "velocity_x_m_s": velocity,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 0.0,
            "kinetic_energy_eV": energy,
            "first_forward_oatof_entry": status == "transmitted",
        }

    @staticmethod
    def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
