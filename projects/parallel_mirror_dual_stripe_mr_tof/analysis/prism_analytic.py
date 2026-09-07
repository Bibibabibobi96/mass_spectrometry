"""Solver-neutral hard-boundary seeds for the two pre-Stripe prisms.

The project convention is x transverse, y drift, z reflection.  A positive
local prism angle is a rotation from -z towards -y, so its unit direction in
the y-z section is ``(-sin(theta), -cos(theta))``.  This is deliberately an
L0 seed: the finite triangular electrodes and their grounded shields must be
corrected with a three-dimensional unit-field trajectory calculation.

It intentionally requires an intermediate hand-off point.  A source ray and
the desired Stripe entrance ray determine only the *sum* of two prism
deflections, not the two voltages individually.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


class PrismAnalyticError(ValueError):
    """Raised for an incomplete or nonphysical two-prism L0 contract."""


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
    ``sin(theta0) = kappa(1) L / (K W)``.  ``L`` is the named slow-drift
    length and ``W`` is the named axial width of the particular Candidate;
    neither may silently inherit a published Astral reference value.
    """
    kappa = _number(kappa_at_nominal_turn, "kappa(1)")
    length = _number(drift_length_l_mm, "slow-drift length L")
    width = _number(axial_width_w_mm, "axial width W")
    if not isinstance(oscillation_count, int) or isinstance(oscillation_count, bool) or oscillation_count <= 0:
        raise PrismAnalyticError("oscillation count K must be a positive integer")
    if kappa <= 0.0 or length <= 0.0 or width <= 0.0:
        raise PrismAnalyticError("kappa(1), L, and W must be positive")
    sine = kappa * length / (oscillation_count * width)
    if not 0.0 < sine < 1.0:
        raise PrismAnalyticError("kappa(1) L / (K W) must lie strictly between zero and one")
    return math.degrees(math.asin(sine))


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
        nominal.get("target_oscillation_count"),
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
    """Derive P1/P2 voltages from a complete geometric phase-space hand-off.

    ``prism_transport.two_prism_injection_l0`` must provide four ordered y-z
    reference points and each prism's local axis/rotation.  The points are
    named physical hand-off sections, not
    free fit coordinates: source/focus, P1 effective plane, P2 effective
    plane, and the theory-derived Stripe entrance section.  Requiring all
    four prevents an underdetermined two-voltage problem from becoming a scan.
    """
    block = contract.get("prism_transport")
    if not isinstance(block, dict):
        raise PrismAnalyticError("prism_transport is required")
    model = block.get("two_prism_injection_l0")
    if not isinstance(model, dict):
        raise PrismAnalyticError("two_prism_injection_l0 is required; two prism voltages are otherwise underdetermined")
    if model.get("status") != "geometry_constrained_hard_boundary_l0":
        raise PrismAnalyticError("two_prism_injection_l0 must declare geometry_constrained_hard_boundary_l0")
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
