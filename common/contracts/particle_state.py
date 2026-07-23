"""Validate canonical particle-event tables independently of solver and device."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C as E_CHARGE_C,
    kinetic_energy_ev,
)

PARTICLE_STATE_COLUMNS = [
    "particle_id", "event", "status", "terminal_reason", "time_us", "elapsed_time_us",
    "rf_phase_rad", "axial_z_mm", "transverse_x_mm", "transverse_y_mm",
    "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV",
    "radial_position_mm", "divergence_angle_deg", "max_rod_radius_mm",
]
ENUMS = {
    "event": ["source", "rod_exit", "handoff", "terminal"],
    "status": ["alive", "transmitted", "lost", "timeout"],
    "terminal_reason": [
        "none", "acceptance_detector", "acceptance_radius", "electrode", "radial_escape", "backward_escape",
        "timeout", "solver_stop", "unknown",
    ],
}
def _close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: actual={actual:.15g} expected={expected:.15g}")


def ion11_sources(path: Path, axial_offset_mm: float = 0.0) -> dict[int, dict[str, float]]:
    """Convert an ION11 table into expected canonical source states."""
    result: dict[int, dict[str, float]] = {}
    rows = csv.reader(path.read_text(encoding="utf-8-sig").splitlines())
    for particle_id, row in enumerate(rows, start=1):
        if len(row) != 11:
            raise ValueError(f"row {particle_id} has {len(row)} columns, expected 11")
        birth_time_us, mass_amu, _, axial_mm, transverse_1_mm, transverse_2_mm, azimuth_deg, elevation_deg, energy_ev, _, _ = map(float, row)
        if mass_amu <= 0 or energy_ev < 0:
            raise ValueError(f"row {particle_id} has invalid mass or kinetic energy")
        speed_m_s = math.sqrt(2 * energy_ev * E_CHARGE_C / (mass_amu * AMU_KG))
        azimuth_rad = math.radians(azimuth_deg)
        elevation_rad = math.radians(elevation_deg)
        velocity_simion = (
            speed_m_s * math.cos(elevation_rad) * math.cos(azimuth_rad),
            speed_m_s * math.cos(elevation_rad) * math.sin(azimuth_rad),
            speed_m_s * math.sin(elevation_rad),
        )
        result[particle_id] = {
            "time_us": birth_time_us,
            "elapsed_time_us": 0.0,
            "axial_z_mm": axial_mm + axial_offset_mm,
            "transverse_x_mm": transverse_2_mm,
            "transverse_y_mm": -transverse_1_mm,
            "velocity_axial_m_s": velocity_simion[0],
            "velocity_x_m_s": -velocity_simion[1],
            "velocity_y_m_s": -velocity_simion[2],
            "kinetic_energy_eV": energy_ev,
        }
    return result


def canonical_sources(path: Path, mass_amu: float | None = None) -> dict[int, dict[str, float]]:
    """Read canonical source rows, requiring mass in the table or explicit argument."""
    result: dict[int, dict[str, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            particle_id = int(row["particle_id"])
            if particle_id in result:
                raise ValueError(f"duplicate canonical particle_id: {particle_id}")
            row_mass = row.get("mass_amu")
            if row_mass in (None, "") and mass_amu is None:
                raise ValueError("canonical particle source requires a mass_amu column or --mass-amu")
            particle_mass_amu = float(row_mass) if row_mass not in (None, "") else float(mass_amu)
            if particle_mass_amu <= 0:
                raise ValueError(f"particle {particle_id} has non-positive mass_amu")
            velocity_x_m_s = float(row["vx_m_s"])
            velocity_y_m_s = float(row["vy_m_s"])
            velocity_z_m_s = float(row["vz_m_s"])
            energy_ev = kinetic_energy_ev(
                particle_mass_amu,
                velocity_x_m_s,
                velocity_y_m_s,
                velocity_z_m_s,
            )
            result[particle_id] = {
                "time_us": float(row["birth_time_s"]) * 1e6,
                "elapsed_time_us": 0.0,
                "axial_z_mm": float(row["z_mm"]),
                "transverse_x_mm": float(row["x_mm"]),
                "transverse_y_mm": float(row["y_mm"]),
                "velocity_axial_m_s": velocity_z_m_s,
                "velocity_x_m_s": velocity_x_m_s,
                "velocity_y_m_s": velocity_y_m_s,
                "kinetic_energy_eV": energy_ev,
            }
    return result


def validate_particle_state(
    state_path: Path,
    sources: dict[int, dict[str, float]],
    frequency_hz: float,
    phase_rad: float,
    rod_exit_mm: float | None = None,
    handoff_mm: float | None = None,
    columns: list[str] | None = None,
    enums: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Validate schema, source identity, RF phase, event identity, and interface planes."""
    columns = columns or PARTICLE_STATE_COLUMNS
    enums = enums or ENUMS
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise AssertionError(f"particle-state columns differ: {reader.fieldnames}")
        rows = list(reader)

    by_id: dict[int, dict[str, dict[str, str]]] = {}
    counts = {event: 0 for event in enums["event"]}
    for row in rows:
        particle_id = int(row["particle_id"])
        event = row["event"]
        if (event not in enums["event"] or row["status"] not in enums["status"]
                or row["terminal_reason"] not in enums["terminal_reason"]):
            raise AssertionError(f"invalid event/status/reason for particle {particle_id}")
        if event in by_id.setdefault(particle_id, {}):
            raise AssertionError(f"duplicate event {event} for particle {particle_id}")
        by_id[particle_id][event] = row
        counts[event] += 1
        if not all(math.isfinite(float(row[name])) for name in columns[4:]):
            raise AssertionError(f"non-finite state value for particle {particle_id} event {event}")
        if not 0 <= float(row["rf_phase_rad"]) < 2 * math.pi + 1e-12:
            raise AssertionError("RF phase outside [0, 2pi)")
        if float(row["kinetic_energy_eV"]) < 0 or float(row["radial_position_mm"]) < 0:
            raise AssertionError("negative energy or radius")

    if sorted(by_id) != sorted(sources):
        raise AssertionError("particle IDs do not match the input table")
    for particle_id, expected in sources.items():
        events = by_id[particle_id]
        if "source" not in events or "terminal" not in events:
            raise AssertionError(f"particle {particle_id} lacks source or terminal event")
        source = events["source"]
        for name, value in expected.items():
            tolerance = 1e-6 if name.startswith("velocity_") else 1e-9
            _close(float(source[name]), value, tolerance, f"particle {particle_id} source {name}")
        expected_phase = (2 * math.pi * frequency_hz * float(source["time_us"]) * 1e-6 + phase_rad) % (2 * math.pi)
        _close(float(source["rf_phase_rad"]), expected_phase, 1e-9, f"particle {particle_id} source RF phase")
        if rod_exit_mm is not None and "rod_exit" in events:
            _close(float(events["rod_exit"]["axial_z_mm"]), rod_exit_mm, 1e-9, "rod-exit plane")
        if handoff_mm is not None and "handoff" in events:
            _close(float(events["handoff"]["axial_z_mm"]), handoff_mm, 1e-9, "handoff plane")
    return {
        "status": "PASS",
        "particles": len(sources),
        "rows": len(rows),
        "event_counts": counts,
        "source_identity": "PASS",
        "plane_identity": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--source-format", choices=("ion11", "canonical"), required=True)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--axial-offset-mm", type=float, default=0.0)
    parser.add_argument("--mass-amu", type=float)
    parser.add_argument("--frequency-hz", type=float, required=True)
    parser.add_argument("--phase-rad", type=float, default=0.0)
    parser.add_argument("--rod-exit-mm", type=float)
    parser.add_argument("--handoff-mm", type=float)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    columns = None
    enums = None
    rod_exit_mm = args.rod_exit_mm
    handoff_mm = args.handoff_mm
    if args.contract:
        contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
        columns = contract["particle_state_columns"]
        enums = contract["enums"]
        rod_exit_mm = float(contract["planes"]["rod_exit"]["z_mm"])
        handoff_mm = float(contract["planes"]["handoff"]["z_mm"])
    sources = (
        ion11_sources(args.particles, args.axial_offset_mm)
        if args.source_format == "ion11"
        else canonical_sources(args.particles, args.mass_amu)
    )
    report = validate_particle_state(
        args.state, sources, args.frequency_hz, args.phase_rad,
        rod_exit_mm, handoff_mm, columns, enums,
    )
    report["solver"] = args.solver
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
