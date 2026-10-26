"""Solver-neutral paired mass-response aggregation, functional checks and plotting."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import matplotlib


matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


TERMINAL_STATUSES = {"transmitted", "lost", "timeout"}


def load_ion_masses(path: Path) -> dict[int, float]:
    """Return particle ID to mass-to-charge ratio from an eleven-column ION table."""
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    if not rows or any(len(row) != 11 for row in rows):
        raise ValueError("particle table must contain eleven-column rows")
    return {index: float(row[1]) for index, row in enumerate(rows, start=1)}


def load_terminal_statuses(path: Path) -> dict[int, str]:
    """Return exactly one terminal status for every particle in a canonical state CSV."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    terminal: dict[int, str] = {}
    all_ids: set[int] = set()
    for row in rows:
        particle_id = int(row["particle_id"])
        all_ids.add(particle_id)
        if row["event"] == "terminal":
            if particle_id in terminal:
                raise ValueError(f"duplicate terminal event for particle {particle_id}")
            if row["status"] not in TERMINAL_STATUSES:
                raise ValueError(f"unknown terminal status for particle {particle_id}: {row['status']}")
            terminal[particle_id] = row["status"]
    if set(terminal) != all_ids:
        raise ValueError("every particle must have exactly one terminal event")
    return terminal


def aggregate_response(masses: dict[int, float], statuses: dict[int, str]) -> list[dict[str, Any]]:
    """Aggregate transmitted counts by mass while preserving the full denominator."""
    if set(masses) != set(statuses):
        raise ValueError("particle table and state CSV particle IDs differ")
    grouped: dict[float, list[str]] = {}
    for particle_id, mass in masses.items():
        grouped.setdefault(mass, []).append(statuses[particle_id])
    response: list[dict[str, Any]] = []
    for mass in sorted(grouped):
        values = grouped[mass]
        transmitted = sum(value == "transmitted" for value in values)
        response.append({
            "mass_Th": mass,
            "particles": len(values),
            "transmitted": transmitted,
            "transmission_fraction": transmitted / len(values),
        })
    return response


def evaluate_functional_contrast(
    response: list[dict[str, Any]], calibration_mass_Th: float, acceptance: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate center transmission, endpoint rejection and their contrast."""
    if len(response) < 3:
        raise ValueError("functional mass response requires at least three masses")
    center = min(response, key=lambda row: abs(float(row["mass_Th"]) - calibration_mass_Th))
    endpoint_maximum = max(
        float(response[0]["transmission_fraction"]), float(response[-1]["transmission_fraction"])
    )
    center_transmission = float(center["transmission_fraction"])
    contrast = center_transmission - endpoint_maximum
    checks = {
        "center_transmission": center_transmission >= float(acceptance["minimum_center_transmission"]),
        "endpoint_rejection": endpoint_maximum <= float(acceptance["maximum_endpoint_transmission"]),
        "center_to_endpoint_contrast": contrast >= float(acceptance["minimum_center_to_endpoint_contrast"]),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "center_sample_mass_Th": float(center["mass_Th"]),
        "center_transmission": center_transmission,
        "maximum_endpoint_transmission": endpoint_maximum,
        "center_to_endpoint_contrast": contrast,
    }


def write_response(path: Path, response: list[dict[str, Any]]) -> None:
    """Write the complete grouped response as CSV."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(response[0]))
        writer.writeheader()
        writer.writerows(response)


def export_response_figure(
    path: Path,
    response: list[dict[str, Any]],
    passband_Th: tuple[float, float],
    solver_label: str,
) -> None:
    """Export an accessible report-profile mass response with actual samples."""
    masses = [float(row["mass_Th"]) for row in response]
    transmission = [float(row["transmission_fraction"]) for row in response]
    sample_counts = {int(row["particles"]) for row in response}
    if len(sample_counts) != 1:
        raise ValueError("response figure requires the same particle count at every mass")
    particles_per_mass = sample_counts.pop()
    with plt.rc_context({"font.size": 8, "axes.labelsize": 9, "legend.fontsize": 8}):
        figure, axis = plt.subplots(figsize=(160 / 25.4, 90 / 25.4), constrained_layout=True)
        axis.axvspan(*passband_Th, color="#56B4E9", alpha=0.22, label="Ideal theory passband")
        axis.plot(
            masses,
            transmission,
            color="#D55E00",
            marker="s",
            markersize=4,
            linewidth=1.2,
            label=f"{solver_label} (N={particles_per_mass}/mass)",
        )
        axis.set_xlabel("Mass-to-charge ratio (Th)")
        axis.set_ylabel("Transmission fraction")
        axis.set_ylim(-0.03, 1.03)
        axis.grid(axis="y", linewidth=0.5, alpha=0.3)
        axis.legend(frameon=False, loc="lower center")
        figure.savefig(path, format="png", dpi=240, facecolor="white")
        plt.close(figure)
