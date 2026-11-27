"""Two-zone OA focus theory using one explicitly frozen campaign and profile."""
from __future__ import annotations

import math
from statistics import fmean
from typing import Any

from msplatform.contracts.particle_physics import kinetic_energy_ev
from .accelerator_time_focus import time_to_fixed_plane_s
from .focus_campaign import ComponentFocusError, _finite

def _ideal_two_zone_contrast(
    hits: dict[int, tuple[dict[str, float], dict[str, float]]], campaign: dict[str, Any],
    *, geometry_profile: dict[str, Any],
) -> dict[str, Any]:
    """Pair native hits with the ideal model at the same plane and clock.

    Each requested ID remains visible if ideal propagation fails. Cohort widths
    require every requested ideal arrival and at least two pairs. Differences
    describe this reference comparison; they do not identify a physical cause.
    """
    profile = geometry_profile
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    point = campaign["operating_point"]
    voltages = point["electrode_voltages_v"]
    repeller, grid1, exit_v = (_finite(voltages[index], "ideal voltage") for index in (1, 2, 3))
    species = campaign["release_spec"]["species"]
    mass = _finite(species["mass_amu"], "ion mass")
    charge = _finite(species["charge_state"], "ion charge state")
    if mass <= 0.0 or charge <= 0.0:
        raise ComponentFocusError("ideal two-zone contrast requires positive ion mass and charge")
    drift = -_finite(point["focus_plane_offset_from_exit_mm"], "focus plane")
    pairs: list[dict[str, Any]] = []
    for particle, (state, focus) in hits.items():
        row = {"particle_id": particle, "source_t_us": state["t_us"],
               "native_arrival_t_us": focus["t_us"], "ideal_arrival_t_us": None,
               "native_minus_ideal_t_ns": None, "ideal_error": None,
               "native_propagation_duration_us": focus["t_us"] - state["t_us"],
               "ideal_propagation_duration_us": None}
        try:
            release = gap1 + gap2 - state["z_mm"]
            if not 0.0 < release < gap1:
                raise ComponentFocusError("common release is outside the ideal first acceleration gap")
            duration = _finite(time_to_fixed_plane_s(
                repeller, grid1, gap1, gap2, release, -state["vz_m_s"],
                drift, mass / charge, exit_v=exit_v,
            ) * 1.0e6, "ideal propagation duration")
            ideal = _finite(state["t_us"] + duration, "ideal arrival time")
            delta = _finite((focus["t_us"]-ideal)*1000.0, "paired arrival difference")
            row.update(ideal_arrival_t_us=ideal, native_minus_ideal_t_ns=delta,
                       ideal_propagation_duration_us=duration)
        except (ValueError, OverflowError) as error:
            row["ideal_error"] = str(error)
        pairs.append(row)
    valid = [row for row in pairs if row["ideal_error"] is None]
    failed = [row["particle_id"] for row in pairs if row["ideal_error"] is not None]
    differences = [row["native_minus_ideal_t_ns"] for row in valid]
    enough = len(valid) >= 2 and not failed
    native_width = ((max(row["native_arrival_t_us"] for row in valid)-min(row["native_arrival_t_us"] for row in valid))*1000.0 if enough else None)
    ideal_width = ((max(row["ideal_arrival_t_us"] for row in valid)-min(row["ideal_arrival_t_us"] for row in valid))*1000.0 if enough else None)
    status = ("unavailable_no_focus_hits" if not hits else "incomplete_ideal_propagation" if failed
              else "single_pair_no_width_conclusion" if len(valid) == 1 else "paired_cohort_diagnostic")
    return {
        "status": status,
        "field_model": "two_zone_piecewise_uniform_ideal_field_v1",
        "same_release_and_runtime_voltages": True,
        "cohort_policy": "valid_native_focus_particle_ids_only",
        "requested_particle_ids": list(hits), "paired_particle_ids": [row["particle_id"] for row in valid],
        "requested_particle_count": len(hits), "paired_particle_count": len(valid),
        "ideal_propagation_failure_count": len(failed), "ideal_failure_particle_ids": failed,
        "clock": "authoritative_release_birth_us_plus_elapsed_propagation",
        "arrival_width_semantics": "instrument_clock_arrival_times",
        "propagation_duration_width_ns": {
            key: (max(row[field] for row in valid) - min(row[field] for row in valid))*1000.0 if enough else None
            for key, field in (("native", "native_propagation_duration_us"), ("ideal", "ideal_propagation_duration_us"))},
        "observation_plane_offset_from_exit_mm": -drift,
        "downstream_reference": "field_free_drift_after_two_zone_exit",
        "particle_pairs": pairs,
        "paired_time_difference_ns": {"count": len(valid),
            "mean": fmean(differences) if differences else None,
            "minimum": min(differences) if differences else None,
            "maximum": max(differences) if differences else None,
            "rms": math.sqrt(fmean(value*value for value in differences)) if differences else None,
            "peak_to_peak": max(differences)-min(differences) if len(differences) >= 2 else None},
        "width_comparison_available": enough,
        "native_peak_to_peak_t_ns": native_width, "ideal_peak_to_peak_t_ns": ideal_width,
        "native_minus_ideal_peak_to_peak_t_ns": native_width-ideal_width if enough else None,
        "diagnosis": "observed_comparison_cause_unassessed" if enough else "not_assessable",
        "interpretation": ("Paired arrival differences are descriptive; their cause needs numerical convergence and an error budget."
            if enough else "No cohort width conclusion: no hits, fewer than two pairs, or ideal propagation failures. Single-particle arrival differences remain descriptive."),
    }

