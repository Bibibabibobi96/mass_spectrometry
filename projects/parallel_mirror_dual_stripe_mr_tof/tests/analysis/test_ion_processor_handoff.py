from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import ValidationError

from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff


class IonProcessorHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.receipt_path = self.root / "component_exit_receipt.json"
        self.trajectory = self.root / "trajectory.json"
        self.provider = self.root / "provider.json"
        self.request = self.root / "request.json"
        self.output = self.root / "prepared"
        project = Path(__file__).parents[2]
        self.request.write_bytes((project / "config/ion_processor_matching_request.json").read_bytes())
        self._write(self.trajectory, {
            "coordinate_system": {"frame_id": "mr_frame.v2"},
            "accelerator": {"focus_y_anchor": {"project_y_mm": -55}},
            "accelerator_energy_contract": {"net_gain_reference_center_per_charge_v": 4000},
        })
        self._write(self.provider, {"mrtof_projection": {"target_axial_energy_per_charge_v": 4372.010347796}})
        self.rows = [self._row(1), self._row(7)]
        self.source = self.root / "source.csv"
        write_component_particle_state_csv(self.source, self.rows)
        self.census = self.root / "census.csv"
        self.census.write_text("particle_id,transfer_status,terminal_reason,instrument_time_us,particle_birth_time_us,particle_age_us\n1,transferred,downstream_domain_exit,7500.6,0,7500.6\n7,transferred,downstream_domain_exit,7500.7,0,7500.7\n9,not_transferred,solver_stop,21,0,21\n", encoding="utf-8")
        self.receipt = {
            "schema_version": 1, "role": "ion_processor_component_exit_export", "status": "prepared",
            "frame_id": "ip_frame.v2", "clock_epoch_id": "ion_processor_epoch_zero_v1",
            "inputs": {},
            "counts": {"source": 3, "transferred": 2, "not_transferred": 1},
            "transferred_particle_ids": [1, 7], "lost_particle_ids": [9],
            "observation_surface": {"center_mm": [0, 170, 0], "normal": [0, 0, -1]},
            "outputs": {"component_states": self._identity(self.source), "mother_census": self._identity(self.census)},
        }
        self._write(self.receipt_path, self.receipt)

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    @staticmethod
    def _identity(path: Path) -> dict:
        return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}

    @staticmethod
    def _row(particle_id: int) -> dict:
        velocity = [50.0, 100.0, -37800.0]
        time = 7500.5 + particle_id / 100
        return {
            "particle_id": particle_id, "parent_particle_id": "", "generation": 0,
            "species_id": "ion_524_q1", "particle_weight": 1,
            "source_component_id": "dual_pressure_rectilinear_ion_processor",
            "target_component_id": "parallel_mirror_dual_stripe_mr_tof", "state_event": "extraction_exit",
            "frame_id": "ip_frame.v2", "clock_epoch_id": "ion_processor_epoch_zero_v1",
            "instrument_time_us": time, "lineage_age_us": time, "particle_age_us": time,
            "last_component_elapsed_time_us": time, "lineage_birth_time_us": 0,
            "particle_birth_time_us": 0, "mass_to_charge_Th": 524, "mass_amu": 524, "charge_state": 1,
            "position_x_mm": 0.02, "position_y_mm": 170.1, "position_z_mm": -0.01,
            "velocity_x_m_s": velocity[0], "velocity_y_m_s": velocity[1], "velocity_z_m_s": velocity[2],
            "kinetic_energy_eV": kinetic_energy_ev(524, *velocity),
            "phase_reference_id": "source_rf.v1", "phase_rad": 1.25,
        }

    def _prepare(self) -> dict:
        return prepare_handoff(self.receipt_path, self.trajectory, self.provider, self.request, self.output)

    def test_preserves_full_state_clock_identity_and_complete_census(self) -> None:
        report = self._prepare()
        self.assertFalse(report["solver_execution"])
        self.assertEqual(report["counts"]["source"], 3)
        self.assertEqual((self.output / "source_census.csv").read_bytes(), self.census.read_bytes())
        with (self.output / "component_particle_state.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([int(row["particle_id"]) for row in rows], [1, 7])
        self.assertAlmostEqual(float(rows[0]["position_y_mm"]), -54.9)
        for original, row in zip(self.rows, rows):
            for field in ("instrument_time_us", "kinetic_energy_eV", "phase_rad", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"):
                self.assertEqual(float(row[field]), original[field])
            self.assertEqual(row["clock_epoch_id"], original["clock_epoch_id"])
            self.assertEqual(row["frame_id"], "mr_frame.v2")
        resolved = json.loads((self.output / "matching_request_resolved.json").read_text())
        self.assertEqual(resolved["target"]["axial_energy_per_charge_v"], 4372.010347796)
        self.assertEqual(resolved["target"]["anchor_y_mm"], -55)
        self.assertEqual(resolved["mirror_nominal_energy_reference"]["net_gain_reference_center_per_charge_v"], 4000)
        self.assertFalse(resolved["old_oa_field_valid_for_replacement"])

    def test_rejects_source_tampering_before_output_creation(self) -> None:
        self.source.write_text(self.source.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_opposite_direction(self) -> None:
        self.rows[0]["velocity_z_m_s"] *= -1
        write_component_particle_state_csv(self.source, self.rows)
        self.receipt["outputs"]["component_states"] = self._identity(self.source)
        self._write(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "negative z"):
            self._prepare()

    def test_rejects_incomplete_mother_identity(self) -> None:
        self.receipt["lost_particle_ids"] = [8]
        self._write(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "do not close"):
            self._prepare()

    def test_refuses_overwrite(self) -> None:
        self._prepare()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self._prepare()

    def test_request_cannot_authorize_execution(self) -> None:
        request = json.loads(self.request.read_text())
        request["policies"]["execution"] = "run"
        self._write(self.request, request)
        with self.assertRaises(ValidationError):
            self._prepare()
