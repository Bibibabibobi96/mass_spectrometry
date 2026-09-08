"""Generate the full MR-TOF Candidate GEM from resolved physical geometry."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from projects.orthogonal_accelerator.analysis.two_zone_geometry import derive_shielded_rectangular_enclosure
from projects.orthogonal_accelerator.simion.rectangular_accelerator import (
    emit_grounded_enclosure, emit_ideal_grid, emit_open_rectangular_frame,
    emit_solid_rectangular_plate,
)
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


ELECTRODE_IDS = {
    "right_mirror": (1, 2, 3, 4, 5),
    "left_mirror": (6, 7, 8, 9, 10),
    "drift_stripe_set_1": (11, 12),
    "drift_stripe_set_2": (13, 14),
    "central_ground": 15,
    "prisms": (16, 17),
    "prism_ground_shields": (18, 20),
    "accelerator": (22, 23, 24),
    "accelerator_stage_2_rings": (26, 27, 28, 29, 30),
}


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


def resolve_simion_iob_origin(contract: dict[str, object]) -> tuple[float, float, float]:
    """Map the resolved physical origin to the PA instance origin in mm."""
    span = contract["simion"]["pa_span_mm"]
    if not isinstance(span, list) or len(span) != 3 or any(float(value) <= 0.0 for value in span):
        raise CandidateContractError("simion.pa_span_mm must contain three positive physical spans")
    placement = derive_two_zone_placement(contract)
    grid_phase_z = -placement.exit_grid_z_mm
    return (-float(span[0]) / 2.0, -float(span[1]) / 2.0, -float(span[2]) / 2.0 - grid_phase_z)


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


def build_full_candidate_gem(contract_path: Path) -> str:
    """Return a SIMION-2020 legacy GEM with all Candidate physical electrodes."""
    contract = load_contract(contract_path)
    if contract["status"] not in {
        "candidate_theory_derived_cad_constrained",
        "candidate_hardware_geometry__theory_operating_point_pending",
    }:
        raise CandidateContractError("full geometry needs a qualified Candidate contract status")
    if contract["accelerator"]["topology"] != "two_zone_orthogonal_pulsed":
        raise CandidateContractError("full geometry requires the MR-TOF two-zone accelerator")
    if contract.get("simion_geometry_release_status") != "cad_topology_and_top_level_pose_qualified":
        raise CandidateContractError(
            "SIMION PA generation is blocked until prism and accelerator top-level pose pass CAD/GUI qualification"
        )
    resolved = resolve_geometry(contract)
    if contract["mirror"].get("design_status") not in {
        "theory_l0_validated",
        "analytic_l0_l1_candidate__3d_unvalidated__pa_build_allowed",
    }:
        raise CandidateContractError("mirror theory L0/L1 candidate has not qualified a prototype PA build")
    if contract["dual_stripe"].get("central_ground_outline_status") != "cad_outline_verified_for_candidate":
        raise CandidateContractError("central ground is only an envelope; its CAD opening outline must be verified before PA geometry")
    if not resolved["metadata"]["mirror_stripe_clearance_pass"]:
        raise CandidateContractError("mirror and Stripe envelopes violate the required clearance")
    fingerprint = geometry_fingerprint(resolved)
    accelerator = contract["accelerator"]
    placement = derive_two_zone_placement(contract)
    repeller_thickness = float(accelerator["repeller_thickness_z_mm"])
    aperture_x = float(accelerator["aperture_width_x_mm"]) / 2.0
    aperture_y = float(accelerator["aperture_height_y_mm"]) / 2.0
    enclosure = derive_shielded_rectangular_enclosure(
        electrode_outer_width_x_mm=float(accelerator["electrode_outer_width_x_mm"]),
        electrode_outer_height_y_mm=float(accelerator["electrode_outer_height_y_mm"]),
        guard_outer_width_x_mm=float(accelerator["grounded_guard_outer_width_x_mm"]),
        guard_outer_height_y_mm=float(accelerator["grounded_guard_outer_height_y_mm"]),
        guard_wall_thickness_mm=float(accelerator["grounded_guard_wall_thickness_mm"]),
        lateral_clearance_mm=float(accelerator["repeller_to_guard_clearance_mm"]),
        repeller_z_mm=placement.repeller_z_mm,
        repeller_thickness_z_mm=repeller_thickness,
        rear_gap_mm=float(accelerator["repeller_to_rear_cap_gap_mm"]),
    )
    electrode_x, electrode_y = enclosure.electrode_half_x_mm, enclosure.electrode_half_y_mm
    grid_phase_z = -placement.exit_grid_z_mm
    span_x, span_y, span_z = (float(value) for value in contract["simion"]["pa_span_mm"])
    lines = [
        "; Full MR-TOF 3D SIMION Candidate (not Formal).",
        "; Native project frame: x transverse focus, y slow drift, z fast reflection; z=0 is the injection/focus handoff.",
        "; Geometry origin: theory-derived resolved primitives, constrained by audited CAD dimensions and curves.",
        f"; mirror_design_status={contract['mirror'].get('design_status', 'missing')}",
        f"; resolved_geometry_sha256={fingerprint}",
        "; Physical IDs: mirrors 1..10; Stripes 11..14; central ground 15; prisms 16..17; shields 18..20; accelerator 22..24 and stage-2 rings 26..30.",
        "# local mmgu_x = _G.var and _G.var.mmgu_x or 4.0",
        "# local mmgu_y = _G.var and _G.var.mmgu_y or 4.0",
        "# local mmgu_z = _G.var and _G.var.mmgu_z or 0.4",
        f"# local grid_phase_z = {_number(grid_phase_z)}",
        f"# local x_span, y_span, z_span = {_number(span_x)}, {_number(span_y)}, {_number(span_z)}",
        "# local nx = math.floor(x_span/mmgu_x + 0.5) + 1",
        "# local ny = math.floor(y_span/mmgu_y + 0.5) + 1",
        "# local nz = math.floor(z_span/mmgu_z + 0.5) + 1",
        "pa_define($(nx),$(ny),$(nz),planar,none,electrostatic,, $(mmgu_x),$(mmgu_y),$(mmgu_z),surface=none)",
        "locate($(x_span/2),$(y_span/2),$(z_span/2 + grid_phase_z)) {",
    ]
    lines.extend(_mirror_lines(resolved))
    lines.extend(_mirror_ground_shield_lines(resolved))
    lines.extend(_stripe_lines(resolved))
    lines.extend(_central_ground_lines(resolved))
    lines.extend((
        f"  ; Numerical detector event slab (not a PA electrode): {_box(resolved['detector']['box'])}.",
        f"  locate(0,{_number(placement.focus_y_mm)},0) {{",
        "  e(15) {",
        "    ; Hollow grounded guard: exit grid meets its inner wall; repeller has a rear acceleration gap before the rear cap.",
        "    " + emit_grounded_enclosure(enclosure, exit_z_mm=placement.exit_grid_z_mm),
        "  }",
        "  ; Theory-derived -z two-zone accelerator: closed repeller -> one-row grid1 -> one-row exit grid.",
        emit_solid_rectangular_plate(
            22, half_x_mm=electrode_x, half_y_mm=electrode_y,
            front_z_mm=placement.repeller_z_mm,
            back_z_mm=placement.repeller_z_mm+repeller_thickness,
        ),
    ))
    for support in resolved["accelerator_grid_support_frames"]:
        lines.extend((
            "  ; Finite grid support frame; only its aperture contains the zero-thickness ideal grid.",
            emit_open_rectangular_frame(
                support["id"], outer_half_x_mm=support["outer_half_x_mm"],
                outer_half_y_mm=support["outer_half_y_mm"],
                aperture_half_x_mm=support["aperture_half_x_mm"],
                aperture_half_y_mm=support["aperture_half_y_mm"],
                front_z_mm=support["front_z_mm"], back_z_mm=support["back_z_mm"],
                cut_padding_mm=support["thickness_z_mm"],
            ),
            emit_ideal_grid(
                support["id"], half_x_mm=support["aperture_half_x_mm"],
                half_y_mm=support["aperture_half_y_mm"], z_mm=support["grid_z_mm"],
            ),
        ))
    lines.append("  ; Five physical open acceleration rings uniformly fill the long second field region.")
    for ring in resolved["accelerator_stage_2_rings"]:
        half_t = float(ring["thickness_z_mm"]) / 2.0
        center = float(ring["center_z_mm"])
        lines.append(
            emit_open_rectangular_frame(
                int(ring['id']), outer_half_x_mm=electrode_x, outer_half_y_mm=electrode_y,
                aperture_half_x_mm=aperture_x, aperture_half_y_mm=aperture_y,
                front_z_mm=center-half_t, back_z_mm=center+half_t, cut_padding_mm=1.0,
            )
        )
    lines.append("  }")
    # Emit the CAD prism solids after the broad grounded bodies.  GEM applies
    # overlapping fills in source order; this keeps the explicitly placed
    # prism electrodes/shields from being erased by a later grounded outline.
    lines.append("  ; Two triangular deflection prisms from the resolved CAD-constrained contract.")
    for prism in resolved["prism_electrodes"]:
        parts = " ".join(
            term for part in prism["parts"] for term in _extrude_polygon_bands(part["x"], part["polygon_yz_mm"])
        )
        lines.append(f"  e({prism['id']}) {{ {parts} }}")
    lines.extend(_prism_ground_shield_lines(resolved))
    lines.extend(("}", ""))
    return "\n".join(lines)


def write_full_candidate_gem(contract_path: Path, output_path: Path) -> None:
    """Write a line-feed GEM source suitable for SIMION's ``gem2pa`` command."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_full_candidate_gem(contract_path), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    arguments = parser.parse_args()
    write_full_candidate_gem(arguments.contract, arguments.output)
    if arguments.receipt:
        write_geometry_receipt(load_contract(arguments.contract), arguments.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
