"""Exact one-dimensional theory for a three-zone oa-TOF accelerator.

The module is deliberately policy-free.  It owns the ideal electrostatic formulas,
the signed affine source coordinate, analytic timing derivatives, and deterministic
cohort construction.  Campaign bounds and acceptance thresholds are supplied by the
caller; this module does not select an instrument design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from numpy.typing import NDArray


from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
)


class TheoryDomainError(ValueError):
    """Raised when a value lies outside the exact ideal-model domain."""


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
class AffineSource:
    """Signed affine source in the canonical ``chi=sqrt(K/q)`` coordinate.

    ``time_scale_s_per_mm_sqrt_v`` converts normalized time in mm/sqrt(V) to
    seconds.  Keeping it in the frozen source makes both signed velocity and the SI
    conversion auditable without consulting campaign-global state.
    """

    center_x_mm: float
    chi_center_sqrt_v: float
    chi_slope_sqrt_v_per_mm: float
    time_scale_s_per_mm_sqrt_v: float

    def __post_init__(self) -> None:
        _finite(self.center_x_mm, "center_x_mm")
        _finite(self.chi_center_sqrt_v, "chi_center_sqrt_v")
        _finite(self.chi_slope_sqrt_v_per_mm, "chi_slope_sqrt_v_per_mm")
        _positive(self.time_scale_s_per_mm_sqrt_v, "time_scale_s_per_mm_sqrt_v")

    @classmethod
    def from_velocity(
        cls,
        *,
        mass_to_charge_th: float,
        center_x_mm: float,
        center_velocity_m_per_s: float,
        velocity_slope_m_per_s_per_mm: float,
    ) -> AffineSource:
        """Construct the canonical source from a signed velocity line in SI units."""

        mass_to_charge = _positive(mass_to_charge_th, "mass_to_charge_th")
        mass_per_charge_kg_per_c = (
            mass_to_charge * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
        )
        root_factor = math.sqrt(mass_per_charge_kg_per_c / 2.0)
        return cls(
            center_x_mm=_finite(center_x_mm, "center_x_mm"),
            chi_center_sqrt_v=(
                _finite(center_velocity_m_per_s, "center_velocity_m_per_s")
                * root_factor
            ),
            chi_slope_sqrt_v_per_mm=(
                _finite(
                    velocity_slope_m_per_s_per_mm,
                    "velocity_slope_m_per_s_per_mm",
                )
                * root_factor
            ),
            time_scale_s_per_mm_sqrt_v=1.0e-3 * root_factor,
        )

    def chi(self, x_mm: float | NDArray[np.float64]) -> float | NDArray[np.float64]:
        """Return the signed kinetic-energy root at source coordinate ``x_mm``."""

        values = np.asarray(x_mm, dtype=float)
        result = self.chi_center_sqrt_v + self.chi_slope_sqrt_v_per_mm * (
            values - self.center_x_mm
        )
        return float(result) if result.ndim == 0 else result


@dataclass(frozen=True)
class OuterGeometry:
    """Campaign-selected three-zone accelerator geometry and first voltage drop."""

    zone1_length_mm: float
    downstream_length_mm: float
    split_fraction: float
    zone1_voltage_drop_v: float
    nominal_energy_per_charge_v: float

    def __post_init__(self) -> None:
        _positive(self.zone1_length_mm, "zone1_length_mm")
        _positive(self.downstream_length_mm, "downstream_length_mm")
        split = _finite(self.split_fraction, "split_fraction")
        if not 0.0 < split < 1.0:
            raise TheoryDomainError("split_fraction must lie in (0, 1)")
        _positive(self.zone1_voltage_drop_v, "zone1_voltage_drop_v")
        _positive(
            self.nominal_energy_per_charge_v, "nominal_energy_per_charge_v"
        )


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
class ThreeZoneState:
    """Derived ideal fields and electrode voltages for one design point."""

    zone1_length_mm: float
    zone2_length_mm: float
    zone3_length_mm: float
    field1_v_per_mm: float
    field2_v_per_mm: float
    field3_v_per_mm: float
    repeller_v: float
    grid1_v: float
    grid2_v: float
    exit_v: float
    field_ratio_2_over_3: float
    grid2_fraction_of_grid1: float
    affine_g: float
    center_energy_per_charge_v: float
    energy_position_first_v_per_mm: float
    energy_position_second_v_per_mm2: float


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


def derive_three_zone_state(
    source: AffineSource,
    outer: OuterGeometry,
    eta: float,
) -> ThreeZoneState:
    """Derive fields and electrode voltages from the logarithmic contrast ``eta``."""

    eta_value = _finite(eta, "eta")
    try:
        ratio = math.exp(eta_value)
    except OverflowError as exc:
        raise TheoryDomainError("eta produces a non-finite field ratio") from exc
    if not math.isfinite(ratio):
        raise TheoryDomainError("eta produces a non-finite field ratio")
    split = outer.split_fraction
    d2 = split * outer.downstream_length_mm
    d3 = (1.0 - split) * outer.downstream_length_mm
    field1 = outer.zone1_voltage_drop_v / outer.zone1_length_mm
    repeller = outer.nominal_energy_per_charge_v + field1 * source.center_x_mm
    grid1 = repeller - outer.zone1_voltage_drop_v
    if grid1 <= 0.0:
        raise TheoryDomainError("derived grid1_v must be > 0")
    denominator = outer.downstream_length_mm * (
        split * ratio + 1.0 - split
    )
    field3 = grid1 / denominator
    field2 = ratio * field3
    grid2_fraction = (1.0 - split) / (split * ratio + 1.0 - split)
    grid2 = grid2_fraction * grid1
    center_energy = (
        outer.nominal_energy_per_charge_v + source.chi_center_sqrt_v**2
    )
    p = -field1 + 2.0 * source.chi_center_sqrt_v * source.chi_slope_sqrt_v_per_mm
    q = 2.0 * source.chi_slope_sqrt_v_per_mm**2
    return ThreeZoneState(
        zone1_length_mm=outer.zone1_length_mm,
        zone2_length_mm=d2,
        zone3_length_mm=d3,
        field1_v_per_mm=field1,
        field2_v_per_mm=field2,
        field3_v_per_mm=field3,
        repeller_v=repeller,
        grid1_v=grid1,
        grid2_v=grid2,
        exit_v=0.0,
        field_ratio_2_over_3=ratio,
        grid2_fraction_of_grid1=grid2_fraction,
        affine_g=grid2_fraction - (1.0 - split),
        center_energy_per_charge_v=center_energy,
        energy_position_first_v_per_mm=p,
        energy_position_second_v_per_mm2=q,
    )


def source_energy_per_charge(
    source: AffineSource,
    state: ThreeZoneState,
    x_mm: float | NDArray[np.float64],
) -> float | NDArray[np.float64]:
    """Return exact final energy per charge along the frozen source line."""

    x_values = np.asarray(x_mm, dtype=float)
    chi_values = np.asarray(source.chi(x_values), dtype=float)
    result = state.repeller_v - state.field1_v_per_mm * x_values + chi_values**2
    return float(result) if result.ndim == 0 else result


def source_coordinate_for_energy(
    source: AffineSource,
    state: ThreeZoneState,
    energy_per_charge_v: float | NDArray[np.float64],
) -> float | NDArray[np.float64]:
    """Invert the local source-energy branch continuous through the source center."""

    energy = np.asarray(energy_per_charge_v, dtype=float)
    delta = energy - state.center_energy_per_charge_v
    p = state.energy_position_first_v_per_mm
    beta2 = source.chi_slope_sqrt_v_per_mm**2
    if p == 0.0:
        raise TheoryDomainError("source energy mapping has zero center slope")
    if beta2 == 0.0:
        offset = delta / p
    else:
        discriminant = p * p + 4.0 * beta2 * delta
        if np.any(discriminant < 0.0):
            raise TheoryDomainError("energy lies outside the local affine-source branch")
        denominator = p + math.copysign(1.0, p) * np.sqrt(discriminant)
        offset = 2.0 * delta / denominator
    result = source.center_x_mm + offset
    return float(result) if result.ndim == 0 else result


def _power_derivative(order: int, offset_v: float, exponent: float) -> float:
    if order < 0:
        raise TheoryDomainError("derivative order must be nonnegative")
    if offset_v <= 0.0:
        raise TheoryDomainError("timing square-root argument must be > 0")
    coefficient = 1.0
    for index in range(order):
        coefficient *= exponent - index
    return coefficient * offset_v ** (exponent - order)


def _accelerator_fixed_energy_derivative(
    order: int,
    state: ThreeZoneState,
    focus_drift_mm: float,
) -> float:
    w = state.center_energy_per_charge_v
    d_w = _power_derivative(order, w, 0.5)
    d_g1 = _power_derivative(order, w - state.grid1_v, 0.5)
    d_g2 = _power_derivative(order, w - state.grid2_v, 0.5)
    return (
        2.0 / state.field1_v_per_mm * d_g1
        + 2.0 / state.field2_v_per_mm * (d_g2 - d_g1)
        + 2.0 / state.field3_v_per_mm * (d_w - d_g2)
        + focus_drift_mm * _power_derivative(order, w, -0.5)
    )


def _source_chain_correction(
    order: int,
    source: AffineSource,
    state: ThreeZoneState,
) -> float:
    beta = source.chi_slope_sqrt_v_per_mm
    p = state.energy_position_first_v_per_mm
    if p == 0.0:
        raise TheoryDomainError("source energy mapping has zero center slope")
    corrections = {
        1: -2.0 * beta / (state.field1_v_per_mm * p),
        2: 4.0 * beta**3 / (state.field1_v_per_mm * p**3),
        3: -24.0 * beta**5 / (state.field1_v_per_mm * p**5),
        4: 240.0 * beta**7 / (state.field1_v_per_mm * p**7),
    }
    try:
        return corrections[order]
    except KeyError as exc:
        raise TheoryDomainError("source correction is implemented for orders 1..4") from exc


def derive_first_order_focus_drift(
    source: AffineSource,
    state: ThreeZoneState,
) -> float:
    """Solve the accelerator-only ``A1=0`` condition for drift after the exit."""

    a1_without_drift = _accelerator_fixed_energy_derivative(1, state, 0.0)
    a1_without_drift += _source_chain_correction(1, source, state)
    drift_basis = _power_derivative(
        1, state.center_energy_per_charge_v, -0.5
    )
    return -a1_without_drift / drift_basis


def exact_accelerator_normalized_time(
    source: AffineSource,
    state: ThreeZoneState,
    x_mm: float | NDArray[np.float64],
    focus_drift_mm: float,
) -> float | NDArray[np.float64]:
    """Return exact accelerator-plus-focus-drift time in mm/sqrt(V)."""

    x_values = np.asarray(x_mm, dtype=float)
    chi = np.asarray(source.chi(x_values), dtype=float)
    energy = np.asarray(source_energy_per_charge(source, state, x_values), dtype=float)
    if np.any(energy <= state.grid1_v):
        raise TheoryDomainError("source cohort cannot cross accelerator grid1")
    term = (
        2.0 / state.field1_v_per_mm * (np.sqrt(energy - state.grid1_v) - chi)
        + 2.0
        / state.field2_v_per_mm
        * (np.sqrt(energy - state.grid2_v) - np.sqrt(energy - state.grid1_v))
        + 2.0
        / state.field3_v_per_mm
        * (np.sqrt(energy) - np.sqrt(energy - state.grid2_v))
        + focus_drift_mm / np.sqrt(energy)
    )
    return float(term) if term.ndim == 0 else term


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
    energy = np.asarray(source_energy_per_charge(source, state, x_values), dtype=float)
    if np.any(energy <= inner.stage1_voltage_drop_v):
        raise TheoryDomainError("reflectron stage1 voltage reaches the source energy")
    field1 = inner.stage1_voltage_drop_v / reflectron.stage1_length_mm
    accelerator = np.asarray(
        exact_accelerator_normalized_time(
            source, state, x_values, focus_drift_mm
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
    accelerator = tuple(
        _accelerator_fixed_energy_derivative(order, state, focus_drift)
        + _source_chain_correction(order, source, state)
        for order in range(1, 5)
    )
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
