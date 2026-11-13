"""SIMION GEM emitters and native PA geometry planning for the MR analyzer."""
from __future__ import annotations

import copy
import math
import struct
from pathlib import Path
from typing import Any, Iterable, Mapping

from msplatform.components.parallel_mirror_dual_stripe_mr_tof import candidate_contract
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.geometry_contract import CENTRAL_GROUND_ELECTRODE_ID
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.mirror_geometry_parameters import derive_mirror_boundaries

IP_PROVIDER = "dual_pressure_rectilinear_ion_processor"


def _number(value: float) -> str:
    return f"{value:.12g}"


def _box(values: Iterable[float]) -> str:
    return "box3D(" + ",".join(_number(value) for value in values) + ")"


def _polyline(points: list[list[float]]) -> str:
    # SIMION's legacy ``polyline`` fill is not implicitly closed for a
    # three-vertex region.  Closing every region is harmless for the Stripe
    # quadrilaterals and is essential for the triangular prism faces.
    closed = points if points and points[0] == points[-1] else [*points, points[0]]
    return "polyline(" + ",".join(_number(value) for point in closed for value in point) + ")"


def _polygon_bands(points: list[list[float]]) -> list[list[list[float]]]:
    """Split a sampled two-edge polygon into GEM-simple shared-edge strips.

    SIMION 2020 legacy GEM rejects a single expression with hundreds of
    polyline vertices.  Resolved Stripe/Ion-Foil shapes are ordered as one
    lower edge followed by the reversed upper edge, so adjacent quadrilaterals
    are an exactly equivalent union at the frozen sampling nodes.
    """
    if len(points) < 4 or len(points) % 2:
        return [points]
    half = len(points) // 2
    lower, upper = points[:half], list(reversed(points[half:]))
    if any(lower[index][0] >= lower[index + 1][0] or upper[index][0] >= upper[index + 1][0] for index in range(half - 1)):
        return [points]
    return [[lower[index], lower[index + 1], upper[index + 1], upper[index]] for index in range(half - 1)]


def _extrude_polygon_bands(x: list[float], polygon: list[list[float]]) -> list[str]:
    """Return one native ``extrude_yz`` term per simple polygon band."""
    return [
        f"extrude_yz({_number(x[0])},{_number(x[1])}) {{ {_polyline(band)} }}"
        for band in _polygon_bands(polygon)
    ]


def _mirror_lines(resolved: dict[str, object], id_map: Mapping[int, int] | None = None) -> list[str]:
    lines = [
        "  ; Each active mirror electrode has its own CAD 580 x 30-mm bounded aperture.",
        "  ; The aperture terminates before both y ends and does not pass through end plates in z.",
    ]
    for electrode in resolved["mirror_electrodes"]:
        native_id = electrode["id"] if id_map is None else id_map[electrode["id"]]
        if "polygon_yz_mm" in electrode:
            lines.extend(_mirror_polygon_lines(electrode, native_id))
            continue
        lines.extend((
            f"  e({native_id}) {{",
            f"    {_box(electrode['box'])}",
            f"    notin_inside {{ {_box(electrode['beam_slot'])} }}",
            "  }",
        ))
    return lines


def _mirror_polygon_lines(solid: dict, electrode_id: int) -> list[str]:
    """Emit the tilted solid and independently x-bounded holes via official GEM primitives.

    Uses the existing extrude_yz/polyline path, supported by SIMION 2020
    examples/geometry/disc_segmented.gem; no AABB is emitted as a tilted solid.
    """
    lines = [f"  e({electrode_id}) {{",
             *(f"    {term}" for term in _extrude_polygon_bands(solid["x"], solid["polygon_yz_mm"]))]
    for hole in solid["holes"]:
        lines.extend(f"    notin_inside {{ {term} }}" for term in
                     _extrude_polygon_bands(hole["x"], hole["polygon_yz_mm"]))
    return [*lines, "  }"]


