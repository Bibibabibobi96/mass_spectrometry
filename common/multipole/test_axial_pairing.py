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


def interface_contract(
    handoff_z_mm: float = 90.2,
    detector_z_mm: float = 95.2,
) -> dict:
    return {
        "planes": {
            "handoff": {"z_mm": handoff_z_mm},
            "acceptance_detector": {"z_mm": detector_z_mm},
        }
    }


def resolved_geometry(
    handoff_z_mm: float = 90.2,
    detector_z_mm: float = 95.2,
) -> dict:
    return {
        "derived_geometry_mm": {
            "exit_plate_z_max": handoff_z_mm,
            "detector_z": detector_z_mm,
        }
    }


def write_state(
    path: Path,
    source_velocity: float = 1.0,
    *,
    handoff_divergence: tuple[float, float] = (2.0, 4.0),
    handoff_radius: tuple[float, float] = (0.3, 0.4),
    handoff_energy: tuple[float, float] = (5.0, 5.2),
    source_max_rod_radius: float = 0.2,
    handoff_z_mm: float = 90.2,
) -> None:
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
            max_rod_radius_mm=str(source_max_rod_radius),
        )
        handoff = dict(source)
        handoff.update(
            event="handoff",
            status="transmitted",
            time_us="1",
            elapsed_time_us="1",
            axial_z_mm=str(handoff_z_mm),
            divergence_angle_deg=str(handoff_divergence[particle_id - 1]),
            radial_position_mm=str(handoff_radius[particle_id - 1]),
            kinetic_energy_eV=str(handoff_energy[particle_id - 1]),
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
            write_state(
                field_off,
                handoff_divergence=(3.0, 5.0),
                handoff_radius=(0.5, 0.6),
                handoff_energy=(2.0, 2.2),
                source_max_rod_radius=0.4,
            )
            paired = root / "paired.csv"
            result = audit_pair(resolved, field_on, field_off, paired)
            with paired.open(encoding="utf-8", newline="") as stream:
                paired_rows = list(csv.DictReader(stream))
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["particle_ids_identical"])
        self.assertEqual(result["arms"]["axial_field_on"]["handoff_particles"], 2)
        self.assertAlmostEqual(
            result["arms"]["axial_field_on"]["rms_divergence_angle_deg"],
            (10.0) ** 0.5,
        )
        self.assertAlmostEqual(
            result["arms"]["axial_field_off"]["rms_radial_position_mm"],
            (0.61 / 2.0) ** 0.5,
        )
        self.assertAlmostEqual(
            result["paired_difference"][
                "field_on_minus_field_off_divergence_angle_deg"
            ]["mean"],
            -1.0,
        )
        self.assertEqual([int(row["particle_id"]) for row in paired_rows], [1, 2])
        self.assertEqual(
            [float(row["delta_kinetic_energy_eV"]) for row in paired_rows],
            [3.0, 3.0],
        )

    def test_resolved_nondefault_geometry_moves_both_arm_handoffs(self) -> None:
        handoff_z_mm = 123.456
        detector_z_mm = 130.25
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("parameterized mother sample\n", encoding="utf-8")
            resolved = resolve_pair(
                pairing_contract(),
                interface_contract(handoff_z_mm, detector_z_mm),
                resolved_geometry(handoff_z_mm, detector_z_mm),
                selected_axial_contract_name="axial.json",
                source_path=source,
                source_count=2,
                source_mean_energy_ev=2.0,
                project_id="rf_quadrupole_collision_cooling",
            )
            field_on = root / "on.csv"
            field_off = root / "off.csv"
            write_state(field_on, handoff_z_mm=handoff_z_mm)
            write_state(field_off, handoff_z_mm=handoff_z_mm)
            result = audit_pair(resolved, field_on, field_off)
        self.assertEqual(resolved["physical_handoff"]["z_mm"], handoff_z_mm)
        self.assertEqual(
            resolved["physical_handoff"]["standalone_detector_z_mm"],
            detector_z_mm,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            {
                arm["handoff_particles"]
                for arm in result["arms"].values()
            },
            {2},
        )

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

    def test_rejects_nonfinite_handoff_metric(self) -> None:
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
            write_state(field_on, handoff_divergence=(float("nan"), 4.0))
            write_state(field_off)
            with self.assertRaisesRegex(ValueError, "non-finite divergence"):
                audit_pair(resolved, field_on, field_off)


if __name__ == "__main__":
    unittest.main()
