"""Analyze one paired multi-mass SIMION quadrupole scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.multipole.mass_response import (
    aggregate_response,
    evaluate_functional_contrast,
    export_response_figure,
    load_ion_masses,
    load_terminal_statuses,
    write_response,
)

from . import quadrupole_l0 as l0


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "baseline.json"
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"


def theory_masses(baseline: dict[str, Any], mode: dict[str, Any]) -> dict[str, float]:
    """Return ideal passband and calibration masses for the current voltage contract."""
    reference = l0.validate_mass_filter_reference(baseline, mode)
    q_tune = float(reference["q_at_tune_mass"])
    tune_mass = float(mode["rf"]["tune_mass_Th"])
    passband = reference["ideal_scanline"]
    return {
        "low_mass_Th": tune_mass * q_tune / float(passband["q_out"]),
        "high_mass_Th": tune_mass * q_tune / float(passband["q_in"]),
        "calibration_mass_Th": l0.mass_to_charge_th(
            float(passband["q_cal"]),
            float(mode["rf"]["amplitude_V_zero_to_peak_per_group"]),
            float(mode["rf"]["effective_radius_mm"]),
            float(mode["rf"]["frequency_Hz"]),
        ),
    }


def evaluate(
    response: list[dict[str, Any]], baseline: dict[str, Any], mode: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate the frozen SIMION functional contrast checks."""
    theory = theory_masses(baseline, mode)
    acceptance = mode["solver_screen"]["acceptance"]
    functional = evaluate_functional_contrast(response, theory["calibration_mass_Th"], acceptance)
    return {
        "schema_version": 1,
        "role": "rf_quadrupole_simion_mass_filter_functional_metrics",
        **functional,
        "solver": "SIMION 2020",
        "theory": theory,
        "claim_limit": mode["solver_screen"]["claim_limit"],
    }


def analyze(
    state_path: Path,
    particle_path: Path,
    baseline_path: Path,
    mode_path: Path,
    response_path: Path,
    metrics_path: Path,
    figure_path: Path,
) -> dict[str, Any]:
    """Analyze, validate and export one SIMION paired mass scan."""
    masses = load_ion_masses(particle_path)
    statuses = load_terminal_statuses(state_path)
    response = aggregate_response(masses, statuses)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    expected_masses = [float(value) for value in mode["solver_screen"]["paired_source_masses_Th"]]
    if [float(row["mass_Th"]) for row in response] != expected_masses:
        raise ValueError("observed mass groups differ from solver_screen contract")
    if any(int(row["particles"]) != int(mode["solver_screen"]["particles_per_mass"]) for row in response):
        raise ValueError("observed particles per mass differ from solver_screen contract")
    metrics = evaluate(response, baseline, mode)
    write_response(response_path, response)
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    export_response_figure(
        figure_path,
        response,
        (float(metrics["theory"]["low_mass_Th"]), float(metrics["theory"]["high_mass_Th"])),
        "SIMION finite geometry",
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--response", required=True, type=Path)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--figure", required=True, type=Path)
    args = parser.parse_args()
    metrics = analyze(
        args.state, args.particles, args.baseline, args.mode, args.response, args.metrics, args.figure
    )
    if metrics["status"] != "PASS":
        raise SystemExit("SIMION_MASS_FILTER_FUNCTIONAL=FAIL")
    print("SIMION_MASS_FILTER_FUNCTIONAL=PASS")


if __name__ == "__main__":
    main()
