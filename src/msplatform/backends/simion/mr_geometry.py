"""SIMION GEM emitters and native PA geometry planning for the MR analyzer."""
from __future__ import annotations

import copy
import math
import struct
from typing import Any, Iterable, Mapping

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.geometry_contract import CENTRAL_GROUND_ELECTRODE_ID

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


def _mirror_lines(resolved: dict[str, object]) -> list[str]:
    lines = [
        "  ; Each active mirror electrode has its own CAD 580 x 30-mm bounded aperture.",
        "  ; The aperture terminates before both y ends and does not pass through end plates in z.",
    ]
    for electrode in resolved["mirror_electrodes"]:
        if "polygon_yz_mm" in electrode:
            lines.extend(_mirror_polygon_lines(electrode, electrode["id"]))
            continue
        lines.extend((
            f"  e({electrode['id']}) {{",
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


def _mirror_ground_shield_lines(resolved: dict[str, object]) -> list[str]:
    """Emit the CAD-derived inner grounded mirror end plates as shared 0-V ID 15."""
    if resolved.get("mirror_convergence_transform") is not None:
        lines = []
        for shield in resolved["mirror_ground_shields"]:
            lines.extend(_mirror_polygon_lines(shield, CENTRAL_GROUND_ELECTRODE_ID))
        for closure in resolved["mirror_e_closures"]:
            lines.extend(_mirror_polygon_lines(closure, closure["id"]))
        return lines
    inner_slot = _box(resolved["mirror_inner_shield_slot"])
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


def _stripe_lines(resolved: dict[str, object]) -> list[str]:
    slot = _box(resolved["stripe_slot"])
    lines = ["  ; Four physical curved Stripe conductors; pairs (11,12) and (13,14) share biases."]
    for electrode in resolved["stripe_electrodes"]:
        lower, upper = electrode["x"]
        lines.extend((
            f"  e({electrode['id']}) {{",
            *(f"    {term}" for term in _extrude_polygon_bands([lower, upper], electrode["polygon_yz_mm"])),
            *(f"    {term}" for term in _extrude_polygon_bands([lower, upper], electrode["terminal_polygon_yz_mm"])),
            # SIMION's official ``notin_inside`` preserves CAD-face nodes.
            # Thus a 4-mm channel retains metal at x=±2 mm, not ±3 mm.
            f"    notin_inside {{ {slot} }}",
            "  }",
        ))
    return lines


def _central_ground_lines(resolved: dict[str, object]) -> list[str]:
    """Emit one whole native Foil-2 body minus its two rectangular windows."""
    lines = ["  ; Whole Ion-Foil-2 with native short cubic and planar end features; no added bridges.",
             f"  e({CENTRAL_GROUND_ELECTRODE_ID}) {{"]
    for body in resolved["central_ground_electrodes"]:
        lines.extend(f"    {term}" for term in _extrude_polygon_bands(body["x"], body["polygon_yz_mm"]))
    lines.extend(f"    notin_inside {{ {_box(slot)} }}" for slot in resolved["central_ground_slots"])
    lines.append("  }")
    return lines


def _prism_ground_shield_lines(resolved: dict[str, object]) -> list[str]:
    """Emit finite-y grounded frames with CAD-audited apertures."""
    lines = [
        "  ; Grounded prism frames retain their CAD finite-y bodies and nested triangular apertures.",
    ]
    for shield in resolved["prism_ground_shields"]:
        outer = [term for section in shield["body_sections"]
                 for term in _extrude_polygon_bands(section["x"], section["polygon_yz_mm"])]
        aperture = _extrude_polygon_bands(shield["x"], shield["prism_clearance_polygon_yz_mm"])
        lines.append(f"  e({shield['id']}) {{")
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
