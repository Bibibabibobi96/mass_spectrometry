"""Manifest-bound paired 2x2 attribution of accelerator stage fields."""

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

EVENTS = ("pre_pulse_state", "accelerator_grid1_forward", "local_accelerator_exit", "accelerator_focus_forward", "reflectron_entrance_forward", "reflectron_midgrid_forward", "reflectron_turning_point", "reflectron_exit_return", "detector_crossing")
ARMS = ("RR", "IR", "RI", "II")


def _load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["particle_id"] = frame["particle_id"].astype(int)
    return frame


def _event(frame: pd.DataFrame, event: str) -> pd.Series:
    rows = frame.loc[frame.event.eq(event), ["particle_id", "instrument_time_us"]]
    if rows.particle_id.duplicated().any():
        raise ValueError(f"duplicate particle/event rows: {event}")
    return rows.set_index("particle_id").instrument_time_us.astype(float).sort_index()


def effect_vectors(values: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Return high-minus-low effects for +/-1 stage coding."""
    return {
        "stage1_ideal_main": (values["IR"] + values["II"] - values["RR"] - values["RI"]) / 2,
        "stage2_ideal_main": (values["RI"] + values["II"] - values["RR"] - values["IR"]) / 2,
        "stage1_stage2_interaction": (values["II"] + values["RR"] - values["IR"] - values["RI"]) / 2,
    }


def analyze(paths: dict[str, Path], manifests: dict[str, Path], output: Path) -> dict[str, object]:
    frames = {arm: _load(paths[arm]) for arm in ARMS}
    ids = {arm: set(frames[arm].particle_id) for arm in ARMS}
    expected = set(range(1, 1001))
    if any(value != expected for value in ids.values()):
        raise ValueError("all arms must contain exactly particle IDs 1..1000")
    source = {}
    for arm in ARMS:
        manifest = json.loads(manifests[arm].read_text(encoding="utf-8-sig"))
        if manifest.get("run_id") != manifests[arm].parent.name:
            raise ValueError(f"manifest run identity differs: {arm}")
        if arm != "RR" and manifest.get("status") != "success":
            raise ValueError(f"factorial child manifest is not successful: {arm}")
        source[arm] = {"run_id": manifest["run_id"], "manifest_status": manifest.get("status"),
                       "checkpoint_path": str(paths[arm]), "checkpoint_sha256": file_sha256(paths[arm]),
                       "manifest_path": str(manifests[arm]), "manifest_sha256": file_sha256(manifests[arm])}
    rows, paired_rows = [], []
    first = None
    effects_by_event: dict[str, dict[str, dict[str, float]]] = {}
    for event in EVENTS:
        series = {arm: _event(frames[arm], event) for arm in ARMS}
        if any(len(value) != 1000 or not value.index.equals(series["RR"].index) for value in series.values()):
            raise ValueError(f"paired event population differs: {event}")
        arrays = {arm: value.to_numpy() * 1000 for arm, value in series.items()}
        for arm in ARMS:
            rows.append({"event": event, "arm": arm, "sample_count": 1000,
                         "mean_time_ns": float(np.mean(arrays[arm])), "sample_sigma_ns": float(np.std(arrays[arm], ddof=1))})
        for arm in ("IR", "RI", "II"):
            delta = arrays[arm] - arrays["RR"]
            paired_rows.append({"event": event, "contrast": f"{arm}-RR", "sample_count": 1000,
                                "mean_delta_ns": float(np.mean(delta)), "sample_sigma_delta_ns": float(np.std(delta, ddof=1)),
                                "rms_delta_ns": float(np.sqrt(np.mean(delta**2))), "minimum_delta_ns": float(np.min(delta)), "maximum_delta_ns": float(np.max(delta))})
            if first is None and np.any(delta != 0):
                first = event
        effects = effect_vectors(arrays)
        effects_by_event[event] = {name: {"mean_ns": float(np.mean(value)), "sample_sigma_ns": float(np.std(value, ddof=1)),
                                                "minimum_ns": float(np.min(value)), "maximum_ns": float(np.max(value))}
                                    for name, value in effects.items()}
    peaks = {}
    for arm in ARMS:
        detector_us = _event(frames[arm], "detector_crossing").to_numpy()
        peak, _ = compute_peak_metrics(detector_us, 100.0)
        peaks[arm] = {key: peak[key] for key in ("mean_tof_us", "std_tof_ns", "direct_fwhm_tof_ns", "time_equivalent_resolution", "mass_resolution", "significant_kde_modes")}
    output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(rows).to_csv(output / "checkpoint_arm_statistics.csv", index=False)
    pd.DataFrame(paired_rows).to_csv(output / "checkpoint_paired_deltas.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    stats = pd.DataFrame(rows)
    for arm in ARMS:
        part = stats[stats.arm.eq(arm)]
        axes[0].plot(range(len(EVENTS)), part.sample_sigma_ns, marker="o", label=arm)
    axes[0].set(xticks=range(len(EVENTS)), xticklabels=EVENTS, ylabel="sample sigma (ns)", title="Checkpoint time spread")
    axes[0].tick_params(axis="x", rotation=70); axes[0].legend()
    detector = {arm: _event(frames[arm], "detector_crossing").to_numpy() * 1000 for arm in ARMS}
    for name, values in effect_vectors(detector).items():
        axes[1].hist(values - np.mean(values), bins=50, histtype="step", density=True, label=name)
    axes[1].set(xlabel="centered paired effect (ns)", ylabel="density", title="Detector 2x2 effect distributions"); axes[1].legend(fontsize=8)
    fig.savefig(output / "stage_field_2x2_diagnostics.png", dpi=180); plt.close(fig)
    result = {"schema_version": 1, "role": "rf_oatof_stage_field_2x2_paired_attribution", "status": "success",
              "paired_particle_count": 1000, "ordered_particle_id_sha256": hashlib.sha256("\n".join(map(str, range(1,1001))).encode()).hexdigest().upper(),
              "factor_coding": {"stage1": {"real": -1, "ideal": 1}, "stage2": {"real": -1, "ideal": 1},
                                "effect_scale": "main effects are average high-minus-low in ns; interaction is one-half the difference-of-differences in ns (2 times the +/-1 regression interaction coefficient)"},
              "sources": source, "first_nonzero_paired_divergence_event": first, "checkpoint_effects": effects_by_event,
              "detector_peak_metrics": peaks, "bootstrap": {"status": "not_computed", "reason": "existing bootstrap is single-arm resolution-only; this paired factorial report remains descriptive"},
              "tables": ["checkpoint_arm_statistics.csv", "checkpoint_paired_deltas.csv"], "diagnostic_figure": "stage_field_2x2_diagnostics.png"}
    (output / "stage_field_2x2_attribution.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    for arm in ARMS:
        p.add_argument(f"--{arm.lower()}-checkpoints", required=True, type=Path); p.add_argument(f"--{arm.lower()}-manifest", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path); a = p.parse_args()
    result = analyze({arm: getattr(a, f"{arm.lower()}_checkpoints") for arm in ARMS}, {arm: getattr(a, f"{arm.lower()}_manifest") for arm in ARMS}, a.output)
    print(f"STAGE_FIELD_2X2=PASS PARTICLES={result['paired_particle_count']} FIRST={result['first_nonzero_paired_divergence_event']}")


if __name__ == "__main__": main()
