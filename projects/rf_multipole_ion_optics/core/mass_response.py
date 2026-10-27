"""Solver-neutral paired mass-response aggregation, functional checks and plotting."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from common.analysis.peak_metrics import half_height_width
from projects.rf_multipole_ion_optics.core.paired_mass_scan import load_ion_rows


matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


TERMINAL_STATUSES = {"transmitted", "lost", "timeout"}


def prepare_response_analysis(response: list[dict[str, Any]]) -> dict[str, Any]:
    """Prepare one sampled m/z response for metrics and plots, without qualification.

    The legacy band is the envelope of all samples at or above half maximum.
    The separate interpolated width uses the nearest half-height crossings
    around the first global maximum, through the common numerical authority.
    Missing crossings and an all-zero response are unavailable widths, not
    extrapolated bands. Invalid or unordered input raises ``ValueError``.
    """
    masses = np.asarray([row["mass_Th"] for row in response], dtype=float)
    transmission = np.asarray([row["transmission_fraction"] for row in response], dtype=float)
    if masses.ndim != 1 or transmission.ndim != 1 or masses.size < 3:
        raise ValueError("sampled mass response requires at least three scalar mass samples")
    if not np.all(np.isfinite(masses)) or not np.all(np.isfinite(transmission)):
        raise ValueError("sampled mass response must contain only finite values")
    if not np.all(masses[1:] > masses[:-1]):
        raise ValueError("sampled mass response masses must be sorted and unique")
    if np.any(transmission < 0) or np.any(transmission > 1):
        raise ValueError("sampled transmission fractions must be within [0, 1]")
    peak_index = int(np.argmax(transmission))
    peak = float(transmission[peak_index])
    result: dict[str, Any] = {
        "schema_version": 1,
        "method_id": "sampled_mass_response_linear_half_height_v1",
        "status": "unavailable_no_positive_response",
        "mass_axis": {"quantity": "mass_to_charge", "unit": "Th"},
        "sample_count": int(masses.size),
        "mass_samples_Th": masses.tolist(),
        "transmission_fraction_samples": transmission.tolist(),
        "peak_selection": "first_global_maximum",
        "crossing_policy": "nearest_half_height_on_each_side_linear_interpolation",
        "peak_mass_Th": None,
        "peak_transmission": peak,
        "observed_half_maximum_band_Th": None,
        "interpolated_main_peak_fwhm_Th": None,
        "half_height_crossings_Th": None,
        "missing_half_height_crossings": [],
        "resolution_claim_allowed": False,
        "species_scope": "positive_single_charge_mass_amu_equals_mass_to_charge_Th",
    }
    if peak == 0:
        return result
    half_maximum = 0.5 * peak
    half_indices = np.flatnonzero(transmission >= half_maximum)
    result["peak_mass_Th"] = float(masses[peak_index])
    result["observed_half_maximum_band_Th"] = [
        float(masses[half_indices[0]]), float(masses[half_indices[-1]]),
    ]
    missing = []
    if not np.any(transmission[:peak_index + 1] <= half_maximum):
        missing.append("left")
    if not np.any(transmission[peak_index:] <= half_maximum):
        missing.append("right")
    if missing:
        result.update(status="unavailable_missing_half_height_crossings",
                      missing_half_height_crossings=missing)
        return result
    width, left, right, _ = half_height_width(masses, transmission)
    result.update(status="computed", interpolated_main_peak_fwhm_Th=width,
                  half_height_crossings_Th=[left, right])
    return result


def load_ion_masses(path: Path) -> dict[int, float]:
    """Return m/z in Th only after validating the ION11 physical mass/+1 scope."""
    rows = load_ion_rows(path)
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
    analysis = prepare_response_analysis(response)
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
        "sampled_response_analysis": analysis,
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
    analysis: dict[str, Any],
) -> None:
    """Export an accessible report-profile mass response with actual samples."""
    masses = analysis["mass_samples_Th"]
    transmission = analysis["transmission_fraction_samples"]
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
        width = analysis["interpolated_main_peak_fwhm_Th"]
        if width is not None:
            left, right = analysis["half_height_crossings_Th"]
            axis.hlines(0.5 * analysis["peak_transmission"], left, right,
                        color="0.3", linestyle="--", linewidth=1)
            width_label = f"Interpolated main-peak width: {width:.4g} Th"
        elif analysis["missing_half_height_crossings"]:
            missing = "/".join(analysis["missing_half_height_crossings"])
            width_label = f"Width unavailable: missing {missing} half-height crossing"
        else:
            width_label = "Width unavailable: no positive response"
        axis.set_title(width_label, fontsize=9)
        axis.grid(axis="y", linewidth=0.5, alpha=0.3)
        axis.legend(frameon=False, loc="lower center")
        figure.savefig(path, format="png", dpi=240, facecolor="white")
        plt.close(figure)
