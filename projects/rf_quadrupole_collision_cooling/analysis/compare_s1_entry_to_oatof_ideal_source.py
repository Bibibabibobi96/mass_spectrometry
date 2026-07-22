"""Compare RF port-selected entry states with a mass-matched oaTOF ideal source."""

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


ATOMIC_MASS_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19


def read_ideal_ion(path: Path) -> pd.DataFrame:
    columns = ["birth_time_us", "mass_amu", "charge_state", "x_mm", "y_mm", "z_mm",
               "azimuth_deg", "elevation_deg", "energy_eV", "cwf", "color"]
    data = pd.read_csv(path, names=columns)
    if data.empty or data.shape[1] != 11:
        raise ValueError("oaTOF ideal ION reference must contain 11 columns")
    if not np.allclose(data["azimuth_deg"], 0) or not np.allclose(data["elevation_deg"], 0):
        raise ValueError("oaTOF ideal source reference must point along its declared +x direction")
    speed = np.sqrt(
        2 * data["energy_eV"].to_numpy() * ELEMENTARY_CHARGE_C
        / (data["mass_amu"].to_numpy() * ATOMIC_MASS_KG)
    )
    data["vx_m_s"], data["vy_m_s"], data["vz_m_s"] = speed, 0.0, 0.0
    return data


def enrich_rf(entry: pd.DataFrame, local: pd.DataFrame) -> pd.DataFrame:
    outcome = local.set_index("particle_id")["event"]
    result = entry.copy()
    result["inside_port"] = result["particle_id"].map(outcome).ne("geometric_reject")
    result["energy_eV"] = result["kinetic_energy_eV"]
    result["vx_m_s"] = result["velocity_x_m_s"]
    result["vy_m_s"] = result["velocity_y_m_s"]
    result["vz_m_s"] = result["velocity_z_m_s"]
    result["theta_y_deg"] = np.degrees(np.arctan2(result["vy_m_s"], result["vx_m_s"]))
    result["theta_z_deg"] = np.degrees(
        np.arctan2(result["vz_m_s"], np.hypot(result["vx_m_s"], result["vy_m_s"]))
    )
    result["angle_deg"] = np.degrees(
        np.arctan2(np.hypot(result["vy_m_s"], result["vz_m_s"]), result["vx_m_s"])
    )
    result["speed_m_s"] = np.sqrt(result["vx_m_s"] ** 2 + result["vy_m_s"] ** 2 + result["vz_m_s"] ** 2)
    return result


def describe(group: pd.DataFrame, energy: str = "energy_eV") -> dict[str, float | int]:
    angle = group["angle_deg"] if "angle_deg" in group else pd.Series(np.zeros(len(group)))
    return {
        "particles": int(len(group)),
        "energy_mean_eV": float(group[energy].mean()),
        "energy_sample_std_eV": float(group[energy].std(ddof=1)),
        "speed_mean_m_s": float(group["speed_m_s"].mean()),
        "speed_sample_std_m_s": float(group["speed_m_s"].std(ddof=1)),
        "direction_angle_rms_deg": float(np.sqrt(np.mean(angle.to_numpy() ** 2))),
        "direction_angle_p95_deg": float(np.quantile(angle, 0.95)),
    }


