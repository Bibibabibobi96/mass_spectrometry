"""Generate the full MR-TOF Candidate GEM from resolved physical geometry."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    geometry_fingerprint,
    resolve_geometry,
    write_geometry_receipt,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
    load_contract,
)


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
        lines.extend((
            f"  e({electrode['id']}) {{",
            f"    {_box(electrode['box'])}",
            f"    notin_inside {{ {_box(electrode['beam_slot'])} }}",
            "  }",
        ))
    return lines


def _mirror_ground_shield_lines(resolved: dict[str, object]) -> list[str]:
    """Emit the CAD-derived inner grounded mirror end plates as shared 0-V ID 15."""
    inner_slot = _box(resolved["mirror_inner_shield_slot"])
    lines = [
        "  ; CAD inner end plates: Stripe-facing 5-mm shields have 4-mm slots.",
        "  e(15) {",
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
             "  e(15) {"]
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
