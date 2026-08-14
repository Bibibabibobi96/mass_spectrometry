"""Atomically compile one finite-interval oaTOF longitudinal design.

The integration supplies source phase-space and requested interval dimensions.  This
project-owned compiler is the sole authority for accelerator voltages and placement,
the coupled reflectron solution, the retained geometry, shield bounds, and rebuild
effects.  Integration provenance is deliberately outside this API and its resolved
geometry.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    accelerator_state,
    linear_phase_space_timing_coefficients,
    match_finite_phase_space_interval,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    derive_accelerator_outer_envelope_min_z,
    derive_shield_bounds,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    solve_coupled_reflectron_from_accelerator_derivatives,
)


FINITE_INTERVAL_COMPILER_POLICY = {
    "policy_id": "finite_interval_uniform_two_field_theory_v1",
    "voltage_drop_bounds_V": (100.0, 1200.0),
    "sample_count": 1001,
    "voltage_tolerance_V": 1e-8,
}


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _phase_space_input(request: Mapping[str, Any]) -> dict[str, Any]:
    raw = request.get("phase_space_input")
    if not isinstance(raw, Mapping):
        raise ValueError("finite-interval phase_space_input must be an object")
    expected = {
        "mass_to_charge_Th",
        "release_position_mm",
        "mean_initial_velocity_m_per_s",
        "velocity_slope_m_per_s_per_mm",
    }
    if set(raw) != expected:
        raise ValueError("finite-interval phase_space_input fields differ")
    phase_space = copy.deepcopy(dict(raw))
    for name in (
        "mass_to_charge_Th",
        "release_position_mm",
        "mean_initial_velocity_m_per_s",
        "velocity_slope_m_per_s_per_mm",
    ):
        _finite_float(phase_space[name], name)
    if float(phase_space["mass_to_charge_Th"]) <= 0.0:
        raise ValueError("finite-interval mass_to_charge_Th must be positive")
    return phase_space


def compile_finite_interval_oatof_design(
    base_geometry: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    prior_rebuild_plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the fully closed geometry and one atomic design-compilation receipt."""

    if base_geometry.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("finite-interval compilation requires resolved oaTOF geometry")
    if set(request) != {
        "phase_space_input",
        "accelerator_stage1_length_mm",
        "source_full_width_mm",
    }:
        raise ValueError("finite-interval design request fields differ")
    if not isinstance(prior_rebuild_plan, Mapping):
        raise ValueError("finite-interval compilation requires the prior rebuild plan")
    geometry = copy.deepcopy(dict(base_geometry))
    phase_space = _phase_space_input(request)
    stage1_length_mm = _finite_float(
        request["accelerator_stage1_length_mm"], "accelerator_stage1_length_mm"
    )
    source_full_width_mm = _finite_float(
        request["source_full_width_mm"], "source_full_width_mm"
    )
    if stage1_length_mm <= 0.0 or source_full_width_mm <= 0.0:
        raise ValueError("finite-interval stage-1 length and source width must be positive")

    accelerator = geometry["geometry_derivation"]["accelerator"]
    accelerator["d1_mm"] = stage1_length_mm
    geometry["geometry_mm"]["L_accel"] = (
        stage1_length_mm + float(accelerator["d2_mm"])
    )
    nominal_energy = geometry["geometry_derivation"]["reflectron"][
        "nominal_energy_per_charge_V"
    ]
    solution = match_finite_phase_space_interval(
        stage1_length_mm,
        float(accelerator["d2_mm"]),
        float(phase_space["release_position_mm"]),
        source_full_width_mm,
        float(phase_space["mean_initial_velocity_m_per_s"]),
        float(phase_space["velocity_slope_m_per_s_per_mm"]),
        float(phase_space["mass_to_charge_Th"]),
        float(nominal_energy),
        exit_v=float(geometry["electrodes_V"]["grid2"]),
        voltage_drop_bounds_v=FINITE_INTERVAL_COMPILER_POLICY[
            "voltage_drop_bounds_V"
        ],
        sample_count=int(FINITE_INTERVAL_COMPILER_POLICY["sample_count"]),
        voltage_tolerance_v=float(
            FINITE_INTERVAL_COMPILER_POLICY["voltage_tolerance_V"]
        ),
    )
    geometry["electrodes_V"]["repeller"] = solution.repeller_v
    geometry["electrodes_V"]["grid1"] = solution.intermediate_v
    geometry["geometry_mm"]["accelerator_repeller_z"] = (
        solution.canonical_repeller_z_mm
    )
    geometry["geometry_mm"]["accelerator_grid1_z"] = solution.canonical_grid1_z_mm
    geometry["geometry_mm"]["accelerator_grid2_z"] = solution.canonical_grid2_z_mm
    geometry["particle_source"]["center_z_mm"] = (
        solution.canonical_repeller_z_mm + solution.source_center_mm
    )
    geometry["particle_source"]["center_z_rule"] = (
        "geometry_derivation.accelerator.finite_interval_theory."
        "canonical_repeller_z_mm + source_center_mm"
    )
    geometry["particle_source"]["size_z_mm"] = solution.source_full_width_mm

    accelerator_state_value = accelerator_state(
        solution.repeller_v,
        solution.intermediate_v,
        float(accelerator["d1_mm"]),
        float(accelerator["d2_mm"]),
        exit_v=solution.exit_v,
        release_position_mm=solution.source_center_mm,
        require_downstream_focus=False,
    )
    coefficients = linear_phase_space_timing_coefficients(
        accelerator_state_value,
        float(phase_space["mass_to_charge_Th"]),
        solution.mean_initial_velocity_m_per_s,
        solution.velocity_slope_m_per_s_per_mm,
        solution.focus_drift_mm,
    )
    half_energy_range = solution.stage1_field_v_per_mm * (
        solution.source_full_width_mm / 2.0
    )
    coupled = solve_coupled_reflectron_from_accelerator_derivatives(
        coefficients.actual_energy_per_charge_v,
        float(geometry["geometry_mm"]["L_stage1"]),
        float(geometry["geometry_mm"]["L_flight"]),
        float(geometry["geometry_mm"]["L_flight"]),
        coefficients.first_derivative_at_focus,
        coefficients.second_derivative_at_focus,
        energy_min_v=solution.nominal_energy_per_charge_v - half_energy_range,
        energy_max_v=solution.nominal_energy_per_charge_v + half_energy_range,
    )
    if coupled.required_stage2_depth_mm > float(geometry["geometry_mm"]["L_stage2"]):
        raise ValueError(
            "finite-interval coupled reflectron exceeds the retained stage-2 length"
        )
    geometry["electrodes_V"]["midgrid"] = coupled.stage1_voltage_drop_v
    geometry["electrodes_V"]["backplate"] = (
        coupled.stage1_voltage_drop_v
        + coupled.stage2_field_v_per_mm * float(geometry["geometry_mm"]["L_stage2"])
    )
    reflectron = geometry["geometry_derivation"]["reflectron"]
    reflectron.update(
        {
            "nominal_energy_per_charge_V": solution.nominal_energy_per_charge_v,
            "source_release_full_width_mm": solution.source_full_width_mm,
            "spatial_energy_half_range_V": half_energy_range,
            "energy_min_V": solution.nominal_energy_per_charge_v - half_energy_range,
            "energy_max_V": solution.nominal_energy_per_charge_v + half_energy_range,
        }
    )
    accelerator.update(
        {
            "rule": (
                f"Set d1={stage1_length_mm:g} mm and solve the finite source interval "
                "accelerator voltages, axial translation, and coupled reflectron "
                "voltages from the frozen first- and second-order timing model."
            ),
            "canonical_repeller_z_mm": solution.canonical_repeller_z_mm,
            "canonical_grid1_z_mm": solution.canonical_grid1_z_mm,
            "canonical_grid2_z_mm": solution.canonical_grid2_z_mm,
            "canonical_focus_z_mm": 0.0,
            "focus_drift_after_grid2_mm": solution.focus_drift_mm,
            "finite_interval_theory": {
                **solution.__dict__,
                "solver_phase_space_input": phase_space,
                "linear_phase_space_coefficients": coefficients.__dict__,
                "coupled_reflectron": coupled.__dict__,
            },
        }
    )
    derive_shield_bounds(geometry, derive_accelerator_outer_envelope_min_z(geometry))
    compilation = {
        "method": FINITE_INTERVAL_COMPILER_POLICY["policy_id"],
        "changed_variables": [
            "accelerator_stage1_length",
            "source_release_full_width",
        ],
        "rebuild_effects": [
            "accelerator_voltage",
            "accelerator_axial_position",
            "reflectron_voltage",
        ],
        "simion_rebuild_plan": {
            "frontend_pa": True,
            "flight_tube_pa": True,
            "reflectron_pa": bool(prior_rebuild_plan["reflectron_pa"]),
        },
        "reflectron_voltage_application": {
            "pa0_basis_reused": True,
            "method": "official_simion_runtime_fast_adjust_v1",
            "voltage_authority": "electrodes_V",
            "runtime_call": "r:fast_adjust(reflectron_voltages)",
        },
    }
    return geometry, compilation
