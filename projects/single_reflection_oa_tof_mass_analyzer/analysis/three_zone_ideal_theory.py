"""Exact accelerator--reflectron coupled oa-TOF theory.

Accelerator-only states, source mapping and first-focus equations are imported
from the orthogonal_accelerator provider. This module owns reflectron geometry,
source-to-detector timing and the instrument's engineering acceptance checks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG as ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C as ELEMENTARY_CHARGE_C,
)
from projects.orthogonal_accelerator.analysis.three_zone_ideal_theory import (
    TheoryDomainError as TheoryDomainError,
    AffineSource as AffineSource,
    OuterGeometry as OuterGeometry,
    ThreeZoneState as ThreeZoneState,
    derive_three_zone_state as derive_three_zone_state,
    source_energy_per_charge as source_energy_per_charge,
    source_coordinate_for_energy as source_coordinate_for_energy,
    derive_first_order_focus_drift as derive_first_order_focus_drift,
    exact_accelerator_normalized_time as exact_accelerator_normalized_time,
    exact_accelerator_normalized_time_from_state as exact_accelerator_normalized_time_from_state,
    compute_accelerator_time_derivatives as compute_accelerator_time_derivatives,
)

def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise TheoryDomainError(f"{name} must be finite")
    return result


def _positive(value: float, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise TheoryDomainError(f"{name} must be > 0")
    return result


@dataclass(frozen=True)
class ReflectronGeometry:
    """Fixed ideal two-stage reflectron and field-free path lengths."""

    stage1_length_mm: float
    stage2_length_mm: float
    upstream_drift_mm: float
    downstream_drift_mm: float

    def __post_init__(self) -> None:
        _positive(self.stage1_length_mm, "stage1_length_mm")
        _positive(self.stage2_length_mm, "stage2_length_mm")
        _positive(self.upstream_drift_mm, "upstream_drift_mm")
        _positive(self.downstream_drift_mm, "downstream_drift_mm")


@dataclass(frozen=True)
class InnerSolution:
    """Inner reflectron variables and logarithmic accelerator field contrast."""

    stage1_voltage_drop_v: float
    stage2_field_v_per_mm: float
    eta: float

    def __post_init__(self) -> None:
        _positive(self.stage1_voltage_drop_v, "stage1_voltage_drop_v")
        _positive(self.stage2_field_v_per_mm, "stage2_field_v_per_mm")
        _finite(self.eta, "eta")


@dataclass(frozen=True)
class TimeDerivatives:
    """Analytic total derivatives along the frozen affine source branch."""

    d1: float
    d2: float
    d3: float
    d4: float
    focus_drift_after_exit_mm: float
    center_normalized_time_mm_sqrt_v: float
    accelerator_components: tuple[float, float, float, float]
    reflectron_components: tuple[float, float, float, float]
    drift_components: tuple[float, float, float, float]

    def as_array(self) -> NDArray[np.float64]:
        """Return ``[D1, D2, D3, D4]`` as a new float array."""

        return np.asarray((self.d1, self.d2, self.d3, self.d4), dtype=float)


@dataclass(frozen=True)
class NumericalDerivativeAudit:
    """Explicit-step polynomial audit of exact-time derivatives."""

    energy_step_v: float
    stencil_radius: int
    d1: float
    d2: float
    d3: float
    d4: float

    def as_array(self) -> NDArray[np.float64]:
        """Return the numerical ``[D1, D2, D3, D4]`` values."""

        return np.asarray((self.d1, self.d2, self.d3, self.d4), dtype=float)


@dataclass(frozen=True)
class ExactCohort:
    """Exact deterministic source cohort and detector-time metric inputs."""

    source_x_mm: NDArray[np.float64]
    chi_sqrt_v: NDArray[np.float64]
    energy_per_charge_v: NDArray[np.float64]
    normalized_time_mm_sqrt_v: NDArray[np.float64]
    tof_us: NDArray[np.float64]

    @property
    def population_sigma_ns(self) -> float:
        """Return population standard deviation of exact detector TOF in ns."""

        return float(np.std(self.tof_us, ddof=0) * 1.0e3)

    @property
    def sample_sigma_ns(self) -> float:
        """Return sample standard deviation of exact detector TOF in ns."""

        return float(np.std(self.tof_us, ddof=1) * 1.0e3)


@dataclass(frozen=True)
class EngineeringAnnotations:
    """Unthresholded engineering quantities attached to a formula evaluation."""

    maximum_accelerator_field_v_per_mm: float
    accelerator_field_contrast: float
    accelerator_focus_envelope_mm: float
    maximum_stage2_turn_depth_mm: float
    minimum_backward_turn_position_mm: float
    minimum_energy_after_grid1_v: float
    minimum_abs_energy_slope_v_per_mm: float


@dataclass(frozen=True)
class PhysicsGateLimits:
    """Caller-owned margins and engineering bounds for ideal-model gates."""

    minimum_zone_length_mm: float
    minimum_electrode_clearance_mm: float
    minimum_energy_margin_v: float
    minimum_abs_energy_slope_v_per_mm: float
    minimum_focus_drift_mm: float
    maximum_accelerator_focus_envelope_mm: float
    minimum_stage1_voltage_v: float
    maximum_stage1_voltage_v: float
    maximum_accelerator_field_v_per_mm: float
    maximum_accelerator_field_contrast: float
    minimum_stage2_depth_margin_mm: float

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            _finite(value, name)
        if self.minimum_zone_length_mm <= 0.0:
            raise TheoryDomainError("minimum_zone_length_mm must be > 0")
        if self.minimum_electrode_clearance_mm < 0.0:
            raise TheoryDomainError("minimum_electrode_clearance_mm must be >= 0")
        if self.minimum_energy_margin_v < 0.0:
            raise TheoryDomainError("minimum_energy_margin_v must be >= 0")
        if self.minimum_abs_energy_slope_v_per_mm < 0.0:
            raise TheoryDomainError(
                "minimum_abs_energy_slope_v_per_mm must be >= 0"
            )
        if self.maximum_stage1_voltage_v < self.minimum_stage1_voltage_v:
            raise TheoryDomainError("stage1 voltage bounds are reversed")
        if self.maximum_accelerator_field_contrast < 1.0:
            raise TheoryDomainError(
                "maximum_accelerator_field_contrast must be >= 1"
            )


@dataclass(frozen=True)
class GateCheck:
    """One named, machine-readable gate comparison."""

    name: str
    passed: bool
    value: float
    relation: str
    limit: float


@dataclass(frozen=True)
class PhysicsGateReport:
    """Complete ideal physics and caller-owned engineering gate report."""

    passed: bool
    checks: tuple[GateCheck, ...]

    @property
    def failed_names(self) -> tuple[str, ...]:
        """Return the names of failed gates in deterministic order."""

        return tuple(check.name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class DesignEvaluation:
    """Formula-oracle result for one exact cohort and one design point."""

    state: ThreeZoneState
    derivatives: TimeDerivatives
    cohort: ExactCohort
    annotations: EngineeringAnnotations
    gates: PhysicsGateReport


def _power_derivative(order: int, offset_v: float, exponent: float) -> float:
    if order < 0:
        raise TheoryDomainError("derivative order must be nonnegative")
    if offset_v <= 0.0:
        raise TheoryDomainError("timing square-root argument must be > 0")
    coefficient = 1.0
    for index in range(order):
        coefficient *= exponent - index
    return coefficient * offset_v ** (exponent - order)


def exact_total_normalized_time(
    source: AffineSource,
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    x_mm: float | NDArray[np.float64],
    focus_drift_mm: float,
) -> float | NDArray[np.float64]:
    """Return exact source-to-detector normalized TOF for source coordinates."""

    x_values = np.asarray(x_mm, dtype=float)
    chi = np.asarray(source.chi(x_values), dtype=float)
    return exact_total_normalized_time_from_state(
        state, reflectron, inner, x_values, chi, focus_drift_mm
    )


def exact_total_normalized_time_from_state(
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    x_mm: float | NDArray[np.float64],
    chi_sqrt_v: float | NDArray[np.float64],
    focus_drift_mm: float,
) -> float | NDArray[np.float64]:
    """Return exact source-to-detector time for independent axial states.

    The function deliberately shares the accelerator and reflectron equations
    with the fitted-manifold oracle.  It only removes the otherwise implicit
    relation ``chi(x)`` so an observed conditional residual can be perturbed
    without changing its conditional coordinate.
    """

    x_values = np.asarray(x_mm, dtype=float)
    chi = np.asarray(chi_sqrt_v, dtype=float)
    try:
        x_values, chi = np.broadcast_arrays(x_values, chi)
    except ValueError as error:
        raise TheoryDomainError("x_mm and chi_sqrt_v cannot be broadcast") from error
    energy = state.repeller_v - state.field1_v_per_mm * x_values + chi**2
    if np.any(energy <= inner.stage1_voltage_drop_v):
        raise TheoryDomainError("reflectron stage1 voltage reaches the source energy")
    field1 = inner.stage1_voltage_drop_v / reflectron.stage1_length_mm
    accelerator = np.asarray(
        exact_accelerator_normalized_time_from_state(
            state, x_values, chi, focus_drift_mm
        ),
        dtype=float,
    )
    reflected = (
        4.0
        / field1
        * (np.sqrt(energy) - np.sqrt(energy - inner.stage1_voltage_drop_v))
        + 4.0 / inner.stage2_field_v_per_mm * np.sqrt(
            energy - inner.stage1_voltage_drop_v
        )
    )
    drift = (
        reflectron.upstream_drift_mm + reflectron.downstream_drift_mm
    ) / np.sqrt(energy)
    total = accelerator + reflected + drift
    return float(total) if total.ndim == 0 else total


def _reflectron_derivative(
    order: int,
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
) -> float:
    w = state.center_energy_per_charge_v
    u = inner.stage1_voltage_drop_v
    field1 = u / reflectron.stage1_length_mm
    return (
        4.0
        / field1
        * (
            _power_derivative(order, w, 0.5)
            - _power_derivative(order, w - u, 0.5)
        )
        + 4.0
        / inner.stage2_field_v_per_mm
        * _power_derivative(order, w - u, 0.5)
    )


def compute_time_derivatives(
    source: AffineSource,
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
) -> TimeDerivatives:
    """Return analytic machine-authority ``D1..D4`` along the affine source."""

    focus_drift = derive_first_order_focus_drift(source, state)
    accelerator = compute_accelerator_time_derivatives(source, state, focus_drift)
    reflected = tuple(
        _reflectron_derivative(order, state, reflectron, inner)
        for order in range(1, 5)
    )
    drift_length = reflectron.upstream_drift_mm + reflectron.downstream_drift_mm
    drift = tuple(
        drift_length
        * _power_derivative(order, state.center_energy_per_charge_v, -0.5)
        for order in range(1, 5)
    )
    total = tuple(
        accelerator[index] + reflected[index] + drift[index]
        for index in range(4)
    )
    center_time = float(
        exact_total_normalized_time(
            source,
            state,
            reflectron,
            inner,
            source.center_x_mm,
            focus_drift,
        )
    )
    return TimeDerivatives(
        d1=total[0],
        d2=total[1],
        d3=total[2],
        d4=total[3],
        focus_drift_after_exit_mm=focus_drift,
        center_normalized_time_mm_sqrt_v=center_time,
        accelerator_components=accelerator,
        reflectron_components=reflected,
        drift_components=drift,
    )


def compute_numerical_time_derivatives(
    source: AffineSource,
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    *,
    energy_step_v: float,
    stencil_radius: int,
) -> NumericalDerivativeAudit:
    """Cross-check ``D1..D4`` by fitting exact time on an explicit energy stencil."""

    step = _positive(energy_step_v, "energy_step_v")
    if isinstance(stencil_radius, bool) or stencil_radius < 4:
        raise TheoryDomainError("stencil_radius must be an integer >= 4")
    radius = int(stencil_radius)
    if radius != stencil_radius:
        raise TheoryDomainError("stencil_radius must be an integer >= 4")
    scaled_offsets = np.arange(-radius, radius + 1, dtype=float)
    energy = state.center_energy_per_charge_v + step * scaled_offsets
    x_values = np.asarray(source_coordinate_for_energy(source, state, energy))
    focus_drift = derive_first_order_focus_drift(source, state)
    times = np.asarray(
        exact_total_normalized_time(
            source, state, reflectron, inner, x_values, focus_drift
        )
    )
    coefficients = np.polynomial.polynomial.polyfit(
        scaled_offsets, times, deg=2 * radius
    )
    values = tuple(
        math.factorial(order) * float(coefficients[order]) / step**order
        for order in range(1, 5)
    )
    return NumericalDerivativeAudit(
        energy_step_v=step,
        stencil_radius=radius,
        d1=values[0],
        d2=values[1],
        d3=values[2],
        d4=values[3],
    )


def build_exact_cohort(
    source: AffineSource,
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    *,
    width_mm: float,
    sample_count: int,
) -> ExactCohort:
    """Build an inclusive, uniformly spaced exact source cohort."""

    width = _positive(width_mm, "width_mm")
    if isinstance(sample_count, bool) or sample_count < 3:
        raise TheoryDomainError("sample_count must be an integer >= 3")
    count = int(sample_count)
    if count != sample_count:
        raise TheoryDomainError("sample_count must be an integer >= 3")
    positions = np.linspace(
        source.center_x_mm - width / 2.0,
        source.center_x_mm + width / 2.0,
        count,
    )
    focus_drift = derive_first_order_focus_drift(source, state)
    chi = np.asarray(source.chi(positions), dtype=float)
    energy = np.asarray(source_energy_per_charge(source, state, positions))
    normalized_time = np.asarray(
        exact_total_normalized_time(
            source, state, reflectron, inner, positions, focus_drift
        )
    )
    tof_us = normalized_time * source.time_scale_s_per_mm_sqrt_v * 1.0e6
    return ExactCohort(
        source_x_mm=positions,
        chi_sqrt_v=chi,
        energy_per_charge_v=energy,
        normalized_time_mm_sqrt_v=normalized_time,
        tof_us=tof_us,
    )


def _minimum_abs_quadratic_slope(
    source: AffineSource,
    state: ThreeZoneState,
    width_mm: float,
) -> float:
    half = width_mm / 2.0
    endpoint_slopes = (
        state.energy_position_first_v_per_mm
        - state.energy_position_second_v_per_mm2 * half,
        state.energy_position_first_v_per_mm
        + state.energy_position_second_v_per_mm2 * half,
    )
    if endpoint_slopes[0] <= 0.0 <= endpoint_slopes[1]:
        return 0.0
    if endpoint_slopes[1] <= 0.0 <= endpoint_slopes[0]:
        return 0.0
    return min(abs(endpoint_slopes[0]), abs(endpoint_slopes[1]))


def engineering_annotations(
    source: AffineSource,
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    cohort: ExactCohort,
    focus_drift_mm: float,
) -> EngineeringAnnotations:
    """Return raw engineering quantities without applying acceptance thresholds."""

    fields = (
        state.field1_v_per_mm,
        state.field2_v_per_mm,
        state.field3_v_per_mm,
    )
    contrast = max(
        state.field_ratio_2_over_3, 1.0 / state.field_ratio_2_over_3
    )
    turn_positions = cohort.source_x_mm - cohort.chi_sqrt_v**2 / state.field1_v_per_mm
    maximum_stage2_depth = float(
        (np.max(cohort.energy_per_charge_v) - inner.stage1_voltage_drop_v)
        / inner.stage2_field_v_per_mm
    )
    return EngineeringAnnotations(
        maximum_accelerator_field_v_per_mm=max(fields),
        accelerator_field_contrast=contrast,
        accelerator_focus_envelope_mm=(
            state.zone1_length_mm
            + state.zone2_length_mm
            + state.zone3_length_mm
            + focus_drift_mm
        ),
        maximum_stage2_turn_depth_mm=maximum_stage2_depth,
        minimum_backward_turn_position_mm=float(np.min(turn_positions)),
        minimum_energy_after_grid1_v=float(
            np.min(cohort.energy_per_charge_v) - state.grid1_v
        ),
        minimum_abs_energy_slope_v_per_mm=_minimum_abs_quadratic_slope(
            source, state, float(np.ptp(cohort.source_x_mm))
        ),
    )


def _lower_check(name: str, value: float, limit: float) -> GateCheck:
    return GateCheck(name, value >= limit, value, ">=", limit)


def _upper_check(name: str, value: float, limit: float) -> GateCheck:
    return GateCheck(name, value <= limit, value, "<=", limit)


def evaluate_physics_gates(
    state: ThreeZoneState,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    cohort: ExactCohort,
    annotations: EngineeringAnnotations,
    limits: PhysicsGateLimits,
) -> PhysicsGateReport:
    """Evaluate exact physics invariants and caller-owned engineering margins."""

    source_grid_clearance = min(
        float(np.min(cohort.source_x_mm)),
        state.zone1_length_mm - float(np.max(cohort.source_x_mm)),
    )
    depth_margin = (
        reflectron.stage2_length_mm - annotations.maximum_stage2_turn_depth_mm
    )
    finite_values: Iterable[float] = (
        *cohort.energy_per_charge_v,
        *cohort.normalized_time_mm_sqrt_v,
        *annotations.__dict__.values(),
    )
    all_finite = float(all(math.isfinite(float(value)) for value in finite_values))
    checks = (
        _lower_check("all_finite", all_finite, 1.0),
        _lower_check(
            "minimum_zone_length_mm",
            min(
                state.zone1_length_mm,
                state.zone2_length_mm,
                state.zone3_length_mm,
            ),
            limits.minimum_zone_length_mm,
        ),
        _lower_check(
            "source_electrode_clearance_mm",
            source_grid_clearance,
            limits.minimum_electrode_clearance_mm,
        ),
        _lower_check(
            "backward_turn_clearance_mm",
            annotations.minimum_backward_turn_position_mm,
            limits.minimum_electrode_clearance_mm,
        ),
        _lower_check(
            "energy_after_grid1_v",
            annotations.minimum_energy_after_grid1_v,
            limits.minimum_energy_margin_v,
        ),
        _lower_check(
            "abs_energy_slope_v_per_mm",
            annotations.minimum_abs_energy_slope_v_per_mm,
            limits.minimum_abs_energy_slope_v_per_mm,
        ),
        _lower_check(
            "focus_drift_after_exit_mm",
            annotations.accelerator_focus_envelope_mm
            - state.zone1_length_mm
            - state.zone2_length_mm
            - state.zone3_length_mm,
            limits.minimum_focus_drift_mm,
        ),
        _upper_check(
            "accelerator_focus_envelope_mm",
            annotations.accelerator_focus_envelope_mm,
            limits.maximum_accelerator_focus_envelope_mm,
        ),
        _lower_check(
            "reflectron_stage1_voltage_min_v",
            inner.stage1_voltage_drop_v,
            limits.minimum_stage1_voltage_v,
        ),
        _upper_check(
            "reflectron_stage1_voltage_max_v",
            inner.stage1_voltage_drop_v,
            limits.maximum_stage1_voltage_v,
        ),
        _upper_check(
            "accelerator_field_v_per_mm",
            annotations.maximum_accelerator_field_v_per_mm,
            limits.maximum_accelerator_field_v_per_mm,
        ),
        _upper_check(
            "accelerator_field_contrast",
            annotations.accelerator_field_contrast,
            limits.maximum_accelerator_field_contrast,
        ),
        _lower_check(
            "reflectron_stage2_depth_margin_mm",
            depth_margin,
            limits.minimum_stage2_depth_margin_mm,
        ),
    )
    report_passed = all(check.passed for check in checks)
    return PhysicsGateReport(report_passed, checks)


def evaluate_three_zone_design(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    *,
    width_mm: float,
    sample_count: int,
    physics_limits: PhysicsGateLimits,
) -> DesignEvaluation:
    """Evaluate the exact formula oracle, cohort, annotations, and physics gates."""

    state = derive_three_zone_state(source, outer, inner.eta)
    derivatives = compute_time_derivatives(source, state, reflectron, inner)
    cohort = build_exact_cohort(
        source,
        state,
        reflectron,
        inner,
        width_mm=width_mm,
        sample_count=sample_count,
    )
    annotations = engineering_annotations(
        source,
        state,
        reflectron,
        inner,
        cohort,
        derivatives.focus_drift_after_exit_mm,
    )
    gates = evaluate_physics_gates(
        state, reflectron, inner, cohort, annotations, physics_limits
    )
    return DesignEvaluation(state, derivatives, cohort, annotations, gates)
