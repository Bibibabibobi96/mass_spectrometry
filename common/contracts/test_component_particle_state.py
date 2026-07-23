import csv
import math
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import (
    SCHEMA_VERSION,
    csv_columns,
    load_schema,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev


def valid_row(particle_id: int = 7) -> dict[str, object]:
    mass_amu = 100.0
    velocity = (1000.0, -2000.0, 3000.0)
    return {
        "particle_id": particle_id,
        "parent_particle_id": "",
        "generation": 0,
        "species_id": "ion_100amu_q1",
        "particle_weight": 1.0,
        "source_component_id": "source_component",
        "target_component_id": "target_component",
        "state_event": "component_exit",
        "frame_id": "instrument_global",
        "clock_epoch_id": "instrument_clock_epoch.v1",
        "instrument_time_us": 12.5,
        "lineage_age_us": 7.5,
        "particle_age_us": 7.5,
        "last_component_elapsed_time_us": 2.0,
        "lineage_birth_time_us": 5.0,
        "particle_birth_time_us": 5.0,
        "mass_to_charge_Th": 100.0,
        "mass_amu": mass_amu,
        "charge_state": 1,
        "position_x_mm": 1.0,
        "position_y_mm": -2.0,
        "position_z_mm": 3.0,
        "velocity_x_m_s": velocity[0],
        "velocity_y_m_s": velocity[1],
        "velocity_z_m_s": velocity[2],
        "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity),
        "phase_reference_id": "source_rf.v1",
        "phase_rad": 1.2,
    }


class ComponentParticleStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "state.csv"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(
        self,
        rows: list[dict[str, object]],
        columns: list[str] | None = None,
    ) -> None:
        fields = columns or csv_columns()
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_accepts_complete_transfer_state(self) -> None:
        self.write([valid_row(7), valid_row(9)])
        report = validate_component_particle_state_csv(self.path)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["particles"], 2)
        self.assertEqual(report["frame_ids"], ["instrument_global"])
        self.assertEqual(report["clock_epoch_ids"], ["instrument_clock_epoch.v1"])

    def test_schema_version_matches_validator(self) -> None:
        self.assertEqual(load_schema()["x-csv-schema-version"], SCHEMA_VERSION)

    def test_rejects_reordered_or_extended_columns(self) -> None:
        columns = csv_columns()
        columns[0], columns[1] = columns[1], columns[0]
        self.write([valid_row()], columns)
        with self.assertRaisesRegex(ValueError, "columns differ"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_duplicate_particle_identity(self) -> None:
        self.write([valid_row(), valid_row()])
        with self.assertRaisesRegex(ValueError, "duplicate particle_id"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_nonfinite_spatial_state(self) -> None:
        row = valid_row()
        row["velocity_z_m_s"] = math.inf
        self.write([row])
        with self.assertRaisesRegex(ValueError, "must be finite"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_clock_discontinuity(self) -> None:
        row = valid_row()
        row["particle_age_us"] = 6.0
        self.write([row])
        with self.assertRaisesRegex(ValueError, "particle clock residual"):
            validate_component_particle_state_csv(self.path)

    def test_requires_parent_for_descendant(self) -> None:
        row = valid_row()
        row["generation"] = 1
        self.write([row])
        with self.assertRaisesRegex(ValueError, "requires a parent"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_root_with_distinct_lineage_clock(self) -> None:
        row = valid_row()
        row["lineage_birth_time_us"] = 4.0
        row["lineage_age_us"] = 8.5
        self.write([row])
        with self.assertRaisesRegex(ValueError, "root particle clock"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_descendant_born_before_lineage(self) -> None:
        row = valid_row()
        row["generation"] = 1
        row["parent_particle_id"] = 3
        row["particle_birth_time_us"] = 4.0
        row["particle_age_us"] = 8.5
        self.write([row])
        with self.assertRaisesRegex(ValueError, "born before its lineage"):
            validate_component_particle_state_csv(self.path)

    def test_accepts_open_component_and_event_identifiers(self) -> None:
        row = valid_row()
        row["source_component_id"] = "future-source:stage_2"
        row["state_event"] = "custom.exit"
        self.write([row])
        report = validate_component_particle_state_csv(self.path)
        self.assertEqual(report["status"], "PASS")

    def test_accepts_state_without_phase_reference(self) -> None:
        row = valid_row()
        row["phase_reference_id"] = ""
        row["phase_rad"] = ""
        self.write([row])
        self.assertEqual(
            validate_component_particle_state_csv(self.path)["status"],
            "PASS",
        )

    def test_rejects_half_populated_phase_reference(self) -> None:
        row = valid_row()
        row["phase_reference_id"] = ""
        self.write([row])
        with self.assertRaisesRegex(ValueError, "not valid"):
            validate_component_particle_state_csv(self.path)

    def test_accepts_states_before_clock_epoch(self) -> None:
        row = valid_row()
        row["instrument_time_us"] = -2.0
        row["lineage_birth_time_us"] = -9.5
        row["particle_birth_time_us"] = -9.5
        self.write([row])
        self.assertEqual(
            validate_component_particle_state_csv(self.path)["status"],
            "PASS",
        )

    def test_accepts_negative_electron_charge(self) -> None:
        row = valid_row()
        row["species_id"] = "electron"
        row["mass_amu"] = 5.485799090441e-4
        row["charge_state"] = -1
        row["mass_to_charge_Th"] = row["mass_amu"]
        row["kinetic_energy_eV"] = kinetic_energy_ev(
            float(row["mass_amu"]),
            float(row["velocity_x_m_s"]),
            float(row["velocity_y_m_s"]),
            float(row["velocity_z_m_s"]),
        )
        self.write([row])
        self.assertEqual(
            validate_component_particle_state_csv(self.path)["status"],
            "PASS",
        )

    def test_rejects_inconsistent_energy(self) -> None:
        row = valid_row()
        row["kinetic_energy_eV"] = float(row["kinetic_energy_eV"]) + 1.0
        self.write([row])
        with self.assertRaisesRegex(ValueError, "kinetic_energy_eV is inconsistent"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_inconsistent_mass_to_charge(self) -> None:
        row = valid_row()
        row["mass_to_charge_Th"] = 50.0
        self.write([row])
        with self.assertRaisesRegex(ValueError, "mass_to_charge_Th is inconsistent"):
            validate_component_particle_state_csv(self.path)


if __name__ == "__main__":
    unittest.main()