def _target_axial_energy_per_charge_v(campaign: dict[str, Any], release_z_mm: float | None = None, *, geometry_profile: dict[str, Any]) -> float:
    profile = geometry_profile
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    release_z = _finite(
        campaign["release_spec"]["geometry"]["center_mm"][2] if release_z_mm is None else release_z_mm,
        "release z",
    )
    release_position = gap1 + gap2 - release_z
    if not 0.0 < release_position < gap1:
        raise ComponentFocusError("release centre is outside provider first acceleration gap")
    voltages = campaign["operating_point"]["electrode_voltages_v"]
    repeller, grid1, exit_v = (_finite(voltages[index], "energy target voltage") for index in (1, 2, 3))
    applied = repeller - exit_v - (repeller - grid1) * release_position / gap1
    correction = _finite(campaign["operating_point"]["finite_3d_gain_correction_v"], "finite-3D gain correction")
    return applied - correction

def _component_energy_per_charge_v(mass_amu: float, charge_state: float, velocity_m_s: float) -> float:
    return kinetic_energy_ev(mass_amu, velocity_m_s, 0.0, 0.0) / abs(charge_state)

def _exit_energy_assessment(
    sources: dict[int, dict[str, float]], events: dict[int, dict[str, dict[str, float]]],
    campaign: dict[str, Any], plane_tolerance: float, *, geometry_profile: dict[str, Any],
) -> dict[str, Any]:
    species, acceptance = campaign["release_spec"]["species"], campaign["acceptance"]
    mass = _finite(species["mass_amu"], "release mass")
    charge = _finite(species["charge_state"], "release charge state")
    if mass <= 0.0 or charge == 0.0:
        raise ComponentFocusError("release species is invalid")
    target_axial = _target_axial_energy_per_charge_v(campaign, geometry_profile=geometry_profile)
    slow_tolerance = _finite(acceptance["maximum_exit_slow_energy_error_per_charge_v"], "exit slow-energy tolerance")
    axial_tolerance = _finite(acceptance["maximum_exit_axial_energy_error_per_charge_v"], "exit axial-energy tolerance")
    transverse_tolerance = _finite(acceptance["maximum_exit_transverse_energy_error_per_charge_v"], "exit transverse-energy tolerance")
    velocity_bias_tolerance = _finite(
        acceptance["maximum_exit_transverse_velocity_bias_mm_per_us"],
        "exit transverse-velocity bias tolerance",
    )
    rows: list[dict[str, Any]] = []
    for ion, source in sources.items():
        exit_state = events[ion].get("exit")
        if exit_state is None:
            continue
        if exit_state["vz_mm_us"] >= 0.0 or abs(exit_state["z_mm"]) > plane_tolerance:
            raise ComponentFocusError(f"ion {ion} exit event is not a -z crossing of the accelerator exit plane")
        source_slow = _component_energy_per_charge_v(mass, charge, source["vy_m_s"])
        source_transverse = _component_energy_per_charge_v(mass, charge, source["vx_m_s"])
        source_axial = _component_energy_per_charge_v(mass, charge, source["vz_m_s"])
        measured_slow = _component_energy_per_charge_v(mass, charge, exit_state["vy_mm_us"] * 1000.0)
        measured_transverse = _component_energy_per_charge_v(mass, charge, exit_state["vx_mm_us"] * 1000.0)
        measured_axial = _component_energy_per_charge_v(mass, charge, exit_state["vz_mm_us"] * 1000.0)
        expected_axial = _target_axial_energy_per_charge_v(campaign, source["z_mm"], geometry_profile=geometry_profile) + source_axial
        slow_residual, axial_residual = measured_slow - source_slow, measured_axial - expected_axial
        transverse_residual = measured_transverse - source_transverse
        source_vx = source["vx_m_s"] / 1000.0
        delta_vx = exit_state["vx_mm_us"] - source_vx
        delta_x = exit_state["x_mm"] - source["x_mm"]
        rows.append({
            "particle_id": ion,
            "source_slow_energy_per_charge_v": source_slow,
            "measured_exit_slow_energy_per_charge_v": measured_slow,
            "slow_energy_residual_per_charge_v": slow_residual,
            "source_transverse_energy_per_charge_v": source_transverse,
            "measured_exit_transverse_energy_per_charge_v": measured_transverse,
            "transverse_energy_residual_per_charge_v": transverse_residual,
            "source_x_mm": source["x_mm"],
            "measured_exit_x_mm": exit_state["x_mm"],
            "delta_x_mm": delta_x,
            "source_vx_mm_per_us": source_vx,
            "measured_exit_vx_mm_per_us": exit_state["vx_mm_us"],
            "delta_vx_mm_per_us": delta_vx,
            "source_axial_energy_per_charge_v": source_axial,
            "expected_exit_axial_energy_per_charge_v": expected_axial,
            "measured_exit_axial_energy_per_charge_v": measured_axial,
            "axial_energy_residual_per_charge_v": axial_residual,
            "slow_energy_passed": abs(slow_residual) <= slow_tolerance,
            "axial_energy_passed": abs(axial_residual) <= axial_tolerance,
            "transverse_energy_passed": abs(transverse_residual) <= transverse_tolerance,
            "transverse_velocity_bias_passed": abs(delta_vx) <= velocity_bias_tolerance,
        })
    center = next((row for row in rows if row["particle_id"] == 1), None)
    maximum_slow = max((abs(row["slow_energy_residual_per_charge_v"]) for row in rows), default=None)
    maximum_axial = max((abs(row["axial_energy_residual_per_charge_v"]) for row in rows), default=None)
    maximum_transverse = max((abs(row["transverse_energy_residual_per_charge_v"]) for row in rows), default=None)
    mean_delta_x = fmean(row["delta_x_mm"] for row in rows) if rows else None
    mean_delta_vx = fmean(row["delta_vx_mm_per_us"] for row in rows) if rows else None
    complete = len(rows) == len(sources)
    slow_passed = complete and maximum_slow is not None and maximum_slow <= slow_tolerance
    axial_passed = complete and maximum_axial is not None and maximum_axial <= axial_tolerance
    transverse_passed = complete and maximum_transverse is not None and maximum_transverse <= transverse_tolerance
    velocity_bias_passed = (
        complete and center is not None and mean_delta_vx is not None
        and abs(center["delta_vx_mm_per_us"]) <= velocity_bias_tolerance
        and abs(mean_delta_vx) <= velocity_bias_tolerance
    )
    return {
        "exit_plane_relative_z_mm": 0.0,
        "target_axial_energy_per_charge_v": target_axial,
        "tolerances": {
            "maximum_exit_slow_energy_error_per_charge_v": slow_tolerance,
            "maximum_exit_axial_energy_error_per_charge_v": axial_tolerance,
            "maximum_exit_transverse_energy_error_per_charge_v": transverse_tolerance,
            "maximum_exit_transverse_velocity_bias_mm_per_us": velocity_bias_tolerance,
        },
        "center_particle": center,
        "cohort": {
            "expected_particle_count": len(sources), "measured_particle_count": len(rows),
            "maximum_absolute_slow_energy_residual_per_charge_v": maximum_slow,
            "maximum_absolute_axial_energy_residual_per_charge_v": maximum_axial,
            "maximum_absolute_transverse_energy_residual_per_charge_v": maximum_transverse,
            "mean_delta_x_mm": mean_delta_x,
            "mean_delta_vx_mm_per_us": mean_delta_vx,
            "slow_energy_passed": slow_passed, "axial_energy_passed": axial_passed,
            "transverse_energy_passed": transverse_passed,
            "transverse_velocity_bias_passed": velocity_bias_passed,
        },
        "passed": slow_passed and axial_passed and transverse_passed and velocity_bias_passed,
    }
