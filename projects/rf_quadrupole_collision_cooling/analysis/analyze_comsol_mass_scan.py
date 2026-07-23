"""Evaluate COMSOL RF+DC mass selection and compare frozen theory/SIMION evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from common.multipole.mass_response import evaluate_functional_contrast, write_response
from .analyze_simion_mass_scan import theory_masses


def read_response(path: Path) -> dict[float, dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {float(row["mass_Th"]): row for row in csv.DictReader(stream)}


def analyze(scan_config: Path, baseline_path: Path, mode_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scan = json.loads(scan_config.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected = [float(value) for value in mode["solver_screen"]["paired_source_masses_Th"]]
    response: list[dict[str, Any]] = []
    for case in scan["cases"]:
        summary = json.loads(Path(case["solver_summary"]).read_text(encoding="utf-8"))
        if summary["mode"] != "mass_filter_reference":
            raise ValueError("COMSOL case mode differs from the mass-filter contract")
        response.append({
            "mass_Th": float(summary["mass_Th"]),
            "particles": int(summary["particles"]),
            "transmitted": int(summary["hits"]),
            "transmission_fraction": float(summary["transmission"]),
        })
    response.sort(key=lambda row: float(row["mass_Th"]))
    if [float(row["mass_Th"]) for row in response] != expected:
        raise ValueError("COMSOL mass cases differ from solver_screen contract")
    expected_count = int(mode["solver_screen"]["particles_per_mass"])
    if any(int(row["particles"]) != expected_count for row in response):
        raise ValueError("COMSOL particles per mass differ from solver_screen contract")
    theory = theory_masses(baseline, mode)
    functional = evaluate_functional_contrast(
        response, theory["calibration_mass_Th"], mode["solver_screen"]["acceptance"]
    )
    metrics = {
        "schema_version": 1,
        "role": "rf_quadrupole_comsol_mass_filter_functional_metrics",
        **functional,
        "solver": "COMSOL 6.4",
        "theory": theory,
        "claim_limit": "COMSOL finite-geometry RF+DC functional response only; no mesh, resolving-power or accuracy qualification.",
    }
    return response, metrics


def compare(
    comsol: list[dict[str, Any]], simion_path: Path, l1_path: Path, passband: tuple[float, float]
) -> list[dict[str, Any]]:
    simion = read_response(simion_path)
    l1 = read_response(l1_path)
    rows: list[dict[str, Any]] = []
    for item in comsol:
        mass = float(item["mass_Th"])
        if mass not in simion or mass not in l1:
            raise ValueError(f"comparison evidence does not contain mass {mass:g} Th")
        comsol_value = float(item["transmission_fraction"])
        simion_value = float(simion[mass]["transmission_fraction"])
        l1_value = float(l1[mass]["transmission_fraction"])
        rows.append({
            "mass_Th": mass,
            "l0_class": "inside" if passband[0] <= mass <= passband[1] else "outside",
            "l1_transmission": l1_value,
            "simion_transmission": simion_value,
            "comsol_transmission": comsol_value,
            "comsol_minus_simion": comsol_value - simion_value,
        })
    return rows


def write_comparison(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(path: Path, rows: list[dict[str, Any]], passband: tuple[float, float]) -> None:
    masses = [float(row["mass_Th"]) for row in rows]
    with plt.rc_context({"font.size": 8, "axes.labelsize": 9, "legend.fontsize": 8}):
        figure, axis = plt.subplots(figsize=(160 / 25.4, 90 / 25.4), constrained_layout=True)
        axis.axvspan(*passband, color="#56B4E9", alpha=0.2, label="L0 ideal passband")
        styles = [
            ("l1_transmission", "L1 ideal finite length", "#009E73", "o"),
            ("simion_transmission", "SIMION finite geometry", "#0072B2", "s"),
            ("comsol_transmission", "COMSOL finite geometry", "#D55E00", "^"),
        ]
        for key, label, color, marker in styles:
            axis.plot(masses, [float(row[key]) for row in rows], marker=marker, markersize=4,
                      linewidth=1.2, color=color, label=label)
        axis.set(xlabel="Mass-to-charge ratio (Th)", ylabel="Transmission fraction", ylim=(-0.03, 1.03))
        axis.grid(axis="y", linewidth=0.5, alpha=0.3)
        axis.legend(frameon=False, loc="lower center")
        figure.savefig(path, format="png", dpi=240, facecolor="white")
        plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-config", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--simion-response", required=True, type=Path)
    parser.add_argument("--l1-response", required=True, type=Path)
    parser.add_argument("--response", required=True, type=Path)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--figure", required=True, type=Path)
    args = parser.parse_args()
    response, metrics = analyze(args.scan_config, args.baseline, args.mode)
    passband = (metrics["theory"]["low_mass_Th"], metrics["theory"]["high_mass_Th"])
    rows = compare(response, args.simion_response, args.l1_response, passband)
    write_response(args.response, response)
    write_comparison(args.comparison, rows)
    metrics["comparison"] = {
        "maximum_absolute_comsol_simion_transmission_difference": max(
            abs(float(row["comsol_minus_simion"])) for row in rows
        ),
        "interpretation": "diagnostic only; no cross-solver numerical agreement tolerance is frozen",
    }
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    plot(args.figure, rows, passband)
    if metrics["status"] != "PASS":
        raise SystemExit("COMSOL_MASS_FILTER_FUNCTIONAL=FAIL")
    print("COMSOL_MASS_FILTER_FUNCTIONAL=PASS")


if __name__ == "__main__":
    main()
