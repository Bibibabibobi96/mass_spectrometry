"""Exact three-zone accelerator theory in a local extraction coordinate.

This module owns the signed affine source, three uniform accelerating regions,
first time focus and accelerator-only derivatives. Reflectron fields, total
instrument TOF, Gamma3 and system qualification remain with each instrument.
The local coordinate x is not the x axis of a consuming instrument.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
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
    return exact_accelerator_normalized_time_from_state(
        state, x_values, chi, focus_drift_mm
    )


def exact_accelerator_normalized_time_from_state(
    state: ThreeZoneState,
    x_mm: float | NDArray[np.float64],
    chi_sqrt_v: float | NDArray[np.float64],
    focus_drift_mm: float,
) -> float | NDArray[np.float64]:
    """Return exact accelerator time for independently specified axial states.

    ``x_mm`` is the local accelerator coordinate and ``chi_sqrt_v`` is the
    signed axial velocity expressed as ``v_z*sqrt((m/q)/2)``.  This is the
    same ideal-field formula used by :func:`exact_accelerator_normalized_time`,
    but keeps a conditional velocity residual independent of the fitted source
    manifold.  It is therefore the required exact oracle boundary for C2's
    axial residual test; it is not a three-dimensional trajectory model.
    """

    x_values = np.asarray(x_mm, dtype=float)
    chi = np.asarray(chi_sqrt_v, dtype=float)
    try:
        x_values, chi = np.broadcast_arrays(x_values, chi)
    except ValueError as error:
        raise TheoryDomainError("x_mm and chi_sqrt_v cannot be broadcast") from error
    energy = state.repeller_v - state.field1_v_per_mm * x_values + chi**2
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


def compute_accelerator_time_derivatives(
    source: AffineSource,
    state: ThreeZoneState,
    focus_drift_mm: float,
) -> tuple[float, float, float, float]:
    """Return A1..A4 along the affine source branch in normalized time units."""
    return tuple(
        _accelerator_fixed_energy_derivative(order, state, focus_drift_mm)
        + _source_chain_correction(order, source, state)
        for order in range(1, 5)
    )
