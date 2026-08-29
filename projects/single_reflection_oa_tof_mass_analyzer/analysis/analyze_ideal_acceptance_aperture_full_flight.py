"""Compare complete-cohort 300 mm aperture full-flight runs without postselection.

The pre-pulse screen establishes source-side collection only.  This companion
reader consumes the already published full-flight receipts and reports the
separate downstream observables requested for the aperture experiment.  Every
arm keeps its own complete mother-cohort denominator and its own detector-hit
peak; paired particle identities are deliberately not used to shrink either
population.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import numpy as np


CAMPAIGN_ID = "ideal_acceptance_300mm_aperture_height_full_flight_n5000"
CAMPAIGN_IDS = frozenset({
    CAMPAIGN_ID,
    "ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_full_flight_n5000",
})
SUMMARY_ROLE = "rf_oatof_simion_single_flight_summary"
PARENT_SUMMARY_ROLE = "integration_family_source_closure_summary"
CHECKPOINT_COLUMNS = {
    "particle_id", "event", "z_mm", "vz_mm_per_us", "pulse_eligibility",
}
RESOLUTION_TIME_BASIS = "detector_time_minus_pulse_effective_time"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _manifest_sha(manifest: dict[str, Any], path: Path) -> str | None:
    for item in manifest.get("outputs", []):
        if isinstance(item, dict) and Path(str(item.get("path", ""))).name == path.name:
            value = item.get("sha256")
            return value if isinstance(value, str) else None
    return None


def _expected_row_metadata(row: dict[str, Any]) -> tuple[str, str, float, str]:
    overrides = row.get("overrides")
    if not isinstance(overrides, dict):
        raise ValueError("campaign row lacks overrides")
    layout = overrides.get("single_flight_layout_profile_id")
    connection = overrides.get("connection_profile_id")
    if not isinstance(layout, str) or not isinstance(connection, str):
        raise ValueError("campaign row lacks layout or connection identity")
    if "square" in layout:
        realization = "square"
    elif "cylindrical" in layout:
        realization = "cylindrical"
    else:
        raise ValueError("campaign row layout is neither square nor cylindrical")
    match = re.search(r"_aperture_100x(\d+)_", connection)
    height_mm = float(match.group(1)) / 100.0 if match else 0.9
    return layout, realization, height_mm, connection


def _input_path(manifest: dict[str, Any], key: str, parent_run_id: str) -> Path:
    """Resolve one parent-manifest input and verify its recorded checksum."""
    record = manifest.get("inputs", {}).get(key)
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError(f"{parent_run_id}: parent manifest lacks {key} input")
    path = Path(record["path"])
    expected_sha = record.get("sha256")
    if not path.is_file() or not isinstance(expected_sha, str) or _sha256(path) != expected_sha:
        raise ValueError(f"{parent_run_id}: parent manifest {key} input differs")
    return path


def _resolve_single_flight_run(parent_run_dir: Path, row: dict[str, Any], campaign: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Follow the parent receipt to its unique, manifest-bound SIMION child run."""
    parent_run_id = row.get("run_id")
    experiment_id = row.get("experiment_id")
    if not isinstance(parent_run_id, str) or not isinstance(experiment_id, str):
        raise ValueError("campaign row lacks run or experiment identity")
    if parent_run_dir.name != parent_run_id:
        raise ValueError("parent run directory identity differs from campaign row")
    parent_manifest = _load_json(parent_run_dir / "run_manifest.json", "parent run manifest")
    parent_summary_path = parent_run_dir / "summary.json"
    parent_summary = _load_json(parent_summary_path, "parent run summary")
    if parent_manifest.get("status") != "success" or parent_summary.get("role") != PARENT_SUMMARY_ROLE or parent_summary.get("status") != "success":
        raise ValueError(f"{parent_run_id}: parent run is not a successful integration closure")
    if _manifest_sha(parent_manifest, parent_summary_path) != _sha256(parent_summary_path):
        raise ValueError(f"{parent_run_id}: parent summary manifest SHA differs")
    _, _, _, connection = _expected_row_metadata(row)
    if (parent_summary.get("campaign_id") != campaign.get("campaign_id") or
            parent_summary.get("experiment_id") != experiment_id or
            parent_summary.get("connection_profile_id") != connection):
        raise ValueError(f"{parent_run_id}: parent campaign, experiment, or connection identity differs")
    child_manifest_path = _input_path(parent_manifest, "single_flight_transport_manifest", parent_run_id)
    child_manifest = _load_json(child_manifest_path, "single-flight child manifest")
    child_run_dir = child_manifest_path.parent
    child_run_id = child_manifest.get("run_id")
    if (not isinstance(child_run_id, str) or child_run_dir.name != child_run_id or
            child_manifest.get("role") != "simulation_run_manifest" or child_manifest.get("status") != "success"):
        raise ValueError(f"{parent_run_id}: child manifest is not one successful SIMION run")
    return child_run_dir, {"parent_run_id": parent_run_id, "parent_summary_path": str(parent_summary_path.resolve()), "single_flight_run_id": child_run_id}


