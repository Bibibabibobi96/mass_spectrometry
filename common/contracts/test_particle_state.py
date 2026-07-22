import csv
import tempfile
import unittest
from pathlib import Path

from particle_state import AMU_KG, E_CHARGE_C, canonical_sources


class CanonicalSourceTests(unittest.TestCase):
    def write_source(self, directory: str, include_mass: bool) -> Path:
        path = Path(directory) / "particles.csv"
        fields = ["particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
                  "vx_m_s", "vy_m_s", "vz_m_s"]
        if include_mass:
            fields.append("mass_amu")
        row = {name: 0 for name in fields}
        row.update({"particle_id": 1, "vx_m_s": 1000})
        if include_mass:
            row["mass_amu"] = 40
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerow(row)
        return path

    def test_explicit_mass_is_used_when_table_omits_mass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = canonical_sources(self.write_source(directory, False), mass_amu=80)
        expected = 0.5 * 80 * AMU_KG * 1000**2 / E_CHARGE_C
        self.assertAlmostEqual(source[1]["kinetic_energy_eV"], expected)

    def test_table_mass_has_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = canonical_sources(self.write_source(directory, True), mass_amu=80)
        expected = 0.5 * 40 * AMU_KG * 1000**2 / E_CHARGE_C
        self.assertAlmostEqual(source[1]["kinetic_energy_eV"], expected)

    def test_missing_mass_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_source(directory, False)
            with self.assertRaisesRegex(ValueError, "mass_amu"):
                canonical_sources(path)


if __name__ == "__main__":
    unittest.main()
