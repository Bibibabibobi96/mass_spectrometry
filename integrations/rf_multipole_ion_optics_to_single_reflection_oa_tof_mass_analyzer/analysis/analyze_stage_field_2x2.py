"""Manifest-bound paired 2x2 attribution of accelerator stage fields."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path
from common.analysis.peak_metrics import compute_peak_metrics

EVENTS = ("pre_pulse_state", "accelerator_grid1_forward", "local_accelerator_exit", "accelerator_focus_forward", "reflectron_entrance_forward", "reflectron_midgrid_forward", "reflectron_turning_point", "reflectron_exit_return", "detector_crossing")
ARMS = ("RR", "IR", "RI", "II")
PEAK_FIELDS = (
    "particles", "mean_tof_us", "std_tof_ns", "direct_fwhm_tof_ns",
    "time_equivalent_resolution", "mass_resolution", "significant_kde_modes",
)
CANONICAL_RR_RECEIPT_ROLE = "manifest_bound_rr_canonical_detector_clock_reanalysis"


def _verify_success_v2_manifest(path: Path) -> dict[str, object]:
    """Verify a success v2 run with the repository's authoritative verifier."""
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != 2:
        raise ValueError("checkpoint evidence manifest must use schema_version 2")
    if manifest.get("status") != "success":
        raise ValueError("checkpoint evidence manifest must be successful")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "common.contracts.verify_run_manifest",
                str(path),
                "--require-status",
                "success",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
            timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown verifier failure").strip()
        raise ValueError(f"checkpoint evidence manifest verification failed: {detail}") from exc
    return manifest


def _bound_output_record(
    manifest: dict[str, object], manifest_path: Path, evidence_path: Path,
) -> dict[str, object]:
    """Require one verified manifest output to bind this exact local file."""
    resolved = evidence_path.resolve()
    matches = [
        record
        for record in manifest.get("outputs", [])
        if record_path(record, base_dir=manifest_path.parent) == resolved
    ]
    if len(matches) != 1:
        raise ValueError(
            f"success v2 manifest does not uniquely bind output path: {resolved}"
        )
    record = matches[0]
    if int(record.get("bytes", -1)) != resolved.stat().st_size:
        raise ValueError(f"manifest-bound output byte count differs: {resolved}")
    if str(record.get("sha256", "")).upper() != file_sha256(resolved):
        raise ValueError(f"manifest-bound output SHA-256 differs: {resolved}")
    run_config = record_path(manifest["run_config"], base_dir=manifest_path.parent)
    run_id = str(manifest.get("run_id", ""))
    if not run_id or run_config.parent.name != run_id:
        raise ValueError("manifest run identity differs from its verified run_config")
    try:
        resolved.relative_to(run_config.parent)
    except ValueError as exc:
        raise ValueError("manifest-bound output is outside the publishing run") from exc
    return record


def bind_checkpoint_evidence(
    arm: str,
    checkpoint_path: Path,
    manifest_path: Path,
    canonical_receipt_path: Path | None = None,
) -> dict[str, object]:
    """Bind an arm checkpoint to a verified solver manifest or RR receipt chain."""
    manifest = _verify_success_v2_manifest(manifest_path)
    _bound_output_record(manifest, manifest_path, checkpoint_path)
    evidence_type = "success_v2_manifest"
    source: dict[str, object] = {
        "run_id": manifest["run_id"],
        "manifest_status": manifest["status"],
        "manifest_schema_version": manifest["schema_version"],
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": file_sha256(checkpoint_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
    }
    if canonical_receipt_path is not None:
        if arm != "RR":
            raise ValueError("canonical detector-clock receipt is only valid for RR")
        _bound_output_record(manifest, manifest_path, canonical_receipt_path)
        receipt = json.loads(canonical_receipt_path.read_text(encoding="utf-8-sig"))
        if receipt.get("schema_version") != 1:
            raise ValueError("canonical RR receipt schema_version differs")
        if receipt.get("role") != CANONICAL_RR_RECEIPT_ROLE:
            raise ValueError("canonical RR receipt role differs")
        if receipt.get("status") != "success":
            raise ValueError("canonical RR receipt is not successful")
        if receipt.get("particle_count") != 1000:
            raise ValueError("canonical RR receipt particle_count differs")
        if receipt.get("old_source_files_modified") is not False:
            raise ValueError("canonical RR receipt source immutability differs")
        if str(receipt.get("derived_checkpoint_sha256", "")).upper() != file_sha256(
            checkpoint_path
        ):
            raise ValueError("canonical RR receipt does not bind checkpoint SHA-256")
        evidence_type = "published_canonical_rr_receipt"
        source.update(
            {
                "canonical_receipt_path": str(canonical_receipt_path),
                "canonical_receipt_sha256": file_sha256(canonical_receipt_path),
                "canonical_receipt_role": receipt["role"],
            }
        )
    source["evidence_type"] = evidence_type
    return source


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


