"""Compile the MR-TOF geometry contract into solver-neutral primitives.

The output deliberately describes physical millimetre geometry, not SIMION PA
indices or any CAD application's private entities.  It is the single resolved
geometry that solver adapters must consume.  CAD evidence appears only as
explicit constraints already frozen in the project contract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    validate_detector_return_path,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_component_requirements import (
    build_two_zone_accelerator_requirements,
)
from projects.orthogonal_accelerator.simion.two_zone_candidate import (
    compile_closed_two_zone_accelerator,
)


@dataclass(frozen=True)
class Box:
    """Axis-aligned physical box in the documented project frame, in mm."""

    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.z0, self.x1, self.y1, self.z1]


@dataclass(frozen=True)
class DualStripePhysicalInstance:
    """One physical member of a shared-bias theoretical Stripe response."""

    electrode_id: int
    set_name: str
    reflection_axis_sign: int


@dataclass(frozen=True)
class DualStripeNativeEdgeEvaluators:
    """Exact native edge functions for one physical +/-z Stripe instance."""

    set_name: str
    reflection_axis_sign: int
    active_y_span_mm: tuple[float, float]
    lower_z_mm: Callable[[float], float]
    upper_z_mm: Callable[[float], float]
    lower_dz_dy: Callable[[float], float]
    upper_dz_dy: Callable[[float], float]


DUAL_STRIPE_PHYSICAL_INSTANCE_INVARIANT = (
    DualStripePhysicalInstance(11, "set_1", 1),
    DualStripePhysicalInstance(12, "set_1", -1),
    DualStripePhysicalInstance(13, "set_2", 1),
    DualStripePhysicalInstance(14, "set_2", -1),
)


def dual_stripe_physical_instance_topology(
    contract: dict[str, Any],
) -> tuple[DualStripePhysicalInstance, ...]:
    """Resolve the single topology authority used by geometry and action paths."""
    try:
        mapping = contract["dual_stripe"]["theory_profile"]["path_length_mapping"]
        definitions = mapping["shared_bias_physical_instances"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("dual Stripe shared-bias physical topology is incomplete") from error
    if mapping.get("derivation") != "sum_reflection_axis_widths_of_shared_bias_physical_instances":
        raise CandidateContractError("dual Stripe total path must be derived from its physical instance topology")
    if not isinstance(definitions, list):
        raise CandidateContractError("dual Stripe physical topology must be a list")
    instances: list[DualStripePhysicalInstance] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            raise CandidateContractError("dual Stripe physical topology entries must be objects")
        electrode_id = definition.get("electrode_id")
        set_name = definition.get("set_name")
        reflection_axis_sign = definition.get("reflection_axis_sign")
        if (
            type(electrode_id) is not int
            or set_name not in {"set_1", "set_2"}
            or type(reflection_axis_sign) is not int
            or reflection_axis_sign not in {-1, 1}
        ):
            raise CandidateContractError("dual Stripe physical topology entry is invalid")
        instances.append(DualStripePhysicalInstance(electrode_id, set_name, reflection_axis_sign))
    if len({item.electrode_id for item in instances}) != len(instances):
        raise CandidateContractError("dual Stripe physical electrode IDs must be unique")
    expected_count = contract["dual_stripe"].get("physical_electrode_count")
    if expected_count != len(instances):
        raise CandidateContractError("dual Stripe physical topology count differs from the contract")
    if tuple(instances) != DUAL_STRIPE_PHYSICAL_INSTANCE_INVARIANT:
        raise CandidateContractError("dual Stripe physical topology differs from the stable project electrode invariant")
    for set_name in ("set_1", "set_2"):
        signs = sorted(item.reflection_axis_sign for item in instances if item.set_name == set_name)
        if signs != [-1, 1]:
            raise CandidateContractError(
                "each theoretical Stripe response must have one physical band on each reflection-axis side"
            )
    return tuple(instances)


def dual_stripe_total_path_scale(contract: dict[str, Any], set_name: str) -> float:
    """Derive total ``S_i`` as the sum of the two physical +/-z band widths."""
    if set_name not in {"set_1", "set_2"}:
        raise CandidateContractError(f"unknown dual Stripe set: {set_name}")
    return float(sum(
        item.set_name == set_name
        for item in dual_stripe_physical_instance_topology(contract)
    ))


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{name} must be numeric") from error
    if result != result or result in (float("inf"), float("-inf")):
        raise CandidateContractError(f"{name} must be finite")
    return result


def _basis(index: int, degree: int, parameter: float, knots: tuple[float, ...]) -> float:
    """Evaluate one Cox--de Boor B-spline basis function."""
    if degree == 0:
        is_final_knot = parameter == knots[-1] and knots[index + 1] == parameter
        return 1.0 if knots[index] <= parameter < knots[index + 1] or is_final_knot else 0.0
    left_denominator = knots[index + degree] - knots[index]
    right_denominator = knots[index + degree + 1] - knots[index + 1]
    left = 0.0 if left_denominator == 0.0 else (parameter - knots[index]) / left_denominator * _basis(index, degree - 1, parameter, knots)
    right = 0.0 if right_denominator == 0.0 else (knots[index + degree + 1] - parameter) / right_denominator * _basis(index + 1, degree - 1, parameter, knots)
    return left + right


def _bspline_edge(value: Any, name: str) -> tuple[tuple[float, ...], tuple[tuple[float, float], ...], int]:
    if not isinstance(value, dict) or value.get("basis") != "cubic_bspline":
        raise CandidateContractError(f"{name} must be a cubic B-spline theory edge")
    order = int(_number(value.get("order"), f"{name}.order"))
    if order != 4:
        raise CandidateContractError(f"{name} must have cubic order 4")
    knots = tuple(_number(item, f"{name}.knots") for item in value.get("knots", []))
    controls = tuple(
        (_number(item[0], f"{name}.control.y"), _number(item[1], f"{name}.control.z"))
        for item in value.get("control_points_yz_mm", [])
    )
    if len(controls) < order or len(knots) != len(controls) + order:
        raise CandidateContractError(f"{name} has an invalid B-spline knot/control count")
    if any(left > right for left, right in zip(knots, knots[1:])) or knots[order - 1] >= knots[-order]:
        raise CandidateContractError(f"{name} knots must define a nonzero nondecreasing domain")
    return knots, controls, order


def _evaluate_bspline(edge: tuple[tuple[float, ...], tuple[tuple[float, float], ...], int], parameter: float) -> tuple[float, float]:
    knots, controls, order = edge
    degree = order - 1
    lower, upper = knots[degree], knots[-order]
    if not lower <= parameter <= upper:
        raise CandidateContractError("B-spline parameter is outside its active knot domain")
    weights = tuple(_basis(index, degree, parameter, knots) for index in range(len(controls)))
    return tuple(sum(weight * point[axis] for weight, point in zip(weights, controls)) for axis in range(2))


def _edge_z_at_y(value: Any, name: str, y_mm: float) -> float:
    if not isinstance(value, dict):
        raise CandidateContractError(f"{name} must be an edge definition")
    if value.get("basis") == "constant_z":
        return _number(value.get("z_mm"), f"{name}.z_mm")
    edge = _bspline_edge(value, name)
    knots, _, order = edge
    lower, upper = knots[order - 1], knots[-order]
    start_y = _evaluate_bspline(edge, lower)[0]
    end_y = _evaluate_bspline(edge, upper)[0]
    ascending = end_y > start_y
    if not ascending and not end_y < start_y:
        raise CandidateContractError(f"{name} must vary monotonically in y")
    if not min(start_y, end_y) - 1e-6 <= y_mm <= max(start_y, end_y) + 1e-6:
        raise CandidateContractError(f"{name} does not cover the frozen Stripe y span")
    left, right = lower, upper
    for _ in range(64):
        middle = (left + right) / 2.0
        middle_y, _ = _evaluate_bspline(edge, middle)
        if (middle_y < y_mm) == ascending:
            left = middle
        else:
            right = middle
    return _evaluate_bspline(edge, (left + right) / 2.0)[1]


def _theory_profiles(stripe: dict[str, Any], y_span: tuple[float, float]) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Evaluate the native B-spline theory realization on a solver mesh."""
    theory = stripe.get("theory_profile")
    if not isinstance(theory, dict) or theory.get("generator") != "theory_bspline_parameterization":
        raise CandidateContractError("dual Stripe curves require the theory B-spline parameter contract")
    samples = int(_number(theory.get("sampling_per_nonzero_knot_span"), "dual_stripe.theory_profile.sampling_per_nonzero_knot_span"))
    if samples < 2:
        raise CandidateContractError("theory B-spline sampling must have at least two samples per knot span")
    edges = []
    for set_name in ("set_1", "set_2"):
        set_definition = theory.get(set_name)
        if not isinstance(set_definition, dict):
            raise CandidateContractError(f"dual_stripe.theory_profile.{set_name} is required")
        for edge_name in ("lower_edge", "upper_edge"):
            value = set_definition.get(edge_name)
            if not isinstance(value, dict):
                raise CandidateContractError(f"dual_stripe.theory_profile.{set_name}.{edge_name} is required")
            if value.get("basis") == "cubic_bspline":
                knots, _, order = _bspline_edge(value, f"dual_stripe.theory_profile.{set_name}.{edge_name}")
                spans = sum(right > left for left, right in zip(knots[order - 1:-order], knots[order:1 - order]))
                break
        else:
            spans = 1
        edges.append((set_definition, spans))
    point_count = max(spans for _, spans in edges) * samples + 1
    y_nodes = tuple(y_span[0] + (y_span[1] - y_span[0]) * index / (point_count - 1) for index in range(point_count))
    profiles = []
    for set_definition, _ in edges:
        profiles.extend(
            tuple((y_value, _edge_z_at_y(set_definition[edge_name], f"theory_profile.{edge_name}", y_value)) for y_value in y_nodes)
            for edge_name in ("lower_edge", "upper_edge")
        )
    return tuple(profiles)


