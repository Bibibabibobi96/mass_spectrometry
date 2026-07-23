"""Compare the sparse S1 pulse-on capture state with the mass-matched oaTOF ideal source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

try:
    from plot_s1_pulse_geometry_snapshot import accelerator_geometry, classify_snapshot
except ModuleNotFoundError:
    from projects.rf_quadrupole_collision_cooling.analysis.plot_s1_pulse_geometry_snapshot import (
        accelerator_geometry,
        classify_snapshot,
    )


ATOMIC_MASS_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19


def read_ideal_ion(path: Path) -> pd.DataFrame:
    names = ["birth_time_us", "mass_amu", "charge_state", "x_mm", "y_mm", "z_mm",
             "azimuth_deg", "elevation_deg", "energy_eV", "cwf", "color"]
    data = pd.read_csv(path, names=names)
    if data.empty or data.shape[1] != 11:
        raise ValueError("oaTOF ideal ION reference must contain 11 columns")
    speed = np.sqrt(2 * data["energy_eV"] * ELEMENTARY_CHARGE_C
                    / (data["mass_amu"] * ATOMIC_MASS_KG))
    data["vx_m_s"] = speed
    data["vy_m_s"] = 0.0
    data["vz_m_s"] = 0.0
    return data


def enrich_capture(capture: pd.DataFrame, entry: pd.DataFrame) -> pd.DataFrame:
    required = {"particle_id", "instrument_time_us", "x_mm", "y_mm", "z_mm",
                "vx_m_s", "vy_m_s", "vz_m_s", "inside_oatof_ideal_reference_volume"}
    if not required.issubset(capture.columns):
        raise ValueError("pulse capture table is missing required sparse-state columns")
    source = entry[["particle_id", "instrument_time_us", "mass_amu", "charge_state"]].rename(
        columns={"instrument_time_us": "entry_instrument_time_us"})
    result = capture.merge(source, on="particle_id", how="left", validate="one_to_one")
    if result[["mass_amu", "charge_state"]].isna().any().any():
        raise ValueError("pulse capture particle IDs are not a subset of the canonical entry table")
    result["inside_reference"] = pd.to_numeric(
        result["inside_oatof_ideal_reference_volume"], errors="raise").astype(bool)
    result["storage_duration_us"] = result["instrument_time_us"] - result["entry_instrument_time_us"]
    result["speed_m_s"] = np.sqrt(result["vx_m_s"] ** 2 + result["vy_m_s"] ** 2 + result["vz_m_s"] ** 2)
    result["energy_eV"] = (0.5 * result["mass_amu"] * ATOMIC_MASS_KG * result["speed_m_s"] ** 2
                           / ELEMENTARY_CHARGE_C)
    result["theta_y_deg"] = np.degrees(np.arctan2(result["vy_m_s"], result["vx_m_s"]))
    result["theta_z_deg"] = np.degrees(
        np.arctan2(result["vz_m_s"], np.hypot(result["vx_m_s"], result["vy_m_s"])))
    result["angle_deg"] = np.degrees(
        np.arctan2(np.hypot(result["vy_m_s"], result["vz_m_s"]), result["vx_m_s"]))
    return result


def describe(data: pd.DataFrame) -> dict[str, float | int]:
    return {
        "particles": int(len(data)),
        "energy_mean_eV": float(data["energy_eV"].mean()),
        "energy_sample_std_eV": float(data["energy_eV"].std(ddof=1)),
        "speed_mean_m_s": float(data["speed_m_s"].mean()),
        "direction_angle_rms_deg": float(np.sqrt(np.mean(data["angle_deg"] ** 2))),
    }


def compare(capture_path: Path, entry_path: Path, local_path: Path, ideal_path: Path,
            baseline_path: Path, joint_path: Path, figure_path: Path,
            summary_path: Path) -> dict[str, object]:
    capture_raw = pd.read_csv(capture_path)
    entry = pd.read_csv(entry_path)
    local = pd.read_csv(local_path)
    ideal = read_ideal_ion(ideal_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    joint = json.loads(joint_path.read_text(encoding="utf-8"))
    snapshot = classify_snapshot(enrich_capture(capture_raw, entry), local,
                                 accelerator_geometry(baseline, joint))
    frozen_port_loss = snapshot[snapshot["frozen_port_loss_before_pulse"]]
    frozen_accelerator_loss = snapshot[
        snapshot["frozen_accelerator_loss_before_pulse"]]
    capture = snapshot[snapshot["active_at_pulse"]].copy()
    accepted_ids = set(local.loc[local["event"] != "geometric_reject", "particle_id"])
    if len(entry) != 100 or len(local) != 100 or len(ideal) != 100:
        raise ValueError("capture comparison requires deterministic N=100 source and reference groups")
    if not set(snapshot["particle_id"]).issubset(accepted_ids):
        raise ValueError("capture table contains a geometrically rejected particle")
    if snapshot.empty or snapshot["instrument_time_us"].nunique() != 1:
        raise ValueError("capture table must be a non-empty snapshot at one shared pulse time")
    identities = snapshot[["frame_id", "clock_epoch_id"]].drop_duplicates()
    if len(identities) != 1 or identities.iloc[0].astype(str).str.strip().eq("").any():
        raise ValueError("capture comparison requires one frame and clock epoch")
    frame_id = str(identities.iloc[0]["frame_id"])
    clock_epoch_id = str(identities.iloc[0]["clock_epoch_id"])
    source = baseline["particle_source"]
    expected_inside = np.logical_and.reduce([
        (snapshot[f"{axis}_mm"] - float(source[f"center_{axis}_mm"])).abs().to_numpy()
        <= float(source[f"size_{axis}_mm"]) / 2 + 1e-12 for axis in "xyz"
    ])
    if not np.array_equal(expected_inside, snapshot["inside_reference"].to_numpy()):
        raise ValueError("capture reference-volume flag disagrees with the oaTOF baseline")
    species = capture[["mass_amu", "charge_state"]].drop_duplicates()
    if len(species) != 1 or not np.allclose(ideal["mass_amu"], species.iloc[0]["mass_amu"]):
        raise ValueError("oaTOF ideal reference is not mass matched")
    ideal["speed_m_s"] = np.sqrt(ideal["vx_m_s"] ** 2 + ideal["vy_m_s"] ** 2 + ideal["vz_m_s"] ** 2)
    ideal["angle_deg"] = 0.0
    inside = capture[capture["inside_reference"]]
    pulse_time = float(snapshot["instrument_time_us"].iloc[0])
    centers = {axis: float(source[f"center_{axis}_mm"]) for axis in "xyz"}
    for data in (capture, ideal):
        for axis in "xyz":
            data[f"d{axis}_mm"] = data[f"{axis}_mm"] - centers[axis]

    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    colors = np.where(capture["inside_reference"], "#238b45", "#e6550d")
    axes[0, 0].scatter(capture["dx_mm"], capture["dz_mm"], c=colors, s=29, alpha=0.8)
    axes[0, 0].add_patch(Rectangle((-0.5, -0.5), 1, 1, fill=False, color="#756bb1", lw=1.8))
    axes[0, 0].set(xlabel="centered x (mm)", ylabel="centered z (mm)", title="A  Pulse-on x-z capture state")
    axes[0, 1].scatter(capture["dx_mm"], capture["dy_mm"], c=colors, s=29, alpha=0.8)
    axes[0, 1].add_patch(Rectangle((-0.5, -0.5), 1, 1, fill=False, color="#756bb1", lw=1.8))
    axes[0, 1].set(xlabel="centered x (mm)", ylabel="centered y (mm)", title="B  Pulse-on x-y capture state")
    bins = np.linspace(min(capture["energy_eV"].min(), ideal["energy_eV"].min()),
                       max(capture["energy_eV"].max(), ideal["energy_eV"].max()), 24)
    axes[0, 2].hist(capture["energy_eV"], bins=bins, histtype="step", lw=2, color="#238b45", label="captured alive")
    axes[0, 2].hist(ideal["energy_eV"], bins=bins, histtype="step", lw=2, color="#756bb1", label="oa ideal")
    axes[0, 2].set(xlabel="kinetic energy (eV)", ylabel="particles", title="C  Energy at pulse onset")
    axes[0, 2].legend(fontsize=8)
    axes[1, 0].scatter(capture["theta_y_deg"], capture["theta_z_deg"], c=colors, s=29, alpha=0.8)
    axes[1, 0].scatter([0], [0], marker="+", s=100, lw=2.5, c="#756bb1")
    axes[1, 0].set(xlabel="theta_y (deg)", ylabel="theta_z (deg)", title="D  Direction at pulse onset")
    axes[1, 1].scatter(capture["storage_duration_us"], capture["dx_mm"], c=colors, s=29, alpha=0.8)
    axes[1, 1].axhspan(-0.5, 0.5, color="#756bb1", alpha=0.08)
    axes[1, 1].set(xlabel="time since entry (us)", ylabel="centered x (mm)", title="E  Shared pulse versus arrival order")
    axes[1, 2].scatter(capture["dx_mm"], capture["vx_m_s"], c=colors, s=29, alpha=0.8)
    axes[1, 2].set(xlabel="centered x (mm)", ylabel="vx (m/s)", title="F  Longitudinal phase space")
    for ax in axes.flat:
        ax.grid(alpha=0.22)
    fig.suptitle(
        f"RF-to-oaTOF state immediately before the shared pulse ({pulse_time:.6f} µs)\n"
        f"frame={frame_id}; clock epoch={clock_epoch_id}",
        fontsize=15,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, format="png", dpi=190)
    plt.close(fig)

    result = {
        "schema_version": 1,
        "role": "rf_s1_pulse_capture_vs_mass_matched_oatof_ideal_source",
        "status": "PASS",
        "pulse_instrument_time_us": pulse_time,
        "frame_id": frame_id,
        "clock_epoch_id": clock_epoch_id,
        "state_time_semantics": "left_limit_immediately_before_pulse_t_pulse_minus",
        "geometric_port_accepted": len(accepted_ids),
        "snapshot_rows_including_frozen_terminal_coordinates": int(len(snapshot)),
        "frozen_port_losses_before_pulse": int(len(frozen_port_loss)),
        "frozen_accelerator_losses_before_pulse": int(len(frozen_accelerator_loss)),
        "alive_at_pulse": int(len(capture)),
        "pre_pulse_dynamic_loss": int(len(accepted_ids) - len(capture)),
        "inside_oatof_ideal_reference_volume": int(len(inside)),
        "inside_reference_fraction_of_alive": float(len(inside) / len(capture)),
        "storage_duration_us": {"min": float(capture["storage_duration_us"].min()),
                                "max": float(capture["storage_duration_us"].max()),
                                "mean": float(capture["storage_duration_us"].mean())},
        "groups": {"pulse_alive_all": describe(capture),
                   "pulse_inside_ideal_reference_volume": describe(inside) if len(inside) else None,
                   "oatof_ideal_mass_matched": describe(ideal)},
        "pulse_alive_minus_ideal": {
            "energy_mean_difference_eV": float(capture["energy_eV"].mean() - ideal["energy_eV"].mean()),
            "speed_mean_difference_m_s": float(capture["speed_m_s"].mean() - ideal["speed_m_s"].mean()),
            "direction_angle_rms_difference_deg": float(np.sqrt(np.mean(capture["angle_deg"] ** 2))),
        },
        "equivalent_capture_time_state_available": True,
        "ideal_volume_is_diagnostic_not_hard_acceptance": True,
        "direct_formal_source_equivalence_claim_allowed": False,
        "dense_trajectories_used": False,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--ideal-ion", type=Path, required=True)
    parser.add_argument("--oatof-baseline", type=Path, required=True)
    parser.add_argument("--joint-contract", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.capture, args.entry, args.local, args.ideal_ion, args.oatof_baseline,
                     args.joint_contract, args.figure, args.summary)
    print(f"S1_CAPTURE_IDEAL_COMPARISON=PASS ALIVE={result['alive_at_pulse']} "
          f"INSIDE_REFERENCE={result['inside_oatof_ideal_reference_volume']}")


if __name__ == "__main__":
    main()
