"""Evaluate the intrinsic COMSOL RF+DC mass-selection response."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.multipole.mass_response import evaluate_functional_contrast, write_response


def analyze(
    scan_config: Path,
    mode_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scan = json.loads(scan_config.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    scan_spec = mode["mass_scan_spec"]
    expected = [float(value) for value in scan_spec["paired_source_masses_Th"]]
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
        raise ValueError("COMSOL mass cases differ from mass_scan_spec")
    particle_counts = {int(row["particles"]) for row in response}
    if len(particle_counts) != 1 or next(iter(particle_counts)) <= 0:
        raise ValueError("COMSOL particles per mass are empty or inconsistent")
    calibration_mass = float(scan_spec["calibration_mass_Th"])
    functional = evaluate_functional_contrast(
        response,
        calibration_mass,
        scan_spec["acceptance"],
    )
    metrics = {
        "schema_version": 1,
        "role": "rf_quadrupole_comsol_mass_filter_functional_metrics",
        **functional,
        "solver": "COMSOL 6.4",
        "calibration_mass_Th": calibration_mass,
        "particles_per_mass": next(iter(particle_counts)),
        "claim_limit": mode["comsol_screen"]["claim_limit"],
    }
    return response, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-config", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--response", required=True, type=Path)
    parser.add_argument("--metrics", required=True, type=Path)
    args = parser.parse_args()
    response, metrics = analyze(args.scan_config, args.mode)
    write_response(args.response, response)
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    if metrics["status"] != "PASS":
        raise SystemExit("COMSOL_MASS_FILTER_FUNCTIONAL=FAIL")
    print("COMSOL_MASS_FILTER_FUNCTIONAL=PASS")


if __name__ == "__main__":
    main()
