"""Derive the fail-closed two-level analyser refinement plan.

The plan does not solve a field.  It converts the resolved physical geometry
and the numerical contract into grid-aligned patch boxes, node counts and PA
family storage estimates.  A later SIMION builder must still supply every
coarse-basis boundary value and pass the declared interface-continuity gate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_pa_family_cache import (
    pa_family_filenames,
)


def _vector(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise CandidateContractError(f"{label} must contain three values")
    if any(isinstance(item, bool) for item in value):
        raise CandidateContractError(f"{label} must contain numbers, not booleans")
    result = tuple(float(item) for item in value)
    if any(not math.isfinite(item) for item in result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _box_bounds(box: Any, label: str) -> tuple[float, float, float, float, float, float]:
    if not isinstance(box, list) or len(box) != 6:
        raise CandidateContractError(f"{label} must be a six-value box")
    values = tuple(float(item) for item in box)
    if any(not math.isfinite(item) for item in values):
        raise CandidateContractError(f"{label} must be finite")
    if any(values[index + 3] < values[index] for index in range(3)):
        raise CandidateContractError(f"{label} has reversed bounds")
    return values


def _polygon_bounds(item: dict[str, Any], label: str) -> tuple[float, float, float, float, float, float]:
    x = item.get("x")
    polygon = item.get("polygon_yz_mm")
    if not isinstance(x, list) or len(x) != 2 or not isinstance(polygon, list) or len(polygon) < 3:
        raise CandidateContractError(f"{label} is not an extruded yz polygon")
    xs = [float(value) for value in x]
    ys = [float(point[0]) for point in polygon]
    zs = [float(point[1]) for point in polygon]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _item_bounds(item: dict[str, Any], label: str) -> list[tuple[float, float, float, float, float, float]]:
    if "box" in item:
        return [_box_bounds(item["box"], f"{label}.box")]
    if "x" in item and "polygon_yz_mm" in item:
        return [_polygon_bounds(item, label)]
    for key in ("parts", "body_sections"):
        if key in item:
            values = item[key]
            if not isinstance(values, list) or not values:
                raise CandidateContractError(f"{label}.{key} must be non-empty")
            return [bound for index, child in enumerate(values)
                    for bound in _item_bounds(child, f"{label}.{key}[{index}]")]
    raise CandidateContractError(f"{label} has no supported physical bounds")


def _role_bounds(
    resolved: dict[str, Any], roles: Iterable[str], *, positive_z_only: bool = False,
) -> tuple[float, float, float, float, float, float]:
    bounds: list[tuple[float, float, float, float, float, float]] = []
    for role in roles:
        items = resolved.get(role)
        if not isinstance(items, list) or not items:
            raise CandidateContractError(f"resolved geometry role is missing: {role}")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise CandidateContractError(f"resolved geometry {role}[{index}] must be an object")
            for bound in _item_bounds(item, f"{role}[{index}]"):
                if not positive_z_only or bound[2] >= 0.0:
                    bounds.append(bound)
    if not bounds:
        raise CandidateContractError("local refinement region has no physical geometry")
    return tuple(min(bound[index] for bound in bounds) if index < 3
                 else max(bound[index] for bound in bounds) for index in range(6))


def _snap_patch(
    raw: tuple[float, float, float, float, float, float],
    global_box: tuple[float, float, float, float, float, float],
    origin: tuple[float, float, float], mesh: tuple[float, float, float],
) -> tuple[float, float, float, float, float, float]:
    low: list[float] = []
    high: list[float] = []
    for axis in range(3):
        lo = origin[axis] + math.floor((raw[axis] - origin[axis]) / mesh[axis] + 1e-12) * mesh[axis]
        hi = origin[axis] + math.ceil((raw[axis + 3] - origin[axis]) / mesh[axis] - 1e-12) * mesh[axis]
        lo = max(lo, global_box[axis])
        hi = min(hi, global_box[axis + 3])
        if hi <= lo:
            raise CandidateContractError("snapped local refinement patch is empty")
        low.append(lo)
        high.append(hi)
    return (*low, *high)


def _shape(box: tuple[float, float, float, float, float, float], mesh: tuple[float, float, float]) -> list[int]:
    result: list[int] = []
    for axis in range(3):
        cells = (box[axis + 3] - box[axis]) / mesh[axis]
        rounded = round(cells)
        if abs(cells - rounded) > 1e-8:
            raise CandidateContractError("patch extent is not aligned to the selected mesh")
        result.append(int(rounded) + 1)
    return result


def _profile(
    profile_id: str, box: tuple[float, float, float, float, float, float],
    mesh: tuple[float, float, float], arrays: int, bytes_per_point: int,
) -> dict[str, Any]:
    shape = _shape(box, mesh)
    points = math.prod(shape)
    return {
        "profile_id": profile_id,
        "box_project_mm": list(box),
        "mesh_mm_per_gu": list(mesh),
        "grid_shape": shape,
        "grid_points_per_array": points,
        "pa_array_count": arrays,
        "estimated_family_bytes": points * arrays * bytes_per_point,
    }


def derive_local_refinement_plan(contract_path: Path) -> dict[str, Any]:
    """Return a geometry-derived local-refinement and storage plan."""
    contract = load_contract(contract_path)
    simion = contract.get("simion")
    if not isinstance(simion, dict):
        raise CandidateContractError("simion contract is required")
    spec = simion.get("analyzer_spatial_convergence")
    if not isinstance(spec, dict):
        raise CandidateContractError("simion.analyzer_spatial_convergence is required")
    expected = {
        "status", "baseline_profile_id", "local_mesh_scale_factors", "patch_margin_mm",
        "storage_bytes_per_grid_point_estimate", "response_voltage_groups",
        "fixed_zero_electrode_ids", "regions", "boundary_rule", "workbench_rule",
        "continuity_gate", "retuning_rule", "forbidden_shortcuts",
    }
    if set(spec) != expected:
        raise CandidateContractError("analyzer spatial-convergence field set differs")
    baseline_mesh = _vector(simion["component_mesh_mm_per_gu"]["analyzer"], "analyzer mesh")
    if min(baseline_mesh) <= 0.0:
        raise CandidateContractError("analyzer mesh must be positive")
    span = _vector(simion["analyzer_pa_span_mm"], "analyzer span")
    origin = _vector(simion["analyzer_pa_origin_mm"], "analyzer origin")
    global_box = (*origin, *(origin[index] + span[index] for index in range(3)))
    margin = _vector(spec["patch_margin_mm"], "patch margin")
    if min(margin) <= 0.0:
        raise CandidateContractError("patch margins must be positive")
    scales = spec["local_mesh_scale_factors"]
    if not isinstance(scales, list) or len(scales) < 3:
        raise CandidateContractError("at least three local mesh scales are required")
    factors = [float(value) for value in scales]
    if any(not math.isfinite(value) or value <= 0.0 for value in factors) or any(
        factors[index + 1] >= factors[index] for index in range(len(factors) - 1)
    ):
        raise CandidateContractError("local mesh scales must be positive and strictly decreasing")
    bytes_per_point = spec["storage_bytes_per_grid_point_estimate"]
    if not isinstance(bytes_per_point, int) or isinstance(bytes_per_point, bool) or bytes_per_point <= 0:
        raise CandidateContractError("storage estimate must be a positive integer")
    regions = spec["regions"]
    if not isinstance(regions, dict) or set(regions) != {"mirror_turn", "central_transport"}:
        raise CandidateContractError("local refinement regions differ")
    resolved = resolve_geometry(contract)

    response_groups = spec["response_voltage_groups"]
    if not isinstance(response_groups, dict) or not response_groups:
        raise CandidateContractError("response voltage groups must be a non-empty object")
    grouped_ids: list[int] = []
    for name, identifiers in response_groups.items():
        if not isinstance(name, str) or not name or not isinstance(identifiers, list) or not identifiers:
            raise CandidateContractError("every response voltage group must have a name and electrode IDs")
        if any(not isinstance(item, int) or isinstance(item, bool) for item in identifiers):
            raise CandidateContractError(f"response voltage group {name} contains a non-integer ID")
        grouped_ids.extend(identifiers)
    fixed_ids = spec["fixed_zero_electrode_ids"]
    if not isinstance(fixed_ids, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in fixed_ids
    ):
        raise CandidateContractError("fixed-zero electrode IDs must be an integer list")
    if len(set(grouped_ids + fixed_ids)) != len(grouped_ids) + len(fixed_ids):
        raise CandidateContractError("response and fixed-zero electrode IDs must be disjoint and unique")
    analyzer_ids = set(range(1, len(pa_family_filenames("analyzer")) - 1))
    if set(grouped_ids + fixed_ids) != analyzer_ids:
        raise CandidateContractError("response and fixed-zero groups must partition the analyzer electrode namespace")
    response_family_arrays = len(response_groups) + 2  # raw geometry, PA0, and one array per group
    local_group_ids = {name: index for index, name in enumerate(response_groups, 1)}
    physical_to_local_id = {
        str(identifier): local_group_ids[name]
        for name, identifiers in response_groups.items()
        for identifier in identifiers
    }
    physical_to_local_id.update({str(identifier): 0 for identifier in fixed_ids})

    mirror_roles = regions["mirror_turn"]["geometry_roles"]
    mirror_physical = _role_bounds(resolved, mirror_roles, positive_z_only=True)
    slot = resolved.get("mirror_slot")
    if not isinstance(slot, list) or len(slot) != 6:
        raise CandidateContractError("resolved mirror slot is required")
    mirror_half_x = max(abs(float(slot[0])), abs(float(slot[3]))) + margin[0]
    mirror_raw = (
        -mirror_half_x, mirror_physical[1] - margin[1], mirror_physical[2] - margin[2],
        mirror_half_x, mirror_physical[4] + margin[1], mirror_physical[5] + margin[2],
    )
    mirror_box = _snap_patch(mirror_raw, global_box, origin, baseline_mesh)

    central_roles = regions["central_transport"]["geometry_roles"]
    central_physical = _role_bounds(resolved, central_roles)
    central_half_x = max(abs(central_physical[0]), abs(central_physical[3])) + margin[0]
    central_raw = (
        -central_half_x, central_physical[1] - margin[1], central_physical[2] - margin[2],
        central_half_x, central_physical[4] + margin[1], central_physical[5] + margin[2],
    )
    central_box = _snap_patch(central_raw, global_box, origin, baseline_mesh)

    def validate_local_groups(name: str) -> None:
        region = regions[name]
        if not isinstance(region, dict):
            raise CandidateContractError(f"local refinement region {name} must be an object")
        values = region.get("local_geometry_voltage_groups")
        if not isinstance(values, list) or not values or any(value not in response_groups for value in values):
            raise CandidateContractError(f"local refinement region {name} has invalid local voltage groups")

    validate_local_groups("mirror_turn")
    validate_local_groups("central_transport")

    profiles: list[dict[str, Any]] = []
    for factor in factors:
        mesh = tuple(value * factor for value in baseline_mesh)
        token = format(factor, ".12g").replace(".", "p")
        profiles.append({
            "scale_factor": factor,
            "mirror_turn": _profile(
                f"mirror_turn_{token}", mirror_box, mesh,
                response_family_arrays, bytes_per_point,
            ),
            "central_transport": _profile(
                f"central_transport_{token}", central_box, mesh,
                response_family_arrays, bytes_per_point,
            ),
        })
    global_shape = _shape(global_box, baseline_mesh)
    global_arrays = len(pa_family_filenames("analyzer"))
    half_mesh = tuple(value * 0.5 for value in baseline_mesh)
    global_half_shape = _shape(global_box, half_mesh)
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_two_level_local_refinement_plan",
        "status": spec["status"],
        "baseline": {
            "profile_id": spec["baseline_profile_id"],
            "box_project_mm": list(global_box),
            "mesh_mm_per_gu": list(baseline_mesh),
            "grid_shape": global_shape,
            "pa_array_count": global_arrays,
            "estimated_family_bytes": math.prod(global_shape) * global_arrays * bytes_per_point,
        },
        "rejected_naive_global_half_mesh": {
            "mesh_mm_per_gu": list(half_mesh),
            "grid_shape": global_half_shape,
            "pa_array_count": global_arrays,
            "estimated_family_bytes": math.prod(global_half_shape) * global_arrays * bytes_per_point,
            "reason": "capacity preflight is required before any full-envelope half-mesh family",
        },
        "patches": {"mirror_turn_positive": list(mirror_box), "central_transport": list(central_box)},
        "profiles": profiles,
        "response_voltage_groups": response_groups,
        "fixed_zero_electrode_ids": fixed_ids,
        "local_fast_adjust_group_ids": local_group_ids,
        "physical_to_local_electrode_id": physical_to_local_id,
        "boundary_rule": spec["boundary_rule"],
        "workbench_rule": spec["workbench_rule"],
        "continuity_gate": spec["continuity_gate"],
        "retuning_rule": spec["retuning_rule"],
        "qualification": "planning_only__no_local_pa_built_or_flown",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    document = derive_local_refinement_plan(arguments.contract)
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if arguments.output is None:
        print(text, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