def _mirror_ground_shield_lines(resolved: dict[str, object], id_map: Mapping[int, int] | None = None, shield_ids: tuple[int, int] | None = None) -> list[str]:
    """Emit the CAD-derived inner grounded mirror end plates as shared 0-V ID 15."""
    if resolved.get("mirror_convergence_transform") is not None:
        lines = []
        for index, shield in enumerate(resolved["mirror_ground_shields"]):
            lines.extend(_mirror_polygon_lines(shield, CENTRAL_GROUND_ELECTRODE_ID if shield_ids is None else shield_ids[index]))
        for closure in resolved["mirror_e_closures"]:
            lines.extend(_mirror_polygon_lines(closure, closure["id"] if id_map is None else id_map[closure["id"]]))
        return lines
    inner_slot = _box(resolved["mirror_inner_shield_slot"])
    if shield_ids is not None:
        lines = []
        for shield, native_id in zip(resolved["mirror_ground_shields"], shield_ids, strict=True):
            lines.extend((f"  e({native_id}) {{", f"    {_box(shield['box'])}"))
            if shield["role"] == "inner_stripe_facing_4mm_slot":
                lines.append(f"    notin_inside {{ {inner_slot} }}")
            lines.append("  }")
        for closure in resolved["mirror_e_closures"]:
            lines.extend((f"  e({id_map[closure['id']]}) {{", f"    {_box(closure['box'])}", "  }"))
        return lines
    lines = [
        "  ; CAD inner end plates: Stripe-facing 5-mm shields have 4-mm slots.",
        f"  e({CENTRAL_GROUND_ELECTRODE_ID}) {{",
    ]
    for shield in resolved["mirror_ground_shields"]:
        lines.append(f"    {_box(shield['box'])}")
        if shield["role"] == "inner_stripe_facing_4mm_slot":
            lines.append(f"    notin_inside {{ {inner_slot} }}")
    lines.append("  }")
    for closure in resolved["mirror_e_closures"]:
        lines.extend((f"  e({closure['id']}) {{", f"    {_box(closure['box'])}", "  }"))
    return lines


def _stripe_lines(resolved: dict[str, object], id_map: Mapping[int, int] | None = None) -> list[str]:
    slot = _box(resolved["stripe_slot"])
    lines = ["  ; Four physical curved Stripe conductors; pairs (11,12) and (13,14) share biases."]
    for electrode in resolved["stripe_electrodes"]:
        native_id = electrode["id"] if id_map is None else id_map[electrode["id"]]
        lower, upper = electrode["x"]
        lines.extend((
            f"  e({native_id}) {{",
            *(f"    {term}" for term in _extrude_polygon_bands([lower, upper], electrode["polygon_yz_mm"])),
            *(f"    {term}" for term in _extrude_polygon_bands([lower, upper], electrode["terminal_polygon_yz_mm"])),
            # SIMION's official ``notin_inside`` preserves CAD-face nodes.
            # Thus a 4-mm channel retains metal at x=±2 mm, not ±3 mm.
            f"    notin_inside {{ {slot} }}",
            "  }",
        ))
    return lines


def _central_ground_lines(resolved: dict[str, object], id_map: Mapping[int, int] | None = None) -> list[str]:
    """Emit one whole native Foil-2 body minus its two rectangular windows."""
    native_id = CENTRAL_GROUND_ELECTRODE_ID if id_map is None else id_map[CENTRAL_GROUND_ELECTRODE_ID]
    lines = ["  ; Whole Ion-Foil-2 with native short cubic and planar end features; no added bridges.",
             f"  e({native_id}) {{"]
    for body in resolved["central_ground_electrodes"]:
        lines.extend(f"    {term}" for term in _extrude_polygon_bands(body["x"], body["polygon_yz_mm"]))
    lines.extend(f"    notin_inside {{ {_box(slot)} }}" for slot in resolved["central_ground_slots"])
    lines.append("  }")
    return lines


