"""Compare particle-wise paired 2 eV and 5 eV RF quadrupole input-energy runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def rms(values: pd.Series | np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(array * array)))


def describe(events: pd.DataFrame) -> dict[str, float | int]:
    handoff = events.loc[events["event"] == "handoff"]
    return {
        "transmitted": int(len(handoff)),
        "transmission": float(len(handoff) / len(events)),
        "mean_energy_eV": float(handoff["kinetic_energy_eV"].mean()),
        "energy_sample_std_eV": float(handoff["kinetic_energy_eV"].std(ddof=1)),
        "rms_radial_position_mm": rms(handoff["radial_position_mm"]),
        "rms_divergence_angle_deg": rms(handoff["divergence_angle_deg"]),
        "mean_global_time_us": float(handoff["global_time_us"].mean()),
    }


def compare(control_events_path: Path, candidate_events_path: Path, control_ion_path: Path,
            candidate_ion_path: Path, contract_path: Path, figure_path: Path,
            summary_path: Path) -> dict[str, object]:
    control = pd.read_csv(control_events_path).sort_values("particle_id").reset_index(drop=True)
    candidate = pd.read_csv(candidate_events_path).sort_values("particle_id").reset_index(drop=True)
    control_ion = np.loadtxt(control_ion_path, delimiter=",")
    candidate_ion = np.loadtxt(candidate_ion_path, delimiter=",")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if len(control) != 100 or len(candidate) != 100 or control_ion.shape != (100, 11) or candidate_ion.shape != (100, 11):
        raise ValueError("RF input-energy comparison requires two N=100 cases")
    if not np.array_equal(control["particle_id"].to_numpy(), candidate["particle_id"].to_numpy()):
        raise ValueError("RF input-energy event identities are not paired")
    paired_columns = list(range(8)) + [9, 10]
    source_phase_space_paired = bool(np.array_equal(control_ion[:, paired_columns], candidate_ion[:, paired_columns]))
    if not source_phase_space_paired:
        raise ValueError("RF input sources differ in more than kinetic energy")
    control_metrics, candidate_metrics = describe(control), describe(candidate)
    target = float(contract["paired_test"]["target_mean_energy_eV"])
    tolerance = float(contract["paired_test"]["target_mean_energy_tolerance_eV"])
    maximum_change = float(contract["paired_test"]["maximum_mean_energy_change_through_rf_eV"])
    input_candidate_mean = float(candidate_ion[:, 8].mean())
    checks = {
        "source_phase_space_particle_wise_paired": source_phase_space_paired,
        "candidate_transmission": candidate_metrics["transmitted"] >= int(contract["paired_test"]["minimum_transmitted_particles"]),
        "candidate_mean_energy_matches_oatof_reference": abs(candidate_metrics["mean_energy_eV"] - target) <= tolerance,
        "candidate_mean_energy_preserved_through_rf": abs(candidate_metrics["mean_energy_eV"] - input_candidate_mean) <= maximum_change,
    }
    status = "PASS" if all(checks.values()) else "FAIL"

    control_handoff = control.loc[control["event"] == "handoff"]
    candidate_handoff = candidate.loc[candidate["event"] == "handoff"]
    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    colors = {"control": "#3182bd", "candidate": "#238b45"}
    for data, label, color in ((control_handoff, "2 eV input", colors["control"]),
                               (candidate_handoff, "5 eV input", colors["candidate"])):
        axes[0, 0].hist(data["kinetic_energy_eV"], bins=20, histtype="step", lw=2, label=label, color=color)
        axes[0, 1].hist(data["radial_position_mm"], bins=20, histtype="step", lw=2, label=label, color=color)
        axes[0, 2].hist(data["divergence_angle_deg"], bins=20, histtype="step", lw=2, label=label, color=color)
        axes[1, 0].hist(data["global_time_us"], bins=20, histtype="step", lw=2, label=label, color=color)
    axes[0, 0].axvline(target, color="#756bb1", ls="--", lw=1.5, label="oa mean reference")
    axes[0, 0].set(xlabel="handoff kinetic energy (eV)", ylabel="particles", title="A  RF handoff energy")
    axes[0, 1].set(xlabel="handoff radius (mm)", ylabel="particles", title="B  Radial distribution")
    axes[0, 2].set(xlabel="handoff divergence (deg)", ylabel="particles", title="C  Divergence distribution")
    axes[1, 0].set(xlabel="handoff instrument time (us)", ylabel="particles", title="D  Arrival-time distribution")
    axes[1, 1].scatter(control_handoff["radial_position_mm"], candidate_handoff["radial_position_mm"],
                       s=28, alpha=0.75, color="#756bb1")
    limit = max(control_handoff["radial_position_mm"].max(), candidate_handoff["radial_position_mm"].max())
    axes[1, 1].plot([0, limit], [0, limit], color="#969696", lw=1)
    axes[1, 1].set(xlabel="2 eV radius (mm)", ylabel="5 eV radius (mm)", title="E  Particle-wise radial change")
    axes[1, 2].axis("off")
    axes[1, 2].text(0.03, 0.92,
                    f"Energy-match status: {status}\n\n"
                    f"Transmission: {candidate_metrics['transmitted']}/100\n"
                    f"Mean energy: {candidate_metrics['mean_energy_eV']:.4f} eV\n"
                    f"Energy sigma: {candidate_metrics['energy_sample_std_eV']:.4f} eV\n"
                    f"Radius RMS: {candidate_metrics['rms_radial_position_mm']:.4f} mm\n"
                    f"Divergence RMS: {candidate_metrics['rms_divergence_angle_deg']:.3f} deg",
                    va="top", fontsize=12)
    for ax in axes.flat[:5]:
        ax.grid(alpha=0.22)
        if ax is not axes[1, 1]:
            ax.legend(fontsize=8)
    fig.suptitle("Particle-wise paired RF input-energy test: 2 eV versus 5 eV (N=100)", fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=190)
    plt.close(fig)

    result = {
        "schema_version": 1,
        "role": "rf_to_oatof_input_energy_match_comparison",
        "status": status,
        "only_source_variable": "kinetic_energy_eV",
        "control_2eV": control_metrics,
        "candidate_5eV": candidate_metrics,
        "candidate_minus_control": {
            "mean_energy_eV": candidate_metrics["mean_energy_eV"] - control_metrics["mean_energy_eV"],
            "mean_global_time_us": candidate_metrics["mean_global_time_us"] - control_metrics["mean_global_time_us"],
            "rms_radius_relative_change": candidate_metrics["rms_radial_position_mm"] / control_metrics["rms_radial_position_mm"] - 1,
            "rms_divergence_relative_change": candidate_metrics["rms_divergence_angle_deg"] / control_metrics["rms_divergence_angle_deg"] - 1,
        },
        "checks": checks,
        "geometry_or_field_changed": False,
        "handoff_velocity_rewritten": False,
        "collision_model_enabled": False,
        "downstream_oatof_performance_claim_allowed": False,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-events", type=Path, required=True)
    parser.add_argument("--candidate-events", type=Path, required=True)
    parser.add_argument("--control-ion", type=Path, required=True)
    parser.add_argument("--candidate-ion", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.control_events, args.candidate_events, args.control_ion, args.candidate_ion,
                     args.contract, args.figure, args.summary)
    print(f"RF_INPUT_ENERGY_MATCH={result['status']} MEAN_EV={result['candidate_5eV']['mean_energy_eV']:.6f}")
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
