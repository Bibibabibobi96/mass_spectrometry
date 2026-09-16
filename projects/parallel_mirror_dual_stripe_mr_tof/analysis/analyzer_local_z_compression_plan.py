"""Evaluate planning-only z compression alternatives for local analyser PAs.

The accepted five-region PA/IOB remains immutable.  This module derives three
replacement candidates from the resolved geometry, existing patch boxes,
handoff responsibility planes and the half-open ``instance_adjust`` ownership
semantics.  It performs no SIMION call and writes no artifact unless its CLI is
given an explicit output path.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_refinement_plan import (
    _box_bounds,
    _item_bounds,
    _shape,
    derive_local_refinement_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


_PHYSICAL_ROLES = (
    "mirror_electrodes",
    "mirror_ground_shields",
    "mirror_e_closures",
    "stripe_electrodes",
    "central_ground_electrodes",
    "prism_electrodes",
    "prism_ground_shields",
)


def _aligned_floor(value: float, origin: float, mesh: float) -> float:
    return origin + math.floor((value - origin) / mesh + 1e-12) * mesh


def _aligned_ceil(value: float, origin: float, mesh: float) -> float:
    return origin + math.ceil((value - origin) / mesh - 1e-12) * mesh


def _union_box(boxes: Iterable[list[float]]) -> list[float]:
    values = list(boxes)
    if not values:
        raise CandidateContractError("cannot union an empty patch set")
    return [
        *(min(float(box[axis]) for box in values) for axis in range(3)),
        *(max(float(box[axis + 3]) for box in values) for axis in range(3)),
    ]


def _new_z_faces(
    candidate: dict[str, list[float]], source: dict[str, list[float]],
) -> list[float]:
    candidate_faces = {box[2] for box in candidate.values()} | {
        box[5] for box in candidate.values()
    }
    source_faces = {box[2] for box in source.values()} | {box[5] for box in source.values()}
    return sorted(candidate_faces - source_faces)


def _point_in_box(point: tuple[float, float, float], box: Any) -> bool:
    bounds = _box_bounds(box, "resolved box")
    return all(bounds[axis] <= point[axis] <= bounds[axis + 3] for axis in range(3))


def _point_in_polygon_yz(y_mm: float, z_mm: float, polygon: Any) -> bool:
    if not isinstance(polygon, list) or len(polygon) < 3:
        return False
    points = [(float(point[0]), float(point[1])) for point in polygon]
    inside = False
    for index, (y0, z0) in enumerate(points):
        y1, z1 = points[(index + 1) % len(points)]
        cross = (y0 > y_mm) != (y1 > y_mm)
        if cross and z_mm < (z1 - z0) * (y_mm - y0) / (y1 - y0) + z0:
            inside = not inside
    return inside


def _point_in_extruded_polygon(point: tuple[float, float, float], item: dict[str, Any]) -> bool:
    x = item.get("x")
    return (
        isinstance(x, list)
        and len(x) == 2
        and float(x[0]) <= point[0] <= float(x[1])
        and _point_in_polygon_yz(point[1], point[2], item.get("polygon_yz_mm"))
    )


def _inside_any_box(point: tuple[float, float, float], boxes: Iterable[Any]) -> bool:
    return any(_point_in_box(point, box) for box in boxes)


def _point_material_labels(resolved: dict[str, Any], point: tuple[float, float, float]) -> list[str]:
    """Return resolved conductors containing a point after known slot subtraction."""
    labels: list[str] = []
    for index, item in enumerate(resolved["mirror_electrodes"]):
        if _point_in_box(point, item["box"]) and not _point_in_box(point, item["beam_slot"]):
            labels.append(f"mirror_electrodes[{index}]")
    for index, item in enumerate(resolved["mirror_ground_shields"]):
        inside = _point_in_box(point, item["box"])
        if inside and item.get("role") == "inner_stripe_facing_4mm_slot":
            inside = not _point_in_box(point, resolved["mirror_inner_shield_slot"])
        if inside:
            labels.append(f"mirror_ground_shields[{index}]")
    for index, item in enumerate(resolved["mirror_e_closures"]):
        if _point_in_box(point, item["box"]):
            labels.append(f"mirror_e_closures[{index}]")
    for index, item in enumerate(resolved["stripe_electrodes"]):
        inside = _point_in_extruded_polygon(point, item)
        terminal = dict(item)
        terminal["polygon_yz_mm"] = item.get("terminal_polygon_yz_mm")
        inside = inside or _point_in_extruded_polygon(point, terminal)
        if inside and not _point_in_box(point, resolved["stripe_slot"]):
            labels.append(f"stripe_electrodes[{index}]")
    central_inside = any(
        _point_in_extruded_polygon(point, item) for item in resolved["central_ground_electrodes"]
    )
    if central_inside and not _inside_any_box(point, resolved["central_ground_slots"]):
        labels.append("central_ground_electrodes")
    for index, item in enumerate(resolved["prism_electrodes"]):
        if any(_point_in_extruded_polygon(point, part) for part in item["parts"]):
            labels.append(f"prism_electrodes[{index}]")
    for index, item in enumerate(resolved["prism_ground_shields"]):
        inside = any(_point_in_extruded_polygon(point, part) for part in item["body_sections"])
        aperture = {
            "x": item["x"],
            "polygon_yz_mm": item["prism_clearance_polygon_yz_mm"],
        }
        inside = inside and not _point_in_extruded_polygon(point, aperture)
        inside = inside and not _inside_any_box(point, item.get("rectangular_slots_mm", []))
        if inside:
            labels.append(f"prism_ground_shields[{index}]")
    return labels


def _point_aperture_labels(resolved: dict[str, Any], point: tuple[float, float, float]) -> list[str]:
    """Return subtractive apertures that make an otherwise occupied axis point vacuum."""
    labels: list[str] = []
    for index, item in enumerate(resolved["mirror_electrodes"]):
        if _point_in_box(point, item["box"]) and _point_in_box(point, item["beam_slot"]):
            labels.append(f"mirror_electrodes[{index}].beam_slot")
    for index, item in enumerate(resolved["mirror_ground_shields"]):
        if _point_in_box(point, item["box"]) and _point_in_box(point, resolved["mirror_inner_shield_slot"]):
            labels.append(f"mirror_ground_shields[{index}].beam_slot")
    for index, item in enumerate(resolved["stripe_electrodes"]):
        terminal = dict(item)
        terminal["polygon_yz_mm"] = item.get("terminal_polygon_yz_mm")
        parent = _point_in_extruded_polygon(point, item) or _point_in_extruded_polygon(point, terminal)
        if parent and _point_in_box(point, resolved["stripe_slot"]):
            labels.append(f"stripe_electrodes[{index}].beam_slot")
    central_parent = any(
        _point_in_extruded_polygon(point, item) for item in resolved["central_ground_electrodes"]
    )
    if central_parent:
        for index, slot in enumerate(resolved["central_ground_slots"]):
            if _point_in_box(point, slot):
                labels.append(f"central_ground_slots[{index}]")
    for index, item in enumerate(resolved["prism_ground_shields"]):
        parent = any(_point_in_extruded_polygon(point, part) for part in item["body_sections"])
        aperture = {"x": item["x"], "polygon_yz_mm": item["prism_clearance_polygon_yz_mm"]}
        if parent and _point_in_extruded_polygon(point, aperture):
            labels.append(f"prism_ground_shields[{index}].prism_clearance")
        for slot_index, slot in enumerate(item.get("rectangular_slots_mm", [])):
            if parent and _point_in_box(point, slot):
                labels.append(f"prism_ground_shields[{index}].rectangular_slots[{slot_index}]")
    return labels


def _plane_envelope_crossings(
    resolved: dict[str, Any], box: list[float], z_mm: float,
) -> list[str]:
    """Conservatively list physical resolved envelopes cut by a z plane."""
    labels: list[str] = []
    for role in _PHYSICAL_ROLES:
        for index, item in enumerate(resolved[role]):
            for bound in _item_bounds(item, f"{role}[{index}]"):
                xy_overlap = (
                    min(float(box[3]), bound[3]) > max(float(box[0]), bound[0])
                    and min(float(box[4]), bound[4]) > max(float(box[1]), bound[1])
                )
                if xy_overlap and bound[2] < z_mm < bound[5]:
                    labels.append(f"{role}[{index}]")
                    break
    return sorted(set(labels))


def _plane_material_witness(
    resolved: dict[str, Any], box: list[float], z_mm: float,
) -> dict[str, Any] | None:
    """Find a resolved-material witness on a proposed z face.

    Coordinates are midpoints of the exact x/y partition induced by resolved
    primitive and aperture boundaries.  Material occupancy itself is evaluated
    after the known slot and prism-clearance subtractions.
    """
    x_values = {float(box[0]), float(box[3])}
    y_values = {float(box[1]), float(box[4])}
    for role in _PHYSICAL_ROLES:
        for index, item in enumerate(resolved[role]):
            for bound in _item_bounds(item, f"{role}[{index}]"):
                x_values.update((max(float(box[0]), bound[0]), min(float(box[3]), bound[3])))
                y_values.update((max(float(box[1]), bound[1]), min(float(box[4]), bound[4])))
            polygons = [item.get("polygon_yz_mm"), item.get("terminal_polygon_yz_mm")]
            polygons.extend(part.get("polygon_yz_mm") for part in item.get("parts", []))
            polygons.extend(part.get("polygon_yz_mm") for part in item.get("body_sections", []))
            for polygon in polygons:
                if isinstance(polygon, list):
                    y_values.update(float(point[0]) for point in polygon)
    for slot_name in ("mirror_slot", "mirror_inner_shield_slot", "stripe_slot"):
        slot = resolved[slot_name]
        x_values.update((float(slot[0]), float(slot[3])))
        y_values.update((float(slot[1]), float(slot[4])))
    for slot in resolved["central_ground_slots"]:
        x_values.update((float(slot[0]), float(slot[3])))
        y_values.update((float(slot[1]), float(slot[4])))

    def probes(values: set[float], low: float, high: float) -> list[float]:
        ordered = sorted(value for value in values if low <= value <= high)
        return [(ordered[index] + ordered[index + 1]) / 2.0 for index in range(len(ordered) - 1)]

    for x_mm in probes(x_values, float(box[0]), float(box[3])):
        for y_mm in probes(y_values, float(box[1]), float(box[4])):
            labels = _point_material_labels(resolved, (x_mm, y_mm, z_mm))
            if labels:
                return {"x_mm": x_mm, "y_mm": y_mm, "material": labels}
    return None


def _boundary_audit(resolved: dict[str, Any], name: str, box: list[float], side: str) -> dict[str, Any]:
    z_mm = float(box[2] if side == "z_min" else box[5])
    crossings = _plane_envelope_crossings(resolved, box, z_mm)
    witness = _plane_material_witness(resolved, box, z_mm)
    axis_material = _point_material_labels(resolved, (0.0, 0.0, z_mm))
    axis_apertures = _point_aperture_labels(resolved, (0.0, 0.0, z_mm))
    return {
        "boundary": f"{name}.{side}",
        "z_mm": z_mm,
        "cuts_physical_electrode": witness is not None,
        "physical_electrode_witness": witness,
        "cuts_physical_electrode_envelope": bool(crossings),
        "physical_electrode_envelopes": crossings,
        "nominal_beam_axis_is_vacuum": not axis_material,
        "nominal_beam_axis_material": axis_material,
        "nominal_beam_axis_apertures": axis_apertures,
    }


def _region_metrics(
    name: str, box: list[float], mesh: tuple[float, float, float], arrays: int,
    bytes_per_point: int,
) -> dict[str, Any]:
    shape = _shape(tuple(float(value) for value in box), mesh)
    points = math.prod(shape)
    return {
        "region": name,
        "box_project_mm": box,
        "grid_shape": shape,
        "grid_points_per_array": points,
        "estimated_pa0_bytes": points * bytes_per_point,
        "estimated_family_bytes": points * arrays * bytes_per_point,
    }


def _scheme_metrics(
    scheme_id: str, boxes: dict[str, list[float]], mesh: tuple[float, float, float],
    arrays: int, bytes_per_point: int, baseline_points: int, resolved: dict[str, Any],
    internal_boundaries: list[tuple[str, str]], interface_count: int,
    new_z_boundary_locations_vs_current_mm: list[float], implementation: str,
) -> dict[str, Any]:
    regions = [
        _region_metrics(name, box, mesh, arrays, bytes_per_point)
        for name, box in boxes.items()
    ]
    points = sum(item["grid_points_per_array"] for item in regions)
    return {
        "scheme_id": scheme_id,
        "status": "planning_only__requires_new_pa_families_and_interface_validation",
        "region_count": len(regions),
        "local_interface_count": interface_count,
        "regions": regions,
        "total_grid_points_per_array": points,
        "estimated_pa0_bytes_total": points * bytes_per_point,
        "estimated_family_bytes_total": points * arrays * bytes_per_point,
        "grid_point_savings_fraction_vs_current": 1.0 - points / baseline_points,
        "new_z_boundary_locations_vs_current_mm": new_z_boundary_locations_vs_current_mm,
        "introduces_new_z_boundary_cut_risk": bool(new_z_boundary_locations_vs_current_mm),
        "boundary_audit": [
            _boundary_audit(resolved, name, boxes[name], side)
            for name, side in internal_boundaries
        ],
        "implementation_impact": implementation,
    }


def derive_local_z_compression_plan(contract_path: Path, scale_factor: float) -> dict[str, Any]:
    """Derive five-region tightening and three-region merge candidates."""
    if not math.isfinite(scale_factor) or scale_factor <= 0.0:
        raise CandidateContractError("local z-compression scale factor must be positive and finite")
    contract = load_contract(contract_path)
    current = derive_local_refinement_plan(contract_path)
    selected = next(
        (profile for profile in current["profiles"] if float(profile["scale_factor"]) == scale_factor),
        None,
    )
    if selected is None:
        raise CandidateContractError("local z-compression scale must be declared by the frozen contract")
    resolved = resolve_geometry(contract)
    mesh = tuple(float(value) for value in selected["central_transport"]["mesh_mm_per_gu"])
    origin = tuple(float(value) for value in current["baseline"]["box_project_mm"][:3])
    margin_z = float(contract["simion"]["analyzer_spatial_convergence"]["patch_margin_mm"][2])
    guard_z = _aligned_ceil(origin[2] + margin_z, origin[2], mesh[2]) - origin[2]
    if guard_z < mesh[2]:
        guard_z = mesh[2]
    handoff = {name: float(value) for name, value in current["handoff_planes_project_mm"].items()}
    h_nm = handoff["negative_bridge_to_mirror"]
    h_nc = handoff["negative_central_to_bridge"]
    h_pc = handoff["positive_central_to_bridge"]
    h_pm = handoff["positive_bridge_to_mirror"]
    if not h_nm < h_nc < h_pc < h_pm:
        raise CandidateContractError("local handoff responsibility planes are not strictly ordered")
    source = {name: [float(value) for value in box] for name, box in current["patches"].items()}

    def lower(value: float) -> float:
        return _aligned_floor(value - guard_z, origin[2], mesh[2])

    def upper(value: float) -> float:
        return _aligned_ceil(value + guard_z, origin[2], mesh[2])

    def replace_z(box: list[float], z_min: float, z_max: float) -> list[float]:
        if z_min < box[2] - 1e-9 or z_max > box[5] + 1e-9 or z_min >= z_max:
            raise CandidateContractError("compressed patch exceeds its existing source envelope")
        return [box[0], box[1], z_min, box[3], box[4], z_max]

    five = {
        "mirror_turn_negative": replace_z(source["mirror_turn_negative"], source["mirror_turn_negative"][2], upper(h_nm)),
        "stripe_mirror_bridge_negative": replace_z(source["stripe_mirror_bridge_negative"], lower(h_nm), upper(h_nc)),
        "central_transport": replace_z(source["central_transport"], lower(h_nc), upper(h_pc)),
        "stripe_mirror_bridge_positive": replace_z(source["stripe_mirror_bridge_positive"], lower(h_pc), upper(h_pm)),
        "mirror_turn_positive": replace_z(source["mirror_turn_positive"], lower(h_pm), source["mirror_turn_positive"][5]),
    }
    negative_union = _union_box([source["mirror_turn_negative"], source["stripe_mirror_bridge_negative"]])
    positive_union = _union_box([source["stripe_mirror_bridge_positive"], source["mirror_turn_positive"]])
    three = {
        "negative_mirror_bridge_merged": replace_z(negative_union, negative_union[2], upper(h_nc)),
        "central_transport": five["central_transport"],
        "positive_mirror_bridge_merged": replace_z(positive_union, lower(h_pc), positive_union[5]),
    }
    wide_three = {
        "negative_mirror_bridge_merged": negative_union,
        "central_transport": source["central_transport"],
        "positive_mirror_bridge_merged": positive_union,
    }
    arrays = int(selected["central_transport"]["pa_array_count"])
    bytes_per_point = int(contract["simion"]["analyzer_spatial_convergence"]["storage_bytes_per_grid_point_estimate"])
    current_regions = {
        "mirror_turn_negative": selected["mirror_turn_negative"],
        "stripe_mirror_bridge_negative": selected["stripe_mirror_bridge_negative"],
        "central_transport": selected["central_transport"],
        "stripe_mirror_bridge_positive": selected["stripe_mirror_bridge"],
        "mirror_turn_positive": selected["mirror_turn"],
    }
    current_points = sum(int(item["grid_points_per_array"]) for item in current_regions.values())
    current_pa0 = current_points * bytes_per_point
    current_family = current_pa0 * arrays

    interface_pairs = {
        "negative_bridge_to_mirror": ("mirror_turn_negative", "stripe_mirror_bridge_negative"),
        "negative_central_to_bridge": ("stripe_mirror_bridge_negative", "central_transport"),
        "positive_central_to_bridge": ("central_transport", "stripe_mirror_bridge_positive"),
        "positive_bridge_to_mirror": ("stripe_mirror_bridge_positive", "mirror_turn_positive"),
    }
    interface_audit = []
    for name, z_mm in handoff.items():
        first, second = interface_pairs[name]
        overlap = max(source[first][2], source[second][2]) < z_mm < min(source[first][5], source[second][5])
        material = _point_material_labels(resolved, (0.0, 0.0, z_mm))
        aperture = _point_aperture_labels(resolved, (0.0, 0.0, z_mm))
        plane_box = _union_box([source[first], source[second]])
        witness = _plane_material_witness(resolved, plane_box, z_mm)
        interface_audit.append({
            "handoff": name,
            "z_mm": z_mm,
            "inside_current_adjacent_patch_overlap": overlap,
            "nominal_beam_axis_is_vacuum": not material,
            "nominal_beam_axis_material": material,
            "nominal_beam_axis_apertures": aperture,
            "full_xy_plane_is_vacuum": witness is None,
            "full_xy_plane_material_witness": witness,
            "full_xy_plane_crosses_physical_envelopes": bool(
                _plane_envelope_crossings(resolved, plane_box, z_mm)
            ),
        })
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_z_compression_candidate_plan",
        "status": "planning_only__accepted_pa_iob_unchanged",
        "scale_factor": scale_factor,
        "mesh_mm_per_gu": list(mesh),
        "derivation_authorities": {
            "resolved_geometry_status": resolved["status"],
            "source_patch_role": current["role"],
            "source_patch_qualification": current["qualification"],
            "source_workbench_rule": current["workbench_rule"],
            "handoff_planes_project_mm": handoff,
            "instance_adjust_semantics": "higher-priority local instance owns a half-open z responsibility interval; ion_instance=0 suppresses only that instance and resumes selection below it",
            "dirichlet_guard_source": "simion.analyzer_spatial_convergence.patch_margin_mm.z snapped outward to the selected local mesh",
            "dirichlet_guard_z_mm": guard_z,
        },
        "instance_adjust_responsibility_intervals": {
            "current_and_scheme_A_half_open_z_mm": {
                "mirror_turn_negative": [None, h_nm],
                "stripe_mirror_bridge_negative": [h_nm, h_nc],
                "central_transport": [h_nc, h_pc],
                "stripe_mirror_bridge_positive": [h_pc, h_pm],
                "mirror_turn_positive": [h_pm, None],
            },
            "schemes_B_and_C_half_open_z_mm": {
                "negative_mirror_bridge_merged": [None, h_nc],
                "central_transport": [h_nc, h_pc],
                "positive_mirror_bridge_merged": [h_pc, None],
            },
        },
        "current_five_region_reference": {
            "region_count": 5,
            "local_interface_count": 4,
            "total_grid_points_per_array": current_points,
            "estimated_pa0_bytes_total": current_pa0,
            "estimated_family_bytes_total": current_family,
            "regions": current_regions,
        },
        "handoff_vacuum_audit": interface_audit,
        "schemes": [
            _scheme_metrics(
                "A_tightened_five_region", five, mesh, arrays, bytes_per_point, current_points,
                resolved,
                [
                    ("mirror_turn_negative", "z_max"),
                    ("stripe_mirror_bridge_negative", "z_min"),
                    ("stripe_mirror_bridge_negative", "z_max"),
                    ("central_transport", "z_min"),
                    ("central_transport", "z_max"),
                    ("stripe_mirror_bridge_positive", "z_min"),
                    ("stripe_mirror_bridge_positive", "z_max"),
                    ("mirror_turn_positive", "z_min"),
                ],
                4,
                _new_z_faces(five, source),
                "same five local instance roles and half-open responsibilities; every changed box requires a new PA family and fresh interface/trajectory validation",
            ),
            _scheme_metrics(
                "B_merged_three_region", three, mesh, arrays, bytes_per_point, current_points,
                resolved,
                [
                    ("negative_mirror_bridge_merged", "z_max"),
                    ("central_transport", "z_min"),
                    ("central_transport", "z_max"),
                    ("positive_mirror_bridge_merged", "z_min"),
                ],
                2,
                _new_z_faces(three, source),
                "requires a new three-local-instance IOB seed, runner contract and Lua instance-count validation; it cannot be loaded by the accepted five-instance program unchanged",
            ),
            _scheme_metrics(
                "C_wide_merged_three_region", wide_three, mesh, arrays, bytes_per_point,
                current_points, resolved,
                [
                    ("negative_mirror_bridge_merged", "z_max"),
                    ("central_transport", "z_min"),
                    ("central_transport", "z_max"),
                    ("positive_mirror_bridge_merged", "z_min"),
                ],
                2,
                [],
                "requires the same three-local-instance IOB/program contract as scheme B, but every z face is inherited from an accepted source patch; only duplicate mirror-bridge overlap is removed",
            ),
        ],
        "acceptance_boundary": {
            "electrode_cut_meaning": "cuts_physical_electrode is backed by a material witness after resolved aperture subtraction; envelope lists remain a conservative ownership diagnostic.",
            "vacuum_meaning": "Vacuum is proved only at the nominal x=0,y=0 handoff sample from resolved solids and apertures; accepted-bunch portal containment and field continuity remain unproved.",
            "build_authorized": False,
            "required_before_build": [
                "freeze an accepted-bunch portal envelope",
                "prove no accepted ion reaches any non-responsibility x/y/z face",
                "compare potential and normal field on every retained handoff portal",
                "re-solve the centre voltage root independently for the candidate mesh",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--scale-factor", required=True, type=float)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    document = derive_local_z_compression_plan(arguments.contract, arguments.scale_factor)
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if arguments.output is None:
        print(text, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