def fwhm_factorial_effects(values: dict[str, float]) -> dict[str, float]:
    """Return FWHM main effects and the complete difference-in-differences."""
    return {
        "stage1_ideal_main": (
            values["IR"] + values["II"] - values["RR"] - values["RI"]
        ) / 2,
        "stage2_ideal_main": (
            values["RI"] + values["II"] - values["RR"] - values["IR"]
        ) / 2,
        "stage1_stage2_interaction_complete_did": (
            values["II"] + values["RR"] - values["IR"] - values["RI"]
        ),
    }


def checkpoint_peak_metrics(
    frames: dict[str, pd.DataFrame], mass_amu: float = 100.0,
) -> dict[str, dict[str, object]]:
    """Apply the canonical peak API to every arm at every checkpoint."""
    result: dict[str, dict[str, object]] = {}
    for event in EVENTS:
        arms: dict[str, dict[str, object]] = {}
        for arm in ARMS:
            peak, _ = compute_peak_metrics(
                _event(frames[arm], event).to_numpy(), mass_amu
            )
            arms[arm] = {key: peak[key] for key in PEAK_FIELDS}
        fwhm = {
            arm: float(arms[arm]["direct_fwhm_tof_ns"])
            for arm in ARMS
        }
        result[event] = {
            "arms": arms,
            "fwhm_factorial_effects_ns": fwhm_factorial_effects(fwhm),
        }
    return result


def analyze(
    paths: dict[str, Path],
    manifests: dict[str, Path],
    output: Path,
    canonical_receipts: dict[str, Path] | None = None,
) -> dict[str, object]:
    canonical_receipts = canonical_receipts or {}
    source = {
        arm: bind_checkpoint_evidence(
            arm, paths[arm], manifests[arm], canonical_receipts.get(arm)
        )
        for arm in ARMS
    }
    frames = {arm: _load(paths[arm]) for arm in ARMS}
    ids = {arm: set(frames[arm].particle_id) for arm in ARMS}
    expected = set(range(1, 1001))
    if any(value != expected for value in ids.values()):
        raise ValueError("all arms must contain exactly particle IDs 1..1000")
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
    checkpoint_peaks = checkpoint_peak_metrics(frames)
    peaks = {
        arm: {
            key: value
            for key, value in checkpoint_peaks["detector_crossing"]["arms"][arm].items()
            if key != "particles"
        }
        for arm in ARMS
    }
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
              "checkpoint_peak_metrics": checkpoint_peaks,
              "fwhm_effect_scale": {
                  "main_effects": "average high-minus-low direct FWHM in ns",
                  "interaction": "complete difference-in-differences II+RR-IR-RI in ns; not divided by two",
              },
              "detector_peak_metrics": peaks, "bootstrap": {"status": "not_computed", "reason": "existing bootstrap is single-arm resolution-only; this paired factorial report remains descriptive"},
              "tables": ["checkpoint_arm_statistics.csv", "checkpoint_paired_deltas.csv"], "diagnostic_figure": "stage_field_2x2_diagnostics.png"}
    (output / "stage_field_2x2_attribution.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    for arm in ARMS:
        p.add_argument(f"--{arm.lower()}-checkpoints", required=True, type=Path); p.add_argument(f"--{arm.lower()}-manifest", required=True, type=Path)
    p.add_argument("--rr-canonical-receipt", type=Path)
    p.add_argument("--output", required=True, type=Path); a = p.parse_args()
    receipts = {"RR": a.rr_canonical_receipt} if a.rr_canonical_receipt else None
    result = analyze({arm: getattr(a, f"{arm.lower()}_checkpoints") for arm in ARMS}, {arm: getattr(a, f"{arm.lower()}_manifest") for arm in ARMS}, a.output, receipts)
    print(f"STAGE_FIELD_2X2=PASS PARTICLES={result['paired_particle_count']} FIRST={result['first_nonzero_paired_divergence_event']}")


if __name__ == "__main__": main()
