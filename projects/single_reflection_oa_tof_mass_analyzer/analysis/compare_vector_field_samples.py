"""Compare COMSOL and SIMION vector fields at identical coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common.analysis.field_comparison import (
    merge_complete_samples,
    normalized_rms_difference_pct,
)


_TRAJECTORY_KEYS = ["particle_id", "time_us", "x_mm", "y_mm", "z_mm"]
_STATIC_KEYS = ["point_id", "x_mm", "y_mm", "z_mm"]
_FIELD_COLUMNS = {f"{component}_V_per_m" for component in ("Ex", "Ey", "Ez")}


def _sample_contract(comsol: pd.DataFrame, simion: pd.DataFrame) -> tuple[str, list[str]]:
    """Select one explicit sample contract; never mix static points and paths."""
    frames = (comsol, simion)
    static_presence = [set(_STATIC_KEYS).issubset(frame.columns) for frame in frames]
    trajectory_presence = [set(_TRAJECTORY_KEYS).issubset(frame.columns) for frame in frames]
    static = all(static_presence)
    trajectory = all(trajectory_presence)
    if static and not trajectory:
        return "static_point_id", _STATIC_KEYS
    if trajectory and not static:
        return "trajectory", _TRAJECTORY_KEYS
    if any(static_presence) or any(trajectory_presence):
        raise ValueError("COMSOL and SIMION vector samples use different contracts")
    raise ValueError("vector samples require either the static point_id or trajectory key contract")


def _require_static_samples(frame: pd.DataFrame, label: str) -> None:
    identifiers = pd.to_numeric(frame["point_id"], errors="raise")
    if (identifiers.empty or identifiers.duplicated().any()
            or any(isinstance(value, (bool, np.bool_)) for value in identifiers)
            or not np.isfinite(identifiers).all() or (identifiers < 0).any()
            or (identifiers != np.floor(identifiers)).any()):
        raise ValueError(f"{label} static point_id must be unique nonnegative integers")
    columns = ["x_mm", "y_mm", "z_mm", *sorted(_FIELD_COLUMNS)]
    values = frame[columns].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{label} static coordinates and fields must be finite")


def _require_field_columns(frame: pd.DataFrame, label: str) -> None:
    missing = sorted(_FIELD_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"{label} misses vector field columns: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("comsol", type=Path)
    parser.add_argument("simion", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    c = pd.read_csv(args.comsol, float_precision="round_trip")
    s = pd.read_csv(args.simion, float_precision="round_trip")
    _require_field_columns(c, "COMSOL")
    _require_field_columns(s, "SIMION")
    sample_contract, keys = _sample_contract(c, s)
    if sample_contract == "static_point_id":
        _require_static_samples(c, "COMSOL")
        _require_static_samples(s, "SIMION")
    merged = merge_complete_samples(
        c,
        s,
        keys=keys,
        left_label="COMSOL",
        right_label="SIMION",
        suffixes=("_COMSOL", "_SIMION"),
    )
    metrics: dict[str, object] = {
        "status": "PASS" if sample_contract == "trajectory" else "COMPARISON_COMPLETE",
        "sample_contract": sample_contract,
        "sample_points": int(len(merged)),
        "aggregate": {},
    }
    if sample_contract == "static_point_id":
        metrics["claim_limit"] = "No numerical-equivalence decision: no approved acceptance tolerance was supplied."
        metrics["source_files"] = {"COMSOL": str(args.comsol.resolve()), "SIMION": str(args.simion.resolve())}
        metrics["display"] = {"x": "point_id", "field_unit": "V/mm", "selection": "all common points; sorted by point_id"}
    else:
        metrics["particles"] = {}
    for component in ("Ex", "Ey", "Ez"):
        cv = merged[f"{component}_V_per_m_COMSOL"].to_numpy()
        sv = merged[f"{component}_V_per_m_SIMION"].to_numpy()
        delta = sv - cv
        normalized = normalized_rms_difference_pct(cv, sv)
        metrics["aggregate"][component] = {
            "COMSOL_rms_V_per_m": normalized["reference_rms_V_per_m"],
            "SIMION_rms_V_per_m": normalized["values_rms_V_per_m"],
            "difference_rms_V_per_m": normalized["difference_rms_V_per_m"],
            "difference_relative_to_COMSOL_rms_pct": normalized["relative_to_reference_rms_pct"],
            "difference_symmetric_scale_pct": normalized["symmetric_scale_pct"],
            "difference_mean_V_per_m": float(np.mean(delta)),
            "difference_max_abs_V_per_m": float(np.max(np.abs(delta))),
        }
    identifiers = (
        [None]
        if sample_contract == "static_point_id"
        else sorted(merged["particle_id"].unique())
    )
    figure, axes = plt.subplots(
        3,
        len(identifiers),
        figsize=(8 if sample_contract == "static_point_id" else 5 * len(identifiers), 11),
        squeeze=False,
        constrained_layout=True,
    )
    for column, identifier in enumerate(identifiers):
        if sample_contract == "static_point_id":
            group = merged.sort_values("point_id")
            x_values = group["point_id"].to_numpy()
            title_prefix, xlabel = f"Static samples (N={len(group)})", "point ID"
        else:
            group = merged[merged["particle_id"] == identifier].sort_values("z_mm")
            x_values = group["z_mm"].to_numpy()
            title_prefix, xlabel = f"Particle {identifier}", "z [mm]"
        component_metrics = {}
        for row, component in enumerate(("Ex", "Ey", "Ez")):
            cv = group[f"{component}_V_per_m_COMSOL"].to_numpy()
            sv = group[f"{component}_V_per_m_SIMION"].to_numpy()
            delta = sv - cv
            component_metrics[component] = {
                "COMSOL_rms_V_per_m": float(np.sqrt(np.mean(cv**2))),
                "SIMION_rms_V_per_m": float(np.sqrt(np.mean(sv**2))),
                "difference_rms_V_per_m": float(np.sqrt(np.mean(delta**2))),
                "difference_mean_V_per_m": float(np.mean(delta)),
                "difference_max_abs_V_per_m": float(np.max(np.abs(delta))),
            }
            if sample_contract == "static_point_id":
                axes[row, column].plot(x_values, cv / 1e3, marker="o", linestyle="none", label="COMSOL")
                axes[row, column].plot(x_values, sv / 1e3, marker="x", linestyle="none", label="SIMION")
            else:
                axes[row, column].plot(x_values, cv / 1e3, marker="o", label="COMSOL")
                axes[row, column].plot(x_values, sv / 1e3, marker="x", label="SIMION")
            axes[row, column].set(
                title=f"{title_prefix}: {component}",
                xlabel=xlabel,
                ylabel=f"{component} [V/mm]",
            )
            axes[row, column].grid(True, alpha=0.3)
            axes[row, column].legend()
        if sample_contract == "trajectory":
            metrics["particles"][str(int(identifier))] = component_metrics
    args.output.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output / "accelerator_vector_field_comparison.csv", index=False)
    (args.output / "accelerator_vector_field_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    metadata = (
        {"Description": json.dumps({"source_files": metrics["source_files"], "claim_limit": metrics["claim_limit"]})}
        if sample_contract == "static_point_id" else None
    )
    figure.savefig(args.output / "accelerator_vector_field_comparison.png", dpi=220, facecolor="white", metadata=metadata)
    plt.close(figure)
    print(f"VECTOR_FIELD_COMPARISON_STATUS={metrics['status']}")


if __name__ == "__main__":
    main()
