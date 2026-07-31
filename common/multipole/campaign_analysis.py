"""Summarize paired multipole campaign exit states without making a qualification claim."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.numerical_qualification import run_data


MODES = {
    "no_acceleration",
    "segmented_acceleration",
    "exit_aperture_plate_acceleration",
}
PAIR_DEFINITIONS = (
    (
        "segmented_vs_no_acceleration",
        "no_acceleration",
        "segmented_acceleration",
    ),
    (
        "exit_aperture_plate_vs_no_acceleration",
        "no_acceleration",
        "exit_aperture_plate_acceleration",
    ),
    (
        "exit_aperture_plate_vs_segmented",
        "segmented_acceleration",
        "exit_aperture_plate_acceleration",
    ),
)


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _rms_about(values: list[float], center: float) -> float:
    return math.sqrt(math.fsum((value - center) ** 2 for value in values) / len(values))


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    fraction = index - low
    return ordered[low] + fraction * (ordered[high] - ordered[low])


def _correlation(left: list[float], right: list[float]) -> float | None:
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = math.fsum(
        (x - left_mean) * (y - right_mean)
        for x, y in zip(left, right, strict=True)
    )
    left_norm = math.sqrt(math.fsum((x - left_mean) ** 2 for x in left))
    right_norm = math.sqrt(math.fsum((y - right_mean) ** 2 for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return numerator / (left_norm * right_norm)


def summarize_run(data: dict[str, Any]) -> dict[str, Any]:
    """Return centroid/deviation/tail metrics for the canonical handoff population."""

    rows = list(data["_handoff"].values())
    if not rows:
        raise ValueError("run has no handoff rows")
    values = {
        name: [float(row[name]) for row in rows]
        for name in (
            "transverse_x_mm",
            "transverse_y_mm",
            "radial_position_mm",
            "divergence_angle_deg",
            "kinetic_energy_eV",
            "elapsed_time_us",
            "velocity_axial_m_s",
            "velocity_x_m_s",
            "velocity_y_m_s",
        )
    }
    theta_x = [
        math.degrees(math.atan2(vx, axial))
        for vx, axial in zip(
            values["velocity_x_m_s"], values["velocity_axial_m_s"], strict=True
        )
    ]
    theta_y = [
        math.degrees(math.atan2(vy, axial))
        for vy, axial in zip(
            values["velocity_y_m_s"], values["velocity_axial_m_s"], strict=True
        )
    ]
    observables = data["observables"]
    direction_tilt = math.degrees(
        math.acos(
            max(-1.0, min(1.0, float(observables["mean_beam_direction_unit_z"])))
        )
    )
    energy_mean = _mean(values["kinetic_energy_eV"])
    time_mean = _mean(values["elapsed_time_us"])
    return {
        "run_id": data["run_id"],
        "project_id": data["project"],
        "solver": data["solver"],
        "particle_source_sha256": data["particle_source_sha256"],
        "transmitted_particles": len(rows),
        "transmission": float(observables["transmission"]),
        "centroid_x_mm": float(observables["transverse_centroid_x_mm"]),
        "centroid_y_mm": float(observables["transverse_centroid_y_mm"]),
        "centered_spatial_rms_spread_mm": float(
            observables["centered_spatial_rms_spread_mm"]
        ),
        "mean_direction_tilt_deg": direction_tilt,
        "mean_direction_x_deg": _mean(theta_x),
        "mean_direction_y_deg": _mean(theta_y),
        "centered_angular_rms_spread_deg": float(
            observables["centered_angular_rms_spread_deg"]
        ),
        "mean_energy_eV": energy_mean,
        "centered_rms_energy_spread_eV": _rms_about(
            values["kinetic_energy_eV"], energy_mean
        ),
        "mean_elapsed_time_us": time_mean,
        "centered_rms_elapsed_time_spread_us": _rms_about(
            values["elapsed_time_us"], time_mean
        ),
        "p95_radius_mm": _percentile(values["radial_position_mm"], 0.95),
        "p99_radius_mm": _percentile(values["radial_position_mm"], 0.99),
        "p95_divergence_deg": _percentile(
            values["divergence_angle_deg"], 0.95
        ),
        "p99_divergence_deg": _percentile(
            values["divergence_angle_deg"], 0.99
        ),
        "position_angle_correlation_x": _correlation(
            values["transverse_x_mm"], theta_x
        ),
        "position_angle_correlation_y": _correlation(
            values["transverse_y_mm"], theta_y
        ),
    }


def _delta(left: dict[str, Any], right: dict[str, Any], field: str) -> float:
    return float(right[field]) - float(left[field])


def compare_pair(
    no_acceleration: dict[str, Any],
    segmented: dict[str, Any],
) -> dict[str, Any]:
    if (
        no_acceleration["project_id"] != segmented["project_id"]
        or no_acceleration["particle_source_sha256"]
        != segmented["particle_source_sha256"]
    ):
        raise ValueError("paired campaign arms differ in project or particle source")
    centroid_shift = math.hypot(
        _delta(no_acceleration, segmented, "centroid_x_mm"),
        _delta(no_acceleration, segmented, "centroid_y_mm"),
    )
    fields = (
        "transmission",
        "centered_spatial_rms_spread_mm",
        "mean_direction_tilt_deg",
        "centered_angular_rms_spread_deg",
        "mean_energy_eV",
        "centered_rms_energy_spread_eV",
        "mean_elapsed_time_us",
        "centered_rms_elapsed_time_spread_us",
        "p95_radius_mm",
        "p99_radius_mm",
        "p95_divergence_deg",
        "p99_divergence_deg",
    )
    return {
        "no_acceleration_run_id": no_acceleration["run_id"],
        "segmented_acceleration_run_id": segmented["run_id"],
        "centroid_shift_mm": centroid_shift,
        "segmented_minus_no_acceleration": {
            field: _delta(no_acceleration, segmented, field) for field in fields
        },
    }


def compare_modes(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_mode: str,
    right_mode: str,
) -> dict[str, Any]:
    """Compare two declared modes with an explicit right-minus-left direction."""

    if (
        left["project_id"] != right["project_id"]
        or left["particle_source_sha256"] != right["particle_source_sha256"]
    ):
        raise ValueError("paired campaign arms differ in project or particle source")
    fields = (
        "transmission",
        "centered_spatial_rms_spread_mm",
        "mean_direction_tilt_deg",
        "centered_angular_rms_spread_deg",
        "mean_energy_eV",
        "centered_rms_energy_spread_eV",
        "mean_elapsed_time_us",
        "centered_rms_elapsed_time_spread_us",
        "p95_radius_mm",
        "p99_radius_mm",
        "p95_divergence_deg",
        "p99_divergence_deg",
    )
    return {
        "left_mode": left_mode,
        "right_mode": right_mode,
        "left_run_id": left["run_id"],
        "right_run_id": right["run_id"],
        "centroid_shift_mm": math.hypot(
            _delta(left, right, "centroid_x_mm"),
            _delta(left, right, "centroid_y_mm"),
        ),
        "right_minus_left": {
            field: _delta(left, right, field) for field in fields
        },
    }


def analyze(arms: list[tuple[str, str, str, Path]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    series: list[dict[str, Any]] = []
    for family, mode, label, manifest in arms:
        if mode not in MODES:
            raise ValueError(f"unsupported campaign analysis mode: {mode}")
        if mode in grouped.setdefault(family, {}):
            raise ValueError(f"duplicate family/mode arm: {family}/{mode}")
        summary = summarize_run(run_data(manifest))
        summary.update({"family": family, "mode": mode, "label": label})
        grouped[family][mode] = summary
        series.append(summary)
    comparisons: dict[str, dict[str, dict[str, Any]]] = {}
    for family, modes in grouped.items():
        required_modes = {"no_acceleration", "segmented_acceleration"}
        if not required_modes.issubset(modes):
            raise ValueError(
                "family must contain no-acceleration and segmented modes: "
                f"{family}"
            )
        family_pairs = {}
        for pair_id, left_mode, right_mode in PAIR_DEFINITIONS:
            if left_mode in modes and right_mode in modes:
                family_pairs[pair_id] = compare_modes(
                    modes[left_mode],
                    modes[right_mode],
                    left_mode=left_mode,
                    right_mode=right_mode,
                )
        comparisons[family] = family_pairs
    return {
        "schema_version": 2,
        "role": "multipole_campaign_engineering_summary",
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "series": series,
        "comparisons": comparisons,
        "claim_limit": (
            "N=100 SIMION handoff diagnostics for the declared arms; "
            "not a convergence, optimization, solver-equivalence, Candidate, or Formal claim."
        ),
    }


def markdown_report(document: dict[str, Any]) -> str:
    lines = [
        "# 多极杆无加速、分段加速与出口带孔接口板加速 H15 对照",
        "",
        "本报告为 N=100 SIMION 事后工程描述。全部指标取规范 handoff 事件；"
        "它不证明数值收敛、最优设计、求解器等价、Candidate 或 Formal 资格。",
        "",
        "## 各臂出口状态",
        "",
        "|系列|透射|质心 x / y (mm)|中心化空间 RMS (mm)|平均方向倾角 (°)|中心化角 RMS (°)|平均能量 / 展宽 (eV)|平均时间 / 展宽 (µs)|p95 半径 / 角度|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in document["series"]:
        lines.append(
            "|{label}|{transmission:.3f}|{centroid_x_mm:.4f} / "
            "{centroid_y_mm:.4f}|{centered_spatial_rms_spread_mm:.4f}|"
            "{mean_direction_tilt_deg:.4f}|{centered_angular_rms_spread_deg:.4f}|"
            "{mean_energy_eV:.4f} / {centered_rms_energy_spread_eV:.4f}|"
            "{mean_elapsed_time_us:.4f} / "
            "{centered_rms_elapsed_time_spread_us:.4f}|"
            "{p95_radius_mm:.4f} / {p95_divergence_deg:.4f}|".format(**item)
        )
    lines.extend(
        [
            "",
            "## 模式间变化",
            "",
            "正值表示右侧模式更大，负值表示更小。",
            "",
            "|家族|比较（右−左）|质心位移 (mm)|空间 RMS Δ (mm)|平均方向倾角 Δ (°)|角 RMS Δ (°)|平均能量 Δ (eV)|能量展宽 Δ (eV)|平均时间 Δ (µs)|p95 角度 Δ (°)|",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for family, family_pairs in document["comparisons"].items():
        for comparison in family_pairs.values():
            delta = comparison["right_minus_left"]
            pair_label = (
                f"{comparison['right_mode']} − {comparison['left_mode']}"
            )
            lines.append(
                f"|{family}|{pair_label}|"
                f"{comparison['centroid_shift_mm']:.4f}|"
                f"{delta['centered_spatial_rms_spread_mm']:.4f}|"
                f"{delta['mean_direction_tilt_deg']:.4f}|"
                f"{delta['centered_angular_rms_spread_deg']:.4f}|"
                f"{delta['mean_energy_eV']:.4f}|"
                f"{delta['centered_rms_energy_spread_eV']:.4f}|"
                f"{delta['mean_elapsed_time_us']:.4f}|"
                f"{delta['p95_divergence_deg']:.4f}|"
            )
    lines.extend(["", f"声明边界：{document['claim_limit']}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arm",
        action="append",
        nargs=4,
        metavar=("FAMILY", "MODE", "LABEL", "MANIFEST"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    document = analyze(
        [(family, mode, label, Path(path)) for family, mode, label, path in args.arm]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(markdown_report(document), encoding="utf-8")
    print(f"MULTIPOLE_CAMPAIGN_ANALYSIS=PASS FAMILIES={len(document['comparisons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
