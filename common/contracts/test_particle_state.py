import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.analysis.rf_event_table_validation import (
    PARTICLE_STATE_COLUMNS, validate_rf_event_table as validate_particle_state,
)
from projects.rf_multipole_ion_optics.simion.ion11_source_adapter import (
    AMU_KG, E_CHARGE_C, read_canonical_rf_source_expectations as canonical_sources,
    read_ion11_source_states as ion11_sources,
)


class CanonicalSourceTests(unittest.TestCase):
    def test_native_workbench_decode_and_same_rigid_rotation_have_independent_6d_oracle(self):
        from projects.rf_multipole_ion_optics.simion.ion11_source_adapter import (
            _decode_ion11_workbench_row, _transform_workbench_to_rf_source,
        )
        energy = .5 * AMU_KG * 100.**2 / E_CHARGE_C
        native = _decode_ion11_workbench_row([str(x) for x in (12.5, 1, 1, 4, 5, 6, 30, 30, energy, 1, 1)], 1)
        self.assertEqual(native["position_mm"], (4., 5., 6.))
        for actual, expected in zip(native["velocity_m_s"], (75., 50., -25.*math.sqrt(3.)), strict=True):
            self.assertAlmostEqual(actual, expected, places=12)
        rf = _transform_workbench_to_rf_source(native, 7.)
        self.assertEqual([rf[k] for k in ("transverse_x_mm", "transverse_y_mm", "axial_z_mm")], [6., -5., 11.])
        for key, expected in zip(("velocity_x_m_s", "velocity_y_m_s", "velocity_axial_m_s"),
                                 (-25.*math.sqrt(3.), -50., 75.), strict=True):
            self.assertAlmostEqual(rf[key], expected, places=12)
        # R is symmetric, so R^T reverses it; translation applies only to position.
        self.assertEqual((rf["axial_z_mm"]-7., -rf["transverse_y_mm"], rf["transverse_x_mm"]), native["position_mm"])
        self.assertEqual((rf["velocity_axial_m_s"], -rf["velocity_y_m_s"], rf["velocity_x_m_s"]), native["velocity_m_s"])
        self.assertEqual(rf["time_us"], 12.5)
        self.assertEqual(rf["kinetic_energy_eV"], energy)

    def test_projection_origin_nonzero_angles_offset_and_row_identity(self):
        from common.contracts import particle_state as bridge
        self.assertIs(bridge.ion11_sources, ion11_sources)
        self.assertIs(bridge.validate_particle_state, validate_particle_state)
        self.assertEqual(ion11_sources.__module__, "projects.rf_multipole_ion_optics.simion.ion11_source_adapter")
        self.assertEqual(validate_particle_state.__module__, "projects.rf_multipole_ion_optics.analysis.rf_event_table_validation")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.ion"
            energy = .5 * AMU_KG * 100.**2 / E_CHARGE_C
            path.write_text(f"12.5,1,1,4,5,6,90,30,{energy},1,1\n19,1,1,8,9,10,0,0,0,1,1\n", encoding="utf-8")
            sources = ion11_sources(path, axial_offset_mm=7.)
        self.assertEqual(list(sources), [1, 2])
        self.assertEqual({k: sources[1][k] for k in ("time_us", "elapsed_time_us", "axial_z_mm", "transverse_x_mm", "transverse_y_mm")},
                         dict(time_us=12.5, elapsed_time_us=0., axial_z_mm=11., transverse_x_mm=6., transverse_y_mm=-5.))
        self.assertAlmostEqual(sources[1]["velocity_axial_m_s"], 0., places=12)
        self.assertAlmostEqual(sources[1]["velocity_x_m_s"], -50. * math.sqrt(3.), places=12)
        self.assertAlmostEqual(sources[1]["velocity_y_m_s"], -50., places=12)
        self.assertEqual(sources[2]["axial_z_mm"], 15.)

    def test_canonical_sparse_ids_birth_clock_and_axis_values_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            path.write_text("particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu\n"
                            "91,0.0000795,1,-2,3,4,-5,6,40\n7,0.00008,2,3,4,5,6,7,40\n", encoding="utf-8")
            source = canonical_sources(path)
        self.assertEqual(list(source), [91, 7])
        self.assertEqual(source[91]["time_us"], 79.5)
        self.assertEqual(source[91]["elapsed_time_us"], 0.)
        self.assertEqual([source[91][k] for k in ("axial_z_mm", "transverse_x_mm", "transverse_y_mm",
                         "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s")], [3., 1., -2., 6., 4., -5.])

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
            outputs = []
            for module in ("common.contracts.particle_state",
                           "projects.rf_multipole_ion_optics.analysis.rf_event_table_validation"):
                result = subprocess.run([sys.executable, "-m", module, "--state", str(state),
                                         "--particles", str(source_path), "--source-format", "canonical",
                                         "--frequency-hz", "1100000", "--phase-rad", "0", "--solver", "fixture"],
                                        cwd=Path(__file__).resolve().parents[2], capture_output=True,
                                        text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(json.loads(result.stdout))
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
