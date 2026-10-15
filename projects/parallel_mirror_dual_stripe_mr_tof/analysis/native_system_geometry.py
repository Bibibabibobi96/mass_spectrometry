"""Emit MR-owned static geometry projections for the native system runtime.

The pulsed runtime retains separate analyser/accelerator instances. The static
C0 projection instead consumes their frozen assembly and voltage authority;
it does not derive a second accelerator geometry or a trajectory qualification.
"""

from __future__ import annotations

import argparse
import copy
import math
import re
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import (
    _box,
    _central_ground_lines,
    _extrude_polygon_bands,
    _mirror_ground_shield_lines,
    _mirror_lines,
    _number,
    _prism_ground_shield_lines,
    _stripe_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
    load_contract,
)


def build_static_c0_gem(
    resolved_geometry: dict,
    voltage_authority: dict,
    numerical_grid: dict,
    *,
    boundary_mode: str,
) -> tuple[str, dict]:
    """Emit ordinary static GEM from frozen millimetre bodies and voltages.

    Grounded enclosure writes five zero-volt faces, never the x mirror plane.
    The local x-mirror/five-face mode writes no exterior electrodes: the public
    local builder supplies parent-field Dirichlet values on those five faces.
    Ideal OA sheets affect this electrostatic field; collision stays separate.
    Official GEM reference: https://simion.com/info/gem_geometry_file.html
    """
    geometry, authority, plan = resolved_geometry, voltage_authority, numerical_grid
    bounds, pitch = plan["box_mm"], plan["pitch_mm"]
    boundary = authority["boundary_contract"]
    if boundary_mode not in ("grounded_enclosure", "x_mirror_five_faces"):
        raise ValueError("Unsupported C0 boundary mode.")
    if (
        len(bounds) != 6
        or len(pitch) != 3
        or not all(math.isfinite(v) for v in (*bounds, *pitch))
        or any(v <= 0 for v in pitch)
        or any(bounds[i + 3] <= bounds[i] for i in range(3))
    ):
        raise ValueError("Finite positive C0 numerical grid required.")
    dimensions = [round((bounds[i + 3] - bounds[i]) / pitch[i]) + 1 for i in range(3)]
    if (
        dimensions != plan["dimensions"]
        or any((dimensions[i] - 1) * pitch[i] != bounds[i + 3] - bounds[i] for i in range(3))
        or plan["mirror_axes"] != ["x"]
        or plan["surface"] != "fractional"
    ):
        raise ValueError("C0 grid dimensions, x mirror or fractional surface differs.")
    if boundary["mode"] != "grounded_enclosure" or boundary["voltage_v"] != 0 or bounds[0] != 0:
        raise ValueError("C0 five-face voltage or x symmetry differs.")
    parent_bounds = boundary["box_mm"]
    if boundary_mode == "grounded_enclosure" and bounds != parent_bounds:
        raise ValueError("Grounded C0 domain differs from frozen boundary.")
    if any(bounds[i] < parent_bounds[i] or bounds[i + 3] > parent_bounds[i + 3] for i in range(3)):
        raise ValueError("Local C0 domain extends outside its parent boundary.")
    voltages = authority["analyzer_electrode_voltages_v"]
    if len(voltages) != 20 or not all(math.isfinite(v) for v in voltages):
        raise ValueError("Complete finite analyzer 20-slot voltage authority required.")
    components = {
        (v["component_namespace"], v["component_electrode_id"]): v["voltage_v"]
        for v in authority["component_voltages_v"]
    }
    if len(components) != len(authority["component_voltages_v"]):
        raise ValueError("Duplicate component voltage identity.")
    if not all(math.isfinite(v) for v in components.values()):
        raise ValueError("Complete finite component voltage authority required.")
    lines = [
        "; Frozen C0 ordinary static geometry; no field or trajectory qualification.",
        "pa_define("
        + ",".join(map(str, dimensions))
        + ",planar,x,electrostatic,, "
        + ",".join(_number(v) for v in pitch)
        + ",surface=fractional)",
        "locate(" + ",".join(_number(-v) for v in bounds[:3]) + ") {",
    ]
    analyzer = _analyzer_geometry_lines(geometry)
    ids = [int(v) for v in re.findall(r"\be\((\d+)\)", "\n".join(analyzer))]
    if any(not 1 <= v <= 20 for v in ids):
        raise ValueError("Analyzer geometry ID outside its own 20-slot namespace.")
    for line in analyzer:
        lines.append(re.sub(r"\be\((\d+)\)", lambda m: "e(" + format(voltages[int(m[1]) - 1], ".17g") + ")", line))
    assembly = authority["assembly"]
    oa = assembly["accelerator_resolved_electrodes"]
    # Frozen coordinates are centred component coordinates. Map through provider PA then MR IOB.
    offset = [a + b for a, b in zip(oa["local_to_pa_translation_mm"], assembly["accelerator_iob_origin_mm"])]
    if offset[0] != 0 or oa["acceleration_direction"] != "-z":
        raise ValueError("OA x mirror/axis mapping differs.")
    records = []

    def component_box(box: dict) -> list[float]:
        return [float(box[f"{axis}_{side}_mm"]) + offset[i] for side in ("min", "max") for i, axis in enumerate("xyz")]

    def emit(name: str, item: dict, outer_key: str, holes: tuple[str, ...] = ()) -> None:
        key = ("accelerator", item["component_electrode_id"])
        voltage = components[key]
        if not math.isfinite(voltage):
            raise ValueError("Nonfinite component voltage.")
        body = component_box(item[outer_key])
        lines.extend(
            [
                "  ; " + name + " namespace=accelerator id=" + str(key[1]),
                "  e(" + format(voltage, ".17g") + ") { " + _box(body),
            ]
        )
        for hole in holes:
            cut = component_box(item[hole])
            if hole == "aperture_box_mm":
                # Existing OA emitter extends cuts through both frame ends; never enlarge x/y.
                padding = body[5] - body[2]
                cut[2] -= padding
                cut[5] += padding
                operator = "notin_inside"
            else:
                # Existing grounded enclosure emitter uses notin, not an added closed exit cap.
                operator = "notin"
                if hole == "exit_opening_box_mm":
                    padding = cut[5] - cut[2]
                    cut[2] -= padding
                    cut[5] += padding
            lines.append("    " + operator + " { " + _box(cut) + " }")
        lines.append("  }")
        records.append({"name": name, "component_electrode_id": key[1], "voltage_v": voltage, "box_mm": body})

    emit("oa_enclosure", oa["grounded_enclosure"], "outer_box_mm", ("cavity_box_mm", "exit_opening_box_mm"))
    emit("oa_repeller", oa["repeller"], "solid_box_mm")
    for i, item in enumerate(oa["grid_supports"], 1):
        if item["transmission"] != "ideal_transparent":
            raise ValueError("C0 requires frozen ideal-transparent sheet semantics.")
        emit("oa_grid_frame_" + str(i), item, "frame_outer_box_mm", ("aperture_box_mm",))
        sheet = item["ideal_sheet_mm"]
        z = float(sheet["z_mm"]) + offset[2]
        body = [
            float(sheet["x_min_mm"]) + offset[0],
            float(sheet["y_min_mm"]) + offset[1],
            z,
            float(sheet["x_max_mm"]) + offset[0],
            float(sheet["y_max_mm"]) + offset[1],
            z,
        ]
        voltage = components[("accelerator", item["component_electrode_id"])]
        lines.extend(
            [
                "  ; Frozen ideal transparent grid_sheet: electrostatic sheet, collision is separate.",
                "  e(" + format(voltage, ".17g") + ") { " + _box(body) + " }",
            ]
        )
        records.append(
            {
                "name": "oa_grid_sheet_" + str(i),
                "component_electrode_id": item["component_electrode_id"],
                "voltage_v": voltage,
                "box_mm": body,
                "transmission": item["transmission"],
            }
        )
    for i, item in enumerate(oa["rings"], 1):
        emit("oa_ring_" + str(i), item, "outer_box_mm", ("aperture_box_mm",))
    detector = assembly["detector"]
    if detector != geometry["detector"]:
        raise ValueError("Frozen detector assembly and geometry differ.")
    voltage = components[("detector", detector["id"])]
    lines.extend(
        [
            "  ; namespace=detector id=" + str(detector["id"]),
            "  e(" + format(voltage, ".17g") + ") { " + _box(detector["box"]) + " }",
        ]
    )
    # Five zero-thickness faces on PA exterior. There is deliberately no x=0 Dirichlet face.
    faces = []
    face_sides = ((0, 1), (1, 0), (1, 1), (2, 0), (2, 1))
    for axis, side in face_sides if boundary_mode == "grounded_enclosure" else ():
        face = list(bounds)
        value = bounds[axis + 3 * side]
        face[axis] = face[axis + 3] = value
        faces.append({"axis": "xyz"[axis], "side": "max" if side else "min", "box_mm": face, "voltage_v": 0})
        lines.append("  e(0) { " + _box(face) + " }")
    lines.extend(["}", ""])
    nodes = math.prod(dimensions)
    report = {
        "status": "PASS",
        "boundary_mode": boundary_mode,
        "dimensions": dimensions,
        "nodes": nodes,
        "pa_double_payload_bytes": nodes * 8,
        "fractional_surface_bytes": "unknown until native build",
        "analyzer_emission_counts": {str(v): ids.count(v) for v in sorted(set(ids))},
        "analyzer_electrode_voltages_v": voltages,
        "component_voltages_v": authority["component_voltages_v"],
        "oa_project_offset_mm": offset,
        "oa_bodies": records,
        "detector": detector,
        "outer_ground_faces": faces,
        "x0_dirichlet_wall": False,
        "surface": "fractional",
        "mirror": "x",
        "ordinary_static_pa": True,
        "geom_compare_scope": "frozen physical expression only; no mesh/field/trajectory qualification",
    }
    return "\n".join(lines), report


