"""Particle-event comparison primitives."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


EventKey = tuple[int, str]
EventTable = dict[EventKey, dict[str, str]]


def load_event_table(path: Path) -> EventTable:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {(int(row["particle_id"]), row["event"]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate particle event in {path}")
    return result


def event_ids(rows: EventTable, event: str) -> set[int]:
    return {particle_id for particle_id, row_event in rows if row_event == event}


def table_ids(rows: EventTable) -> set[int]:
    return {particle_id for particle_id, _ in rows}


def source_id_evidence(
    left: EventTable, right: EventTable, particle_count: int
) -> dict[str, Any]:
    expected = set(range(1, particle_count + 1))
    left_ids = event_ids(left, "source")
    right_ids = event_ids(right, "source")
    left_unexpected = table_ids(left) - expected
    right_unexpected = table_ids(right) - expected
    return {
        "valid": (
            left_ids == expected
            and right_ids == expected
            and not left_unexpected
            and not right_unexpected
        ),
        "expected_count": particle_count,
        "left_missing_ids": sorted(expected - left_ids),
        "left_extra_ids": sorted(left_ids - expected),
        "left_unexpected_event_ids": sorted(left_unexpected),
        "right_missing_ids": sorted(expected - right_ids),
        "right_extra_ids": sorted(right_ids - expected),
        "right_unexpected_event_ids": sorted(right_unexpected),
    }


def _values(rows: EventTable, event: str, name: str) -> list[float]:
    return [
        float(row[name])
        for (_, row_event), row in sorted(rows.items())
        if row_event == event
    ]


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
    return ordered[lower] + (position - lower) * (
        ordered[upper] - ordered[lower]
    )


def optional_mean(data: list[float]) -> float | None:
    return mean(data) if data else None


def optional_rms(data: list[float]) -> float | None:
    return rms(data) if data else None


def optional_percentile(
    data: list[float], probability: float
) -> float | None:
    return percentile(data, probability) if data else None


def symmetric_relative_difference(left: float, right: float) -> float:
    scale = (abs(left) + abs(right)) / 2
    return abs(left - right) / scale if scale else 0.0


def optional_symmetric_relative_difference(
    left: float | None, right: float | None
) -> float | None:
    if left is None or right is None:
        return None
    return symmetric_relative_difference(left, right)


def wrapped_phase_difference(left: float, right: float) -> float:
    return abs((left - right + math.pi) % (2 * math.pi) - math.pi)


def aggregate_handoff(
    rows: EventTable, particle_count: int
) -> dict[str, float | int | None]:
    elapsed = _values(rows, "handoff", "elapsed_time_us")
    radius = _values(rows, "handoff", "radial_position_mm")
    divergence = _values(rows, "handoff", "divergence_angle_deg")
    energy = _values(rows, "handoff", "kinetic_energy_eV")
    terminal_radius = _values(rows, "terminal", "max_rod_radius_mm")
    return {
        "handoff_particles": len(elapsed),
        "transmission": len(elapsed) / particle_count,
        "mean_tof_us": optional_mean(elapsed),
        "p95_tof_us": optional_percentile(elapsed, 0.95),
        "rms_radius_mm": optional_rms(radius),
        "p95_radius_mm": optional_percentile(radius, 0.95),
        "rms_divergence_deg": optional_rms(divergence),
        "p95_divergence_deg": optional_percentile(divergence, 0.95),
        "mean_energy_eV": optional_mean(energy),
        "max_rod_radius_mm": max(terminal_radius)
        if terminal_radius
        else None,
    }


def residual_values(
    particle_id: int,
    left: dict[str, str],
    right: dict[str, str],
) -> dict[str, float | int]:
    dx = float(left["transverse_x_mm"]) - float(right["transverse_x_mm"])
    dy = float(left["transverse_y_mm"]) - float(right["transverse_y_mm"])
    dvz = float(left["velocity_axial_m_s"]) - float(
        right["velocity_axial_m_s"]
    )
    dvx = float(left["velocity_x_m_s"]) - float(right["velocity_x_m_s"])
    dvy = float(left["velocity_y_m_s"]) - float(right["velocity_y_m_s"])
    return {
        "particle_id": particle_id,
        "position_residual_mm": math.hypot(dx, dy),
        "velocity_residual_m_s": math.sqrt(
            dvz * dvz + dvx * dvx + dvy * dvy
        ),
        "tof_residual_us": float(left["elapsed_time_us"])
        - float(right["elapsed_time_us"]),
        "energy_residual_eV": float(left["kinetic_energy_eV"])
        - float(right["kinetic_energy_eV"]),
        "rf_phase_residual_rad": wrapped_phase_difference(
            float(left["rf_phase_rad"]), float(right["rf_phase_rad"])
        ),
    }


def pair_event_census(
    left: EventTable,
    right: EventTable,
    expected_ids: set[int],
    event: str = "handoff",
) -> tuple[list[dict[str, float | int | str]], list[dict[str, float | int]]]:
    all_ids = sorted(
        expected_ids
        | table_ids(left)
        | table_ids(right)
    )
    census: list[dict[str, float | int | str]] = []
    residuals: list[dict[str, float | int]] = []
    for particle_id in all_ids:
        left_row = left.get((particle_id, event))
        right_row = right.get((particle_id, event))
        status = (
            "paired"
            if left_row is not None and right_row is not None
            else "left_only"
            if left_row is not None
            else "right_only"
            if right_row is not None
            else "neither"
        )
        row: dict[str, float | int | str] = {
            "particle_id": particle_id,
            "pair_status": status,
            "left_event": int(left_row is not None),
            "right_event": int(right_row is not None),
            "position_residual_mm": "",
            "velocity_residual_m_s": "",
            "tof_residual_us": "",
            "energy_residual_eV": "",
            "rf_phase_residual_rad": "",
        }
        if left_row is not None and right_row is not None:
            residual = residual_values(particle_id, left_row, right_row)
            row.update(residual)
            residuals.append(residual)
        census.append(row)
    return census, residuals


def aggregate_comparison(
    left: dict[str, float | int | None],
    right: dict[str, float | int | None],
    residuals: list[dict[str, float | int]],
) -> dict[str, float | None]:
    return {
        "transmission_absolute_difference": abs(
            float(left["transmission"]) - float(right["transmission"])
        ),
        "mean_tof_relative_difference": optional_symmetric_relative_difference(
            left["mean_tof_us"], right["mean_tof_us"]
        ),
        "rms_radius_relative_difference": optional_symmetric_relative_difference(
            left["rms_radius_mm"], right["rms_radius_mm"]
        ),
        "rms_divergence_relative_difference": (
            optional_symmetric_relative_difference(
                left["rms_divergence_deg"], right["rms_divergence_deg"]
            )
        ),
        "mean_energy_relative_difference": (
            optional_symmetric_relative_difference(
                left["mean_energy_eV"], right["mean_energy_eV"]
            )
        ),
        "paired_mean_position_residual_mm": optional_mean(
            [float(row["position_residual_mm"]) for row in residuals]
        ),
        "paired_p95_position_residual_mm": optional_percentile(
            [float(row["position_residual_mm"]) for row in residuals], 0.95
        ),
        "paired_mean_velocity_residual_m_s": optional_mean(
            [float(row["velocity_residual_m_s"]) for row in residuals]
        ),
        "paired_p95_velocity_residual_m_s": optional_percentile(
            [float(row["velocity_residual_m_s"]) for row in residuals], 0.95
        ),
        "paired_mean_absolute_tof_residual_us": optional_mean(
            [abs(float(row["tof_residual_us"])) for row in residuals]
        ),
        "paired_mean_absolute_energy_residual_eV": optional_mean(
            [abs(float(row["energy_residual_eV"])) for row in residuals]
        ),
        "paired_mean_absolute_rf_phase_residual_rad": optional_mean(
            [float(row["rf_phase_residual_rad"]) for row in residuals]
        ),
    }


def write_census(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    left_label: str,
    right_label: str,
) -> None:
    serialized = []
    for source in rows:
        row = dict(source)
        row[f"{left_label}_event"] = row.pop("left_event")
        row[f"{right_label}_event"] = row.pop("right_event")
        row["pair_status"] = (
            str(row["pair_status"])
            .replace("left_only", f"{left_label}_only")
            .replace("right_only", f"{right_label}_only")
        )
        serialized.append(row)
    fields = [
        "particle_id",
        "pair_status",
        f"{left_label}_event",
        f"{right_label}_event",
        "position_residual_mm",
        "velocity_residual_m_s",
        "tof_residual_us",
        "energy_residual_eV",
        "rf_phase_residual_rad",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(serialized)
