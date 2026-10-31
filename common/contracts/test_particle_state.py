import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from particle_state import AMU_KG, E_CHARGE_C, PARTICLE_STATE_COLUMNS, canonical_sources, validate_particle_state


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


class UnknownTerminalStateTests(unittest.TestCase):
    def test_unknown_native_causes_validate_without_changing_source_clock(self):
        contract = json.loads((Path(__file__).resolve().parents[2]/"projects/rf_multipole_ion_optics/variants/quadrupole/config/interface_contract.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root/"particles.csv"
            fields = ["particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu"]
            with source_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(dict(zip(fields, (7, 79.5e-6, 0, 0, 0, 0, 0, 1000, 100))))
            sources = canonical_sources(source_path)
            for reason in ("time_window_end", "ended_without_loss_evidence", "terminal_cause_unresolved"):
                rows = []
                for event in ("source", "terminal"):
                    row = dict.fromkeys(PARTICLE_STATE_COLUMNS, 0)
                    row.update(sources[7])
                    row.update(particle_id=7, event=event, status="alive" if event == "source" else "unknown",
                               terminal_reason="none" if event == "source" else reason)
                    if event == "terminal":
                        row.update(time_us=80., elapsed_time_us=.5)
                    row["rf_phase_rad"] = (2*math.pi*1.1e6*row["time_us"]*1e-6) % (2*math.pi)
                    rows.append(row)
                state = root/"state.csv"
                with state.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.subTest(reason=reason):
                    default = validate_particle_state(state, sources, 1.1e6, 0.)
                    explicit = validate_particle_state(state, sources, 1.1e6, 0., columns=contract["particle_state_columns"], enums=contract["enums"])
                    self.assertEqual(default["status"], "PASS")
                    self.assertEqual(explicit["particles"], 1)
                    self.assertEqual(rows[-1]["particle_id"], 7)
                    self.assertEqual(rows[-1]["elapsed_time_us"], .5)


if __name__ == "__main__":
    unittest.main()
