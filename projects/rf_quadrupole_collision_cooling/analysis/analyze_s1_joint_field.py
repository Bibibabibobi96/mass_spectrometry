"""Compare one opened S1 joint field with the frozen closed-shield reference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--closed-reference", required=True, type=Path)
    parser.add_argument("--joint-contract", required=True, type=Path)
    parser.add_argument("--interface-contract", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    joint = json.loads(args.joint_contract.read_text(encoding="utf-8-sig"))
    interface = json.loads(args.interface_contract.read_text(encoding="utf-8-sig"))
    candidate_all = pd.read_csv(args.candidate)
    candidate = candidate_all[candidate_all["sample_type"] == "accelerator_profile"].copy()
    candidate = candidate.rename(columns={
        "static_Ex_V_per_m": "Ex_V_per_m",
        "static_Ey_V_per_m": "Ey_V_per_m",
        "static_Ez_V_per_m": "Ez_V_per_m",
        "static_potential_V": "potential_V",
    })
    closed = pd.read_csv(args.closed_reference)
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
        static_magnitude = np.sqrt(sum(np.square(injection[column].to_numpy(float)) for column in (
            "static_Ex_V_per_m", "static_Ey_V_per_m", "static_Ez_V_per_m"
        )))
        rf_magnitude = np.sqrt(sum(np.square(injection[column].to_numpy(float)) for column in (
            "rf_Ex_V_per_m", "rf_Ey_V_per_m", "rf_Ez_V_per_m"
        )))
        injection_characterization = {
            "status": "sampled_through_open_port",
            "maximum_oatof_static_field_V_per_m": float(static_magnitude.max()),
            "maximum_rf_unit_field_V_per_m": float(rf_magnitude.max()),
            "oatof_static_component_line_integrals": field_line_integrals(injection, "static"),
            "rf_unit_component_line_integrals": field_line_integrals(injection, "rf"),
        }
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