def _read_pre_pulse_states(path: Path) -> tuple[np.ndarray, np.ndarray, set[int]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not CHECKPOINT_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("checkpoint table lacks required full-flight fields")
        rows = [row for row in reader if row.get("event") == "pre_pulse_state"]
    if not rows:
        raise ValueError("checkpoint table lacks pre_pulse_state rows")
    ids = [int(row["particle_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("checkpoint table repeats particle IDs at pre_pulse_state")
    z_mm = np.asarray([float(row["z_mm"]) for row in rows], dtype=float)
    vz_mm_per_us = np.asarray([float(row["vz_mm_per_us"]) for row in rows], dtype=float)
    if not (np.all(np.isfinite(z_mm)) and np.all(np.isfinite(vz_mm_per_us))):
        raise ValueError("checkpoint table has non-finite pre-pulse phase-space values")
    return z_mm, vz_mm_per_us, set(ids)


def _polynomial_metrics(
    z_mm: np.ndarray, vz_mm_per_us: np.ndarray, degree: int
) -> dict[str, Any]:
    coefficients = np.polyfit(z_mm, vz_mm_per_us, degree)
    residual = vz_mm_per_us - np.polyval(coefficients, z_mm)
    result: dict[str, Any] = {
        "degree": degree,
        "coefficients_descending_power": [float(value) for value in coefficients],
        "coefficient_units_descending_power": [
            "mm_per_us_per_mm" if power == 1 else (
                "mm_per_us" if power == 0 else f"mm_per_us_per_mm{power}"
            )
            for power in range(degree, -1, -1)
        ],
        "residual_sample_sigma_mm_per_us": float(np.std(residual, ddof=1)),
        "residual_rms_mm_per_us": float(np.sqrt(np.mean(residual**2))),
        "residual_max_abs_mm_per_us": float(np.max(np.abs(residual))),
    }
    result["intercept_mm_per_us"] = float(coefficients[-1])
    result["k_per_us"] = float(coefficients[-2])
    if degree >= 2:
        result["quadratic_coefficient_per_mm_us"] = float(coefficients[-3])
    if degree >= 3:
        result["cubic_coefficient_per_mm2_us"] = float(coefficients[-4])
    return result


def _affine_metrics(z_mm: np.ndarray, vz_mm_per_us: np.ndarray) -> dict[str, Any]:
    if z_mm.size < 2 or np.ptp(z_mm) == 0.0:
        raise ValueError("pre-pulse states do not identify an affine z-vz relation")
    design = np.column_stack((np.ones(z_mm.size), z_mm))
    intercept, slope = np.linalg.lstsq(design, vz_mm_per_us, rcond=None)[0]
    residual = vz_mm_per_us - (intercept + slope * z_mm)
    centered = vz_mm_per_us - np.mean(vz_mm_per_us)
    total = float(np.sum(centered**2))
    residual_sum = float(np.sum(residual**2))
    linear = _polynomial_metrics(z_mm, vz_mm_per_us, 1)
    quadratic = _polynomial_metrics(z_mm, vz_mm_per_us, 2) if z_mm.size >= 3 else None
    cubic = _polynomial_metrics(z_mm, vz_mm_per_us, 3) if z_mm.size >= 4 else None
    random_model = cubic or quadratic or linear
    return {
        "intercept_mm_per_us": float(intercept),
        "slope_per_us": float(slope),
        "k_per_us": float(slope),
        "r_squared": 1.0 if total == 0.0 and residual_sum == 0.0 else float(1.0 - residual_sum / total),
        "residual_rms_mm_per_us": float(np.sqrt(np.mean(residual**2))),
        "residual_max_abs_mm_per_us": float(np.max(np.abs(residual))),
        "linear_residual_sample_sigma_mm_per_us": linear["residual_sample_sigma_mm_per_us"],
        "random_residual_model_degree": random_model["degree"],
        "random_residual_sample_sigma_mm_per_us": random_model["residual_sample_sigma_mm_per_us"],
        "random_residual_rms_mm_per_us": random_model["residual_rms_mm_per_us"],
        "polynomial_diagnostics": {
            "linear": linear,
            "quadratic": quadratic,
            "cubic": cubic,
            "higher_order_residual_sigma_reduction_vs_linear_mm_per_us": {
                "quadratic": None if quadratic is None else linear["residual_sample_sigma_mm_per_us"] - quadratic["residual_sample_sigma_mm_per_us"],
                "cubic": None if cubic is None else linear["residual_sample_sigma_mm_per_us"] - cubic["residual_sample_sigma_mm_per_us"],
            },
        },
    }


def _width_metrics(z_mm: np.ndarray, threshold_mm: float) -> dict[str, Any]:
    percentile = np.percentile(z_mm, [0, 1, 5, 50, 95, 99, 100])
    full_range = float(percentile[6] - percentile[0])
    p01_p99_range = float(percentile[5] - percentile[1])
    return {
        "coordinate": "z_mm",
        "percentiles_mm": dict(zip(("p00", "p01", "p05", "p50", "p95", "p99", "p100"), map(float, percentile))),
        "full_range_mm": full_range,
        "p01_p99_range_mm": p01_p99_range,
        "exceeds_4mm_full_range": full_range > threshold_mm,
        "exceeds_4mm_p01_p99_range": p01_p99_range > threshold_mm,
        "threshold_mm": threshold_mm,
    }


def _full_cohort_losses(census: dict[str, Any], mother_count: int) -> dict[str, int]:
    """Return checkpoint-interval losses, not a terminal loss taxonomy."""
    required = ("launched", "accelerator_grid1_forward", "accelerator_intermediate2_forward", "local_accelerator_exit", "detector_crossing")
    counts = {name: int(census[name]) for name in required}
    if counts["launched"] != mother_count:
        raise ValueError("run does not preserve the full N=5000 mother cohort")
    ordered = [counts[name] for name in required]
    if any(value < 0 for value in ordered) or any(right > left for left, right in zip(ordered, ordered[1:])):
        raise ValueError("full-flight checkpoint census is not monotonic")
    return {
        "before_grid1": counts["launched"] - counts["accelerator_grid1_forward"],
        "between_grid1_and_grid2": counts["accelerator_grid1_forward"] - counts["accelerator_intermediate2_forward"],
        "between_grid2_and_exit": counts["accelerator_intermediate2_forward"] - counts["local_accelerator_exit"],
        "after_accelerator_before_detector": counts["local_accelerator_exit"] - counts["detector_crossing"],
    }


def _terminal_taxonomy(
    summary: dict[str, Any], census: dict[str, Any], mother_ids: set[int],
) -> dict[str, Any]:
    """Verify one exhaustive, per-instance terminal outcome for every mother ID."""

    taxonomy = summary.get("terminal_taxonomy")
    if not isinstance(taxonomy, dict):
        raise ValueError("full-flight summary lacks terminal taxonomy")
    mother_count = len(mother_ids)
    if (
        taxonomy.get("role") != "rf_oatof_full_flight_terminal_taxonomy"
        or taxonomy.get("classification_is_mutually_exclusive_and_exhaustive") is not True
        or taxonomy.get("mother_cohort_count") != mother_count
        or taxonomy.get("terminal_outcome_count") != mother_count
    ):
        raise ValueError("full-flight terminal taxonomy is not exhaustive and exclusive")
    category_counts = taxonomy.get("category_counts")
    outcomes = taxonomy.get("particle_outcomes")
    if not isinstance(category_counts, dict) or not isinstance(outcomes, list):
        raise ValueError("full-flight terminal taxonomy is incomplete")
    if len(outcomes) != mother_count:
        raise ValueError("full-flight terminal taxonomy outcome count differs")
    ids: set[int] = set()
    observed_counts: dict[str, int] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise ValueError("full-flight terminal taxonomy outcome is invalid")
        particle_id, category = outcome.get("particle_id"), outcome.get("category")
        if not isinstance(particle_id, int) or particle_id < 1 or particle_id in ids:
            raise ValueError("full-flight terminal taxonomy particle identities differ")
        if not isinstance(category, str):
            raise ValueError("full-flight terminal taxonomy category is invalid")
        if category == "detector_crossing":
            if outcome.get("terminal_event") != "detector_crossing":
                raise ValueError("detector terminal taxonomy event differs")
        else:
            match = re.fullmatch(r"non_detector_splat_instance_([1-9][0-9]*)", category)
            if match is None or outcome.get("terminal_event") != "non_detector_splat" or outcome.get("instance_id") != int(match.group(1)):
                raise ValueError("non-detector terminal taxonomy instance differs")
        ids.add(particle_id)
        observed_counts[category] = observed_counts.get(category, 0) + 1
    if ids != mother_ids:
        raise ValueError("full-flight terminal taxonomy does not close the mother cohort")
    if (
        any(not isinstance(count, int) or count < 0 for count in category_counts.values())
        or category_counts != observed_counts
        or sum(category_counts.values()) != mother_count
        or int(category_counts.get("detector_crossing", 0)) != int(census["detector_crossing"])
    ):
        raise ValueError("full-flight terminal taxonomy counts differ")
    return taxonomy


def _peak_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    peak = summary.get("pulse_effective_peak")
    bootstrap = summary.get("full_pulse_eligible_bootstrap")
    if peak is None:
        return {"status": "NOT_COMPUTED", "reason": (bootstrap or {}).get("reason", "no_detector_peak")}
    if not isinstance(peak, dict) or not isinstance(bootstrap, dict):
        raise ValueError("full-flight summary lacks peak or bootstrap contract")
    keys = ("mean_tof_us", "direct_fwhm_tof_ns", "mass_resolution", "direct_fwhm_mass_Da", "significant_kde_modes", "tail_fraction_outside_3sigma", "tof_skewness", "tof_excess_kurtosis")
    if any(key not in peak for key in keys):
        raise ValueError("full-flight peak contract is incomplete")
    return {"status": "COMPUTED", "all_detector_hits_only": True, "metrics": {key: peak[key] for key in keys}, "bootstrap": bootstrap}


def _analyze_arm(parent_run_dir: Path, row: dict[str, Any], campaign: dict[str, Any], candidate_sha256: str, threshold_mm: float) -> dict[str, Any]:
    run_dir, parent_evidence = _resolve_single_flight_run(parent_run_dir, row, campaign)
    run_id = parent_evidence["single_flight_run_id"]
    manifest = _load_json(run_dir / "run_manifest.json", "single-flight run manifest")
    summary_path = run_dir / "summary.json"
    checkpoints_path = run_dir / "results" / "single_flight_particle_checkpoints.csv"
    initial_path = run_dir / "inputs" / "single_flight_initial_global_state.csv"
    summary = _load_json(summary_path, "run summary")
    if summary.get("role") != SUMMARY_ROLE or summary.get("status") != "success":
        raise ValueError(f"{run_id}: summary is not a successful full flight")
    if summary.get("resolution_time_basis") != RESOLUTION_TIME_BASIS:
        raise ValueError(f"{run_id}: resolution clock is not pulse-relative")
    if _manifest_sha(manifest, summary_path) != _sha256(summary_path) or _manifest_sha(manifest, checkpoints_path) != _sha256(checkpoints_path):
        raise ValueError(f"{run_id}: manifest output SHA differs")
    initial = np.genfromtxt(initial_path, delimiter=",", names=True, dtype=None, encoding="utf-8-sig")
    if initial.size != 5000 or "particle_id" not in initial.dtype.names:
        raise ValueError(f"{run_id}: frozen mother cohort is incomplete")
    mother_ids = {int(value) for value in np.atleast_1d(initial["particle_id"])}
    if len(mother_ids) != 5000:
        raise ValueError(f"{run_id}: frozen mother cohort identities differ")
    candidate = run_dir / "inputs" / "three_zone_t5_candidate_resolved.json"
    if _sha256(candidate) != candidate_sha256:
        raise ValueError(f"{run_id}: frozen Candidate identity differs")
    layout_profile_id, realization, height_mm, connection = _expected_row_metadata(row)
    geometry = _load_json(run_dir / "inputs" / "oatof_resolved_geometry.json", "resolved geometry")
    derivation = geometry.get("single_flight_layout_derivation", {})
    if derivation.get("layout_profile_id") != layout_profile_id:
        raise ValueError(f"{run_id}: geometry layout profile differs from campaign row")
    if geometry.get("geometry_derivation", {}).get("accelerator", {}).get("realization_id") != f"{realization}_3d":
        raise ValueError(f"{run_id}: geometry realization differs from campaign row")
    z_mm, vz_mm_per_us, observed_ids = _read_pre_pulse_states(checkpoints_path)
    census = summary.get("census")
    if not isinstance(census, dict):
        raise ValueError(f"{run_id}: summary lacks census")
    interval_losses = _full_cohort_losses(census, 5000)
    terminal_taxonomy = _terminal_taxonomy(summary, census, mother_ids)
    return {
        **parent_evidence,
        "experiment_id": row.get("experiment_id"),
        "realization": realization,
        "aperture_height_mm": height_mm,
        "layout_profile_id": layout_profile_id,
        "connection_profile_id": connection,
        "checkpoint_table": {"path": str(checkpoints_path.resolve()), "sha256": _sha256(checkpoints_path)},
        "pre_pulse_observed_count": len(observed_ids),
        "axial_z_width": _width_metrics(z_mm, threshold_mm),
        "z_vz_affine": _affine_metrics(z_mm, vz_mm_per_us),
        "mother_cohort": {
            "count": 5000,
            "detector_hit_count": int(census["detector_crossing"]),
            "detector_fraction": float(int(census["detector_crossing"]) / 5000),
            "checkpoint_census": {key: int(value) for key, value in census.items()},
            "checkpoint_interval_loss_counts": interval_losses,
            "terminal_taxonomy": terminal_taxonomy,
        },
        "detector_peak": _peak_metrics(summary),
    }


def analyze_campaign(*, campaign_path: Path, runs_root: Path, threshold_mm: float = 4.0) -> dict[str, Any]:
    """Return the eight-arm full-flight comparison or fail on identity drift."""
    campaign = _load_json(campaign_path, "campaign")
    campaign_id = campaign.get("campaign_id")
    if campaign_id not in CAMPAIGN_IDS:
        raise ValueError("analysis only accepts a registered 300 mm aperture full-flight campaign")
    rows = campaign.get("experiments", {}).get("rows")
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("campaign must contain exactly eight arms")
    candidate_sha256 = campaign.get("experiments", {}).get("shared", {}).get("single_flight_three_zone_candidate", {}).get("sha256")
    if not isinstance(candidate_sha256, str):
        raise ValueError("campaign lacks frozen three-zone Candidate identity")
    arms = [_analyze_arm(runs_root / row["run_id"], row, campaign, candidate_sha256, threshold_mm) for row in rows]
    return {
        "schema_version": 1,
        "role": "oatof_ideal_acceptance_300mm_aperture_full_flight_comparison",
        "qualification": "REAL_FIELD_EXPLORATORY_ONLY",
        "resolution_time_basis": RESOLUTION_TIME_BASIS,
        "campaign": {"id": campaign_id, "path": str(campaign_path.resolve()), "sha256": _sha256(campaign_path)},
        "candidate_sha256": candidate_sha256,
        "axial_width_threshold_mm": threshold_mm,
        "full_hit_metric_policy": "each arm uses all of its own detector hits; no common-hit peak-width filter",
        "arms": arms,
        "claims_prohibited": ["field equivalence", "optimization", "experimental performance", "Formal acceptance"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--axial-width-threshold-mm", type=float, default=4.0)
    args = parser.parse_args()
    result = analyze_campaign(campaign_path=args.campaign, runs_root=args.runs_root, threshold_mm=args.axial_width_threshold_mm)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"APERTURE_FULL_FLIGHT_COMPARISON=PASS ARMS={len(result['arms'])} OUTPUT={args.output}")


if __name__ == "__main__":
    main()
