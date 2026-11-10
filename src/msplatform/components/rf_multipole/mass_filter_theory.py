"""Ideal quadrupole Mathieu reference; original group-voltage conventions."""
from __future__ import annotations
import math
from scipy.constants import atomic_mass, elementary_charge
from scipy.optimize import brentq
from scipy.special import mathieu_a, mathieu_b

def _positive(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def mathieu_parameters(
    mass_to_charge_th: float,
    dc_amplitude_v_per_group: float,
    rf_amplitude_v_zero_to_peak_per_group: float,
    r0_mm: float,
    frequency_hz: float,
) -> dict[str, float]:
    """Return positive-magnitude ``a`` and ``q`` for the documented convention."""
    mu = _positive("mass_to_charge_th", mass_to_charge_th)
    r0_m = _positive("r0_mm", r0_mm) * 1e-3
    frequency = _positive("frequency_hz", frequency_hz)
    rf_amplitude = _positive(
        "rf_amplitude_v_zero_to_peak_per_group",
        rf_amplitude_v_zero_to_peak_per_group,
    )
    dc_amplitude = float(dc_amplitude_v_per_group)
    if not math.isfinite(dc_amplitude) or dc_amplitude < 0:
        raise ValueError("dc_amplitude_v_per_group must be finite and non-negative")

    omega = 2.0 * math.pi * frequency
    mass_per_charge_kg_per_e = mu * atomic_mass
    denominator = mass_per_charge_kg_per_e * r0_m**2 * omega**2
    return {
        "a": 8.0 * elementary_charge * dc_amplitude / denominator,
        "q": 4.0 * elementary_charge * rf_amplitude / denominator,
    }


def mass_to_charge_th(
    q_cal: float,
    rf_amplitude_v_zero_to_peak_per_group: float,
    r0_mm: float,
    frequency_hz: float,
) -> float:
    """Return the mass-to-charge scale in Th for a positive ``q`` magnitude."""
    q_value = _positive("q_cal", q_cal)
    r0_m = _positive("r0_mm", r0_mm) * 1e-3
    frequency = _positive("frequency_hz", frequency_hz)
    rf_amplitude = _positive(
        "rf_amplitude_v_zero_to_peak_per_group",
        rf_amplitude_v_zero_to_peak_per_group,
    )
    omega = 2.0 * math.pi * frequency
    return (
        4.0
        * elementary_charge
        * rf_amplitude
        / (q_value * atomic_mass * r0_m**2 * omega**2)
    )


def first_stability_apex() -> dict[str, float]:
    """Return the first-region intersection of ``-a0(q)`` and ``b1(q)``."""
    q_apex = brentq(lambda q: -mathieu_a(0, q) - mathieu_b(1, q), 0.6, 0.8)
    return {"a": float(-mathieu_a(0, q_apex)), "q": float(q_apex)}


def rf_only_cutoff() -> float:
    """Return the positive first-region cutoff on the ``a=0`` axis."""
    return float(brentq(lambda q: mathieu_b(1, q), 0.8, 1.0))


def scanline_passband(u_over_v: float) -> dict[str, float]:
    """Return ideal first-region intersections for a fixed ``U/V`` line."""
    ratio = _positive("u_over_v", u_over_v)
    apex = first_stability_apex()
    apex_ratio = apex["a"] / (2.0 * apex["q"])
    if ratio >= apex_ratio:
        raise ValueError(f"u_over_v must be below the first-region apex ratio {apex_ratio:.12g}")

    slope = 2.0 * ratio
    q_in = brentq(lambda q: -mathieu_a(0, q) - slope * q, 1e-12, apex["q"])
    q_out = brentq(lambda q: mathieu_b(1, q) - slope * q, apex["q"], rf_only_cutoff())
    resolving_power = (q_in + q_out) / (2.0 * (q_out - q_in))
    q_cal = 2.0 * q_in * q_out / (q_in + q_out)
    return {
        "u_over_v": ratio,
        "q_in": float(q_in),
        "q_out": float(q_out),
        "q_cal": float(q_cal),
        "resolving_power_stability": float(resolving_power),
    }