def compare(entry_path: Path, local_path: Path, ideal_path: Path, baseline_path: Path,
            figure_path: Path, summary_path: Path) -> dict[str, object]:
    entry = pd.read_csv(entry_path)
    local = pd.read_csv(local_path)
    ideal = read_ideal_ion(ideal_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    rf = enrich_rf(entry, local)
    if len(rf) != 100 or len(local) != 100 or len(ideal) != 100:
        raise ValueError("entry comparison requires deterministic N=100 groups")
    species = rf[["mass_amu", "charge_state"]].drop_duplicates()
    if len(species) != 1 or not np.allclose(ideal["mass_amu"], float(species.iloc[0]["mass_amu"])):
        raise ValueError("oaTOF ideal reference is not mass matched to the RF particles")
    if not np.allclose(ideal["charge_state"], float(species.iloc[0]["charge_state"])):
        raise ValueError("oaTOF ideal reference is not charge matched to the RF particles")
    ideal["theta_y_deg"] = 0.0; ideal["theta_z_deg"] = 0.0; ideal["angle_deg"] = 0.0
    ideal["speed_m_s"] = np.sqrt(ideal["vx_m_s"] ** 2 + ideal["vy_m_s"] ** 2 + ideal["vz_m_s"] ** 2)
    inside, rejected = rf[rf["inside_port"]], rf[~rf["inside_port"]]
    center_z = float(baseline["particle_source"]["center_z_mm"])

    colors = {"all": "#3182bd", "inside": "#238b45", "rejected": "#636363", "ideal": "#756bb1"}
    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    ax = axes[0, 0]
    ax.scatter(inside["position_y_mm"], inside["position_z_mm"] - center_z, s=23,
               c=colors["inside"], alpha=0.75, label="RF inside port (88)")
    ax.scatter(rejected["position_y_mm"], rejected["position_z_mm"] - center_z, s=38,
               c=colors["rejected"], marker="x", label="RF rejected (12)")
    ax.scatter(ideal["y_mm"], ideal["z_mm"] - center_z, s=15, facecolors="none",
               edgecolors=colors["ideal"], alpha=0.55, label="oa ideal source (100)")
    ax.add_patch(Rectangle((-0.5, -0.45), 1.0, 0.9, fill=False, color="#54278f", linewidth=1.8))
    ax.set(xlabel="centered y (mm)", ylabel="centered z (mm)",
           title="A  Position reference and fixed physical port")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[0, 1]
    bins = np.linspace(min(rf["energy_eV"].min(), ideal["energy_eV"].min()),
                       max(rf["energy_eV"].max(), ideal["energy_eV"].max()), 25)
    ax.hist(rf["energy_eV"], bins=bins, histtype="step", linewidth=1.6, color=colors["all"],
            label="RF exit all")
    ax.hist(inside["energy_eV"], bins=bins, histtype="step", linewidth=2.0, color=colors["inside"],
            label="RF inside port")
    ax.hist(ideal["energy_eV"], bins=bins, histtype="step", linewidth=2.0, color=colors["ideal"],
            label="oa ideal, mass matched")
    ax.set(xlabel="kinetic energy (eV)", ylabel="particles", title="B  Kinetic-energy distributions")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[0, 2]
    ax.hist(rf["speed_m_s"], bins=20, histtype="step", linewidth=1.6, color=colors["all"],
            label="RF exit all")
    ax.hist(inside["speed_m_s"], bins=20, histtype="step", linewidth=2.0, color=colors["inside"],
            label="RF inside port")
    ax.hist(ideal["speed_m_s"], bins=20, histtype="step", linewidth=2.0, color=colors["ideal"],
            label="oa ideal")
    ax.set(xlabel="speed (m/s)", ylabel="particles", title="C  Speed distributions (100 amu, +1)")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[1, 0]
    ax.scatter(inside["theta_y_deg"], inside["theta_z_deg"], s=28, c=colors["inside"],
               alpha=0.8, label="inside port")
    ax.scatter(rejected["theta_y_deg"], rejected["theta_z_deg"], s=42, c=colors["rejected"],
               marker="x", label="rejected")
    ax.scatter([0], [0], s=90, c=colors["ideal"], marker="+", linewidths=2.5,
               label="oa ideal +x")
    ax.set(xlabel="horizontal direction angle theta_y (deg)",
           ylabel="vertical direction angle theta_z (deg)", title="D  Direction-angle distribution")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[1, 1]
    ax.scatter(inside["energy_eV"], inside["angle_deg"], s=28, c=colors["inside"], alpha=0.8,
               label="inside port")
    ax.scatter(rejected["energy_eV"], rejected["angle_deg"], s=42, c=colors["rejected"], marker="x",
               label="rejected")
    ax.scatter(ideal["energy_eV"], ideal["angle_deg"], s=20, facecolors="none",
               edgecolors=colors["ideal"], label="oa ideal")
    ax.set(xlabel="kinetic energy (eV)", ylabel="angle from +x (deg)",
           title="E  Energy-direction coupling")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[1, 2]
    ax.scatter(inside["position_y_mm"], inside["vy_m_s"], s=27, c=colors["inside"], alpha=0.8,
               label="RF y-vy")
    ax.scatter(inside["position_z_mm"] - center_z, inside["vz_m_s"], s=27, c="#e6550d",
               alpha=0.7, label="RF centered z-vz")
    ax.scatter(ideal["y_mm"], ideal["vy_m_s"], s=16, facecolors="none", edgecolors=colors["ideal"],
               alpha=0.5, label="oa ideal transverse velocity=0")
    ax.axhline(0, color="#969696", linewidth=1)
    ax.set(xlabel="transverse position (mm)", ylabel="transverse velocity (m/s)",
           title="F  Port-selected transverse phase space")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    fig.suptitle("RF physical-port selection vs mass-matched oaTOF ideal source (N=100)", fontsize=16)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=190)
    plt.close(fig)

    result = {
        "schema_version": 1,
        "role": "rf_s1_entry_vs_mass_matched_oatof_ideal_source",
        "status": "PASS",
        "comparison_scope": "RF physical-port entry-plane selection diagnostic versus oaTOF ideal release reference",
        "equivalent_capture_state_available": False,
        "direct_acceptance_claim_allowed": False,
        "species": {"mass_amu": float(species.iloc[0]["mass_amu"]),
                    "charge_state": int(species.iloc[0]["charge_state"])},
        "groups": {"rf_exit_all": describe(rf), "rf_inside_port": describe(inside),
                   "rf_geometric_reject": describe(rejected), "oatof_ideal_mass_matched": describe(ideal)},
        "aperture_selection": {
            "accepted": int(len(inside)), "rejected": int(len(rejected)),
            "accepted_fraction": float(len(inside) / len(rf)),
            "inside_minus_all_energy_mean_eV": float(inside["energy_eV"].mean() - rf["energy_eV"].mean()),
            "inside_direction_angle_rms_deg": float(np.sqrt(np.mean(inside["angle_deg"] ** 2))),
        },
        "inside_port_minus_ideal_reference": {
            "energy_mean_difference_eV": float(inside["energy_eV"].mean() - ideal["energy_eV"].mean()),
            "energy_mean_ratio": float(inside["energy_eV"].mean() / ideal["energy_eV"].mean()),
            "speed_mean_difference_m_s": float(inside["speed_m_s"].mean() - ideal["speed_m_s"].mean()),
            "speed_mean_ratio": float(inside["speed_m_s"].mean() / ideal["speed_m_s"].mean()),
            "direction_angle_rms_difference_deg": float(np.sqrt(np.mean(inside["angle_deg"] ** 2))),
        },
        "next_required_state": "particle state inside the oa capture volume immediately before the extraction pulse",
        "dense_trajectories_used": False,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--ideal-ion", type=Path, required=True)
    parser.add_argument("--oatof-baseline", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.entry, args.local, args.ideal_ion, args.oatof_baseline,
                     args.figure, args.summary)
    print(f"S1_ENTRY_IDEAL_COMPARISON=PASS INSIDE={result['aperture_selection']['accepted']}/100")


if __name__ == "__main__":
    main()