def dual_stripe_width_at_y_mm(contract: dict[str, Any], set_name: str, y_mm: float) -> float:
    """Evaluate one frozen theory B-spline Stripe width at physical project ``y``.

    This is the sole analytic-width accessor for the resolved CAD-constrained
    Stripe geometry.  It deliberately evaluates the original B-spline edges,
    rather than interpolating a solver sampling polygon into a second shape
    contract.
    """
    if set_name not in {"set_1", "set_2"}:
        raise CandidateContractError("dual Stripe set name must be set_1 or set_2")
    stripe = contract.get("dual_stripe")
    if not isinstance(stripe, dict):
        raise CandidateContractError("dual Stripe contract is required")
    theory = stripe.get("theory_profile")
    if not isinstance(theory, dict) or theory.get("generator") != "theory_bspline_parameterization":
        raise CandidateContractError("dual Stripe width needs the theory B-spline parameter contract")
    y_span = tuple(_number(value, "dual_stripe.theory_profile.active_y_span_mm") for value in theory.get("active_y_span_mm", []))
    if len(y_span) != 2 or not y_span[0] < y_span[1]:
        raise CandidateContractError("dual Stripe active theory y span must be ordered")
    y_value = _number(y_mm, "dual Stripe physical y")
    if not y_span[0] <= y_value <= y_span[1]:
        raise CandidateContractError("dual Stripe physical y lies outside its frozen span")
    definition = theory.get(set_name)
    if not isinstance(definition, dict):
        raise CandidateContractError(f"dual Stripe theory profile {set_name} is required")
    lower = _edge_z_at_y(definition.get("lower_edge"), f"dual Stripe {set_name}.lower_edge", y_value)
    upper = _edge_z_at_y(definition.get("upper_edge"), f"dual Stripe {set_name}.upper_edge", y_value)
    width = upper - lower
    if width <= 0.0:
        raise CandidateContractError("dual Stripe B-spline geometry has non-positive physical width")
    return width


def compile_dual_stripe_width_evaluator(
    contract: dict[str, Any], set_name: str,
) -> Callable[[float], float]:
    """Compile the frozen native B-spline width into an exact fast evaluator.

    The returned callable consumes the same knots and control points as
    :func:`dual_stripe_width_at_y_mm`.  It does not interpolate a sampled
    polygon or create another geometry authority; SciPy merely evaluates the
    native spline basis and inverts its monotone ``y(parameter)`` relation in
    compiled numerical code.  This is suitable for optimizer inner loops,
    where repeatedly reparsing the contract and recursively evaluating every
    basis function is needlessly expensive.
    """
    edges = compile_dual_stripe_edge_evaluators(contract, set_name, 1)

    def width_at_y(y_mm: float) -> float:
        y_value = _number(y_mm, "dual Stripe physical y")
        if not edges.active_y_span_mm[0] <= y_value <= edges.active_y_span_mm[1]:
            raise CandidateContractError("dual Stripe physical y lies outside its frozen span")
        width = edges.upper_z_mm(y_value) - edges.lower_z_mm(y_value)
        if width <= 0.0:
            raise CandidateContractError("dual Stripe B-spline geometry has non-positive physical width")
        return width

    return width_at_y


def _compile_dual_stripe_native_edge(
    value: Any, name: str,
) -> tuple[Callable[[float], float], Callable[[float], float], tuple[float, float]]:
    """Compile one native edge as ``z(y)`` and its analytic ``dz/dy``."""
    if not isinstance(value, dict):
        raise CandidateContractError(f"{name} must be an edge definition")
    if value.get("basis") == "constant_z":
        constant = _number(value.get("z_mm"), f"{name}.z_mm")
        return (lambda _y: constant), (lambda _y: 0.0), (-math.inf, math.inf)

    knots, controls, order = _bspline_edge(value, name)
    degree = order - 1
    lower_parameter, upper_parameter = knots[degree], knots[-order]
    # Lazy import preserves the lightweight geometry-only import path.
    from scipy.interpolate import BSpline
    from scipy.optimize import brentq

    y_spline = BSpline(knots, tuple(point[0] for point in controls), degree, extrapolate=False)
    z_spline = BSpline(knots, tuple(point[1] for point in controls), degree, extrapolate=False)
    dy_spline = y_spline.derivative()
    dz_spline = z_spline.derivative()
    start_y = float(y_spline(lower_parameter))
    end_y = float(y_spline(upper_parameter))
    if start_y == end_y:
        raise CandidateContractError(f"{name} must vary monotonically in y")
    minimum_y, maximum_y = sorted((start_y, end_y))

    def parameter_at_y(y_mm: float) -> float:
        y_value = _number(y_mm, f"{name}.physical_y")
        if not minimum_y - 1e-6 <= y_value <= maximum_y + 1e-6:
            raise CandidateContractError(f"{name} does not cover the frozen Stripe y span")
        if y_value <= minimum_y:
            return lower_parameter if start_y < end_y else upper_parameter
        if y_value >= maximum_y:
            return upper_parameter if start_y < end_y else lower_parameter
        return brentq(
            lambda candidate: float(y_spline(candidate)) - y_value,
            lower_parameter,
            upper_parameter,
            xtol=1e-13,
            rtol=4.0 * math.ulp(1.0),
        )

    def z_at_y(y_mm: float) -> float:
        return float(z_spline(parameter_at_y(y_mm)))

    def dz_dy(y_mm: float) -> float:
        parameter = parameter_at_y(y_mm)
        dy_dt = float(dy_spline(parameter))
        dz_dt = float(dz_spline(parameter))
        scale = max(1.0, abs(dy_dt), abs(dz_dt))
        if abs(dy_dt) <= 128.0 * math.ulp(scale):
            raise CandidateContractError(f"{name} has no finite z(y) derivative")
        return dz_dt / dy_dt

    return z_at_y, dz_dy, (minimum_y, maximum_y)


def compile_dual_stripe_edge_evaluators(
    contract: dict[str, Any], set_name: str, reflection_axis_sign: int,
) -> DualStripeNativeEdgeEvaluators:
    """Compile exact native ``z(y)`` edges for one physical Stripe band.

    The positive instance follows the frozen native B-spline definitions.
    The negative instance is their exact project-``z`` reflection, so its
    lower edge is the reflected positive upper edge (and conversely).  No
    sampled polygon, bounding box, or independently entered mirror geometry
    participates.  The functions fail closed outside the active theory span;
    they do not extrapolate into the separate ``y=-2..0`` terminal-trim and
    mechanical bridge geometry.
    """
    if set_name not in {"set_1", "set_2"}:
        raise CandidateContractError("dual Stripe set name must be set_1 or set_2")
    if type(reflection_axis_sign) is not int or reflection_axis_sign not in {-1, 1}:
        raise CandidateContractError("dual Stripe reflection-axis sign must be +1 or -1")
    stripe = contract.get("dual_stripe")
    if not isinstance(stripe, dict):
        raise CandidateContractError("dual Stripe contract is required")
    theory = stripe.get("theory_profile")
    if not isinstance(theory, dict) or theory.get("generator") != "theory_bspline_parameterization":
        raise CandidateContractError("dual Stripe edges need the theory B-spline parameter contract")
    y_span_values = tuple(
        _number(value, "dual_stripe.theory_profile.active_y_span_mm")
        for value in theory.get("active_y_span_mm", [])
    )
    if len(y_span_values) != 2 or not y_span_values[0] < y_span_values[1]:
        raise CandidateContractError("dual Stripe active theory y span must be ordered")
    y_span = (y_span_values[0], y_span_values[1])
    definition = theory.get(set_name)
    if not isinstance(definition, dict):
        raise CandidateContractError(f"dual Stripe theory profile {set_name} is required")
    lower_z, lower_derivative, lower_domain = _compile_dual_stripe_native_edge(
        definition.get("lower_edge"), f"dual Stripe {set_name}.lower_edge",
    )
    upper_z, upper_derivative, upper_domain = _compile_dual_stripe_native_edge(
        definition.get("upper_edge"), f"dual Stripe {set_name}.upper_edge",
    )
    for domain in (lower_domain, upper_domain):
        if domain[0] > y_span[0] + 1e-6 or domain[1] < y_span[1] - 1e-6:
            raise CandidateContractError(f"dual Stripe {set_name} native edges do not cover the active y span")

    def active_y(y_mm: float) -> float:
        y_value = _number(y_mm, "dual Stripe physical y")
        if not y_span[0] <= y_value <= y_span[1]:
            raise CandidateContractError("dual Stripe native edge is outside its active theory y span")
        return y_value

    def positive_lower(y_mm: float) -> float:
        return lower_z(active_y(y_mm))

    def positive_upper(y_mm: float) -> float:
        return upper_z(active_y(y_mm))

    def positive_lower_derivative(y_mm: float) -> float:
        return lower_derivative(active_y(y_mm))

    def positive_upper_derivative(y_mm: float) -> float:
        return upper_derivative(active_y(y_mm))

    if reflection_axis_sign > 0:
        physical_lower = positive_lower
        physical_upper = positive_upper
        physical_lower_derivative = positive_lower_derivative
        physical_upper_derivative = positive_upper_derivative
    else:
        def physical_lower(y_mm: float) -> float:
            return -positive_upper(y_mm)

        def physical_upper(y_mm: float) -> float:
            return -positive_lower(y_mm)

        def physical_lower_derivative(y_mm: float) -> float:
            return -positive_upper_derivative(y_mm)

        def physical_upper_derivative(y_mm: float) -> float:
            return -positive_lower_derivative(y_mm)
    return DualStripeNativeEdgeEvaluators(
        set_name=set_name,
        reflection_axis_sign=reflection_axis_sign,
        active_y_span_mm=y_span,
        lower_z_mm=physical_lower,
        upper_z_mm=physical_upper,
        lower_dz_dy=physical_lower_derivative,
        upper_dz_dy=physical_upper_derivative,
    )