def _require_release(contract: dict[str, object]) -> None:
    if contract.get("simion_geometry_release_status") != "cad_topology_and_top_level_pose_qualified":
        raise CandidateContractError("native system geometry requires the qualified CAD topology/pose release")


def _span(contract: dict[str, object], key: str) -> tuple[float, float, float]:
    simion = contract["simion"]
    values = simion[key]
    if not isinstance(values, list) or len(values) != 3:
        raise CandidateContractError(f"simion.{key} must contain three spans")
    span = tuple(float(value) for value in values)
    if min(span) <= 0:
        raise CandidateContractError(f"simion.{key} must be positive")
    return span


def _analyzer_origin(contract: dict[str, object], span: tuple[float, float, float]) -> tuple[float, float, float]:
    """Return the CAD-envelope-derived analyzer PA origin in project mm."""
    values = contract["simion"].get("analyzer_pa_origin_mm")
    if not isinstance(values, list) or len(values) != 3:
        raise CandidateContractError("simion.analyzer_pa_origin_mm must contain three coordinates")
    origin = tuple(float(value) for value in values)
    expected = (-span[0] / 2.0, -162.0, -span[2] / 2.0)
    if origin != expected:
        raise CandidateContractError("analyzer PA origin must retain the v2 CAD-envelope y=[-162,478] mm review extent")
    return origin


