"""Compare paired N=100 continuous-shield transport events without selecting a shield."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = {
    "particle_id", "status", "global_time_us", "x_mm", "y_mm", "vx_m_s", "vy_m_s", "vz_m_s",
    "kinetic_energy_eV", "radial_position_mm", "divergence_angle_deg", "rf_phase_rad",
}


def compare(candidate: pd.DataFrame, reference: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    for label, table in (("candidate", candidate), ("reference", reference)):
        missing = REQUIRED - set(table.columns)
        if missing:
            raise ValueError(f"{label} event table is missing columns: {sorted(missing)}")
        if table["particle_id"].duplicated().any():
            raise ValueError(f"{label} event table has duplicate particle identities")
    left = candidate.sort_values("particle_id").reset_index(drop=True)
    right = reference.sort_values("particle_id").reset_index(drop=True)
    if not np.array_equal(left["particle_id"].to_numpy(int), right["particle_id"].to_numpy(int)):
        raise ValueError("paired event tables do not share particle identities")
    paired = pd.DataFrame({
        "particle_id": left["particle_id"].to_numpy(int),
        "candidate_status": left["status"],
        "reference_status": right["status"],
    })
    paired["classification_changed"] = paired["candidate_status"] != paired["reference_status"]
    common = (left["status"] == "transmitted") & (right["status"] == "transmitted")
    paired["common_transmitted"] = common
    for column in ("global_time_us", "radial_position_mm", "divergence_angle_deg", "kinetic_energy_eV", "x_mm", "y_mm", "vx_m_s", "vy_m_s", "vz_m_s"):
        paired[f"delta_{column}"] = left[column].to_numpy(float) - right[column].to_numpy(float)
    common_left = left.loc[common]
    common_right = right.loc[common]
    def rms(series: pd.Series) -> float:
        return float(np.sqrt(np.mean(np.square(series.to_numpy(float)))))
    def relative(candidate_value: float, reference_value: float) -> float:
        return abs(candidate_value-reference_value)/abs(reference_value) if reference_value != 0.0 else np.nan
    left_rms_radius, right_rms_radius = rms(common_left["radial_position_mm"]), rms(common_right["radial_position_mm"])
    left_rms_div, right_rms_div = rms(common_left["divergence_angle_deg"]), rms(common_right["divergence_angle_deg"])
    delta_x = paired.loc[common, "delta_x_mm"].to_numpy(float)
    delta_y = paired.loc[common, "delta_y_mm"].to_numpy(float)
    delta_vx = paired.loc[common, "delta_vx_m_s"].to_numpy(float)
    delta_vy = paired.loc[common, "delta_vy_m_s"].to_numpy(float)
    phase_delta = np.angle(np.exp(1j * (
        common_left["rf_phase_rad"].to_numpy(float) - common_right["rf_phase_rad"].to_numpy(float)
    )))
    summary = {
        "schema_version": 1,
        "role": "rf_continuous_shield_n100_paired_transport_comparison",
        "status": "CHARACTERIZED",
        "particles": int(len(left)),
        "candidate_transmitted": int((left["status"] == "transmitted").sum()),
        "reference_transmitted": int((right["status"] == "transmitted").sum()),
        "transmission_absolute_difference": float(abs((left["status"] == "transmitted").mean()-(right["status"] == "transmitted").mean())),
        "classification_change_count": int(paired["classification_changed"].sum()),
        "classification_changed_particle_ids": paired.loc[paired["classification_changed"], "particle_id"].tolist(),
        "common_transmitted_particles": int(common.sum()),
        "relative_rms_radius_difference_common_transmitted": relative(left_rms_radius, right_rms_radius),
        "relative_rms_divergence_difference_common_transmitted": relative(left_rms_div, right_rms_div),
        "relative_mean_energy_difference_common_transmitted": relative(float(common_left["kinetic_energy_eV"].mean()), float(common_right["kinetic_energy_eV"].mean())),
        "paired_time_difference_rms_us_common_transmitted": rms(paired.loc[common, "delta_global_time_us"]),
        "paired_position_difference_rms_mm_common_transmitted": float(np.sqrt(np.mean(delta_x**2 + delta_y**2))),
        "paired_transverse_velocity_difference_rms_m_s_common_transmitted": float(np.sqrt(np.mean(delta_vx**2 + delta_vy**2))),
        "paired_rf_phase_difference_rms_rad_common_transmitted": float(np.sqrt(np.mean(phase_delta**2))),
        "paired_rf_phase_difference_max_abs_rad_common_transmitted": float(np.max(np.abs(phase_delta))),
        "acceptance_decision": "FAIL" if paired["classification_changed"].any() else "UNRESOLVED",
        "selection_allowed": False,
    }
    return paired, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    paired, summary = compare(pd.read_csv(args.candidate), pd.read_csv(args.reference))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paired.to_csv(args.output_dir / "rf_continuous_shield_n100_paired_particles.csv", index=False)
    (args.output_dir / "rf_continuous_shield_n100_comparison_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"RF_CONTINUOUS_SHIELD_N100_COMPARISON=PASS ACCEPTANCE_DECISION={summary['acceptance_decision']}")


if __name__ == "__main__":
    main()
