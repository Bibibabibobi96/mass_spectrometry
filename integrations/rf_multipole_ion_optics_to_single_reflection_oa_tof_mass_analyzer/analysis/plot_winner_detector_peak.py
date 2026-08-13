"""Render the manifest-bound winner detector flight-time distribution."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common.contracts.file_identity import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8-sig"))
    if summary.get("reanalysis_provenance", {}).get("claim_limit") != "detector_blind_spatial_selection_only":
        raise ValueError("winner plot requires manifest-bound reanalysis provenance")
    with args.checkpoints.open(encoding="utf-8-sig", newline="") as handle:
        values = [
            float(row["pulse_effective_elapsed_us"])
            for row in csv.DictReader(handle) if row["event"] == "detector_crossing"
        ]
    if not values or min(values) <= 0:
        raise ValueError("winner detector elapsed times must be positive")
    peak = summary["pulse_effective_peak"]
    with plt.rc_context({"font.size": 8, "axes.labelsize": 9}):
        figure, axis = plt.subplots(figsize=(160 / 25.4, 90 / 25.4), layout="constrained")
        axis.hist(values, bins=50, density=True, color="#0072B2", alpha=0.78)
        axis.set_xlabel("Pulse-effective flight time (µs)")
        axis.set_ylabel("Probability density (1/µs)")
        axis.set_title("Fixed winner offset 0: detector distribution")
        axis.text(0.02, 0.97, f"N={len(values)}\nR={peak['mass_resolution']:.0f}\nmodes={peak['significant_kde_modes']}", transform=axis.transAxes, va="top")
        figure.savefig(args.output, dpi=300, facecolor="white")
        plt.close(figure)
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_winner_detector_peak_figure",
        "checkpoints_sha256": file_sha256(args.checkpoints),
        "summary_sha256": file_sha256(args.summary),
        "output_sha256": file_sha256(args.output),
        "sample_count": len(values),
        "time_basis": "pulse_effective_elapsed_us",
        "bins": 50,
        "normalization": "probability_density",
        "source_run_id": summary["reanalysis_provenance"]["source_run_id"],
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
