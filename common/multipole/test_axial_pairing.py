from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from common.multipole.axial_pairing import audit_pair, resolve_pair


HEADER = [
    "particle_id",
    "event",
    "status",
    "terminal_reason",
    "time_us",
    "elapsed_time_us",
    "rf_phase_rad",
    "axial_z_mm",
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_axial_m_s",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "kinetic_energy_eV",
    "radial_position_mm",
    "divergence_angle_deg",
    "max_rod_radius_mm",
]


def pairing_contract() -> dict:
    return {
        "schema_version": 1,
        "role": "multipole_axial_field_paired_diagnostic",
        "pair_id": "explicit_axial_n100.v1",
        "project_id": "rf_quadrupole_collision_cooling",
        "axial_contract_file": "axial.json",
        "source": {
            "operating_point": "official_100amu_2eV",
            "particle_count": 2,
            "mean_kinetic_energy_bounds_eV": [1.8, 2.2],
        },
        "arms": [
            {
                "arm_id": "axial_field_on",
                "case_id": "axial_acceleration_rf_on",
                "axial_scale": 1,
                "rf_scale": 1,
            },
            {
                "arm_id": "axial_field_off",
                "case_id": "zero_axial_drop_rf_on",
                "axial_scale": 0,
                "rf_scale": 1,
            },
        ],
        "invariants": ["particle_source", "geometry", "rf", "solver"],
        "independent_5ev_source_allowed": False,
        "excluded_legacy_run_ids": ["legacy-r05"],
        "claim_limit": "paired source preparation only",
    }


def interface_contract() -> dict:
    return {
        "planes": {
            "handoff": {"z_mm": 90.2},
            "acceptance_detector": {"z_mm": 95.2},
        }
    }


def resolved_geometry() -> dict:
    return {"derived_geometry_mm": {"exit_plate_z_max": 90.2, "detector_z": 95.2}}


def write_state(path: Path, source_velocity: float = 1.0) -> None:
    rows = []
    for particle_id in (1, 2):
        source = {
            name: "0"
            for name in HEADER
        }
        source.update(
            particle_id=str(particle_id),
            event="source",
            status="alive",
            terminal_reason="none",
            velocity_axial_m_s=str(source_velocity),
            kinetic_energy_eV="2",
        )
        handoff = dict(source)
        handoff.update(
            event="handoff",
            status="transmitted",
            time_us="1",
            elapsed_time_us="1",
            axial_z_mm="90.2",
        )
        rows.extend((source, handoff))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class AxialPairingTest(unittest.TestCase):
    def test_resolve_and_audit_strict_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("same mother sample\n", encoding="utf-8")
            resolved = resolve_pair(
                pairing_contract(),
                interface_contract(),
                resolved_geometry(),
                selected_axial_contract_name="axial.json",
                source_path=source,
                source_count=2,
                source_mean_energy_ev=2.0,
                project_id="rf_quadrupole_collision_cooling",
            )
            field_on = root / "on.csv"
            field_off = root / "off.csv"
            write_state(field_on)
            write_state(field_off)
            result = audit_pair(resolved, field_on, field_off)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["particle_ids_identical"])
        self.assertEqual(result["arms"]["axial_field_on"]["handoff_particles"], 2)

    def test_rejects_independent_five_ev_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text("5 eV source\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "5 eV"):
                resolve_pair(
                    pairing_contract(),
                    interface_contract(),
                    resolved_geometry(),
                    selected_axial_contract_name="axial.json",
                    source_path=source,
                    source_count=2,
                    source_mean_energy_ev=5.0,
                    project_id="rf_quadrupole_collision_cooling",
                )

    def test_rejects_detector_plane_as_handoff(self) -> None:
        invalid = resolved_geometry()
        invalid["derived_geometry_mm"]["exit_plate_z_max"] = 95.2
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text("source\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "handoff"):
                resolve_pair(
                    pairing_contract(),
                    interface_contract(),
                    invalid,
                    selected_axial_contract_name="axial.json",
                    source_path=source,
                    source_count=2,
                    source_mean_energy_ev=2.0,
                    project_id="rf_quadrupole_collision_cooling",
                )

    def test_rejects_source_state_drift_between_arms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("source\n", encoding="utf-8")
            resolved = resolve_pair(
                pairing_contract(),
                interface_contract(),
                resolved_geometry(),
                selected_axial_contract_name="axial.json",
                source_path=source,
                source_count=2,
                source_mean_energy_ev=2.0,
                project_id="rf_quadrupole_collision_cooling",
            )
            field_on = root / "on.csv"
            field_off = root / "off.csv"
            write_state(field_on)
            write_state(field_off, source_velocity=2.0)
            with self.assertRaisesRegex(ValueError, "source states"):
                audit_pair(resolved, field_on, field_off)

    def test_rejects_legacy_terminal_only_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("source\n", encoding="utf-8")
            resolved = resolve_pair(
                pairing_contract(),
                interface_contract(),
                resolved_geometry(),
                selected_axial_contract_name="axial.json",
                source_path=source,
                source_count=2,
                source_mean_energy_ev=2.0,
                project_id="rf_quadrupole_collision_cooling",
            )
            field_on = root / "on.csv"
            field_off = root / "off.csv"
            write_state(field_on)
            write_state(field_off)
            field_on.write_text(
                field_on.read_text(encoding="utf-8").replace(",handoff,", ",terminal,"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "one handoff"):
                audit_pair(resolved, field_on, field_off)


if __name__ == "__main__":
    unittest.main()
