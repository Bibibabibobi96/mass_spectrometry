"""Manifest-bound q8/q108 paired trajectory-quality diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import compute_peak_metrics

EVENTS = (
    "accelerator_grid1_forward", "local_accelerator_exit",
    "accelerator_focus_forward", "reflectron_entrance_forward",
    "reflectron_midgrid_forward", "reflectron_turning_point",
    "reflectron_exit_return", "detector_crossing",
)


def _load_manifest(path: Path, require_success: bool = True) -> dict:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if require_success and document.get("status") != "success":
        raise ValueError(f"manifest is not successful: {path}")
    return document


def _peak(values_us: np.ndarray, pulse_time_us: float = 0.0) -> dict:
    metrics, _ = compute_peak_metrics(values_us - pulse_time_us, 100.0)
    return {key: metrics[key] for key in (
        "particles", "mean_tof_us", "std_tof_ns", "direct_fwhm_tof_ns",
        "mass_resolution", "significant_kde_modes",
    )}


def analyze(args: argparse.Namespace) -> dict:
    q8_manifest = _load_manifest(args.q8_manifest, require_success=False)
    q108_manifest = _load_manifest(args.q108_manifest)
    q8_reanalysis = json.loads(args.q8_reanalysis_summary.read_text(encoding="utf-8-sig"))
    provenance = q8_reanalysis.get("reanalysis_provenance", {})
    if q8_reanalysis.get("status") != "success" or provenance.get("source_run_manifest", {}).get("sha256") != file_sha256(args.q8_manifest):
        raise ValueError("q8 successful reanalysis is not bound to the supplied source manifest")
    mapping_receipt = json.loads(args.sample_receipt.read_text(encoding="utf-8-sig"))
    mapping = {int(k): int(v) for k, v in mapping_receipt["selection"]["local_to_global_particle_id"].items()}
    expected_local = set(range(1, 101))
    expected_global = set(mapping.values())
    if set(mapping) != expected_local or len(expected_global) != 100:
        raise ValueError("sample receipt must define a bijective local 1..100 mapping")

    q8 = pd.read_csv(args.q8_checkpoints)
    q108 = pd.read_csv(args.q108_checkpoints)
    q8["particle_id"] = q8.particle_id.astype(int)
    q108["particle_id"] = q108.particle_id.astype(int)
    q108["global_particle_id"] = q108.particle_id.map(mapping)
    if q108.global_particle_id.isna().any():
        raise ValueError("q108 checkpoint contains an unmapped local ID")

    paired_rows: list[dict] = []
    arm_rows: list[dict] = []
    arm_peaks: dict[str, dict[str, dict]] = {"focus": {}, "detector": {}}
    censuses = {
        "q8": {event: int(q8.loc[(q8.event == event) & q8.particle_id.isin(expected_global), "particle_id"].nunique()) for event in EVENTS},
        "q108": {event: int(q108.loc[q108.event == event, "global_particle_id"].nunique()) for event in EVENTS},
    }
    event_pairs: dict[str, dict[str, np.ndarray]] = {}
    for event in EVENTS:
        left = q8.loc[(q8.event == event) & q8.particle_id.isin(expected_global), ["particle_id", "instrument_time_us"]].rename(columns={"particle_id": "global_particle_id", "instrument_time_us": "q8_us"})
        right = q108.loc[q108.event == event, ["global_particle_id", "instrument_time_us"]].rename(columns={"instrument_time_us": "q108_us"})
        joined = left.merge(right, on="global_particle_id", validate="one_to_one").sort_values("global_particle_id")
        if len(joined) != 100 or set(joined.global_particle_id.astype(int)) != expected_global:
            raise ValueError(f"event does not close over the frozen 100 IDs: {event}")
        values = {"q8": joined.q8_us.to_numpy(float), "q108": joined.q108_us.to_numpy(float)}
        event_pairs[event] = values
        delta_ns = (values["q108"] - values["q8"]) * 1000.0
        paired_rows.append({
            "event": event, "paired_count": 100,
            "mean_delta_t_ns": float(np.mean(delta_ns)),
            "sample_sigma_delta_t_ns": float(np.std(delta_ns, ddof=1)),
            "rms_delta_t_ns": float(np.sqrt(np.mean(delta_ns ** 2))),
            "max_absolute_delta_t_ns": float(np.max(np.abs(delta_ns))),
        })
        for arm, times in values.items():
            arm_rows.append({
                "event": event, "arm": arm, "count": 100,
                "mean_time_us": float(np.mean(times)),
                "sample_sigma_ns": float(np.std(times, ddof=1) * 1000.0),
            })

    for label, event in (("focus", "accelerator_focus_forward"), ("detector", "detector_crossing")):
        for arm, values in event_pairs[event].items():
            pulse = 0.0 if label == "focus" else 45.40674277644788
            arm_peaks[label][arm] = _peak(values, pulse)
            arm_peaks[label][arm]["time_basis"] = "focus_instrument_clock_distribution" if label == "focus" else "detector_time_minus_pulse_effective_time"

    thresholds = mapping_receipt["paired_thresholds"]
    focus = next(row for row in paired_rows if row["event"] == "accelerator_focus_forward")
    decision = {
        "max_absolute_paired_mean_shift_ns": float(thresholds["max_absolute_paired_mean_shift_ns"]),
        "max_paired_sample_sigma_ns": float(thresholds["max_paired_sample_sigma_ns"]),
        "mean_shift_pass": abs(focus["mean_delta_t_ns"]) <= float(thresholds["max_absolute_paired_mean_shift_ns"]),
        "paired_sigma_pass": focus["sample_sigma_delta_t_ns"] <= float(thresholds["max_paired_sample_sigma_ns"]),
    }
    decision["paired_trajectory_quality_pass"] = decision["mean_shift_pass"] and decision["paired_sigma_pass"]
    reference_effects = {"accelerator_dz_effect_ns": 0.0399346, "stage2_field_effect_ns": 0.337887}
    reference_effects["focus_paired_sigma_over_accelerator_dz_effect"] = focus["sample_sigma_delta_t_ns"] / reference_effects["accelerator_dz_effect_ns"]
    reference_effects["focus_paired_sigma_over_stage2_field_effect"] = focus["sample_sigma_delta_t_ns"] / reference_effects["stage2_field_effect_ns"]

    trace_text = args.q108_stdout.read_text(encoding="utf-8-sig", errors="replace")
    trace_line = next((line for line in trace_text.splitlines() if "TRACE: field_mode" in line and "trajectory_quality=108" in line), None)
    if trace_line is None:
        raise ValueError("q108 machine TRACE authority is absent")
    config = json.loads(args.q108_configuration.read_text(encoding="utf-8-sig"))
    profiles = {item["profile_id"]: item["trajectory_quality"] for item in config["trajectory_quality_profiles"]}
    if profiles.get("tqual_108") != 108:
        raise ValueError("q108 governed configuration profile is absent")
    geometry = json.loads(args.q108_geometry.read_text(encoding="utf-8-sig"))

    args.output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(paired_rows).to_csv(args.output / "checkpoint_paired_statistics.csv", index=False)
    pd.DataFrame(arm_rows).to_csv(args.output / "checkpoint_arm_statistics.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    x = np.arange(len(EVENTS)); mean = np.array([r["mean_delta_t_ns"] for r in paired_rows]); sigma = np.array([r["sample_sigma_delta_t_ns"] for r in paired_rows])
    axes[0].plot(x, mean, "o-"); axes[0].axhline(0, color="black", lw=.8); axes[0].set(ylabel="q108 - q8 mean Δt (ns)", title="Paired mean shift")
    axes[1].plot(x, sigma, "o-"); axes[1].axhline(decision["max_paired_sample_sigma_ns"], color="C1", ls="--", label="frozen focus gate"); axes[1].set(ylabel="paired Δt sample sigma (ns)", title="Paired dispersion"); axes[1].legend()
    for ax in axes: ax.set_xticks(x, EVENTS, rotation=70)
    fig.savefig(args.output / "trajectory_quality_paired_check.png", dpi=180); plt.close(fig)

    result = {
        "schema_version": 1, "role": "rf_oatof_trajectory_quality_manifest_bound_paired_diagnostic", "status": "success",
        "paired_particle_count": 100,
        "ordered_global_particle_id_sha256": hashlib.sha256("\n".join(map(str, mapping_receipt["selection"]["global_particle_ids"])).encode()).hexdigest().upper(),
        "machine_numerics_authority": {
            "resolved_runtime_value": 108,
            "governed_profile_id": "tqual_108",
            "configuration": {"path": str(args.q108_configuration), "sha256": file_sha256(args.q108_configuration)},
            "program_build": {"path": str(args.q108_program_build), "sha256": file_sha256(args.q108_program_build)},
            "simion_stdout_trace": {"path": str(args.q108_stdout), "sha256": file_sha256(args.q108_stdout), "line": trace_line},
            "resolved_geometry_baseline": {"path": str(args.q108_geometry), "sha256": file_sha256(args.q108_geometry), "trajectory_quality_field": geometry.get("simion", {}).get("trajectory_quality"), "authority": "geometry_baseline_not_runtime_numerics"},
            "interpretation": "Program/TRACE plus governed tqual_108 profile is runtime numerical authority; resolved_geometry trajectory_quality=8 is an inherited geometry baseline and does not override runtime T.Qual.",
        },
        "manifest_bound_sources": {
            "q8": {"run_id": q8_manifest["run_id"], "source_manifest_status": q8_manifest.get("status"), "manifest_path": str(args.q8_manifest), "manifest_sha256": file_sha256(args.q8_manifest), "successful_reanalysis_summary_path": str(args.q8_reanalysis_summary), "successful_reanalysis_summary_sha256": file_sha256(args.q8_reanalysis_summary), "checkpoint_path": str(args.q8_checkpoints), "checkpoint_sha256": file_sha256(args.q8_checkpoints)},
            "q108": {"run_id": q108_manifest["run_id"], "manifest_path": str(args.q108_manifest), "manifest_sha256": file_sha256(args.q108_manifest), "checkpoint_path": str(args.q108_checkpoints), "checkpoint_sha256": file_sha256(args.q108_checkpoints)},
            "mapping_receipt": {"path": str(args.sample_receipt), "sha256": file_sha256(args.sample_receipt)},
        },
        "census": censuses, "checkpoint_paired_statistics": paired_rows,
        "focus_time_distribution_and_detector_pulse_effective_peak_metrics": arm_peaks,
        "absolute_instrument_clock_peak_policy": "forbidden_for_resolution_claim",
        "focus_decision": decision,
        "effect_scale_comparison": reference_effects,
        "claim_limit": "N=100 trajectory integration quality sensitivity only; not a PA spatial-grid convergence or Formal result.",
    }
    json_path = args.output / "trajectory_quality_paired_check.json"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    outputs = [json_path, args.output / "checkpoint_paired_statistics.csv", args.output / "checkpoint_arm_statistics.csv", args.output / "trajectory_quality_paired_check.png"]
    if not getattr(args, "no_derived_manifest", False):
        manifest = {"schema_version": 1, "role": "derived_analysis_manifest", "status": "success", "outputs": [{"path": str(p), "sha256": file_sha256(p), "bytes": p.stat().st_size} for p in outputs]}
        (args.output / "derived_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("q8-checkpoints", "q108-checkpoints", "q8-manifest", "q8-reanalysis-summary", "q108-manifest", "sample-receipt", "q108-configuration", "q108-program-build", "q108-stdout", "q108-geometry", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--no-derived-manifest", action="store_true")
    result = analyze(parser.parse_args())
    print(f"TQUAL_PAIRED_ANALYSIS=PASS PRIMARY={result['focus_decision']['paired_trajectory_quality_pass']}")


if __name__ == "__main__":
    main()
