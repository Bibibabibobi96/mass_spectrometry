"""Summarize controlled field-idealization cases relative to a real-field baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-summary", required=True, type=Path)
    parser.add_argument("--metrics-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    run = pd.read_csv(args.run_summary)
    particle_tables = {
        row.case_id: pd.read_csv(row.particle_csv).sort_values("particle_id").reset_index(drop=True)
        for row in run.itertuples(index=False)
    }
    real_particles = particle_tables["real"]
    records: list[dict[str, object]] = []
    for row in run.itertuples(index=False):
        payload = json.loads((args.metrics_root / row.case_id / "metrics.json").read_text(encoding="utf-8"))
        metrics = payload["metrics"]
        particles = particle_tables[row.case_id]
        if not particles.particle_id.equals(real_particles.particle_id):
            raise ValueError(f"Particle IDs are not paired for {row.case_id}.")
        tof_delta_ns = (particles.tof_us - real_particles.tof_us) * 1000
        landing_delta_mm = ((particles.detector_x_mm - real_particles.detector_x_mm) ** 2 +
                            (particles.detector_y_mm - real_particles.detector_y_mm) ** 2) ** 0.5
        records.append({
            "case_id": row.case_id,
            "selector": row.selector,
            "detected": int(row.detected),
            "solve_seconds": float(row.solve_seconds),
            "mean_tof_us": metrics["mean_tof_us"],
            "direct_fwhm_tof_ns": metrics["direct_fwhm_tof_ns"],
            "mass_resolution": metrics["mass_resolution"],
            "std_tof_ns": metrics["std_tof_ns"],
            "landing_rms_mm": metrics["detector"]["impact_rms_radius_mm"],
            "z_quadratic_r_squared": metrics["source_mapping"]["z_only_quadratic_r_squared"],
            "paired_tof_rms_ns": float((tof_delta_ns.pow(2).mean()) ** 0.5),
            "paired_tof_max_abs_ns": float(tof_delta_ns.abs().max()),
            "paired_landing_rms_mm": float((landing_delta_mm.pow(2).mean()) ** 0.5),
        })
    frame = pd.DataFrame(records)
    baseline = frame.loc[frame.case_id == "real"]
    if len(baseline) != 1:
        raise ValueError("Exactly one real baseline is required.")
    base = baseline.iloc[0]
    frame["delta_mean_tof_ns"] = (frame.mean_tof_us - base.mean_tof_us) * 1000
    frame["delta_direct_fwhm_tof_ns"] = frame.direct_fwhm_tof_ns - base.direct_fwhm_tof_ns
    frame["delta_mass_resolution_pct"] = (frame.mass_resolution / base.mass_resolution - 1) * 100
    frame["delta_landing_rms_mm"] = frame.landing_rms_mm - base.landing_rms_mm

    args.output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output / "field_idealization_effects.csv", index=False)
    all_particles = particle_tables.get("ideal_all")
    ez_particles = particle_tables.get("ideal_ez")
    endpoint_pair = None
    if all_particles is not None and ez_particles is not None:
        endpoint_tof_delta_ns = (all_particles.tof_us - ez_particles.tof_us) * 1000
        endpoint_landing_delta_mm = ((all_particles.detector_x_mm - ez_particles.detector_x_mm) ** 2 +
                                     (all_particles.detector_y_mm - ez_particles.detector_y_mm) ** 2) ** 0.5
        endpoint_pair = {
            "ideal_all_minus_ideal_ez_tof_rms_ns": float((endpoint_tof_delta_ns.pow(2).mean()) ** 0.5),
            "ideal_all_minus_ideal_ez_tof_max_abs_ns": float(endpoint_tof_delta_ns.abs().max()),
            "ideal_all_minus_ideal_ez_landing_rms_mm": float((endpoint_landing_delta_mm.pow(2).mean()) ** 0.5),
        }
    by_case = frame.set_index("case_id")
    interaction_cases = {
        "a": "ideal_accel_ez", "b": "ideal_stage1_ez", "c": "ideal_stage2_ez",
        "ab": "ideal_accel_stage1_ez", "ac": "ideal_accel_stage2_ez",
        "bc": "ideal_stage1_stage2_ez", "abc": "ideal_ez",
    }
    ez_interactions = None
    if all(case in by_case.index for case in interaction_cases.values()):
        ez_interactions = {}
        for metric in ("mean_tof_us", "direct_fwhm_tof_ns", "mass_resolution", "landing_rms_mm"):
            base_value = float(by_case.loc["real", metric])
            effect = {key: float(by_case.loc[case, metric]) - base_value
                      for key, case in interaction_cases.items()}
            pair = {
                "accel_stage1": effect["ab"] - effect["a"] - effect["b"],
                "accel_stage2": effect["ac"] - effect["a"] - effect["c"],
                "stage1_stage2": effect["bc"] - effect["b"] - effect["c"],
            }
            third = effect["abc"] - effect["ab"] - effect["ac"] - effect["bc"] + \
                effect["a"] + effect["b"] + effect["c"]
            ez_interactions[metric] = {"single_and_combined_effects": effect,
                                       "pairwise_interactions": pair,
                                       "third_order_interaction": third}
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "baseline": "real",
        "cases": frame.to_dict(orient="records"),
        "endpoint_pair": endpoint_pair,
        "ez_region_interactions": ez_interactions,
        "interpretation_policy": {
            "component_screen": "Compare each one-component intervention with real and ideal_all.",
            "interaction_warning": "Matching endpoint metrics do not prove pointwise trajectory identity; use paired tables for exact equality.",
            "resolution_scope": "N=100 diagnostic only; not a formal N=1000 resolution claim.",
        },
    }
    (args.output / "field_idealization_effects.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    plot = frame.loc[frame.case_id != "real"].copy()
    labels = plot.case_id.str.replace("ideal_", "", regex=False)
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    panels = [
        ("delta_mean_tof_ns", "Mean TOF change (ns)"),
        ("delta_direct_fwhm_tof_ns", "Direct KDE FWHM change (ns)"),
        ("delta_mass_resolution_pct", "Mass resolution change (%)"),
        ("delta_landing_rms_mm", "Landing RMS radius change (mm)"),
    ]
    for axis, (column, ylabel) in zip(axes.flat, panels, strict=True):
        axis.bar(labels, plot[column], color=["0.35", "tab:blue", "tab:orange", "tab:green"])
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle("oa-TOF N=100 controlled global field-component screen")
    fig.savefig(args.output / "field_idealization_effects.png", dpi=180)
    plt.close(fig)
    print("FIELD_IDEALIZATION_ANALYSIS=PASS")


if __name__ == "__main__":
    main()
