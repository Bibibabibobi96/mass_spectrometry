"""Compare one opened S1 joint field with the frozen closed-shield reference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


RF_PROJECT = Path(__file__).resolve().parents[1]
OA_ANALYSIS = Path(__file__).resolve().parent
if not (OA_ANALYSIS / "analyze_accelerator_transverse_field_uniformity.py").is_file():
    OA_ANALYSIS = RF_PROJECT.parent / "oa_tof" / "analysis"
sys.path.insert(0, str(OA_ANALYSIS))
from analyze_accelerator_transverse_field_uniformity import analyze  # noqa: E402


def relative_rms(delta: np.ndarray, scale: float) -> float:
    return float(np.sqrt(np.mean(np.square(delta))) / scale)


def evaluation_half_width(port_full_width_mm: float, closed_reference_full_width_mm: float) -> float:
    if port_full_width_mm < 0.0 or closed_reference_full_width_mm <= 0.0:
        raise ValueError("S1 evaluation widths must be non-negative with a positive reference width")
    if np.isclose(port_full_width_mm, 0.0, rtol=0.0, atol=1e-12):
        return closed_reference_full_width_mm / 2.0
    return port_full_width_mm / 2.0


def component_profile_envelope(samples: pd.DataFrame) -> pd.DataFrame:
    """Resolve Ex and Ey profile perturbations instead of hiding them in |E_perp|."""
    axis = samples[np.isclose(samples["y_mm"], 0.0)].sort_values("z_mm")
    z_axis = axis["z_mm"].to_numpy(float)
    ez_scale = float(np.sqrt(np.mean(np.square(axis["Ez_V_per_m"].to_numpy(float)))))
    if ez_scale <= 0.0:
        raise ValueError("candidate axial-field scale is not positive")
    rows = []
    for y_mm, group in samples.groupby("y_mm"):
        profile = group.sort_values("z_mm")
        if not np.allclose(profile["z_mm"].to_numpy(float), z_axis, rtol=0.0, atol=1e-10):
            raise ValueError("component profiles do not share identical z samples")
        rows.append({
            "abs_y_mm": abs(float(y_mm)),
            "ex_profile_relative_rms": relative_rms(
                profile["Ex_V_per_m"].to_numpy(float) - axis["Ex_V_per_m"].to_numpy(float),
                ez_scale,
            ),
            "ey_profile_relative_rms": relative_rms(
                profile["Ey_V_per_m"].to_numpy(float) - axis["Ey_V_per_m"].to_numpy(float),
                ez_scale,
            ),
        })
    return pd.DataFrame(rows).groupby("abs_y_mm", as_index=False).max()


def field_line_integrals(injection: pd.DataFrame, prefix: str) -> dict[str, float]:
    ordered = injection.sort_values("x_mm")
    x_m = ordered["x_mm"].to_numpy(float) * 1e-3
    integrate = np.trapezoid
    return {
        f"{axis.lower()}_line_integral_V": float(integrate(
            ordered[f"{prefix}_{axis}_V_per_m"].to_numpy(float), x_m
        ))
        for axis in ("Ex", "Ey", "Ez")
    }


def normalize_static_reference(samples: pd.DataFrame) -> pd.DataFrame:
    if "sample_type" in samples.columns:
        samples = samples[samples["sample_type"] == "accelerator_profile"].copy()
    rename = {
        "static_Ex_V_per_m": "Ex_V_per_m",
        "static_Ey_V_per_m": "Ey_V_per_m",
        "static_Ez_V_per_m": "Ez_V_per_m",
        "static_potential_V": "potential_V",
    }
    samples = samples.rename(columns=rename)
    required = {"x_mm", "y_mm", "z_mm", "Ex_V_per_m", "Ey_V_per_m", "Ez_V_per_m", "potential_V"}
    missing = required - set(samples.columns)
    if missing:
        raise ValueError(f"closed reference is missing columns: {sorted(missing)}")
    return samples


def vector_magnitude(samples: pd.DataFrame, prefix: str) -> np.ndarray:
    return np.sqrt(sum(np.square(samples[f"{prefix}_{axis}_V_per_m"].to_numpy(float)) for axis in (
        "Ex", "Ey", "Ez"
    )))


def shielding_diagnostics(
    injection: pd.DataFrame, entry_x_mm: float, rf_peak_scale: float,
) -> dict[str, float]:
    upstream = injection[injection["x_mm"] <= entry_x_mm + 1e-12]
    source = injection[injection["x_mm"] >= float(injection["x_mm"].max()) - 0.5 - 1e-12]
    if upstream.empty or source.empty:
        raise ValueError("injection-axis samples do not cover the RF region and oa source neighborhood")
    static_all = vector_magnitude(injection, "static")
    rf_all = vector_magnitude(injection, "rf") * rf_peak_scale
    static_upstream = vector_magnitude(upstream, "static")
    rf_source = vector_magnitude(source, "rf") * rf_peak_scale
    static_scale, rf_scale = float(static_all.max()), float(rf_all.max())
    if static_scale <= 0.0 or rf_scale <= 0.0:
        raise ValueError("joint-field shielding scales must be positive")
    return {
        "oatof_static_maximum_upstream_of_entry_V_per_m": float(static_upstream.max()),
        "oatof_static_upstream_relative_to_joint_axis_maximum": float(static_upstream.max() / static_scale),
        "rf_peak_maximum_near_oatof_source_V_per_m": float(rf_source.max()),
        "rf_peak_near_source_relative_to_joint_axis_maximum": float(rf_source.max() / rf_scale),
        "rf_peak_scale_from_unit_field": rf_peak_scale,
    }


def plot_injection_axis(injection: pd.DataFrame, rf_peak_scale: float, entry_x_mm: float, output: Path) -> None:
    ordered = injection.sort_values("x_mm")
    static = np.maximum(vector_magnitude(ordered, "static"), 1e-18)
    rf_peak = np.maximum(vector_magnitude(ordered, "rf") * rf_peak_scale, 1e-18)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8, 4.8))
    axis.semilogy(ordered["x_mm"], static, label="oa pulse-field basis |E|", color="#2166ac")
    axis.semilogy(ordered["x_mm"], rf_peak, label="RF peak |E|", color="#d95f0e")
    axis.axvline(entry_x_mm, color="#636363", linestyle="--", label="oa outer entry face")
    axis.set(xlabel="Instrument x (mm)", ylabel="Field magnitude (V/m)",
             title="S1 physical-port injection-axis field isolation")
    axis.grid(alpha=0.25, which="both")
    axis.legend()
    figure.tight_layout()
    figure.savefig(output, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--closed-reference", required=True, type=Path)
    parser.add_argument("--joint-contract", required=True, type=Path)
    parser.add_argument("--interface-contract", required=True, type=Path)
    parser.add_argument("--rf-resolved", required=True, type=Path)
    parser.add_argument("--reference-role", required=True, choices=("formal_closed", "matched_local_closed"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    joint = json.loads(args.joint_contract.read_text(encoding="utf-8-sig"))
    interface = json.loads(args.interface_contract.read_text(encoding="utf-8-sig"))
    rf_resolved = json.loads(args.rf_resolved.read_text(encoding="utf-8-sig"))
    candidate_all = pd.read_csv(args.candidate)
    candidate = candidate_all[candidate_all["sample_type"] == "accelerator_profile"].copy()
    candidate = candidate.rename(columns={
        "static_Ex_V_per_m": "Ex_V_per_m",
        "static_Ey_V_per_m": "Ey_V_per_m",
        "static_Ez_V_per_m": "Ez_V_per_m",
        "static_potential_V": "potential_V",
    })
    closed = normalize_static_reference(pd.read_csv(args.closed_reference))
    envelope, candidate_report = analyze(candidate, formal_half_width_mm=0.5)
    field_reference = interface["connector"]["entry_aperture_design"]["field_uniformity_reference"]
    thresholds = field_reference["diagnostic_alert_thresholds"]
    for metric, threshold in thresholds.items():
        envelope[f"closed_reference_{metric}_alert_clear"] = (
            envelope[metric] <= float(threshold) * (1.0 + 1e-9)
        )
    envelope["all_closed_reference_alerts_clear"] = envelope[
        [f"closed_reference_{name}_alert_clear" for name in thresholds]
    ].all(axis=1)
    envelope = envelope.merge(component_profile_envelope(candidate), on="abs_y_mm", how="left")

    axis_candidate = candidate[np.isclose(candidate["y_mm"], 0.0)].sort_values("z_mm")
    axis_closed = closed[np.isclose(closed["y_mm"], 0.0)].sort_values("z_mm")
    if not np.allclose(axis_candidate["z_mm"], axis_closed["z_mm"], rtol=0.0, atol=1e-10):
        raise ValueError("opened and closed axis profiles use different z samples")
    closed_ez = axis_closed["Ez_V_per_m"].to_numpy(float)
    closed_v = axis_closed["potential_V"].to_numpy(float)
    axis_ez_scale = float(np.sqrt(np.mean(np.square(closed_ez))))
    axis_v_scale = float(np.ptp(closed_v))
    axis_change = {
        "ez_relative_rms": relative_rms(
            axis_candidate["Ez_V_per_m"].to_numpy(float) - closed_ez, axis_ez_scale
        ),
        "potential_relative_rms": relative_rms(
            axis_candidate["potential_V"].to_numpy(float) - closed_v, axis_v_scale
        ),
    }
    injection = candidate_all[candidate_all["sample_type"] == "injection_axis"].copy()
    if injection.empty:
        injection_characterization = {
            "status": "not_applicable_for_closed_shield_control",
            "maximum_oatof_static_field_V_per_m": None,
            "maximum_rf_unit_field_V_per_m": None,
        }
    else:
        static_magnitude = vector_magnitude(injection, "static")
        rf_magnitude = vector_magnitude(injection, "rf")
        rf_peak_scale = float(rf_resolved["mode"]["rf"]["amplitude_V_peak"]) / 100.0
        entry_x_mm = float(joint["nominal_registration"]["target_entry_center_instrument_mm"][0])
        injection_characterization = {
            "status": "sampled_through_open_port",
            "maximum_oatof_static_field_V_per_m": float(static_magnitude.max()),
            "maximum_rf_unit_field_V_per_m": float(rf_magnitude.max()),
            "oatof_static_component_line_integrals": field_line_integrals(injection, "static"),
            "rf_unit_component_line_integrals": field_line_integrals(injection, "rf"),
            "shielding_diagnostics": shielding_diagnostics(injection, entry_x_mm, rf_peak_scale),
        }
        plot_injection_axis(
            injection, rf_peak_scale, entry_x_mm,
            args.output_dir / "s1_injection_axis_field.png",
        )
    width = float(candidate_all["port_full_width_y_mm"].iloc[0])
    reference_width = float(
        field_reference["closed_shield_contiguous_full_width_y_mm"]
    )
    evaluated_half_width = evaluation_half_width(width, reference_width)
    within_width = envelope[envelope["abs_y_mm"] <= evaluated_half_width + 1e-12]
    if within_width.empty or within_width["abs_y_mm"].max() < evaluated_half_width - 1e-12:
        raise ValueError("S1 samples do not include the exact evaluation edge")
    reference_alert_clear = bool(within_width["all_closed_reference_alerts_clear"].all())
    report = {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_opened_joint_field_characterization",
        "status": "CHARACTERIZED",
        "geometry_state": "closed_local_domain_control" if np.isclose(width, 0.0) else "opened_port",
        "port_full_width_y_mm": width,
        "port_full_height_z_mm": float(candidate_all["port_full_height_z_mm"].iloc[0]),
        "evaluated_full_width_y_mm": 2.0 * evaluated_half_width,
        "closed_shield_diagnostic_alert_thresholds": thresholds,
        "closed_reference_alert_clear": reference_alert_clear,
        "closed_reference_alert_is_hard_gate": False,
        "opened_to_closed_axis_change": axis_change,
        "axis_change_reference_role": args.reference_role,
        "injection_axis_characterization": injection_characterization,
        "unresolved_gates": [
            "maximum relative field leakage",
            "high-voltage and mechanical limits",
            "particle transmission and final resolution",
        ],
        "all_constraints_pass": None,
        "s1_pass_allowed": False,
        "claim_limit": "Field characterization only. A legacy field-reference alert cannot accept or reject the connector; no particle runtime or physical interface claim.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    envelope.to_csv(args.output_dir / "s1_joint_field_uniformity_curve.csv", index=False)
    (args.output_dir / "s1_joint_field_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "S1_JOINT_FIELD_ANALYSIS=PASS "
        f"WIDTH_MM={width:.12g} FIELD_REFERENCE_ALERT_CLEAR={str(reference_alert_clear).lower()} "
        "S1_PASS_ALLOWED=false"
    )


if __name__ == "__main__":
    main()