def compile_dual_stripe_path_length_evaluator(
    contract: dict[str, Any], set_name: str,
) -> Callable[[float], float]:
    """Compile the theory ``S_i(y)`` represented by one frozen profile.

    Geometry width and action path length are deliberately separate concepts.
    The action path scale is derived from the same shared-bias physical-instance
    topology that creates the mirrored electrode solids.
    """
    width_at_y = compile_dual_stripe_width_evaluator(contract, set_name)
    total_path_scale = dual_stripe_total_path_scale(contract, set_name)

    def path_length_at_y(y_mm: float) -> float:
        return total_path_scale * width_at_y(y_mm)

    return path_length_at_y


def _central_ground_polygons(stripe: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    """Resolve the complete Ion-Foil-2 body before its rectangular cuts.

    Native long-edge curves stop at y=-4, not at the part's positive end.
    The independent short cubic and terminal trim are explicit CAD features;
    neither extrapolating the long curve nor filling its bbox is valid.
    """
    definition = stripe.get("central_ground_profile")
    if not isinstance(definition, dict) or definition.get("generator") != "cad_bspline_body_outline":
        raise CandidateContractError("central ground requires its CAD B-spline body-outline contract")
    y_span = tuple(_number(value, "dual_stripe.central_ground_profile.y_span_mm") for value in definition.get("y_span_mm", []))
    if len(y_span) != 2 or not y_span[0] < y_span[1]:
        raise CandidateContractError("central-ground B-spline y span must be ordered")
    samples = int(_number(definition.get("sampling_per_nonzero_knot_span"), "central_ground_profile.sampling_per_nonzero_knot_span"))
    if samples < 2:
        raise CandidateContractError("central-ground B-spline sampling must have at least two samples per knot span")
    records = []
    for side in ("positive_x", "negative_x"):
        item = definition.get(side)
        if not isinstance(item, dict):
            raise CandidateContractError(f"central-ground {side} profile is required")
        x = tuple(_number(value, f"central_ground.{side}.x_mm") for value in item.get("x_mm", []))
        if len(x) != 2 or not x[0] < x[1] or (side == "positive_x" and x[0] != 0.0) or (side == "negative_x" and x[1] != 0.0):
            raise CandidateContractError("central ground must describe its whole body before the finite slot subtraction")
        lower = item.get("lower_edge")
        upper = item.get("upper_edge")
        for edge, label in ((lower, "lower_edge"), (upper, "upper_edge")):
            if not isinstance(edge, dict) or edge.get("basis") != "cubic_bspline":
                raise CandidateContractError(f"central_ground.{side}.{label} must be a B-spline")
        knots, _, order = _bspline_edge(lower, f"central_ground.{side}.lower_edge")
        spans = sum(right > left for left, right in zip(knots[order - 1:-order], knots[order:1 - order]))
        y_nodes = tuple(y_span[0] + (y_span[1] - y_span[0]) * index / (spans * samples) for index in range(spans * samples + 1))
        lower_points = tuple((y_value, _edge_z_at_y(lower, f"central_ground.{side}.lower_edge", y_value)) for y_value in y_nodes)
        upper_points = tuple((y_value, _edge_z_at_y(upper, f"central_ground.{side}.upper_edge", y_value)) for y_value in y_nodes)
        polygon = _polygon(lower_points, upper_points)
        records.append({"x": list(x), "polygon_yz_mm": [list(point) for point in polygon]})
    terminal = definition.get("terminal_profile")
    if not isinstance(terminal, dict):
        raise CandidateContractError("central ground requires its native short-curve and terminal profile")
    short_span = tuple(_number(value, "central ground terminal curve span") for value in terminal.get("curve_y_span_mm", []))
    body_span = stripe["y_span_mm"]
    if (
        len(short_span) != 2
        or not body_span[0] < short_span[0] < short_span[1] == y_span[0]
        or y_span[1] != body_span[1]
    ):
        raise CandidateContractError(
            "central ground terminal, short cubic, and long profile must be ordered in positive theory y"
        )
    short_y = tuple(short_span[0] + (short_span[1] - short_span[0]) * index / samples for index in range(samples + 1))
    short_edges = [tuple((y, _edge_z_at_y(terminal.get(edge), f"central_ground.terminal.{edge}", y)) for y in short_y)
                   for edge in ("lower_edge", "upper_edge")]
    body_x = [min(record["x"][0] for record in records), max(record["x"][1] for record in records)]
    records.extend((
        {"x": body_x, "polygon_yz_mm": [list(point) for point in _polygon(*short_edges)]},
        {"x": body_x, "polygon_yz_mm": _terminal_polygon(body_span[0], short_span[0], terminal.get("terminal_z_mm"))},
    ))
    top = max(point[1] for record in records for point in record["polygon_yz_mm"])
    return records, top


def _terminal_polygon(y_start: float, y_end: float, z_bounds: Any) -> list[list[float]]:
    """Return a native planar end feature, not a synthesized slot bridge."""
    if not isinstance(z_bounds, list) or len(z_bounds) != 2:
        raise CandidateContractError("native terminal feature requires its two z bounds")
    z0, z1 = (_number(value, "terminal z bound") for value in z_bounds)
    if not y_start < y_end or not z0 < z1:
        raise CandidateContractError("native terminal feature must have positive y-z area")
    return [[y_start, z0], [y_end, z0], [y_end, z1], [y_start, z1]]


def _polygon(lower: tuple[tuple[float, float], ...], upper: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    """Create an ordered y-z polygon from two non-crossing edge profiles."""
    if lower[0][0] != upper[0][0] or lower[-1][0] != upper[-1][0]:
        raise CandidateContractError("stripe edges must share y endpoints")
    # Linear interpolation is intentionally not used as an implicit geometry
    # rule: both curves must be sampled on the same y nodes in the contract.
    if tuple(point[0] for point in lower) != tuple(point[0] for point in upper):
        raise CandidateContractError("stripe edges must use the same sampled y nodes")
    if any(low[1] >= high[1] for low, high in zip(lower, upper)):
        raise CandidateContractError("stripe profile must have positive width everywhere")
    return lower + tuple(reversed(upper))


def _mirrored_polygon(polygon: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    return tuple((y, -z) for y, z in polygon)


def _strictly_inside_triangle(point: list[float], triangle: list[list[float]]) -> bool:
    """Return whether a y-z point lies strictly within a nondegenerate triangle."""
    if len(triangle) != 3:
        raise CandidateContractError("prism clearance contour must be triangular")
    signs = []
    for start, end in zip(triangle, triangle[1:] + triangle[:1]):
        signed_cross = ((end[0] - start[0]) * (point[1] - start[1])
                        - (end[1] - start[1]) * (point[0] - start[0]))
        signs.append(signed_cross)
    tolerance = 1e-9
    return all(value > tolerance for value in signs) or all(value < -tolerance for value in signs)


def _candidate_low_field_reference_section(
    contract: dict[str, Any],
    prism_electrodes: list[dict[str, Any]],
    prism_ground_shields: list[dict[str, Any]],
    stripe_records: list[dict[str, Any]],
    positive_mirror_inner_faces_z_mm: list[float],
) -> dict[str, Any]:
    """Derive one reference plane while leaving field flatness unqualified."""
    try:
        authority = contract["prism_transport"]["two_prism_injection_l0"][
            "low_field_reference_section"
        ]
        target_authority = contract["prism_transport"]["two_prism_injection_l0"][
            "low_field_angle_and_positive_mirror_turn_authority"
        ]
        prism_id = int(authority["second_prism_electrode_id"])
        shield_id = int(authority["ground_shield_id"])
        validation = authority["pa_field_plateau_validation"]
        target_turn_y = _number(
            target_authority["positive_mirror_turn_target_project_y_mm"],
            "positive-mirror-turn target y",
        )
        function_y_zero = _number(
            contract["dual_stripe_l0"]["theory_function_coordinate_registration"]
            ["function_y_zero_project_y_mm"],
            "Stripe function y origin",
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(
            "two-prism low-field reference-section authority is incomplete"
        ) from error
    if (
        authority.get("status")
        != "candidate_geometry_derived__pa_field_plateau_validation_pending"
        or authority.get("axis") != "z"
        or authority.get("interval_semantics") != "open"
        or authority.get("lower_boundary_rule")
        != "positive_z_edge_of_second_prism_ground_shield_clearance"
        or authority.get("upper_boundary_rule")
        != "minimum_of_ground_shield_cross_aperture_positive_z_edge_nearest_positive_stripe_terminal_surface_and_positive_grounded_mirror_inner_face"
        or authority.get("reference_plane_rule") != "midpoint_of_open_candidate_interval"
    ):
        raise CandidateContractError(
            "two-prism low-field reference section must remain a geometry-derived Candidate"
        )
    if (
        target_authority.get("status")
        != "derived_design_authority__pa_field_plateau_validation_pending"
        or target_authority.get("low_field_angle_event")
        != "first_positive_z_crossing_of_resolved_candidate_reference_plane_after_P2"
        or target_authority.get("positive_mirror_turn_event")
        != "first_u_z_zero_crossing_after_the_low_field_reference_plane"
        or target_turn_y != function_y_zero
    ):
        raise CandidateContractError(
            "two-prism targets must be the low-field angle and first positive-mirror-turn y"
        )
    if (
        not isinstance(validation, dict)
        or validation.get("required") is not True
        or validation.get("status") != "pending_user_threshold"
        or validation.get("maximum_field_plateau_variation") is not None
        or validation.get("validation_nodes_project_z_mm") is not None
    ):
        raise CandidateContractError(
            "low-field Candidate requires PA validation with user-owned threshold and nodes"
        )
    prisms = [item for item in prism_electrodes if item["id"] == prism_id]
    shields = [item for item in prism_ground_shields if item["id"] == shield_id]
    if len(prisms) != 1 or len(shields) != 1 or prisms[0]["station"] != shields[0]["station"]:
        raise CandidateContractError(
            "low-field Candidate requires one station-matched second prism and grounded shield"
        )
    shield = shields[0]
    cross = shield.get("cross_aperture")
    if not isinstance(cross, dict):
        raise CandidateContractError("low-field Candidate requires the grounded-shield cross aperture")
    clearance_positive_z = max(point[1] for point in shield["prism_clearance_polygon_yz_mm"])
    prism_positive_z = max(
        point[1] for part in prisms[0]["parts"] for point in part["polygon_yz_mm"]
    )
    if prism_positive_z >= clearance_positive_z:
        raise CandidateContractError(
            "second prism must remain strictly inside its positive-z clearance boundary"
        )
    cross_positive_z = max(
        _number(value, "low-field cross-aperture z") for value in cross["z_mm"]
    )
    positive_terminal_z = [
        point[1]
        for stripe in stripe_records
        if all(point[1] > 0.0 for point in stripe["terminal_polygon_yz_mm"])
        for point in stripe["terminal_polygon_yz_mm"]
    ]
    if not positive_terminal_z or len(positive_mirror_inner_faces_z_mm) != 1:
        raise CandidateContractError(
            "low-field Candidate requires positive Stripe terminals and one positive mirror inner face"
        )
    upper_candidates = {
        "ground_shield_cross_aperture_positive_z_edge_mm": cross_positive_z,
        "nearest_positive_stripe_terminal_surface_z_mm": min(positive_terminal_z),
        "positive_grounded_mirror_inner_face_z_mm": positive_mirror_inner_faces_z_mm[0],
    }
    lower = clearance_positive_z
    upper = min(upper_candidates.values())
    if not lower < upper:
        raise CandidateContractError("derived low-field Candidate interval is empty")
    reference_z = (lower + upper) / 2.0
    open_slots = [
        tuple(_number(value, "low-field grounded-shield slot bound") for value in slot)
        for slot in shield.get("rectangular_slots_mm", [])
        if len(slot) == 6 and float(slot[2]) < reference_z < float(slot[5])
    ]
    if not open_slots:
        raise CandidateContractError(
            "derived low-field Candidate plane has no grounded-shield transit aperture"
        )
    x_intersection = [max(slot[0] for slot in open_slots), min(slot[3] for slot in open_slots)]
    y_intervals = sorted((slot[1], slot[4]) for slot in open_slots)
    merged_y = [list(y_intervals[0])]
    for y_min, y_max in y_intervals[1:]:
        if y_min > merged_y[-1][1]:
            raise CandidateContractError(
                "low-field grounded-shield transit slots are disconnected in project y"
            )
        merged_y[-1][1] = max(merged_y[-1][1], y_max)
    if not x_intersection[0] < x_intersection[1] or len(merged_y) != 1:
        raise CandidateContractError(
            "low-field grounded-shield transit aperture is empty or disconnected"
        )
    return {
        "status": authority["status"],
        "qualification": "candidate_reference_section__not_a_zero_field_claim",
        "axis": "z",
        "open_project_z_interval_mm": [lower, upper],
        "reference_plane_project_z_mm": reference_z,
        "transit_aperture_project_mm": {
            "x_mm": x_intersection,
            "y_mm": merged_y[0],
            "source": "union_of_ground_shield_rectangular_slots_open_at_reference_plane",
        },
        "derivation": {
            "lower_boundary": {
                "source": "second_prism_ground_shield_clearance_positive_z_edge",
                "ground_shield_id": shield_id,
                "second_prism_electrode_id": prism_id,
                "second_prism_positive_z_extent_mm": prism_positive_z,
                "value_mm": lower,
            },
            "upper_boundary_candidates_mm": upper_candidates,
            "selected_upper_boundary_mm": upper,
        },
        "pa_field_plateau_validation": copy.deepcopy(validation),
        "operating_targets": {
            "low_field_angle_condition": target_authority["angle_condition"],
            "first_positive_mirror_turn_target_project_y_mm": target_turn_y,
        },
    }


def _inherit_dual_stripe_topology(
    geometry_contract: dict[str, Any], topology_contract: dict[str, Any],
) -> dict[str, Any]:
    """Project current topology/event authority onto frozen reviewed geometry.

    The GUI-reviewed r51 geometry predates the topology-derived path convention
    and therefore carries the retired single-profile multiplier ``1``.  That
    field never changed the generated solids.  Accept exactly that known legacy
    marker, remove it, and let the current four-instance authority derive
    ``S_i = 2 w_i``.  Any other legacy multiplier remains an incompatible
    physical contract and fails closed.
    """
    result = copy.deepcopy(geometry_contract)
    try:
        target = result["dual_stripe"]
        source = topology_contract["dual_stripe"]
        target_mapping = target["theory_profile"]["path_length_mapping"]
        source_mapping = source["theory_profile"]["path_length_mapping"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError(
            "dual Stripe topology inheritance needs complete geometry and authority blocks"
        ) from error
    for name in ("physical_electrode_count", "theoretical_response_count"):
        if target.get(name) != source.get(name):
            raise CandidateContractError(
                f"dual Stripe topology inheritance changes {name}"
            )
    source_legacy_scale = source_mapping.get("profile_width_to_total_S_multiplier")
    if source_legacy_scale is not None:
        raise CandidateContractError(
            "dual Stripe topology authority must derive path length from physical instances"
        )
    target_legacy_scale = target_mapping.get("profile_width_to_total_S_multiplier")
    if target_legacy_scale is not None and float(target_legacy_scale) != 1.0:
        raise CandidateContractError(
            "reviewed geometry has an unknown legacy dual Stripe path-length scale"
        )
    target_mapping.pop("profile_width_to_total_S_multiplier", None)
    for name in ("derivation", "shared_bias_physical_instances"):
        inherited = source_mapping.get(name)
        existing = target_mapping.get(name)
        if existing is not None and existing != inherited:
            raise CandidateContractError(
                f"reviewed geometry conflicts with inherited dual Stripe {name}"
            )
        target_mapping[name] = copy.deepcopy(inherited)
    try:
        target_injection = result["prism_transport"]["two_prism_injection_l0"]
        source_injection = topology_contract["prism_transport"][
            "two_prism_injection_l0"
        ]
    except (KeyError, TypeError) as error:
        raise CandidateContractError(
            "two-prism observation-authority inheritance needs complete contracts"
        ) from error
    for name in (
        "low_field_reference_section",
        "low_field_angle_and_positive_mirror_turn_authority",
    ):
        inherited = source_injection.get(name)
        if not isinstance(inherited, dict):
            raise CandidateContractError(
                f"current two-prism authority lacks {name}"
            )
        existing = target_injection.get(name)
        if existing is not None and existing != inherited:
            raise CandidateContractError(
                f"reviewed geometry conflicts with inherited two-prism {name}"
            )
        target_injection[name] = copy.deepcopy(inherited)
    # Exercise the full invariant validator before any geometry is generated.
    dual_stripe_physical_instance_topology(result)
    return result


def resolve_geometry(
    contract: dict[str, Any],
    *,
    inherited_dual_stripe_topology_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return validated physical primitives for all electrodes.

    A Candidate may be a theory-derived design or the existing manufactured
    mirror geometry with a theory-optimized operating point.  In either case,
    the resolved output is solver-neutral and contains no CAD-private entity.
    """
    if inherited_dual_stripe_topology_contract is not None:
        contract = _inherit_dual_stripe_topology(
            contract, inherited_dual_stripe_topology_contract,
        )
    authority = contract.get("geometry_authority", {})
    if authority.get("model") not in {
        "theory_derived_3d",
        "manufactured_CAD_geometry__theory_optimized_operating_point",
    }:
        raise CandidateContractError("resolved geometry needs a qualified Candidate authority")
    frame = contract.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v2":
        raise CandidateContractError("resolved geometry requires the MR-TOF project frame")

    mirror = contract["mirror"]
    slot_width = _number(mirror["beam_slot_width_mm"], "mirror.beam_slot_width_mm")
    if slot_width != 30.0:
        raise CandidateContractError("mirror beam slot is the fixed 30 mm CAD constraint")
    width_x = _number(mirror["outer_width_x_mm"], "mirror.outer_width_x_mm")
    length_y = _number(mirror["length_y_mm"], "mirror.length_y_mm")
    centre_y = _number(mirror["centre_y_mm"], "mirror.centre_y_mm")
    y0, y1 = centre_y - length_y / 2.0, centre_y + length_y / 2.0
    inner = _number(mirror["inner_face_z_mm"], "mirror.inner_face_z_mm")
    inner_clearance = _number(
        mirror["inner_clearance_to_stripe_mm"], "mirror.inner_clearance_to_stripe_mm"
    )
    thicknesses = tuple(_number(value, "mirror.electrode_thicknesses_mm") for value in mirror["electrode_thicknesses_mm"])
    gaps = tuple(_number(value, "mirror.inter_electrode_gaps_mm") for value in mirror["inter_electrode_gaps_mm"])
    if len(thicknesses) != 5 or len(gaps) != 4 or min(thicknesses) <= 0.0 or min(gaps) <= 0.0:
        raise CandidateContractError("mirror requires five positive thicknesses and four positive gaps")
    if not width_x > slot_width or length_y <= 0.0 or inner <= 0.0 or inner_clearance <= 0.0:
        raise CandidateContractError("mirror envelope cannot contain its fixed beam slot")
    slot = mirror["beam_slot"]
    if slot.get("axis") != "x":
        raise CandidateContractError("mirror mechanical slot must be the documented x-wide longitudinal through-slot")
    if slot.get("topology_status") != "verified":
        raise CandidateContractError(
            "mirror slot topology is not CAD-verified; refusing to emit a synthetic through-cut"
        )
    slot_x = _number(slot["centre_x_mm"], "mirror.beam_slot.centre_x_mm")
    slot_length_y = _number(slot["length_y_mm"], "mirror.beam_slot.length_y_mm")
    if not 0.0 < slot_length_y < length_y or abs(slot_x) + slot_width / 2.0 > width_x / 2.0:
        raise CandidateContractError("mirror slot must be a bounded 30-mm x opening within the CAD envelope")
    slot_y0, slot_y1 = centre_y - slot_length_y / 2.0, centre_y + slot_length_y / 2.0

    inner_shield = mirror["grounded_inner_shield"]
    outer_closure = mirror["outer_e_closure"]
    inner_shield_thickness = _number(
        inner_shield["thickness_z_mm"], "mirror.grounded_inner_shield.thickness_z_mm"
    )
    inner_shield_slot_width = _number(
        inner_shield["slot_width_x_mm"], "mirror.grounded_inner_shield.slot_width_x_mm"
    )
    inner_shield_slot_length = _number(
        inner_shield["slot_length_y_mm"], "mirror.grounded_inner_shield.slot_length_y_mm"
    )
    outer_closure_thickness = _number(
        outer_closure["thickness_z_mm"], "mirror.outer_e_closure.thickness_z_mm"
    )
    if (
        inner_shield_thickness != 5.0
        or inner_shield_slot_width != 4.0
        or not 0.0 < inner_shield_slot_length <= length_y
        or outer_closure_thickness != 5.0
    ):
        raise CandidateContractError(
            "mirror end plates require the CAD-verified 5-mm inner 4-mm-slot shield and 5-mm closed E plate"
        )

    mirror_boxes: list[dict[str, Any]] = []
    # ``inner`` is the physical, Stripe-facing face of the grounded shield.
    # The first active electrode begins only behind that 5-mm plate.
    z_cursor = inner + inner_shield_thickness
    for index, thickness in enumerate(thicknesses, start=1):
        right = Box(-width_x / 2.0, y0, z_cursor, width_x / 2.0, y1, z_cursor + thickness)
        left = Box(right.x0, right.y0, -right.z1, right.x1, right.y1, -right.z0)
        right_slot = Box(slot_x - slot_width / 2.0, slot_y0, right.z0 - 1.0, slot_x + slot_width / 2.0, slot_y1, right.z1 + 1.0)
        left_slot = Box(slot_x - slot_width / 2.0, slot_y0, left.z0 - 1.0, slot_x + slot_width / 2.0, slot_y1, left.z1 + 1.0)
        mirror_boxes.extend((
            {"id": index, "box": right.as_list(), "beam_slot": right_slot.as_list()},
            {"id": index + 5, "box": left.as_list(), "beam_slot": left_slot.as_list()},
        ))
        z_cursor += thickness + (gaps[index - 1] if index < 5 else 0.0)
    active_outer_z = z_cursor
    mirror_slot = Box(
        slot_x - slot_width / 2.0,
        slot_y0,
        -active_outer_z,
        slot_x + slot_width / 2.0,
        slot_y1,
        active_outer_z,
    )
    shield_slot = Box(
        -inner_shield_slot_width / 2.0,
        centre_y - inner_shield_slot_length / 2.0,
        -inner - inner_shield_thickness - 1.0,
        inner_shield_slot_width / 2.0,
        centre_y + inner_shield_slot_length / 2.0,
        inner + inner_shield_thickness + 1.0,
    )
    mirror_ground_shields = [
        {"role": "inner_stripe_facing_4mm_slot", "box": Box(-width_x / 2.0, y0, inner, width_x / 2.0, y1, inner + inner_shield_thickness).as_list()},
        {"role": "inner_stripe_facing_4mm_slot", "box": Box(-width_x / 2.0, y0, -inner - inner_shield_thickness, width_x / 2.0, y1, -inner).as_list()},
    ]
    mirror_e_closures = [
        {"id": 5, "role": "outer_closed_e_voltage", "box": Box(-width_x / 2.0, y0, active_outer_z, width_x / 2.0, y1, active_outer_z + outer_closure_thickness).as_list()},
        {"id": 10, "role": "outer_closed_e_voltage", "box": Box(-width_x / 2.0, y0, -active_outer_z - outer_closure_thickness, width_x / 2.0, y1, -active_outer_z).as_list()},
    ]

    stripe = contract["dual_stripe"]
    if _number(stripe["beam_slot_width_mm"], "dual_stripe.beam_slot_width_mm") != 4.0:
        raise CandidateContractError("Ion-Foil beam slot is the fixed 4 mm CAD constraint")
    thickness_x = _number(stripe["thickness_x_mm"], "dual_stripe.thickness_x_mm")
    if thickness_x <= 4.0:
        raise CandidateContractError("physical Stripe body must enclose the 4 mm beam slot")
    y_span = tuple(_number(value, "dual_stripe.y_span_mm") for value in stripe["y_span_mm"])
    if len(y_span) != 2 or not y_span[0] < y_span[1]:
        raise CandidateContractError("dual_stripe.y_span_mm must be ordered")
    bridges = stripe.get("beam_slot_y_bridges_mm")
    if not isinstance(bridges, dict):
        raise CandidateContractError("dual_stripe requires CAD-derived finite-y beam-slot bridges")
    bridge_from_min = _number(
        bridges.get("from_min_y_mm"), "dual_stripe.beam_slot_y_bridges_mm.from_min_y_mm"
    )
    bridge_from_max = _number(
        bridges.get("from_max_y_mm"), "dual_stripe.beam_slot_y_bridges_mm.from_max_y_mm"
    )
    if min(bridge_from_min, bridge_from_max) <= 0.0 or bridge_from_min + bridge_from_max >= y_span[1] - y_span[0]:
        raise CandidateContractError("finite-y Stripe slot bridges must be positive and leave a nonempty opening")
    curve_span = tuple(_number(value, "dual_stripe.theory_profile.active_y_span_mm")
                       for value in stripe["theory_profile"].get("active_y_span_mm", []))
    if (
        len(curve_span) != 2
        or not y_span[0] < curve_span[0] < curve_span[1] == y_span[1]
    ):
        raise CandidateContractError(
            "Stripe finite terminal feature must precede the active curves in positive theory y"
        )
    identity = stripe.get("cad_body_topology_identity", {})
    if identity.get("schema_version") != 1 or set(identity.get("source_native_sha256", {})) != {"ion_foil_1", "ion_foil_2", "ion_foil_3"}:
        raise CandidateContractError("whole Foil bodies require the native CAD topology identities")
    if identity.get("source_units") != "m" or identity.get("resolved_units") != "mm" or any(
        not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        for value in identity["source_native_sha256"].values()
    ):
        raise CandidateContractError("Foil CAD topology units and source hashes must be explicit and valid")
    one_lower, one_upper, two_lower, two_upper = _theory_profiles(stripe, curve_span)
    for name, edge in (("set_1 lower", one_lower), ("set_1 upper", one_upper), ("set_2 lower", two_lower), ("set_2 upper", two_upper)):
        if (edge[0][0], edge[-1][0]) != curve_span:
            raise CandidateContractError(f"{name} must span the frozen active curve interval")
    set_1 = _polygon(one_lower, one_upper)
    set_2 = _polygon(two_lower, two_upper)
    required_interstripe_gap = _number(
        stripe["serial_positive_z_gap_mm"], "dual_stripe.serial_positive_z_gap_mm"
    )
    interstripe_clearance = min(
        first[1] - second[1] for first, second in zip(one_lower, two_upper)
    )
    if required_interstripe_gap <= 0.0 or interstripe_clearance < required_interstripe_gap:
        raise CandidateContractError(
            "the two positive-z Stripe profiles must retain their declared non-overlapping clearance"
        )
    central_ground_electrodes, central_ground_top_z = _central_ground_polygons(stripe)
    central_ground_status = stripe.get("central_ground_outline_status")
    if central_ground_status != "cad_outline_verified_for_candidate":
        raise CandidateContractError("central-ground CAD body outline is not qualified for Candidate geometry")
    stripe_two_lower = stripe["theory_profile"]["set_2"]["lower_edge"]
    ground_y_span = tuple(_number(value, "central_ground_profile.y_span_mm") for value in stripe["central_ground_profile"]["y_span_mm"])
    ground_clearance = min(
        _edge_z_at_y(stripe_two_lower, "theory_profile.set_2.lower_edge", y_value)
        - max(
            _edge_z_at_y(stripe["central_ground_profile"][side]["upper_edge"], f"central_ground.{side}.upper_edge", y_value)
            for side in ("positive_x", "negative_x")
        )
        for y_value in (ground_y_span[0] + (ground_y_span[1] - ground_y_span[0]) * index / 96.0 for index in range(97))
    )
    if ground_clearance <= 0.0:
        raise CandidateContractError("central ground overlaps the inner Stripe profile")
    raw_heights = {
        "set_1": max(point[1] for point in set_1) - min(point[1] for point in set_1),
        "set_2": max(point[1] for point in set_2) - min(point[1] for point in set_2),
    }
    polygons = {"set_1": set_1, "set_2": set_2}
    stripe_records = []
    for instance in dual_stripe_physical_instance_topology(contract):
        polygon = polygons[instance.set_name]
        terminal = _terminal_polygon(
            y_span[0], curve_span[0],
            stripe["theory_profile"][instance.set_name].get("terminal_z_mm"),
        )
        if instance.reflection_axis_sign < 0:
            polygon = _mirrored_polygon(polygon)
            terminal = _mirrored_polygon(terminal)
        stripe_records.append({
            "id": instance.electrode_id,
            "x": [-thickness_x / 2.0, thickness_x / 2.0],
            "polygon_yz_mm": [list(point) for point in polygon],
            "terminal_polygon_yz_mm": [list(point) for point in terminal],
        })
    stripe_z = [point[1] for record in stripe_records
                for key in ("polygon_yz_mm", "terminal_polygon_yz_mm") for point in record[key]]
    max_abs_stripe_z = max(abs(value) for value in stripe_z)
    mirror_stripe_clearance = inner - max_abs_stripe_z
    if mirror_stripe_clearance < inner_clearance:
        raise CandidateContractError("outer Stripe profile overlaps the required grounded-inner-shield clearance")
    # The native Ion-Foil body is one conductor: the 4-mm central channel is
    # open only between the two CAD-measured y-end bridges.  Cutting it across
    # the whole drift length would falsely create two disconnected plates.
    stripe_slot = Box(
        -2.0,
        y_span[0] + bridge_from_min,
        min(stripe_z) - 1.0,
        2.0,
        y_span[1] - bridge_from_max,
        max(stripe_z) + 1.0,
    )
    terminal_window = stripe["central_ground_profile"]["terminal_profile"].get("terminal_window_yz_mm")
    if not isinstance(terminal_window, list) or len(terminal_window) != 4:
        raise CandidateContractError("central ground terminal requires its x-through rectangular window")
    window_y0, window_z0, window_y1, window_z1 = (_number(value, "central ground terminal window") for value in terminal_window)
    if window_y0 != y_span[0] or window_y1 != ground_y_span[0] or not window_z0 < window_z1:
        raise CandidateContractError("central ground terminal window must span the complete short-end feature")
    central_ground_slots = [
        Box(-2.0, stripe_slot.y0, -central_ground_top_z, 2.0, stripe_slot.y1, central_ground_top_z).as_list(),
        Box(-thickness_x / 2.0, window_y0, window_z0, thickness_x / 2.0, window_y1, window_z1).as_list(),
    ]
    prism_contract = contract.get("prisms")
    if not isinstance(prism_contract, dict) or prism_contract.get("geometry_status") != "cad_triangle_and_nested_ground_aperture_audited__candidate_pose":
        raise CandidateContractError("prism Candidate geometry requires its explicit qualified-layout contract")
    prism_electrodes = []
    for item in prism_contract.get("electrodes", []):
        if not isinstance(item, dict) or int(item.get("id", 0)) not in (16, 17):
            raise CandidateContractError("prism electrodes must use stable IDs 16 and 17")
        station = item.get("station")
        bands, polygons = item.get("x_bands_mm"), item.get("polygons_yz_mm")
        if not isinstance(station, str) or not station:
            raise CandidateContractError("each prism electrode requires a named physical station")
        if not isinstance(bands, list) or not isinstance(polygons, list) or len(bands) != len(polygons) or len(bands) != 2:
            raise CandidateContractError("each prism requires two x bands and two y-z triangles")
        parts = []
        for x_band, flat_polygon in zip(bands, polygons):
            if not isinstance(x_band, list) or len(x_band) != 2 or not float(x_band[0]) < float(x_band[1]):
                raise CandidateContractError("prism x bands must have positive width")
            if not isinstance(flat_polygon, list) or len(flat_polygon) != 6:
                raise CandidateContractError("prism candidate requires triangular y-z polygons")
            parts.append({"x": [float(value) for value in x_band], "polygon_yz_mm": [[float(flat_polygon[index]), float(flat_polygon[index + 1])] for index in range(0, 6, 2)]})
        prism_electrodes.append({"id": int(item["id"]), "station": station, "parts": parts})
    if {item["id"] for item in prism_electrodes} != {16, 17}:
        raise CandidateContractError("exactly the two stable prism IDs are required")
    prism_ground_shields = []
    prism_stations = {item["id"]: item["station"] for item in prism_electrodes}
    for item in prism_contract.get("ground_shields", []):
        if not isinstance(item, dict) or int(item.get("id", 0)) not in (18, 20):
            raise CandidateContractError("prism grounded shields must use the two CAD physical IDs 18 and 20")
        station = item.get("station")
        if station not in set(prism_stations.values()):
            raise CandidateContractError("each prism shield must name an existing prism station")
        x = [float(value) for value in item.get("x_mm", [])]
        outer = item.get("outer_polygon_yz_mm")
        clearance = item.get("prism_clearance_polygon_yz_mm")
        topology = item.get("topology")
        channel: list[float] = []
        rectangular_slots: list[list[float]] = []
        cross_aperture = item.get("cross_aperture")
        if len(x) != 2 or not x[0] < x[1]:
            raise CandidateContractError("prism shields require a positive x extent")
        body_sections = item.get("body_sections")
        body_identity = item.get("cad_body_topology_identity", {})
        if not isinstance(body_sections, list) or not body_sections or body_identity.get("schema_version") != 1:
            raise CandidateContractError("prism shield requires native CAD body sections, not an extruded bounding box")
        for key in ("native_sha256", "stl_sha256"):
            digest = body_identity.get(key)
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise CandidateContractError("prism shield native/STL topology identity is missing or invalid")
        sections = []
        for section in body_sections:
            sx = [_number(value, "prism body section x") for value in section.get("x_mm", [])]
            polygon = [[_number(value, "prism body contour") for value in point]
                       for point in section.get("outer_polygon_yz_mm", [])]
            if len(sx) != 2 or not x[0] <= sx[0] < sx[1] <= x[1] or len(polygon) < 3 or any(len(point) != 2 for point in polygon):
                raise CandidateContractError("native prism body section has invalid x bounds or contour")
            sections.append({"x": sx, "polygon_yz_mm": polygon})
        if topology == "single_continuous_frame_with_rectangular_slots":
            if item.get("mechanical_component") != "grounded_1_single_frame" or x != [-24.0, 12.0]:
                raise CandidateContractError("accelerator-exit shield must be the single CAD grounded-1 frame")
            slot_items = item.get("rectangular_slots_mm")
            if not isinstance(slot_items, list) or len(slot_items) != 1 or not isinstance(slot_items[0], dict):
                raise CandidateContractError("grounded-1 requires exactly one CAD rectangular beam-channel slot")
            slot = [float(value) for value in slot_items[0].get("box", [])]
            if slot_items[0].get("role") != "four_mm_beam_channel" or slot != [-2.0, -75.0, -100.0, 2.0, -35.0, -30.0]:
                raise CandidateContractError("grounded-1 must subtract its CAD 4-mm by 40-mm finite rectangular channel")
            rectangular_slots.append(slot)
            channel = [-2.0, 2.0]
        elif topology == "single_continuous_frame_with_cross_aperture":
            if item.get("mechanical_component") != "grounded_2_single_cross_frame" or not isinstance(cross_aperture, dict):
                raise CandidateContractError("central grounded-2 shield requires its single-frame cross-aperture contract")
            channel = [float(value) for value in cross_aperture.get("x_mm", [])]
            cross_y = [float(value) for value in cross_aperture.get("y_mm", [])]
            cross_z = [float(value) for value in cross_aperture.get("z_mm", [])]
            lands = [float(value) for value in cross_aperture.get("reflection_axis_end_lands_z_mm", [])]
            if channel != [-2.0, 2.0] or cross_y != [-28.0, -6.0] or cross_z != [-40.0, 40.0] or lands != [57.0, 57.0]:
                raise CandidateContractError("grounded-2 cross aperture must retain the CAD-measured 4 x 22 x 80 mm opening")
            if float(cross_aperture.get("stripe_side_wall_y_mm", 0.0)) != 3.0 or float(cross_aperture.get("far_stripe_side_wall_y_mm", 0.0)) != 4.0:
                raise CandidateContractError("grounded-2 cross aperture requires its measured 3-mm and 4-mm y walls")
            if cross_aperture.get("boolean_operation") != "union":
                raise CandidateContractError("grounded-2 cross aperture is the union of two rectangular slots, not their intersection")
        else:
            raise CandidateContractError("prism shield topology is unsupported")
        if not isinstance(outer, list) or len(outer) < 3 or not isinstance(clearance, list) or len(clearance) != 3:
            raise CandidateContractError("each prism shield requires an outer y-z contour and larger triangular clearance")
        outer_polygon = [[float(point[0]), float(point[1])] for point in outer]
        clearance_polygon = [[float(point[0]), float(point[1])] for point in clearance]
        outer_y = [point[0] for point in outer_polygon]
        outer_z = [point[1] for point in outer_polygon]
        if min(outer_y) >= max(outer_y) or min(outer_z) >= max(outer_z):
            raise CandidateContractError("prism shield outer contour must have positive y-z area")
        if station == "accelerator_exit" and (min(outer_y), max(outer_y), min(outer_z), max(outer_z)) != (-77.0, -33.0, -100.0, -30.0):
            raise CandidateContractError("accelerator-exit prism shield must retain the CAD grounded-1 project-frame start and extent")
        if any(not (min(outer_y) <= point[0] <= max(outer_y) and min(outer_z) <= point[1] <= max(outer_z)) for point in clearance_polygon):
            raise CandidateContractError("larger prism clearance must remain inside the grounded shield contour")
        if topology == "single_continuous_frame_with_cross_aperture":
            rectangular_slots.extend((
                [channel[0], cross_y[0], min(outer_z), channel[1], cross_y[1], max(outer_z)],
                [channel[0], min(outer_y), cross_z[0], channel[1], max(outer_y), cross_z[1]],
            ))
        prism_ground_shields.append({
            "id": int(item["id"]), "station": station, "x": x,
            "outer_polygon_yz_mm": outer_polygon,
            "body_sections": sections,
            "cad_body_topology_identity": body_identity,
            "prism_clearance_polygon_yz_mm": clearance_polygon,
            "beam_channel_x_mm": channel, "topology": topology,
            "rectangular_slots_mm": rectangular_slots,
            "mechanical_component": item.get("mechanical_component"),
            "cad_negative_inner_mirror_face_z_mm": item.get("cad_negative_inner_mirror_face_z_mm"),
            "cad_required_mirror_clearance_mm": item.get("cad_required_mirror_clearance_mm"),
            "cross_aperture": None if cross_aperture is None else {
                "x_mm": channel, "y_mm": cross_y, "z_mm": cross_z, "boolean_operation": "union",
            },
        })
    if {item["id"] for item in prism_ground_shields} != {18, 20}:
        raise CandidateContractError("exactly the two CAD physical prism grounded shields are required")
    # Both mechanical shield sides at a station must leave a true triangular
    # clearance around every corresponding prism, not merely contain its bbox.
    for prism in prism_electrodes:
        matching_shields = [shield for shield in prism_ground_shields if shield["station"] == prism["station"]]
        if not matching_shields:
            raise CandidateContractError("each prism requires a matching grounded shield")
        for shield in matching_shields:
            if not all(
                _strictly_inside_triangle(vertex, shield["prism_clearance_polygon_yz_mm"])
                for part in prism["parts"] for vertex in part["polygon_yz_mm"]
            ):
                raise CandidateContractError("prism triangle must lie strictly inside every matching CAD shield aperture")
    central_shields = [item for item in prism_ground_shields if item["station"] == "central_ground_left"]
    if len(central_shields) != 1 or central_shields[0]["topology"] != "single_continuous_frame_with_cross_aperture":
        raise CandidateContractError("the central-ground prism requires its one CAD grounded-2 cross frame")
    for shield in central_shields:
        outer_z = [point[1] for point in shield["outer_polygon_yz_mm"]]
        outer_y = [point[0] for point in shield["outer_polygon_yz_mm"]]
        if min(outer_z) > -97.0 or max(outer_z) < 97.0 or min(outer_y) < -32.0 or max(outer_y) > 3.0:
            raise CandidateContractError(
                "central-ground prism shields must retain the audited finite-y, z=[-97,97] coverage"
            )
    exit_shields = [item for item in prism_ground_shields if item["station"] == "accelerator_exit"]
    if len(exit_shields) != 1 or exit_shields[0]["topology"] != "single_continuous_frame_with_rectangular_slots":
        raise CandidateContractError("accelerator-exit prism requires its one CAD grounded-1 frame")
    for shield in exit_shields:
        cad_face = _number(shield.get("cad_negative_inner_mirror_face_z_mm"), "accelerator-exit shield CAD mirror face")
        cad_gap = _number(shield.get("cad_required_mirror_clearance_mm"), "accelerator-exit shield CAD mirror clearance")
        observed = min(point[1] for point in shield["outer_polygon_yz_mm"]) - cad_face
        if cad_gap != 2.0 or abs(observed - cad_gap) > 1e-9:
            raise CandidateContractError("accelerator-exit prism shield must retain the CAD 2-mm gap to the negative inner mirror face")
    detector_contract = contract.get("detector")
    if not isinstance(detector_contract, dict) or int(detector_contract.get("id", 0)) != 25:
        raise CandidateContractError("numerical detector requires stable ID 25")
    if detector_contract.get("anchor") != "positive_grounded_mirror_inner_face" or detector_contract.get("normal_project") != "+z":
        raise CandidateContractError("detector must be +z-facing at the positive grounded-mirror side")
    width_x = _number(detector_contract.get("active_width_x_mm"), "detector.active_width_x_mm")
    height_y = _number(detector_contract.get("active_height_y_mm"), "detector.active_height_y_mm")
    thickness_z = _number(detector_contract.get("thickness_z_mm"), "detector.thickness_z_mm")
    clearance_z = _number(detector_contract.get("clearance_from_positive_grounded_mirror_z_mm"), "detector.clearance_from_positive_grounded_mirror_z_mm")
    clearance_y = _number(detector_contract.get("clearance_from_central_prism_ground_shield_y_mm"), "detector.clearance_from_central_prism_ground_shield_y_mm")
    if min(width_x, height_y, thickness_z, clearance_z, clearance_y) <= 0.0:
        raise CandidateContractError("detector dimensions and all declared clearances must be positive")
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict) or accelerator.get("axis") != "z_negative":
        raise CandidateContractError("detector placement requires the -z two-zone accelerator")
    accelerator_requirements = build_two_zone_accelerator_requirements(contract)
    accelerator_layout = compile_closed_two_zone_accelerator(accelerator_requirements).layout.to_dict()
    placement = accelerator_requirements["placement"]
    if not isinstance(placement, dict):
        raise CandidateContractError("accelerator provider placement request is invalid")
    accelerator_focus_y = _number(placement.get("focus_y_mm"), "accelerator provider focus_y_mm")
    accelerator_exit_z = _number(placement.get("global_exit_z_mm"), "accelerator provider global_exit_z_mm")
    central_shield_y_min = min(point[0] for shield in central_shields for point in shield["outer_polygon_yz_mm"])
    accelerator_guard_y1 = accelerator_focus_y + float(accelerator_layout["static_minimum_y_extent_mm"]) / 2.0
    accelerator_shield_clearance = central_shield_y_min - accelerator_guard_y1
    required_accelerator_shield_clearance = _number(
        accelerator.get("minimum_clearance_to_central_prism_ground_shield_y_mm"),
        "accelerator.minimum_clearance_to_central_prism_ground_shield_y_mm",
    )
    if required_accelerator_shield_clearance <= 0.0 or accelerator_shield_clearance < required_accelerator_shield_clearance:
        raise CandidateContractError(
            "accelerator grounded enclosure intersects or lacks its declared clearance to the central prism grounded shield"
        )
    positive_inner_faces = [float(shield["box"][2]) for shield in mirror_ground_shields if float(shield["box"][2]) > 0.0]
    if len(positive_inner_faces) != 1:
        raise CandidateContractError("detector requires exactly one positive grounded-mirror inner face")
    low_field_reference_section = _candidate_low_field_reference_section(
        contract,
        prism_electrodes,
        prism_ground_shields,
        stripe_records,
        positive_inner_faces,
    )
    detector_z1 = positive_inner_faces[0] - clearance_z
    detector_z0 = detector_z1 - thickness_z
    if detector_z0 <= accelerator_exit_z + float(accelerator_layout["static_axial_length_mm"]):
        raise CandidateContractError("detector overlaps the accelerator instead of occupying the grounded-mirror side")
    detector_y = accelerator_focus_y
    for shield in central_shields:
        shield_x = shield["x"]
        shield_y = [point[0] for point in shield["outer_polygon_yz_mm"]]
        shield_z = [point[1] for point in shield["outer_polygon_yz_mm"]]
        x_overlap = -width_x / 2.0 < shield_x[1] and width_x / 2.0 > shield_x[0]
        z_overlap = detector_z0 < max(shield_z) and detector_z1 > min(shield_z)
        if x_overlap and z_overlap:
            detector_y = min(detector_y, min(shield_y) - clearance_y - height_y / 2.0)
    detector_box = [-width_x / 2.0, detector_y - height_y / 2.0, detector_z0,
                    width_x / 2.0, detector_y + height_y / 2.0, detector_z1]
    for shield in central_shields:
        shield_y = [point[0] for point in shield["outer_polygon_yz_mm"]]
        shield_z = [point[1] for point in shield["outer_polygon_yz_mm"]]
        if detector_box[4] > min(shield_y) - clearance_y and detector_box[2] < max(shield_z) and detector_box[5] > min(shield_z):
            raise CandidateContractError("detector must retain its declared y clearance from the central-prism grounded shield")
    validate_detector_return_path(contract)

    return {
        "schema_version": 1,
        "project_id": "parallel_mirror_dual_stripe_mr_tof",
        "status": "candidate_theory_derived_cad_constrained",
        "frame_id": frame["frame_id"],
        "mirror_electrodes": mirror_boxes,
        "mirror_slot": mirror_slot.as_list(),
        "mirror_inner_shield_slot": shield_slot.as_list(),
        "mirror_ground_shields": mirror_ground_shields,
        "mirror_e_closures": mirror_e_closures,
        "stripe_electrodes": stripe_records,
        "stripe_slot": stripe_slot.as_list(),
        "central_ground_electrodes": central_ground_electrodes,
        "central_ground_slots": central_ground_slots,
        "cad_body_topology_identity": identity,
        "prism_electrodes": prism_electrodes,
        "prism_ground_shields": prism_ground_shields,
        "two_prism_low_field_reference_section": low_field_reference_section,
        "accelerator_component_layout": accelerator_layout,
        "detector": {"id": 25, "box": detector_box, "normal_project": "+z", "separate_pa": True},
        "metadata": {
            "mirror_slot_width_mm": slot_width,
            "mirror_slot_length_y_mm": slot_length_y,
            "mirror_centre_y_mm": centre_y,
            "mirror_inner_ground_shield_slot_width_mm": inner_shield_slot_width,
            "mirror_inner_ground_shield_slot_length_mm": inner_shield_slot_length,
            "mirror_inner_ground_shield_thickness_mm": inner_shield_thickness,
            "mirror_outer_e_closure_thickness_mm": outer_closure_thickness,
            "mirror_inner_clearance_to_stripe_mm": inner_clearance,
            "resolved_minimum_stripe_to_inner_shield_clearance_mm": inner - max_abs_stripe_z,
            "mirror_stripe_clearance_pass": mirror_stripe_clearance >= inner_clearance - 1e-9,
            "ion_foil_slot_width_mm": 4.0,
            "ion_foil_slot_bridge_from_min_y_mm": bridge_from_min,
            "ion_foil_slot_bridge_from_max_y_mm": bridge_from_max,
            "central_ground_slot_topology": "whole native body minus the finite 4-mm x slot and x-through terminal window; no added bridge solids",
            "central_ground_max_positive_z_mm": central_ground_top_z,
            "central_ground_to_stripe_clearance_mm": ground_clearance,
            "resolved_minimum_interstripe_clearance_mm": interstripe_clearance,
            "required_minimum_interstripe_clearance_mm": required_interstripe_gap,
            "raw_positive_profile_heights_mm": raw_heights,
            "stripe_curve_pose_model": "theory_bspline_parameterization__native_knot_control_contract",
            "central_ground_outline_status": central_ground_status,
            "detector_to_positive_grounded_mirror_clearance_mm": positive_inner_faces[0] - detector_z1,
            "detector_to_central_prism_ground_shield_clearance_y_mm": min(point[0] for shield in central_shields for point in shield["outer_polygon_yz_mm"]) - detector_box[4],
            "accelerator_guard_to_central_prism_ground_shield_clearance_y_mm": accelerator_shield_clearance,
            "required_accelerator_guard_to_central_prism_ground_shield_clearance_y_mm": required_accelerator_shield_clearance,
            "accelerator_component_geometry_profile_id": accelerator_layout["geometry_profile_id"],
        },
    }


def geometry_fingerprint(resolved: dict[str, Any]) -> str:
    """Hash physical geometry without derived numerical observation surfaces."""
    physical = copy.deepcopy(resolved)
    # This section is derived from physical clearances for trajectory sampling;
    # it adds no conductor or aperture and therefore must not invalidate an
    # already reviewed PA/IOB geometry identity.
    physical.pop("two_prism_low_field_reference_section", None)
    payload = json.dumps(physical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def geometry_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    """Expose stable cross-solver geometry checks from one resolved contract."""
    resolved = resolve_geometry(contract)
    mirror_ids = sorted(item["id"] for item in resolved["mirror_electrodes"])
    stripe_ids = sorted(item["id"] for item in resolved["stripe_electrodes"])
    return {
        "schema_version": 1,
        "project_id": resolved["project_id"],
        "frame_id": resolved["frame_id"],
        "units": "mm",
        "resolved_geometry_sha256": geometry_fingerprint(resolved),
        "electrode_ids": {
            "mirrors": mirror_ids,
            "stripes": stripe_ids,
            "central_ground": [15],
            "prisms": [16, 17],
            "prism_ground_shields": [18, 20],
            "detector": [25],
        },
        "mechanical_invariants_mm": resolved["metadata"],
        "mirror_slot_box_mm": resolved["mirror_slot"],
        "mirror_inner_shield_slot_box_mm": resolved["mirror_inner_shield_slot"],
        "stripe_slot_box_mm": resolved["stripe_slot"],
    }


def write_geometry_receipt(contract: dict[str, Any], output_path: Path) -> dict[str, Any]:
    """Write an LF, solver-neutral resolved-geometry receipt for adapters."""
    receipt = geometry_receipt(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt
