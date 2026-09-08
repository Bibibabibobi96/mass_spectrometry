"""Pure reference and SIMION-GEM source generator for the MR-TOF prototype.

The only coordinate frame accepted here is the project frame: z is reflection,
y is drift, x is transverse focusing, and z=0 is the injection midplane.  This
module deliberately does not import the oa-TOF implementation: its accelerator
is a separate candidate, even though it uses the same two-uniform-field theory.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projects.orthogonal_accelerator.analysis.two_zone_geometry import TwoZoneGeometryError, UniformRingPlaneLayout, derive_uniform_ring_planes
from projects.orthogonal_accelerator.analysis.two_zone_theory import TwoZoneTheoryError, TwoZoneTimeFocus, derive_two_zone_time_focus
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries


class CandidateContractError(ValueError):
    """Raised when the prototype contract cannot describe a physical candidate."""


@dataclass(frozen=True)
class TwoZoneFocus(TwoZoneTimeFocus):
    """MR alias retaining the candidate-reference result type."""


@dataclass(frozen=True)
class TwoZonePlacement:
    """Project-frame locations of the three two-zone accelerator electrodes."""

    repeller_z_mm: float
    grid_1_z_mm: float
    exit_grid_z_mm: float
    focus_y_mm: float
    focus_z_mm: float


@dataclass(frozen=True)
class OperatingEnergyEnvelope:
    """Derived per-charge energy quantities for the coupled accelerator/analyser."""

    pre_acceleration_kinetic_energy_v: float
    net_gain_reference_center_v: float
    selected_net_gain_center_v: float
    net_gain_center_minimum_v: float
    net_gain_center_maximum_v: float
    particle_net_gain_half_range_v: float
    mirror_energy_nodes_v: tuple[float, float, float]
    mirror_b_through_d_maximum_v: float
    post_acceleration_total_energy_reference_v: float


def _number(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


def derive_operating_energy_envelope(
    contract: dict[str, Any], *, selected_center_v: float | None = None,
) -> OperatingEnergyEnvelope:
    """Derive accelerator search and mirror-window energies from native inputs.

    The current mirror and Stripe theory deliberately use the selected net-gain
    reference centre as ``w0``.  The incoming 5 eV/q remains separately visible
    in total-energy bookkeeping and is not silently added to that theory axis.
    """
    energy = contract.get("accelerator_energy_contract")
    if not isinstance(energy, dict):
        raise CandidateContractError("accelerator_energy_contract is required")
    pre_energy = _number(
        energy.get("pre_acceleration_kinetic_energy_per_charge_v"),
        "pre_acceleration_kinetic_energy_per_charge_v",
    )
    reference = _number(
        energy.get("net_gain_reference_center_per_charge_v"),
        "net_gain_reference_center_per_charge_v",
    )
    center_half_range = _number(
        energy.get("net_gain_center_search_half_range_per_charge_v"),
        "net_gain_center_search_half_range_per_charge_v",
    )
    particle_half_range = _number(
        energy.get("maximum_particle_net_gain_deviation_per_charge_v"),
        "maximum_particle_net_gain_deviation_per_charge_v",
    )
    if pre_energy < 0.0 or reference <= 0.0:
        raise CandidateContractError("accelerator energies require pre-energy >= 0 and gain > 0")
    if not 0.0 < center_half_range < reference:
        raise CandidateContractError("net-gain centre search half-range must be in (0, reference)")
    if not 0.0 < particle_half_range < reference - center_half_range:
        raise CandidateContractError(
            "particle net-gain deviation must be positive and below the lowest centre"
        )
    if energy.get("mirror_and_stripe_energy_basis") != "net_acceleration_gain_reference_center":
        raise CandidateContractError(
            "mirror and Stripe energy basis must be the net-gain reference centre"
        )
    nominal = _number(contract.get("nominal", {}).get("energy_per_charge_v"), "nominal energy")
    if nominal != reference:
        raise CandidateContractError(
            "nominal mirror/Stripe energy must equal the net-gain reference centre"
        )
    selected = reference if selected_center_v is None else _number(
        selected_center_v, "selected net-gain center"
    )
    center_minimum = reference - center_half_range
    center_maximum = reference + center_half_range
    if not center_minimum <= selected <= center_maximum:
        raise CandidateContractError("selected net-gain center lies outside the declared search range")
    nodes = (selected - particle_half_range, selected, selected + particle_half_range)
    return OperatingEnergyEnvelope(
        pre_acceleration_kinetic_energy_v=pre_energy,
        net_gain_reference_center_v=reference,
        selected_net_gain_center_v=selected,
        net_gain_center_minimum_v=center_minimum,
        net_gain_center_maximum_v=center_maximum,
        particle_net_gain_half_range_v=particle_half_range,
        mirror_energy_nodes_v=nodes,
        mirror_b_through_d_maximum_v=nodes[0],
        post_acceleration_total_energy_reference_v=pre_energy + selected,
    )


def derive_mirror_voltage_bounds(
    contract: dict[str, Any], *, selected_center_v: float | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Resolve B--E search bounds, including the energy-derived B--D cap."""
    energy = derive_operating_energy_envelope(contract, selected_center_v=selected_center_v)
    envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
    keys = ("B", "C", "D", "E")
    expected_cap = "minimum_particle_net_acceleration_gain_per_charge_v"
    if any(envelope[key].get("maximum_inclusive_v") != expected_cap for key in keys[:3]):
        raise CandidateContractError("mirror B--D maxima must reference the minimum particle net gain")
    lower = tuple(
        math.nextafter(max(energy.mirror_energy_nodes_v), math.inf)
        if key == "E" else _number(envelope[key]["minimum_inclusive_v"], f"mirror {key} minimum")
        for key in keys
    )
    upper = tuple(
        energy.mirror_b_through_d_maximum_v
        if key != "E" else _number(envelope[key]["maximum_inclusive_v"], "mirror E maximum")
        for key in keys
    )
    if any(low >= high for low, high in zip(lower, upper, strict=True)):
        raise CandidateContractError("resolved mirror voltage envelope is empty")
    return lower, upper


