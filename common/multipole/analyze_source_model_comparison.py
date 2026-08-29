"""Compare verified planar and independent-volume multipole source runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.contracts.verify_run_manifest import record_path, verify_record
from common.multipole.campaign_analysis import SERIES_DELTA_FIELDS, summarize_run
from common.multipole.numerical_observables import (
    manifest_record,
    primary_state_filename,
    run_data,
)


ROLE = "multipole_source_model_comparison"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest().upper()


def _verify_success_manifest(path: Path) -> dict[str, Any]:
    """Verify every frozen record before reading a source-model run."""

    path = path.resolve()
    manifest = _load_json(path)
    if manifest.get("status") != "success":
        raise ValueError(f"source-model arm is not a success manifest: {path}")
    manifest_copy_dir = path.parent
    verify_record("run_config", manifest["run_config"], base_dir=manifest_copy_dir)
    # Campaign analysis freezes a copy of each source manifest.  The copied
    # record still deliberately points at the original, hash-verified source
    # run, which is the authority for its input/output records.
    config_path = record_path(manifest["run_config"], base_dir=manifest_copy_dir)
    run_dir = config_path.parent
    for name, record in manifest.get("inputs", {}).items():
        verify_record(f"input {name}", record, base_dir=run_dir)
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record, base_dir=run_dir)
    return manifest


def _terminal_fingerprint(manifest: dict[str, Any], run_dir: Path) -> str:
    try:
        resolved_path = record_path(
            manifest["inputs"]["multipole_resolved_design"], base_dir=run_dir
        )
        resolved = _load_json(resolved_path)
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise ValueError("source-model arm lacks a readable resolved terminal") from error
    terminal = {
        "interfaces_exit": resolved.get("interfaces_mm", {}).get("exit"),
        "downstream_terminal": resolved.get("downstream_terminal"),
        "static_electrodes_V": resolved.get("static_electrodes_V"),
    }
    if terminal["interfaces_exit"] is None:
        raise ValueError("source-model arm lacks the resolved exit terminal")
    return _canonical_sha256(terminal)


def _source_authority(data: dict[str, Any]) -> str:
    authority = data["config"].get("provenance", {}).get("particle_source_authority_sha256")
    if isinstance(authority, str) and len(authority) == 64:
        return authority.upper()
    # A volume snapshot intentionally bypasses planar phase derivation, so it
    # has no derivation provenance.  Its frozen manifest input is the direct,
    # hash-verified source authority instead.
    record = data["manifest"].get("inputs", {}).get("particle_source")
    source_sha = record.get("sha256") if isinstance(record, dict) else None
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise ValueError("source-model arm lacks particle-source authority")
    return source_sha.upper()


def _source_distribution(manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Summarize the frozen source's axial phase space without a fit model."""

    try:
        source_path = record_path(manifest["inputs"]["particle_source"], base_dir=run_dir)
        with source_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        x = [float(row["x_mm"]) for row in rows]
        y = [float(row["y_mm"]) for row in rows]
        z = [float(row["z_mm"]) for row in rows]
        vx = [float(row["vx_m_s"]) for row in rows]
        vy = [float(row["vy_m_s"]) for row in rows]
        vz = [float(row["vz_m_s"]) for row in rows]
        births = [float(row["birth_time_s"]) for row in rows]
        masses = [float(row["mass_amu"]) for row in rows]
        charges = [int(row["charge_state"]) for row in rows]
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise ValueError("source-model arm lacks a readable canonical particle source") from error
    if not z or any(len(values) != len(z) for values in (x, y, vx, vy, vz, births, masses, charges)):
        raise ValueError("source-model arm has an empty or inconsistent particle source")
    count = len(z)
    mean_z, mean_vz = sum(z) / count, sum(vz) / count
    centered_z = [value - mean_z for value in z]
    centered_vz = [value - mean_vz for value in vz]
    z_sum_sq = sum(value * value for value in centered_z)
    vz_sum_sq = sum(value * value for value in centered_vz)
    covariance_sum = sum(left * right for left, right in zip(centered_z, centered_vz))
    correlation = None if z_sum_sq == 0 or vz_sum_sq == 0 else covariance_sum / math.sqrt(z_sum_sq * vz_sum_sq)
    slope = None if z_sum_sq == 0 else covariance_sum / z_sum_sq
    radial = [math.hypot(x_value, y_value) for x_value, y_value in zip(x, y)]
    energy = [
        0.5 * mass * AMU_KG * (x_velocity * x_velocity + y_velocity * y_velocity + z_velocity * z_velocity)
        / (abs(charge) * ELEMENTARY_CHARGE_C)
        for mass, charge, x_velocity, y_velocity, z_velocity in zip(masses, charges, vx, vy, vz)
    ]
    mean_energy = sum(energy) / count
    return {
        "particle_count": count,
        "birth_time_min_s": min(births),
        "birth_time_max_s": max(births),
        "z_min_mm": min(z),
        "z_max_mm": max(z),
        "z_mean_mm": mean_z,
        "z_rms_spread_mm": math.sqrt(z_sum_sq / count),
        "radial_rms_mm": math.sqrt(sum(value * value for value in radial) / count),
        "radial_max_mm": max(radial),
        "vz_mean_m_s": mean_vz,
        "vz_rms_spread_m_s": math.sqrt(vz_sum_sq / count),
        "kinetic_energy_mean_eV": mean_energy,
        "kinetic_energy_rms_spread_eV": math.sqrt(sum((value - mean_energy) ** 2 for value in energy) / count),
        "z_vz_pearson_correlation": correlation,
        "z_vz_linear_slope_m_s_per_mm": slope,
    }


