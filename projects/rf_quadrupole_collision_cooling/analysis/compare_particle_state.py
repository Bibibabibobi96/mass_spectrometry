"""Compare independently solved COMSOL and SIMION particle-state events."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def load(path: Path) -> dict[tuple[int, str], dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {(int(row["particle_id"]), row["event"]): row for row in rows}
    if len(result) != len(rows):
        raise AssertionError(f"duplicate particle event in {path}")
    return result


def values(rows: dict[tuple[int, str], dict[str, str]], event: str, name: str) -> list[float]:
    return [float(row[name]) for (particle_id, row_event), row in sorted(rows.items()) if row_event == event]


def mean(data: list[float]) -> float:
    return sum(data) / len(data)


def rms(data: list[float]) -> float:
    return math.sqrt(mean([value * value for value in data]))


def percentile(data: list[float], probability: float) -> float:
    ordered = sorted(data)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def relative_difference(left: float, right: float) -> float:
    scale = (abs(left) + abs(right)) / 2
    return abs(left - right) / scale if scale else 0.0


def wrapped_phase_difference(left: float, right: float) -> float:
    return abs((left - right + math.pi) % (2 * math.pi) - math.pi)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def aggregate(rows: dict[tuple[int, str], dict[str, str]], particles: int) -> dict[str, float]:
    event = "handoff"
    elapsed = values(rows, event, "elapsed_time_us")
    radius = values(rows, event, "radial_position_mm")
    divergence = values(rows, event, "divergence_angle_deg")
    energy = values(rows, event, "kinetic_energy_eV")
    return {
        "handoff_particles": len(elapsed),
        "transmission": len(elapsed) / particles,
        "mean_tof_us": mean(elapsed),
        "p95_tof_us": percentile(elapsed, 0.95),
        "rms_radius_mm": rms(radius),
        "p95_radius_mm": percentile(radius, 0.95),
        "rms_divergence_deg": rms(divergence),
        "p95_divergence_deg": percentile(divergence, 0.95),
        "mean_energy_eV": mean(energy),
        "max_rod_radius_mm": max(values(rows, "terminal", "max_rod_radius_mm")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comsol", type=Path, required=True)
    parser.add_argument("--simion", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--interface-mode", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paired-output", type=Path, required=True)
    args = parser.parse_args()

    comsol, simion = load(args.comsol), load(args.simion)
    resolved = json.loads(args.resolved.read_text(encoding="utf-8"))
    interface_mode = json.loads(args.interface_mode.read_text(encoding="utf-8"))
    source_ids_c = sorted(particle_id for particle_id, event in comsol if event == "source")
    source_ids_s = sorted(particle_id for particle_id, event in simion if event == "source")
    if source_ids_c != source_ids_s or not source_ids_c:
        raise AssertionError("paired source particle IDs differ")
    particles = len(source_ids_c)
    c_aggregate, s_aggregate = aggregate(comsol, particles), aggregate(simion, particles)

    paired: list[dict[str, float | int]] = []
    for particle_id in source_ids_c:
        c = comsol.get((particle_id, "handoff"))
        s = simion.get((particle_id, "handoff"))
        if c is None or s is None:
            continue
        dx = float(c["transverse_x_mm"]) - float(s["transverse_x_mm"])
        dy = float(c["transverse_y_mm"]) - float(s["transverse_y_mm"])
        dvz = float(c["velocity_axial_m_s"]) - float(s["velocity_axial_m_s"])
        dvx = float(c["velocity_x_m_s"]) - float(s["velocity_x_m_s"])
        dvy = float(c["velocity_y_m_s"]) - float(s["velocity_y_m_s"])
        paired.append({
            "particle_id": particle_id,
            "position_residual_mm": math.hypot(dx, dy),
            "velocity_residual_m_s": math.sqrt(dvz * dvz + dvx * dvx + dvy * dvy),
            "tof_residual_us": float(c["elapsed_time_us"]) - float(s["elapsed_time_us"]),
            "energy_residual_eV": float(c["kinetic_energy_eV"]) - float(s["kinetic_energy_eV"]),
            "rf_phase_residual_rad": wrapped_phase_difference(float(c["rf_phase_rad"]), float(s["rf_phase_rad"])),
        })

    targets = interface_mode["candidate_acceptance_targets"]
    comparison = {
        "transmission_absolute_difference": abs(c_aggregate["transmission"] - s_aggregate["transmission"]),
        "mean_tof_relative_difference": relative_difference(c_aggregate["mean_tof_us"], s_aggregate["mean_tof_us"]),
        "rms_radius_relative_difference": relative_difference(c_aggregate["rms_radius_mm"], s_aggregate["rms_radius_mm"]),
        "rms_divergence_relative_difference": relative_difference(c_aggregate["rms_divergence_deg"], s_aggregate["rms_divergence_deg"]),
        "mean_energy_relative_difference": relative_difference(c_aggregate["mean_energy_eV"], s_aggregate["mean_energy_eV"]),
        "paired_mean_position_residual_mm": mean([row["position_residual_mm"] for row in paired]),
        "paired_p95_position_residual_mm": percentile([row["position_residual_mm"] for row in paired], 0.95),
        "paired_mean_velocity_residual_m_s": mean([row["velocity_residual_m_s"] for row in paired]),
        "paired_p95_velocity_residual_m_s": percentile([row["velocity_residual_m_s"] for row in paired], 0.95),
        "paired_mean_absolute_tof_residual_us": mean([abs(row["tof_residual_us"]) for row in paired]),
        "paired_mean_absolute_energy_residual_eV": mean([abs(row["energy_residual_eV"]) for row in paired]),
        "paired_mean_absolute_rf_phase_residual_rad": mean([row["rf_phase_residual_rad"] for row in paired]),
    }
    diagnostic_targets = {
        "transmission": comparison["transmission_absolute_difference"] <= targets["cross_solver_transmission_absolute_difference"],
        "mean_tof": comparison["mean_tof_relative_difference"] <= targets["cross_solver_relative_mean_tof_difference"],
        "rms_radius": comparison["rms_radius_relative_difference"] <= targets["cross_solver_relative_rms_output_radius_difference"],
        "rms_divergence": comparison["rms_divergence_relative_difference"] <= targets["cross_solver_relative_rms_divergence_difference"],
        "mean_energy": comparison["mean_energy_relative_difference"] <= targets["cross_solver_relative_mean_energy_difference"],
    }
    official = resolved["mode"]["numerics"]
    regression_gates = {
        "particle_identity": len(paired) == particles,
        "transmission": comparison["transmission_absolute_difference"] <= official["cross_solver_transmission_absolute_tolerance"],
        "mean_tof": comparison["mean_tof_relative_difference"] <= official["cross_solver_relative_mean_tof_tolerance"],
        "confinement": max(c_aggregate["max_rod_radius_mm"], s_aggregate["max_rod_radius_mm"]) < resolved["geometry_mm"]["field_radius_r0"],
    }
    minimum = interface_mode["numerics"]["minimum_diagnostic_particles"]
    interface_evaluated = particles >= minimum
    accepted = all(regression_gates.values()) and (
        not interface_evaluated or all(diagnostic_targets.values())
    )
    result = {
        "status": "PASS" if accepted else "FAIL",
        "scope": "interface_readiness" if interface_evaluated else "official_n100_phase_space_regression",
        "particles": particles,
        "interface_acceptance_formally_evaluated": interface_evaluated,
        "minimum_interface_diagnostic_particles": minimum,
        "inputs": {
            "comsol_particle_state_sha256": sha256(args.comsol),
            "simion_particle_state_sha256": sha256(args.simion),
        },
        "comsol": c_aggregate,
        "simion": s_aggregate,
        "comparison": comparison,
        "regression_gates": regression_gates,
        "candidate_interface_targets_diagnostic_only": diagnostic_targets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with args.paired_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(paired[0]))
        writer.writeheader()
        writer.writerows(paired)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
