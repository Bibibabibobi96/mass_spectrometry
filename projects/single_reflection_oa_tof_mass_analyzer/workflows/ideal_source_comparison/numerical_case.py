"""Numerical working-point and per-case propagation for ideal-source comparison."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from common.analysis.peak_metrics import AnalysisSettings
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    NumericalSourceSpec, build_numerical_source, build_working_point, propagate_ideal_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import OuterGeometry, ReflectronGeometry

def _settings(analysis_contract_path: Path) -> AnalysisSettings:
    kde = load_json(analysis_contract_path)["kde"]
    return AnalysisSettings(grid_points=kde["grid_points"], bandwidth_multiplier=kde["bandwidth_multiplier"],
                            mode_threshold_fraction=kde["significant_mode_threshold_fraction"])

def _working_points(config: dict[str, Any]) -> dict[str, Any]:
    source = NumericalSourceSpec(**config["source"])
    outer, mirror = OuterGeometry(**config["outer"]), ReflectronGeometry(**config["reflectron"])
    points = {}
    for name, eta, slope in (
        ("three_zone_uncorrelated_setting", config["three_zone_eta"], 0.0),
        ("three_zone_matched", config["three_zone_eta"], source.velocity_slope_m_per_s_per_mm),
        ("two_zone_matched", 0.0, source.velocity_slope_m_per_s_per_mm),
    ):
        points[name] = build_working_point(source, outer, mirror, eta=eta,
                                          design_velocity_slope_m_per_s_per_mm=slope,
                                          focus_drift_mm=config["focus_drift_mm"])
    return points

def _run_case(case: dict[str, Any], config: dict[str, Any], points: dict[str, Any],
              settings: AnalysisSettings, result_dir: Path) -> dict[str, Any]:
    source = build_numerical_source(NumericalSourceSpec(**config["source"]),
                                    particle_count=config["sampling"]["particle_count"], seed=case["seed"],
                                    full_width_mm=case["full_width_mm"], residual_sigma_m_per_s=case["residual_sigma_m_per_s"])
    names = ("three_zone_uncorrelated_setting", "three_zone_matched") if case["stage"] == "residual_scan" else ("two_zone_matched", "three_zone_matched")
    outputs = {name: propagate_ideal_source(source, points[name], settings=settings) for name in names}
    csv_path = result_dir / f"{case['case_id']}__particles.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["particle_id", "source_x_mm", "source_velocity_m_per_s", *[f"{name}__{field}" for name in names for field in ("classification", "tof_us")]])
        for index, particle_id in enumerate(source.particle_id):
            values = [int(particle_id), float(source.source_x_mm[index]), float(source.velocity_z_m_per_s[index])]
            for name in names:
                output = outputs[name]
                values.extend([str(output.classification[index]), float(output.tof_us[index]) if np.isfinite(output.tof_us[index]) else ""])
            writer.writerow(values)
    arms = {}
    for name, result in outputs.items():
        if result.summary["status"] == "PEAK_METRICS_FAILED":
            raise ArithmeticError(f"{name}: {result.summary['reason']}")
        metrics = result.summary["peak_metrics"] or {}
        arms[name] = {**result.summary, "resolution": metrics.get("mass_resolution"),
                      "fwhm_ns": metrics.get("direct_fwhm_tof_ns"),
                      "model_arrival_fraction": result.summary["axial_model_reachability_fraction"]}
    before, after = (arms[name] for name in names)
    gain = 100 * (after["resolution"] / before["resolution"] - 1) if before["resolution"] and after["resolution"] else None
    eligible = gain is not None and all(r["model_arrival_fraction"] == 1 for r in arms.values())
    return {"case": case, "arms": arms, "resolution_gain_percent": gain,
            "comparison_eligible": eligible,
            "reason": "full mother cohort retained" if eligible else "loss, unsupported event topology, or undefined peak; not a fair full-cohort gain claim",
            "particles": {"path": csv_path.name, "bytes": csv_path.stat().st_size, "sha256": file_sha256(csv_path)}}
