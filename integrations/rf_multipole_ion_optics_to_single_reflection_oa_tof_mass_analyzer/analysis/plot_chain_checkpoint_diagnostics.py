"""Render the governed six-panel RF-multipole to oaTOF checkpoint diagnostic."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_shared_pulse_geometry_snapshot import (
    add_accelerator_geometry_outlines,
    add_connection_geometry_outlines,
    resolved_chain_geometry,
)


CAPABILITY_ID = "rf_oatof_chain_checkpoint_six_panel_v1"
FRAME_ID = "oatof_global"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def _read(path: Path, role: str, columns: set[str]) -> pd.DataFrame:
    data = pd.read_csv(path)
    missing = sorted(columns - set(data.columns))
    if missing:
        raise ValueError(f"{role} is missing columns: {', '.join(missing)}")
    if data.empty or data["particle_id"].duplicated().any():
        raise ValueError(f"{role} must contain unique nonempty particle IDs")
    return data


def _require_frame(data: pd.DataFrame, role: str) -> None:
    if "frame_id" in data and not data["frame_id"].eq(FRAME_ID).all():
        raise ValueError(f"{role} frame differs from {FRAME_ID}")


def _map_downstream(downstream: pd.DataFrame, row_map: pd.DataFrame) -> pd.DataFrame:
    mapping = row_map[["solver_row_index", "particle_id"]].rename(
        columns={"solver_row_index": "Ion"}
    )
    result = downstream.merge(mapping, on="Ion", how="left", validate="one_to_one")
    if result["particle_id"].isna().any():
        raise ValueError("downstream state contains an unmapped solver row")
    result["particle_id"] = result["particle_id"].astype(int)
    return result


def _scatter(ax, data: pd.DataFrame, x: str, y: str, *, label: str,
             color: str, marker: str, size: float = 17.0) -> None:
    if not data.empty:
        ax.scatter(data[x], data[y], s=size, color=color, marker=marker,
                   alpha=0.78, linewidths=0.45, label=label, zorder=5)


def build_figure(
    *, label: str, rf_exit: pd.DataFrame, oatof_entry: pd.DataFrame,
    pulse: pd.DataFrame, terminal: pd.DataFrame, local_exit: pd.DataFrame,
    downstream: pd.DataFrame, geometry: dict[str, Any], pulse_time_us: float,
) -> tuple[plt.Figure, dict[str, Any]]:
    ids = set(rf_exit["particle_id"].astype(int))
    entry_ids = set(oatof_entry.loc[oatof_entry["status"].eq("transmitted"), "particle_id"].astype(int))
    pulse_ids = set(pulse["particle_id"].astype(int))
    exit_ids = set(local_exit["particle_id"].astype(int))
    hit_rows = downstream.loc[downstream["Hit"].astype(str).str.lower().eq("true")].copy()
    hit_ids = set(hit_rows["particle_id"].astype(int))
    if not hit_ids <= exit_ids <= pulse_ids <= entry_ids <= ids:
        raise ValueError("checkpoint particle memberships are not nested")

    port_loss = terminal.loc[terminal["oatof_entry_status"].eq("wall_loss")]
    pre_pulse_loss = terminal.loc[
        terminal["oatof_entry_status"].eq("transmitted")
        & terminal["active_at_pulse"].eq(0)
    ]
    active_exit_loss = terminal.loc[
        terminal["active_at_pulse"].eq(1)
        & terminal["local_accelerator_exit"].eq(0)
    ]

    fig, axes = plt.subplots(2, 3, figsize=(15.4, 9.2), constrained_layout=True)
    ax_a, ax_b, ax_c, ax_d, ax_e, ax_f = axes.flat
    add_connection_geometry_outlines(ax_a, geometry, "xz")
    add_accelerator_geometry_outlines(ax_a, geometry, "x")
    _scatter(ax_a, rf_exit, "position_x_mm", "position_z_mm", label="RF exit",
             color="#2166ac", marker="o")
    _scatter(ax_a, oatof_entry, "position_x_mm", "position_z_mm", label="oaTOF entry",
             color="#67a9cf", marker="^")
    _scatter(ax_a, pulse, "x_mm", "z_mm", label="pulse left limit",
             color="#fdae61", marker="s")
    _scatter(ax_a, local_exit, "position_x_mm", "position_z_mm", label="grid2 exit",
             color="#1b9e77", marker="D")
    ax_a.set(xlabel="oaTOF global x (mm)", ylabel="oaTOF global z (mm)",
             title="A  Registered chain checkpoints (x–z)")

    add_connection_geometry_outlines(ax_b, geometry, "yz")
    add_accelerator_geometry_outlines(ax_b, geometry, "y")
    _scatter(ax_b, pulse, "y_mm", "z_mm", label="pulse active",
             color="#fdae61", marker="s")
    _scatter(ax_b, local_exit, "position_y_mm", "position_z_mm", label="grid2 exit",
             color="#1b9e77", marker="D")
    _scatter(ax_b, port_loss, "y_mm", "z_mm", label="port-wall loss",
             color="#d95f02", marker="x")
    _scatter(ax_b, pre_pulse_loss, "y_mm", "z_mm", label="pre-pulse loss",
             color="#252525", marker="X")
    ax_b.set(xlabel="oaTOF global y (mm)", ylabel="oaTOF global z (mm)",
             title="B  Physical aperture and losses (y–z)")

    if not hit_rows.empty:
        detector_x = hit_rows["XMm"] - float(geometry["detector_center_x"])
        detector_y = hit_rows["YMm"] - float(geometry["detector_center_y"])
        ax_c.scatter(detector_x, detector_y, s=30, marker="*",
                     color="#1b9e77", label="detector hit")
    detector_radius = float(geometry["physical_detector_radius"])
    circle = plt.Circle((0.0, 0.0), detector_radius, fill=False,
                        linestyle="--", color="#756bb1", label="active radius")
    ax_c.add_patch(circle)
    ax_c.set_aspect("equal", adjustable="box")
    detector_limit = detector_radius * 1.05
    ax_c.set(xlim=(-detector_limit, detector_limit),
             ylim=(-detector_limit, detector_limit),
             xlabel="x − detector center (mm)",
             ylabel="y − detector center (mm)",
             title=f"C  Downstream detector state ({len(hit_ids)}/{len(exit_ids)})")

    active = pulse.merge(
        oatof_entry[["particle_id", "instrument_time_us", "position_x_mm",
                     "position_y_mm", "position_z_mm", "velocity_x_m_s",
                     "velocity_y_m_s", "velocity_z_m_s"]],
        on="particle_id", validate="one_to_one", suffixes=("", "_entry"),
    )
    dt_s = (active["instrument_time_us"] - active["instrument_time_us_entry"]) * 1e-6
    for axis, color, marker in (("x", "#2166ac", "o"), ("y", "#e6ab02", "s"), ("z", "#1b9e77", "^")):
        predicted = active[f"position_{axis}_mm"] + active[f"velocity_{axis}_m_s"] * dt_s * 1e3
        residual = active[f"{axis}_mm"] - predicted
        ax_d.scatter(active["particle_id"], residual, s=17, color=color,
                     marker=marker, label=f"Δ{axis}")
    ax_d.axhline(0.0, color="#777777", linewidth=0.7)
    ax_d.set(xlabel="particle ID", ylabel="COMSOL pulse − ballistic prediction (mm)",
             title=f"D  Same-ID pulse residual (N={len(active)})")

    outcome_counts = [len(hit_ids), len(exit_ids - hit_ids), len(active_exit_loss),
                      len(pre_pulse_loss), len(port_loss)]
    outcome_labels = ["detector hit", "grid2 exit; no hit", "active grid2 loss",
                      "pre-pulse loss", "port-wall loss"]
    ax_e.barh(outcome_labels, outcome_counts,
              color=["#1b9e77", "#67a9cf", "#de2d26", "#252525", "#d95f02"])
    for index, value in enumerate(outcome_counts):
        ax_e.text(value + max(len(ids), 1) * 0.01, index, f"{value}/{len(ids)}", va="center")
    ax_e.set(xlabel="mutually exclusive particles", title="E  Exhaustive final outcomes")

    stage_counts = [len(ids), len(entry_ids), len(pulse_ids), len(exit_ids), len(hit_ids)]
    stage_labels = ["RF exit", "oaTOF entry", "pulse active", "grid2 exit", "detector hit"]
    ax_f.plot(range(5), stage_counts, marker="o", color="#2b8cbe")
    ax_f.set_xticks(range(5), stage_labels, rotation=25, ha="right")
    ax_f.set(ylabel=f"nested membership (of N={len(ids)})",
             title="F  Stage membership (not additive)", ylim=(0, max(stage_counts) * 1.1))
    for index, value in enumerate(stage_counts):
        ax_f.text(index, value, f"{value}/{len(ids)}", ha="center", va="bottom", fontsize=8)

    for ax in axes.flat:
        ax.grid(alpha=0.18)
    handles, legend_labels = ax_a.get_legend_handles_labels()
    if handles:
        fig.legend(handles, legend_labels, loc="outside lower center", ncol=4,
                   frameon=False, fontsize=8)
    fig.suptitle(
        f"{label}: RF exit → oaTOF entry → shared pulse → grid2 exit → detector\n"
        f"pulse t={pulse_time_us:.6f} µs; frame={FRAME_ID}; capability={CAPABILITY_ID}",
        fontsize=12,
    )
    return fig, {
        "source_particles": len(ids), "oatof_entry": len(entry_ids),
        "active_at_pulse": len(pulse_ids), "grid2_exit": len(exit_ids),
        "detector_hit": len(hit_ids), "event_plane_z_mm": float(geometry["grid2_z"]),
    }


def publish_checkpoint_figure(
    *,
    label: str,
    rf_exit_path: Path,
    oatof_entry_path: Path,
    pulse_state_path: Path,
    terminal_census_path: Path,
    local_exit_path: Path,
    row_map_path: Path,
    downstream_path: Path,
    baseline_path: Path,
    joint_path: Path,
    resolved_connection_path: Path,
    rf_resolved_design_path: Path,
    output_path: Path,
    metadata_path: Path,
) -> dict[str, Any]:
    """Validate canonical checkpoints and atomically publish one diagnostic."""
    rf_exit = _read(rf_exit_path, "RF exit", {
        "particle_id", "frame_id", "instrument_time_us", "position_x_mm",
        "position_y_mm", "position_z_mm",
    })
    entry = _read(oatof_entry_path, "oaTOF entry", {
        "particle_id", "frame_id", "status", "instrument_time_us",
        "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s",
        "velocity_y_m_s", "velocity_z_m_s",
    })
    pulse = _read(pulse_state_path, "pulse state", {
        "particle_id", "frame_id", "instrument_time_us", "x_mm", "y_mm",
        "z_mm",
    })
    terminal = _read(terminal_census_path, "terminal census", {
        "particle_id", "frame_id", "oatof_entry_status", "active_at_pulse",
        "local_accelerator_exit", "y_mm", "z_mm",
    })
    local_exit = _read(local_exit_path, "grid2 exit", {
        "particle_id", "frame_id", "position_x_mm", "position_y_mm",
        "position_z_mm",
    })
    for role, data in (
        ("RF exit", rf_exit), ("oaTOF entry", entry), ("pulse", pulse),
        ("terminal", terminal), ("grid2 exit", local_exit),
    ):
        _require_frame(data, role)
    downstream = _map_downstream(
        pd.read_csv(downstream_path), pd.read_csv(row_map_path)
    )
    baseline, joint = _load_json(baseline_path), _load_json(joint_path)
    geometry = resolved_chain_geometry(
        baseline,
        joint,
        _load_json(resolved_connection_path),
        _load_json(rf_resolved_design_path),
    )
    plane = float(geometry["grid2_z"])
    if not np.allclose(local_exit["position_z_mm"], plane, rtol=0, atol=1e-8):
        raise ValueError(
            "local_accelerator_exit is not sampled at the canonical grid2 plane"
        )
    event = joint.get("diagnostic_events", {}).get(
        "local_accelerator_exit", {}
    )
    if (
        event.get("physical_surface_role") != "accelerator_grid2"
        or float(event.get("sampling_offset_mm", math.nan)) != 0.0
    ):
        raise ValueError(
            "joint contract does not bind the canonical grid2 diagnostic plane"
        )
    pulse_times = pulse["instrument_time_us"].unique()
    if len(pulse_times) != 1:
        raise ValueError("pulse state must use one instrument time")
    figure, census = build_figure(
        label=label,
        rf_exit=rf_exit,
        oatof_entry=entry,
        pulse=pulse,
        terminal=terminal,
        local_exit=local_exit,
        downstream=downstream,
        geometry=geometry,
        pulse_time_us=float(pulse_times[0]),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_figure = output_path.with_name(f".{output_path.name}.pending")
    try:
        figure.savefig(
            pending_figure, format="png", dpi=220, facecolor="white"
        )
    finally:
        plt.close(figure)
    os.replace(pending_figure, output_path)
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_chain_checkpoint_figure_manifest",
        "capability_id": CAPABILITY_ID,
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "frame_id": FRAME_ID,
        "event_plane": "accelerator_grid2",
        "display_transforms": {
            "detector_panel": "XMm/YMm minus canonical detector center"
        },
        "census": census,
        "figure": str(output_path.resolve()),
    }
    pending_metadata = metadata_path.with_name(f".{metadata_path.name}.pending")
    pending_metadata.parent.mkdir(parents=True, exist_ok=True)
    pending_metadata.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(pending_metadata, metadata_path)
    return census


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rf-exit", "oatof-entry", "pulse-state", "terminal-census",
                 "local-exit", "row-map", "downstream", "baseline", "joint",
                 "resolved-connection", "rf-resolved-design", "output", "metadata"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    census = publish_checkpoint_figure(
        label=args.label,
        rf_exit_path=args.rf_exit,
        oatof_entry_path=args.oatof_entry,
        pulse_state_path=args.pulse_state,
        terminal_census_path=args.terminal_census,
        local_exit_path=args.local_exit,
        row_map_path=args.row_map,
        downstream_path=args.downstream,
        baseline_path=args.baseline,
        joint_path=args.joint,
        resolved_connection_path=args.resolved_connection,
        rf_resolved_design_path=args.rf_resolved_design,
        output_path=args.output,
        metadata_path=args.metadata,
    )
    print(f"RF_OATOF_CHECKPOINT_FIGURE=PASS GRID2_EXIT={census['grid2_exit']}/{census['source_particles']}")


if __name__ == "__main__":
    main()
