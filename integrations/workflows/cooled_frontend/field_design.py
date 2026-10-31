"""Infer two voltage controls from measured assembled Laplace responses.

This local quadratic design is a proposal, not a capture or flight result.
The independent terminal-inner and HP-common responses avoid conflating well
curvature, gate height and released energy in one arbitrary voltage scan.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.polynomial import Polynomial

from common.contracts.particle_physics import BOLTZMANN_CONSTANT_J_K, ELEMENTARY_CHARGE_C
from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import (
    analyze_buncher_axial_barriers, analyze_buncher_field_samples,
)


def project_member_samples(frame: pd.DataFrame, kind: str, scale: float) -> pd.DataFrame:
    """Project sampled source fields; preserve positions, names and raw data."""
    if (isinstance(scale, bool) or not isinstance(scale, (int, float))
            or not math.isfinite(scale) or (kind != "pulse_delta" and scale != 1)):
        raise ValueError("invalid proven field member scale")
    projected = frame.copy()
    columns = ["potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm"]
    projected[columns] = projected[columns] * scale
    if not np.isfinite(projected[columns].to_numpy(dtype=float)).all():
        raise ValueError("nonfinite projected field samples")
    return projected


def compose_samples(responses: dict[str, pd.DataFrame], coefficients: dict[str, float],
                    *, rf_amplitude_v: float) -> pd.DataFrame:
    """Compose measured DC and a guide-normalized unit RF response by point ID."""
    reference = responses["rf_differential_unit"].set_index("name", verify_integrity=True)
    positions = [f"{a}_mm" for a in "xyz"]
    if not math.isfinite(rf_amplitude_v) or rf_amplitude_v <= 0:
        raise ValueError("positive guide RF amplitude required")
    output = reference[positions].copy()
    output["dc_potential_v"] = 0.
    for name, coefficient in coefficients.items():
        if not math.isfinite(coefficient):
            raise ValueError("finite response coefficient required")
        values = responses[name].set_index("name", verify_integrity=True)
        if set(values.index) != set(reference.index):
            raise ValueError("actual response point identities differ")
        values = values.loc[reference.index]
        if not np.array_equal(values[positions].to_numpy(), reference[positions].to_numpy()):
            raise ValueError("actual response coordinate mappings differ")
        output["dc_potential_v"] += coefficient*values["potential_v"]
    for axis in "xyz":
        output[f"unit_rf_e{axis}_v_per_mm"] = reference[f"e{axis}_v_per_mm"]
    if not np.isfinite(output.to_numpy(dtype=float)).all():
        raise ValueError("nonfinite actual response field")
    return output.reset_index()


def design_voltage_controls(
    responses: dict[str, pd.DataFrame], *, center_mr_mm: list[float], mass_amu: float,
    charge_state: int, temperature_k: float, rf_frequency_hz: float,
    guide_rf_amplitude_v: float, target_thermal_sigma_y_mm: float,
    target_static_energy_gain_ev: float, release_reference_name: str,
    oa_entry_reference_name: str,
) -> dict:
    """Solve axial curvature and static release energy using two linear controls.

    The target width is an explicit design assumption. RF micromotion, finite
    bunch aberration and collisions are reserved for the actual native test.
    An unstable or extrapolated local well is reported rather than accepted.
    """
    if (isinstance(charge_state, bool) or not isinstance(charge_state, int) or charge_state <= 0
            or not math.isfinite(target_thermal_sigma_y_mm) or target_thermal_sigma_y_mm <= 0
            or not math.isfinite(target_static_energy_gain_ev)):
        raise ValueError("positive charge/target width and finite energy target required")
    fit_args = dict(center_mr_mm=center_mr_mm, mass_amu=mass_amu, charge_state=charge_state,
                    temperature_k=temperature_k, rf_frequency_hz=rf_frequency_hz,
                    rf_peak_amplitude_v=guide_rf_amplitude_v)
    def fit(coefficients):
        samples = compose_samples(responses, coefficients, rf_amplitude_v=guide_rf_amplitude_v)
        return analyze_buncher_field_samples(samples[samples.name.str.startswith("well_")], **fit_args)
    closed_coefficients = dict(carrier_off=1., entry_close_delta=1.)
    seed = fit(closed_coefficients)
    plus_one = fit(dict(closed_coefficients, inner_auxiliary_unit=1.))
    curvature0 = seed["effective_energy_hessian_ev_per_mm2"][1][1]
    response = plus_one["effective_energy_hessian_ev_per_mm2"][1][1]-curvature0
    if not math.isfinite(response) or response == 0:
        raise ValueError("terminal inner electrode has no identifiable axial curvature response")
    kt = BOLTZMANN_CONSTANT_J_K*temperature_k/ELEMENTARY_CHARGE_C
    target = kt/target_thermal_sigma_y_mm**2
    h0 = np.asarray(seed["effective_energy_hessian_ev_per_mm2"])
    dh = np.asarray(plus_one["effective_energy_hessian_ev_per_mm2"])-h0
    h = [[Polynomial([h0[i,j], dh[i,j]]) for j in range(3)] for i in range(3)]
    minor_yy = h[0][0]*h[2][2]-h[0][2]*h[2][0]
    determinant = (h[0][0]*(h[1][1]*h[2][2]-h[1][2]*h[2][1])
                   -h[0][1]*(h[1][0]*h[2][2]-h[1][2]*h[2][0])
                   +h[0][2]*(h[1][0]*h[2][1]-h[1][1]*h[2][0]))
    # cov_yy = kBT * cofactor_yy(H)/det(H): retain actual cross-axis
    # coupling instead of silently assuming sigma_y^2 = kBT/Hyy.
    roots = (kt*minor_yy-target_thermal_sigma_y_mm**2*determinant).roots()
    candidates = []
    for root in roots:
        if abs(root.imag) <= 64*np.finfo(float).eps*max(1.,abs(root.real)):
            value = float(root.real)
            matrix = h0+value*dh
            if np.all(np.linalg.eigvalsh(matrix)>0):
                variance = kt*np.linalg.solve(matrix, [0.,1.,0.])[1]
                target_variance = target_thermal_sigma_y_mm**2
                roundoff = 64*np.finfo(float).eps*np.linalg.cond(matrix)
                # Multiplying by det(H) introduces poles as spurious roots.
                # Recheck the original covariance equation in binary64; this
                # allowance is numerical conditioning, not a physical target.
                if roundoff < 1 and abs(variance-target_variance) <= roundoff*max(abs(variance),target_variance):
                    candidates.append(value)
    if not candidates:
        raise ValueError("requested thermal covariance has no locally stable inner-control solution")
    correction = min(candidates, key=abs)
    calibrated = fit(dict(closed_coefficients, inner_auxiliary_unit=correction))
    closed = compose_samples(responses, dict(closed_coefficients, inner_auxiliary_unit=correction),
                             rf_amplitude_v=guide_rf_amplitude_v)
    line = closed[closed.name.str.startswith("axis_")].sort_values("y_mm")
    barriers = analyze_buncher_axial_barriers(line, well_center_y_mm=center_mr_mm[1], mass_amu=mass_amu,
        charge_state=charge_state, temperature_k=temperature_k, rf_frequency_hz=rf_frequency_hz,
        rf_peak_amplitude_v=guide_rf_amplitude_v)
    release_coefficients = dict(carrier_off=1., entry_close_delta=1., release_delta=1.)
    release = compose_samples(responses, release_coefficients, rf_amplitude_v=guide_rf_amplitude_v).set_index("name")
    common = compose_samples(responses, {"hp_common_unit":1.},
                             rf_amplitude_v=guide_rf_amplitude_v).set_index("name")
    # Explicit sampled points: never extrapolate an on-axis potential beyond
    # the gate or silently equate the metal voltage with the vacuum potential.
    baseline_gain = charge_state*(release.loc[release_reference_name, "dc_potential_v"]-
                                  release.loc[oa_entry_reference_name, "dc_potential_v"])
    gain_per_volt = charge_state*(common.loc[release_reference_name, "dc_potential_v"]-
                                 common.loc[oa_entry_reference_name, "dc_potential_v"])
    if not math.isfinite(gain_per_volt) or gain_per_volt == 0:
        raise ValueError("HP-common response cannot identify release energy control")
    release_correction = (target_static_energy_gain_ev-baseline_gain)/gain_per_volt
    return dict(schema_version=1, role="cooled_frontend_actual_field_voltage_design",
        voltage_calibration=dict(inner_correction_v=float(correction),
                                 release_hp_common_correction_v=float(release_correction)),
        targets=dict(thermal_sigma_y_mm=target_thermal_sigma_y_mm,
                     static_energy_gain_ev=target_static_energy_gain_ev),
        seed_closed_well=seed, calibrated_closed_well=calibrated, closed_axial_line_barriers=barriers,
        axial_curvature_response_ev_per_mm2_per_v=float(response),
        uncoupled_equivalent_target_curvature_ev_per_mm2=float(target),
        stable_covariance_solution_inner_corrections_v=candidates,
        covariance_solution_selection="smallest absolute correction among locally positive Hessians; equilibrium domain remains explicitly reported",
        release_design=dict(reference_point=release_reference_name, destination_point=oa_entry_reference_name,
            seed_static_gain_ev=float(baseline_gain), energy_gain_response_ev_per_v=float(gain_per_volt)),
        qualification="Local effective-well and static-energy proposal; native capture/release, RF work, widths and losses remain unverified")


def analyze_field_run(run: Path) -> dict:
    """Analyze an unsealed caller-owned native field stage before publication."""
    run = Path(run).resolve(strict=True)
    def read(name):
        return json.loads((run/"inputs"/name).read_text(encoding="utf-8-sig"))
    manifest_path = run/"run_manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8-sig")).get("status") != "checkpoint":
        raise ValueError("field analysis must precede immutable owner publication")
    targets = read("cooled_design_targets.json")
    conditioner, guide = read("conditioner_contract.json"), read("guide_contract.json")
    source = pd.read_csv(run/"inputs/release_global.csv")
    if len(source[["mass_amu","charge_state"]].drop_duplicates()) != 1:
        raise ValueError("single-species curvature design required")
    # Native probes sample the actual immutable source member.  A proven
    # Laplace rescaling is a scientific projection, never a rewritten CSV.
    from .runtime import KINDS, static_probe_analysis_records
    stage = read("cooled_frontend_field_stage_receipt.json")
    rows = stage["working_points"]
    actual_probes = static_probe_analysis_records(run, rows)
    probe_records = actual_probes["native_probe_records"]
    paths = {kind: Path(record["path"]) for kind, record in probe_records.items()}
    if tuple(row["kind"] for row in rows) != KINDS or set(paths) != set(KINDS):
        raise ValueError("complete ordered field member evidence required")
    responses = {}
    projections = {}
    for row in rows:
        kind = row["kind"]
        scale = row["field_scale"]
        responses[kind] = project_member_samples(pd.read_csv(paths[kind]), kind, scale)
        projections[kind] = dict(scale=scale, source_member=row,
                                raw_probe_record=probe_records[kind])
        if kind in actual_probes["probe_owner_manifest_records"]:
            projections[kind]["probe_owner_manifest_record"] = actual_probes["probe_owner_manifest_records"][kind]
    output = run/"results/cooled_field_design"
    output.mkdir(exist_ok=False)
    try:
        result = design_voltage_controls(responses,
            center_mr_mm=conditioner["geometry"]["trap_center_mr_mm"],
            mass_amu=float(source.mass_amu.iloc[0]), charge_state=int(source.charge_state.iloc[0]),
            temperature_k=conditioner["gas"]["parameters"]["temperature_k"],
            rf_frequency_hz=guide["drive"]["frequency_hz"],
            guide_rf_amplitude_v=guide["drive"]["rf_amplitude_v"],
            target_thermal_sigma_y_mm=targets["thermal_sigma_y_mm"],
            target_static_energy_gain_ev=targets["static_release_energy_gain_ev"],
            release_reference_name="well_62",oa_entry_reference_name="oa_side_entry")
        result["design_status"] = ("proposal_computed" if result["calibrated_closed_well"]["equilibrium_within_sample_bounds"]
                                    else "additional_actual_field_samples_required")
    except ValueError as error:
        result = dict(schema_version=1,role="cooled_frontend_actual_field_voltage_design",
                      design_status="target_not_identifiable_or_feasible",reason=str(error),
                      qualification="Native fields remain evidence; failed theory target does not qualify capture or focusing")
    result["native_probe_records"] = probe_records
    result["response_projections"] = projections
    result["target_record"] = file_record(run/"inputs/cooled_design_targets.json")
    (output/"voltage_design.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    result = analyze_field_run(parser.parse_args().run)
    print(json.dumps(dict(role=result["role"],design_status=result["design_status"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
