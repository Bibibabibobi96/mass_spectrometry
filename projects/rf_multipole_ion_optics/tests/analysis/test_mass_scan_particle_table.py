from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    prepare_simion_scan as MODULE,
)
from projects.rf_multipole_ion_optics.core import paired_mass_scan
from projects.rf_multipole_ion_optics.core.mass_response import load_ion_masses


PROJECT_ROOT = Path(__file__).parents[2]


class MassScanParticleTableTests(unittest.TestCase):
    def test_generator_preserves_paired_phase_space(self) -> None:
        source = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "particles" / "official_fixed_100.ion"
        mode = PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json"
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "scan.ion"
            metadata = Path(directory) / "scan.json"
            result = MODULE.generate(source, mode, table, metadata)
            rows = list(csv.reader(table.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(result["particles"], 700)
            self.assertEqual(result["charge_state"], 1)
            self.assertEqual(result["species_scope"], "positive_single_charge_mass_amu_equals_mass_to_charge_Th")
            self.assertEqual(len(rows), 700)
        self.assertEqual(float(rows[0][1]), 96.0)
        self.assertEqual(float(rows[100][1]), 99.0)
        self.assertEqual(rows[0][0], rows[100][0])
        self.assertEqual(rows[0][2:], rows[100][2:])

    def test_mass_list_rejects_duplicates(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MODULE.validate_masses([96.0, 100.0, 100.0])

    def test_readers_and_both_generators_reject_unsupported_ion_species(self) -> None:
        source = PROJECT_ROOT / "variants/quadrupole/config/particles/official_fixed_100.ion"
        original = next(csv.reader(source.read_text(encoding="utf-8").splitlines()))
        for column, value in [(1, value) for value in ("0", "-1", "nan", "inf")] + [
            (2, value) for value in ("2", "-1", "0", "1.5", "nan", "inf", True)
        ]:
            with self.subTest(column=column, value=value), tempfile.TemporaryDirectory() as temporary:
                row = original.copy()
                row[column] = value
                with self.assertRaises(ValueError):
                    paired_mass_scan.build_paired_ion_rows([row], [96, 100, 106])
                root = Path(temporary)
                path = root / "source.ion"
                with path.open("w", newline="") as stream:
                    csv.writer(stream).writerow(row)
                for reader in (paired_mass_scan.load_ion_rows, load_ion_masses):
                    with self.assertRaises(ValueError):
                        reader(path)
                with self.assertRaises(ValueError):
                    paired_mass_scan.generate_paired_ion_table(
                        path, root / "scan.ion", root / "scan.json", [96, 100, 106], 1, {},
                    )
                with self.assertRaises(ValueError):
                    paired_mass_scan.generate_paired_case_tables(path, root / "cases", [96, 100, 106], 1)
                self.assertFalse((root / "scan.ion").exists())
                self.assertFalse((root / "cases").exists())


if __name__ == "__main__":
    unittest.main()
