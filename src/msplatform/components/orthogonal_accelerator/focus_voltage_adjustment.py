"""Original bounded OA voltage response and trial projection."""
from __future__ import annotations

import json
import math
from typing import Any

_TIERS = ((2.0, 0.0005), (10.0, 0.0025), (math.inf, 0.01))


class ComponentFocusFastAdjustError(ValueError):
    """Raised when the bounded accelerator correction cannot continue."""


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ComponentFocusFastAdjustError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ComponentFocusFastAdjustError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise ComponentFocusFastAdjustError(f"{label} must be finite")
    return result


def _parameters(campaign: dict[str, Any]) -> dict[str, float]:
    point = campaign["operating_point"]
    return {
        "instance_center_y_mm": _number(point["instance_center_y_mm"], "instance center y"),
        "finite_3d_gain_correction_v": _number(
            point["finite_3d_gain_correction_v"], "finite-3D gain correction",
        ),
    }


def _candidate_campaign(campaign: dict[str, Any], parameters: dict[str, float], *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    """Change only runtime placement and voltages; PA geometry remains untouched."""
    profile = geometry_profile
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    ring_count = int(profile["ring_count"])
    center_z = _number(campaign["release_spec"]["geometry"]["center_mm"][2], "release centre z")
    release_position = gap1 + gap2 - center_z
    if not 0.0 < release_position < gap1:
        raise ComponentFocusFastAdjustError("release centre is outside provider first acceleration gap")
    base = campaign["operating_point"]["electrode_voltages_v"]
    drop = _number(base[1], "repeller voltage") - _number(base[2], "grid1 voltage")
    base_correction = _number(
        campaign["operating_point"]["finite_3d_gain_correction_v"], "base finite-3D gain correction",
    )
    theoretical_energy = _number(base[1], "repeller voltage") - drop * release_position / gap1 - base_correction
    correction = _number(parameters["finite_3d_gain_correction_v"], "candidate finite-3D gain correction")
    applied_energy = theoretical_energy + correction
    repeller = applied_energy + drop * release_position / gap1
    grid1 = repeller - drop
    candidate = json.loads(json.dumps(campaign))
    candidate["operating_point"]["instance_center_y_mm"] = _number(
        parameters["instance_center_y_mm"], "candidate instance center y",
    )
    candidate["operating_point"]["finite_3d_gain_correction_v"] = correction
    candidate["operating_point"]["electrode_voltages_v"] = [
        0.0, repeller, grid1, 0.0,
        *(grid1 * index / (ring_count + 1) for index in range(ring_count, 0, -1)),
    ]
    return candidate


def _tier(maximum_normalized_residual: float) -> float:
    return next(step for limit, step in _TIERS if maximum_normalized_residual <= limit)


def _scale(campaign: dict[str, Any], *, geometry_profile: dict[str, Any]) -> float:
    profile = geometry_profile
    base = campaign["operating_point"]["electrode_voltages_v"]
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    release_z = _number(campaign["release_spec"]["geometry"]["center_mm"][2], "release centre z")
    release_position = gap1 + gap2 - release_z
    correction = _number(campaign["operating_point"]["finite_3d_gain_correction_v"], "finite-3D gain correction")
    target = _number(base[1], "repeller voltage") - (_number(base[1], "repeller voltage") - _number(base[2], "grid1 voltage")) * release_position / gap1 - correction
    return abs(target)


def _probe(base: dict[str, float], relative_step: float, scale: float) -> dict[str, float]:
    result = dict(base)
    result["finite_3d_gain_correction_v"] += relative_step * scale
    return result


def _solution(records: list[dict[str, Any]], base_index: int, relative_step: float, scale: float) -> dict[str, float]:
    base, gain_probe = records[base_index:base_index + 2]
    if gain_probe["kind"] != "gain_probe":
        raise ComponentFocusFastAdjustError("real-flight axial-voltage probe is incomplete")
    r0, rg = base["residuals"][0], gain_probe["residuals"][0]
    dg = gain_probe["parameters"]["finite_3d_gain_correction_v"] - base["parameters"]["finite_3d_gain_correction_v"]
    derivative = (rg - r0) / dg
    if abs(derivative) <= 1.0e-12:
        raise ComponentFocusFastAdjustError("real-flight axial-voltage response is singular")
    delta_gain = -r0 / derivative
    trust_gain = relative_step * scale
    delta_gain = max(-trust_gain, min(trust_gain, delta_gain))
    return {
        "instance_center_y_mm": base["parameters"]["instance_center_y_mm"],
        "finite_3d_gain_correction_v": base["parameters"]["finite_3d_gain_correction_v"] + delta_gain,
    }




def residual_from_focus_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Extract physically measured bounded-adjustment inputs from SI focus evidence.

    Partial transport and unsupported species are not silently promoted to a
    decision. This returns measurements only, without a global qualification.
    """
    if analysis.get('role') != 'oa_focus_si_analysis' or analysis.get('status') != 'analyzed':
        raise ComponentFocusFastAdjustError('complete OA focus analysis is required')
    measurements=analysis.get('measurements',{})
    energy=analysis.get('energy_assessment',{})
    center=energy.get('center_particle')
    cohort=energy.get('cohort',{})
    tolerances=energy.get('tolerances',{})
    if (measurements.get('particle_count') != measurements.get('focus_particle_count')
            or cohort.get('expected_particle_count') != cohort.get('measured_particle_count')
            or not isinstance(center,dict)):
        raise ComponentFocusFastAdjustError('complete focus and exit-energy cohort is required')
    names=('slow','axial','transverse')
    residuals={name:_number(cohort.get('maximum_absolute_'+name+'_energy_residual_per_charge_v'),name+' residual')
               for name in names}
    limits={name:_number(tolerances.get('maximum_exit_'+name+'_energy_error_per_charge_v'),name+' tolerance')
            for name in names}
    if min(limits.values())<=0.:
        raise ComponentFocusFastAdjustError('exit-energy tolerances must be positive')
    center_residual=_number(center.get('axial_energy_residual_per_charge_v'),'center axial residual')
    width=measurements.get('peak_to_peak_arrival_s')
    return dict(center_axial_residual_v=center_residual,
        maximum_normalized_center_residual=abs(center_residual)/limits['axial'],
        maximum_normalized_cohort_residual=max(residuals[name]/limits[name] for name in names),
        focus_peak_to_peak_ns=None if width is None else _number(width,'focus peak-to-peak time')*1e9,
        cohort_energy_passed=bool(energy.get('passed')))


def advance_adjustment_state(state: dict[str, Any], record: dict[str, Any], campaign: dict[str, Any], *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    """Apply the original bounded measured-response step without executing a solver."""
    records = state["records"]
    records.append(record)
    best = state["best_record_index"]
    if record["valid"] and (best is None or record["score"] < records[best]["score"]):
        state["best_record_index"] = len(records) - 1
    if record["accepted"]:
        state["status"], state["next_parameters"] = "accepted", None
        return state
    if not record["geometry_acceptable"] or record["center_axial_energy_passed"]:
        state["status"], state["next_parameters"] = "exhausted", None
        return state
    if len(records) >= state["maximum_trials"]:
        state["status"], state["next_parameters"] = "exhausted", None
        return state
    scale = _scale(campaign, geometry_profile=geometry_profile)
    if state["phase"] in {"base", "solution"}:
        state["base_record_index"] = len(records) - 1
        state["probe_relative_step"] = _tier(record["maximum_normalized_residual"])
        state["next_parameters"] = _probe(record["parameters"], state["probe_relative_step"], scale)
        state["phase"] = "gain_probe"
    elif state["phase"] == "gain_probe":
        state["next_parameters"] = _solution(records, state["base_record_index"], state["probe_relative_step"], scale)
        state["phase"] = "solution"
    else:
        raise ComponentFocusFastAdjustError("controller phase is invalid")
    return state


def adjustment_record_from_si(analysis: dict[str, Any]) -> dict[str, Any]:
    """Translate actual SI cohort measurements into the existing bounded decision inputs."""
    from msplatform.io.file_identity import canonical_json_sha256
    values=residual_from_focus_analysis(analysis)
    energy=analysis['energy_assessment'];center=energy['center_particle'];cohort=energy['cohort'];limits=energy['tolerances']
    width=_number(values['focus_peak_to_peak_ns'],'focus peak-to-peak time')
    velocity_limit=_number(limits['maximum_exit_transverse_velocity_bias_mm_per_us'],'velocity bias tolerance')
    if velocity_limit<=0.:
        raise ComponentFocusFastAdjustError('velocity bias tolerance must be positive')
    acceptable=(cohort['slow_energy_passed'] is True and cohort['transverse_energy_passed'] is True
        and abs(_number(center['delta_vx_mm_per_us'],'center transverse velocity'))<=velocity_limit
        and abs(_number(cohort['mean_delta_vx_mm_per_us'],'mean transverse velocity'))<=velocity_limit)
    return dict(analysis_content_sha256=canonical_json_sha256(analysis).lower(),
        residuals=[values['center_axial_residual_v']],
        maximum_normalized_residual=values['maximum_normalized_center_residual'],
        score=values['maximum_normalized_cohort_residual'],peak_to_peak_t_ns=width,
        accepted=values['cohort_energy_passed'],geometry_acceptable=acceptable,
        geometry_diagnostic='cohort_Ex_Ey_geometry_gate_passed' if acceptable else 'cohort_Ex_Ey_geometry_gate_failed',
        center_axial_energy_passed=abs(values['center_axial_residual_v'])<=limits['maximum_exit_axial_energy_error_per_charge_v'],
        valid=True)
