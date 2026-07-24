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


def optional_mean(data: list[float]) -> float | None:
    return mean(data) if data else None


def optional_rms(data: list[float]) -> float | None:
    return rms(data) if data else None


def optional_percentile(data: list[float], probability: float) -> float | None:
    return percentile(data, probability) if data else None


def optional_relative_difference(
    left: float | None, right: float | None
) -> float | None:
    if left is None or right is None:
        return None
    return relative_difference(left, right)


def within(value: float | None, limit: float) -> bool:
    return value is not None and value <= limit


def count_particle_rows(path: Path) -> int:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return sum(1 for line in lines if line.strip())


def aggregate(
    rows: dict[tuple[int, str], dict[str, str]], particles: int
) -> dict[str, float | int | None]:
    event = "handoff"
    elapsed = values(rows, event, "elapsed_time_us")
    radius = values(rows, event, "radial_position_mm")
    divergence = values(rows, event, "divergence_angle_deg")
    energy = values(rows, event, "kinetic_energy_eV")
    terminal_radius = values(rows, "terminal", "max_rod_radius_mm")
    return {
        "handoff_particles": len(elapsed),
        "transmission": len(elapsed) / particles,
        "mean_tof_us": optional_mean(elapsed),
        "p95_tof_us": optional_percentile(elapsed, 0.95),
        "rms_radius_mm": optional_rms(radius),
        "p95_radius_mm": optional_percentile(radius, 0.95),
        "rms_divergence_deg": optional_rms(divergence),
        "p95_divergence_deg": optional_percentile(divergence, 0.95),
        "mean_energy_eV": optional_mean(energy),
        "max_rod_radius_mm": max(terminal_radius) if terminal_radius else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comsol", type=Path, required=True)
    parser.add_argument("--simion", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--regression-mode", type=Path, required=True)
    parser.add_argument("--interface-mode", type=Path, required=True)
    parser.add_argument("--particles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paired-output", type=Path, required=True)
    args = parser.parse_args()

    comsol, simion = load(args.comsol), load(args.simion)
    resolved = json.loads(args.resolved.read_text(encoding="utf-8"))
    regression_mode = json.loads(args.regression_mode.read_text(encoding="utf-8"))
    interface_mode = json.loads(args.interface_mode.read_text(encoding="utf-8"))
    if regression_mode.get("mode") != "transport_no_collision":
        raise ValueError("regression mode identity must be transport_no_collision")
    if interface_mode.get("mode") != "transport_interface_readiness":
        raise ValueError("interface mode identity must be transport_interface_readiness")
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("resolved physical authority role differs")
    source_ids_c = sorted(particle_id for particle_id, event in comsol if event == "source")
    source_ids_s = sorted(particle_id for particle_id, event in simion if event == "source")
    particles = count_particle_rows(args.particles)
    if particles <= 0:
        raise ValueError("particle source is empty")
    expected_ids = set(range(1, particles + 1))
    all_source_ids = sorted(expected_ids | set(source_ids_c) | set(source_ids_s))
    source_identity = (
        set(source_ids_c) == expected_ids and set(source_ids_s) == expected_ids
    )
    c_aggregate, s_aggregate = aggregate(comsol, particles), aggregate(simion, particles)

    paired: list[dict[str, float | int | str]] = []
    paired_residuals: list[dict[str, float | int]] = []
    for particle_id in all_source_ids:
        c = comsol.get((particle_id, "handoff"))
        s = simion.get((particle_id, "handoff"))
        pair_status = (
            "paired"
            if c is not None and s is not None
            else "comsol_only"
            if c is not None
            else "simion_only"
            if s is not None
            else "neither"
        )
        row: dict[str, float | int | str] = {
            "particle_id": particle_id,
            "pair_status": pair_status,
            "comsol_handoff": int(c is not None),
            "simion_handoff": int(s is not None),
            "position_residual_mm": "",
            "velocity_residual_m_s": "",
            "tof_residual_us": "",
            "energy_residual_eV": "",
            "rf_phase_residual_rad": "",
        }
        if c is not None and s is not None:
            dx = float(c["transverse_x_mm"]) - float(s["transverse_x_mm"])
            dy = float(c["transverse_y_mm"]) - float(s["transverse_y_mm"])
            dvz = float(c["velocity_axial_m_s"]) - float(s["velocity_axial_m_s"])
            dvx = float(c["velocity_x_m_s"]) - float(s["velocity_x_m_s"])
            dvy = float(c["velocity_y_m_s"]) - float(s["velocity_y_m_s"])
            residual = {
                "particle_id": particle_id,
                "position_residual_mm": math.hypot(dx, dy),
                "velocity_residual_m_s": math.sqrt(
                    dvz * dvz + dvx * dvx + dvy * dvy
                ),
                "tof_residual_us": float(c["elapsed_time_us"])
                - float(s["elapsed_time_us"]),
                "energy_residual_eV": float(c["kinetic_energy_eV"])
                - float(s["kinetic_energy_eV"]),
                "rf_phase_residual_rad": wrapped_phase_difference(
                    float(c["rf_phase_rad"]), float(s["rf_phase_rad"])
                ),
            }
            row.update(residual)
            paired_residuals.append(residual)
        paired.append(row)

    targets = interface_mode["candidate_acceptance_targets"]
    comparison = {
        "transmission_absolute_difference": abs(c_aggregate["transmission"] - s_aggregate["transmission"]),
        "mean_tof_relative_difference": optional_relative_difference(c_aggregate["mean_tof_us"], s_aggregate["mean_tof_us"]),
        "rms_radius_relative_difference": optional_relative_difference(c_aggregate["rms_radius_mm"], s_aggregate["rms_radius_mm"]),
        "rms_divergence_relative_difference": optional_relative_difference(c_aggregate["rms_divergence_deg"], s_aggregate["rms_divergence_deg"]),
        "mean_energy_relative_difference": optional_relative_difference(c_aggregate["mean_energy_eV"], s_aggregate["mean_energy_eV"]),
        "paired_mean_position_residual_mm": optional_mean([float(row["position_residual_mm"]) for row in paired_residuals]),
        "paired_p95_position_residual_mm": optional_percentile([float(row["position_residual_mm"]) for row in paired_residuals], 0.95),
        "paired_mean_velocity_residual_m_s": optional_mean([float(row["velocity_residual_m_s"]) for row in paired_residuals]),
        "paired_p95_velocity_residual_m_s": optional_percentile([float(row["velocity_residual_m_s"]) for row in paired_residuals], 0.95),
        "paired_mean_absolute_tof_residual_us": optional_mean([abs(float(row["tof_residual_us"])) for row in paired_residuals]),
        "paired_mean_absolute_energy_residual_eV": optional_mean([abs(float(row["energy_residual_eV"])) for row in paired_residuals]),
        "paired_mean_absolute_rf_phase_residual_rad": optional_mean([float(row["rf_phase_residual_rad"]) for row in paired_residuals]),
    }
    diagnostic_targets = {
        "minimum_transmission_comsol": c_aggregate["transmission"] >= targets["minimum_transmission"],
        "minimum_transmission_simion": s_aggregate["transmission"] >= targets["minimum_transmission"],
        "transmission": within(comparison["transmission_absolute_difference"], targets["cross_solver_transmission_absolute_difference"]),
        "mean_tof": within(comparison["mean_tof_relative_difference"], targets["cross_solver_relative_mean_tof_difference"]),
        "rms_radius": within(comparison["rms_radius_relative_difference"], targets["cross_solver_relative_rms_output_radius_difference"]),
        "rms_divergence": within(comparison["rms_divergence_relative_difference"], targets["cross_solver_relative_rms_divergence_difference"]),
        "mean_energy": within(comparison["mean_energy_relative_difference"], targets["cross_solver_relative_mean_energy_difference"]),
    }
    regression_numerics = regression_mode["numerics"]
    maximum_radius = (
        max(c_aggregate["max_rod_radius_mm"], s_aggregate["max_rod_radius_mm"])
        if c_aggregate["max_rod_radius_mm"] is not None
        and s_aggregate["max_rod_radius_mm"] is not None
        else None
    )
    regression_gates = {
        "source_identity": source_identity,
        "particle_identity": len(paired_residuals) == particles,
        "minimum_transmission_comsol": c_aggregate["transmission"] >= regression_numerics["minimum_expected_transmission"],
        "minimum_transmission_simion": s_aggregate["transmission"] >= regression_numerics["minimum_expected_transmission"],
        "transmission": comparison["transmission_absolute_difference"] <= regression_numerics["cross_solver_transmission_absolute_tolerance"],
        "mean_tof": within(comparison["mean_tof_relative_difference"], regression_numerics["cross_solver_relative_mean_tof_tolerance"]),
        "confinement": maximum_radius is not None and maximum_radius < resolved["geometry_mm"]["inscribed_radius_r0"],
    }
    minimum = interface_mode["numerics"]["minimum_diagnostic_particles"]
    interface_evaluated = particles >= minimum
    accepted = all(regression_gates.values()) and (
        not interface_evaluated or all(diagnostic_targets.values())
    )
    result = {
        "status": "PASS" if accepted else "FAIL",
        "execution_status": "success",
        "scope": "interface_readiness" if interface_evaluated else "official_n100_phase_space_regression",
        "particles": particles,
        "source_particle_count": particles,
        "paired_handoff_particles": len(paired_residuals),
        "interface_acceptance_formally_evaluated": interface_evaluated,
        "minimum_interface_diagnostic_particles": minimum,
        "inputs": {
            "comsol_particle_state_sha256": sha256(args.comsol),
            "simion_particle_state_sha256": sha256(args.simion),
            "resolved_physical_authority_sha256": sha256(args.resolved),
            "regression_mode_sha256": sha256(args.regression_mode),
            "interface_mode_sha256": sha256(args.interface_mode),
            "particle_source_sha256": sha256(args.particles),
        },
        "comsol": c_aggregate,
        "simion": s_aggregate,
        "comparison": comparison,
        "regression_gates": regression_gates,
        "candidate_interface_targets_diagnostic_only": diagnostic_targets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    paired_fields = [
        "particle_id",
        "pair_status",
        "comsol_handoff",
        "simion_handoff",
        "position_residual_mm",
        "velocity_residual_m_s",
        "tof_residual_us",
        "energy_residual_eV",
        "rf_phase_residual_rad",
    ]
    with args.paired_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=paired_fields)
        writer.writeheader()
        writer.writerows(paired)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
