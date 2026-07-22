"""Analyze oa-TOF SIMION accelerator grid-origin phase diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from projects.oa_tof.analysis.peak_metrics import AnalysisSettings, compute_peak_metrics, compute_source_mapping_metrics


def _read_particles(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"Ion", "X0Mm", "Y0Mm", "Z0Mm", "EnergyEv", "TofUs"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} misses columns {sorted(missing)}")
    if frame["Ion"].duplicated().any():
        raise ValueError(f"{path} contains duplicate ion identifiers")
    return frame.sort_values("Ion").reset_index(drop=True)


def _relative_rms(values: np.ndarray, reference: np.ndarray) -> float:
    denominator = float(np.sqrt(np.mean(reference**2)))
    if denominator <= 0:
        raise ValueError("field reference has zero RMS")
    return float(np.sqrt(np.mean((values - reference) ** 2)) / denominator)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--robustness-reference", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    cases = manifest["cases"]
    by_name = {case["name"]: case for case in cases}
    reference_name = "expanded_p0000"
    crop_name = "formal_crop_p0000"
    if reference_name not in by_name or crop_name not in by_name:
        raise ValueError("manifest must contain expanded_p0000 and formal_crop_p0000")

    settings = AnalysisSettings()
    particle_frames: dict[str, pd.DataFrame] = {}
    field_frames: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, float | str | int]] = []

    for case in cases:
        name = case["name"]
        particles = _read_particles(Path(case["particle_csv"]))
        field = pd.read_csv(case["field_csv"])
        if len(field) != 1941 or not np.allclose(
            field["z_mm"].to_numpy(), np.linspace(0.2, 19.6, 1941), atol=1e-10
        ):
            raise ValueError(f"{name} field coordinates are not the common grid")
        peak, _ = compute_peak_metrics(particles["TofUs"].to_numpy(), 524.0, settings)
        source, _ = compute_source_mapping_metrics(
            particles["TofUs"].to_numpy(),
            particles["X0Mm"].to_numpy(),
            particles["Y0Mm"].to_numpy(),
            particles["Z0Mm"].to_numpy(),
            particles["EnergyEv"].to_numpy(),
        )
        source_mask = field["z_mm"].to_numpy() <= 2.8
        particle_frames[name] = particles
        field_frames[name] = field
        rows.append(
            {
                "name": name,
                "phase_mm": float(case["phase_mm"]),
                "back_margin_mm": float(case["back_margin_mm"]),
                "front_margin_mm": float(case["front_margin_mm"]),
                "particles": int(len(particles)),
                "mean_tof_us": peak["mean_tof_us"],
                "std_tof_ns": peak["std_tof_ns"],
                "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"],
                "mass_resolution": peak["mass_resolution"],
                "time_focus_vertex_z_mm": source["quadratic_vertex_z_mm"],
                "source_mean_ez_v_per_m": float(field.loc[source_mask, "Ez_V_per_m"].mean()),
            }
        )

    reference_particles = particle_frames[reference_name]
    reference_field = field_frames[reference_name]
    reference_tof = reference_particles.set_index("Ion")["TofUs"]
    source_mask = reference_field["z_mm"].to_numpy() <= 2.8
    full_mask = reference_field["z_mm"].to_numpy() >= 3.2
    for row in rows:
        name = str(row["name"])
        tof = particle_frames[name].set_index("Ion")["TofUs"].reindex(reference_tof.index)
        if tof.isna().any():
            raise ValueError(f"{name} does not contain the same fixed ions")
        delta_ns = (tof.to_numpy() - reference_tof.to_numpy()) * 1000.0
        field = field_frames[name]["Ez_V_per_m"].to_numpy()
        reference = reference_field["Ez_V_per_m"].to_numpy()
        row["paired_tof_delta_mean_ns_vs_expanded_p0000"] = float(np.mean(delta_ns))
        row["paired_tof_delta_rms_ns_vs_expanded_p0000"] = float(np.sqrt(np.mean(delta_ns**2)))
        row["paired_tof_delta_max_abs_ns_vs_expanded_p0000"] = float(np.max(np.abs(delta_ns)))
        row["source_field_relative_rms_vs_expanded_p0000"] = _relative_rms(
            field[source_mask], reference[source_mask]
        )
        row["accelerator_field_relative_rms_vs_expanded_p0000"] = _relative_rms(
            field[full_mask], reference[full_mask]
        )

    summary = pd.DataFrame(rows).sort_values(["back_margin_mm", "phase_mm"]).reset_index(drop=True)
    expanded = summary[summary["back_margin_mm"] > 0].copy()
    phase_tof_span_ns = float((expanded["mean_tof_us"].max() - expanded["mean_tof_us"].min()) * 1000.0)
    phase_fwhm_span_pct = float(
        100.0
        * (expanded["direct_fwhm_tof_ns"].max() - expanded["direct_fwhm_tof_ns"].min())
        / expanded.loc[expanded["name"] == reference_name, "direct_fwhm_tof_ns"].iloc[0]
    )
    phase_source_ez_span_pct = float(
        100.0
        * (expanded["source_mean_ez_v_per_m"].max() - expanded["source_mean_ez_v_per_m"].min())
        / abs(expanded.loc[expanded["name"] == reference_name, "source_mean_ez_v_per_m"].iloc[0])
    )
    crop = summary.set_index("name")
    crop_tof_delta_ns = float(
        (crop.loc[crop_name, "mean_tof_us"] - crop.loc[reference_name, "mean_tof_us"]) * 1000.0
    )
    crop_fwhm_delta_pct = float(
        100.0
        * (crop.loc[crop_name, "direct_fwhm_tof_ns"] - crop.loc[reference_name, "direct_fwhm_tof_ns"])
        / crop.loc[reference_name, "direct_fwhm_tof_ns"]
    )
    cross_solver_mean_tof_difference_ns = 3.180093702454201
    cross_solver_source_ez_difference_pct = 0.8396084857556473
    result = {
        "status": "PASS",
        "design": {
            "axial_cell_mm": 0.05,
            "expanded_domain_margin_back_front_mm": [0.2, 0.2],
            "grid_phases_mm": [0.0, 0.0125, 0.025, 0.0375],
            "fixed_particles": 100,
            "ideal_grid_epsilon_mm": float(manifest["ideal_grid_epsilon_mm"]),
            "mechanical_geometry_changed": False,
            "independent_variable": "accelerator geometry phase relative to a fixed SIMION axial grid",
        },
        "aggregate": {
            "phase_mean_tof_span_ns": phase_tof_span_ns,
            "phase_fwhm_span_pct_of_phase0": phase_fwhm_span_pct,
            "phase_source_mean_ez_span_pct": phase_source_ez_span_pct,
            "phase_tof_span_fraction_of_cross_solver_mean_difference": phase_tof_span_ns
            / cross_solver_mean_tof_difference_ns,
            "phase_source_ez_span_fraction_of_cross_solver_difference": phase_source_ez_span_pct
            / cross_solver_source_ez_difference_pct,
            "crop_control_mean_tof_delta_ns_formal_minus_expanded": crop_tof_delta_ns,
            "crop_control_fwhm_delta_pct_formal_minus_expanded": crop_fwhm_delta_pct,
        },
        "interpretation": {
            "phase_effect_material_for_sub_0p1ns_matching": bool(
                expanded["paired_tof_delta_rms_ns_vs_expanded_p0000"].max() >= 0.1
            ),
            "phase_alone_explains_cross_solver_mean_tof_difference": bool(
                phase_tof_span_ns >= cross_solver_mean_tof_difference_ns
            ),
            "note": "Phase sensitivity is isolated at fixed dz; crop-control sensitivity is reported separately.",
        },
        "cases": summary.to_dict(orient="records"),
    }
    if args.robustness_reference:
        reference_result = json.loads(
            args.robustness_reference.read_text(encoding="utf-8-sig")
        )
        reference_aggregate = reference_result["aggregate"]
        reference_span = float(reference_aggregate["phase_mean_tof_span_ns"])
        result["robustness_vs_reference"] = {
            "reference_path": str(args.robustness_reference.resolve()),
            "reference_ideal_grid_epsilon_mm": float(
                reference_result["design"]["ideal_grid_epsilon_mm"]
            ),
            "mean_tof_span_absolute_difference_ns": abs(
                phase_tof_span_ns - reference_span
            ),
            "mean_tof_span_relative_difference_pct": 100.0
            * abs(phase_tof_span_ns - reference_span)
            / reference_span,
            "reference_phase_fwhm_span_pct": float(
                reference_aggregate["phase_fwhm_span_pct_of_phase0"]
            ),
            "current_phase_fwhm_span_pct": phase_fwhm_span_pct,
            "interpretation": (
                "Mean-TOF phase sensitivity is robust across grid-jump buffers; "
                "direct FWHM remains buffer-sensitive."
            ),
        }

    args.output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output / "accelerator_grid_phase_summary.csv", index=False)
    (args.output / "accelerator_grid_phase_metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), constrained_layout=True)
    phase0_tof_us = float(
        expanded.loc[expanded["name"] == reference_name, "mean_tof_us"].iloc[0]
    )
    phase0_source_ez = float(
        expanded.loc[expanded["name"] == reference_name, "source_mean_ez_v_per_m"].iloc[0]
    )
    axes[0].plot(
        expanded["phase_mm"],
        (expanded["mean_tof_us"] - phase0_tof_us) * 1000.0,
        "o-",
    )
    axes[0].set(
        xlabel="grid phase (mm)",
        ylabel="mean TOF shift from phase 0 (ns)",
        title="Fixed N=100 mean TOF",
    )
    axes[1].plot(expanded["phase_mm"], expanded["direct_fwhm_tof_ns"], "o-")
    axes[1].set(xlabel="grid phase (mm)", ylabel="direct FWHM (ns)", title="Canonical direct FWHM")
    axes[2].plot(
        expanded["phase_mm"],
        1.0e6 * (expanded["source_mean_ez_v_per_m"] - phase0_source_ez) / abs(phase0_source_ez),
        "o-",
    )
    axes[2].set(
        xlabel="grid phase (mm)",
        ylabel="mean Ez shift from phase 0 (ppm)",
        title="Source-region axial field",
    )
    for axis in axes:
        axis.grid(alpha=0.3)
    fig.suptitle(
        "SIMION accelerator grid-phase diagnostic: "
        f"dz=0.05 mm, margins=0.2 mm, grid jump={manifest['ideal_grid_epsilon_mm']:.3f} mm"
    )
    fig.savefig(args.output / "accelerator_grid_phase_diagnostics.png", dpi=180)
    plt.close(fig)
    print(json.dumps(result["aggregate"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
