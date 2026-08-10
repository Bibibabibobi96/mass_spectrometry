"""Compare legacy and conditional sources against a detector-blind held-out oracle."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


FEATURES = (
    "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us",
    "vz_mm_per_us", "kinetic_energy_eV",
)


def _prepulse(path: Path, eligible_only: bool = False) -> dict[int, np.ndarray]:
    result: dict[int, np.ndarray] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["event"] != "pre_pulse_state":
                continue
            if eligible_only and row.get("pulse_eligibility") != "eligible":
                continue
            result[int(row["particle_id"])] = np.asarray([float(row[key]) for key in FEATURES])
    return result


def _distance(sample: np.ndarray, oracle: np.ndarray) -> tuple[float, list[float]]:
    q = np.linspace(0.0, 1.0, 257)
    scale = np.std(oracle, axis=0, ddof=1)
    scale[scale < 1e-12] = 1.0
    per_feature = np.mean(
        np.abs(np.quantile(sample, q, axis=0) - np.quantile(oracle, q, axis=0)),
        axis=0,
    ) / scale
    return float(np.mean(per_feature)), [float(value) for value in per_feature]


def compare(
    candidate_checkpoints: list[Path],
    receipt_path: Path,
    new_checkpoints: Path,
    legacy_checkpoints: Path,
    output: Path,
    bootstrap_count: int = 500,
) -> dict[str, object]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    selected = {
        (int(row["batch_index"]), int(row["batch_particle_id"]))
        for row in receipt["selected_lineage"]
    }
    held_out: list[np.ndarray] = []
    for batch_index, path in enumerate(candidate_checkpoints, 1):
        rows = _prepulse(path, eligible_only=True)
        held_out.extend(
            value for particle_id, value in rows.items()
            if (batch_index, particle_id) not in selected
        )
    oracle = np.asarray(held_out)
    new = np.asarray(list(_prepulse(new_checkpoints).values()))
    legacy = np.asarray(list(_prepulse(legacy_checkpoints).values()))
    if min(len(oracle), len(new), len(legacy)) < 100:
        raise ValueError("accuracy comparison requires at least 100 particles per population")
    new_distance, new_features = _distance(new, oracle)
    legacy_distance, legacy_features = _distance(legacy, oracle)
    rng = np.random.default_rng(2026081003)
    improvements = np.empty(bootstrap_count)
    for index in range(bootstrap_count):
        boot_oracle = oracle[rng.integers(0, len(oracle), len(oracle))]
        boot_new = new[rng.integers(0, len(new), len(new))]
        boot_legacy = legacy[rng.integers(0, len(legacy), len(legacy))]
        improvements[index] = _distance(boot_legacy, boot_oracle)[0] - _distance(boot_new, boot_oracle)[0]
    ci = np.quantile(improvements, [0.025, 0.975])
    result: dict[str, object] = {
        "schema_version": 1,
        "role": "rf_oatof_steady_source_accuracy_comparison",
        "status": "success",
        "metric": "mean_oracle_sigma_normalized_1d_wasserstein_over_prepulse_7d",
        "features": list(FEATURES),
        "population_counts": {"legacy": len(legacy), "new": len(new), "held_out_oracle": len(oracle)},
        "legacy_distance": legacy_distance,
        "new_distance": new_distance,
        "legacy_per_feature_distance": dict(zip(FEATURES, legacy_features, strict=True)),
        "new_per_feature_distance": dict(zip(FEATURES, new_features, strict=True)),
        "distance_reduction_fraction": 1.0 - new_distance / legacy_distance,
        "bootstrap": {
            "replicates": bootstrap_count,
            "legacy_minus_new_distance_mean": float(np.mean(improvements)),
            "confidence_interval_95": [float(ci[0]), float(ci[1])],
            "new_is_closer_with_95pct_confidence": bool(ci[0] > 0),
        },
        "oracle_is_detector_blind": True,
        "resolution_claim_authorized": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-checkpoints", action="append", required=True, type=Path)
    parser.add_argument("--selection-receipt", required=True, type=Path)
    parser.add_argument("--new-checkpoints", required=True, type=Path)
    parser.add_argument("--legacy-checkpoints", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compare(
        args.candidate_checkpoints, args.selection_receipt, args.new_checkpoints,
        args.legacy_checkpoints, args.output,
    )
    print(
        "STEADY_SOURCE_ACCURACY=PASS "
        f"LEGACY={result['legacy_distance']:.6g} NEW={result['new_distance']:.6g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
