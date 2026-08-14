"""Publish the canonical detector report for a detector-blind pulse winner."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import _peak_summary
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import publish_manifest


PROJECT = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "whole_stage_pulse_postselection_analysis"


def build_report(summary: dict, selector: dict) -> dict:
    if selector.get("selected_offset_rf_periods") != 0.0625:
        raise ValueError("selector winner is not the frozen +0.0625 RF delay")
    if selector.get("detector_results_used") is not False:
        raise ValueError("selector is not explicitly detector-blind")
    census = summary["census"]
    capture = summary["pulse_capture"]
    eligible = int(capture["counts"]["eligible"])
    detected_eligible = int(capture["detected_eligible_count"])
    detected = int(census["detector_crossing"])
    launched = int(census["launched"])
    handoff = int(census["multipole_handoff"])
    categories = capture["counts"]
    if sum(int(value) for value in categories.values()) != launched:
        raise ValueError("pulse eligibility categories are not exhaustive")
    peak = summary["pulse_effective_peak"]
    if peak is None or int(peak["particles"]) != detected_eligible:
        raise ValueError("canonical eligible detector peak identity differs")
    return {
        "schema_version": 1,
        "role": "whole_stage_native_pulse_winner_postselection_report",
        "status": "success",
        "selected_offset_rf_periods": 0.0625,
        "selected_offset_semantics": "positive_rf_delay",
        "selector_detector_results_used": False,
        "source_run_id": summary["reanalysis_provenance"]["source_run_id"],
        "clock_basis": summary["clock_basis"],
        "resolution_time_basis": summary["resolution_time_basis"],
        "census": census,
        "mutually_exclusive_pulse_eligibility": categories,
        "cohorts": {
            "eligible_detector": detected_eligible,
            "all_detector": detected,
            "detector_noneligible": detected - detected_eligible,
        },
        "transmission_fractions": {
            "detector_over_launched": detected / launched,
            "detector_over_eligible": detected_eligible / eligible,
            "detector_over_mother_handoff": detected / handoff,
            "eligible_detector_over_mother_handoff": detected_eligible / handoff,
        },
        "eligible_canonical_peak": peak,
        "all_detector_instrument_clock_diagnostic": summary["instrument_clock_peak"],
        "claim_limit": "Post-selection detector analysis only; the all-detector instrument-clock distribution is diagnostic and is not a resolution claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--selector", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8-sig"))
    selector = json.loads(args.selector.read_text(encoding="utf-8-sig"))
    report = build_report(summary, selector)
    results = args.run_dir / "results"
    results.mkdir(parents=True, exist_ok=True)
    report_path = results / "postselection_report.json"
    csv_path = results / "postselection_metrics.csv"
    png_path = results / "postselection_detector_peak.png"
    checkpoint_rows = []
    with args.checkpoints.open(encoding="utf-8-sig", newline="") as handle:
        checkpoint_rows = list(csv.DictReader(handle))
    eligible_ids = {
        int(row["particle_id"]) for row in checkpoint_rows
        if row["event"] == "pre_pulse_state"
        and row["pulse_eligibility"] == "eligible"
    }
    detector_rows = [
        row for row in checkpoint_rows if row["event"] == "detector_crossing"
    ]
    all_times = [float(row["pulse_effective_elapsed_us"]) for row in detector_rows]
    eligible_times = [
        float(row["pulse_effective_elapsed_us"]) for row in detector_rows
        if int(row["particle_id"]) in eligible_ids
    ]
    if (
        len(eligible_times) != report["cohorts"]["eligible_detector"]
        or len(all_times) != report["cohorts"]["all_detector"]
    ):
        raise ValueError("detector cohort census differs")
    all_peak, _ = _peak_summary(
        np.asarray(all_times), 100.0, bootstrap_resamples=0, bootstrap_seed=20260812
    )
    report["all_detector_canonical_peak"] = all_peak
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = []
    for name, value in report["census"].items():
        rows.append(("census", name, value))
    for name, value in report["mutually_exclusive_pulse_eligibility"].items():
        rows.append(("pulse_eligibility", name, value))
    for name, value in report["transmission_fractions"].items():
        rows.append(("transmission_fraction", name, value))
    peak_fields = ("particles", "mean_tof_us", "std_tof_ns", "direct_fwhm_tof_ns", "mass_resolution", "significant_kde_modes", "tof_skewness", "tof_excess_kurtosis")
    for section in ("eligible_canonical_peak", "all_detector_canonical_peak"):
        for name in peak_fields:
            rows.append((section, name, report[section][name]))
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("section", "metric", "value")); writer.writerows(rows)
    with plt.rc_context({"font.size": 8, "axes.labelsize": 9}):
        figure, axis = plt.subplots(figsize=(160 / 25.4, 90 / 25.4), layout="constrained")
        axis.hist(all_times, bins=50, density=True, color="#999999", alpha=0.45, label=f"All detector (N={len(all_times)})")
        axis.hist(eligible_times, bins=50, density=True, histtype="step", linewidth=1.5, color="#0072B2", label=f"Eligible (N={len(eligible_times)})")
        axis.set(xlabel="Pulse-effective flight time (µs)", ylabel="Probability density (1/µs)", title="Whole-stage +0.0625 RF delay: post-selection detector peak")
        axis.legend(frameon=False)
        figure.savefig(png_path, dpi=300, facecolor="white"); plt.close(figure)
    run_config = {
        "schema_version": 2, "run_id": args.run_id, "project": PROJECT,
        "mode": MODE, "project_root": str(args.repo_root.resolve()),
        "inputs": {"source_summary": str(args.summary.resolve()), "source_checkpoints": str(args.checkpoints.resolve()), "selector_receipt": str(args.selector.resolve())},
        "parameters": {"selected_offset_rf_periods": 0.0625, "detector_results_used_for_selection": False},
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
    }
    config_path = args.run_dir / "run_config.json"
    config_path.write_text(json.dumps(run_config, indent=2) + "\n", encoding="utf-8")
    manifest = args.run_dir / "run_manifest.json"
    publish_manifest(repo_root=args.repo_root, run_config=config_path, manifest_path=manifest, status="success", outputs=[report_path, csv_path, png_path], project=PROJECT, mode=MODE, label="whole-stage pulse postselection")
    print(f"WHOLE_STAGE_PULSE_POSTSELECTION=PASS REPORT={report_path} MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
