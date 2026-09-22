"""Derive the smallest numerical domain for the closed two-zone focus PA."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from projects.orthogonal_accelerator.analysis.component_focus_analysis import _load_campaign
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import accelerator_state
from projects.orthogonal_accelerator.simion.two_zone_candidate import (
    _load_geometry_profile, compile_closed_two_zone_accelerator,
)


class ComponentFocusPAPlanError(ValueError):
    """Raised when the focus campaign cannot define one numerical PA."""


def _positive(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ComponentFocusPAPlanError(f"{label} must be positive")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ComponentFocusPAPlanError(f"{label} must be positive") from error
    if not math.isfinite(result) or result <= 0.0:
        raise ComponentFocusPAPlanError(f"{label} must be positive")
    return result


def _ceil_mesh(value: float, mesh: float) -> float:
    return math.ceil((value - 1e-12) / mesh) * mesh


def _validate_theory_seed(campaign: dict[str, Any], layout: dict[str, Any]) -> dict[str, float]:
    """Bind the exit-frame source and nine PA voltages to the 1-D two-zone seed."""
    geometry = campaign["release_spec"]["geometry"]
    source_center = float(geometry["center_mm"][2])
    source_half_height = float(geometry["height_mm"]) / 2.0
    gap_1, gap_2 = float(layout["gap_1_mm"]), float(layout["gap_2_mm"])
    if not gap_2 < source_center - source_half_height < source_center + source_half_height < gap_2 + gap_1:
        raise ComponentFocusPAPlanError("campaign source cylinder is outside provider first acceleration gap")
    release_position = gap_1 + gap_2 - source_center
    voltages = [float(value) for value in campaign["operating_point"]["electrode_voltages_v"]]
    state = accelerator_state(
        voltages[1], voltages[2], gap_1, gap_2,
        exit_v=voltages[3], release_position_mm=release_position,
    )
    expected_focus = -float(campaign["operating_point"]["focus_plane_offset_from_exit_mm"])
    # The operating seed is deliberately published to 0.1 microvolt precision.
    # That finite decimal form moves an exit-plane first-order root by about
    # 4e-9 mm, so retain it while rejecting material focus-plane drift.
    if not math.isclose(state.first_order_focus_drift_mm, expected_focus, rel_tol=0.0, abs_tol=1.0e-8):
        raise ComponentFocusPAPlanError("campaign first-gap voltages do not reproduce the declared time-focus plane")
    for index, voltage in enumerate(voltages[4:], 1):
        expected_ring = voltages[2] + (voltages[3] - voltages[2]) * index / 6.0
        if not math.isclose(voltage, expected_ring, rel_tol=0.0, abs_tol=1.0e-9):
            raise ComponentFocusPAPlanError("campaign second-region rings do not linearly interpolate grid1 to exit")
    return {"source_center_exit_mm": source_center, "release_position_from_repeller_mm": release_position,
            "first_order_focus_drift_mm": state.first_order_focus_drift_mm,
            "nominal_energy_per_charge_v": state.nominal_energy_per_charge_v}


def derive(campaign_path: Path) -> dict[str, Any]:
    """Place exit/focus/end enclosure inside one PA without changing hardware.

    ``focus_plane_padding_mm`` is the distance from PA z=0 to the declared
    downstream focus plane.  The positive-z padding protects the closed cap.
    Both values are numerical-domain requirements, never geometry knobs.
    """
    campaign = _load_campaign(campaign_path)
    projection = campaign["simion_projection"]
    required = {
        "source_frame", "workbench_mapping", "local_pa_span_mm", "iob_origin_rule",
        "local_exit_z_mm", "semantics", "focus_plane_padding_mm", "positive_z_enclosure_padding_mm",
    }
    if set(projection) != required:
        raise ComponentFocusPAPlanError("component focus projection must declare both numerical paddings")
    span = projection["local_pa_span_mm"]
    if not isinstance(span, list) or len(span) != 3:
        raise ComponentFocusPAPlanError("component focus transverse PA span is invalid")
    mesh = projection.get("mesh_mm_per_gu")
    # The original public campaign schema did not carry mesh. Keep it in the
    # numerical plan contract instead of letting callers infer it from PA bytes.
    if mesh is None:
        mesh = [0.25, 0.25, 0.1]
    if not isinstance(mesh, list) or len(mesh) != 3:
        raise ComponentFocusPAPlanError("component focus PA mesh is invalid")
    declared_spans = [_positive(value, "PA span") for value in span]
    mesh_xyz = [_positive(value, "PA mesh") for value in mesh]
    profile = _load_geometry_profile(campaign["geometry_profile_id"])
    # The provider derives transverse PA extents from its closed grounded shell,
    # retaining one mesh cell on either side.  Consumers cannot waste cache
    # capacity by prescribing a larger numerical aperture.
    spans = [
        _ceil_mesh(float(profile["guard_outer_width_x_mm"]) + 2.0 * mesh_xyz[0], mesh_xyz[0]),
        _ceil_mesh(float(profile["guard_outer_height_y_mm"]) + 2.0 * mesh_xyz[1], mesh_xyz[1]),
        declared_spans[2],
    ]
    focus_padding = _positive(projection["focus_plane_padding_mm"], "focus-plane padding")
    enclosure_padding = _positive(projection["positive_z_enclosure_padding_mm"], "positive-z enclosure padding")
    focus_offset = float(campaign["operating_point"]["focus_plane_offset_from_exit_mm"])
    if not math.isfinite(focus_offset) or focus_offset > 0.0:
        raise ComponentFocusPAPlanError("focus plane must be at or downstream of the exit")
    local_exit = focus_padding - focus_offset
    declared_exit = _positive(projection["local_exit_z_mm"], "declared local exit")
    if not math.isclose(declared_exit, local_exit, rel_tol=0.0, abs_tol=1e-9):
        raise ComponentFocusPAPlanError("declared local exit differs from focus-plane-derived placement")
    # Read the provider-owned profile once: neither the consumer campaign nor
    # the numerical plan may carry a duplicate physical repeller position.
    repeller_to_exit_mm = float(profile["gap_1_mm"]) + float(profile["gap_2_mm"])
    requirements = {
        "schema_version": 1,
        "role": "orthogonal_accelerator_two_zone_requirements",
        "variant_id": "two_zone", "acceleration_direction": "-z",
        "source_cylinder": {"radius_mm": campaign["release_spec"]["geometry"]["radius_mm"],
                            "height_mm": campaign["release_spec"]["geometry"]["height_mm"]},
        "focus": {"mode": "two_zone_time_focus", "focus_plane": "component_focus_plane"},
        "compaction": {"axes": ["y", "z"], "objective": "minimize_subject_to_focus"},
        "local_pa": {"span_mm": [spans[0], spans[1], 1.0], "mesh_mm_per_gu": mesh_xyz,
                     "exit_z_mm": local_exit, "margin_z_mm": enclosure_padding},
        "placement": {"focus_y_mm": 0.0, "global_repeller_z_mm": repeller_to_exit_mm,
                      "global_exit_z_mm": 0.0},
    }
    # This derives the sealed enclosure length directly from the provider
    # profile. It avoids compiling any placeholder PA domain (such as 1000 mm)
    # whose size could otherwise leak into identity or build evidence.
    static_axial_length = sum(float(profile[key]) for key in (
        "gap_1_mm", "gap_2_mm", "repeller_thickness_z_mm", "rear_gap_mm", "guard_wall_thickness_mm"
    ))
    minimum_z = static_axial_length + local_exit + enclosure_padding
    resolved_span_z = _ceil_mesh(minimum_z, mesh_xyz[2])
    requirements["local_pa"]["span_mm"][2] = resolved_span_z
    declared_span_z = declared_spans[2]
    if not math.isclose(declared_span_z, resolved_span_z, rel_tol=0.0, abs_tol=1e-9):
        raise ComponentFocusPAPlanError("declared PA z span differs from focus-plane-derived numerical domain")
    compiled = compile_closed_two_zone_accelerator(requirements, geometry_profile_id=campaign["geometry_profile_id"])
    focus_local = local_exit + focus_offset
    if focus_local < focus_padding - 1e-9 or focus_local <= 0.0:
        raise ComponentFocusPAPlanError("derived focus plane is outside the PA")
    theory_seed = _validate_theory_seed(campaign, compiled.layout.to_dict())
    return {
        "schema_version": 1,
        "role": "orthogonal_accelerator_component_focus_pa_plan",
        "status": "derived",
        "qualification": "numerical_domain_layout_only__native_build_and_focus_pending",
        "campaign_path": str(campaign_path.resolve()),
        "geometry_profile_id": compiled.layout.geometry_profile_id,
        "cache_policy": "one_native_fast_adjust_family_pa_hash_and_pa0_through_pa9__published_read_only_no_detached_response_bank",
        "numerical_domain": {
            "span_mm": [spans[0], spans[1], resolved_span_z],
            "mesh_mm_per_gu": mesh_xyz,
            "iob_origin_mm": [-spans[0] / 2.0, -spans[1] / 2.0, 0.0],
            "focus_plane_local_z_mm": focus_local,
            "focus_plane_padding_mm": focus_padding,
            "positive_z_enclosure_padding_mm": enclosure_padding,
            "local_exit_z_mm": local_exit,
        },
        "layout": compiled.layout.to_dict(),
        "theory_seed": theory_seed,
        "requirements": requirements,
        "gem": compiled.gem,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = derive(args.campaign)
    except (OSError, ValueError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_PA_PLAN=FAIL ERROR={error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print("ACCELERATOR_COMPONENT_FOCUS_PA_PLAN=PASS "
          f"EXIT_Z_MM={plan['numerical_domain']['local_exit_z_mm']:.12g} "
          f"FOCUS_Z_MM={plan['numerical_domain']['focus_plane_local_z_mm']:.12g} "
          f"SPAN_Z_MM={plan['numerical_domain']['span_mm'][2]:.12g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
