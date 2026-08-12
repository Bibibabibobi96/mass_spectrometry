"""Solver-independent reference for a two-region orthogonal space-focusing accelerator.

This module models the ideal one-dimensional Wiley--McLaren-type accelerator used by
``projects/single_reflection_oa_tof_mass_analyzer``.  Geometry lengths are in millimetres and electrode potentials
are in volts.  The default release position is the centre of the first gap.

The reference quantity is the first-order time-focus plane.  Its distance ``D`` is
measured from the grounded accelerator exit plane; it is not required to coincide
with that plane.  Mass-to-charge cancels from the focus-position equation.

The command-line interface remains compatible with the historical project contract
shape while adding explicit units, focus feasibility, and provenance-friendly output.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_CONSTANT_KG = 1.66053906892e-27


class PhysicsContractError(ValueError):
    """Raised when an input violates the ideal-model physics contract."""


@dataclass(frozen=True)
class AcceleratorState:
    """Derived ideal accelerator state at the nominal release position."""

    repeller_relative_v: float
    intermediate_relative_v: float
    exit_potential_v: float
    gap1_mm: float
    gap2_mm: float
    release_position_mm: float
    field1_v_per_mm: float
    field2_v_per_mm: float
    nominal_energy_per_charge_v: float
    energy_after_region1_per_charge_v: float
    first_order_focus_drift_mm: float
    focus_is_downstream: bool


@dataclass(frozen=True)
class PhaseSpaceMatchedVoltagePair:
    """Fixed-geometry voltage pair matched to a measured axial phase-space slope."""

    repeller_v: float
    intermediate_v: float
    exit_v: float
    gap1_voltage_drop_v: float
    nominal_energy_per_charge_v: float
    release_position_mm: float
    mean_initial_velocity_m_per_s: float
    velocity_slope_m_per_s_per_mm: float
    focus_drift_mm: float
    time_derivative_s_per_mm: float


@dataclass(frozen=True)
class FiniteIntervalMatchedVoltagePair:
    """Uniform-field voltage pair minimizing time spread over a finite source width."""

    repeller_v: float
    intermediate_v: float
    exit_v: float
    gap1_voltage_drop_v: float
    stage1_field_v_per_mm: float
    stage2_field_v_per_mm: float
    nominal_energy_per_charge_v: float
    source_center_mm: float
    source_full_width_mm: float
    source_minimum_mm: float
    source_maximum_mm: float
    mean_initial_velocity_m_per_s: float
    velocity_slope_m_per_s_per_mm: float
    focus_drift_mm: float
    sample_count: int
    theoretical_rms_time_ns: float
    theoretical_peak_to_peak_time_ns: float
    canonical_repeller_z_mm: float
    canonical_grid1_z_mm: float
    canonical_grid2_z_mm: float


@dataclass(frozen=True)
class LinearPhaseSpaceTimingCoefficients:
    """Local timing coefficients along ``v_z(x)=v_c+kappa*(x-x_c)``.

    ``first_derivative`` and ``second_derivative`` are derivatives of the
    normalized accelerator time with respect to the *actual* energy per charge
    along the fitted phase-space line.  They can therefore replace the static
    source derivatives in the coupled reflectron solver.
    """

    electrostatic_energy_per_charge_v: float
    actual_energy_per_charge_v: float
    velocity_energy_root_v_sqrt: float
    velocity_slope_energy_root_v_sqrt_per_mm: float
    energy_position_first_v_per_mm: float
    energy_position_second_v_per_mm2: float
    normalized_time_energy_first_mm_per_v_sqrt_v: float
    normalized_time_energy_second_mm_per_v2_sqrt_v: float
    normalized_time_position_first_per_sqrt_v: float
    normalized_time_position_second_per_mm_sqrt_v: float
    first_derivative_at_focus: float
    second_derivative_at_focus: float


def _as_finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise PhysicsContractError(f"{name} must be finite")
    return result


def _require_positive(value: float, name: str) -> None:
    if value <= 0.0:
        raise PhysicsContractError(f"{name} must be > 0")


def _as_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise PhysicsContractError(f"{name} must be a nonnegative integer")
    numeric = _as_finite_float(value, name)
    if numeric < 0.0 or not numeric.is_integer():
        raise PhysicsContractError(f"{name} must be a nonnegative integer")
    return int(numeric)


def _relative_potentials(
    repeller_v: float,
    intermediate_v: float,
    exit_v: float,
) -> tuple[float, float]:
    repeller_relative = repeller_v - exit_v
    intermediate_relative = intermediate_v - exit_v
    if not repeller_relative > intermediate_relative > 0.0:
        raise PhysicsContractError(
            "require repeller_relative > intermediate_relative > 0; "
            "the exit potential is the reference"
        )
    return repeller_relative, intermediate_relative


def accelerator_state(
    repeller_v: float,
    intermediate_v: float,
    gap1_mm: float,
    gap2_mm: float,
    *,
    exit_v: float = 0.0,
    release_position_mm: float | None = None,
    require_downstream_focus: bool = True,
    zero_tolerance_mm: float | None = None,
) -> AcceleratorState:
    """Return the ideal state and first-order time-focus distance.

    Coordinates are measured from the repeller plane.  ``release_position_mm`` must
    lie strictly inside the first gap.  ``D`` is measured from the exit plane at
    ``gap1_mm + gap2_mm``.  A negative ``D`` means the mathematical focus lies
    upstream of the exit plane and is rejected by default.
    """

    repeller_v = _as_finite_float(repeller_v, "repeller_v")
    intermediate_v = _as_finite_float(intermediate_v, "intermediate_v")
    exit_v = _as_finite_float(exit_v, "exit_v")
    gap1_mm = _as_finite_float(gap1_mm, "gap1_mm")
    gap2_mm = _as_finite_float(gap2_mm, "gap2_mm")
    _require_positive(gap1_mm, "gap1_mm")
    _require_positive(gap2_mm, "gap2_mm")

    repeller_relative, intermediate_relative = _relative_potentials(
        repeller_v, intermediate_v, exit_v
    )
    release_position = (
        gap1_mm / 2.0
        if release_position_mm is None
        else _as_finite_float(release_position_mm, "release_position_mm")
    )
    if not 0.0 < release_position < gap1_mm:
        raise PhysicsContractError(
            "release_position_mm must lie strictly inside the first gap"
        )

    field1 = (repeller_relative - intermediate_relative) / gap1_mm
    field2 = intermediate_relative / gap2_mm
    nominal_energy = repeller_relative - field1 * release_position
    after_region1 = nominal_energy - intermediate_relative
    if after_region1 <= 0.0 or nominal_energy <= 0.0:
        raise PhysicsContractError("nominal ion must cross both acceleration regions")

    # Velocities with the common sqrt(q/m) factor removed.  This makes D explicitly
    # species independent while preserving the exact algebra.
    v2_bar = math.sqrt(2.0 * after_region1)
    v3_bar = math.sqrt(2.0 * nominal_energy)
    drift = (v3_bar**3 / field1) * (
        1.0 / v2_bar
        + (field1 / field2) * (1.0 / v3_bar - 1.0 / v2_bar)
    )
    if zero_tolerance_mm is None:
        zero_tolerance_mm = max(1.0e-12, 1.0e-10 * (gap1_mm + gap2_mm))
    elif zero_tolerance_mm < 0.0:
        raise PhysicsContractError("zero_tolerance_mm must be >= 0")
    if abs(drift) <= zero_tolerance_mm:
        drift = 0.0
    focus_is_downstream = drift >= 0.0
    if require_downstream_focus and drift < 0.0:
        raise PhysicsContractError(
            "first-order time focus lies upstream of the accelerator exit plane beyond "
            "the configured serialization tolerance"
        )

    return AcceleratorState(
        repeller_relative_v=repeller_relative,
        intermediate_relative_v=intermediate_relative,
        exit_potential_v=exit_v,
        gap1_mm=gap1_mm,
        gap2_mm=gap2_mm,
        release_position_mm=release_position,
        field1_v_per_mm=field1,
        field2_v_per_mm=field2,
        nominal_energy_per_charge_v=nominal_energy,
        energy_after_region1_per_charge_v=after_region1,
        first_order_focus_drift_mm=drift,
        focus_is_downstream=focus_is_downstream,
    )


def focus_drift_mm(
    u1_v: float,
    u2_v: float,
    d1_mm: float,
    d2_mm: float,
    *,
    exit_v: float = 0.0,
    release_position_mm: float | None = None,
    require_downstream_focus: bool = True,
    zero_tolerance_mm: float | None = None,
) -> float:
    """Return field-free drift from the accelerator exit to the first-order focus.

    The four positional arguments preserve the historical project API.  Here ``u1_v``
    is the repeller potential, ``u2_v`` is the intermediate-grid potential, and the
    exit plane is grounded unless ``exit_v`` is supplied.
    """

    return accelerator_state(
        u1_v,
        u2_v,
        d1_mm,
        d2_mm,
        exit_v=exit_v,
        release_position_mm=release_position_mm,
        require_downstream_focus=require_downstream_focus,
        zero_tolerance_mm=zero_tolerance_mm,
    ).first_order_focus_drift_mm


def normalized_time_to_plane_mm_sqrt_v(
    energy_per_charge_v: float,
    intermediate_relative_v: float,
    field1_v_per_mm: float,
    field2_v_per_mm: float,
    distance_after_exit_mm: float,
) -> float:
    """Return normalized time from release to a plane after the exit.

    The particle family is parameterized by its final energy per charge ``W``.  It is
    assumed to originate at rest at the corresponding position in the first gap.
    Actual time is

    ``t = 1e-3 * sqrt((m/q)/2) * tau``

    when ``tau`` is returned in mm/sqrt(V) and SI ``m/q`` is used.
    """

    w = _as_finite_float(energy_per_charge_v, "energy_per_charge_v")
    vg = _as_finite_float(intermediate_relative_v, "intermediate_relative_v")
    e1 = _as_finite_float(field1_v_per_mm, "field1_v_per_mm")
    e2 = _as_finite_float(field2_v_per_mm, "field2_v_per_mm")
    distance = _as_finite_float(distance_after_exit_mm, "distance_after_exit_mm")
    _require_positive(e1, "field1_v_per_mm")
    _require_positive(e2, "field2_v_per_mm")
    if w <= vg:
        raise PhysicsContractError(
            "energy_per_charge_v must exceed the intermediate potential so the ion "
            "crosses region 1"
        )
    if distance < 0.0:
        raise PhysicsContractError("distance_after_exit_mm must be >= 0")

    root_w = math.sqrt(w)
    root_after_region1 = math.sqrt(w - vg)
    return (
        2.0 * root_after_region1 / e1
        + 2.0 * (root_w - root_after_region1) / e2
        + distance / root_w
    )


def time_to_plane_s(
    energy_per_charge_v: float,
    mass_to_charge_th: float,
    intermediate_relative_v: float,
    field1_v_per_mm: float,
    field2_v_per_mm: float,
    distance_after_exit_mm: float,
) -> float:
    """Return physical flight time for a specified mass-to-charge ratio in Th."""

    mu = _as_finite_float(mass_to_charge_th, "mass_to_charge_th")
    _require_positive(mu, "mass_to_charge_th")
    tau = normalized_time_to_plane_mm_sqrt_v(
        energy_per_charge_v,
        intermediate_relative_v,
        field1_v_per_mm,
        field2_v_per_mm,
        distance_after_exit_mm,
    )
    mass_over_charge_si = mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    return 1.0e-3 * math.sqrt(mass_over_charge_si / 2.0) * tau


def time_to_fixed_plane_s(
    repeller_v: float,
    intermediate_v: float,
    gap1_mm: float,
    gap2_mm: float,
    release_position_mm: float,
    initial_velocity_m_per_s: float,
    focus_drift_mm: float,
    mass_to_charge_th: float,
    *,
    exit_v: float = 0.0,
) -> float:
    """Return exact 1-D time from a moving ion in gap 1 to a fixed focus plane."""

    state = accelerator_state(
        repeller_v,
        intermediate_v,
        gap1_mm,
        gap2_mm,
        exit_v=exit_v,
        release_position_mm=release_position_mm,
        require_downstream_focus=False,
    )
    drift = _as_finite_float(focus_drift_mm, "focus_drift_mm")
    velocity = _as_finite_float(
        initial_velocity_m_per_s, "initial_velocity_m_per_s"
    )
    mu = _as_finite_float(mass_to_charge_th, "mass_to_charge_th")
    _require_positive(mu, "mass_to_charge_th")
    if drift < 0.0:
        raise PhysicsContractError("focus_drift_mm must be >= 0")

    mass_over_charge_si = mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    acceleration1 = state.field1_v_per_mm * 1000.0 / mass_over_charge_si
    acceleration2 = state.field2_v_per_mm * 1000.0 / mass_over_charge_si
    distance1_m = (gap1_mm - release_position_mm) * 1.0e-3
    distance2_m = gap2_mm * 1.0e-3
    discriminant1 = velocity * velocity + 2.0 * acceleration1 * distance1_m
    if discriminant1 <= 0.0:
        raise PhysicsContractError("ion does not cross accelerator region 1")
    velocity1 = math.sqrt(discriminant1)
    time1 = (velocity1 - velocity) / acceleration1
    velocity2 = math.sqrt(
        velocity1 * velocity1 + 2.0 * acceleration2 * distance2_m
    )
    time2 = (velocity2 - velocity1) / acceleration2
    return time1 + time2 + drift * 1.0e-3 / velocity2


def match_finite_phase_space_interval(
    gap1_mm: float,
    gap2_mm: float,
    source_center_mm: float,
    source_full_width_mm: float,
    mean_initial_velocity_m_per_s: float,
    velocity_slope_m_per_s_per_mm: float,
    mass_to_charge_th: float,
    nominal_energy_per_charge_v: float,
    *,
    exit_v: float = 0.0,
    voltage_drop_bounds_v: tuple[float, float] = (100.0, 1200.0),
    sample_count: int = 1001,
    voltage_tolerance_v: float = 1.0e-8,
) -> FiniteIntervalMatchedVoltagePair:
    """Minimize ideal two-uniform-field timing RMS over a finite linear ``z-vz`` interval.

    Only the first-gap voltage drop is varied.  The nominal energy at the source
    centre, geometry, exit voltage and focus plane remain fixed; consequently the
    complete second region remains one uniform field.  The result is a numerical
    limit of this declared one-dimensional model, not a three-dimensional or
    full-instrument resolution limit.
    """
    gap1 = _as_finite_float(gap1_mm, "gap1_mm")
    gap2 = _as_finite_float(gap2_mm, "gap2_mm")
    center = _as_finite_float(source_center_mm, "source_center_mm")
    width = _as_finite_float(source_full_width_mm, "source_full_width_mm")
    mean_velocity = _as_finite_float(
        mean_initial_velocity_m_per_s, "mean_initial_velocity_m_per_s"
    )
    slope = _as_finite_float(
        velocity_slope_m_per_s_per_mm, "velocity_slope_m_per_s_per_mm"
    )
    mu = _as_finite_float(mass_to_charge_th, "mass_to_charge_th")
    energy = _as_finite_float(
        nominal_energy_per_charge_v, "nominal_energy_per_charge_v"
    )
    exit_potential = _as_finite_float(exit_v, "exit_v")
    tolerance = _as_finite_float(voltage_tolerance_v, "voltage_tolerance_v")
    for value, name in (
        (gap1, "gap1_mm"), (gap2, "gap2_mm"), (width, "source_full_width_mm"),
        (mu, "mass_to_charge_th"), (energy, "nominal_energy_per_charge_v"),
        (tolerance, "voltage_tolerance_v"),
    ):
        _require_positive(value, name)
    if sample_count < 11 or sample_count % 2 == 0:
        raise PhysicsContractError(
            "sample_count must be an odd integer >= 11"
        )
    source_minimum = center - width / 2.0
    source_maximum = center + width / 2.0
    if not 0.0 < source_minimum < source_maximum < gap1:
        raise PhysicsContractError("finite source interval must lie inside gap 1")
    if len(voltage_drop_bounds_v) != 2:
        raise PhysicsContractError("voltage_drop_bounds_v must contain two values")
    lower, upper = (
        _as_finite_float(voltage_drop_bounds_v[0], "voltage_drop_bounds_v[0]"),
        _as_finite_float(voltage_drop_bounds_v[1], "voltage_drop_bounds_v[1]"),
    )
    if not 0.0 < lower < upper:
        raise PhysicsContractError("voltage-drop bounds must satisfy 0 < lower < upper")

    positions = [
        source_minimum + width * index / (sample_count - 1)
        for index in range(sample_count)
    ]

    def voltage_pair(voltage_drop: float) -> tuple[float, float]:
        repeller = exit_potential + energy + voltage_drop * center / gap1
        intermediate = repeller - voltage_drop
        if intermediate <= exit_potential:
            raise PhysicsContractError(
                "finite-interval search makes the intermediate grid non-accelerating"
            )
        return repeller, intermediate

    derivative_step = min(1.0e-4, width / 1000.0)

    def derived_focus_drift(voltage_drop: float) -> float:
        repeller, intermediate = voltage_pair(voltage_drop)
        before_position = center - derivative_step
        after_position = center + derivative_step
        before_velocity = mean_velocity - slope * derivative_step
        after_velocity = mean_velocity + slope * derivative_step

        def derivative_at(drift_mm: float) -> float:
            before = time_to_fixed_plane_s(
                repeller, intermediate, gap1, gap2, before_position,
                before_velocity, drift_mm, mu, exit_v=exit_potential,
            )
            after = time_to_fixed_plane_s(
                repeller, intermediate, gap1, gap2, after_position,
                after_velocity, drift_mm, mu, exit_v=exit_potential,
            )
            return (after - before) / (2.0 * derivative_step)

        derivative_at_zero = derivative_at(0.0)
        derivative_at_one = derivative_at(1.0)
        slope_per_mm = derivative_at_one - derivative_at_zero
        if abs(slope_per_mm) <= 1.0e-30:
            raise PhysicsContractError("finite-interval focus derivative is singular")
        drift = -derivative_at_zero / slope_per_mm
        if drift < 0.0:
            raise PhysicsContractError("finite-interval focus lies upstream of grid2")
        return drift

    def timing_metrics(voltage_drop: float) -> tuple[float, float, float]:
        repeller, intermediate = voltage_pair(voltage_drop)
        try:
            drift = derived_focus_drift(voltage_drop)
        except PhysicsContractError:
            return math.inf, math.inf, math.nan
        times_ns = [
            time_to_fixed_plane_s(
                repeller, intermediate, gap1, gap2, position,
                mean_velocity + slope * (position - center), drift, mu,
                exit_v=exit_potential,
            ) * 1.0e9
            for position in positions
        ]
        mean_time = sum(times_ns) / sample_count
        rms = math.sqrt(
            sum((value - mean_time) ** 2 for value in times_ns) / sample_count
        )
        return rms, max(times_ns) - min(times_ns), drift

    # The declared problem has one physical degree of freedom.  A dense bracket
    # search prevents an assumed starting point from selecting the candidate;
    # golden-section refinement then resolves the best bracket deterministically.
    bracket_count = 201
    bracket_values = [
        lower + (upper - lower) * index / (bracket_count - 1)
        for index in range(bracket_count)
    ]
    bracket_objectives = [timing_metrics(value)[0] for value in bracket_values]
    if not any(math.isfinite(value) for value in bracket_objectives):
        raise PhysicsContractError("finite-interval voltage optimization is infeasible")
    best_index = min(range(bracket_count), key=bracket_objectives.__getitem__)
    left = bracket_values[max(0, best_index - 1)]
    right = bracket_values[min(bracket_count - 1, best_index + 1)]
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    c = right - ratio * (right - left)
    d = left + ratio * (right - left)
    fc = timing_metrics(c)[0]
    fd = timing_metrics(d)[0]
    while right - left > tolerance:
        if fc <= fd:
            right, d, fd = d, c, fc
            c = right - ratio * (right - left)
            fc = timing_metrics(c)[0]
        else:
            left, c, fc = c, d, fd
            d = left + ratio * (right - left)
            fd = timing_metrics(d)[0]
    optimum = (left + right) / 2.0
    rms_ns, peak_to_peak_ns, drift = timing_metrics(optimum)
    repeller, intermediate = voltage_pair(optimum)
    return FiniteIntervalMatchedVoltagePair(
        repeller_v=repeller,
        intermediate_v=intermediate,
        exit_v=exit_potential,
        gap1_voltage_drop_v=optimum,
        stage1_field_v_per_mm=optimum / gap1,
        stage2_field_v_per_mm=(intermediate - exit_potential) / gap2,
        nominal_energy_per_charge_v=energy,
        source_center_mm=center,
        source_full_width_mm=width,
        source_minimum_mm=source_minimum,
        source_maximum_mm=source_maximum,
        mean_initial_velocity_m_per_s=mean_velocity,
        velocity_slope_m_per_s_per_mm=slope,
        focus_drift_mm=drift,
        sample_count=sample_count,
        theoretical_rms_time_ns=rms_ns,
        theoretical_peak_to_peak_time_ns=peak_to_peak_ns,
        canonical_repeller_z_mm=-(drift + gap2 + gap1),
        canonical_grid1_z_mm=-(drift + gap2),
        canonical_grid2_z_mm=-drift,
    )


def linear_phase_space_timing_coefficients(
    accelerator: AcceleratorState,
    mass_to_charge_th: float,
    mean_initial_velocity_m_per_s: float,
    velocity_slope_m_per_s_per_mm: float,
    focus_drift_mm: float,
) -> LinearPhaseSpaceTimingCoefficients:
    """Return first/second energy derivatives for a fitted linear ``z-vz`` beam.

    The independent coordinate is the accelerator release coordinate in mm.  The
    electrostatic energy is augmented by the incoming axial kinetic energy,
    ``W_actual = W_electrostatic + chi**2``, where
    ``chi = vz*sqrt((m/q)/2)``.  The returned derivatives use the repository's
    normalized-time unit, mm/sqrt(V).
    """

    mu = _as_finite_float(mass_to_charge_th, "mass_to_charge_th")
    velocity = _as_finite_float(
        mean_initial_velocity_m_per_s, "mean_initial_velocity_m_per_s"
    )
    slope = _as_finite_float(
        velocity_slope_m_per_s_per_mm, "velocity_slope_m_per_s_per_mm"
    )
    drift = _as_finite_float(focus_drift_mm, "focus_drift_mm")
    _require_positive(mu, "mass_to_charge_th")
    if drift < 0.0:
        raise PhysicsContractError("focus_drift_mm must be >= 0")

    mass_over_charge_si = mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    velocity_scale = math.sqrt(mass_over_charge_si / 2.0)
    chi = velocity * velocity_scale
    beta = slope * velocity_scale
    electrostatic_energy = accelerator.nominal_energy_per_charge_v
    actual_energy = electrostatic_energy + chi * chi
    if actual_energy <= accelerator.intermediate_relative_v:
        raise PhysicsContractError(
            "actual nominal energy must exceed the intermediate potential"
        )

    energy_first = -accelerator.field1_v_per_mm + 2.0 * chi * beta
    if abs(energy_first) <= 1.0e-15:
        raise PhysicsContractError(
            "actual energy is locally stationary in release position; energy "
            "derivatives are singular"
        )
    energy_second = 2.0 * beta * beta
    s2 = math.sqrt(actual_energy - accelerator.intermediate_relative_v)
    s3 = math.sqrt(actual_energy)
    e1 = accelerator.field1_v_per_mm
    e2 = accelerator.field2_v_per_mm

    b1 = (
        1.0 / (e1 * s2)
        + (1.0 / s3 - 1.0 / s2) / e2
        - drift / (2.0 * s3**3)
    )
    b2 = (
        -1.0 / (2.0 * e1 * s2**3)
        + (1.0 / s2**3 - 1.0 / s3**3) / (2.0 * e2)
        + 3.0 * drift / (4.0 * s3**5)
    )
    position_first = energy_first * b1 - 2.0 * beta / e1
    position_second = energy_second * b1 + energy_first * energy_first * b2
    first = position_first / energy_first
    second = (
        position_second * energy_first - position_first * energy_second
    ) / energy_first**3

    return LinearPhaseSpaceTimingCoefficients(
        electrostatic_energy_per_charge_v=electrostatic_energy,
        actual_energy_per_charge_v=actual_energy,
        velocity_energy_root_v_sqrt=chi,
        velocity_slope_energy_root_v_sqrt_per_mm=beta,
        energy_position_first_v_per_mm=energy_first,
        energy_position_second_v_per_mm2=energy_second,
        normalized_time_energy_first_mm_per_v_sqrt_v=b1,
        normalized_time_energy_second_mm_per_v2_sqrt_v=b2,
        normalized_time_position_first_per_sqrt_v=position_first,
        normalized_time_position_second_per_mm_sqrt_v=position_second,
        first_derivative_at_focus=first,
        second_derivative_at_focus=second,
    )


def match_phase_space_voltage_pair(
    gap1_mm: float,
    gap2_mm: float,
    release_position_mm: float,
    mean_initial_velocity_m_per_s: float,
    velocity_slope_m_per_s_per_mm: float,
    focus_drift_mm: float,
    mass_to_charge_th: float,
    nominal_energy_per_charge_v: float,
    *,
    exit_v: float = 0.0,
    voltage_drop_bounds_v: tuple[float, float] = (10.0, 1500.0),
    derivative_step_mm: float = 1.0e-4,
    derivative_tolerance_s_per_mm: float = 1.0e-15,
) -> PhaseSpaceMatchedVoltagePair:
    """Solve the stage-1 voltage drop for first-order ``z-vz`` time matching.

    Geometry, the fixed downstream focus plane, exit voltage, and nominal final
    energy at the measured mean release position remain fixed.  Only the repeller
    and intermediate-grid voltages are derived.  The root condition is the total
    time derivative along the measured linear phase-space relation.
    """

    gap1 = _as_finite_float(gap1_mm, "gap1_mm")
    gap2 = _as_finite_float(gap2_mm, "gap2_mm")
    release = _as_finite_float(release_position_mm, "release_position_mm")
    velocity = _as_finite_float(
        mean_initial_velocity_m_per_s, "mean_initial_velocity_m_per_s"
    )
    slope = _as_finite_float(
        velocity_slope_m_per_s_per_mm, "velocity_slope_m_per_s_per_mm"
    )
    drift = _as_finite_float(focus_drift_mm, "focus_drift_mm")
    mu = _as_finite_float(mass_to_charge_th, "mass_to_charge_th")
    nominal_energy = _as_finite_float(
        nominal_energy_per_charge_v, "nominal_energy_per_charge_v"
    )
    exit_potential = _as_finite_float(exit_v, "exit_v")
    step = _as_finite_float(derivative_step_mm, "derivative_step_mm")
    tolerance = _as_finite_float(
        derivative_tolerance_s_per_mm, "derivative_tolerance_s_per_mm"
    )
    for value, name in (
        (gap1, "gap1_mm"),
        (gap2, "gap2_mm"),
        (mu, "mass_to_charge_th"),
        (nominal_energy, "nominal_energy_per_charge_v"),
        (step, "derivative_step_mm"),
        (tolerance, "derivative_tolerance_s_per_mm"),
    ):
        _require_positive(value, name)
    if not step < min(release, gap1 - release):
        raise PhysicsContractError(
            "derivative_step_mm must remain inside accelerator gap 1"
        )
    if drift < 0.0:
        raise PhysicsContractError("focus_drift_mm must be >= 0")
    if len(voltage_drop_bounds_v) != 2:
        raise PhysicsContractError("voltage_drop_bounds_v must contain two values")
    lower = _as_finite_float(voltage_drop_bounds_v[0], "voltage_drop_bounds_v[0]")
    upper = _as_finite_float(voltage_drop_bounds_v[1], "voltage_drop_bounds_v[1]")
    if not 0.0 < lower < upper:
        raise PhysicsContractError("voltage-drop bounds must satisfy 0 < lower < upper")

    def voltages(voltage_drop: float) -> tuple[float, float]:
        # W = Vrep - E1*s at the measured mean release position.
        repeller = exit_potential + nominal_energy + voltage_drop * release / gap1
        intermediate = repeller - voltage_drop
        if intermediate <= exit_potential:
            raise PhysicsContractError(
                "voltage-drop search makes the intermediate grid non-accelerating"
            )
        return repeller, intermediate

    def derivative(voltage_drop: float) -> float:
        repeller, intermediate = voltages(voltage_drop)
        before = time_to_fixed_plane_s(
            repeller,
            intermediate,
            gap1,
            gap2,
            release - step,
            velocity - slope * step,
            drift,
            mu,
            exit_v=exit_potential,
        )
        after = time_to_fixed_plane_s(
            repeller,
            intermediate,
            gap1,
            gap2,
            release + step,
            velocity + slope * step,
            drift,
            mu,
            exit_v=exit_potential,
        )
        return (after - before) / (2.0 * step)

    lower_value = derivative(lower)
    upper_value = derivative(upper)
    if lower_value == 0.0:
        root = lower
    elif upper_value == 0.0:
        root = upper
    elif lower_value * upper_value > 0.0:
        raise PhysicsContractError(
            "phase-space time derivative has no bracketed voltage-drop root"
        )
    else:
        for _ in range(100):
            root = 0.5 * (lower + upper)
            value = derivative(root)
            if abs(value) <= tolerance:
                break
            if lower_value * value <= 0.0:
                upper = root
            else:
                lower = root
                lower_value = value
        else:
            raise PhysicsContractError("phase-space voltage match did not converge")

    repeller, intermediate = voltages(root)
    residual = derivative(root)
    return PhaseSpaceMatchedVoltagePair(
        repeller_v=repeller,
        intermediate_v=intermediate,
        exit_v=exit_potential,
        gap1_voltage_drop_v=root,
        nominal_energy_per_charge_v=nominal_energy,
        release_position_mm=release,
        mean_initial_velocity_m_per_s=velocity,
        velocity_slope_m_per_s_per_mm=slope,
        focus_drift_mm=drift,
        time_derivative_s_per_mm=residual,
    )


def compact_exit_focus_bound(
    nominal_energy_per_charge_v: float,
    spatial_energy_half_range_v: float,
    source_full_width_mm: float,
    minimum_gap1_mm: float,
) -> dict[str, float]:
    """Return the closed-form ``D = 0`` compactness bound.

    This is a special local bound, not an oa-TOF instrument optimum.  It assumes a
    centred source, zero initial axial velocity, uniform fields, and permits the
    first-order focus to lie exactly on the accelerator exit plane.
    """

    w0 = _as_finite_float(
        nominal_energy_per_charge_v, "nominal_energy_per_charge_v"
    )
    dw = _as_finite_float(spatial_energy_half_range_v, "spatial_energy_half_range_v")
    width = _as_finite_float(source_full_width_mm, "source_full_width_mm")
    gap_min = _as_finite_float(minimum_gap1_mm, "minimum_gap1_mm")
    for value, name in (
        (w0, "nominal_energy_per_charge_v"),
        (dw, "spatial_energy_half_range_v"),
        (width, "source_full_width_mm"),
        (gap_min, "minimum_gap1_mm"),
    ):
        _require_positive(value, name)

    gap1 = max(width, gap_min)
    r = w0 / dw
    s = gap1 / width
    if not s < r:
        raise PhysicsContractError(
            "require gap1/source_width < nominal_energy/spatial_energy_half_range; "
            "otherwise the intermediate electrode potential is non-positive"
        )

    field1 = 2.0 * dw / width
    repeller = w0 + dw * s
    intermediate = w0 - dw * s
    rho = math.sqrt(r) / (math.sqrt(r) - math.sqrt(s))
    field2 = field1 / rho
    gap2 = 0.5 * width * (r + math.sqrt(r * s))
    total = 0.5 * width * (r + 2.0 * s + math.sqrt(r * s))
    return {
        "nominal_energy_per_charge_V": w0,
        "spatial_energy_half_range_V": dw,
        "source_full_width_mm": width,
        "minimum_gap1_mm": gap_min,
        "r": r,
        "s": s,
        "gap1_mm": gap1,
        "gap2_mm": gap2,
        "field1_V_per_mm": field1,
        "field2_V_per_mm": field2,
        "repeller_relative_V": repeller,
        "intermediate_relative_V": intermediate,
        "field_ratio_E1_over_E2": rho,
        "focus_drift_after_exit_mm": 0.0,
        "compact_accelerator_length_mm": total,
        "is_instrument_optimum": False,
    }


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise PhysicsContractError(f"missing required key; expected one of {keys}")


def _derive_reference_focus(reference: Mapping[str, Any]) -> float:
    voltage = reference["electrodes_V"]
    exit_v = float(voltage.get("exit", voltage.get("grid2", 0.0)))
    drift = focus_drift_mm(
        float(_first_present(voltage, "repeller", "u1")),
        float(_first_present(voltage, "grid1", "intermediate", "u2")),
        float(_first_present(reference, "d1_mm", "gap1_mm")),
        float(_first_present(reference, "d2_mm", "gap2_mm")),
        exit_v=exit_v,
        release_position_mm=reference.get("release_position_mm"),
        require_downstream_focus=True,
    )
    return (
        float(reference["assembly_translation_z_mm"])
        + float(_first_present(reference, "d1_mm", "gap1_mm"))
        + float(_first_present(reference, "d2_mm", "gap2_mm"))
        + drift
    )


def derive(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Derive accelerator geometry and focus coordinates from a project contract."""

    design = contract["design"]
    geometry = design["local_geometry_mm"]
    voltage = design["electrodes_V"]

    gap1 = float(_first_present(geometry, "gap1", "d1"))
    gap2 = float(_first_present(geometry, "gap2", "d2"))
    repeller = float(_first_present(voltage, "repeller", "u1"))
    intermediate = float(_first_present(voltage, "grid1", "intermediate", "u2"))
    exit_v = float(voltage.get("exit", voltage.get("grid2", 0.0)))

    release_position = geometry.get("release_position")
    if release_position is None:
        release_fraction = float(design.get("release_center_fraction", 0.5))
        if not 0.0 < release_fraction < 1.0:
            raise PhysicsContractError("release_center_fraction must be in (0, 1)")
        release_position = release_fraction * gap1

    state = accelerator_state(
        repeller,
        intermediate,
        gap1,
        gap2,
        exit_v=exit_v,
        release_position_mm=float(release_position),
        require_downstream_focus=bool(design.get("require_downstream_focus", True)),
        zero_tolerance_mm=(
            None
            if "focus_zero_tolerance_mm" not in design
            else float(design["focus_zero_tolerance_mm"])
        ),
    )

    ring_pitch_raw = geometry.get("ring_pitch")
    ring_count_raw = geometry.get("ring_count")
    ring_pitch: float | None = None
    ring_count: int | None = None
    local_centers: list[float] = []
    if ring_pitch_raw is not None or ring_count_raw is not None:
        if ring_pitch_raw is None or ring_count_raw is None:
            raise PhysicsContractError(
                "ring_pitch and ring_count must be supplied together"
            )
        ring_pitch = float(ring_pitch_raw)
        ring_count = _as_nonnegative_int(ring_count_raw, "ring_count")
        _require_positive(ring_pitch, "ring_pitch")
        expected_gap2 = (ring_count + 1) * ring_pitch
        tolerance = max(1.0e-12, abs(gap2) * 1.0e-12)
        if not math.isclose(gap2, expected_gap2, rel_tol=0.0, abs_tol=tolerance):
            raise PhysicsContractError(
                "gap2/d2 must equal (ring_count + 1) * ring_pitch"
            )
        local_centers = [gap1 + k * ring_pitch for k in range(1, ring_count + 1)]

    local_exit = gap1 + gap2
    local_focus = local_exit + state.first_order_focus_drift_mm
    reference = design.get("reference_geometry")
    if reference:
        target_focus = _derive_reference_focus(reference)
        translation = target_focus - local_focus
        reference_focus = target_focus
    elif "target_global_focus_z_mm" in design:
        target_focus = float(design["target_global_focus_z_mm"])
        translation = target_focus - local_focus
        reference_focus = None
    else:
        translation = float(design.get("assembly_translation_z_mm", 0.0))
        target_focus = translation + local_focus
        reference_focus = None

    result: dict[str, Any] = {
        "model_id": "oaaccelerator.two_region_space_focus.ideal_1d.v2",
        "length_unit": "mm",
        "potential_unit": "V",
        "energy_per_charge_unit": "V",
        "d1_mm": gap1,
        "d2_mm": gap2,
        "gap1_mm": gap1,
        "gap2_mm": gap2,
        "release_position_local_mm": state.release_position_mm,
        "field1_V_per_mm": state.field1_v_per_mm,
        "field2_V_per_mm": state.field2_v_per_mm,
        "nominal_energy_per_charge_V": state.nominal_energy_per_charge_v,
        "energy_after_region1_per_charge_V": (
            state.energy_after_region1_per_charge_v
        ),
        "focus_drift_after_grid2_mm": state.first_order_focus_drift_mm,
        "first_order_focus_drift_after_exit_mm": (
            state.first_order_focus_drift_mm
        ),
        "focus_is_downstream": state.focus_is_downstream,
        "grid2_local_z_mm": local_exit,
        "accelerator_exit_local_z_mm": local_exit,
        "focus_local_z_mm": local_focus,
        "first_order_focus_local_z_mm": local_focus,
        "assembly_translation_z_mm": translation,
        "repeller_global_z_mm": translation,
        "grid1_global_z_mm": translation + gap1,
        "grid2_global_z_mm": translation + local_exit,
        "accelerator_exit_global_z_mm": translation + local_exit,
        "focus_global_z_mm": translation + local_focus,
        "first_order_focus_global_z_mm": translation + local_focus,
        "canonical_origin_shift_z_mm": -target_focus,
        "canonical_repeller_z_mm": translation - target_focus,
        "canonical_grid1_z_mm": translation + gap1 - target_focus,
        "canonical_grid2_z_mm": translation + local_exit - target_focus,
        "canonical_focus_and_detector_z_mm": (
            translation + local_focus - target_focus
        ),
        "formal_use_requires": [
            "project baseline/resolved contract",
            "3D field and trajectory validation",
            "shared FWHM analysis contract",
        ],
    }
    if ring_pitch is not None and ring_count is not None:
        result.update(
            {
                "ring_pitch_mm": ring_pitch,
                "ring_count": ring_count,
                "ring_centers_local_mm": local_centers,
                "ring_centers_global_mm": [translation + z for z in local_centers],
            }
        )
    if reference_focus is not None:
        result["reference_global_focus_z_mm"] = reference_focus
        result["reference_focus_drift_after_grid2_mm"] = (
            reference_focus
            - float(reference["assembly_translation_z_mm"])
            - float(_first_present(reference, "d1_mm", "gap1_mm"))
            - float(_first_present(reference, "d2_mm", "gap2_mm"))
        )
    return result


