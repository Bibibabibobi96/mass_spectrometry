from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import materialize, materialize_pre_pulse_restart


REPO = Path(__file__).resolve().parents[3]


class SingleFlightSourceTests(unittest.TestCase):
    def test_real_n1000_continuous_source_separates_solver_and_absolute_birth(self) -> None:
        source = REPO / "common/multipole/sources/rf_oatof_short_focus_ideal_linear_z_vz_entry_n1000.csv"
        connection = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260813_170000__sim__simion__rf-oatof-single-flight-gap0__n1000/inputs/resolved_connection.json"
        if not source.is_file() or not connection.is_file():
            self.skipTest("N=1000 continuous source fixture is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            ion = Path(directory) / "source.ion"
            global_state = Path(directory) / "global.csv"
            completed = subprocess.run([
                sys.executable, "-m",
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source",
                "--source", str(source), "--connection", str(connection),
                "--ion", str(ion), "--global-state", str(global_state),
                "--source-release-mode", "continuous_frontend",
            ], cwd=REPO, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            ion_rows = ion.read_text(encoding="utf-8").splitlines()
            with global_state.open(encoding="utf-8", newline="") as handle:
                global_rows = list(csv.DictReader(handle))
        self.assertEqual(len(ion_rows), 1000)
        self.assertTrue(all(row.split(",", 1)[0] == "0" for row in ion_rows))
        self.assertEqual(len(global_rows), 1000)
        self.assertGreater(float(global_rows[0]["instrument_time_us"]), 41.0)
        self.assertLess(float(global_rows[0]["instrument_time_us"]), 41.1)

    def test_rejects_removed_legacy_clock_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            completed = subprocess.run([
                sys.executable, "-m",
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source",
                "--source", str(target / "source.csv"),
                "--connection", str(target / "connection.json"),
                "--ion", str(target / "source.ion"),
                "--global-state", str(target / "global.csv"),
                "--clock-basis", "legacy_relative_time",
            ], cwd=REPO, text=True, capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("unrecognized arguments", completed.stderr)

    def test_attribution_prepulse_state_is_read_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.csv"
            source.write_text(
                "simulation_particle_id,source_particle_id,arm_id,instrument_time_us,mass_amu,charge_state,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,kinetic_energy_eV\n"
                "1,7,ideal,45.5585544411,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            ion, rows = materialize_pre_pulse_restart(source, 45.5585544411)
        self.assertEqual(len(ion), 1)
        self.assertEqual(rows[0]["particle_id"], "1")
        self.assertEqual(list(rows[0]), ["particle_id", "instrument_time_us", "mass_amu", "charge_state", "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV"])
        self.assertEqual(ion[0][0], "0")
        self.assertEqual(rows[0]["instrument_time_us"], "45.5585544411")

    def test_real_n835_attribution_source_writes_both_outputs(self) -> None:
        source = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260812_210000__sim__simion__rf-oatof-terminal-analytic-ideal-boundary-step__n1000__r01/inputs/counterfactual_arms/current_layout_ideal_1mm_linear_z_vz__source_state.csv"
        if not source.is_file():
            self.skipTest("historical N=835 attribution source is unavailable")
        connection = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/connection_profiles.json"
        with tempfile.TemporaryDirectory() as directory:
            ion = Path(directory) / "source.ion"
            global_state = Path(directory) / "global.csv"
            completed = subprocess.run([sys.executable, "-m", "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source", "--source", str(source), "--connection", str(connection), "--ion", str(ion), "--global-state", str(global_state), "--source-release-mode", "pre_pulse_restart", "--pulse-time-us", "45.5585544411"], cwd=REPO, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(len(ion.read_text(encoding="utf-8").splitlines()), 835)
            self.assertTrue(all(
                line.split(",", 1)[0] == "0"
                for line in ion.read_text(encoding="utf-8").splitlines()
            ))
            with global_state.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                output_rows = list(reader)
            self.assertEqual(reader.fieldnames, ["particle_id", "instrument_time_us", "mass_amu", "charge_state", "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV"])
            self.assertEqual(len(output_rows), 835)
            self.assertEqual((output_rows[0]["particle_id"], output_rows[-1]["particle_id"]), ("1", "835"))
            self.assertTrue(all(row["instrument_time_us"] == "45.5585544411" for row in output_rows))

    def test_maps_all_n1000_particles_without_handoff_filtering(self) -> None:
        run = (
            REPO.parent
            / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
        )
        if not run.is_dir():
            self.skipTest("local N=1000 octupole source artifact is unavailable")
        connection = json.loads(
            (
                REPO.parent
                / "artifacts/projects/rf_octupole_ion_optics/runs"
                / "20260804_125500__sim__simion__oct-aperture100x090-interface__n459"
                / "inputs/resolved_connection.json"
            ).read_text(encoding="utf-8-sig")
        )
        ion, states = materialize(run / "inputs/particle_source.csv", connection)
        self.assertEqual(len(ion), 1000)
        self.assertEqual(len(states), 1000)
        first = states[0]
        self.assertAlmostEqual(float(first["position_x_mm"]), -149.9)
        self.assertAlmostEqual(float(first["position_y_mm"]), -0.08166000357342909)
        self.assertAlmostEqual(float(first["position_z_mm"]), -18.32170905524317)
        self.assertAlmostEqual(float(first["velocity_x_m_s"]), 1959.568200662977)
        self.assertAlmostEqual(float(first["velocity_y_m_s"]), -105.35913222607861)
        self.assertAlmostEqual(float(first["velocity_z_m_s"]), -91.67991313892833)
        self.assertEqual(len(ion[0]), 11)

    def test_rejects_noncontiguous_particle_ids(self) -> None:
        connection = {
            "spatial_registration": {
                "rotation_upstream_to_downstream": [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "translation_mm": [0.0, 0.0, 0.0],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(["particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state"])
                writer.writerow([2, 0, 0, 0, 0, 0, 0, 1, 100, 1])
            with self.assertRaisesRegex(ValueError, "contiguous"):
                materialize(path, connection)


if __name__ == "__main__":
    unittest.main()
