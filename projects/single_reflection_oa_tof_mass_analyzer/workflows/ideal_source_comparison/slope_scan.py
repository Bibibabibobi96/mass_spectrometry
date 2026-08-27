"""Compare affine source slopes with theory-derived OA-TOF working points.

This is a solver-free, synthetic-source mechanism workflow.  A nonzero source
slope is deliberately compared with the same source propagated through a
zero-slope design and through the matching design; fields and reflector
voltages are always derived, never independently tuned.
"""

from __future__ import annotations

import csv
import math
import time
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json
from common.contracts.particle_count_policy import validate_positive_particle_count
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    NumericalSourceSpec, build_numerical_source,
    propagate_ideal_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_linear_design import (
    solve_linear_third_order_design,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    ReflectronGeometry,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison import (
    REPO_ROOT, _prepare_run, _publish_manifest, _settings,
    _write_json,
)


def _keys(value: dict[str, Any], expected: str, label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError(f"{label}: missing or unknown fields; expected {expected}")


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise ValueError(f"{label} must be finite{' and positive' if positive else ''}")
    return result


def validate_slope_scan_config(config: dict[str, Any]) -> None:
    """Validate the scientific inputs before freezing or calculating a run."""
    _keys(config, "schema_version role source_template source_slopes_m_per_s_per_mm historical_slope_receipt theory_controls reflectron full_width_mm residual_sigma_m_per_s sampling analysis_contract scope", "slope scan")
    if config["schema_version"] != 1 or config["role"] != "ideal_source_slope_scan":
        raise ValueError("unsupported slope-scan schema or role")
    _keys(config["source_template"], "mass_to_charge_th center_x_mm center_velocity_m_per_s velocity_quadratic_m_per_s_per_mm2", "source template")
    template = config["source_template"]
    NumericalSourceSpec(**template, velocity_slope_m_per_s_per_mm=0.0)
    for label in ("full_width_mm", "residual_sigma_m_per_s"):
        _finite(config[label], label, positive=label == "full_width_mm")
    slopes = config["source_slopes_m_per_s_per_mm"]
    if not isinstance(slopes, list) or len(slopes) < 2:
        raise ValueError("source slopes require at least zero and one nonzero value")
    parsed_slopes = [_finite(value, "source slope") for value in slopes]
    if len(set(parsed_slopes)) != len(parsed_slopes) or 0.0 not in parsed_slopes:
        raise ValueError("source slopes must be unique and include zero")
    _keys(config["historical_slope_receipt"], "path sha256 slope_m_per_s_per_mm", "historical slope receipt")
    receipt = config["historical_slope_receipt"]
    if not isinstance(receipt["path"], str) or not receipt["path"]:
        raise ValueError("historical slope receipt path is required")
    if not isinstance(receipt["sha256"], str) or len(receipt["sha256"]) != 64:
        raise ValueError("historical slope receipt sha256 is invalid")
    historical_slope = _finite(receipt["slope_m_per_s_per_mm"], "historical source slope")
    if historical_slope not in parsed_slopes:
        raise ValueError("source slopes must include the frozen historical slope")
    ReflectronGeometry(**config["reflectron"])
    _keys(config["theory_controls"], "field1_v_per_mm center_to_grid1_mm grid2_voltage_fraction reflectron_stage1_voltage_v nominal_energy_per_charge_v focus_drift_mm characteristic_half_width_mm condition_limit coefficient_tolerance_ns order", "theory controls")
    controls = config["theory_controls"]
    for name in ("field1_v_per_mm", "center_to_grid1_mm", "reflectron_stage1_voltage_v", "nominal_energy_per_charge_v", "characteristic_half_width_mm", "condition_limit", "coefficient_tolerance_ns"):
        _finite(controls[name], name, positive=True)
    if not 0.0 < _finite(controls["grid2_voltage_fraction"], "grid2 voltage fraction") < 1.0:
        raise ValueError("grid2 voltage fraction must be between zero and one")
    _finite(controls["focus_drift_mm"], "focus drift")
    if isinstance(controls["order"], bool) or not isinstance(controls["order"], int) or controls["order"] < 4:
        raise ValueError("theory order must be an integer at least four")
    _keys(config["sampling"], "particle_count replicate_count", "sampling")
    for name, value in config["sampling"].items():
        validate_positive_particle_count(value)
    if config["sampling"]["particle_count"] < 3:
        raise ValueError("at least three particles are required")
    if config["analysis_contract"] != "config/analysis_contract.json":
        raise ValueError("use the canonical analysis contract")
    if not isinstance(config["scope"], str) or not config["scope"].strip():
        raise ValueError("scope is required")


def _receipt_path(config: dict[str, Any]) -> Path:
    """Resolve and verify the declared historical scalar provenance input."""
    receipt = REPO_ROOT.parent / config["historical_slope_receipt"]["path"]
    if not receipt.is_file():
        raise ValueError(f"historical slope receipt is unavailable: {receipt}")
    if file_sha256(receipt).lower() != config["historical_slope_receipt"]["sha256"].lower():
        raise ValueError("historical slope receipt hash differs from the scientific contract")
    data = load_json(receipt)
    observed = data.get("source_state", {}).get("ols_slope_vz_m_per_s_per_mm")
    if observed is None or not math.isclose(float(observed), config["historical_slope_receipt"]["slope_m_per_s_per_mm"], rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("historical receipt slope differs from the scientific contract")
    return receipt


def _source(config: dict[str, Any], slope: float) -> NumericalSourceSpec:
    return NumericalSourceSpec(**config["source_template"], velocity_slope_m_per_s_per_mm=slope)


def _arms(config: dict[str, Any], slope: float) -> dict[str, Any]:
    """Solve dependent three-zone fields for zero-slope and matching-slope designs."""
    source, reflectron, controls = _source(config, slope), ReflectronGeometry(**config["reflectron"]), config["theory_controls"]

    def design(design_slope: float):
        return solve_linear_third_order_design(
            replace(source, velocity_slope_m_per_s_per_mm=design_slope), reflectron,
            field1_v_per_mm=controls["field1_v_per_mm"], center_to_grid1_mm=controls["center_to_grid1_mm"],
            grid2_voltage_fraction=controls["grid2_voltage_fraction"], reflectron_stage1_voltage_v=controls["reflectron_stage1_voltage_v"],
            nominal_energy_per_charge_v=controls["nominal_energy_per_charge_v"], focus_drift_mm=controls["focus_drift_mm"],
            characteristic_half_width_mm=controls["characteristic_half_width_mm"], condition_limit=controls["condition_limit"],
            coefficient_tolerance_ns=controls["coefficient_tolerance_ns"], order=controls["order"]).point

    return {"zero_slope_design": design(0.0), "matching_slope_design": design(slope)}


def _record_case(config: dict[str, Any], slope: float, seed: int, result_dir: Path) -> dict[str, Any]:
    """Propagate a paired synthetic source through its derived two-arm comparison."""
    source = build_numerical_source(_source(config, slope), particle_count=config["sampling"]["particle_count"],
        seed=seed, full_width_mm=config["full_width_mm"], residual_sigma_m_per_s=config["residual_sigma_m_per_s"])
    points = _arms(config, slope)
    settings = _settings()
    outputs = {name: propagate_ideal_source(source, point, settings=settings) for name, point in points.items()}
    csv_path = result_dir / f"slope_{slope:g}__seed{seed}__particles.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["particle_id", "source_x_mm", "source_velocity_m_per_s", "source_residual_m_per_s", *[
            f"{name}__{field}" for name in outputs for field in ("classification", "tof_us")]])
        for index, particle_id in enumerate(source.particle_id):
            row = [int(particle_id), float(source.source_x_mm[index]), float(source.velocity_z_m_per_s[index]),
                   float(source.residual_m_per_s[index])]
            for result in outputs.values():
                row.extend([str(result.classification[index]), float(result.tof_us[index]) if np.isfinite(result.tof_us[index]) else ""])
            writer.writerow(row)
    arms: dict[str, Any] = {}
    for name, result in outputs.items():
        metrics = result.summary.get("peak_metrics") or {}
        if result.summary["status"] == "PEAK_METRICS_FAILED":
            raise ArithmeticError(f"{name}: {result.summary['reason']}")
        arms[name] = {**result.summary, "resolution": metrics.get("mass_resolution"),
                      "fwhm_ns": metrics.get("direct_fwhm_tof_ns")}
    zero, matched = arms["zero_slope_design"], arms["matching_slope_design"]
    gain = 100.0 * (matched["resolution"] / zero["resolution"] - 1.0)
    return {"source_slope_m_per_s_per_mm": slope, "seed": seed, "arms": arms,
            "resolution_gain_percent": gain, "working_points": {name: point.to_dict() for name, point in points.items()},
            "particles": {"path": csv_path.name, "bytes": csv_path.stat().st_size, "sha256": file_sha256(csv_path)}}


