"""RF event-table protocol, distinct from neutral transfer-state snapshots.

Preserves the deployed source/terminal, single-event, phase and plane checks.
Source formats are loaded only by CLI, never by a core column-order consumer.
"""
from __future__ import annotations
import csv
import math
from pathlib import Path
from typing import Any

from msplatform.contracts.particle_physics import kinetic_energy_ev

PARTICLE_STATE_COLUMNS = [
    "particle_id", "event", "status", "terminal_reason", "time_us", "elapsed_time_us",
    "rf_phase_rad", "axial_z_mm", "transverse_x_mm", "transverse_y_mm",
    "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV",
    "radial_position_mm", "divergence_angle_deg", "max_rod_radius_mm",
]

ENUMS = {
    "event": ["source", "rod_exit", "handoff", "terminal"],
    "status": ["alive", "transmitted", "lost", "timeout", "unknown"],
    "terminal_reason": [
        "none", "acceptance_surface", "acceptance_radius", "acceptance_aperture",
        "electrode", "radial_escape", "backward_escape",
        "timeout", "solver_stop", "unknown",
        "time_window_end", "ended_without_loss_evidence", "terminal_cause_unresolved",
    ],
}

def _close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: actual={actual:.15g} expected={expected:.15g}")

def validate_rf_event_table(
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

def read_canonical_rf_source_expectations(path: Path, mass_amu: float | None = None) -> dict[int, dict[str, float]]:
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
