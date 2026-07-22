"""Select a provisional circular-rod multipole geometry from 2D field samples."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def harmonic_amplitude(values: list[float], angles: list[float], order: int) -> float:
    """Return the cosine/sine Fourier amplitude for one positive angular order."""
    scale = 2.0 / len(values)
    cosine = scale * sum(value * math.cos(order * angle) for value, angle in zip(values, angles))
    sine = scale * sum(value * math.sin(order * angle) for value, angle in zip(values, angles))
    return math.hypot(cosine, sine)


def harmonic_components(values: list[float], angles: list[float], order: int) -> tuple[float, float]:
    """Return signed cosine and sine Fourier coefficients."""
    scale = 2.0 / len(values)
    cosine = scale * sum(value * math.cos(order * angle) for value, angle in zip(values, angles))
    sine = scale * sum(value * math.sin(order * angle) for value, angle in zip(values, angles))
    return cosine, sine


def characterize_group(
    rows: list[dict[str, str]], radial_order: int, r0_mm: float
) -> dict[str, float]:
    angles = [float(row["theta_rad"]) for row in rows]
    values = [float(row["potential_V"]) for row in rows]
    radius_mm = float(rows[0]["sample_radius_mm"])
    main_cosine, main_sine = harmonic_components(values, angles, radial_order)
    main = math.hypot(main_cosine, main_sine)
    if main <= 0:
        raise ValueError("target multipole harmonic is not positive")
    result = {
        "sample_radius_mm": radius_mm,
        "main_boundary_amplitude_V": main * (r0_mm / radius_mm) ** radial_order,
        "main_boundary_cosine_V": main_cosine * (r0_mm / radius_mm) ** radial_order,
        "main_boundary_sine_V": main_sine * (r0_mm / radius_mm) ** radial_order,
    }
    for multiplier in (3, 5):
        order = multiplier * radial_order
        cosine, sine = harmonic_components(values, angles, order)
        amplitude = math.hypot(cosine, sine)
        result[f"normalized_a{order}_over_a{radial_order}"] = (
            amplitude / main * (r0_mm / radius_mm) ** (order - radial_order)
        )
        result[f"signed_cosine_a{order}_over_a{radial_order}"] = (
            cosine / main_cosine * (r0_mm / radius_mm) ** (order - radial_order)
        )
        result[f"signed_sine_a{order}_over_a{radial_order}"] = (
            sine / main_cosine * (r0_mm / radius_mm) ** (order - radial_order)
        )
    return result


def aggregate_candidate(
    ratio: float, groups: list[dict[str, float]], contract: dict[str, Any]
) -> dict[str, Any]:
    radial_order = int(contract["multipole"]["radial_order_n"])
    r0_mm = float(contract["geometry_mm"]["inscribed_radius_r0"])
    rod_radius_mm = ratio * r0_mm
    center_mm = r0_mm + rod_radius_mm
    electrode_count = 2 * radial_order
    gap_mm = 2 * center_mm * math.sin(math.pi / electrode_count) - 2 * rod_radius_mm
    harmonic_keys = [
        f"normalized_a{3 * radial_order}_over_a{radial_order}",
        f"normalized_a{5 * radial_order}_over_a{radial_order}",
    ]
    means = {key: sum(group[key] for group in groups) / len(groups) for key in harmonic_keys}
    spreads = {key: max(group[key] for group in groups) - min(group[key] for group in groups) for key in harmonic_keys}
    main_mean = sum(group["main_boundary_amplitude_V"] for group in groups) / len(groups)
    main_cosine_mean = sum(group["main_boundary_cosine_V"] for group in groups) / len(groups)
    signed_cosine = {
        str(radial_order): main_cosine_mean,
        str(3 * radial_order): main_cosine_mean * sum(
            group[f"signed_cosine_a{3 * radial_order}_over_a{radial_order}"] for group in groups
        ) / len(groups),
        str(5 * radial_order): main_cosine_mean * sum(
            group[f"signed_cosine_a{5 * radial_order}_over_a{radial_order}"] for group in groups
        ) / len(groups),
    }
    score = math.sqrt(sum(value * value for value in means.values()))
    return {
        "rod_radius_ratio": ratio,
        "rod_radius_mm": rod_radius_mm,
        "rod_center_radius_mm": center_mm,
        "minimum_adjacent_surface_gap_mm": gap_mm,
        "main_boundary_amplitude_V": main_mean,
        "boundary_cosine_coefficients_V": signed_cosine,
        "parasitic_harmonic_score": score,
        "harmonics": means,
        "cross_radius_spread": spreads,
        "sample_groups": groups,
    }


def analyze(rows: list[dict[str, str]], contract: dict[str, Any]) -> dict[str, Any]:
    radial_order = int(contract["multipole"]["radial_order_n"])
    r0_mm = float(contract["geometry_mm"]["inscribed_radius_r0"])
    grouped: dict[tuple[float, float], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(float(row["rod_radius_ratio"]), float(row["sample_radius_mm"]))].append(row)
    by_ratio: dict[float, list[dict[str, float]]] = defaultdict(list)
    for (ratio, _), sample_rows in grouped.items():
        by_ratio[ratio].append(characterize_group(sample_rows, radial_order, r0_mm))
    candidates = [aggregate_candidate(ratio, groups, contract) for ratio, groups in sorted(by_ratio.items())]
    minimum_gap = float(contract["selection"]["minimum_adjacent_surface_gap_mm"])
    minimum_main = float(contract["selection"]["minimum_main_boundary_amplitude_fraction_of_drive"])
    maximum_spread = float(contract["selection"]["maximum_cross_radius_absolute_harmonic_spread"])
    drive = float(contract["field_solve"]["rod_voltage_zero_to_peak_V"])
    eligible = [
        candidate for candidate in candidates
        if candidate["minimum_adjacent_surface_gap_mm"] >= minimum_gap
        and candidate["main_boundary_amplitude_V"] >= minimum_main * drive
        and max(candidate["cross_radius_spread"].values()) <= maximum_spread
    ]
    if not eligible:
        raise ValueError("no circular-rod candidate satisfies the frozen geometry and field constraints")
    selected = min(eligible, key=lambda candidate: candidate["parasitic_harmonic_score"])
    return {
        "schema_version": 1,
        "role": "multipole_round_rod_field_screen_metrics",
        "status": "PASS",
        "project_id": contract["project_id"],
        "model_level": "L2",
        "radial_order_n": radial_order,
        "electrode_count": 2 * radial_order,
        "field_solve_drive_V": float(contract["field_solve"]["rod_voltage_zero_to_peak_V"]),
        "selected_candidate": selected,
        "candidates": candidates,
        "claim_limit": contract["claim_limit"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    with args.samples.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    metrics = analyze(rows, contract)
    args.output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    selected = metrics["selected_candidate"]
    print(
        f"ROUND_ROD_SCREEN=PASS PROJECT={metrics['project_id']} "
        f"RATIO={selected['rod_radius_ratio']:.8g} SCORE={selected['parasitic_harmonic_score']:.6g}"
    )


if __name__ == "__main__":
    main()