def _loss_census(data: dict[str, Any]) -> dict[str, Any]:
    """Return a per-terminal-reason census when terminal events were retained."""

    manifest = data["manifest"]
    state_path = manifest_record(manifest, primary_state_filename(manifest, data["solver"]))
    latest: dict[int, dict[str, str]] = {}
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            particle_id = int(row["particle_id"])
            if particle_id in data["lost_particle_ids"]:
                latest[particle_id] = row
    reasons: dict[str, int] = {}
    unavailable = 0
    for particle_id in data["lost_particle_ids"]:
        row = latest.get(particle_id)
        reason = "" if row is None else str(row.get("terminal_reason", ""))
        if not reason or reason == "none":
            unavailable += 1
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "available": unavailable == 0,
        "lost_particle_count": len(data["lost_particle_ids"]),
        "classified_particle_count": len(data["lost_particle_ids"]) - unavailable,
        "unclassified_particle_count": unavailable,
        "by_terminal_reason": dict(sorted(reasons.items())),
    }


def _resource_metrics(manifest: dict[str, Any], run_dir: Path) -> dict[str, float] | None:
    records = [
        record for record in manifest.get("outputs", [])
        if record_path(record, base_dir=run_dir).name == "resource_usage.json"
    ]
    if len(records) != 1:
        return None
    value = _load_json(record_path(records[0], base_dir=run_dir))
    fields = (
        "wall_clock_seconds",
        "peak_process_tree_working_set_bytes",
        "peak_run_directory_bytes",
        "final_retained_bytes",
    )
    try:
        metrics = {field: float(value[field]) for field in fields}
    except (KeyError, TypeError, ValueError):
        return None
    return metrics if all(math.isfinite(item) for item in metrics.values()) else None


def _arm(manifest_path: Path, label: str) -> dict[str, Any]:
    manifest = _verify_success_manifest(manifest_path)
    data = run_data(manifest_path)
    run_dir = manifest_path.resolve().parent
    summary = summarize_run(data)
    return {
        "label": label,
        "manifest_path": str(manifest_path.resolve()),
        "summary": summary,
        "identity": {
            "project_id": data["project"],
            "solver": data["solver"],
            "design_profile_id": data["config"].get("parameters", {}).get("design_profile_id"),
            "physical_resolved_design_sha256": data["physical_resolved_design_sha256"],
            "numerics": data["numerics"],
            "terminal_fingerprint_sha256": _terminal_fingerprint(manifest, run_dir),
            "source_particle_ids": data["source_particle_ids"],
            "source_particle_count": len(data["source_particle_ids"]),
            "particle_source_authority_sha256": _source_authority(data),
        },
        "loss_census": _loss_census(data),
        "resource_metrics": _resource_metrics(manifest, run_dir),
        "source_distribution": _source_distribution(manifest, run_dir),
    }


