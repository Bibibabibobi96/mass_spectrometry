"""Compare the detector-blind pre-pulse results of the 300 mm aperture campaign.

This module deliberately only consumes successful, manifest-bound pre-pulse
screens.  It reports the whole launched population denominator and never
turns a survivor-only state table into a transmission or resolution claim.
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


CAMPAIGN_ID = "ideal_acceptance_300mm_aperture_height_pre_pulse_n5000"
CAMPAIGN_IDS = frozenset({
    CAMPAIGN_ID,
    "ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000",
})
RECEIPT_ROLE = "rf_oatof_pre_pulse_time_series_screening_receipt"
SUMMARY_ROLE = "rf_oatof_simion_single_flight_summary"
STATE_COLUMNS = {"particle_id", "event", "sample_index", "z_mm", "vz_mm_per_us", "survival_status"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _manifest_output_sha(manifest: dict[str, Any], path: Path) -> str | None:
    for item in manifest.get("outputs", []):
        if not isinstance(item, dict):
            continue
        item_path = item.get("path")
        if isinstance(item_path, str) and Path(item_path).name == path.name:
            return item.get("sha256")
    return None


def _read_states(path: Path, expected_count: int) -> tuple[np.ndarray, np.ndarray]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not STATE_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("state table lacks required pre-pulse fields")
        rows = list(reader)
    if len(rows) != expected_count:
        raise ValueError("state table row count differs from receipt")
    ids = np.asarray([int(row["particle_id"]) for row in rows], dtype=np.int64)
    if len(np.unique(ids)) != len(ids):
        raise ValueError("state table repeats particle IDs")
    if any(row["event"] != "pre_pulse_time_series_state" for row in rows):
        raise ValueError("state table contains a non pre-pulse event")
    if any(row["survival_status"] != "alive" for row in rows):
        raise ValueError("state table contains non-alive rows")
    samples = {int(row["sample_index"]) for row in rows}
    if len(samples) != 1:
        raise ValueError("aperture campaign state table must contain exactly one anchor sample")
    z = np.asarray([float(row["z_mm"]) for row in rows], dtype=float)
    vz = np.asarray([float(row["vz_mm_per_us"]) for row in rows], dtype=float)
    if not (np.all(np.isfinite(z)) and np.all(np.isfinite(vz))):
        raise ValueError("state table contains non-finite z or vz")
    return z, vz


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
    design = np.column_stack((np.ones(z_mm.size), z_mm))
    intercept, slope = np.linalg.lstsq(design, vz_mm_per_us, rcond=None)[0]
    residual = vz_mm_per_us - (intercept + slope * z_mm)
    total = float(np.sum((vz_mm_per_us - np.mean(vz_mm_per_us)) ** 2))
    residual_sum = float(np.sum(residual**2))
    r_squared = 1.0 if total == 0.0 and residual_sum == 0.0 else 1.0 - residual_sum / total
    linear = _polynomial_metrics(z_mm, vz_mm_per_us, 1)
    quadratic = _polynomial_metrics(z_mm, vz_mm_per_us, 2) if z_mm.size >= 3 else None
    cubic = _polynomial_metrics(z_mm, vz_mm_per_us, 3) if z_mm.size >= 4 else None
    random_model = cubic or quadratic or linear
    return {
        "intercept_mm_per_us": float(intercept),
        "slope_per_us": float(slope),
        "k_per_us": float(slope),
        "r_squared": float(r_squared),
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
        "percentiles_mm": {
            "p00": float(percentile[0]), "p01": float(percentile[1]),
            "p05": float(percentile[2]), "p50": float(percentile[3]),
            "p95": float(percentile[4]), "p99": float(percentile[5]), "p100": float(percentile[6]),
        },
        "full_range_mm": full_range,
        "p01_p99_range_mm": p01_p99_range,
        "exceeds_4mm_full_range": full_range > threshold_mm,
        "exceeds_4mm_p01_p99_range": p01_p99_range > threshold_mm,
        "threshold_mm": threshold_mm,
    }


def _expected_row_metadata(row: dict[str, Any]) -> tuple[str, float, str]:
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
    return realization, height_mm, connection


def _analyze_arm(
    run_dir: Path, row: dict[str, Any], campaign: dict[str, Any],
    candidate_sha256: str, threshold_mm: float,
) -> dict[str, Any]:
    run_id = row.get("run_id")
    experiment_id = row.get("experiment_id")
    if not isinstance(run_id, str) or not isinstance(experiment_id, str):
        raise ValueError("campaign row lacks run or experiment identity")
    if run_dir.name != run_id:
        raise ValueError(f"run directory identity differs from campaign row: {run_dir.name}")
    manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
    summary = _load_json(run_dir / "summary.json", "run summary")
    receipt_path = run_dir / "results" / "pre_pulse_time_series_screening_receipt.json"
    state_path = run_dir / "results" / "pre_pulse_time_series_states.csv"
    receipt = _load_json(receipt_path, "pre-pulse receipt")
    if summary.get("role") != SUMMARY_ROLE or summary.get("status") != "success":
        raise ValueError(f"{run_id}: summary is not a successful pre-pulse screen")
    if receipt.get("role") != RECEIPT_ROLE or receipt.get("status") != "success":
        raise ValueError(f"{run_id}: receipt is not a successful pre-pulse screen")
    if summary.get("pulse_disabled") is not True or receipt.get("pulse_disabled") is not True:
        raise ValueError(f"{run_id}: screen is not pulse disabled")
    expected_receipt_sha = _manifest_output_sha(manifest, receipt_path)
    expected_state_sha = _manifest_output_sha(manifest, state_path)
    if expected_receipt_sha != _sha256(receipt_path) or expected_state_sha != _sha256(state_path):
        raise ValueError(f"{run_id}: manifest output SHA differs")
    outputs = receipt.get("outputs", {}).get("states", {})
    if outputs.get("sha256") != _sha256(state_path):
        raise ValueError(f"{run_id}: receipt state SHA differs")
    identities = receipt.get("identities", {})
    realization, height_mm, connection = _expected_row_metadata(row)
    if identities.get("campaign_id") != campaign.get("campaign_id") or identities.get("experiment_id") != experiment_id:
        raise ValueError(f"{run_id}: campaign or experiment identity differs")
    if identities.get("connection_profile_id") != connection:
        raise ValueError(f"{run_id}: connection identity differs")
    if identities.get("layout_profile_id") != row["overrides"]["single_flight_layout_profile_id"]:
        raise ValueError(f"{run_id}: layout identity differs")
    if identities.get("candidate_sha256") != candidate_sha256:
        raise ValueError(f"{run_id}: frozen Candidate identity differs")
    mother_count = receipt.get("particle_count")
    state_count = receipt.get("state_row_count")
    census = receipt.get("terminal_census")
    samples = receipt.get("sample_census")
    if not isinstance(mother_count, int) or mother_count < 1 or not isinstance(state_count, int):
        raise ValueError(f"{run_id}: receipt has invalid population counts")
    if not isinstance(census, dict) or sum(item.get("count", -1) for item in census.values() if isinstance(item, dict)) != mother_count:
        raise ValueError(f"{run_id}: terminal census does not close the mother cohort")
    if not isinstance(samples, list) or len(samples) != 1:
        raise ValueError(f"{run_id}: receipt does not have exactly one anchor census")
    anchor = samples[0]
    if anchor.get("alive_count") != state_count or anchor.get("missing_count") != mother_count - state_count:
        raise ValueError(f"{run_id}: anchor census does not close the observed state")
    z_mm, vz_mm_per_us = _read_states(state_path, state_count)
    return {
        "run_id": run_id,
        "experiment_id": experiment_id,
        "realization": realization,
        "aperture_height_mm": height_mm,
        "layout_profile_id": identities["layout_profile_id"],
        "connection_profile_id": connection,
        "state_table": {"path": str(state_path.resolve()), "sha256": _sha256(state_path)},
        "mother_cohort": {
            "launched_count": mother_count,
            "observed_pre_pulse_count": state_count,
            "transmission_fraction": state_count / mother_count,
            "loss_count": mother_count - state_count,
            "loss_fraction": (mother_count - state_count) / mother_count,
            "terminal_loss_census": {key: item["count"] for key, item in census.items()},
        },
        "axial_z_width": _width_metrics(z_mm, threshold_mm),
        "z_vz_affine": _affine_metrics(z_mm, vz_mm_per_us),
    }


def analyze_campaign(*, campaign_path: Path, runs_root: Path, threshold_mm: float = 4.0) -> dict[str, Any]:
    """Return a fail-closed, compact comparison for all eight campaign arms."""
    campaign = _load_json(campaign_path, "campaign")
    campaign_id = campaign.get("campaign_id")
    if campaign_id not in CAMPAIGN_IDS:
        raise ValueError("analysis only accepts a registered 300 mm aperture pre-pulse campaign")
    rows = campaign.get("experiments", {}).get("rows")
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("campaign must contain exactly eight arms")
    expected_candidate = campaign.get("experiments", {}).get("shared", {}).get("single_flight_three_zone_candidate", {}).get("sha256")
    if not isinstance(expected_candidate, str):
        raise ValueError("campaign lacks frozen three-zone Candidate identity")
    arms = [
        _analyze_arm(runs_root / row["run_id"], row, campaign, expected_candidate, threshold_mm)
        for row in rows
    ]
    shared_values = {arm["mother_cohort"]["launched_count"] for arm in arms}
    if shared_values != {5000}:
        raise ValueError("campaign arms do not preserve the declared N=5000 mother cohort")
    return {
        "schema_version": 1,
        "role": "oatof_ideal_acceptance_300mm_aperture_pre_pulse_comparison",
        "qualification": "DETECTOR_BLIND_SOURCE_ONLY",
        "campaign": {"id": campaign_id, "path": str(campaign_path.resolve()), "sha256": _sha256(campaign_path)},
        "candidate_sha256": expected_candidate,
        "axial_width_threshold_mm": threshold_mm,
        "arms": arms,
        "claims_prohibited": ["detector performance", "resolution", "field equivalence", "Formal acceptance", "postselected transmission"],
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
    print(f"APERTURE_PRE_PULSE_COMPARISON=PASS ARMS={len(result['arms'])} OUTPUT={args.output}")


if __name__ == "__main__":
    main()
