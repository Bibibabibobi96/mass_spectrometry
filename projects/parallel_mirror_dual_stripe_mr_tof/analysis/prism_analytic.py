"""Solver-neutral hard-boundary seeds for the two pre-Stripe prisms.

The project convention is x transverse, y drift, z reflection.  A positive
local prism angle is a rotation from -z towards +y, so its unit direction in
the y-z section is ``(+sin(theta), -cos(theta))``.  This is deliberately an
L0 seed: the finite triangular electrodes and their grounded shields must be
corrected with a three-dimensional unit-field trajectory calculation.

The direct P1-to-P2 construction below is retained as a generic component
regression only.  It is not applicable to the manufactured MR-TOF path,
which contains a distributed-field negative-mirror pre-reflection between
P1 and P2.  That path first needs a solver-neutral mirror/Stripe propagation
model and must then be corrected by finite-three-dimensional trajectory
shooting.  The triangular primitive in this module supplies only one local
hard-boundary interaction, not that complete transport solution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_l0 import (
    ray_segment_intersection_yz,
)


class PrismAnalyticError(ValueError):
    """Raised for an incomplete or nonphysical two-prism L0 contract."""


@dataclass(frozen=True)
class TriangularHardBoundaryTrace:
    """One solver-neutral interaction with a triangular potential region.

    Positions are project-frame ``(y, z)`` millimetres.  Kinetic energies are
    volts per absolute elementary charge; ``charge_sign`` is therefore the
    only charge quantity needed by the geometric ray law, and mass cancels.
    ``exit_*`` identifies the first inside-to-outside face attempted, even
    when that boundary reflects the ray back into the prism.
    """

    status: str
    charge_sign: int
    prism_bias_v: float
    entry_point_yz_mm: tuple[float, float]
    entry_edge_index: int
    exit_point_yz_mm: tuple[float, float] | None
    exit_edge_index: int | None
    incident_unit_direction_yz: tuple[float, float]
    inside_unit_direction_yz: tuple[float, float] | None
    resulting_unit_direction_yz: tuple[float, float]
    incident_kinetic_energy_per_charge_v: float
    inside_kinetic_energy_per_charge_v: float | None
    resulting_kinetic_energy_per_charge_v: float
    hamiltonian_residual_per_charge_v: float


def _unit_yz_pair(y: float, z: float, label: str) -> tuple[float, float]:
    magnitude = math.hypot(y, z)
    if not math.isfinite(magnitude) or magnitude <= 0.0:
        raise PrismAnalyticError(f"{label} must be finite and nonzero")
    return y / magnitude, z / magnitude


def _triangle_vertices(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise PrismAnalyticError("hard-boundary prism must have exactly three y-z vertices")
    vertices = tuple(_point_yz(vertex, "hard-boundary prism vertex") for vertex in value)
    twice_area = sum(
        start[0] * end[1] - start[1] * end[0]
        for start, end in zip(vertices, vertices[1:] + vertices[:1])
    )
    scale = max(1.0, *(abs(coordinate) for vertex in vertices for coordinate in vertex))
    if abs(twice_area) <= 64.0 * math.ulp(scale * scale):
        raise PrismAnalyticError("hard-boundary prism triangle is degenerate")
    return vertices


def _edge_frame(
    vertices: tuple[tuple[float, float], ...], edge_index: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    start, end = vertices[edge_index], vertices[(edge_index + 1) % 3]
    tangent = _unit_yz_pair(end[0] - start[0], end[1] - start[1], "triangle edge")
    twice_area = sum(
        left[0] * right[1] - left[1] * right[0]
        for left, right in zip(vertices, vertices[1:] + vertices[:1])
    )
    orientation = 1.0 if twice_area > 0.0 else -1.0
    inward = (-orientation * tangent[1], orientation * tangent[0])
    return tangent, inward


def _first_triangle_edge_hit(
    origin: tuple[float, float],
    direction: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
    *,
    excluded_edge: int | None = None,
) -> tuple[tuple[float, float], int]:
    hits: list[tuple[float, float, int, tuple[float, float]]] = []
    coordinate_scale = max(1.0, *(abs(value) for point in vertices for value in point))
    distance_tolerance = 128.0 * math.ulp(coordinate_scale)
    for edge_index, (start, end) in enumerate(zip(vertices, vertices[1:] + vertices[:1])):
        if edge_index == excluded_edge:
            continue
        edge = (end[0] - start[0], end[1] - start[1])
        denominator = direction[0] * edge[1] - direction[1] * edge[0]
        offset = (start[0] - origin[0], start[1] - origin[1])
        collinearity = offset[0] * direction[1] - offset[1] * direction[0]
        if abs(denominator) <= distance_tolerance and abs(collinearity) <= distance_tolerance:
            raise PrismAnalyticError("ray is collinear with a triangular prism face")
        result = ray_segment_intersection_yz(origin, direction, start, end)
        if result is None:
            continue
        ray_t, segment_fraction = result
        point = (origin[0] + ray_t * direction[0], origin[1] + ray_t * direction[1])
        hits.append((ray_t, segment_fraction, edge_index, point))
    if not hits:
        raise PrismAnalyticError("ray does not meet a forward triangular prism face")
    hits.sort(key=lambda item: item[0])
    first = hits[0]
    if first[1] <= 1.0e-10 or first[1] >= 1.0 - 1.0e-10:
        raise PrismAnalyticError("ray meets a triangular prism vertex; the active face is ambiguous")
    if len(hits) > 1 and abs(hits[1][0] - first[0]) <= distance_tolerance:
        raise PrismAnalyticError("ray meets two triangular prism faces simultaneously")
    return first[3], first[2]


def _potential_step(
    reduced_momentum: tuple[float, float],
    kinetic_energy_per_charge_v: float,
    tangent: tuple[float, float],
    forward_normal: tuple[float, float],
    signed_potential_change_v: float,
) -> tuple[bool, tuple[float, float], float]:
    next_energy = kinetic_energy_per_charge_v - signed_potential_change_v
    tangent_component = sum(left * right for left, right in zip(reduced_momentum, tangent))
    normal_energy = next_energy - tangent_component * tangent_component
    scale = max(1.0, abs(kinetic_energy_per_charge_v), abs(next_energy), tangent_component * tangent_component)
    tolerance = 128.0 * math.ulp(scale)
    if next_energy <= 0.0 or normal_energy <= tolerance:
        incoming_normal = sum(left * right for left, right in zip(reduced_momentum, forward_normal))
        reflected = tuple(
            value - 2.0 * incoming_normal * normal
            for value, normal in zip(reduced_momentum, forward_normal)
        )
        return False, reflected, kinetic_energy_per_charge_v
    transmitted = tuple(
        tangent_component * axis + math.sqrt(normal_energy) * normal
        for axis, normal in zip(tangent, forward_normal)
    )
    return True, transmitted, next_energy


def trace_triangular_hard_boundary_prism(
    triangle_yz_mm: Any,
    ray_origin_yz_mm: Any,
    incident_direction_yz: Any,
    incident_kinetic_energy_per_charge_v: float,
    prism_bias_v: float,
    *,
    charge_sign: int,
) -> TriangularHardBoundaryTrace:
    """Trace the first entry and exit of a triangular hard-boundary prism.

    The potential outside the triangle is zero and the potential inside is
    ``prism_bias_v``.  At each face the reduced tangential momentum
    ``sqrt(K/|q|) * direction`` is conserved; its normal component is obtained
    from energy conservation.  A forbidden normal component produces a
    specular electrostatic reflection report rather than a fabricated ray.
    Vertex hits, face-collinear rays and tangential incidence fail closed.
    """
    vertices = _triangle_vertices(triangle_yz_mm)
    origin = _point_yz(ray_origin_yz_mm, "hard-boundary ray origin")
    incident = _unit_yz(incident_direction_yz, "hard-boundary incident direction")
    energy = _number(incident_kinetic_energy_per_charge_v, "incident kinetic energy per charge")
    bias = _number(prism_bias_v, "prism bias")
    if energy <= 0.0:
        raise PrismAnalyticError("incident kinetic energy per charge must be positive")
    if charge_sign not in (-1, 1) or isinstance(charge_sign, bool):
        raise PrismAnalyticError("charge_sign must be +1 or -1")
    entry_point, entry_edge = _first_triangle_edge_hit(origin, incident, vertices)
    entry_tangent, entry_inward = _edge_frame(vertices, entry_edge)
    incident_normal = sum(value * normal for value, normal in zip(incident, entry_inward))
    if incident_normal <= 128.0 * math.ulp(1.0):
        raise PrismAnalyticError("ray is tangential to or leaves the selected entry face")
    incident_momentum = tuple(math.sqrt(energy) * value for value in incident)
    entered, inside_momentum, inside_energy = _potential_step(
        incident_momentum, energy, entry_tangent, entry_inward, charge_sign * bias,
    )
    if not entered:
        reflected = _unit_yz_pair(*inside_momentum, "entry-reflected direction")
        hamiltonian_residual = sum(value * value for value in inside_momentum) - energy
        return TriangularHardBoundaryTrace(
            "reflected_at_entry", charge_sign, bias, entry_point, entry_edge, None, None,
            incident, None, reflected, energy, None, energy, hamiltonian_residual,
        )
    inside_direction = _unit_yz_pair(*inside_momentum, "inside-prism direction")
    exit_point, exit_edge = _first_triangle_edge_hit(
        entry_point, inside_direction, vertices, excluded_edge=entry_edge,
    )
    exit_tangent, exit_inward = _edge_frame(vertices, exit_edge)
    exit_outward = (-exit_inward[0], -exit_inward[1])
    if sum(value * normal for value, normal in zip(inside_direction, exit_outward)) <= 128.0 * math.ulp(1.0):
        raise PrismAnalyticError("inside ray is tangential to or enters the selected exit face")
    exited, result_momentum, result_energy = _potential_step(
        inside_momentum, inside_energy, exit_tangent, exit_outward, -charge_sign * bias,
    )
    result_direction = _unit_yz_pair(*result_momentum, "hard-boundary result direction")
    status = "transmitted" if exited else "internally_reflected_at_first_exit"
    result_potential = 0.0 if exited else bias
    hamiltonian_residual = sum(value * value for value in result_momentum) + charge_sign * result_potential - energy
    return TriangularHardBoundaryTrace(
        status, charge_sign, bias, entry_point, entry_edge, exit_point, exit_edge,
        incident, inside_direction, result_direction, energy, inside_energy,
        result_energy, hamiltonian_residual,
    )


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise PrismAnalyticError(f"{label} must be a finite number")
    return float(value)


def _point_yz(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PrismAnalyticError(f"{label} must be a [y, z] point")
    return _number(value[0], label), _number(value[1], label)


def hard_boundary_bias_v(total_energy_ev: float, alpha_deg: float, beta_deg: float) -> float:
    """Return the exact 90-degree hard-boundary prism bias in volts.

    This is the theory document's ``v = w0 cos(a+b) sin(b-a)`` for a singly
    charged reference ion.  Energy is total kinetic energy at the prism, not
    an axial or drift component.
    """
    energy = _number(total_energy_ev, "total prism kinetic energy")
    if energy <= 0.0:
        raise PrismAnalyticError("total prism kinetic energy must be positive")
    alpha = math.radians(_number(alpha_deg, "prism entry angle"))
    beta = math.radians(_number(beta_deg, "prism exit angle"))
    return energy * math.cos(alpha + beta) * math.sin(beta - alpha)


def nominal_stripe_injection_angle_deg(
    kappa_at_nominal_turn: float,
    drift_length_l_mm: float,
    axial_width_w_mm: float,
    oscillation_count: int,
) -> float:
    """Return the L0 nominal Stripe entrance angle in degrees.

    The dual-Stripe/adiabatic-drift theory gives
    ``tan(theta0) = kappa(1) L / (K W_z)`` when ``W_z`` is the axial width.
    ``L`` is the named slow-drift length and ``W_z`` is the mirror-derived
    axial width of the particular Candidate; neither may silently inherit a
    published Astral reference value.  A finite mathematical angle does not
    by itself qualify a large-angle ray for the adiabatic approximation.
    """
    kappa = _number(kappa_at_nominal_turn, "kappa(1)")
    length = _number(drift_length_l_mm, "slow-drift length L")
    width = _number(axial_width_w_mm, "axial width W")
    oscillation_count = _number(oscillation_count, "drift period ratio K")
    if oscillation_count <= 0:
        raise PrismAnalyticError("drift period ratio K must be positive")
    if kappa <= 0.0 or length <= 0.0 or width <= 0.0:
        raise PrismAnalyticError("kappa(1), L, and W must be positive")
    tangent = kappa * length / (oscillation_count * width)
    return math.degrees(math.atan(tangent))


def contract_nominal_stripe_injection_angle_deg(contract: dict[str, Any]) -> float:
    """Resolve a completed project L0 Stripe target, otherwise fail closed.

    The analytic prism seed may consume this result only after the dual-Stripe
    inverse solve has published its own values and provenance.  A CAD length
    or an Astral-reference number is deliberately not a fallback.
    """
    model = contract.get("dual_stripe_l0")
    if not isinstance(model, dict) or model.get("status") != "joint_l0_l1_candidate":
        raise PrismAnalyticError("dual_stripe_l0 must be a completed coupled mirror-Stripe L0/L1 candidate before deriving the Stripe entrance angle")
    receipts = model.get("source_receipts")
    if not isinstance(receipts, dict) or not all(isinstance(receipts.get(key), str) and receipts[key] for key in (
        "joint_action_period_l1_sha256", "psi_kappa_integral_sha256", "joint_residual_report_sha256",
    )):
        raise PrismAnalyticError("dual_stripe_l0 requires nonempty joint-period, kappa, and residual receipt identities")
    nominal = contract.get("nominal")
    if not isinstance(nominal, dict):
        raise PrismAnalyticError("nominal contract is required")
    return nominal_stripe_injection_angle_deg(
        _number(model.get("nominal_kappa_1"), "dual_stripe_l0.nominal_kappa_1"),
        _number(model.get("drift_length_L_mm"), "dual_stripe_l0.drift_length_L_mm"),
        _number(model.get("axial_width_W_mm"), "dual_stripe_l0.axial_width_W_mm"),
        resolve_drift_phase_contract(contract).target_period_ratio,
    )


def hard_boundary_exit_angle_deg(total_energy_ev: float, alpha_deg: float, bias_v: float) -> float:
    """Invert the exact hard-boundary law on the continuous small-angle branch."""
    energy = _number(total_energy_ev, "total prism kinetic energy")
    if energy <= 0.0:
        raise PrismAnalyticError("total prism kinetic energy must be positive")
    alpha = math.radians(_number(alpha_deg, "prism entry angle"))
    bias = _number(bias_v, "prism bias")
    argument = math.sin(2.0 * alpha) + 2.0 * bias / energy
    if not -1.0 <= argument <= 1.0:
        raise PrismAnalyticError("prism bias is outside the real hard-boundary transmission branch")
    beta = 0.5 * math.asin(argument)
    return math.degrees(beta)


def hard_boundary_bias_correction_v(
    total_energy_ev: float,
    actual_exit_angle_deg: float,
    target_exit_angle_deg: float,
) -> float:
    """Return the exact fixed-entry-angle bias correction on one branch.

    Subtracting the two hard-boundary identities
    ``2 V / E = sin(2 beta) - sin(2 alpha)`` eliminates the unchanged entry
    angle ``alpha``.  The two beta values must use the same prism-local axis
    and rotation convention; project-frame ``atan(v_y/v_z)`` values may only
    be supplied directly when that convention is aligned with the declared
    exit reference axis.

    This is an analytic P2 proposal, not proof that the corrected ray still
    intersects the same exit face or preserves the required instrument
    topology.  Callers must re-propagate and reject non-transmitted proposals.
    """
    energy = _number(total_energy_ev, "total prism kinetic energy")
    if energy <= 0.0:
        raise PrismAnalyticError("total prism kinetic energy must be positive")
    actual = math.radians(_number(actual_exit_angle_deg, "actual prism exit angle"))
    target = math.radians(_number(target_exit_angle_deg, "target prism exit angle"))
    return 0.5 * energy * (math.sin(2.0 * target) - math.sin(2.0 * actual))


def hard_boundary_bias_for_face_order_and_target_direction_v(
    triangle_yz_mm: Any,
    incident_direction_yz: Any,
    target_exit_direction_yz: Any,
    incident_kinetic_energy_per_charge_v: float,
    *,
    entry_edge_index: int,
    exit_edge_index: int,
    charge_sign: int,
) -> float:
    """Solve one triangular-prism bias without an angle convention.

    The selected entry and exit faces define their own tangent/normal frames.
    Entry-face tangential momentum and exit-face tangential momentum are both
    conserved.  Eliminating the unknown inside direction gives the required
    entry-normal momentum and therefore the prism potential exactly for the
    ideal constant-potential triangle.

    The caller must subsequently trace the ray and verify that it really uses
    the selected face order.  This function deliberately does not turn a
    different face intersection or a blocked ray into a voltage solution.
    """
    vertices = _triangle_vertices(triangle_yz_mm)
    if type(entry_edge_index) is not int or type(exit_edge_index) is not int:
        raise PrismAnalyticError("entry and exit edge indices must be integers")
    if not 0 <= entry_edge_index < 3 or not 0 <= exit_edge_index < 3:
        raise PrismAnalyticError("entry and exit edge indices must lie in [0, 2]")
    if entry_edge_index == exit_edge_index:
        raise PrismAnalyticError("entry and exit edges must be distinct")
    if charge_sign not in (-1, 1) or isinstance(charge_sign, bool):
        raise PrismAnalyticError("charge_sign must be +1 or -1")
    energy = _number(
        incident_kinetic_energy_per_charge_v,
        "incident kinetic energy per charge",
    )
    if energy <= 0.0:
        raise PrismAnalyticError("incident kinetic energy per charge must be positive")
    incident = _unit_yz(incident_direction_yz, "hard-boundary incident direction")
    target = _unit_yz(target_exit_direction_yz, "hard-boundary target exit direction")
    entry_tangent, entry_inward = _edge_frame(vertices, entry_edge_index)
    exit_tangent, exit_inward = _edge_frame(vertices, exit_edge_index)
    exit_outward = (-exit_inward[0], -exit_inward[1])
    if sum(value * normal for value, normal in zip(incident, entry_inward)) <= 0.0:
        raise PrismAnalyticError("incident direction does not enter the selected entry face")
    if sum(value * normal for value, normal in zip(target, exit_outward)) <= 0.0:
        raise PrismAnalyticError("target direction does not leave the selected exit face")

    root_energy = math.sqrt(energy)
    entry_tangent_momentum = root_energy * sum(
        value * tangent for value, tangent in zip(incident, entry_tangent)
    )
    target_exit_tangent_momentum = root_energy * sum(
        value * tangent for value, tangent in zip(target, exit_tangent)
    )
    frame_coupling = sum(
        normal * tangent for normal, tangent in zip(entry_inward, exit_tangent)
    )
    scale = max(1.0, abs(entry_tangent_momentum), abs(target_exit_tangent_momentum))
    if abs(frame_coupling) <= 128.0 * math.ulp(scale):
        raise PrismAnalyticError("selected prism faces do not define a unique bias")
    entry_normal_inside = (
        target_exit_tangent_momentum
        - entry_tangent_momentum
        * sum(left * right for left, right in zip(entry_tangent, exit_tangent))
    ) / frame_coupling
    if entry_normal_inside <= 0.0:
        raise PrismAnalyticError(
            "target direction requires momentum toward the selected entry face"
        )
    inside_energy = entry_tangent_momentum**2 + entry_normal_inside**2
    return charge_sign * (energy - inside_energy)


def _unit_yz(value: Any, label: str) -> tuple[float, float]:
    y, z = _point_yz(value, label)
    magnitude = math.hypot(y, z)
    if magnitude <= 0.0:
        raise PrismAnalyticError(f"{label} must be nonzero")
    return y / magnitude, z / magnitude


def direction_between_project_points(start_yz_mm: Any, end_yz_mm: Any) -> tuple[float, float]:
    """Return the unit y-z direction from one physical hand-off to the next."""
    start_y, start_z = _point_yz(start_yz_mm, "ray start")
    end_y, end_z = _point_yz(end_yz_mm, "ray end")
    dy, dz = end_y - start_y, end_z - start_z
    return _unit_yz([dy, dz], "successive analytic prism reference points")


def local_angle_deg(reference_axis_yz: Any, ray_direction_yz: Any, positive_rotation: Any) -> float:
    """Return a ray angle in a prism's declared local orientation.

    CAD positions alone do not establish a prism's optical sign.  Each prism
    therefore declares its own local axial direction and whether increasing
    angle is clockwise or counter-clockwise in the project y-z section.
    """
    reference_y, reference_z = _unit_yz(reference_axis_yz, "prism local reference axis")
    ray_y, ray_z = _unit_yz(ray_direction_yz, "prism ray direction")
    cross = reference_y * ray_z - reference_z * ray_y
    dot = reference_y * ray_y + reference_z * ray_z
    angle = math.degrees(math.atan2(cross, dot))
    if positive_rotation == "clockwise_yz":
        return -angle
    if positive_rotation == "counterclockwise_yz":
        return angle
    raise PrismAnalyticError("prism positive_rotation must be clockwise_yz or counterclockwise_yz")


@dataclass(frozen=True)
class TwoPrismHardBoundarySeed:
    """Two uniquely constrained hard-boundary prism biases and phase-space rays."""

    total_kinetic_energy_ev: float
    prism_1_entry_angle_degrees: float
    prism_1_exit_angle_degrees: float
    prism_2_entry_angle_degrees: float
    prism_2_exit_angle_degrees: float
    prism_1_bias_v: float
    prism_2_bias_v: float
    prism_1_reference_yz_mm: tuple[float, float]
    prism_2_reference_yz_mm: tuple[float, float]
    stripe_entrance_yz_mm: tuple[float, float]

    def receipt(self) -> dict[str, Any]:
        return {"schema_version": 1, "status": "two_pre_stripe_prism_hard_boundary_l0_seed", **asdict(self)}


def derive_two_prism_hard_boundary_seed(contract: dict[str, Any]) -> TwoPrismHardBoundarySeed:
    """Derive a direct-path P1/P2 hard-boundary component seed.

    ``prism_transport.two_prism_injection_l0`` must provide four ordered y-z
    reference points and each prism's local axis/rotation.  The points are
    named physical hand-off sections, not
    free fit coordinates: source/focus, P1 effective plane, P2 effective
    plane, and the theory-derived Stripe entrance section.  Requiring all
    four prevents an underdetermined two-voltage problem from becoming a scan.
    A hardware path containing a mirror pre-reflection is rejected because a
    straight P1-to-P2 ray cannot represent its distributed-field dynamics.
    """
    block = contract.get("prism_transport")
    if not isinstance(block, dict):
        raise PrismAnalyticError("prism_transport is required")
    model = block.get("two_prism_injection_l0")
    if not isinstance(model, dict):
        raise PrismAnalyticError("two_prism_injection_l0 is required; two prism voltages are otherwise underdetermined")
    if model.get("status") != "geometry_constrained_hard_boundary_l0":
        raise PrismAnalyticError("two_prism_injection_l0 must declare geometry_constrained_hard_boundary_l0")
    if model.get("path_topology") != "direct_p1_to_p2_without_intervening_mirror":
        raise PrismAnalyticError(
            "direct hard-boundary P1/P2 construction requires an explicit no-intervening-mirror topology"
        )
    if model.get("prism_1_electrode_id") != 16 or model.get("prism_2_electrode_id") != 17:
        raise PrismAnalyticError("two-prism L0 must bind path-order P1=16 and P2=17")
    energy = _number(model.get("total_kinetic_energy_ev"), "two-prism total kinetic energy")
    source = _point_yz(model.get("source_focus_reference_yz_mm"), "source/focus reference")
    prism_1 = _point_yz(model.get("prism_1_effective_plane_yz_mm"), "P1 effective plane")
    prism_2 = _point_yz(model.get("prism_2_effective_plane_yz_mm"), "P2 effective plane")
    stripe = _point_yz(model.get("stripe_entrance_reference_yz_mm"), "Stripe entrance reference")
    source_to_p1 = direction_between_project_points(source, prism_1)
    p1_to_p2 = direction_between_project_points(prism_1, prism_2)
    p2_to_stripe = direction_between_project_points(prism_2, stripe)
    p1_axis = model.get("prism_1_local_reference_axis_yz")
    p2_axis = model.get("prism_2_local_reference_axis_yz")
    p1_rotation = model.get("prism_1_positive_rotation")
    p2_rotation = model.get("prism_2_positive_rotation")
    p1_entry = local_angle_deg(p1_axis, source_to_p1, p1_rotation)
    p1_exit = local_angle_deg(p1_axis, p1_to_p2, p1_rotation)
    p2_entry = local_angle_deg(p2_axis, p1_to_p2, p2_rotation)
    p2_exit = local_angle_deg(p2_axis, p2_to_stripe, p2_rotation)
    return TwoPrismHardBoundarySeed(
        total_kinetic_energy_ev=energy,
        prism_1_entry_angle_degrees=p1_entry,
        prism_1_exit_angle_degrees=p1_exit,
        prism_2_entry_angle_degrees=p2_entry,
        prism_2_exit_angle_degrees=p2_exit,
        prism_1_bias_v=hard_boundary_bias_v(energy, p1_entry, p1_exit),
        prism_2_bias_v=hard_boundary_bias_v(energy, p2_entry, p2_exit),
        prism_1_reference_yz_mm=prism_1,
        prism_2_reference_yz_mm=prism_2,
        stripe_entrance_yz_mm=stripe,
    )