def _require_equal_identity(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    left, right = baseline["identity"], candidate["identity"]
    for field in (
        "project_id",
        "solver",
        "design_profile_id",
        "physical_resolved_design_sha256",
        "numerics",
        "terminal_fingerprint_sha256",
        "source_particle_ids",
        "source_particle_count",
    ):
        if left[field] != right[field]:
            raise ValueError(f"source-model arms differ in required identity: {field}")
    if left["particle_source_authority_sha256"] == right["particle_source_authority_sha256"]:
        raise ValueError("source-model arms must have different source authorities")


def analyze_source_models(
    baseline_manifest: Path,
    candidate_manifest: Path,
    *,
    baseline_label: str = "planar_baseline",
    candidate_label: str = "independent_axial_volume_candidate",
) -> dict[str, Any]:
    """Create a descriptive, source-only comparison after strict identity checks."""

    baseline = _arm(baseline_manifest, baseline_label)
    candidate = _arm(candidate_manifest, candidate_label)
    _require_equal_identity(baseline, candidate)
    baseline_summary, candidate_summary = baseline["summary"], candidate["summary"]
    resource_delta = None
    if baseline["resource_metrics"] is not None and candidate["resource_metrics"] is not None:
        resource_delta = {
            name: candidate["resource_metrics"][name] - baseline["resource_metrics"][name]
            for name in baseline["resource_metrics"]
        }
    return {
        "schema_version": 1,
        "role": ROLE,
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "identity": {
            key: baseline["identity"][key]
            for key in (
                "project_id", "solver", "design_profile_id", "physical_resolved_design_sha256",
                "numerics", "terminal_fingerprint_sha256", "source_particle_ids", "source_particle_count",
            )
        },
        "baseline": baseline,
        "candidate": candidate,
        "candidate_minus_baseline": {
            "transport_exit_metrics": {
                name: candidate_summary[name] - baseline_summary[name] for name in SERIES_DELTA_FIELDS
            },
            "centroid_shift_mm": math.hypot(
                candidate_summary["centroid_x_mm"] - baseline_summary["centroid_x_mm"],
                candidate_summary["centroid_y_mm"] - baseline_summary["centroid_y_mm"],
            ),
            "resource_metrics": resource_delta,
        },
        "claim_limit": (
            "Paired N=1000 source-model transport comparison only; no convergence, detector, "
            "Candidate, or Formal claim."
        ),
    }


def markdown_report(document: dict[str, Any]) -> str:
    """Render a concise human-readable counterpart to the JSON result."""

    baseline, candidate = document["baseline"], document["candidate"]
    delta = document["candidate_minus_baseline"]["transport_exit_metrics"]
    lines = [
        "# 平面源与独立轴向体积源：八极杆传输对比", "",
        "仅来源模型不同；设计、数值、终端和 N=1000 粒子 ID 母队列已逐项核对。", "",
        "|臂|z 范围 (mm)|z RMS (mm)|径向 RMS (mm)|动能均值 ± RMS (eV)|vz RMS (m/s)|z–vz Pearson r|同刻释放|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in (baseline, candidate):
        source = arm["source_distribution"]
        correlation = source["z_vz_pearson_correlation"]
        correlation_text = "无定义" if correlation is None else f"{correlation:+.5f}"
        snapshot = "是" if source["birth_time_min_s"] == source["birth_time_max_s"] else "否"
        lines.append(
            f"|{arm['label']}|{source['z_min_mm']:.4f} 至 {source['z_max_mm']:.4f}|"
            f"{source['z_rms_spread_mm']:.4f}|{source['radial_rms_mm']:.4f}|"
            f"{source['kinetic_energy_mean_eV']:.4f} ± {source['kinetic_energy_rms_spread_eV']:.4f}|"
            f"{source['vz_rms_spread_m_s']:.4f}|{correlation_text}|{snapshot}|")
    lines.extend([
        "",
        "|臂|传输率|空间 RMS (mm)|角 RMS (°)|平均能量 (eV)|平均飞行时间 (µs)|损失分类|",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for arm in (baseline, candidate):
        summary, census = arm["summary"], arm["loss_census"]
        loss = "不可用" if not census["available"] else str(census["lost_particle_count"])
        lines.append(
            f"|{arm['label']}|{summary['transmission']:.4f}|{summary['centered_spatial_rms_spread_mm']:.4f}|"
            f"{summary['centered_angular_rms_spread_deg']:.4f}|{summary['mean_energy_eV']:.4f}|"
            f"{summary['mean_elapsed_time_us']:.4f}|{loss}|")
    lines.extend([
        "", "候选 − 基线："
        f"传输率 {delta['transmission']:+.4f}，空间 RMS {delta['centered_spatial_rms_spread_mm']:+.4f} mm，"
        f"角 RMS {delta['centered_angular_rms_spread_deg']:+.4f}°，"
        f"平均飞行时间 {delta['mean_elapsed_time_us']:+.4f} µs。",
    ])
    resource = document["candidate_minus_baseline"]["resource_metrics"]
    if resource is not None:
        lines.append(f"资源：墙钟时间 {resource['wall_clock_seconds']:+.3f} s。")
    lines.extend(["", f"声明边界：{document['claim_limit']}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--series", action="append", nargs=2, metavar=("LABEL", "MANIFEST"))
    inputs.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--candidate-manifest", type=Path)
    parser.add_argument("--baseline-label")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    args = parser.parse_args()
    output = args.output or args.output_json
    markdown = args.markdown or args.output_markdown
    if output is None or markdown is None:
        parser.error("--output and --markdown are required")
    if args.series:
        if len(args.series) != 2 or not args.baseline_label:
            parser.error("--series requires exactly two arms and --baseline-label")
        labels = [label for label, _ in args.series]
        if len(set(labels)) != 2 or args.baseline_label not in labels:
            parser.error("--series labels must be unique and include --baseline-label")
        by_label = {label: Path(path) for label, path in args.series}
        candidate_label = next(label for label in labels if label != args.baseline_label)
        document = analyze_source_models(
            by_label[args.baseline_label], by_label[candidate_label],
            baseline_label=args.baseline_label, candidate_label=candidate_label,
        )
    else:
        if args.candidate_manifest is None or args.baseline_label:
            parser.error("--baseline-manifest requires --candidate-manifest and no --baseline-label")
        document = analyze_source_models(args.baseline_manifest, args.candidate_manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown.write_text(markdown_report(document), encoding="utf-8")
    print("SOURCE_MODEL_COMPARISON=PASS PARTICLES=" + str(document["identity"]["source_particle_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
