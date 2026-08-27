"""Audit one preregistered C4_J3 locked three-dimensional prediction family.

The caller supplies a frozen case declaration and three completed, governed
single-flight runs.  This module never selects a direction, trains a source
model, or starts SIMION.  In particular it refuses to inspect detector results
until a separately published C3_J3 PASS_CONTINUE evidence package is supplied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_focusability import (
    assign_detector_blind_cohorts,
)


_DIRECTIONS = ("improve", "zero", "worsen")


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_c3_pass(path: Path) -> dict[str, Any]:
    evidence = _load_object(path, label="C3 stage evidence")
    if evidence.get("stage_id") != "C3_J3" or evidence.get("conclusion") != "PASS_CONTINUE":
        raise ValueError("C4_J3 requires a published C3_J3 PASS_CONTINUE stage report")
    return evidence


def _run_metrics(path: Path, *, cohort_salt: str, expected_mother_count: int) -> dict[str, Any]:
    summary = _load_object(path / "summary.json", label="C4 run summary")
    manifest = _load_object(path / "run_manifest.json", label="C4 run manifest")
    if summary.get("status") != "success" or manifest.get("status") != "success":
        raise ValueError(f"C4 run is not a successful governed run: {path}")
    if int(summary.get("launched_particle_count", -1)) <= 0:
        raise ValueError("C4 run lacks a positive launched-particle count")
    population = summary.get("source_population")
    authority = summary.get("observed_cohort_authority")
    peak = summary.get("pulse_effective_peak")
    bootstrap = summary.get("full_pulse_eligible_bootstrap")
    transmission = summary.get("transmission")
    if not all(isinstance(item, Mapping) for item in (population, authority, peak, bootstrap, transmission)):
        raise ValueError("C4 run lacks source population, authority, peak, bootstrap, or transmission receipts")
    if int(population.get("candidate_population_count", -1)) != expected_mother_count:
        raise ValueError("C4 run mother-cohort denominator differs from its frozen case")
    if population.get("complete_pulse_eligible_population_simulated") is not True:
        raise ValueError("C4 run does not cover its complete pulse-eligible population")
    release = authority.get("source_release")
    if not isinstance(release, Mapping) or not isinstance(release.get("ordered_particle_ids"), list):
        raise ValueError("C4 run lacks its ordered source-release cohort")
    identifiers = [int(item) for item in release["ordered_particle_ids"]]
    if int(release.get("count", -1)) != len(identifiers):
        raise ValueError("C4 run source-release count differs from its ID list")
    roles = {item.particle_id: item.role for item in assign_detector_blind_cohorts(identifiers, salt=cohort_salt)}
    if not identifiers or any(roles[identifier] != "locked_test" for identifier in identifiers):
        raise ValueError("C4 run source-release cohort is not exclusively locked_test")
    required_peak = ("direct_fwhm_mass_Da", "mass_resolution", "tail_fraction_outside_3sigma", "significant_kde_modes")
    if any(not isinstance(peak.get(name), (int, float)) for name in required_peak):
        raise ValueError("C4 run peak receipt lacks canonical direct metrics")
    if not isinstance(transmission.get("detector_fraction_of_candidate_population"), (int, float)):
        raise ValueError("C4 run lacks full-mother detector transmission")
    if not isinstance(bootstrap.get("resolution_p2p5"), (int, float)) or not isinstance(bootstrap.get("resolution_p97p5"), (int, float)):
        raise ValueError("C4 run lacks bootstrap confidence bounds")
    return {
        "run_directory": str(path.resolve()),
        "source_release_ids": identifiers,
        "pulse_effective_time_us": float(summary.get("pulse_effective_time_us")),
        "census": summary.get("census"),
        "fwhm_mass_da": float(peak["direct_fwhm_mass_Da"]),
        "resolution": float(peak["mass_resolution"]),
        "tail_fraction": float(peak["tail_fraction_outside_3sigma"]),
        "mode_count": int(peak["significant_kde_modes"]),
        "detector_fraction_of_mother": float(transmission["detector_fraction_of_candidate_population"]),
        "bootstrap_resolution_95pct": [float(bootstrap["resolution_p2p5"]), float(bootstrap["resolution_p97p5"])],
    }


def analyze_c4_locked_prediction(*, c3_stage_report: Path, case_path: Path) -> dict[str, Any]:
    """Evaluate one already-frozen improve/zero/worsen C4_J3 case."""

    c3 = _require_c3_pass(c3_stage_report)
    case = _load_object(case_path, label="C4 locked-case declaration")
    required = {"case_id", "source_condition_id", "architecture", "cohort_salt", "mother_cohort_count", "minimum_detector_count", "prediction_score", "runs"}
    if set(case) != required:
        raise ValueError("C4 locked-case declaration fields differ from the contract")
    scores, run_paths = case["prediction_score"], case["runs"]
    if set(scores) != set(_DIRECTIONS) or set(run_paths) != set(_DIRECTIONS):
        raise ValueError("C4 case requires exactly improve, zero, and worsen predictions and runs")
    if not all(isinstance(scores[name], (int, float)) for name in _DIRECTIONS):
        raise ValueError("C4 prediction scores must be numeric and frozen before detector readout")
    if not (float(scores["improve"]) < float(scores["zero"]) < float(scores["worsen"])):
        raise ValueError("C4 prediction score must preregister improve < zero < worsen")
    mother_count = int(case["mother_cohort_count"])
    if mother_count < 1 or int(case["minimum_detector_count"]) < 3:
        raise ValueError("C4 cohort counts are invalid")
    observations = {
        direction: _run_metrics(Path(str(run_paths[direction])), cohort_salt=str(case["cohort_salt"]), expected_mother_count=mother_count)
        for direction in _DIRECTIONS
    }
    common_ids = observations["improve"]["source_release_ids"]
    same_ids = all(item["source_release_ids"] == common_ids for item in observations.values())
    same_pulse = len({item["pulse_effective_time_us"] for item in observations.values()}) == 1
    detector_counts = {name: int(item["census"].get("detector_crossing", -1)) if isinstance(item["census"], Mapping) else -1 for name, item in observations.items()}
    observed_order = tuple(sorted(_DIRECTIONS, key=lambda name: observations[name]["fwhm_mass_da"]))
    no_loss_trade = observations["improve"]["detector_fraction_of_mother"] >= observations["zero"]["detector_fraction_of_mother"]
    gates = {
        "c3_pass_prerequisite": True,
        "same_locked_source_ids": same_ids,
        "same_effective_pulse": same_pulse,
        "minimum_detector_count": min(detector_counts.values()) >= int(case["minimum_detector_count"]),
        "predicted_fwhm_order": observed_order == _DIRECTIONS,
        "improvement_not_bought_by_mother_transmission_loss": no_loss_trade,
    }
    conclusion = "PASS_CONTINUE" if all(gates.values()) else "INCONCLUSIVE_REVISE"
    return {
        "stage_id": "C4_J3",
        "conclusion": conclusion,
        "claim_limit": "One frozen C3_J3 direction family on a locked three-dimensional cohort; no J2, architecture-superiority, multi-source, multi-mass, Candidate, or Formal claim.",
        "inputs": {"c3_stage_report": str(Path(c3_stage_report).resolve()), "c3_conclusion": c3["conclusion"], "case": str(Path(case_path).resolve())},
        "metrics": {"case_id": case["case_id"], "source_condition_id": case["source_condition_id"], "architecture": case["architecture"], "prediction_score": scores, "observations": observations, "detector_counts": detector_counts, "observed_fwhm_order": list(observed_order), "gates": gates},
        "claims_supported": ["The preregistered C3_J3 improve/zero/worsen prediction is evaluated only after C3 PASS and only on a detector-blind locked cohort."],
        "claims_prohibited": ["J2 recovery, general three-zone superiority, source-weighted superiority, multi-source, multi-mass, Candidate, Formal, or JASMS-readiness claims."],
        "failures": [name for name, passed in gates.items() if not passed],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c3-stage-report", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze_c4_locked_prediction(c3_stage_report=args.c3_stage_report, case_path=args.case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
