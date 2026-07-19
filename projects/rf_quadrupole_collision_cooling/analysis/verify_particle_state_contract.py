"""Validate solver particle-state CSV against the shared interface contract."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: actual={actual:.15g} expected={expected:.15g}")


def expected_source(row: list[float], axial_offset_mm: float) -> dict[str, float]:
    tob, mass, _, axial, transverse_1, transverse_2, azimuth, elevation, energy, _, _ = row
    speed = math.sqrt(2 * energy * 1.602176634e-19 / (mass * 1.66053906660e-27))
    az, el = math.radians(azimuth), math.radians(elevation)
    v_sim = (
        speed * math.cos(el) * math.cos(az),
        speed * math.cos(el) * math.sin(az),
        speed * math.sin(el),
    )
    return {
        "time_us": tob,
        "elapsed_time_us": 0.0,
        "axial_z_mm": axial + axial_offset_mm,
        "transverse_x_mm": transverse_2,
        "transverse_y_mm": -transverse_1,
        "velocity_axial_m_s": v_sim[0],
        "velocity_x_m_s": -v_sim[1],
        "velocity_y_m_s": -v_sim[2],
        "kinetic_energy_eV": energy,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--interface", required=True, type=Path)
    parser.add_argument("--axial-offset-mm", type=float, default=0.0)
    parser.add_argument("--frequency-hz", type=float, required=True)
    parser.add_argument("--phase-rad", type=float, default=0.0)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    interface = json.loads(args.interface.read_text(encoding="utf-8"))
    columns = interface["particle_state_columns"]
    enums = interface["enums"]
    event_values = enums["event"]
    events = set(event_values)
    statuses = set(enums["status"])
    reasons = set(enums["terminal_reason"])

    with args.state.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise AssertionError(f"particle-state columns differ: {reader.fieldnames}")
        rows = list(reader)
    particles = [list(map(float, row)) for row in csv.reader(args.particles.read_text(encoding="utf-8").splitlines())]
    planes = interface["planes"]
    by_id: dict[int, dict[str, dict[str, str]]] = {}
    for row in rows:
        particle_id = int(row["particle_id"])
        event = row["event"]
        if event not in events or row["status"] not in statuses or row["terminal_reason"] not in reasons:
            raise AssertionError(f"invalid event/status/reason for particle {particle_id}")
        if event in by_id.setdefault(particle_id, {}):
            raise AssertionError(f"duplicate event {event} for particle {particle_id}")
        by_id[particle_id][event] = row
        numeric = [float(row[name]) for name in columns[4:]]
        if not all(math.isfinite(value) for value in numeric):
            raise AssertionError(f"non-finite state value for particle {particle_id} event {event}")
        if not 0 <= float(row["rf_phase_rad"]) < 2 * math.pi + 1e-12:
            raise AssertionError(f"RF phase outside [0, 2pi) for particle {particle_id}")
        if float(row["kinetic_energy_eV"]) < 0 or float(row["radial_position_mm"]) < 0:
            raise AssertionError(f"negative energy or radius for particle {particle_id}")

    expected_ids = list(range(1, len(particles) + 1))
    if sorted(by_id) != expected_ids:
        raise AssertionError("particle IDs do not match the input table")
    counts = {event: 0 for event in event_values}
    for particle_id, particle in zip(expected_ids, particles):
        events = by_id[particle_id]
        if "source" not in events or "terminal" not in events:
            raise AssertionError(f"particle {particle_id} lacks source or terminal event")
        for event in events:
            counts[event] += 1
        expected = expected_source(particle, args.axial_offset_mm)
        source = events["source"]
        for name, value in expected.items():
            tolerance = 1e-6 if name.startswith("velocity_") else 1e-9
            close(float(source[name]), value, tolerance, f"particle {particle_id} source {name}")
        expected_phase = (2 * math.pi * args.frequency_hz * float(source["time_us"]) * 1e-6 + args.phase_rad) % (2 * math.pi)
        close(float(source["rf_phase_rad"]), expected_phase, 1e-9, f"particle {particle_id} source RF phase")
        if "rod_exit" in events:
            close(float(events["rod_exit"]["axial_z_mm"]), planes["rod_exit"]["z_mm"], 1e-9, "rod-exit plane")
        if "handoff" in events:
            close(float(events["handoff"]["axial_z_mm"]), planes["handoff"]["z_mm"], 1e-9, "handoff plane")

    report = {
        "status": "PASS",
        "solver": args.solver,
        "particles": len(particles),
        "rows": len(rows),
        "event_counts": counts,
        "source_identity": "PASS",
        "plane_identity": "PASS",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
