"""Solver-neutral segmented Hamiltonian transport in the project y-z plane.

The reduced momenta ``u_y`` and ``u_z`` have units ``sqrt(V)`` and obey
``H = u_y**2 + u_z**2 + sign(q) * phi``.  Positions are millimetres and the
independent variable therefore has units ``mm/sqrt(V)``.  Constant-potential
regions represent ideal prism or Stripe field bands, not metal.  The supplied
mirror gradient remains active inside every band; only an interface crossing
changes the constant part of the potential.

This module intentionally owns no MR-TOF geometry, voltage, source, or event
sequence.  Project adapters must construct those explicit inputs from their
frozen contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, Sequence

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq


ScalarField = Callable[[float, float], float]
VectorField = Callable[[float, float], tuple[float, float]]
AxialField = Callable[[float], float]


class TransportError(ValueError):
    """Raised when transport inputs or an interface event are ambiguous."""


@dataclass(frozen=True)
class PhaseState2D:
    """A project-frame y-z state in mm, sqrt(V), and reduced time."""

    reduced_time_mm_per_sqrt_v: float
    y_mm: float
    z_mm: float
    u_y_sqrt_v: float
    u_z_sqrt_v: float


@dataclass(frozen=True)
class InterfaceBoundary:
    """One finite boundary with an inward-positive, mm-valued level set."""

    name: str
    level: ScalarField
    inward_normal: VectorField
    contains_boundary_point: Callable[[float, float], bool]


@dataclass(frozen=True)
class PotentialRegion:
    """A finite ideal constant-potential region bounded by real interfaces."""

    name: str
    bias_v: float
    boundaries: tuple[InterfaceBoundary, ...]
    contains: Callable[[float, float], bool]


@dataclass(frozen=True)
class StopTarget:
    """An explicit finite mm-valued level set; direction is -1, 0, or +1."""

    name: str
    level: ScalarField
    positive_normal: VectorField
    contains_target_point: Callable[[float, float], bool]
    direction: int = 0


@dataclass(frozen=True)
class TransportNumerics:
    """Numerical controls for ODE integration and event isolation."""

    relative_tolerance: float
    absolute_tolerance: float
    max_step_mm_per_sqrt_v: float
    event_samples_per_step: int
    root_time_tolerance_mm_per_sqrt_v: float
    boundary_root_tolerance_mm: float
    momentum_tolerance_sqrt_v: float
    normal_energy_tolerance_v: float
    maximum_steps: int


@dataclass(frozen=True)
class TransportEvent:
    """A resolved interface or stop event and its local conservation report."""

    kind: str
    name: str
    state_before: PhaseState2D
    state_after: PhaseState2D
    region_name: str | None
    entering: bool | None
    transmitted: bool | None
    attempted_potential_change_v: float
    applied_potential_change_v: float
    tangential_momentum_residual_sqrt_v: float
    hamiltonian_residual_v: float


@dataclass(frozen=True)
class TransportResult:
    """Terminal state, ordered events, and Hamiltonian drift diagnostics."""

    status: str
    initial_state: PhaseState2D
    final_state: PhaseState2D
    active_region_names: tuple[str, ...]
    events: tuple[TransportEvent, ...]
    initial_hamiltonian_v: float
    final_hamiltonian_v: float
    final_hamiltonian_residual_v: float
    maximum_absolute_hamiltonian_residual_v: float


def _finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise TransportError(f"{label} must be finite")
    return result


def _unit(vector: tuple[float, float], label: str) -> tuple[float, float]:
    y, z = (_finite(value, label) for value in vector)
    length = math.hypot(y, z)
    if length <= 0.0:
        raise TransportError(f"{label} must be nonzero")
    return y / length, z / length


def _validate_numerics(numerics: TransportNumerics) -> None:
    positive = (
        numerics.relative_tolerance,
        numerics.absolute_tolerance,
        numerics.max_step_mm_per_sqrt_v,
        numerics.root_time_tolerance_mm_per_sqrt_v,
        numerics.boundary_root_tolerance_mm,
        numerics.momentum_tolerance_sqrt_v,
        numerics.normal_energy_tolerance_v,
    )
    if any(not math.isfinite(value) or value <= 0.0 for value in positive):
        raise TransportError("transport numerical tolerances and max step must be positive and finite")
    integer_values = (numerics.event_samples_per_step, numerics.maximum_steps)
    if any(type(value) is not int or value <= 0 for value in integer_values):
        raise TransportError("transport event samples and maximum steps must be positive integers")
    if numerics.event_samples_per_step < 2:
        raise TransportError("transport needs at least two event samples per integration step")


def polygon_potential_region(
    name: str, vertices_yz_mm: Sequence[Sequence[float]], bias_v: float,
) -> PotentialRegion:
    """Build a finite convex-polygon constant-potential region.

    Vertices may be clockwise or counter-clockwise.  Degenerate polygons and
    repeated names are rejected by the transport entry point.
    """
    if not name:
        raise TransportError("polygon region name must be nonempty")
    if len(vertices_yz_mm) < 3 or any(len(point) != 2 for point in vertices_yz_mm):
        raise TransportError(f"{name} polygon needs at least three y-z vertices")
    vertices = tuple(
        (_finite(point[0], f"{name} vertex y"), _finite(point[1], f"{name} vertex z"))
        for point in vertices_yz_mm
    )
    twice_area = sum(
        start[0] * end[1] - start[1] * end[0]
        for start, end in zip(vertices, vertices[1:] + vertices[:1])
    )
    scale = max(1.0, *(abs(value) for point in vertices for value in point))
    if abs(twice_area) <= 128.0 * math.ulp(scale * scale):
        raise TransportError(f"{name} polygon is degenerate")
    orientation = 1.0 if twice_area > 0.0 else -1.0
    convexity_tolerance = 128.0 * math.ulp(scale * scale)
    for first, second, third in zip(vertices, vertices[1:] + vertices[:1], vertices[2:] + vertices[:2]):
        turn = (
            (second[0] - first[0]) * (third[1] - second[1])
            - (second[1] - first[1]) * (third[0] - second[0])
        )
        if orientation * turn <= convexity_tolerance:
            raise TransportError(f"{name} polygon must be strictly convex")
    boundaries: list[InterfaceBoundary] = []
    for index, (start, end) in enumerate(zip(vertices, vertices[1:] + vertices[:1])):
        edge_y, edge_z = end[0] - start[0], end[1] - start[1]
        length = math.hypot(edge_y, edge_z)
        if length <= 0.0:
            raise TransportError(f"{name} polygon has a zero-length edge")
        inward = (-orientation * edge_z / length, orientation * edge_y / length)

        def level(y: float, z: float, a=start, ey=edge_y, ez=edge_z, edge_length=length) -> float:
            return orientation * (ey * (z - a[1]) - ez * (y - a[0])) / edge_length

        def active(y: float, z: float, a=start, ey=edge_y, ez=edge_z, length2=length * length) -> bool:
            fraction = ((y - a[0]) * ey + (z - a[1]) * ez) / length2
            return 0.0 <= fraction <= 1.0

        boundaries.append(InterfaceBoundary(f"{name}.edge_{index}", level, lambda _y, _z, n=inward: n, active))

    def contains(y: float, z: float) -> bool:
        return all(boundary.level(y, z) >= 0.0 for boundary in boundaries)

    return PotentialRegion(name, _finite(bias_v, f"{name} bias"), tuple(boundaries), contains)


def curved_strip_potential_region(
    name: str,
    y_span_mm: tuple[float, float],
    lower_z_mm: Callable[[float], float],
    upper_z_mm: Callable[[float], float],
    lower_dz_dy: Callable[[float], float],
    upper_dz_dy: Callable[[float], float],
    bias_v: float,
) -> PotentialRegion:
    """Build a finite curved band between two explicit z(y) boundaries."""
    if not name:
        raise TransportError("curved strip name must be nonempty")
    y0, y1 = (_finite(value, f"{name} y span") for value in y_span_mm)
    if not y0 < y1:
        raise TransportError(f"{name} y span must be ordered")
    for y in (y0, (y0 + y1) / 2.0, y1):
        if not _finite(lower_z_mm(y), f"{name} lower edge") < _finite(upper_z_mm(y), f"{name} upper edge"):
            raise TransportError(f"{name} curved strip must have positive width")

    def in_y(y: float, _z: float) -> bool:
        return y0 <= y <= y1

    # Native B-spline evaluators intentionally reject points outside their
    # active y-domain.  A constant endpoint extension is used only to define
    # a continuous root function there; ``contains_boundary_point`` still
    # rejects every root outside the real finite curve.
    def curve_y(y: float) -> float:
        return min(max(y, y0), y1)

    lower = InterfaceBoundary(
        f"{name}.lower",
        lambda y, z: z - lower_z_mm(curve_y(y)),
        lambda y, _z: _unit((-lower_dz_dy(y), 1.0), f"{name} lower normal"),
        in_y,
    )
    upper = InterfaceBoundary(
        f"{name}.upper",
        lambda y, z: upper_z_mm(curve_y(y)) - z,
        lambda y, _z: _unit((upper_dz_dy(y), -1.0), f"{name} upper normal"),
        in_y,
    )

    def within_z(y: float, z: float) -> bool:
        return lower_z_mm(y) <= z <= upper_z_mm(y)

    start = InterfaceBoundary(
        f"{name}.y_start", lambda y, _z: y - y0, lambda _y, _z: (1.0, 0.0), within_z,
    )
    end = InterfaceBoundary(
        f"{name}.y_end", lambda y, _z: y1 - y, lambda _y, _z: (-1.0, 0.0), within_z,
    )

    def contains(y: float, z: float) -> bool:
        return y0 <= y <= y1 and lower_z_mm(y) <= z <= upper_z_mm(y)

    return PotentialRegion(name, _finite(bias_v, f"{name} bias"), (lower, upper, start, end), contains)


def plane_stop_target(
    name: str,
    normal_yz: tuple[float, float],
    offset_mm: float,
    *,
    direction: int = 0,
    contains_target_point: Callable[[float, float], bool] | None = None,
) -> StopTarget:
    """Build an explicit plane ``normal dot (y,z) = offset`` stop target."""
    if not name:
        raise TransportError("stop target name must be nonempty")
    normal = _unit(normal_yz, f"{name} normal")
    offset = _finite(offset_mm, f"{name} offset")
    active = contains_target_point or (lambda _y, _z: True)
    return StopTarget(
        name,
        lambda y, z: normal[0] * y + normal[1] * z - offset,
        lambda _y, _z: normal,
        active,
        direction,
    )


def _hamiltonian(
    state: PhaseState2D,
    charge_sign: int,
    mirror_potential_v: AxialField,
    regions_by_name: dict[str, PotentialRegion],
    active_names: set[str],
) -> float:
    constant = sum(regions_by_name[name].bias_v for name in active_names)
    return (
        state.u_y_sqrt_v**2
        + state.u_z_sqrt_v**2
        + charge_sign * (_finite(mirror_potential_v(state.z_mm), "mirror potential") + constant)
    )


def _state(time: float, values: Sequence[float]) -> PhaseState2D:
    return PhaseState2D(float(time), *(float(value) for value in values))


def _first_root(
    dense: Callable[[float], np.ndarray],
    start: float,
    end: float,
    objects: Iterable[tuple[str, ScalarField, Callable[[float, float], bool]]],
    numerics: TransportNumerics,
    consumed_root: tuple[str, int] | None,
) -> tuple[float, str] | None:
    sample_times = np.linspace(start, end, numerics.event_samples_per_step + 1)
    candidates: list[tuple[float, str]] = []
    for name, level, active in objects:
        values = []
        for time in sample_times:
            point = dense(float(time))
            values.append(_finite(level(float(point[0]), float(point[1])), f"{name} level"))
        for index in range(len(sample_times) - 1):
            left_t, right_t = float(sample_times[index]), float(sample_times[index + 1])
            left, right = values[index], values[index + 1]
            consumed_here = (
                index == 0
                and consumed_root is not None
                and name == consumed_root[0]
                and abs(left) <= numerics.boundary_root_tolerance_mm
            )
            root: float | None = None
            if consumed_here:
                departure_sign = consumed_root[1]
                if abs(right) <= numerics.boundary_root_tolerance_mm:
                    root = right_t
                elif departure_sign * right < 0.0:
                    # Divide out only the already-owned root at the exact
                    # interval start.  This exposes a genuine second root in
                    # the same sample interval without displacing geometry.
                    def after_consumed(time: float) -> float:
                        if time == left_t:
                            return float(departure_sign)
                        point = dense(time)
                        return level(float(point[0]), float(point[1])) / (time - left_t)

                    root = brentq(
                        after_consumed,
                        left_t,
                        right_t,
                        xtol=numerics.root_time_tolerance_mm_per_sqrt_v,
                        rtol=max(4.0 * math.ulp(1.0), numerics.root_time_tolerance_mm_per_sqrt_v),
                    )
            elif abs(left) <= numerics.boundary_root_tolerance_mm:
                root = left_t
            elif left * right < 0.0:
                root = brentq(
                    lambda time: level(float(dense(time)[0]), float(dense(time)[1])),
                    left_t,
                    right_t,
                    xtol=numerics.root_time_tolerance_mm_per_sqrt_v,
                    rtol=max(4.0 * math.ulp(1.0), numerics.root_time_tolerance_mm_per_sqrt_v),
                )
            elif abs(right) <= numerics.boundary_root_tolerance_mm:
                root = right_t
            if root is None or root <= start + numerics.root_time_tolerance_mm_per_sqrt_v:
                continue
            point = dense(root)
            if active(float(point[0]), float(point[1])):
                candidates.append((root, name))
                break
    if not candidates:
        return None
    candidates.sort()
    first_time = candidates[0][0]
    simultaneous = [
        item for item in candidates
        if abs(item[0] - first_time) <= numerics.root_time_tolerance_mm_per_sqrt_v
    ]
    if len(simultaneous) != 1:
        names = ", ".join(item[1] for item in simultaneous)
        raise TransportError(f"simultaneous boundary/target event is ambiguous: {names}")
    return simultaneous[0]


def propagate_segmented_hamiltonian(
    initial_state: PhaseState2D,
    *,
    charge_sign: int,
    mirror_potential_v: AxialField,
    mirror_gradient_v_per_mm: AxialField,
    potential_regions: Sequence[PotentialRegion],
    stop_targets: Sequence[StopTarget],
    maximum_reduced_time_mm_per_sqrt_v: float,
    numerics: TransportNumerics,
    stop_on_transmitted_entry_region_names: Sequence[str] = (),
) -> TransportResult:
    """Propagate until a stop target, selected region entry, or time limit.

    Interfaces are owned by a state machine at their exact root.  After a
    jump the consumed root is ignored only at that same integration start;
    no coordinate displacement is used.  A forbidden normal kinetic energy
    produces specular reflection and an explicit non-transmission event.
    Corner/vertex hits and tangencies fail closed because their continuation
    is not uniquely defined by the ideal hard-boundary model.
    """
    _validate_numerics(numerics)
    if charge_sign not in (-1, 1) or isinstance(charge_sign, bool):
        raise TransportError("charge_sign must be +1 or -1")
    end_time = _finite(maximum_reduced_time_mm_per_sqrt_v, "maximum reduced time")
    values = [
        _finite(initial_state.y_mm, "initial y"),
        _finite(initial_state.z_mm, "initial z"),
        _finite(initial_state.u_y_sqrt_v, "initial u_y"),
        _finite(initial_state.u_z_sqrt_v, "initial u_z"),
    ]
    time = _finite(initial_state.reduced_time_mm_per_sqrt_v, "initial reduced time")
    if end_time <= time:
        raise TransportError("maximum reduced time must follow the initial state")
    regions_by_name = {region.name: region for region in potential_regions}
    if len(regions_by_name) != len(potential_regions):
        raise TransportError("potential region names must be unique")
    entry_stop_names = tuple(stop_on_transmitted_entry_region_names)
    if (
        len(set(entry_stop_names)) != len(entry_stop_names)
        or any(not isinstance(name, str) or not name for name in entry_stop_names)
        or not set(entry_stop_names) <= set(regions_by_name)
    ):
        raise TransportError(
            "transmitted-entry stop names must be unique nonempty potential-region names"
        )
    entry_stop_name_set = set(entry_stop_names)
    boundaries: dict[str, tuple[PotentialRegion, InterfaceBoundary]] = {}
    for region in potential_regions:
        if not region.name or not region.boundaries:
            raise TransportError("potential regions need nonempty names and boundaries")
        _finite(region.bias_v, f"{region.name} bias")
        for boundary in region.boundaries:
            if not boundary.name:
                raise TransportError("interface boundary names must be nonempty")
            if boundary.name in boundaries:
                raise TransportError("interface boundary names must be globally unique")
            boundaries[boundary.name] = (region, boundary)
    targets = {target.name: target for target in stop_targets}
    if len(targets) != len(stop_targets) or set(targets) & set(boundaries):
        raise TransportError("stop target and interface names must be globally unique")
    if any(not target.name for target in stop_targets):
        raise TransportError("stop target names must be nonempty")
    if any(type(target.direction) is not int or target.direction not in (-1, 0, 1) for target in stop_targets):
        raise TransportError("stop target direction must be -1, 0, or +1")
    for name, (_region, boundary) in boundaries.items():
        if abs(boundary.level(values[0], values[1])) <= numerics.boundary_root_tolerance_mm and boundary.contains_boundary_point(values[0], values[1]):
            raise TransportError(f"initial state lies on ambiguous interface {name}")
    active_names = {region.name for region in potential_regions if region.contains(values[0], values[1])}
    state0 = _state(time, values)
    initial_h = _hamiltonian(state0, charge_sign, mirror_potential_v, regions_by_name, active_names)
    max_residual = 0.0
    events: list[TransportEvent] = []
    consumed_root: tuple[str, int] | None = None

    def rhs(_time: float, phase: np.ndarray) -> tuple[float, float, float, float]:
        gradient = _finite(mirror_gradient_v_per_mm(float(phase[1])), "mirror gradient")
        return float(phase[2]), float(phase[3]), 0.0, -0.5 * charge_sign * gradient

    for _step in range(numerics.maximum_steps):
        next_time = min(end_time, time + numerics.max_step_mm_per_sqrt_v)
        solution = solve_ivp(
            rhs,
            (time, next_time),
            values,
            rtol=numerics.relative_tolerance,
            atol=numerics.absolute_tolerance,
            max_step=numerics.max_step_mm_per_sqrt_v,
            dense_output=True,
        )
        if not solution.success or solution.sol is None:
            raise TransportError(f"Hamiltonian integration failed: {solution.message}")
        scan_objects = [
            (name, boundary.level, boundary.contains_boundary_point)
            for name, (_region, boundary) in boundaries.items()
        ] + [
            (name, target.level, target.contains_target_point) for name, target in targets.items()
        ]
        root = _first_root(solution.sol, time, next_time, scan_objects, numerics, consumed_root)
        if root is None:
            values = [float(value) for value in solution.y[:, -1]]
            time = next_time
            current = _state(time, values)
            max_residual = max(
                max_residual,
                abs(_hamiltonian(current, charge_sign, mirror_potential_v, regions_by_name, active_names) - initial_h),
            )
            consumed_root = None
            if time >= end_time:
                break
            continue

        root_time, name = root
        values = [float(value) for value in solution.sol(root_time)]
        time = root_time
        before = _state(time, values)
        if name in targets:
            target = targets[name]
            normal = _unit(target.positive_normal(before.y_mm, before.z_mm), f"{name} normal")
            crossing = before.u_y_sqrt_v * normal[0] + before.u_z_sqrt_v * normal[1]
            if abs(crossing) <= numerics.momentum_tolerance_sqrt_v:
                raise TransportError(f"trajectory is tangent to stop target {name}")
            direction = 1 if crossing > 0.0 else -1
            if target.direction and direction != target.direction:
                consumed_root = (name, direction)
                continue
            residual = _hamiltonian(before, charge_sign, mirror_potential_v, regions_by_name, active_names) - initial_h
            events.append(TransportEvent("stop", name, before, before, None, None, None, 0.0, 0.0, 0.0, residual))
            max_residual = max(max_residual, abs(residual))
            return TransportResult(
                "stopped", state0, before, tuple(sorted(active_names)), tuple(events), initial_h,
                initial_h + residual, residual, max_residual,
            )

        region, boundary = boundaries[name]
        inward = _unit(boundary.inward_normal(before.y_mm, before.z_mm), f"{name} inward normal")
        is_inside = region.name in active_names
        forward = (-inward[0], -inward[1]) if is_inside else inward
        incident_normal = values[2] * forward[0] + values[3] * forward[1]
        if incident_normal <= numerics.momentum_tolerance_sqrt_v:
            raise TransportError(f"trajectory is tangent to or approaches the wrong side of {name}")
        tangent = (-forward[1], forward[0])
        tangent_before = values[2] * tangent[0] + values[3] * tangent[1]
        delta_v = -region.bias_v if is_inside else region.bias_v
        normal_after_squared = incident_normal**2 - charge_sign * delta_v
        kinetic_scale = max(1.0, values[2] ** 2 + values[3] ** 2, abs(delta_v))
        threshold = max(numerics.normal_energy_tolerance_v, 128.0 * math.ulp(kinetic_scale))
        if normal_after_squared <= threshold:
            values[2] -= 2.0 * incident_normal * forward[0]
            values[3] -= 2.0 * incident_normal * forward[1]
            transmitted = False
            applied_delta = 0.0
        else:
            normal_after = math.sqrt(normal_after_squared)
            values[2] = tangent_before * tangent[0] + normal_after * forward[0]
            values[3] = tangent_before * tangent[1] + normal_after * forward[1]
            transmitted = True
            applied_delta = delta_v
            if is_inside:
                active_names.remove(region.name)
            else:
                active_names.add(region.name)
        after = _state(time, values)
        tangent_after = values[2] * tangent[0] + values[3] * tangent[1]
        residual = _hamiltonian(after, charge_sign, mirror_potential_v, regions_by_name, active_names) - initial_h
        max_residual = max(max_residual, abs(residual))
        event = TransportEvent(
            "interface", name, before, after, region.name, not is_inside, transmitted,
            delta_v, applied_delta, tangent_after - tangent_before, residual,
        )
        events.append(event)
        if transmitted and not is_inside and region.name in entry_stop_name_set:
            return TransportResult(
                "stopped_on_transmitted_entry",
                state0,
                after,
                tuple(sorted(active_names)),
                tuple(events),
                initial_h,
                initial_h + residual,
                residual,
                max_residual,
            )
        consumed_root = (name, 1 if region.name in active_names else -1)
    else:
        raise TransportError("transport exceeded the configured maximum integration steps")

    final = _state(time, values)
    final_h = _hamiltonian(final, charge_sign, mirror_potential_v, regions_by_name, active_names)
    residual = final_h - initial_h
    max_residual = max(max_residual, abs(residual))
    return TransportResult(
        "maximum_reduced_time", state0, final, tuple(sorted(active_names)), tuple(events),
        initial_h, final_h, residual, max_residual,
    )