def execute_slope_scan(config_path: Path, *, seed: int, run_id: str, resume_from: Path | None,
                       artifact_root: Path) -> Path:
    """Freeze, run and publish the declared synthetic affine-slope mechanism scan."""
    config = load_json(config_path)
    validate_slope_scan_config(config)
    if resume_from is not None:
        raise ValueError("slope scan does not support resume; publish a new immutable run")
    receipt = _receipt_path(config)
    run_dir, identity = _prepare_run(config_path, seed=seed, run_id=run_id, resume_from=None,
        artifact_root=artifact_root, mode="ideal_source_slope_scan", extra_inputs={
            "slope_scan_workflow": Path(__file__), "historical_slope_receipt": receipt})
    started, status, error, stage = time.perf_counter(), "success", None, "paired_ideal_propagation"
    records: list[dict[str, Any]] = []
    try:
        for slope in config["source_slopes_m_per_s_per_mm"]:
            for replicate in range(config["sampling"]["replicate_count"]):
                record = _record_case(config, float(slope), seed + replicate, run_dir / "results")
                record["numerical_identity"] = identity
                _write_json(run_dir / "results" / f"slope_{slope:g}__seed{seed + replicate}.json", record)
                records.append(record)
                print(f"IDEAL_SLOPE_SCAN EVENT=CASE_COMPLETE SLOPE={slope} REPLICATE={replicate + 1}/{config['sampling']['replicate_count']}", flush=True)
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        (run_dir / "logs" / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    groups = []
    for slope in config["source_slopes_m_per_s_per_mm"]:
        subset = [record for record in records if record["source_slope_m_per_s_per_mm"] == slope]
        gains = [record["resolution_gain_percent"] for record in subset]
        groups.append({"source_slope_m_per_s_per_mm": slope, "completed_replicates": len(subset),
                       "gain_percent_range": [min(gains), max(gains)] if gains else None,
                       "matching_resolution_range": [min(r["arms"]["matching_slope_design"]["resolution"] for r in subset),
                                                       max(r["arms"]["matching_slope_design"]["resolution"] for r in subset)] if subset else None})
    summary = {"status": status, "numerical_identity": identity, "elapsed_s": time.perf_counter() - started,
               "failure_stage": stage if error else None, "failure_reason": error, "groups": groups,
               "claim": "Synthetic affine source, exact one-dimensional static fields. Each nonzero source slope is compared with a zero-slope-derived and matching-slope-derived working point; no 3D, source-production, transmission or global-optimum claim.",
               "historical_slope_used_as_scalar_reference_only": config["historical_slope_receipt"]}
    _write_json(run_dir / "summary.json", summary)
    lines = ["# Synthetic affine-source slope scan", "", summary["claim"], "", "|k (m/s/mm)|Seed|R zero-slope design|R matching design|Gain (%)|", "|---:|---:|---:|---:|---:|"]
    for record in records:
        lines.append(f"|{record['source_slope_m_per_s_per_mm']}|{record['seed']}|{record['arms']['zero_slope_design']['resolution']}|{record['arms']['matching_slope_design']['resolution']}|{record['resolution_gain_percent']}|")
    (run_dir / "results" / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _publish_manifest(run_dir, status)
    print(f"IDEAL_SLOPE_SCAN STATUS={status} RUN={run_dir} REASON={error or 'all declared slopes completed'}", flush=True)
    return run_dir