def _prism_ground_shield_lines(resolved: dict[str, object], id_map: Mapping[int, int] | None = None) -> list[str]:
    """Emit finite-y grounded frames with CAD-audited apertures."""
    lines = [
        "  ; Grounded prism frames retain their CAD finite-y bodies and nested triangular apertures.",
    ]
    for shield in resolved["prism_ground_shields"]:
        outer = [term for section in shield["body_sections"]
                 for term in _extrude_polygon_bands(section["x"], section["polygon_yz_mm"])]
        aperture = _extrude_polygon_bands(shield["x"], shield["prism_clearance_polygon_yz_mm"])
        native_id = shield["id"] if id_map is None else id_map[shield["id"]]
        lines.append(f"  e({native_id}) {{")
        lines.extend(f"    {term}" for term in outer)
        lines.append("    notin_inside_or_on {")
        lines.extend(f"      {term}" for term in aperture)
        lines.append("    }")
        for slot in shield.get("rectangular_slots_mm", []):
            lines.append("    ; CAD slot subtraction leaves the finite end lands as one continuous grounded body.")
            lines.append(f"    notin_inside {{ {_box(slot)} }}")
        lines.append("  }")
    return lines


def validate_generation_grid_pitch(contract: Mapping[str, Any], pitch_mm: object) -> float:
    """Validate new target spacing against the contract quantum; never round a grid.

    Historical PA consumers do not call this generation-only check. Eight ULPs
    allow binary representation of an integer ratio, not a physical tolerance.
    """
    try:
        quantum = contract["simion"]["numerical_profiles"]["grid_generation"]["spacing_quantum_mm"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("new grid requires its spacing_quantum_mm contract") from error
    if (isinstance(quantum, bool) or not isinstance(quantum, (int, float))
            or not math.isfinite(quantum) or quantum <= 0):
        raise CandidateContractError("spacing_quantum_mm must be finite and positive")
    if (not isinstance(pitch_mm, list) or len(pitch_mm) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or v <= 0 for v in pitch_mm)):
        raise CandidateContractError("new grid pitch must contain three finite positive numeric spacings")
    for value in pitch_mm:
        ratio = value / quantum
        if not math.isfinite(ratio):
            raise CandidateContractError("new grid spacing/quantum ratio must be finite")
        multiple = round(ratio)
        if multiple < 1 or abs(ratio - multiple) > 8 * math.ulp(ratio):
            raise CandidateContractError("new grid spacing must be a positive integer multiple of spacing_quantum_mm")
    return float(quantum)


def _grid_shape(box: list[float], mesh: list[float]) -> list[int]:
    shape: list[int] = []
    for axis in range(3):
        cells = (box[axis + 3] - box[axis]) / mesh[axis]
        rounded = round(cells)
        if abs(cells - rounded) > 1e-8:
            raise CandidateContractError("native corridor extent is not aligned to its mesh")
        shape.append(int(rounded) + 1)
    return shape


def ordinary_pa_file_bytes(dimensions: list[int], pitch_mm: list[float]) -> int:
    """Forecast SIMION's ordinary GEM-save header and double node payload.

    SIMION 2020 lib/python/SIMION/PA.py load/save: mode -1 stores the 32-byte
    fixed header and implicit unit pitch. Nonunit pitch selects mode -2 and
    adds three double pitches (56-byte header). This is not a PA parser and
    does not broaden the mode -2-only affine-composition consumer.
    """
    header_bytes = struct.calcsize("<iidiiii")
    if pitch_mm != [1, 1, 1]:
        header_bytes += 3 * struct.calcsize("<d")
    return header_bytes + math.prod(dimensions) * struct.calcsize("<d")


