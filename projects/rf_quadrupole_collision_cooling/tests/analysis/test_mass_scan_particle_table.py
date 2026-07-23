from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import generate_mass_scan_particle_table as MODULE


PROJECT_ROOT = Path(__file__).parents[2]


class MassScanParticleTableTests(unittest.TestCase):
    def test_generator_preserves_paired_phase_space(self) -> None:
        source = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"
        mode = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "scan.ion"
            metadata = Path(directory) / "scan.json"
            result = MODULE.generate(source, mode, table, metadata)
            rows = list(csv.reader(table.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(result["particles"], 700)
            self.assertEqual(len(rows), 700)
        self.assertEqual(float(rows[0][1]), 96.0)
        self.assertEqual(float(rows[100][1]), 99.0)
        self.assertEqual(rows[0][0], rows[100][0])
        self.assertEqual(rows[0][2:], rows[100][2:])

    def test_mass_list_rejects_duplicates(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MODULE.validate_masses([96.0, 100.0, 100.0])


if __name__ == "__main__":
    unittest.main()
