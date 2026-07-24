from __future__ import annotations

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev
from projects.rf_quadrupole_collision_cooling.analysis import audit_s3_pulse_chain as module


class S3PulseChainAuditTests(unittest.TestCase):
    def test_matlab_local_exit_uses_exact_common_v1_columns(self) -> None:
        script = Path(__file__).parents[1] / "comsol" / "solve_s3_pulse_capture.m"
        text = script.read_text(encoding="utf-8")
        start = text.index("localExit=cell2table")
        end = text.index(");", start)
        names = re.findall(r"'([^']+)'", text[start:end])[1:]
        self.assertEqual(len(csv_columns()), 28)
        self.assertEqual(names, csv_columns())
        self.assertIn("exitRows = cell(height(ions), 28)", text)
        self.assertIn("ions.particle_id(index),canonicalParentIds(index)", text)
        self.assertIn("string(ions.species_id(index)),ions.particle_weight(index)", text)
        self.assertIn("canonicalParentIds(index)", text)
        self.assertIn("if ismissing(value) || isnan(value)", text)
        self.assertIn("value == fix(value)", text)

    def test_runner_validates_and_records_frozen_s3_particle_input(self) -> None:
        runner = Path(__file__).parents[1] / "comsol" / "run_s3_pulse_capture.ps1"
        text = runner.read_text(encoding="utf-8")
        validation = text.index("-m common.contracts.component_particle_state")
        comsol = text.index("common\\comsol\\run_comsol_r2025b.ps1")
        self.assertLess(validation, comsol)
        self.assertIn("canonical_rf_exit_component_state_validation.json", text)
        self.assertIn("particle_state_validation = $particleValidation", text)
        self.assertIn("particle_validation_sha256", text)

    def test_parent_nan_boundary_and_real_parent_are_explicit(self) -> None:
        velocity = 1000.0
        row = {
            "particle_id": 2, "parent_particle_id": "", "generation": 0,
            "species_id": "ion_100amu_q1", "particle_weight": 1,
            "source_component_id": "s2", "target_component_id": "s3",
            "state_event": "component_handoff", "frame_id": "oatof_global",
            "clock_epoch_id": "epoch", "instrument_time_us": 12,
            "lineage_age_us": 6, "particle_age_us": 6,
            "last_component_elapsed_time_us": 2,
            "lineage_birth_time_us": 6, "particle_birth_time_us": 6,
            "mass_to_charge_Th": 100, "mass_amu": 100, "charge_state": 1,
            "position_x_mm": 0, "position_y_mm": 0, "position_z_mm": 0,
            "velocity_x_m_s": velocity, "velocity_y_m_s": 0, "velocity_z_m_s": 0,
            "kinetic_energy_eV": kinetic_energy_ev(100, velocity, 0, 0),
            "phase_reference_id": "rf_drive.v1", "phase_rad": 0,
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.csv"

            def write(parent: object, generation: int) -> None:
                candidate = {**row, "parent_particle_id": parent, "generation": generation}
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=csv_columns())
                    writer.writeheader()
                    writer.writerow(candidate)

            write("", 0)
            self.assertEqual(validate_component_particle_state_csv(path)["status"], "PASS")
            write(7, 1)
            self.assertEqual(validate_component_particle_state_csv(path)["status"], "PASS")
            write("NaN", 0)
            with self.assertRaisesRegex(ValueError, "parent_particle_id"):
                validate_component_particle_state_csv(path)
            write("", 0)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["species_id"] = ""
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=csv_columns())
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "species_id"):
                validate_component_particle_state_csv(path)

    def test_minimal_chain_preserves_clock_and_exit_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            velocity = 1000.0
            energy = kinetic_energy_ev(100, velocity, 0, 0)
            source = pd.DataFrame([{
                "particle_id": 1, "parent_particle_id": None, "generation": 0,
                "species_id": "ion_100amu_q1", "particle_weight": 1.0,
                "source_component_id": "s2", "target_component_id": "s3",
                "state_event": "component_handoff", "frame_id": "oatof_global",
                "clock_epoch_id": "epoch", "instrument_time_us": 10.0,
                "lineage_age_us": 4.0, "particle_age_us": 4.0,
                "last_component_elapsed_time_us": 0.0,
                "lineage_birth_time_us": 6.0, "particle_birth_time_us": 6.0,
                "mass_to_charge_Th": 100.0, "mass_amu": 100.0,
                "charge_state": 1, "position_x_mm": 0.0, "position_y_mm": 0.0,
                "position_z_mm": 0.0, "velocity_x_m_s": velocity,
                "velocity_y_m_s": 0.0, "velocity_z_m_s": 0.0,
                "kinetic_energy_eV": energy,
                "phase_reference_id": "rf_drive.v1", "phase_rad": 0.0,
            }], columns=csv_columns())
            terminal = pd.DataFrame([{
                "particle_id": 1, "event": "local_accelerator_exit", "frame_id": "oatof_global",
                "clock_epoch_id": "epoch", "instrument_time_us": 12.0, "lineage_age_us": 6.0,
                "particle_age_us": 6.0, "last_component_elapsed_time_us": 2.0,
                "mass_amu": 100.0, "charge_state": 1, "vx_m_s": velocity,
                "vy_m_s": 0.0, "vz_m_s": 0.0, "kinetic_energy_eV": energy,
                "first_forward_oatof_entry": True,
            }])
            capture = pd.DataFrame([{
                "particle_id": 1, "frame_id": "oatof_global",
                "clock_epoch_id": "epoch", "instrument_time_us": 11.0,
                "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
                "vx_m_s": velocity, "vy_m_s": 0.0, "vz_m_s": 0.0,
                "inside_oatof_ideal_reference_volume": True, "active_at_pulse": True,
            }])
            local_exit = pd.DataFrame([{
                "particle_id": 1, "parent_particle_id": None, "generation": 0,
                "species_id": "ion_100amu_q1", "particle_weight": 1.0,
                "source_component_id": "s3", "target_component_id": "oatof",
                "state_event": "local_accelerator_exit",
                "frame_id": "oatof_global", "clock_epoch_id": "epoch",
                "instrument_time_us": 12.0, "lineage_age_us": 6.0, "particle_age_us": 6.0,
                "last_component_elapsed_time_us": 2.0,
                "lineage_birth_time_us": 6.0, "particle_birth_time_us": 6.0,
                "mass_to_charge_Th": 100.0,
                "mass_amu": 100.0, "charge_state": 1, "position_x_mm": 0.0,
                "position_y_mm": 0.0, "position_z_mm": 0.0, "velocity_x_m_s": velocity,
                "velocity_y_m_s": 0.0, "velocity_z_m_s": 0.0,
                "kinetic_energy_eV": energy,
                "phase_reference_id": "rf_drive.v1", "phase_rad": 0.0,
            }], columns=csv_columns())
            for name, frame in (("source", source), ("terminal", terminal),
                                ("capture", capture), ("exit", local_exit)):
                frame.to_csv(root/f"{name}.csv", index=False)
            (root/"schedule.json").write_text(json.dumps({
                "stage": "S3", "derived_pulse_time_us": 11.0,
                "pulse_width_us": 1.0,
                "target_species": {"mass_amu": 100.0, "charge_state": 1},
            }), encoding="utf-8")
            (root/"contract.json").write_text(json.dumps({
                "source": {"source_particles": 1, "clock_epoch_id": "epoch",
                           "target_mass_amu": 100.0, "target_charge_state": 1},
                "runtime": {"minimum_active_at_pulse": 1, "minimum_local_accelerator_exit": 1},
            }), encoding="utf-8")
            result = module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                                  root/"exit.csv", root/"schedule.json", root/"contract.json")
            self.assertEqual(result["local_accelerator_exit"], 1)
            self.assertEqual(result["maximum_clock_residual_us"], 0.0)

            changed_capture = capture.copy()
            changed_capture.loc[0, "particle_id"] = 2
            changed_capture.to_csv(root/"capture.csv", index=False)
            with self.assertRaisesRegex(ValueError, "unknown particle ID"):
                module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                             root/"exit.csv", root/"schedule.json", root/"contract.json")

            changed_capture = capture.copy()
            changed_capture.loc[0, "instrument_time_us"] = 11.001
            changed_capture.to_csv(root/"capture.csv", index=False)
            with self.assertRaisesRegex(ValueError, "scheduled pulse time"):
                module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                             root/"exit.csv", root/"schedule.json", root/"contract.json")


if __name__ == "__main__":
    unittest.main()
