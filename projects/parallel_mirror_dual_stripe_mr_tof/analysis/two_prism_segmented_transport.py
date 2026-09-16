"""Bind the frozen two-prism and dual-Stripe geometry to segmented transport.

This adapter creates only solver-neutral constant-potential regions in the
project y-z frame.  Voltages are mandatory caller inputs; source states,
mirror roots, event sequences, and numerical controls remain outside this
module.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    axial_potential_gradient_v_per_mm,
    axial_potential_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    InterfaceBoundary,
    PhaseState2D,
    PotentialRegion,
    StopTarget,
    TransportEvent,
    TransportError,
    TransportNumerics,
    TransportResult,
    curved_strip_potential_region,
    plane_stop_target,
    polygon_potential_region,
    propagate_segmented_hamiltonian,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_analytic import (
    PrismAnalyticError,
    hard_boundary_bias_for_face_order_and_target_direction_v,
    trace_triangular_hard_boundary_prism,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_edge_evaluators,
    dual_stripe_physical_instance_topology,
    resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    TwoPrismTransportObservation,
    prism_handoff_residuals,
)


def _finite_bias(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateContractError(f"{label} must be a finite voltage")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be a finite voltage") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be a finite voltage")
    return result


def validate_two_prism_voltage_polarity_domain(
    contract: Mapping[str, Any],
    *,
    charge_state: int,
    p1_bounds_v: tuple[float, float],
    p2_bounds_v: tuple[float, float],
) -> dict[str, Any]:
    """Fail closed unless a search domain obeys the frozen path polarity."""
    if type(charge_state) is not int or charge_state == 0:
        raise CandidateContractError("two-prism polarity validation needs a nonzero integer charge")
    try:
        authority = contract["prism_transport"]["two_prism_injection_l0"][
            "voltage_polarity_contract"
        ]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("two-prism voltage polarity contract is missing") from error
    if authority.get("status") != "user_frozen_path_polarity__magnitudes_solver_derived":
        raise CandidateContractError("two-prism voltage polarity contract status is invalid")
    reference_charge = authority.get("reference_charge_state_e")
    if type(reference_charge) is not int or reference_charge == 0:
        raise CandidateContractError("two-prism reference charge state is invalid")
    signs = {
        "positive": 1,
        "negative": -1,
    }
    try:
        p1_sign = signs[authority["first_prism_required_sign"]]
        p2_sign = signs[authority["second_prism_required_sign"]]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("two-prism required voltage signs are invalid") from error
    if charge_state * reference_charge < 0:
        if authority.get("negative_charge_rule") != "reverse_both_prism_voltage_signs":
            raise CandidateContractError("negative-charge prism polarity rule is invalid")
        p1_sign *= -1
        p2_sign *= -1
    for label, bounds, required_sign in (
        ("P1", p1_bounds_v, p1_sign),
        ("P2", p2_bounds_v, p2_sign),
    ):
        lower, upper = (_finite_bias(value, f"{label} bound") for value in bounds)
        if lower >= upper:
            raise CandidateContractError(f"{label} voltage bounds must have positive width")
        if required_sign > 0 and lower <= 0.0:
            raise CandidateContractError(f"{label} voltage domain must be strictly positive")
        if required_sign < 0 and upper >= 0.0:
            raise CandidateContractError(f"{label} voltage domain must be strictly negative")
    return {
        "charge_state_e": charge_state,
        "p1_required_sign": p1_sign,
        "p2_required_sign": p2_sign,
        "p1_bounds_v": list(p1_bounds_v),
        "p2_bounds_v": list(p2_bounds_v),
        "magnitude_semantics": authority.get("magnitude_semantics"),
    }


def _exact_bias_map(
    values: Mapping[Any, Any], expected_keys: set[Any], label: str,
) -> dict[Any, float]:
    if not isinstance(values, Mapping) or set(values) != expected_keys:
        raise CandidateContractError(f"{label} voltage keys must be exactly {sorted(expected_keys, key=str)}")
    return {key: _finite_bias(values[key], f"{label} {key}") for key in expected_keys}


def _rectangle_bounds(
    vertices: Sequence[Sequence[float]], label: str,
) -> tuple[float, float, float, float]:
    if len(vertices) != 4 or any(len(point) != 2 for point in vertices):
        raise CandidateContractError(f"{label} terminal trim must be a four-vertex y-z rectangle")
    points = tuple((float(point[0]), float(point[1])) for point in vertices)
    if any(not math.isfinite(value) for point in points for value in point):
        raise CandidateContractError(f"{label} terminal trim coordinates must be finite")
    y_values = sorted({point[0] for point in points})
    z_values = sorted({point[1] for point in points})
    if len(y_values) != 2 or len(z_values) != 2 or not y_values[0] < y_values[1] or not z_values[0] < z_values[1]:
        raise CandidateContractError(f"{label} terminal trim must have positive rectangular area")
    if set(points) != {(y, z) for y in y_values for z in z_values}:
        raise CandidateContractError(f"{label} terminal trim must contain each rectangle corner exactly once")
    return y_values[0], y_values[1], z_values[0], z_values[1]


def _filtered_boundary(
    boundary: InterfaceBoundary,
    exposed: Callable[[float, float], bool],
) -> InterfaceBoundary:
    return InterfaceBoundary(
        boundary.name,
        boundary.level,
        boundary.inward_normal,
        lambda y, z: boundary.contains_boundary_point(y, z) and exposed(y, z),
    )


def _stripe_region(
    contract: dict[str, Any],
    record: dict[str, Any],
    *,
    set_name: str,
    reflection_axis_sign: int,
    bias_v: float,
) -> tuple[PotentialRegion, tuple[float, float, float, float]]:
    electrode_id = int(record["id"])
    name = f"stripe_{electrode_id}_{set_name}"
    edges = compile_dual_stripe_edge_evaluators(contract, set_name, reflection_axis_sign)
    active_y0, active_y1 = edges.active_y_span_mm
    trim_bounds = _rectangle_bounds(record["terminal_polygon_yz_mm"], name)
    trim_y0, trim_y1, trim_z0, trim_z1 = trim_bounds
    if trim_y1 != active_y0:
        raise CandidateContractError(f"{name} terminal trim must meet the registered active function origin")

    active_z0 = edges.lower_z_mm(active_y0)
    active_z1 = edges.upper_z_mm(active_y0)
    active_end_z0 = edges.lower_z_mm(active_y1)
    active_end_z1 = edges.upper_z_mm(active_y1)
    if not active_z0 < active_z1:
        raise CandidateContractError(f"{name} active Stripe width must be positive")
    if max(trim_z0, active_z0) >= min(trim_z1, active_z1):
        raise CandidateContractError(f"{name} terminal trim is disconnected from its active Stripe")

    active = curved_strip_potential_region(
        f"{name}.active",
        (active_y0, active_y1),
        edges.lower_z_mm,
        edges.upper_z_mm,
        edges.lower_dz_dy,
        edges.upper_dz_dy,
        bias_v,
    )
    trim = polygon_potential_region(f"{name}.trim", record["terminal_polygon_yz_mm"], bias_v)

    def outside_active_seam(_y: float, z: float) -> bool:
        return not active_z0 < z < active_z1

    def outside_trim_seam(_y: float, z: float) -> bool:
        return not trim_z0 < z < trim_z1

    trim_vertices = tuple((float(point[0]), float(point[1])) for point in record["terminal_polygon_yz_mm"])
    trim_boundaries = []
    for boundary, start, end in zip(trim.boundaries, trim_vertices, trim_vertices[1:] + trim_vertices[:1]):
        is_join = start[0] == trim_y1 and end[0] == trim_y1
        trim_boundaries.append(_filtered_boundary(boundary, outside_active_seam) if is_join else boundary)
    active_boundaries = []
    for boundary in active.boundaries:
        if boundary.name == f"{name}.active.y_start":
            active_boundaries.append(InterfaceBoundary(
                boundary.name,
                boundary.level,
                boundary.inward_normal,
                lambda _y, z: active_z0 <= z <= active_z1 and outside_trim_seam(_y, z),
            ))
        elif boundary.name == f"{name}.active.y_end":
            active_boundaries.append(InterfaceBoundary(
                boundary.name,
                boundary.level,
                boundary.inward_normal,
                lambda _y, z: active_end_z0 <= z <= active_end_z1,
            ))
        else:
            active_boundaries.append(boundary)

    def contains(y: float, z: float) -> bool:
        return trim.contains(y, z) or active.contains(y, z)

    return (
        PotentialRegion(name, bias_v, tuple(trim_boundaries) + tuple(active_boundaries), contains),
        trim_bounds,
    )


def _reject_terminal_overlap(
    regions: Sequence[tuple[int, tuple[float, float, float, float]]],
) -> None:
    for index, (first_id, first) in enumerate(regions):
        for second_id, second in regions[index + 1:]:
            y_overlap = max(first[0], second[0]) < min(first[1], second[1])
            z_overlap = max(first[2], second[2]) < min(first[3], second[3])
            if y_overlap and z_overlap:
                raise CandidateContractError(
                    f"Stripe terminal trims {first_id} and {second_id} overlap"
                )


def build_two_prism_segmented_potential_regions(
    contract: dict[str, Any],
    *,
    prism_bias_v_by_electrode_id: Mapping[int, float],
    stripe_bias_v_by_set_name: Mapping[str, float],
) -> tuple[PotentialRegion, ...]:
    """Return P1/P2 and four physical Stripe regions in stable electrode order.

    The two x-separated solids of each prism must expose the same y-z
    triangle because this is a two-dimensional reduction.  Each Stripe's
    mechanical terminal trim and active native B-spline band are joined into
    one potential region, with their common y seam removed wherever the two
    cross-sections overlap.
    """
    prism_biases = _exact_bias_map(prism_bias_v_by_electrode_id, {16, 17}, "prism")
    stripe_biases = _exact_bias_map(stripe_bias_v_by_set_name, {"set_1", "set_2"}, "Stripe")
    resolved = resolve_geometry(contract)

    prism_regions = []
    for record in sorted(resolved["prism_electrodes"], key=lambda item: item["id"]):
        electrode_id = int(record["id"])
        parts = record.get("parts")
        if not isinstance(parts, list) or len(parts) != 2:
            raise CandidateContractError(f"prism {electrode_id} requires two facing x sections")
        left, right = sorted(parts, key=lambda item: item["x"][0])
        if left["polygon_yz_mm"] != right["polygon_yz_mm"] or left["x"][1] > right["x"][0]:
            raise CandidateContractError(
                f"prism {electrode_id} facing x sections must have one consistent y-z triangle"
            )
        prism_regions.append(polygon_potential_region(
            f"prism_{electrode_id}", left["polygon_yz_mm"], prism_biases[electrode_id],
        ))

    stripe_records = {int(item["id"]): item for item in resolved["stripe_electrodes"]}
    stripe_regions = []
    terminal_bounds = []
    for instance in dual_stripe_physical_instance_topology(contract):
        if instance.electrode_id not in stripe_records:
            raise CandidateContractError("resolved Stripe geometry differs from its physical topology")
        region, bounds = _stripe_region(
            contract,
            stripe_records[instance.electrode_id],
            set_name=instance.set_name,
            reflection_axis_sign=instance.reflection_axis_sign,
            bias_v=stripe_biases[instance.set_name],
        )
        stripe_regions.append(region)
        terminal_bounds.append((instance.electrode_id, bounds))
    if set(stripe_records) != {item.electrode_id for item in dual_stripe_physical_instance_topology(contract)}:
        raise CandidateContractError("resolved Stripe geometry contains an unknown physical electrode")
    _reject_terminal_overlap(terminal_bounds)
    return tuple(prism_regions + stripe_regions)


@dataclass(frozen=True)
class TwoPrismSourceEnergyDiagnostic:
    """Upstream source-energy checks excluded from the two-voltage residuals."""

    source_slow_kinetic_energy_per_charge_v: float
    target_slow_kinetic_energy_per_charge_v: float
    source_axial_hamiltonian_per_charge_v: float
    selected_axial_energy_per_charge_v: float
    source_slow_energy_residual_v: float
    source_axial_energy_residual_v: float


@dataclass(frozen=True)
class TwoPrismTransverseProjectionDiagnostic:
    """The measured x state omitted from the solver-neutral y-z projection."""

    source_x_mm: float
    source_vx_mm_per_us: float
    transverse_kinetic_energy_ev: float
    transverse_kinetic_energy_per_charge_v: float


@dataclass(frozen=True)
class TwoPrismSegmentedVoltagePairDiagnostic:
    """One solver-neutral hard-boundary P1/P2 voltage-pair diagnostic."""

    qualification: str
    source: ProjectPhaseSpaceState
    transverse_projection: TwoPrismTransverseProjectionDiagnostic
    source_energy_consistency: TwoPrismSourceEnergyDiagnostic
    stage_a_p1_to_interface: TransportResult
    stage_b_p1_exit_to_p2_low_field_reference: TransportResult
    inferred_negative_mirror_pre_reflection: bool
    stripe_entrance_region_name: str
    voltage_residuals: tuple[tuple[str, float], ...]
    limitations: tuple[str, ...]
    stage_c_low_field_reference_to_positive_mirror_turn: TransportResult | None = None
    stage_d_positive_mirror_turn_to_first_stripe_pass: TransportResult | None = None
    p2_shield_low_field_reference_state: ProjectPhaseSpaceState | None = None
    positive_mirror_turn_state: ProjectPhaseSpaceState | None = None
    derived_positive_mirror_turn_z_mm: float | None = None

    @property
    def stage_b_pre_reflection_to_stripe_entrance(self) -> TransportResult:
        """Deprecated compatibility alias; stage B ends before the positive turn."""
        return self.stage_b_p1_exit_to_p2_low_field_reference


@dataclass(frozen=True)
class P2IdealAngleVoltagePrediction:
    """One exact-triangle P2 proposal derived from a legal pre-entry state."""

    qualification: str
    p2_electrode_id: int
    source_prism_bias_v: float
    predicted_prism_bias_v: float
    entry_edge_index: int
    exit_edge_index: int
    incident_kinetic_energy_per_charge_v: float
    incident_unit_direction_yz: tuple[float, float]
    target_reference_tangent_ratio: float
    target_exit_unit_direction_yz: tuple[float, float]
    reference_z_mm: float
    exit_z_mm: float
    limitations: tuple[str, ...]


def _finite_value(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateContractError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _triangle_edge_index(event: TransportEvent, expected_region: str) -> int:
    if event.region_name != expected_region or not event.name.startswith(f"{expected_region}.edge_"):
        raise CandidateContractError("P2 event does not identify a triangle edge")
    try:
        index = int(event.name.rsplit("_", 1)[1])
    except (IndexError, ValueError) as error:
        raise CandidateContractError("P2 triangle edge index is invalid") from error
    if index not in (0, 1, 2):
        raise CandidateContractError("P2 triangle edge index lies outside [0, 2]")
    return index


def predict_p2_ideal_bias_for_reference_tangent_ratio(
    contract: dict[str, Any],
    diagnostic: TwoPrismSegmentedVoltagePairDiagnostic,
    *,
    mirror_design: MirrorL0Design,
    charge_state: int,
    target_reference_tangent_ratio: float,
) -> P2IdealAngleVoltagePrediction:
    """Predict P2 from its actual pre-entry state and desired reference angle.

    P1 and the negative mirror determine the state immediately before P2, so
    that state is independent of the P2 bias in the hard-boundary model.  The
    requested direction at the downstream reference plane is back-propagated
    through the continuous axial mirror potential to the P2 exit.  Tangential
    momentum conservation on the actual entry/exit triangle faces then gives
    P2 analytically.  The proposal remains approximate because the continuous
    mirror gradient inside the finite triangle is omitted by this one-element
    solve; full segmented propagation must verify it and its topology.
    """
    if type(charge_state) is not int or charge_state == 0:
        raise CandidateContractError("charge state must be a nonzero integer")
    target_ratio = _finite_value(
        target_reference_tangent_ratio, "target P2-reference tangent ratio",
    )
    if target_ratio <= 0.0:
        raise CandidateContractError("target P2-reference tangent ratio must be positive")
    try:
        p2_id = int(contract["prism_transport"]["second_prism"]["electrode_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("contract lacks the path-order P2 electrode ID") from error
    region_name = f"prism_{p2_id}"
    p2_pairs = _complete_region_passes(
        diagnostic.stage_b_p1_exit_to_p2_low_field_reference.events,
        region_name,
    )
    if len(p2_pairs) != 1:
        raise CandidateContractError("P2 prediction requires one transmitted P2 pass")
    entry_event, exit_event = p2_pairs[0]
    entry_edge = _triangle_edge_index(entry_event, region_name)
    exit_edge = _triangle_edge_index(exit_event, region_name)
    if entry_edge == exit_edge:
        raise CandidateContractError("P2 entry and exit faces must differ")

    resolved = resolve_geometry(contract)
    records = [
        item for item in resolved["prism_electrodes"]
        if int(item.get("id", -1)) == p2_id
    ]
    if len(records) != 1 or not isinstance(records[0].get("parts"), list):
        raise CandidateContractError("resolved P2 triangle geometry is missing")
    parts = records[0]["parts"]
    if len(parts) != 2 or parts[0].get("polygon_yz_mm") != parts[1].get("polygon_yz_mm"):
        raise CandidateContractError("resolved P2 facing parts do not share one y-z triangle")
    triangle = parts[0]["polygon_yz_mm"]

    stage = diagnostic.stage_b_p1_exit_to_p2_low_field_reference
    hamiltonian = _finite_value(stage.initial_hamiltonian_v, "stage-B Hamiltonian")
    sign = 1 if charge_state > 0 else -1
    reference = stage.final_state
    exit_state = exit_event.state_after
    reference_kinetic = hamiltonian - sign * axial_potential_v(reference.z_mm, mirror_design)
    if reference_kinetic <= 0.0:
        raise CandidateContractError("target P2 reference plane has no positive kinetic energy")
    target_uz_reference = math.sqrt(reference_kinetic / (1.0 + target_ratio**2))
    target_uy = target_ratio * target_uz_reference
    exit_kinetic = hamiltonian - sign * axial_potential_v(exit_state.z_mm, mirror_design)
    target_uz_exit_squared = exit_kinetic - target_uy**2
    if target_uz_exit_squared <= 0.0:
        raise CandidateContractError("target reference angle cannot be back-propagated to P2 exit")
    target_exit_direction = (
        target_uy / math.sqrt(exit_kinetic),
        math.sqrt(target_uz_exit_squared) / math.sqrt(exit_kinetic),
    )
    incident_energy = entry_event.state_before.u_y_sqrt_v**2 + entry_event.state_before.u_z_sqrt_v**2
    incident_direction = (
        entry_event.state_before.u_y_sqrt_v / math.sqrt(incident_energy),
        entry_event.state_before.u_z_sqrt_v / math.sqrt(incident_energy),
    )
    try:
        predicted = hard_boundary_bias_for_face_order_and_target_direction_v(
            triangle,
            incident_direction,
            target_exit_direction,
            incident_energy,
            entry_edge_index=entry_edge,
            exit_edge_index=exit_edge,
            charge_sign=sign,
        )
        entry_point = (entry_event.state_before.y_mm, entry_event.state_before.z_mm)
        scale = max(1.0, *(abs(value) for point in triangle for value in point))
        origin = tuple(
            value - 1.0e-7 * scale * direction
            for value, direction in zip(entry_point, incident_direction)
        )
        trace = trace_triangular_hard_boundary_prism(
            triangle,
            origin,
            incident_direction,
            incident_energy,
            predicted,
            charge_sign=sign,
        )
    except PrismAnalyticError as error:
        raise CandidateContractError(f"ideal P2 angle prediction failed: {error}") from error
    if (
        trace.status != "transmitted"
        or trace.entry_edge_index != entry_edge
        or trace.exit_edge_index != exit_edge
    ):
        raise CandidateContractError("ideal P2 prediction does not preserve its triangle face order")
    return P2IdealAngleVoltagePrediction(
        qualification="ideal_triangle_fixed_pre_entry_state_angle_seed_only",
        p2_electrode_id=p2_id,
        source_prism_bias_v=entry_event.applied_potential_change_v / sign,
        predicted_prism_bias_v=predicted,
        entry_edge_index=entry_edge,
        exit_edge_index=exit_edge,
        incident_kinetic_energy_per_charge_v=incident_energy,
        incident_unit_direction_yz=incident_direction,
        target_reference_tangent_ratio=target_ratio,
        target_exit_unit_direction_yz=target_exit_direction,
        reference_z_mm=reference.z_mm,
        exit_z_mm=exit_state.z_mm,
        limitations=(
            "the continuous mirror potential is back-propagated outside P2 but its gradient inside P2 is omitted",
            "the full segmented path must preserve the same face order and instrument topology",
            "finite-three-dimensional fringe fields and grounded shields are not represented",
        ),
    )


def _species_scale_v_per_velocity_squared(
    particle_mass_th: float, charge_state: int,
) -> float:
    mass = _finite_value(particle_mass_th, "particle mass")
    if mass <= 0.0:
        raise CandidateContractError("particle mass must be positive")
    if type(charge_state) is not int or charge_state == 0:
        raise CandidateContractError("charge state must be a nonzero integer")
    return kinetic_energy_ev(mass, 0.0, 1000.0, 0.0) / abs(charge_state)


def _reduced_state_from_project_source(
    source: ProjectPhaseSpaceState,
    *,
    particle_mass_th: float,
    charge_state: int,
) -> PhaseState2D:
    """Project one complete finite 3-D source into signed y-z momenta."""
    _x, y, z = source.position_mm
    _vx, vy, vz = source.velocity_mm_per_us
    scale = _species_scale_v_per_velocity_squared(particle_mass_th, charge_state)
    return PhaseState2D(
        0.0,
        y,
        z,
        math.copysign(math.sqrt(scale * vy * vy), vy),
        math.copysign(math.sqrt(scale * vz * vz), vz),
    )


def _project_state_from_reduced(
    state: PhaseState2D,
    *,
    particle_mass_th: float,
    charge_state: int,
) -> ProjectPhaseSpaceState:
    scale = _species_scale_v_per_velocity_squared(particle_mass_th, charge_state)
    return ProjectPhaseSpaceState(
        (0.0, state.y_mm, state.z_mm),
        (
            0.0,
            state.u_y_sqrt_v / math.sqrt(scale),
            state.u_z_sqrt_v / math.sqrt(scale),
        ),
    )


def _p1_interface_target(contract: dict[str, Any]) -> tuple[int, StopTarget]:
    try:
        first = contract["prism_transport"]["first_prism"]
        target = first["target_interface"]
        prism_id = int(first["electrode_id"])
        shield_id = int(target["ground_shield_id"])
        coordinate = _finite_value(target["coordinate_mm"], "P1 target coordinate")
        shields = contract["prisms"]["ground_shields"]
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("P1 target plane or grounded-shield authority is incomplete") from error
    if (
        target.get("axis") != "z"
        or target.get("y_acceptance_from_slot")
        != f"grounded_shield_{shield_id}_slot_y_bounds"
    ):
        raise CandidateContractError("P1 target must use the declared grounded-shield slot z plane")
    matches = [
        shield for shield in shields
        if isinstance(shield, dict) and shield.get("id") == shield_id
    ] if isinstance(shields, list) else []
    if len(matches) != 1:
        raise CandidateContractError("P1 target needs exactly one matching grounded shield")
    slots = matches[0].get("rectangular_slots_mm")
    if not isinstance(slots, list) or len(slots) != 1:
        raise CandidateContractError("P1 grounded shield must expose one authoritative rectangular slot")
    box = slots[0].get("box") if isinstance(slots[0], dict) else None
    if not isinstance(box, list) or len(box) != 6:
        raise CandidateContractError("P1 grounded-shield slot must provide one six-bound box")
    bounds = tuple(_finite_value(value, "P1 grounded-shield slot bound") for value in box)
    if not bounds[0] < bounds[3] or not bounds[1] < bounds[4] or not bounds[2] < bounds[5]:
        raise CandidateContractError("P1 grounded-shield slot bounds must be ordered")
    target_plane = plane_stop_target(
        "p1_post_prism_interface",
        (0.0, 1.0),
        coordinate,
        direction=-1,
        contains_target_point=lambda y, _z: bounds[1] <= y <= bounds[4],
    )
    return prism_id, target_plane


def _p2_handoff_authority(contract: dict[str, Any]) -> tuple[int, float, StopTarget]:
    try:
        transport = contract["prism_transport"]
        p2_id = int(transport["second_prism"]["electrode_id"])
        function_y = _finite_value(
            contract["dual_stripe_l0"]["theory_function_coordinate_registration"]
            ["function_y_zero_project_y_mm"],
            "Stripe function-origin y",
        )
        electrodes = contract["prisms"]["electrodes"]
        shields = contract["prisms"]["ground_shields"]
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("P2 handoff geometry or function origin is incomplete") from error
    p2 = [item for item in electrodes if isinstance(item, dict) and item.get("id") == p2_id]
    if len(p2) != 1:
        raise CandidateContractError("P2 handoff needs exactly one P2 electrode")
    shield = [
        item for item in shields
        if isinstance(item, dict) and item.get("station") == p2[0].get("station")
    ]
    if len(shield) != 1 or not isinstance(shield[0].get("cross_aperture"), dict):
        raise CandidateContractError("P2 handoff needs one cross-aperture grounded shield")
    clearance = shield[0].get("prism_clearance_polygon_yz_mm")
    cross = shield[0]["cross_aperture"]
    try:
        lower = max(_finite_value(point[1], "P2 clearance z") for point in clearance)
        cross_z = tuple(_finite_value(value, "P2 cross-aperture z") for value in cross["z_mm"])
        outer_y = tuple(
            _finite_value(point[0], "P2 shield outer y")
            for point in shield[0]["outer_polygon_yz_mm"]
        )
    except (KeyError, TypeError) as error:
        raise CandidateContractError("P2 low-field reference geometry is incomplete") from error
    upper = cross_z[1]
    if len(cross_z) != 2 or not cross_z[0] < lower < upper or not min(outer_y) < max(outer_y):
        raise CandidateContractError("P2 geometry has no positive-z low-field reference section")
    plane_z = 0.5 * (lower + upper)
    reference = plane_stop_target(
        "p2_low_field_reference",
        (0.0, 1.0),
        plane_z,
        direction=1,
        contains_target_point=lambda y, _z: min(outer_y) <= y <= max(outer_y),
    )
    return p2_id, function_y, reference


def _propagate_to_first_positive_mirror_turn(
    initial: PhaseState2D,
    *,
    charge_sign: int,
    mirror_potential_v: Callable[[float], float],
    mirror_gradient_v_per_mm: Callable[[float], float],
    potential_regions: Sequence[PotentialRegion],
    maximum_reduced_time_mm_per_sqrt_v: float,
    numerics: TransportNumerics,
) -> TransportResult:
    """Step the segmented trajectory and localize its first smooth +z turn."""
    if initial.u_z_sqrt_v <= 0.0:
        raise CandidateContractError("positive-mirror turn search must start with positive u_z")
    end = _finite_value(maximum_reduced_time_mm_per_sqrt_v, "positive-turn search limit")
    current = initial
    events: list[TransportEvent] = []
    initial_h: float | None = None
    maximum_residual = 0.0
    for _step in range(numerics.maximum_steps):
        next_time = min(end, current.reduced_time_mm_per_sqrt_v + numerics.max_step_mm_per_sqrt_v)
        if next_time <= current.reduced_time_mm_per_sqrt_v:
            break
        try:
            segment = propagate_segmented_hamiltonian(
                current,
                charge_sign=charge_sign,
                mirror_potential_v=mirror_potential_v,
                mirror_gradient_v_per_mm=mirror_gradient_v_per_mm,
                potential_regions=potential_regions,
                stop_targets=(),
                maximum_reduced_time_mm_per_sqrt_v=next_time,
                numerics=numerics,
            )
        except TransportError as error:
            raise CandidateContractError(f"positive-mirror turn transport failed: {error}") from error
        if any(event.transmitted is False for event in segment.events):
            raise CandidateContractError("positive-mirror turn path contains a hard-boundary reflection")
        if initial_h is None:
            initial_h = segment.initial_hamiltonian_v
        maximum_residual = max(
            maximum_residual, segment.maximum_absolute_hamiltonian_residual_v,
        )
        continuous_bracket: tuple[float, float] | None = None
        previous = current
        for event in (item for item in segment.events if item.kind == "interface"):
            if previous.u_z_sqrt_v > 0.0 and event.state_before.u_z_sqrt_v <= 0.0:
                continuous_bracket = (
                    previous.reduced_time_mm_per_sqrt_v,
                    event.state_before.reduced_time_mm_per_sqrt_v,
                )
                break
            if (
                event.state_before.u_z_sqrt_v > 0.0
                and event.state_after.u_z_sqrt_v <= 0.0
            ):
                raise CandidateContractError(
                    "positive-to-negative z momentum change occurred at a hard-boundary "
                    f"interface {event.name}, not at a smooth positive-mirror turn: "
                    f"u_z_before={event.state_before.u_z_sqrt_v:.17g}, "
                    f"u_z_after={event.state_after.u_z_sqrt_v:.17g}"
                )
            previous = event.state_after
        if (
            continuous_bracket is None
            and previous.u_z_sqrt_v > 0.0
            and segment.final_state.u_z_sqrt_v <= 0.0
        ):
            continuous_bracket = (
                previous.reduced_time_mm_per_sqrt_v,
                segment.final_state.reduced_time_mm_per_sqrt_v,
            )
        if continuous_bracket is not None:
            left, right = continuous_bracket
            localized = segment
            for _iteration in range(80):
                if right - left <= numerics.root_time_tolerance_mm_per_sqrt_v:
                    break
                middle = 0.5 * (left + right)
                probe = propagate_segmented_hamiltonian(
                    current,
                    charge_sign=charge_sign,
                    mirror_potential_v=mirror_potential_v,
                    mirror_gradient_v_per_mm=mirror_gradient_v_per_mm,
                    potential_regions=potential_regions,
                    stop_targets=(),
                    maximum_reduced_time_mm_per_sqrt_v=middle,
                    numerics=numerics,
                )
                if probe.final_state.u_z_sqrt_v > 0.0:
                    left = middle
                else:
                    right = middle
                    localized = probe
            raw = localized.final_state
            if raw.u_z_sqrt_v > numerics.momentum_tolerance_sqrt_v:
                raise CandidateContractError(
                    "positive-mirror turn localization did not reach the negative side of a smooth root"
                )
            turn = PhaseState2D(
                raw.reduced_time_mm_per_sqrt_v,
                raw.y_mm,
                raw.z_mm,
                raw.u_y_sqrt_v,
                0.0,
            )
            events.extend(localized.events)
            events.append(TransportEvent(
                "stop", "first_post_P2_positive_mirror_turn", turn, turn,
                None, None, None, 0.0, 0.0, 0.0,
                localized.final_hamiltonian_residual_v,
            ))
            return TransportResult(
                "stopped_at_positive_mirror_turn",
                initial,
                turn,
                localized.active_region_names,
                tuple(events),
                initial_h if initial_h is not None else localized.initial_hamiltonian_v,
                localized.final_hamiltonian_v,
                localized.final_hamiltonian_residual_v,
                maximum_residual,
            )
        events.extend(segment.events)
        current = segment.final_state
    raise CandidateContractError("stage C did not reach the first post-P2 positive-mirror turn")


def _complete_region_passes(
    events: Sequence[TransportEvent], region_name: str,
) -> tuple[tuple[TransportEvent, TransportEvent], ...]:
    selected = [event for event in events if event.region_name == region_name]
    if len(selected) % 2:
        raise CandidateContractError(f"{region_name} has an incomplete interface pass")
    pairs = []
    for entry, exit_event in zip(selected[::2], selected[1::2], strict=True):
        if (
            entry.kind != "interface" or exit_event.kind != "interface"
            or entry.entering is not True or exit_event.entering is not False
            or entry.transmitted is not True or exit_event.transmitted is not True
            or entry.state_before.reduced_time_mm_per_sqrt_v
            >= exit_event.state_after.reduced_time_mm_per_sqrt_v
        ):
            raise CandidateContractError(f"{region_name} does not have transmitted enter/exit pairs")
        pairs.append((entry, exit_event))
    return tuple(pairs)


def _propagate_to_first_complete_positive_stripe_pass(
    initial: PhaseState2D,
    *,
    charge_sign: int,
    mirror_potential_v: Callable[[float], float],
    mirror_gradient_v_per_mm: Callable[[float], float],
    potential_regions: Sequence[PotentialRegion],
    positive_stripe_region_names: Sequence[str],
    maximum_reduced_time_mm_per_sqrt_v: float,
    numerics: TransportNumerics,
) -> TransportResult:
    """Verify the first post-turn Stripe entry and its complete transmitted pass."""
    if abs(initial.u_z_sqrt_v) > numerics.momentum_tolerance_sqrt_v:
        raise CandidateContractError("post-turn Stripe search must start at the localized z turn")
    if initial.z_mm <= 0.0 or initial.u_y_sqrt_v <= 0.0:
        raise CandidateContractError("post-turn Stripe search needs positive z and positive u_y")
    allowed = frozenset(positive_stripe_region_names)
    if not allowed:
        raise CandidateContractError("post-turn Stripe search needs positive-side Stripe regions")
    end = _finite_value(maximum_reduced_time_mm_per_sqrt_v, "post-turn Stripe search limit")
    current = initial
    events: list[TransportEvent] = []
    pending_entry: TransportEvent | None = None
    initial_h: float | None = None
    maximum_residual = 0.0
    for _step in range(numerics.maximum_steps):
        next_time = min(end, current.reduced_time_mm_per_sqrt_v + numerics.max_step_mm_per_sqrt_v)
        if next_time <= current.reduced_time_mm_per_sqrt_v:
            break
        try:
            segment = propagate_segmented_hamiltonian(
                current,
                charge_sign=charge_sign,
                mirror_potential_v=mirror_potential_v,
                mirror_gradient_v_per_mm=mirror_gradient_v_per_mm,
                potential_regions=potential_regions,
                stop_targets=(),
                maximum_reduced_time_mm_per_sqrt_v=next_time,
                numerics=numerics,
            )
        except TransportError as error:
            raise CandidateContractError(f"post-turn Stripe transport failed: {error}") from error
        if initial_h is None:
            initial_h = segment.initial_hamiltonian_v
        maximum_residual = max(
            maximum_residual,
            abs(segment.initial_hamiltonian_v - initial_h),
            abs(segment.final_hamiltonian_v - initial_h),
        )
        for event in (item for item in segment.events if item.kind == "interface"):
            if event.transmitted is not True:
                raise CandidateContractError(
                    "post-turn path contains a reflected or unresolved hard-boundary crossing"
                )
            if event.region_name not in allowed:
                raise CandidateContractError(
                    "post-turn path reaches an interface outside the positive-Stripe path"
                )
            if (
                event.state_before.u_z_sqrt_v >= -numerics.momentum_tolerance_sqrt_v
                or event.state_after.u_z_sqrt_v >= -numerics.momentum_tolerance_sqrt_v
            ):
                raise CandidateContractError(
                    "Stripe transmission must preserve strictly negative z momentum on both "
                    f"sides of interface {event.name}"
                )
            events.append(event)
            if pending_entry is None:
                if event.entering is not True:
                    raise CandidateContractError(
                        "the first post-turn Stripe interface must be a transmitted entry"
                    )
                pending_entry = event
                continue
            if event.region_name != pending_entry.region_name or event.entering is not False:
                raise CandidateContractError(
                    "the first post-turn Stripe entry is not followed by its matching exit"
                )
            exit_state = event.state_after
            global_final_h = segment.initial_hamiltonian_v + event.hamiltonian_residual_v
            global_residual = global_final_h - initial_h
            stop = TransportEvent(
                "stop",
                "first_post_turn_positive_stripe_pass_complete",
                exit_state,
                exit_state,
                None,
                None,
                None,
                0.0,
                0.0,
                0.0,
                global_residual,
            )
            return TransportResult(
                "stopped_after_first_positive_stripe_pass",
                initial,
                exit_state,
                (),
                tuple(events + [stop]),
                initial_h,
                global_final_h,
                global_residual,
                max(maximum_residual, abs(global_residual)),
            )
        if (
            pending_entry is not None
            and segment.final_state.u_z_sqrt_v >= -numerics.momentum_tolerance_sqrt_v
        ):
            raise CandidateContractError(
                "z momentum reached a smooth turn before the first Stripe pass exited"
            )
        current = segment.final_state
    if pending_entry is not None:
        raise CandidateContractError("post-turn positive-Stripe pass is incomplete")
    raise CandidateContractError("positive mirror turn is not followed by a positive-Stripe entry")


def evaluate_two_prism_segmented_voltage_pair(
    contract: dict[str, Any],
    *,
    source: ProjectPhaseSpaceState,
    particle_mass_th: float,
    charge_state: int,
    mirror_design: MirrorL0Design,
    selected_axial_energy_per_charge_v: float,
    target_slow_kinetic_energy_per_charge_v: float,
    target_p2_reference_tangent_ratio: float,
    prism_bias_v_by_electrode_id: Mapping[int, float],
    stripe_bias_v_by_set_name: Mapping[str, float],
    numerics: TransportNumerics,
    stage_a_maximum_reduced_time_mm_per_sqrt_v: float,
    stage_b_maximum_reduced_time_mm_per_sqrt_v: float,
) -> TwoPrismSegmentedVoltagePairDiagnostic:
    """Evaluate one explicit P1/P2 pair through the manufactured 2-D topology.

    Both maximum-reduced-time inputs are absolute terminal coordinates in the
    propagator's reduced-time variable, not per-stage durations.  The input
    The source must lie outside every hard-boundary band.  Its measured x/vx
    coordinates are retained in the returned projection diagnostic, while
    only y/z coordinates and momenta enter this two-dimensional propagation.
    """
    initial = _reduced_state_from_project_source(
        source, particle_mass_th=particle_mass_th, charge_state=charge_state,
    )
    if initial.u_z_sqrt_v >= 0.0:
        raise CandidateContractError("P1/P2 source must initially travel toward negative project z")
    selected_energy = _finite_value(
        selected_axial_energy_per_charge_v, "selected axial energy",
    )
    target_slow_energy = _finite_value(
        target_slow_kinetic_energy_per_charge_v, "target slow energy",
    )
    if selected_energy <= 0.0 or target_slow_energy <= 0.0:
        raise CandidateContractError("selected axial and target slow energies must be positive")
    charge_sign = 1 if charge_state > 0 else -1
    transverse_energy_ev = kinetic_energy_ev(
        particle_mass_th, source.velocity_mm_per_us[0] * 1000.0, 0.0, 0.0,
    )
    transverse_projection = TwoPrismTransverseProjectionDiagnostic(
        source.position_mm[0],
        source.velocity_mm_per_us[0],
        transverse_energy_ev,
        transverse_energy_ev / abs(charge_state),
    )
    mirror_potential = lambda z: axial_potential_v(z, mirror_design)
    mirror_gradient = lambda z: axial_potential_gradient_v_per_mm(z, mirror_design)
    regions = build_two_prism_segmented_potential_regions(
        contract,
        prism_bias_v_by_electrode_id=prism_bias_v_by_electrode_id,
        stripe_bias_v_by_set_name=stripe_bias_v_by_set_name,
    )
    source_regions = tuple(
        region.name for region in regions if region.contains(initial.y_mm, initial.z_mm)
    )
    if source_regions:
        raise CandidateContractError(
            "P1/P2 source must be outside every prism and Stripe potential band; "
            f"active at source: {', '.join(source_regions)}"
        )
    p1_id, p1_target = _p1_interface_target(contract)
    p2_id, target_y, low_field_target = _p2_handoff_authority(contract)
    target_tangent_ratio = _finite_value(
        target_p2_reference_tangent_ratio, "target P2 low-field reference tangent ratio",
    )
    if target_tangent_ratio <= 0.0:
        raise CandidateContractError("target Stripe-entrance tangent ratio must be positive")

    try:
        stage_a = propagate_segmented_hamiltonian(
            initial,
            charge_sign=charge_sign,
            mirror_potential_v=mirror_potential,
            mirror_gradient_v_per_mm=mirror_gradient,
            potential_regions=regions,
            stop_targets=(p1_target,),
            maximum_reduced_time_mm_per_sqrt_v=stage_a_maximum_reduced_time_mm_per_sqrt_v,
            numerics=numerics,
        )
    except TransportError as error:
        raise CandidateContractError(
            f"stage A segmented transport failed: {error}"
        ) from error
    if (
        stage_a.status != "stopped"
        or not stage_a.events
        or stage_a.events[-1].name != p1_target.name
    ):
        raise CandidateContractError("stage A did not reach the P1 post-prism interface")
    stage_b_end = _finite_value(
        stage_b_maximum_reduced_time_mm_per_sqrt_v,
        "stage B absolute maximum reduced time",
    )
    if stage_b_end <= stage_a.final_state.reduced_time_mm_per_sqrt_v:
        raise CandidateContractError(
            "stage B absolute maximum reduced time must follow the stage A terminal time"
        )
    p1_pairs = _complete_region_passes(stage_a.events, f"prism_{p1_id}")
    stage_a_interfaces = [event for event in stage_a.events if event.kind == "interface"]
    if (
        len(p1_pairs) != 1
        or any(event.region_name != f"prism_{p1_id}" for event in stage_a_interfaces)
        or p1_pairs[0][0].state_before.u_z_sqrt_v >= 0.0
        or p1_pairs[0][1].state_after.u_z_sqrt_v >= 0.0
        or stage_a.final_state.u_z_sqrt_v >= 0.0
    ):
        raise CandidateContractError("stage A needs one P1 pass and a negative-z interface exit")

    try:
        positive_stripes = tuple(
            f"stripe_{item.electrode_id}_{item.set_name}"
            for item in dual_stripe_physical_instance_topology(contract)
            if item.reflection_axis_sign == 1
        )
        stage_b = propagate_segmented_hamiltonian(
            stage_a.final_state,
            charge_sign=charge_sign,
            mirror_potential_v=mirror_potential,
            mirror_gradient_v_per_mm=mirror_gradient,
            potential_regions=regions,
            stop_targets=(low_field_target,),
            maximum_reduced_time_mm_per_sqrt_v=stage_b_end,
            numerics=numerics,
        )
    except TransportError as error:
        raise CandidateContractError(
            f"stage B segmented transport failed: {error}"
        ) from error
    if (
        stage_b.status != "stopped"
        or not stage_b.events
        or stage_b.events[-1].name != low_field_target.name
    ):
        raise CandidateContractError("stage B did not reach the P2-shield low-field reference")
    interfaces = [event for event in stage_b.events if event.kind == "interface"]
    if any(event.transmitted is not True for event in interfaces):
        raise CandidateContractError("stage B contains a reflected or unresolved hard-boundary crossing")
    if any(event.region_name == f"prism_{p1_id}" for event in interfaces):
        raise CandidateContractError("stage B re-enters P1 instead of following the P1-mirror-P2 path")
    p2_pairs = _complete_region_passes(stage_b.events, f"prism_{p2_id}")
    if (
        len(p2_pairs) != 1
        or p2_pairs[0][0].state_before.u_z_sqrt_v <= 0.0
        or p2_pairs[0][1].state_after.u_z_sqrt_v <= 0.0
    ):
        raise CandidateContractError("stage B needs one positive-z transmitted P2 pass")

    allowed_stage_b_regions = {f"prism_{p2_id}"}
    if any(event.region_name not in allowed_stage_b_regions for event in interfaces):
        raise CandidateContractError(
            "stage B contains an interface outside the negative-mirror/P2/reference path"
        )
    if interfaces[0].region_name != f"prism_{p2_id}" or interfaces[0].entering is not True:
        raise CandidateContractError("P2 entry must be the first hard-boundary event after the negative mirror")
    if (
        any(event.region_name != f"prism_{p2_id}" for event in interfaces)
        or p2_pairs[0][1].state_after.reduced_time_mm_per_sqrt_v
        >= stage_b.final_state.reduced_time_mm_per_sqrt_v
        or stage_b.final_state.u_z_sqrt_v <= 0.0
        or stage_b.final_state.u_y_sqrt_v <= 0.0
    ):
        raise CandidateContractError(
            "stage B must complete P2 then cross the positive-z, positive-y low-field reference"
        )

    stage_c = _propagate_to_first_positive_mirror_turn(
        stage_b.final_state,
        charge_sign=charge_sign,
        mirror_potential_v=mirror_potential,
        mirror_gradient_v_per_mm=mirror_gradient,
        potential_regions=regions,
        maximum_reduced_time_mm_per_sqrt_v=stage_b_end,
        numerics=numerics,
    )
    if (
        stage_c.status != "stopped_at_positive_mirror_turn"
        or stage_c.final_state.z_mm <= 0.0
        or stage_c.final_state.u_y_sqrt_v <= 0.0
        or abs(stage_c.final_state.u_z_sqrt_v) > numerics.momentum_tolerance_sqrt_v
    ):
        raise CandidateContractError("stage C did not localize the outbound positive-mirror turn")
    stage_c_interfaces = [event for event in stage_c.events if event.kind == "interface"]
    if stage_c_interfaces:
        raise CandidateContractError(
            "stage C must reach the positive-mirror turn before every Stripe interface"
        )
    stage_d = _propagate_to_first_complete_positive_stripe_pass(
        stage_c.final_state,
        charge_sign=charge_sign,
        mirror_potential_v=mirror_potential,
        mirror_gradient_v_per_mm=mirror_gradient,
        potential_regions=regions,
        positive_stripe_region_names=positive_stripes,
        maximum_reduced_time_mm_per_sqrt_v=stage_b_end,
        numerics=numerics,
    )
    if stage_d.status != "stopped_after_first_positive_stripe_pass":
        raise CandidateContractError("stage D did not complete the first post-turn Stripe pass")
    stripe_pairs = tuple(
        pair
        for name in positive_stripes
        for pair in _complete_region_passes(stage_d.events, name)
    )
    if len(stripe_pairs) != 1:
        raise CandidateContractError("stage D needs exactly one complete first positive-Stripe pass")
    stripe_entry = min(stripe_pairs, key=lambda pair: pair[0].state_before.reduced_time_mm_per_sqrt_v)[0]

    source_slow = initial.u_y_sqrt_v**2
    source_axial = initial.u_z_sqrt_v**2 + charge_sign * mirror_potential(initial.z_mm)
    source_energy = TwoPrismSourceEnergyDiagnostic(
        source_slow,
        target_slow_energy,
        source_axial,
        selected_energy,
        source_slow - target_slow_energy,
        source_axial - selected_energy,
    )
    p1_state = _project_state_from_reduced(
        p1_pairs[0][1].state_after,
        particle_mass_th=particle_mass_th,
        charge_state=charge_state,
    )
    reference_state = _project_state_from_reduced(
        stage_b.final_state,
        particle_mass_th=particle_mass_th,
        charge_state=charge_state,
    )
    turn_state = _project_state_from_reduced(
        stage_c.final_state,
        particle_mass_th=particle_mass_th,
        charge_state=charge_state,
    )
    # These x=0 lifts exist only to reuse the established y/angle residual
    # calculation.  The returned transport remains explicitly two-dimensional.
    observation = TwoPrismTransportObservation(
        source, p1_state, reference_state, turn_state, True,
    )
    residuals = prism_handoff_residuals(
        observation,
        target_positive_mirror_turn_y_mm=target_y,
        target_tangent_ratio_vy_over_vz=target_tangent_ratio,
    )
    if tuple(name for name, _value in residuals) != (
        "P1_P2_positive_mirror_turn_y_mm",
        "P1_P2_P2_shield_low_field_signed_vy_over_vz",
    ):
        raise CandidateContractError("P1/P2 residual names differ from the handoff authority")
    return TwoPrismSegmentedVoltagePairDiagnostic(
        qualification="projected_yz_seed_only",
        source=source,
        transverse_projection=transverse_projection,
        source_energy_consistency=source_energy,
        stage_a_p1_to_interface=stage_a,
        stage_b_p1_exit_to_p2_low_field_reference=stage_b,
        inferred_negative_mirror_pre_reflection=(
            stage_a.final_state.u_z_sqrt_v < 0.0
            and p2_pairs[0][0].state_before.u_z_sqrt_v > 0.0
        ),
        stripe_entrance_region_name=stripe_entry.region_name,
        voltage_residuals=residuals,
        limitations=(
            "the smooth positive-mirror turn is localized from the first outbound z-momentum sign change",
            "grounded-shield solid collisions outside the P1 slot plane are not represented",
            "the y-z projection does not validate x focusing, transverse wall clearance, or electrode collision",
            "projected x=0 lifts used for turn-y/reference-angle residuals are not predicted finite-3D terminal states",
            "the source must be outside every potential band and initially travel toward negative project z",
            "the source-energy checks are upstream diagnostics, not P1/P2 voltage residuals",
            "Stripe time-platform and complete-analyser K acceptance are not evaluated",
        ),
        stage_c_low_field_reference_to_positive_mirror_turn=stage_c,
        stage_d_positive_mirror_turn_to_first_stripe_pass=stage_d,
        p2_shield_low_field_reference_state=reference_state,
        positive_mirror_turn_state=turn_state,
        derived_positive_mirror_turn_z_mm=turn_state.position_mm[2],
    )
