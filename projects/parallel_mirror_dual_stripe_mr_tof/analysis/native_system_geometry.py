"""Emit MR-owned static geometry projections for the native system runtime.

The analyser and its pulsed accelerator are separate PA instances.  They share
only the resolved project-frame geometry receipt; the grounded accelerator
enclosure is an intentional electrostatic boundary, so no monolithic refine is
permitted.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import (
    _box, _central_ground_lines, _extrude_polygon_bands, _mirror_ground_shield_lines, _mirror_lines,
    _number, _prism_ground_shield_lines, _stripe_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, derive_two_zone_placement, load_contract,
)

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
    local_origin = domain.get("iob_origin_mm")
    placement = requirements.get("placement")
    if (
        not isinstance(span, list) or len(span) != 3
        or not isinstance(local_origin, list) or len(local_origin) != 3
        or not isinstance(placement, dict)
    ):
        raise CandidateContractError("accelerator provider pose fields are incomplete")
    spans = tuple(float(value) for value in span)
    provider_origin = tuple(float(value) for value in local_origin)
    if min(spans) <= 0.0 or provider_origin != (-spans[0] / 2.0, -spans[1] / 2.0, 0.0):
        raise CandidateContractError("accelerator provider local IOB origin rule differs")
    local_exit_z = float(domain.get("local_exit_z_mm"))
    global_exit_z = float(placement.get("global_exit_z_mm"))
    if not all(value == value and abs(value) < float("inf") for value in (*spans, local_exit_z, global_exit_z)):
        raise CandidateContractError("accelerator provider pose contains a non-finite value")

    resolved = resolve_geometry(contract)
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