def _analyzer_geometry_lines(resolved: dict[str, object], *, native_group_ids: Mapping[str, int] | None = None) -> list[str]:
    """Emit the same analyzer solids with optional explicit scientific-group IDs."""
    id_map = None
    shield_ids = None
    if native_group_ids is not None:
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface import _component_electrodes, _scientific_groups
        from .rf_electrode_mapping import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
        electrodes = _component_electrodes(resolved)
        groups = _scientific_groups(resolved, electrodes)
        names = [row['electrode_group_id'] for row in groups]
        if (not isinstance(native_group_ids, Mapping) or set(native_group_ids) != set(names)
                or any(type(v) is not int or not 1 <= v <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for v in native_group_ids.values())
                or len(set(native_group_ids.values())) != len(names)):
            raise ValueError('MR native IDs must uniquely cover all scientific groups')
        id_map = {electrode['component_electrode_id']:native_group_ids[group['electrode_group_id']]
                  for electrode, group in zip(electrodes, groups[:len(electrodes)], strict=True)}
        shield_ids = (native_group_ids['positive_mirror_ground_shield'], native_group_ids['negative_mirror_ground_shield'])
    lines: list[str] = []
    lines.extend(_mirror_lines(resolved, id_map))
    lines.extend(_mirror_ground_shield_lines(resolved, id_map, shield_ids))
    lines.extend(_stripe_lines(resolved, id_map))
    lines.extend(_central_ground_lines(resolved, id_map))
    lines.append("  ; CAD-constrained triangular prism electrodes, emitted after ground bodies.")
    for prism in resolved["prism_electrodes"]:
        terms = " ".join(term for part in prism["parts"] for term in _extrude_polygon_bands(part["x"], part["polygon_yz_mm"]))
        native_id = prism['id'] if id_map is None else id_map[prism['id']]
        lines.append(f"  e({native_id}) {{ {terms} }}")
    lines.extend(_prism_ground_shield_lines(resolved, id_map))
    return lines