def build_analyzer_gem(contract_path: Path) -> str:
    """Build the non-accelerator PA with contract-owned component mesh defaults."""
    contract = load_contract(contract_path)
    _require_release(contract)
    mesh = contract["simion"]["component_mesh_mm_per_gu"]["analyzer"]
    resolved = resolve_geometry(contract)
    span_x, span_y, span_z = _span(contract, "analyzer_pa_span_mm")
    origin_x, origin_y, origin_z = _analyzer_origin(contract, (span_x, span_y, span_z))
    lines = [
        "; MR-TOF analyser PA only: mirrors, physical Stripes, central ground, prisms and shields.",
        "; Project frame: x transverse, y drift, z fast reflection; origin is the central injection reference.",
        "; Accelerator intentionally absent: its grounded enclosure permits a separate local PA refine.",
        f"# local contract_mmgu_x, contract_mmgu_y, contract_mmgu_z = {_number(mesh[0])}, {_number(mesh[1])}, {_number(mesh[2])}",
        "# local mmgu_x = _G.var and _G.var.mmgu_x or contract_mmgu_x",
        "# local mmgu_y = _G.var and _G.var.mmgu_y or contract_mmgu_y",
        "# local mmgu_z = _G.var and _G.var.mmgu_z or contract_mmgu_z",
        "# assert(mmgu_x == contract_mmgu_x and mmgu_y == contract_mmgu_y and mmgu_z == contract_mmgu_z, 'runtime mesh must equal frozen Candidate contract')",
        f"# local x_span, y_span, z_span = {_number(span_x)}, {_number(span_y)}, {_number(span_z)}",
        "# local nx = math.floor(x_span/mmgu_x + 0.5) + 1",
        "# local ny = math.floor(y_span/mmgu_y + 0.5) + 1",
        "# local nz = math.floor(z_span/mmgu_z + 0.5) + 1",
        "pa_define($(nx),$(ny),$(nz),planar,none,electrostatic,, $(mmgu_x),$(mmgu_y),$(mmgu_z),surface=none)",
        f"locate({_number(-origin_x)},{_number(-origin_y)},{_number(-origin_z)}) {{",
    ]
    lines.extend(_analyzer_geometry_lines(resolved))
    lines.extend(("}", ""))
    return "\n".join(lines)


def _analyzer_geometry_lines(resolved: dict[str, object]) -> list[str]:
    """Return the geometry emitter shared by the global fallback and native corridor."""
    lines: list[str] = []
    lines.extend(_mirror_lines(resolved))
    lines.extend(_mirror_ground_shield_lines(resolved))
    lines.extend(_stripe_lines(resolved))
    lines.extend(_central_ground_lines(resolved))
    lines.append("  ; CAD-constrained triangular prism electrodes, emitted after ground bodies.")
    for prism in resolved["prism_electrodes"]:
        terms = " ".join(
            term for part in prism["parts"] for term in _extrude_polygon_bands(part["x"], part["polygon_yz_mm"])
        )
        lines.append(f"  e({prism['id']}) {{ {terms} }}")
    lines.extend(_prism_ground_shield_lines(resolved))
    return lines


def _detector_origin(
    contract: dict[str, object],
    span: tuple[float, float, float],
    *,
    topology_contract: dict[str, object] | None = None,
) -> tuple[float, float, float]:
    """Return the independent detector PA origin derived only from its resolved box."""
    geometry_contract = contract
    if topology_contract is not None:
        geometry_contract = copy.deepcopy(contract)
        reviewed_accelerator = geometry_contract.get("accelerator")
        active_accelerator = topology_contract.get("accelerator")
        if not isinstance(reviewed_accelerator, dict) or not isinstance(active_accelerator, dict):
            raise CandidateContractError("detector pose lacks its accelerator geometry projection")
        for key in ("component_source_cylinder", "focus_y_anchor"):
            value = active_accelerator.get(key)
            if not isinstance(value, dict):
                raise CandidateContractError(f"detector pose accelerator projection lacks {key}")
            reviewed_accelerator[key] = copy.deepcopy(value)
    detector = resolve_geometry(
        geometry_contract,
        inherited_dual_stripe_topology_contract=topology_contract,
    )["detector"]
    box = detector["box"]
    center = tuple((float(box[index]) + float(box[index + 3])) / 2.0 for index in range(3))
    return tuple(center[index] - span[index] / 2.0 for index in range(3))


def build_detector_gem(contract_path: Path) -> str:
    """Build a detector-only PA so it cannot be confused with a prism shield."""
    contract = load_contract(contract_path)
    _require_release(contract)
    resolved = resolve_geometry(contract)
    detector = resolved["detector"]
    if detector.get("separate_pa") is not True:
        raise CandidateContractError("detector must be emitted as a separate PA")
    span_x, span_y, span_z = _span(contract, "detector_pa_span_mm")
    origin_x, origin_y, origin_z = _detector_origin(contract, (span_x, span_y, span_z))
    box = detector["box"]
    local_box = [
        float(box[0]) - origin_x, float(box[1]) - origin_y, float(box[2]) - origin_z,
        float(box[3]) - origin_x, float(box[4]) - origin_y, float(box[5]) - origin_z,
    ]
    lines = [
        "; MR-TOF detector PA only; independent from analyser/prism PA geometry.",
        "; Project frame: x transverse, y drift, z fast reflection.",
        "# local mmgu_x = _G.var and _G.var.mmgu_x or 1.0",
        "# local mmgu_y = _G.var and _G.var.mmgu_y or 1.0",
        "# local mmgu_z = _G.var and _G.var.mmgu_z or 1.0",
        f"# local x_span, y_span, z_span = {_number(span_x)}, {_number(span_y)}, {_number(span_z)}",
        "# local nx = math.floor(x_span/mmgu_x + 0.5) + 1",
        "# local ny = math.floor(y_span/mmgu_y + 0.5) + 1",
        "# local nz = math.floor(z_span/mmgu_z + 0.5) + 1",
        "pa_define($(nx),$(ny),$(nz),planar,none,electrostatic,, $(mmgu_x),$(mmgu_y),$(mmgu_z),surface=none)",
        "locate(0,0,0) {",
        "  ; Detector is grounded only for this geometry-review PA; no analyser/prism solid is present.",
        f"  e({detector['id']}) {{ {_box(local_box)} }}",
        "}",
        "",
    ]
    return "\n".join(lines)



