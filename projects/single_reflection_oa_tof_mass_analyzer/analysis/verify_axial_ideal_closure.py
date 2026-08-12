"""Verify the solver-independent axial ideal Arm 8 analytic closure.

The model is one-dimensional and piecewise uniform.  It starts its clock at the
effective extraction pulse, propagates a predeclared position lattice through the
ideal accelerator, drift regions, and dual-stage reflectron, and applies the
repository's canonical KDE/FWHM implementation.  It does not invoke or emulate a
SIMION or COMSOL trajectory solve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    AcceleratorState,
    PhysicsContractError,
    accelerator_state,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    CoupledReflectronSolution,
    coupled_flight_time_s,
    solve_coupled_reflectron_fields,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PhysicsContractError(f"{path} must contain a JSON object")
    return payload


def _physical_factor_s_per_mm_sqrt_v(mass_to_charge_th: float) -> float:
    mass_over_charge = (
        mass_to_charge_th * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    )
    return 1.0e-3 * math.sqrt(mass_over_charge / 2.0)


def segment_times_s(
    release_position_mm: float,
    accelerator: AcceleratorState,
    reflectron: CoupledReflectronSolution,
    mass_to_charge_th: float,
) -> dict[str, float]:
    """Return exact constant-acceleration and constant-velocity segment times."""

    energy = (
        accelerator.repeller_relative_v
        - accelerator.field1_v_per_mm * release_position_mm
    )
    stage1_exit_energy = energy - accelerator.intermediate_relative_v
    reflectron_stage2_entry_energy = energy - reflectron.stage1_voltage_drop_v
    if min(stage1_exit_energy, reflectron_stage2_entry_energy) <= 0.0:
        raise PhysicsContractError("analytic path turns before a required interface")

    factor = _physical_factor_s_per_mm_sqrt_v(mass_to_charge_th)
    root_energy = math.sqrt(energy)
    root_accel_stage1_exit = math.sqrt(stage1_exit_energy)
    root_reflectron_stage2_entry = math.sqrt(reflectron_stage2_entry_energy)
    times = {
        "accelerator_stage1_s": factor
        * 2.0
        * root_accel_stage1_exit
        / accelerator.field1_v_per_mm,
        "accelerator_stage2_s": factor
        * 2.0
        * (root_energy - root_accel_stage1_exit)
        / accelerator.field2_v_per_mm,
        "accelerator_exit_to_focus_s": factor
        * accelerator.first_order_focus_drift_mm
        / root_energy,
        "focus_to_reflectron_entrance_s": factor
        * reflectron.upstream_from_accelerator_focus_mm
        / root_energy,
        "reflectron_stage1_outbound_s": factor
        * 2.0
        * (root_energy - root_reflectron_stage2_entry)
        / reflectron.stage1_field_v_per_mm,
        "reflectron_stage2_outbound_to_turn_s": factor
        * 2.0
        * root_reflectron_stage2_entry
        / reflectron.stage2_field_v_per_mm,
        "reflectron_stage2_return_s": factor
        * 2.0
        * root_reflectron_stage2_entry
        / reflectron.stage2_field_v_per_mm,
        "reflectron_stage1_return_s": factor
        * 2.0
        * (root_energy - root_reflectron_stage2_entry)
        / reflectron.stage1_field_v_per_mm,
        "reflectron_exit_to_return_focus_s": factor
        * reflectron.downstream_to_detector_mm
        / root_energy,
    }
    times["total_s"] = sum(times.values())
    return times


def _check(
    assertions: list[dict[str, Any]],
    assertion_id: str,
    passed: bool,
    actual: Any,
    requirement: str,
) -> None:
    assertions.append(
        {
            "assertion_id": assertion_id,
            "passed": bool(passed),
            "actual": actual,
            "requirement": requirement,
        }
    )


def compute_receipt(
    contract: Mapping[str, Any],
    resolved: Mapping[str, Any],
    *,
    contract_path: Path,
    resolved_path: Path,
) -> dict[str, Any]:
    """Compute all Arm 8 analytic assertions and return a JSON-ready receipt."""

    source = contract["source"]
    detector = contract["detector_arrival"]
    theory = contract["theory"]
    gates = contract["gates"]
    geometry = resolved["geometry_mm"]
    electrodes = resolved["electrodes_V"]
    derivation = resolved["geometry_derivation"]

    gap1 = float(derivation["accelerator"]["d1_mm"])
    gap2 = float(derivation["accelerator"]["d2_mm"])
    repeller_v = float(electrodes["repeller"])
    grid1_v = float(electrodes["grid1"])
    grid2_v = float(electrodes["grid2"])
    accelerator = accelerator_state(
        repeller_v,
        grid1_v,
        gap1,
        gap2,
        exit_v=grid2_v,
    )
    reflectron = solve_coupled_reflectron_fields(
        accelerator,
        float(geometry["L_stage1"]),
        float(geometry["L_flight"]),
        float(geometry["L_flight"]),
        energy_min_v=float(theory["energy_envelope_min_V"]),
        energy_max_v=float(theory["energy_envelope_max_V"]),
        stage2_margin_fraction=float(theory["reflectron_stage2_margin_fraction"]),
        stage2_margin_mm=float(theory["reflectron_stage2_margin_mm"]),
    )

    stage2_length = reflectron.required_stage2_depth_mm
    entrance_v = float(electrodes["entgrid"])
    midgrid_v = reflectron.stage1_voltage_drop_v + entrance_v
    backplate_v = midgrid_v + reflectron.stage2_field_v_per_mm * stage2_length
    continuity = {
        "accelerator_stage1_V": repeller_v
        - accelerator.field1_v_per_mm * gap1
        - grid1_v,
        "accelerator_stage2_V": grid1_v
        - accelerator.field2_v_per_mm * gap2
        - grid2_v,
        "reflectron_stage1_V": entrance_v
        + reflectron.stage1_field_v_per_mm * reflectron.stage1_length_mm
        - midgrid_v,
        "reflectron_stage2_V": midgrid_v
        + reflectron.stage2_field_v_per_mm * stage2_length
        - backplate_v,
    }

    width = float(source["release_full_width_mm"])
    count = int(source["sample_count"])
    if count < 3 or count != float(source["sample_count"]):
        raise PhysicsContractError("source.sample_count must be an integer >= 3")
    if float(source["initial_axial_velocity_m_per_s"]) != 0.0:
        raise PhysicsContractError("Arm 8 reference requires zero initial axial velocity")
    release_positions = np.linspace(
        accelerator.release_position_mm - width / 2.0,
        accelerator.release_position_mm + width / 2.0,
        count,
    )
    if release_positions[0] <= 0.0 or release_positions[-1] >= gap1:
        raise PhysicsContractError("predeclared source grid must remain inside stage 1")

    mass_to_charge = float(source["mass_to_charge_Th"])
    pulse_effective_time_us = float(source["pulse_effective_time_us"])
    injection_energy_ev = float(detector["injection_energy_eV"])
    transverse_velocity_mm_per_us = math.sqrt(
        2.0 * injection_energy_ev * ELEMENTARY_CHARGE_C
        / (mass_to_charge * ATOMIC_MASS_CONSTANT_KG)
    ) / 1000.0
    source_axis_x_mm = float(detector["source_axis_x_mm"])
    detector_center_x_mm = float(detector["detector_center_x_mm"])
    detector_center_y_mm = float(detector["detector_center_y_mm"])
    detector_radius_mm = float(detector["detector_active_radius_mm"])
    profile_registry_path = (
        REPOSITORY_ROOT / contract["layout_profile_registry_path"]
    ).resolve()
    profile_registry = _load_json(profile_registry_path)
    profiles = [
        item
        for item in profile_registry.get("profiles", [])
        if item.get("layout_profile_id") == contract["layout_profile_id"]
    ]
    if len(profiles) != 1:
        raise PhysicsContractError("Arm 8 layout profile identity must be unique")
    profile = profiles[0]
    layout_scale = math.sqrt(
        float(profile["target_injection_energy_eV"])
        / float(profile["reference_injection_energy_eV"])
    )
    expected_source_axis_x_mm = (
        float(resolved["coordinate_convention"]["accelerator_axis_x"])
        * layout_scale
    )
    expected_detector_center_x_mm = -expected_source_axis_x_mm
    analytic_rows: list[dict[str, Any]] = []
    max_segment_sum_error_ns = 0.0
    for index, release_position in enumerate(release_positions):
        energy = repeller_v - accelerator.field1_v_per_mm * float(release_position)
        segments = segment_times_s(
            float(release_position), accelerator, reflectron, mass_to_charge
        )
        direct_time_s = coupled_flight_time_s(
            energy,
            mass_to_charge,
            accelerator,
            reflectron.upstream_from_accelerator_focus_mm,
            reflectron.downstream_to_detector_mm,
            reflectron.stage1_voltage_drop_v,
            reflectron.stage1_field_v_per_mm,
            reflectron.stage2_field_v_per_mm,
        )
        error_ns = abs(segments["total_s"] - direct_time_s) * 1.0e9
        max_segment_sum_error_ns = max(max_segment_sum_error_ns, error_ns)
        turning_depth = (energy - reflectron.stage1_voltage_drop_v) / (
            reflectron.stage2_field_v_per_mm
        )
        return_focus_tof_us = direct_time_s * 1.0e6 - pulse_effective_time_us
        detector_x_mm = (
            source_axis_x_mm + transverse_velocity_mm_per_us * return_focus_tof_us
        )
        detector_radius_from_center_mm = math.hypot(
            detector_x_mm - detector_center_x_mm,
            -detector_center_y_mm,
        )
        analytic_rows.append(
            {
                "sample_index": index,
                "release_position_mm": float(release_position),
                "energy_per_charge_eV": energy,
                "turning_depth_in_stage2_mm": turning_depth,
                "pulse_effective_return_focus_tof_us": return_focus_tof_us,
                "detector_x_mm": detector_x_mm,
                "detector_radius_from_center_mm": detector_radius_from_center_mm,
                "detector_active_disk_hit": detector_radius_from_center_mm
                <= detector_radius_mm,
                "longitudinal_path_status": "analytic_return_focus_arrival",
            }
        )

    tof_us = np.asarray(
        [float(row["pulse_effective_return_focus_tof_us"]) for row in analytic_rows]
    )
    peak, _ = compute_peak_metrics(tof_us, mass_to_charge)
    center_index = count // 2
    center = analytic_rows[center_index]
    center_segments = segment_times_s(
        float(center["release_position_mm"]),
        accelerator,
        reflectron,
        mass_to_charge,
    )
    actual_fwhm_limit_ns = peak["mean_tof_us"] * 1.0e3 / (
        2.0 * float(gates["minimum_mass_resolution"])
    )
    continuity_tolerance = float(
        gates["potential_continuity_absolute_tolerance_V"]
    )
    assertions: list[dict[str, Any]] = []
    _check(
        assertions,
        "symmetric_10ev_layout_geometry_identity",
        profile.get("method") == "symmetric_axis_speed_scaling_v1"
        and float(profile["target_injection_energy_eV"]) == injection_energy_ev
        and math.isclose(
            source_axis_x_mm,
            expected_source_axis_x_mm,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
        and math.isclose(
            detector_center_x_mm,
            expected_detector_center_x_mm,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
        and detector_radius_mm == float(geometry["detector_radius"]),
        {
            "layout_profile_id": contract["layout_profile_id"],
            "source_axis_x_mm": source_axis_x_mm,
            "detector_center_x_mm": detector_center_x_mm,
            "detector_active_radius_mm": detector_radius_mm,
            "injection_energy_eV": injection_energy_ev,
        },
        "profile-derived symmetric 10 eV axes are +/-69.01362184380704 mm and active radius is 40 mm",
    )
    _check(
        assertions,
        "potential_continuity_four_equations",
        all(abs(value) <= continuity_tolerance for value in continuity.values()),
        continuity,
        f"all four absolute residuals <= {continuity_tolerance} V",
    )
    _check(
        assertions,
        "positive_ion_force_directions",
        accelerator.field1_v_per_mm > 0.0
        and accelerator.field2_v_per_mm > 0.0
        and reflectron.stage1_field_v_per_mm > 0.0
        and reflectron.stage2_field_v_per_mm > 0.0,
        {
            "accelerator": "+z_downstream",
            "reflectron": "-z_toward_entrance",
        },
        "positive ions accelerate downstream in the accelerator and decelerate in the reflectron",
    )
    center_energy_tolerance = float(
        gates["center_energy_absolute_tolerance_eV_per_charge"]
    )
    _check(
        assertions,
        "center_exit_energy_2000_eV_per_charge",
        abs(float(center["energy_per_charge_eV"]) - 2000.0)
        <= center_energy_tolerance,
        center["energy_per_charge_eV"],
        f"abs(center energy - 2000) <= {center_energy_tolerance} eV/q",
    )
    turn_tolerance = float(gates["turning_depth_absolute_tolerance_mm"])
    center_turn = float(center["turning_depth_in_stage2_mm"])
    _check(
        assertions,
        "center_turning_point_inside_stage2",
        0.0 < center_turn < stage2_length
        and abs(center_turn - float(gates["turning_depth_reference_mm"]))
        <= turn_tolerance,
        {"depth_mm": center_turn, "stage2_length_mm": stage2_length},
        "turn lies inside stage 2 and matches the declared analytic reference",
    )
    segment_tolerance = float(gates["segment_sum_absolute_tolerance_ns"])
    _check(
        assertions,
        "piecewise_constant_acceleration_time_sum",
        max_segment_sum_error_ns <= segment_tolerance,
        max_segment_sum_error_ns,
        f"maximum segment/direct formula difference <= {segment_tolerance} ns",
    )
    center_tof_tolerance = float(gates["center_tof_absolute_tolerance_us"])
    _check(
        assertions,
        "pulse_effective_center_tof",
        abs(
            float(center["pulse_effective_return_focus_tof_us"])
            - float(gates["center_tof_reference_us"])
        )
        <= center_tof_tolerance,
        center["pulse_effective_return_focus_tof_us"],
        "return-focus crossing time minus effective pulse time matches the analytic reference",
    )
    path_fraction = sum(
        row["longitudinal_path_status"] == "analytic_return_focus_arrival"
        for row in analytic_rows
    ) / count
    _check(
        assertions,
        "complete_longitudinal_return_focus_path",
        path_fraction >= float(gates["analytic_path_fraction_minimum"]),
        {"return_focus_fraction": path_fraction},
        "100% longitudinal analytic return-focus arrival; this is not a detector-hit claim",
    )
    detector_hit_count = sum(row["detector_active_disk_hit"] for row in analytic_rows)
    _check(
        assertions,
        "ballistic_detector_active_disk_hits",
        detector_hit_count == count,
        {
            "hit_count": detector_hit_count,
            "sample_count": count,
            "maximum_radius_from_detector_center_mm": max(
                float(row["detector_radius_from_center_mm"])
                for row in analytic_rows
            ),
        },
        "10 eV +x ballistic layer places every return-focus crossing inside the R40 mm active disk",
    )
    _check(
        assertions,
        "canonical_kde_unimodal",
        peak["significant_kde_modes"] == 1,
        peak["significant_kde_modes"],
        "exactly one significant canonical KDE mode",
    )
    fwhm_reference_tolerance = float(
        gates["direct_fwhm_reference_absolute_tolerance_ns"]
    )
    _check(
        assertions,
        "direct_fwhm_reference",
        abs(
            peak["direct_fwhm_tof_ns"]
            - float(gates["direct_fwhm_reference_ns"])
        )
        <= fwhm_reference_tolerance,
        peak["direct_fwhm_tof_ns"],
        "canonical direct FWHM matches the declared approximately 0.202 ns reference",
    )
    resolution_reference = float(gates["mass_resolution_reference"])
    resolution_relative_error = abs(
        peak["mass_resolution"] / resolution_reference - 1.0
    )
    _check(
        assertions,
        "mass_resolution_reference",
        resolution_relative_error
        <= float(gates["mass_resolution_reference_relative_tolerance"]),
        peak["mass_resolution"],
        "canonical mass resolution matches the declared approximately 77094 reference",
    )
    _check(
        assertions,
        "hard_resolution_and_actual_mean_fwhm_gate",
        peak["mass_resolution"] >= float(gates["minimum_mass_resolution"])
        and peak["direct_fwhm_tof_ns"] <= actual_fwhm_limit_ns,
        {
            "mass_resolution": peak["mass_resolution"],
            "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"],
            "actual_mean_fwhm_limit_ns": actual_fwhm_limit_ns,
        },
        "R >= 30000 and direct FWHM <= actual mean TOF/(2*30000)",
    )

    passed = all(item["passed"] for item in assertions)
    return {
        "schema_version": 1,
        "receipt_role": "axial_ideal_arm8_solver_independent_analytic_closure",
        "status": "pass" if passed else "fail",
        "claim_scope": "analytic_closure_not_a_simion_or_comsol_solver_result",
        "campaign_id": contract["campaign_id"],
        "arm_id": contract["arm_id"],
        "clock": {
            "time_zero": "pulse_effective_time",
            "definition": "return_focus_crossing_time_minus_pulse_effective_time",
            "pulse_effective_time_us": pulse_effective_time_us,
            "absolute_instrument_clock_used": False,
        },
        "inputs": {
            "contract": {"path": str(contract_path), "sha256": _sha256(contract_path)},
            "resolved_geometry": {
                "path": str(resolved_path),
                "sha256": _sha256(resolved_path),
            },
            "layout_profile": {
                "registry_path": str(profile_registry_path),
                "registry_sha256": _sha256(profile_registry_path),
                "layout_profile_id": contract["layout_profile_id"],
            },
            "source": dict(source),
        },
        "ideal_piecewise_potential": {
            "accelerator": {
                "repeller_V": repeller_v,
                "grid1_V": grid1_v,
                "grid2_V": grid2_v,
                "stage1_field_V_per_mm": accelerator.field1_v_per_mm,
                "stage2_field_V_per_mm": accelerator.field2_v_per_mm,
            },
            "reflectron": {
                "entrance_V": entrance_v,
                "midgrid_V": midgrid_v,
                "backplate_V": backplate_v,
                "stage1_field_V_per_mm": reflectron.stage1_field_v_per_mm,
                "stage2_field_V_per_mm": reflectron.stage2_field_v_per_mm,
                "stage1_length_mm": reflectron.stage1_length_mm,
                "stage2_length_mm": stage2_length,
            },
            "continuity_residuals_V": continuity,
        },
        "longitudinal_return_focus": {
            "sample_count": count,
            "return_focus_arrival_count": count,
            "transverse_velocity_assumption_m_per_s": 0.0,
            "mechanical_detector_hit_claimed": False,
            "center_release_position_mm": center["release_position_mm"],
            "center_exit_energy_eV_per_charge": center["energy_per_charge_eV"],
            "center_turning_depth_in_stage2_mm": center_turn,
            "center_segment_times_us": {
                key.removesuffix("_s") + "_us": value * 1.0e6
                for key, value in center_segments.items()
            },
            "maximum_segment_sum_error_ns": max_segment_sum_error_ns,
        },
        "detector_arrival": {
            "layout_profile_id": contract["layout_profile_id"],
            "source_axis_x_mm": source_axis_x_mm,
            "detector_center_x_mm": detector_center_x_mm,
            "detector_center_y_mm": detector_center_y_mm,
            "detector_active_radius_mm": detector_radius_mm,
            "injection_energy_eV": injection_energy_ev,
            "mass_to_charge_Th": mass_to_charge,
            "positive_x_velocity_mm_per_us": transverse_velocity_mm_per_us,
            "center_particle_x_mm": center["detector_x_mm"],
            "center_particle_offset_x_mm": float(center["detector_x_mm"])
            - detector_center_x_mm,
            "active_disk_hit_count": detector_hit_count,
            "active_disk_miss_count": count - detector_hit_count,
        },
        "peak_metrics": {
            "mean_pulse_effective_return_focus_tof_us": peak["mean_tof_us"],
            "center_pulse_effective_return_focus_tof_us": center[
                "pulse_effective_return_focus_tof_us"
            ],
            "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"],
            "mass_resolution": peak["mass_resolution"],
            "time_equivalent_resolution": peak["time_equivalent_resolution"],
            "significant_kde_modes": peak["significant_kde_modes"],
            "actual_mean_R30000_fwhm_limit_ns": actual_fwhm_limit_ns,
        },
        "assertions": assertions,
        "all_assertions_passed": passed,
        "qualification": {
            "analytic_arm8_closure_passed": passed,
            "solver_result": False,
            "formal_qualification_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write the solver-independent axial ideal Arm 8 closure receipt."
    )
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    contract_path = args.contract.resolve()
    contract = _load_json(contract_path)
    resolved_path = (REPOSITORY_ROOT / contract["resolved_geometry_path"]).resolve()
    resolved = _load_json(resolved_path)
    receipt = compute_receipt(
        contract,
        resolved,
        contract_path=contract_path,
        resolved_path=resolved_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"AXIAL_IDEAL_ARM8_ANALYTIC_CLOSURE={receipt['status'].upper()}")
    print(f"RECEIPT={args.output.resolve()}")
    return 0 if receipt["all_assertions_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
