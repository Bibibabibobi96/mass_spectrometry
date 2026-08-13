"""Select a pulse offset using only frozen pre-detector acceptance metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.contracts.file_identity import file_sha256


def select(candidates: list[tuple[float, Path]]) -> dict[str, object]:
    rows = []
    for offset, path in candidates:
        summary = json.loads(path.read_text(encoding="utf-8-sig"))
        provenance = summary.get("reanalysis_provenance")
        if provenance is not None and (
            provenance.get("role") != "manifest_bound_single_flight_spatial_reanalysis"
            or provenance.get("claim_limit") != "detector_blind_spatial_selection_only"
            or not provenance.get("source_run_manifest", {}).get("sha256")
            or len(provenance.get("source_logs", [])) != 5
            or not provenance.get("analyzer", {}).get("sha256")
        ):
            raise ValueError("reanalysis candidate provenance is incomplete")
        metrics = summary["spatial_window_peak"]["detector_blind_selection_metrics"]
        if metrics.get("detector_results_used") is not False:
            raise ValueError("pulse selection metrics are not detector-blind")
        rows.append({
            "offset_rf_periods": offset,
            "summary_path": str(path),
            "summary_sha256": file_sha256(path),
            "reanalysis_provenance": provenance,
            "accepted_count": int(metrics["accepted_count"]),
            "normalized_2d_centroid_distance": float(
                metrics["normalized_2d_centroid_distance"]
            ),
            "quantile_normalized_edge_margin": float(
                metrics["quantile_normalized_edge_margin"]
            ),
            "minimum_normalized_edge_margin": float(
                metrics["minimum_normalized_edge_margin"]
            ),
        })
    rows.sort(key=lambda row: (
        -row["accepted_count"],
        row["normalized_2d_centroid_distance"],
        -row["quantile_normalized_edge_margin"],
        -row["minimum_normalized_edge_margin"],
        row["offset_rf_periods"],
    ))
    return {
        "schema_version": 1,
        "role": "rf_oatof_detector_blind_pulse_offset_selection_receipt",
        "selection_order": [
            "maximize_accepted_count",
            "minimize_normalized_2d_centroid_distance",
            "maximize_5pct_normalized_edge_margin",
            "maximize_minimum_normalized_edge_margin",
            "minimize_offset_rf_periods",
        ],
        "selection_uses_detector_outcome": False,
        "detector_results_used": False,
        "selected_offset_rf_periods": rows[0]["offset_rf_periods"],
        "candidates_ranked": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", nargs=2, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = select([(float(offset), Path(path)) for offset, path in args.candidate])
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