def _assert_expected(
    actual: Any,
    expected: Any,
    path: str,
    *,
    abs_tol: float,
    rel_tol: float,
) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise SystemExit(f"MISMATCH {path}: actual is not a mapping")
        for key, value in expected.items():
            if key not in actual:
                raise SystemExit(f"MISMATCH {path}.{key}: missing actual key")
            _assert_expected(
                actual[key],
                value,
                f"{path}.{key}",
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
        return
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes)):
            raise SystemExit(f"MISMATCH {path}: actual is not a sequence")
        if len(actual) != len(expected):
            raise SystemExit(
                f"MISMATCH {path}: actual length={len(actual)} expected={len(expected)}"
            )
        for index, (a_value, e_value) in enumerate(zip(actual, expected, strict=True)):
            _assert_expected(
                a_value,
                e_value,
                f"{path}[{index}]",
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not math.isclose(
            float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol
        ):
            raise SystemExit(
                f"MISMATCH {path}: actual={actual!r} expected={expected!r}"
            )
        return
    if actual != expected:
        raise SystemExit(f"MISMATCH {path}: actual={actual!r} expected={expected!r}")


def run_self_test() -> None:
    """Run deterministic algebra and compatibility checks."""

    # Historical centred-source expression.
    u1, u2, d1, d2 = 4060.0, 3940.0, 3.0, 112.247459
    e1 = (u1 - u2) / d1
    e2 = u2 / d2
    v2 = math.sqrt(u1 - u2)
    v3 = math.sqrt(u1 + u2)
    historical = (v3**3 / e1) * (
        1.0 / v2 + (e1 / e2) * (1.0 / v3 - 1.0 / v2)
    )
    current = focus_drift_mm(u1, u2, d1, d2, require_downstream_focus=False)
    if not math.isclose(current, historical, rel_tol=0.0, abs_tol=1.0e-12):
        raise AssertionError("historical centred-source formula changed")

    # Equal fields reduce to D = 2 * (distance from release point to exit).
    equal_state = accelerator_state(30.0, 20.0, 10.0, 20.0)
    expected_equal = 2.0 * (10.0 + 20.0 - 5.0)
    if not math.isclose(
        equal_state.first_order_focus_drift_mm,
        expected_equal,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise AssertionError("equal-field degeneration failed")

    # Closed-form D=0 bound, including an active mechanical lower gap.
    bound = compact_exit_focus_bound(4000.0, 20.0, 1.0, 3.0)
    state = accelerator_state(
        bound["repeller_relative_V"],
        bound["intermediate_relative_V"],
        bound["gap1_mm"],
        bound["gap2_mm"],
        require_downstream_focus=False,
    )
    if abs(state.first_order_focus_drift_mm) > 1.0e-9:
        raise AssertionError("compact D=0 bound does not focus at exit")
    expected_total = 0.5 * (200.0 + 6.0 + math.sqrt(600.0))
    if not math.isclose(
        bound["compact_accelerator_length_mm"],
        expected_total,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise AssertionError("general closed-form compactness bound failed")

    # Physical time must scale as sqrt(m/z).
    tau_args = (
        state.nominal_energy_per_charge_v,
        state.intermediate_relative_v,
        state.field1_v_per_mm,
        state.field2_v_per_mm,
        state.first_order_focus_drift_mm,
    )
    t100 = time_to_plane_s(tau_args[0], 100.0, *tau_args[1:])
    t400 = time_to_plane_s(tau_args[0], 400.0, *tau_args[1:])
    if not math.isclose(t400 / t100, 2.0, rel_tol=1.0e-12):
        raise AssertionError("mass-to-charge time scaling failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive an ideal two-region orthogonal accelerator time focus."
    )
    parser.add_argument("contract", type=Path, nargs="?")
    parser.add_argument("--write-derived", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print("ACCELERATOR_TIME_FOCUS_SELF_TEST=PASS")
        if args.contract is None:
            return 0
    if args.contract is None:
        parser.error("contract is required unless --self-test is used")

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = derive(contract)
    tolerance = contract.get("expected_tolerance", {})
    abs_tol = float(tolerance.get("absolute", 1.0e-10))
    rel_tol = float(tolerance.get("relative", 1.0e-12))
    expected = contract.get("expected_derived", {})
    _assert_expected(
        result,
        expected,
        "expected_derived",
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.write_derived:
        args.write_derived.parent.mkdir(parents=True, exist_ok=True)
        args.write_derived.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("ACCELERATOR_TIME_FOCUS_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
