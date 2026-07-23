from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import csv_columns
from common.contracts.particle_physics import kinetic_energy_ev
from projects.rf_quadrupole_collision_cooling.analysis import (
    migrate_legacy_component_particle_state as module,
)


class LegacyComponentParticleStateMigrationTests(unittest.TestCase):
    def test_explicit_bindings_produce_valid_common_v1_without_rewriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.csv"
            output = root / "common.csv"
            metadata = root / "migration.json"
            row = {name: "1" for name in module.LEGACY_25_COLUMNS}
            row.update({
                "parent_particle_id": "",
                "generation": "0",
                "source_component_id": "rf",
                "target_component_id": "oatof",
                "state_event": "component_handoff",
                "frame_id": "instrument_global",
                "clock_epoch_id": "epoch.v1",
                "instrument_time_us": "10",
                "lineage_age_us": "5",
                "particle_age_us": "5",
                "last_component_elapsed_time_us": "5",
                "lineage_birth_time_us": "5",
                "particle_birth_time_us": "5",
                "mass_to_charge_Th": "999",
                "mass_amu": "100",
                "charge_state": "1",
                "position_x_mm": "0",
                "position_y_mm": "0",
                "position_z_mm": "0",
                "velocity_x_m_s": "1000",
                "velocity_y_m_s": "0",
                "velocity_z_m_s": "0",
                "kinetic_energy_eV": "999",
                "source_rf_phase_rad": "1.25",
            })
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=module.LEGACY_25_COLUMNS,
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerow(row)
            before = source.read_bytes()
            result = module.migrate(
                source,
                output,
                metadata,
                species_id="ion_100amu_q1",
                particle_weight=2.5,
                phase_reference_id="rf_drive.v1",
            )
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(result["source_preserved"])
            with output.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, csv_columns())
                migrated = next(reader)
            self.assertEqual(migrated["species_id"], "ion_100amu_q1")
            self.assertEqual(float(migrated["particle_weight"]), 2.5)
            self.assertEqual(migrated["phase_reference_id"], "rf_drive.v1")
            self.assertEqual(float(migrated["phase_rad"]), 1.25)
            self.assertEqual(float(migrated["mass_to_charge_Th"]), 100.0)
            self.assertAlmostEqual(
                float(migrated["kinetic_energy_eV"]),
                kinetic_energy_ev(100.0, 1000.0, 0.0, 0.0),
            )

    def test_missing_or_invalid_bindings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.csv"
            with self.assertRaisesRegex(ValueError, "bindings are required"):
                module.migrate(
                    missing,
                    root / "out.csv",
                    root / "metadata.json",
                    species_id="",
                    particle_weight=1.0,
                    phase_reference_id="rf_drive.v1",
                )
            with self.assertRaisesRegex(ValueError, "finite and positive"):
                module.migrate(
                    missing,
                    root / "out.csv",
                    root / "metadata.json",
                    species_id="ion_100amu_q1",
                    particle_weight=0.0,
                    phase_reference_id="rf_drive.v1",
                )


if __name__ == "__main__":
    unittest.main()