def resolve_static_iob_origins(
    contract_path: Path,
    *,
    inherited_detector_return_path: dict[str, object] | None = None,
    inherited_dual_stripe_topology_contract: dict[str, object] | None = None,
    inherited_mirror_power_supply_limits_v: dict[str, object] | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Resolve only the MR-owned analyzer and detector poses."""
    contract = load_contract(
        contract_path,
        inherited_detector_return_path=inherited_detector_return_path,
        inherited_mirror_power_supply_limits_v=inherited_mirror_power_supply_limits_v,
    )
    _require_release(contract)
    analyzer_span = _span(contract, "analyzer_pa_span_mm")
    return {
        "analyzer": _analyzer_origin(contract, analyzer_span),
        "detector": _detector_origin(
            contract, _span(contract, "detector_pa_span_mm"),
            topology_contract=inherited_dual_stripe_topology_contract,
        ),
    }


def resolve_accelerator_iob_origin(
    contract: dict[str, object],
    provider_plan: dict[str, object],
    *, resolved_geometry: dict[str, object] | None = None,
) -> tuple[float, float, float]:
    """Project one provider-local accelerator PA onto the MR injection line.

    The provider plan deliberately uses an exit-origin component frame whose
    transverse centre is ``y=0``.  That local coordinate is not an MR assembly
    pose.  The global y coordinate comes only from the independently
    configurable, clearance-gated MR assembly coordinate.
    """
    if (
        provider_plan.get("role") != "orthogonal_accelerator_component_focus_pa_plan"
        or provider_plan.get("status") != "derived"
    ):
        raise CandidateContractError("accelerator provider plan is not a derived component PA plan")
    domain = provider_plan.get("numerical_domain")
    requirements = provider_plan.get("requirements")
    layout = provider_plan.get("layout")
    if not isinstance(domain, dict) or not isinstance(requirements, dict) or not isinstance(layout, dict):
        raise CandidateContractError("accelerator provider plan lacks domain, requirements, or layout")
    span = domain.get("span_mm")
    stored_span = domain.get("stored_span_mm")
    mirror_axes = domain.get("mirror_axes")
    local_origin = domain.get("iob_origin_mm")
    placement = requirements.get("placement")
    if (
        not isinstance(span, list) or len(span) != 3
        or not isinstance(stored_span, list) or len(stored_span) != 3
        or not isinstance(local_origin, list) or len(local_origin) != 3
        or mirror_axes != ["x"]
        or not isinstance(placement, dict)
    ):
        raise CandidateContractError("accelerator provider pose fields are incomplete")
    spans = tuple(float(value) for value in span)
    stored_spans = tuple(float(value) for value in stored_span)
    provider_origin = tuple(float(value) for value in local_origin)
    expected_stored_spans = (spans[0] / 2.0, spans[1], spans[2])
    if (
        min(spans) <= 0.0
        or stored_spans != expected_stored_spans
        or provider_origin != (0.0, -spans[1] / 2.0, 0.0)
    ):
        raise CandidateContractError("accelerator provider local IOB origin rule differs")
    local_exit_z = float(domain.get("local_exit_z_mm"))
    global_exit_z = float(placement.get("global_exit_z_mm"))
    if not all(
        value == value and abs(value) < float("inf")
        for value in (*spans, *stored_spans, local_exit_z, global_exit_z)
    ):
        raise CandidateContractError("accelerator provider pose contains a non-finite value")

    # Static-field callers already own the solved, assembly-resolved geometry.
    # Reuse it for the same clearance checks instead of resolving without OA.
    resolved = resolve_geometry(contract) if resolved_geometry is None else resolved_geometry
    profile_id = layout.get("geometry_profile_id")
    if profile_id != resolved["metadata"]["accelerator_component_geometry_profile_id"]:
        raise CandidateContractError("accelerator provider geometry profile differs from the MR contract")
    focus_y = derive_two_zone_placement(contract).focus_y_mm
    physical_y_extent = float(layout.get("static_minimum_y_extent_mm"))
    if physical_y_extent <= 0.0:
        raise CandidateContractError("accelerator provider physical y extent must be positive")
    accelerator_y_max = focus_y + physical_y_extent / 2.0
    central_shields = [
        item for item in resolved["prism_ground_shields"]
        if item.get("station") == "central_ground_left"
    ]
    if len(central_shields) != 1:
        raise CandidateContractError("accelerator pose requires exactly one Prism2 grounded shield")
    shield_y_min = min(float(point[0]) for point in central_shields[0]["outer_polygon_yz_mm"])
    required_clearance = float(
        contract["accelerator"]["minimum_clearance_to_central_prism_ground_shield_y_mm"]
    )
    if shield_y_min - accelerator_y_max < required_clearance:
        raise CandidateContractError("accelerator pose overlaps or approaches the Prism2 shield too closely")
    stripe_y_min = min(
        float(point[0])
        for stripe in resolved["stripe_electrodes"]
        for point in stripe["polygon_yz_mm"]
    )
    if accelerator_y_max >= stripe_y_min:
        raise CandidateContractError("accelerator pose overlaps the Stripe assembly")

    return (
        provider_origin[0],
        focus_y + provider_origin[1],
        global_exit_z + provider_origin[2] - local_exit_z,
    )



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--component", required=True, choices=("analyzer", "detector"))
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.component == "analyzer":
        text = build_analyzer_gem(arguments.contract)
    else:
        text = build_detector_gem(arguments.contract)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
