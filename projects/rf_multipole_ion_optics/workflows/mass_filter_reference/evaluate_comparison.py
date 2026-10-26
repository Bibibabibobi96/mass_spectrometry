"""Compare governed L0, L1, SIMION and COMSOL mass responses."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from .theory import theory_masses


def read_response(path: Path) -> dict[float, dict[str, str]]:
    """Read one mass response and reject duplicate masses."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    response = {float(row["mass_Th"]): row for row in rows}
    if not response or len(response) != len(rows):
        raise ValueError(f"mass response is empty or contains duplicates: {path}")
    for mass, row in response.items():
        transmission = float(row["transmission_fraction"])
        particles = int(row["particles"])
        transmitted = int(row["transmitted"])
        if (
            not math.isfinite(mass)
            or not math.isfinite(transmission)
            or not 0.0 <= transmission <= 1.0
            or particles <= 0
            or not 0 <= transmitted <= particles
        ):
            raise ValueError(f"mass response contains an invalid value: {path}")
        if not math.isclose(
            transmission,
            transmitted / particles,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"mass response transmission fraction is inconsistent: {path}"
            )
    return response


def load_metrics(path: Path, expected_role: str) -> dict[str, Any]:
    """Load one solver-specific metrics record."""
    metrics = json.loads(path.read_text(encoding="utf-8-sig"))
    if metrics.get("role") != expected_role or metrics.get("status") not in {
        "PASS",
        "FAIL",
    }:
        raise ValueError(f"source metrics identity or status differs: {path}")
    return metrics


