"""Emit the two shield-decoupled SIMION PA components for the MR-TOF Candidate.

The analyser and its pulsed accelerator are separate PA instances.  They share
only the resolved project-frame geometry receipt; the grounded accelerator
enclosure is an intentional electrostatic boundary, so no monolithic refine is
permitted.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from projects.orthogonal_accelerator.analysis.two_zone_geometry import derive_shielded_rectangular_enclosure
from projects.orthogonal_accelerator.simion.rectangular_accelerator import (
    emit_grounded_enclosure, emit_ideal_grid, emit_open_rectangular_frame,
    emit_solid_rectangular_plate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry import (
    _box, _central_ground_lines, _extrude_polygon_bands, _mirror_ground_shield_lines, _mirror_lines,
    _number, _prism_ground_shield_lines, _stripe_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, derive_two_zone_placement, load_contract,
)

# A split PA has its own SIMION Fast-Adjust namespace.  Keep the stable project
# IDs in the resolved contract, but map its local arrays densely so SIMION does
# not request nonexistent pa1..paN files for a sparse 15/22..30 namespace.
ACCELERATOR_LOCAL_ELECTRODE_IDS = {15: 1, 22: 2, 23: 3, 24: 4, 26: 5, 27: 6, 28: 7, 29: 8, 30: 9}


def _require_release(contract: dict[str, object]) -> None:
    if contract.get("simion_geometry_release_status") != "cad_topology_and_top_level_pose_qualified":
        raise CandidateContractError("split PA generation requires the qualified CAD topology/pose release")


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
    lines.extend(("}", ""))
    return "\n".join(lines)


def _detector_origin(contract: dict[str, object], span: tuple[float, float, float]) -> tuple[float, float, float]:
    """Return the independent detector PA origin derived only from its resolved box."""
    detector = resolve_geometry(contract)["detector"]
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


def build_accelerator_gem(contract_path: Path) -> str:
    """Build the shielded local two-zone accelerator PA in local millimetres."""
    contract = load_contract(contract_path)
    _require_release(contract)
    resolved = resolve_geometry(contract)
    accelerator = contract["accelerator"]
    mesh = contract["simion"]["component_mesh_mm_per_gu"]["accelerator"]
    span_x, span_y, span_z = _span(contract, "accelerator_pa_span_mm")
    placement = derive_two_zone_placement(contract)
    margin_z = float(accelerator["pa_local_margin_z_mm"])
    if margin_z <= 0:
        raise CandidateContractError("accelerator.pa_local_margin_z_mm must be positive")
    repeller_t = float(accelerator["repeller_thickness_z_mm"])
    local_exit = margin_z
    local_grid_1 = local_exit + float(accelerator["gap_2_mm"])
    local_repeller = local_grid_1 + float(accelerator["gap_1_mm"])
    enclosure = derive_shielded_rectangular_enclosure(
        electrode_outer_width_x_mm=float(accelerator["electrode_outer_width_x_mm"]),
        electrode_outer_height_y_mm=float(accelerator["electrode_outer_height_y_mm"]),
        guard_outer_width_x_mm=float(accelerator["grounded_guard_outer_width_x_mm"]),
        guard_outer_height_y_mm=float(accelerator["grounded_guard_outer_height_y_mm"]),
        guard_wall_thickness_mm=float(accelerator["grounded_guard_wall_thickness_mm"]),
        lateral_clearance_mm=float(accelerator["repeller_to_guard_clearance_mm"]),
        repeller_z_mm=local_repeller,
        repeller_thickness_z_mm=repeller_t,
        rear_gap_mm=float(accelerator["repeller_to_rear_cap_gap_mm"]),
    )
    electrode_x, electrode_y = enclosure.electrode_half_x_mm, enclosure.electrode_half_y_mm
    guard_x, guard_y = enclosure.guard_half_x_mm, enclosure.guard_half_y_mm
    rear_cap_outer = enclosure.rear_cap_outer_z_mm
    if rear_cap_outer + margin_z > span_z + 1e-9:
        raise CandidateContractError("accelerator local PA z span does not enclose both grids and margins")
    aperture_x = float(accelerator["aperture_width_x_mm"]) / 2.0
    aperture_y = float(accelerator["aperture_height_y_mm"]) / 2.0
    if max(guard_x, guard_y) * 2 + 2 * float(accelerator["pa_transverse_margin_mm"]) > min(span_x, span_y) + 1e-9:
        raise CandidateContractError("accelerator local PA transverse span is too small for grounded enclosure")
    lines = [
        "; Local shielded two-zone accelerator PA only; local +z is project +z.",
        f"; global repeller z={_number(placement.repeller_z_mm)} mm; global focus=(0,{_number(placement.focus_y_mm)},0) mm.",
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
        "locate($(x_span/2),$(y_span/2),0) {",
        "  ; Finite-wall grounded enclosure: hollow field cavity, not a solid box with a drilled tunnel.",
        "  ; The exit grid meets the inner wall; the repeller has lateral and rear acceleration gaps before the grounded rear cap.",
        f"  ; Stable project IDs map to local IDs {ACCELERATOR_LOCAL_ELECTRODE_IDS}; this mapping is solver-local only.",
        f"  e(1) {{ {emit_grounded_enclosure(enclosure, exit_z_mm=local_exit)} notin {{ box3D(-{_number(aperture_x)},-{_number(aperture_y)},{_number(margin_z-1)},{_number(aperture_x)},{_number(aperture_y)},{_number(local_exit+1)}) }} }}",
        emit_solid_rectangular_plate(
            2, half_x_mm=electrode_x, half_y_mm=electrode_y,
            front_z_mm=local_repeller, back_z_mm=local_repeller+repeller_t,
        ),
    ]
    for support in resolved["accelerator_grid_support_frames"]:
        offset_z = local_exit - placement.exit_grid_z_mm
        electrode_id = ACCELERATOR_LOCAL_ELECTRODE_IDS[support["id"]]
        lines.extend((
            "  ; Finite grid support frame; only its aperture contains the zero-thickness ideal grid.",
            emit_open_rectangular_frame(
                electrode_id, outer_half_x_mm=support["outer_half_x_mm"],
                outer_half_y_mm=support["outer_half_y_mm"],
                aperture_half_x_mm=support["aperture_half_x_mm"],
                aperture_half_y_mm=support["aperture_half_y_mm"],
                front_z_mm=support["front_z_mm"]+offset_z,
                back_z_mm=support["back_z_mm"]+offset_z,
                cut_padding_mm=support["thickness_z_mm"],
            ),
            emit_ideal_grid(
                electrode_id, half_x_mm=support["aperture_half_x_mm"],
                half_y_mm=support["aperture_half_y_mm"], z_mm=support["grid_z_mm"]+offset_z,
            ),
        ))
    lines.append("  ; Five physical open acceleration rings uniformly fill the long second field region.")
    for ring in resolved["accelerator_stage_2_rings"]:
        half_t = float(ring["thickness_z_mm"]) / 2.0
        center = float(ring["center_z_mm"]) - placement.exit_grid_z_mm + local_exit
        lines.append(
            emit_open_rectangular_frame(
                ACCELERATOR_LOCAL_ELECTRODE_IDS[int(ring['id'])],
                outer_half_x_mm=electrode_x, outer_half_y_mm=electrode_y,
                aperture_half_x_mm=aperture_x, aperture_half_y_mm=aperture_y,
                front_z_mm=center-half_t, back_z_mm=center+half_t, cut_padding_mm=1.0,
            )
        )
    lines.extend(("}", ""))
    return "\n".join(lines)


def resolve_split_iob_origins(contract_path: Path) -> dict[str, tuple[float, float, float]]:
    """Return the sole allowed project-to-Workbench translations for both PAs."""
    contract = load_contract(contract_path)
    _require_release(contract)
    analyzer_span = _span(contract, "analyzer_pa_span_mm")
    accelerator_span = _span(contract, "accelerator_pa_span_mm")
    accelerator = contract["accelerator"]
    placement = derive_two_zone_placement(contract)
    local_exit = float(accelerator["pa_local_margin_z_mm"])
    return {
        "analyzer": _analyzer_origin(contract, analyzer_span),
        "accelerator": (-accelerator_span[0] / 2.0, placement.focus_y_mm - accelerator_span[1] / 2.0, placement.exit_grid_z_mm - local_exit),
        "detector": _detector_origin(contract, _span(contract, "detector_pa_span_mm")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--component", required=True, choices=("analyzer", "accelerator", "detector"))
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.component == "analyzer":
        text = build_analyzer_gem(arguments.contract)
    elif arguments.component == "accelerator":
        text = build_accelerator_gem(arguments.contract)
    else:
        text = build_detector_gem(arguments.contract)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
