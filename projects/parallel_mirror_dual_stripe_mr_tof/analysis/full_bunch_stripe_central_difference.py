"""Validate and reduce four full-bunch Stripe voltage perturbation flights."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.stripe_return_sensitivity import (
    _run,
    _same_parent_inputs,
)


STATE_NAMES = ("s1_minus", "s1_plus", "s2_minus", "s2_plus")
FROZEN_INPUT_KEYS = (
    "geometry_run_manifest",
    "mirror_run_manifest",
    "stripe_run_manifest",
    "accelerator_run_manifest",
    "local_workbench_run_manifest",
    "bunch_source_run_manifest",
)
METRICS = (
    "detector_hit_count",
    "electrode_collision_count",
    "detection_rate",
    "target_k_fraction",
    "detector_tof_median_us",
    "detector_tof_fwhm_us",
    "mass_resolution_t_over_2fwhm",
    "target_k_handoff_tof_fwhm_us",
    "effective_axial_width_W_median_mm",
    "target_k_phase_y_median_mm",
    "target_k_phase_y_rms_mm",
)


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def _metrics(summary: dict[str, Any], label: str) -> dict[str, float]:
    cohort = summary.get("cohort_analysis")
    if not isinstance(cohort, dict):
        raise CandidateContractError(f"{label} lacks cohort analysis")
    if not cohort.get("event_integrity_passed") or cohort.get("integrity_errors"):
        raise CandidateContractError(f"{label} failed event integrity")
    if cohort.get("expected_particle_count") != 100 or cohort.get("particle_terminal_count") != 100:
        raise CandidateContractError(f"{label} is not one complete N=100 cohort")
    if cohort.get("all_losses_retained") is not True:
        raise CandidateContractError(f"{label} filtered losses")
    residuals = cohort.get("target_k_phase_y_residuals_mm")
    if not isinstance(residuals, list) or len(residuals) != 100:
        raise CandidateContractError(f"{label} lacks 100 target-K phase residuals")
    y_values = [_finite(value, f"{label} target-K y residual") for value in residuals]
    values = {
        name: _finite(cohort.get(name), f"{label} {name}")
        for name in METRICS[:-2]
    }
    values["target_k_phase_y_median_mm"] = float(median(y_values))
    values["target_k_phase_y_rms_mm"] = math.sqrt(sum(value * value for value in y_values) / len(y_values))
    return values


def analyze_documents(states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if set(states) != set(STATE_NAMES):
        raise CandidateContractError("exactly four named Stripe perturbation states are required")
    reference = states["s1_minus"]
    reference_config = reference["config"]
    reference_parameters = reference_config.get("parameters", {})
    reference_inputs = reference_config.get("inputs", {})
    if not isinstance(reference_inputs, dict):
        raise CandidateContractError("reference run lacks frozen inputs")
    reference_cohort = reference_parameters.get("source_cohort")
    reference_prisms = (
        reference_parameters.get("prism_1_voltage_v"),
        reference_parameters.get("prism_2_voltage_v"),
    )
    voltage_states: dict[str, tuple[float, float]] = {}
    metric_states: dict[str, dict[str, float]] = {}
    run_ids: dict[str, str] = {}
    for label in STATE_NAMES:
        document = states[label]
        config = document["config"]
        summary = document["summary"]
        if config.get("project") != "parallel_mirror_dual_stripe_mr_tof" or config.get("mode") != "finite_3d_two_prism_voltage_trial":
            raise CandidateContractError(f"{label} has the wrong project or mode")
        parameters = config.get("parameters", {})
        inputs = config.get("inputs", {})
        _same_parent_inputs(reference_inputs, inputs, label)
        if any(inputs.get(key) != reference_inputs.get(key) for key in FROZEN_INPUT_KEYS):
            raise CandidateContractError(f"{label} changes a frozen parent input")
        if parameters.get("source_cohort") != reference_cohort or parameters.get("source_particle_count") != 100:
            raise CandidateContractError(f"{label} changes the frozen N=100 source")
        if parameters.get("source_selection") is not None:
            raise CandidateContractError(f"{label} is a selected subset rather than the full cohort")
        if parameters.get("trajectory_profile") != reference_parameters.get("trajectory_profile"):
            raise CandidateContractError(f"{label} changes trajectory numerics")
        if parameters.get("accelerator_pulse", {}).get("mode") != "static":
            raise CandidateContractError(f"{label} changes the static accelerator contract")
        prisms = (parameters.get("prism_1_voltage_v"), parameters.get("prism_2_voltage_v"))
        if prisms != reference_prisms:
            raise CandidateContractError(f"{label} changes P1/P2")
        stripes = parameters.get("stripe_biases_v")
        if not isinstance(stripes, list) or len(stripes) != 2:
            raise CandidateContractError(f"{label} lacks two Stripe voltages")
        voltage_states[label] = (_finite(stripes[0], f"{label} S1"), _finite(stripes[1], f"{label} S2"))
        metric_states[label] = _metrics(summary, label)
        run_ids[label] = str(config.get("run_id"))

    s1m, s1p, s2m, s2p = (voltage_states[name] for name in STATE_NAMES)
    if not (_close(s1m[1], s1p[1]) and _close(s2m[0], s2p[0])):
        raise CandidateContractError("perturbations are not axis aligned")
    center_s1 = (s1m[0] + s1p[0]) / 2.0
    center_s2 = (s2m[1] + s2p[1]) / 2.0
    if not (_close(s1m[1], center_s2) and _close(s2m[0], center_s1)):
        raise CandidateContractError("the four perturbations do not share one center")
    delta_s1 = (s1p[0] - s1m[0]) / 2.0
    delta_s2 = (s2p[1] - s2m[1]) / 2.0
    if delta_s1 <= 0.0 or delta_s2 <= 0.0 or not _close(delta_s1, delta_s2):
        raise CandidateContractError("central-difference steps must be equal and positive")
    delta = (delta_s1 + delta_s2) / 2.0
    derivatives = {
        name: [
            (metric_states["s1_plus"][name] - metric_states["s1_minus"][name]) / (2.0 * delta),
            (metric_states["s2_plus"][name] - metric_states["s2_minus"][name]) / (2.0 * delta),
        ]
        for name in METRICS
    }
    fwhm_gradient = derivatives["detector_tof_fwhm_us"]
    norm = math.hypot(*fwhm_gradient)
    descent = None if norm == 0.0 else [-fwhm_gradient[0] / norm, -fwhm_gradient[1] / norm]
    return {
        "schema_version": 1,
        "role": "mrtof_full_bunch_stripe_central_difference",
        "status": "complete",
        "qualification": "candidate_local_sensitivity__not_an_operating_point",
        "frozen_contract": {
            "particle_count": 100,
            "source_cohort": reference_cohort,
            "prism_voltages_v": list(reference_prisms),
            "trajectory_profile": reference_parameters.get("trajectory_profile"),
            "input_manifests": {key: reference_inputs.get(key) for key in FROZEN_INPUT_KEYS},
        },
        "center_stripe_biases_v": [center_s1, center_s2],
        "central_difference_step_v": delta,
        "member_run_ids": run_ids,
        "states": {
            name: {"stripe_biases_v": list(voltage_states[name]), "metrics": metric_states[name]}
            for name in STATE_NAMES
        },
        "central_difference_derivatives_per_v": derivatives,
        "local_fwhm_descent_unit_direction_dS1_dS2": descent,
        "interpretation": {
            "continuous_metrics_are_local_derivatives_only": True,
            "count_derivatives_are_discrete_diagnostics_only": True,
            "full_bunch_predictive_qualification": "one_symmetric_step_only__new_point_requires_simion_validation",
        },
    }


def analyze_runs(run_paths: dict[str, Path], output: Path) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = {}
    for label in STATE_NAMES:
        root, _manifest, config, summary = _run(run_paths[label], label)
        states[label] = {"root": str(root), "config": config, "summary": summary}
    result = analyze_documents(states)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in STATE_NAMES:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in STATE_NAMES}
    result = analyze_runs(paths, args.output)
    print(
        "MRTOF_FULL_BUNCH_STRIPE_CENTRAL_DIFFERENCE=PASS "
        f"STEP_V={result['central_difference_step_v']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