def load_contract(path: Path) -> dict[str, Any]:
    """Load and minimally validate the MR-TOF-only candidate contract."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("project_id") != "parallel_mirror_dual_stripe_mr_tof":
        raise CandidateContractError("project_id must identify the MR-TOF project")
    authority = data.get("geometry_authority", {})
    if authority.get("model") not in {
        "theory_derived_3d",
        "manufactured_CAD_geometry__theory_optimized_operating_point",
    }:
        raise CandidateContractError(
            "geometry authority must be either a theory-derived design or a fixed manufactured "
            "mirror geometry with a theory-optimized operating point"
        )
    frame = data.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v1":
        raise CandidateContractError("candidate must use the documented Astral coordinate frame")
    mirror = data.get("mirror", {})
    if _number(mirror.get("beam_slot_width_mm"), "beam_slot_width_mm") != 30.0:
        raise CandidateContractError("CAD mirror beam slot is a fixed 30 mm mechanical constraint")
    stripe = data.get("dual_stripe", {})
    if stripe.get("physical_electrode_count") != 4 or stripe.get("theoretical_response_count") != 2:
        raise CandidateContractError("dual stripe requires four physical electrodes and two responses")
    if _number(stripe.get("beam_slot_width_mm"), "ion_foil_beam_slot_width_mm") != 4.0:
        raise CandidateContractError("CAD Ion-Foil beam slot is a fixed 4 mm mechanical constraint")
    if _number(stripe["minimum_width_mm"], "minimum_width_mm") <= 0.0:
        raise CandidateContractError("stripe widths must remain positive")
    if _number(stripe["maximum_width_mm"], "maximum_width_mm") < _number(stripe["minimum_width_mm"], "minimum_width_mm"):
        raise CandidateContractError("maximum stripe width must be >= minimum width")
    derive_operating_energy_envelope(data)
    derive_mirror_voltage_bounds(data)
    return data


def derive_two_zone_focus(contract: dict[str, Any]) -> TwoZoneFocus:
    """Derive the first-order temporal focus of the two uniform-field regions."""
    frame = contract.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v1":
        raise CandidateContractError("candidate must use the documented Astral coordinate frame")
    accelerator = contract["accelerator"]
    try:
        focus = derive_two_zone_time_focus(
            repeller_v=_number(accelerator["repeller_v"], "repeller_v"),
            intermediate_v=_number(accelerator["intermediate_grid_v"], "intermediate_grid_v"),
            exit_v=_number(accelerator["exit_grid_v"], "exit_grid_v"),
            gap_1_mm=_number(accelerator["gap_1_mm"], "gap_1_mm"),
            gap_2_mm=_number(accelerator["gap_2_mm"], "gap_2_mm"),
            release_position_in_gap_1_mm=_number(
                accelerator["release_position_in_gap_1_mm"], "release_position_in_gap_1_mm"
            ),
        )
    except TwoZoneTheoryError as error:
        raise CandidateContractError(str(error)) from error
    result = TwoZoneFocus(
        focus.field_1_v_per_mm, focus.field_2_v_per_mm,
        focus.energy_per_charge_v, focus.focus_after_exit_mm,
    )
    expected_gain = derive_operating_energy_envelope(contract).net_gain_reference_center_v
    if not math.isclose(result.energy_per_charge_v, expected_gain, rel_tol=0.0, abs_tol=1e-9):
        raise CandidateContractError(
            "two-zone reference voltages must produce the declared net-gain reference centre"
        )
    return result


def derive_two_zone_placement(contract: dict[str, Any]) -> TwoZonePlacement:
    """Place the -z accelerator so its first time focus lies on the z=0 plane.

    The focus plane constrains only z.  Its y coordinate is the independently
    declared injection-line coordinate and must not be silently collapsed to
    the project origin.
    """
    accelerator = contract["accelerator"]
    if accelerator.get("axis") != "z_negative":
        raise CandidateContractError("the two-zone Candidate accelerator must accelerate along -z")
    focus_position = accelerator.get("focus_project_position_mm")
    if not isinstance(focus_position, list) or len(focus_position) != 3:
        raise CandidateContractError("focus_project_position_mm must be a three-coordinate project point")
    focus_x = _number(focus_position[0], "focus_project_position_mm[0]")
    focus_z = _number(focus_position[2], "focus_project_position_mm[2]")
    anchor = accelerator.get("focus_y_anchor")
    if not isinstance(anchor, dict) or anchor.get("method") != "audited_triangle_y_bounds_midpoint":
        raise CandidateContractError("accelerator focus y must be derived from an audited prism station")
    station = anchor.get("prism_station")
    prisms = contract.get("prisms", {}).get("electrodes", [])
    matching = [item for item in prisms if isinstance(item, dict) and item.get("station") == station]
    if len(matching) != 1:
        raise CandidateContractError("accelerator focus y anchor must select exactly one prism station")
    coordinates = matching[0].get("polygons_yz_mm", [])
    y_values = [
        _number(polygon[index], "accelerator focus prism y coordinate")
        for polygon in coordinates if isinstance(polygon, list)
        for index in range(0, len(polygon), 2)
    ]
    if not y_values:
        raise CandidateContractError("accelerator focus prism has no y-coordinate evidence")
    focus_y = (min(y_values) + max(y_values)) / 2.0
    if abs(focus_x) > 1e-12 or abs(focus_z) > 1e-12 or accelerator.get("focus_plane_constraint") != "z=0":
        raise CandidateContractError(
            "first time focus must lie on the x=0, z=0 central injection plane"
        )
    focus = derive_two_zone_focus(contract)
    gap_1 = _number(accelerator["gap_1_mm"], "gap_1_mm")
    gap_2 = _number(accelerator["gap_2_mm"], "gap_2_mm")
    # Ions leave the exit grid toward -z.  The upstream repeller/grid planes
    # therefore lie on +z, and the positive post-exit focal distance ends at z=0.
    exit_grid = focus_z + focus.focus_after_exit_mm
    grid_1 = exit_grid + gap_2
    repeller = grid_1 + gap_1
    return TwoZonePlacement(repeller, grid_1, exit_grid, focus_y, focus_z)


def derive_stage_2_ring_layout(contract: dict[str, Any]) -> UniformRingPlaneLayout:
    """Return the physical second-zone ring planes in project ``z`` order.

    The long second field region extends from grid1 toward the lower-``z``
    exit grid.  Ring count and thickness are project inputs; their equal pitch
    is solver-neutral shared geometry derived from the two endpoint planes.
    """
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict):
        raise CandidateContractError("stage-2 rings require an accelerator contract")
    rings = accelerator.get("stage_2_rings")
    if not isinstance(rings, dict):
        raise CandidateContractError("accelerator.stage_2_rings is required")
    count = rings.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise CandidateContractError("accelerator.stage_2_rings.count must be a positive integer")
    if rings.get("outer_frame") != "inherits_declared_repeller_and_grid_frame" or rings.get("beam_aperture") != "inherits_declared_accelerator_aperture":
        raise CandidateContractError("stage-2 rings must inherit the declared accelerator frame and aperture")
    if rings.get("voltage_rule") != "linear_interpolation_from_grid1_to_exit":
        raise CandidateContractError("stage-2 ring voltage rule must interpolate the two field endpoints")
    placement = derive_two_zone_placement(contract)
    try:
        return derive_uniform_ring_planes(
            placement.grid_1_z_mm,
            placement.exit_grid_z_mm,
            count,
            ring_thickness_mm=_number(rings.get("thickness_z_mm"), "accelerator.stage_2_rings.thickness_z_mm"),
        )
    except TwoZoneGeometryError as error:
        raise CandidateContractError(str(error)) from error


def derive_stage_2_ring_voltages(contract: dict[str, Any]) -> tuple[float, ...]:
    """Linearly interpolate stage-2 ring voltages from grid1 to the exit grid."""
    accelerator = contract["accelerator"]
    layout = derive_stage_2_ring_layout(contract)
    grid_1 = _number(accelerator["intermediate_grid_v"], "intermediate_grid_v")
    exit_grid = _number(accelerator["exit_grid_v"], "exit_grid_v")
    return tuple(
        grid_1 + (exit_grid - grid_1) * index / (len(layout.centers_mm) + 1)
        for index in range(1, len(layout.centers_mm) + 1)
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
    if _number(mirror.get("beam_slot_width_mm"), "beam_slot_width_mm") != 30.0:
        raise CandidateContractError("CAD mirror beam slot is a fixed 30 mm mechanical constraint")
    stripe = contract["dual_stripe"]
    if _number(stripe.get("beam_slot_width_mm"), "ion_foil_beam_slot_width_mm") != 4.0:
        raise CandidateContractError("CAD Ion-Foil beam slot is a fixed 4 mm mechanical constraint")
    edges = [_number(value, "electrode_z_edges_mm") for value in derive_mirror_boundaries(mirror)["active_start_z_mm"]]
    if len(edges) != 5 or edges != sorted(edges) or edges[0] <= 0.0:
        raise CandidateContractError("five positive ordered mirror electrode edges are required")
    width = _number(stripe["maximum_width_mm"], "maximum_width_mm")
    corridor = _number(stripe["central_grounded_corridor_mm"], "central_grounded_corridor_mm")
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


def write_gem(contract_path: Path, output_path: Path) -> TwoZoneFocus:
    """Validate a contract, emit its GEM source, and return the focus placement."""
    contract = load_contract(contract_path)
    focus = derive_two_zone_focus(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_simion_gem(contract), encoding="utf-8", newline="\n")
    return focus
