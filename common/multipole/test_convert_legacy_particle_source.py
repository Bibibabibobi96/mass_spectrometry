from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from common.multipole.convert_legacy_particle_source import (
    LEGACY_COLUMNS,
    convert,
)
from common.multipole.particle_source_preflight import AMU_KG, E_CHARGE_C, COLUMNS


class ConvertLegacyParticleSourceTest(unittest.TestCase):
    @staticmethod
    def resolved() -> dict:
        return {
            "role": "multipole_resolved_design_do_not_edit",
            "resolved_sha256": "A" * 64,
            "interfaces_mm": {"entrance": {"particle_plane_z_mm": 0.0}},
            "particle_source": {
                "charge_state": 1,
                "energy_model": {
                    "kind": "monoenergetic",
                    "kinetic_energy_eV": 2.0,
                },
            },
        }

    @staticmethod
    def write_legacy(path: Path, *, energy_eV: float = 2.0) -> list[dict[str, str]]:
        speed = (2 * energy_eV * E_CHARGE_C / (100.0 * AMU_KG)) ** 0.5
        rows = []
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=LEGACY_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for particle_id in range(1, 101):
                row = {
                    "particle_id": str(particle_id),
                    "birth_time_s": f"{particle_id * 1e-9:.17g}",
                    "x_mm": f"{particle_id * 1e-5:.17g}",
                    "y_mm": f"{-particle_id * 1e-5:.17g}",
                    "z_mm": "0",
                    "vx_m_s": "0",
                    "vy_m_s": "0",
                    "vz_m_s": f"{speed:.17g}",
                }
                rows.append(row)
                writer.writerow(row)
        return rows

    def test_preserves_eight_fields_and_appends_governed_species(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy.csv"
            output = root / "canonical.csv"
            expected = self.write_legacy(legacy)
            lineage = convert(
                legacy,
                self.resolved(),
                {"mass_amu": 100.0, "charge_state": 1},
                output,
            )
            with output.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                actual = list(reader)
                self.assertEqual(reader.fieldnames, COLUMNS)
        self.assertEqual(
            [{column: row[column] for column in LEGACY_COLUMNS} for row in actual],
            expected,
        )
        self.assertEqual({row["mass_amu"] for row in actual}, {"100"})
        self.assertEqual({row["charge_state"] for row in actual}, {"1"})
        self.assertEqual(
            lineage["canonical_preflight"]["energy_model"]["kinetic_energy_eV"],
            2.0,
        )
        self.assertEqual(lineage["canonical_preflight"]["particle_count"], 100)

    def test_nonconforming_energy_fails_without_publishing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy.csv"
            output = root / "canonical.csv"
            self.write_legacy(legacy, energy_eV=1.9)
            with self.assertRaisesRegex(ValueError, "kinetic energy differs"):
                convert(
                    legacy,
                    self.resolved(),
                    {"mass_amu": 100.0, "charge_state": 1},
                    output,
                )
            self.assertFalse(output.exists())

    def test_species_charge_must_match_resolved_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy.csv"
            self.write_legacy(legacy)
            with self.assertRaisesRegex(ValueError, "charge differs"):
                convert(
                    legacy,
                    self.resolved(),
                    {"mass_amu": 100.0, "charge_state": 2},
                    root / "canonical.csv",
                )


if __name__ == "__main__":
    unittest.main()