def collision_overlay_plan(source: dict[str, Any], update: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Compile same-CSG occupancy; its vacuum replaces the coarse PA too."""
    if (not isinstance(update, dict) or set(update) != {"box_mm", "pitch_mm", "priority_probes"}
            or "collision_overlay" in source or source.get("consumer_view")
            or source.get("accelerator_provider") != IP_PROVIDER
            or [i["role"] for i in source["instances"]] != ["global_fallback", "native_corridor", "ion_processor_collision", "detector"]):
        raise ValueError("collision overlay requires one complete four-role IP source and explicit patch numerics")
    box, pitch = update["box_mm"], update["pitch_mm"]
    if (not isinstance(box, list) or len(box) != 6
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
            or box[0] != 0 or any(box[a] >= box[a+3] for a in range(3))):
        raise ValueError("collision overlay requires a finite x-mirrored nonempty box")
    validate_generation_grid_pitch(contract, pitch)
    dimensions = _grid_shape(box, pitch)
    if min(dimensions) < 3:
        raise ValueError("collision overlay requires at least three nodes on every axis")
    effective = [-box[3], box[1], box[2], *box[3:]]
    probes = update["priority_probes"]
    if not isinstance(probes, list) or not probes:
        raise ValueError("collision overlay requires declared metal, vacuum and exterior priority probes")
    labels, categories = set(), set()
    for probe in probes:
        if (not isinstance(probe, dict) or set(probe) != {"label", "point_mm", "expected_electrode", "expected_instance"}
                or not isinstance(probe["label"], str) or not probe["label"] or probe["label"] in labels
                or type(probe["expected_electrode"]) is not bool or type(probe["expected_instance"]) is not int
                or probe["expected_instance"] not in (2, 5)):
            raise ValueError("invalid collision overlay priority probe")
        point = probe["point_mm"]
        if (not isinstance(point, list) or len(point) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)):
            raise ValueError("collision overlay probe requires finite project coordinates")
        inside = all(effective[a] <= point[a] <= effective[a+3] for a in range(3))
        if inside != (probe["expected_instance"] == 5):
            raise ValueError("collision overlay probe instance contradicts its declared box")
        labels.add(probe["label"])
        categories.add((inside, probe["expected_electrode"]))
    if not {(True, True), (True, False)} <= categories or not any(not inside for inside, _ in categories):
        raise ValueError("collision overlay probes must cover interior metal, interior vacuum and exterior")
    bracket = any(
        sum(a != b for a, b in zip(inner["point_mm"], outer["point_mm"], strict=True)) == 1
        and all(abs(inner["point_mm"][a]-outer["point_mm"][a]) <= 2*pitch[a] for a in range(3))
        for inner in probes if inner["expected_instance"] == 5
        for outer in probes if outer["expected_instance"] == 2)
    if not bracket:
        raise ValueError("collision overlay probes require an adjacent inside/outside face bracket")
    gem = ("; Same complete analyzer CSG; collision only, no Refine or Fast Adjust.\npa_define("
           + ",".join(map(str, dimensions)) + ",planar,x,electric_,,"
           + ",".join(format(v, ".17g") for v in pitch) + ",surface=fractional)\nlocate("
           + ",".join(format(-v, ".17g") for v in box[:3]) + ") {\n"
           + "\n".join(_analyzer_geometry_lines(source["geometry"])) + "\n}\n")
    pa_bytes = ordinary_pa_file_bytes(dimensions, pitch)
    # Fractional surface storage is unknown before native GEM conversion. Reserve
    # another full PA plus evidence; the owner still measures the actual output.
    committed = 2*pa_bytes + 16*1024**2
    return dict(box_mm=box, origin_mm=box[:3], pitch_mm=pitch, dimensions=dimensions,
                symmetry="x", pa_bytes=pa_bytes, committed_new_bytes=committed,
                surface_allowance_bytes=pa_bytes, priority_probes=copy.deepcopy(probes), gem=gem,
                refine_performed=False, fast_adjust_performed=False, refinable=False)


def resolve_accelerator_assembly_transform(requirements, profile, profile_id, accelerator_assembly):
    """Validate the selected OA native supports and project its explicit assembly pose."""
    from msplatform.backends.simion.two_zone_candidate import resolve_closed_two_zone_electrodes
    from msplatform.contracts.rigid_transform import RigidTransform
    native = resolve_closed_two_zone_electrodes(
        requirements, geometry_profile_id=profile_id, geometry_profile=profile).to_dict()
    try:
        actual = accelerator_assembly["accelerator_resolved_electrodes"]
        supports = actual["grid_supports"]
        if (actual["acceleration_direction"] != "-z"
                or sorted(supports, key=lambda item: item["component_electrode_id"])
                != sorted(native["grid_supports"], key=lambda item: item["component_electrode_id"])):
            raise CandidateContractError("frozen OA support solids differ from explicit physical authority")
        translation = actual["local_to_pa_translation_mm"]
        origin = accelerator_assembly["accelerator_iob_origin_mm"]
        if len(translation) != 3 or len(origin) != 3:
            raise CandidateContractError("OA projection requires three-dimensional translations")
        delta = tuple(float(translation[i]) + float(origin[i]) for i in range(3))
        # The canonical mechanical exit is zero; native z carries its explicit storage margin.
        delta = (delta[0], delta[1], delta[2] + float(requirements["local_pa"]["exit_z_mm"]))
        return RigidTransform(
            "orthogonal_accelerator_exit_origin_v1",
            "astral.xyz.reflection_z.drift_y.transverse_x.v2",
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), delta)
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("P1 extension lacks complete matching OA support/placement authority") from error


def resolve_mr_geometry(contract: dict[str, Any], *, accelerator_geometry_authority: Mapping[str, Any],
                        inherited_dual_stripe_topology_contract: dict[str, Any] | None = None,
                        accelerator_to_mr=None, accelerator_assembly=None) -> dict[str, Any]:
    """Validate the explicit OA PA envelope before resolving current MR mechanics.

    This backend operation retains native span/mesh/margin/x-mirror guards.
    The domain resolver itself remains independent of PA storage coordinates.
    Source records are verified by their existing consuming workflow boundary.
    """
    from msplatform.backends.simion.two_zone_candidate import resolve_closed_two_zone_layout
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry import resolve_geometry

    if not isinstance(accelerator_geometry_authority, Mapping):
        raise CandidateContractError("new MR geometry requires complete explicit OA geometry authority")
    try:
        requirements = accelerator_geometry_authority["accelerator_requirements"]
        profile = accelerator_geometry_authority["geometry_profile"]
        profile_id = accelerator_geometry_authority["geometry_profile_id"]
    except KeyError as error:
        raise CandidateContractError("new MR geometry lacks complete frozen OA geometry authority") from error
    resolve_closed_two_zone_layout(requirements, geometry_profile_id=profile_id, geometry_profile=profile)
    if accelerator_assembly is not None:
        if accelerator_to_mr is not None:
            raise CandidateContractError("OA placement must have one explicit projection authority")
        accelerator_to_mr = resolve_accelerator_assembly_transform(
            requirements, profile, profile_id, accelerator_assembly)
    return resolve_geometry(
        contract, accelerator_requirements=requirements, geometry_profile=profile, geometry_profile_id=profile_id,
        inherited_dual_stripe_topology_contract=inherited_dual_stripe_topology_contract,
        accelerator_to_mr=accelerator_to_mr,
    )


def build_simion_gem(contract: dict[str, Any]) -> str:
    """Emit a reviewable legacy-GEM electrode map with stable electrode IDs.

    This is a topology source, not an approval to run SIMION: CAD dimensions and
    full PA bounds remain subject to the project CAD audit and numerical contract.
    """
    if contract.get("geometry_authority", {}).get("model") not in {
        "theory_derived_3d",
        "manufactured_CAD_geometry__theory_optimized_operating_point",
    }:
        raise CandidateContractError("SIMION topology needs a qualified Candidate authority")
    mirror = contract["mirror"]
    if candidate_contract._number(mirror.get("beam_slot_width_mm"), "beam_slot_width_mm") != 30.0:
        raise CandidateContractError("CAD mirror beam slot is a fixed 30 mm mechanical constraint")
    stripe = contract["dual_stripe"]
    if candidate_contract._number(stripe.get("beam_slot_width_mm"), "ion_foil_beam_slot_width_mm") != 4.0:
        raise CandidateContractError("CAD Ion-Foil beam slot is a fixed 4 mm mechanical constraint")
    edges = [candidate_contract._number(value, "electrode_z_edges_mm") for value in derive_mirror_boundaries(mirror)["active_start_z_mm"]]
    if len(edges) != 5 or edges != sorted(edges) or edges[0] <= 0.0:
        raise CandidateContractError("five positive ordered mirror electrode edges are required")
    width = candidate_contract._number(stripe["maximum_width_mm"], "maximum_width_mm")
    corridor = candidate_contract._number(stripe["central_grounded_corridor_mm"], "central_grounded_corridor_mm")
    lines = [
        "; MR-TOF Candidate-only topology source for SIMION 2020 legacy GEM.",
        "; Frame: x transverse focus, y drift, z reflection; central plane is z=0.",
        "; IDs 1..5 right mirror, 6..10 left mirror, 11..14 physical dual stripes.",
        "; Stripe pairs (11,12) and (13,14) share independently adjustable voltages.",
        "pa_define(801,801,1601, planar,none,electrostatic,,,0.25,0.25,0.25, surface=none)",
        "locate(400,400,800) {",
    ]
    for index, edge in enumerate(edges, start=1):
        lines.append(f"  e({index}) {{ box3D(-{width},-{width},{edge - 2}, {width},{width},{edge + 2}) }}")
        lines.append(f"  e({index + 5}) {{ box3D(-{width},-{width},{-edge - 2}, {width},{width},{-edge + 2}) }}")
    half = corridor / 2.0
    lines.extend([
        f"  e(11) {{ box3D(-{width},-{width},-{half}, {width},-{width / 2}, {half}) }}",
        f"  e(12) {{ box3D(-{width},{width / 2},-{half}, {width},{width}, {half}) }}",
        f"  e(13) {{ box3D(-{width / 2},-{width},-{half}, {width / 2},-{width / 2}, {half}) }}",
        f"  e(14) {{ box3D(-{width / 2},{width / 2},-{half}, {width / 2},{width}, {half}) }}",
        "  ; The accelerator, prism, grounded guard, detector and raw-node ideal grids are generated only after CAD audit.",
        "}",
        "",
    ])
    return "\n".join(lines)


def write_gem(contract_path: Path, output_path: Path) -> candidate_contract.TwoZoneFocus:
    """Validate a contract, emit its GEM source, and return the focus placement."""
    contract = candidate_contract.load_contract(contract_path)
    focus = candidate_contract.derive_two_zone_focus(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_simion_gem(contract), encoding="utf-8", newline="\n")
    return focus