def compare_responses(
    comsol_path: Path,
    simion_path: Path,
    l1_path: Path,
    baseline_path: Path,
    mode_path: Path,
    source_metrics: dict[str, dict[str, Any]],
    comsol_source_particles: int,
    simion_source_particles: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the diagnostic comparison and its comparison-owned decision."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
    mode = json.loads(mode_path.read_text(encoding="utf-8-sig"))
    if (
        mode.get("schema_version") != 3
        or mode.get("mode") != "mass_filter_reference"
    ):
        raise ValueError("mass-response comparison mode identity differs")
    failed_sources = [
        name
        for name, document in source_metrics.items()
        if document["status"] != "PASS"
    ]
    if failed_sources:
        raise ValueError(
            "source functional metrics failed: "
            + ", ".join(sorted(failed_sources))
        )
    expected = [
        float(value)
        for value in mode["mass_scan_spec"]["paired_source_masses_Th"]
    ]
    responses = {
        "COMSOL": read_response(comsol_path),
        "SIMION": read_response(simion_path),
        "L1": read_response(l1_path),
    }
    for name in ("COMSOL", "SIMION"):
        response = responses[name]
        if sorted(response) != sorted(expected):
            raise ValueError(f"{name} response masses differ from the governed mode")
    l1_grid = mode["functional_screen"]["mass_scan_Th"]
    l1_min = float(l1_grid["min"])
    l1_max = float(l1_grid["max"])
    l1_step = float(l1_grid["step"])
    l1_count = round((l1_max - l1_min) / l1_step) + 1
    expected_l1 = [l1_min + index * l1_step for index in range(l1_count)]
    if sorted(responses["L1"]) != expected_l1:
        raise ValueError("L1 response grid is incomplete or differs from the mode")
    solver_particle_counts = {
        name: {
            int(row["particles"]) for row in responses[name].values()
        }
        for name in ("COMSOL", "SIMION")
    }
    if (
        any(len(counts) != 1 for counts in solver_particle_counts.values())
        or solver_particle_counts["COMSOL"] != solver_particle_counts["SIMION"]
    ):
        raise ValueError("COMSOL and SIMION particles per mass differ")
    response_particles = next(iter(solver_particle_counts["COMSOL"]))
    if (
        comsol_source_particles <= 0
        or simion_source_particles <= 0
        or comsol_source_particles != simion_source_particles
        or response_particles != comsol_source_particles
    ):
        raise ValueError("solver response particle count differs from source N")
    if (
        int(source_metrics["COMSOL"].get("particles_per_mass", 0))
        != comsol_source_particles
        or int(source_metrics["SIMION"].get("particles_per_mass", 0))
        != simion_source_particles
    ):
        raise ValueError("solver source metrics particle count differs from source N")
    l1_counts = {
        int(row["particles"]) for row in responses["L1"].values()
    }
    if (
        len(l1_counts) != 1
        or int(source_metrics["L1"].get("particle_count_per_mass", 0))
        != next(iter(l1_counts))
    ):
        raise ValueError("L1 response particle count differs from source metrics")
    theory = theory_masses(baseline, mode)
    passband = (theory["low_mass_Th"], theory["high_mass_Th"])
    rows: list[dict[str, Any]] = []
    for mass in expected:
        comsol_value = float(responses["COMSOL"][mass]["transmission_fraction"])
        simion_value = float(responses["SIMION"][mass]["transmission_fraction"])
        l1_value = float(
            responses["L1"][mass]["transmission_fraction"]
        )
        rows.append(
            {
                "mass_Th": mass,
                "l0_class": (
                    "inside"
                    if passband[0] <= mass <= passband[1]
                    else "outside"
                ),
                "l1_transmission": l1_value,
                "simion_transmission": simion_value,
                "comsol_transmission": comsol_value,
                "comsol_minus_simion": comsol_value - simion_value,
            }
        )
    maximum_difference = max(
        abs(float(row["comsol_minus_simion"])) for row in rows
    )
    cross_policy = mode["cross_solver_functional_comparison"]
    threshold = cross_policy["maximum_absolute_transmission_difference"]
    tolerance_frozen = bool(cross_policy["acceptance_tolerance_frozen"])
    if not tolerance_frozen or threshold is None:
        decision = "NOT_EVALUATED"
    else:
        decision = (
            "PASS"
            if maximum_difference <= float(threshold)
            else "FAIL"
        )
    metrics = {
        "schema_version": 1,
        "role": "rf_quadrupole_mass_filter_response_comparison",
        "status": "success",
        "decision_status": decision,
        "mode": "mass_filter_reference",
        "maximum_absolute_comsol_simion_transmission_difference": (
            maximum_difference
        ),
        "source_functional_status": {
            name: document["status"]
            for name, document in sorted(source_metrics.items())
        },
        "theory": theory,
        "particles_per_mass": response_particles,
        "acceptance": {
            "maximum_absolute_transmission_difference": threshold,
            "acceptance_tolerance_frozen": tolerance_frozen,
        },
        "claim_limit": cross_policy["claim_limit"],
    }
    return rows, metrics


def write_comparison(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write the stable comparison table."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_comparison(
    path: Path,
    rows: list[dict[str, Any]],
    passband: tuple[float, float],
) -> None:
    """Render the diagnostic comparison figure."""
    masses = [float(row["mass_Th"]) for row in rows]
    styles = (
        ("l1_transmission", "L1 ideal finite length", "#009E73", "o"),
        ("simion_transmission", "SIMION finite geometry", "#0072B2", "s"),
        ("comsol_transmission", "COMSOL finite geometry", "#D55E00", "^"),
    )
    with plt.rc_context(
        {"font.size": 8, "axes.labelsize": 9, "legend.fontsize": 8}
    ):
        figure, axis = plt.subplots(
            figsize=(160 / 25.4, 90 / 25.4),
            constrained_layout=True,
        )
        axis.axvspan(
            *passband,
            color="#56B4E9",
            alpha=0.2,
            label="L0 ideal passband",
        )
        for key, label, color, marker in styles:
            axis.plot(
                masses,
                [float(row[key]) for row in rows],
                marker=marker,
                markersize=4,
                linewidth=1.2,
                color=color,
                label=label,
            )
        axis.set(
            xlabel="Mass-to-charge ratio (Th)",
            ylabel="Transmission fraction",
            ylim=(-0.03, 1.03),
        )
        axis.grid(axis="y", linewidth=0.5, alpha=0.3)
        axis.legend(frameon=False, loc="lower center")
        figure.savefig(path, format="png", dpi=240, facecolor="white")
        plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comsol-response", required=True, type=Path)
    parser.add_argument("--simion-response", required=True, type=Path)
    parser.add_argument("--l1-response", required=True, type=Path)
    parser.add_argument("--comsol-metrics", required=True, type=Path)
    parser.add_argument("--simion-metrics", required=True, type=Path)
    parser.add_argument("--l1-metrics", required=True, type=Path)
    parser.add_argument("--comsol-source-particles", required=True, type=int)
    parser.add_argument("--simion-source-particles", required=True, type=int)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--figure", required=True, type=Path)
    args = parser.parse_args()
    source_metrics = {
        "COMSOL": load_metrics(
            args.comsol_metrics,
            "rf_quadrupole_comsol_mass_filter_functional_metrics",
        ),
        "SIMION": load_metrics(
            args.simion_metrics,
            "rf_quadrupole_simion_mass_filter_functional_metrics",
        ),
        "L1": load_metrics(
            args.l1_metrics,
            "quadrupole_mass_filter_l1_metrics",
        ),
    }
    rows, metrics = compare_responses(
        args.comsol_response,
        args.simion_response,
        args.l1_response,
        args.baseline,
        args.mode,
        source_metrics,
        args.comsol_source_particles,
        args.simion_source_particles,
    )
    write_comparison(args.output, rows)
    args.metrics.write_text(
        json.dumps(metrics, indent=2) + "\n",
        encoding="utf-8",
    )
    theory = metrics["theory"]
    plot_comparison(
        args.figure,
        (rows),
        (theory["low_mass_Th"], theory["high_mass_Th"]),
    )
    print(
        "EXECUTION=PASS "
        f"DECISION={metrics['decision_status']}"
    )


if __name__ == "__main__":
    main()
