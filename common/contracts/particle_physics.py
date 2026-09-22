"""Solver- and device-neutral particle physics formulas and constants."""

from __future__ import annotations

import math


AMU_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19
# Frozen oa-TOF references predate the repository-wide mass authority and bind
# this value into their published numerical fixtures.  New calculations must
# use ``AMU_KG``; this named compatibility constant exists only so those
# references do not silently change while their contracts are requalified.
LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG = 1.66053906892e-27
# NIST 2022 CODATA recommended values.
ELECTRON_MASS_KG = 9.1093837139e-31
ELECTRON_MASS_U = 5.485799090441e-4


def kinetic_energy_ev(
    mass_amu: float,
    velocity_x_m_s: float,
    velocity_y_m_s: float,
    velocity_z_m_s: float,
) -> float:
    """Return nonrelativistic kinetic energy in eV for a particle state."""
    speed_squared = velocity_x_m_s**2 + velocity_y_m_s**2 + velocity_z_m_s**2
    return 0.5 * mass_amu * AMU_KG * speed_squared / ELEMENTARY_CHARGE_C


def speed_m_s_from_kinetic_energy_ev(
    mass_amu: float,
    kinetic_energy_ev_value: float,
) -> float:
    """Return nonrelativistic speed in m/s from mass in u and energy in eV.

    ``mass_amu`` is the particle mass expressed in unified atomic mass units;
    it is not a mass-to-charge ratio.  ``kinetic_energy_ev_value`` is the
    particle's total kinetic energy, not energy per charge.
    """

    mass = float(mass_amu)
    energy = float(kinetic_energy_ev_value)
    if not math.isfinite(mass) or mass <= 0.0:
        raise ValueError("mass_amu must be finite and > 0")
    if not math.isfinite(energy) or energy < 0.0:
        raise ValueError("kinetic_energy_ev_value must be finite and >= 0")
    return math.sqrt(2.0 * energy * ELEMENTARY_CHARGE_C / (mass * AMU_KG))


def kinetic_energy_ev_from_speed_m_s(mass_amu: float, speed_m_s: float) -> float:
    """Return nonrelativistic kinetic energy in eV from mass in u and speed."""

    mass = float(mass_amu)
    speed = float(speed_m_s)
    if not math.isfinite(mass) or mass <= 0.0:
        raise ValueError("mass_amu must be finite and > 0")
    if not math.isfinite(speed) or speed < 0.0:
        raise ValueError("speed_m_s must be finite and >= 0")
    return kinetic_energy_ev(mass, speed, 0.0, 0.0)


def charge_to_mass_c_per_kg(mass_amu: float, charge_state: int) -> float:
    """Return signed charge-to-mass ratio in C/kg.

    ``mass_amu`` is particle mass in unified atomic mass units and
    ``charge_state`` is the signed integer multiple of the elementary charge.
    """

    mass = float(mass_amu)
    if not math.isfinite(mass) or mass <= 0.0:
        raise ValueError("mass_amu must be finite and > 0")
    if isinstance(charge_state, bool) or not isinstance(charge_state, int):
        raise ValueError("charge_state must be an integer")
    if charge_state == 0:
        raise ValueError("charge_state must be nonzero")
    return charge_state * ELEMENTARY_CHARGE_C / (mass * AMU_KG)


def mass_to_charge_kg_per_c(mass_amu: float, charge_state: int) -> float:
    """Return unsigned mass-to-charge magnitude in kg/C.

    The sign convention matches :func:`mass_to_charge_th`: negative and
    positive ions with the same absolute charge state have the same returned
    mass-to-charge magnitude.
    """

    return 1.0 / abs(charge_to_mass_c_per_kg(mass_amu, charge_state))


def thomson_to_kg_per_c(
    mass_to_charge_th_value: float,
    *,
    atomic_mass_constant_kg: float = AMU_KG,
) -> float:
    """Convert an unsigned mass-to-charge magnitude from Th (u/e) to kg/C.

    ``atomic_mass_constant_kg`` is injectable only for a frozen legacy
    numerical contract.  Ordinary callers use the repository authority
    :data:`AMU_KG`.
    """

    value = float(mass_to_charge_th_value)
    mass_constant = float(atomic_mass_constant_kg)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("mass_to_charge_th_value must be finite and > 0")
    if not math.isfinite(mass_constant) or mass_constant <= 0.0:
        raise ValueError("atomic_mass_constant_kg must be finite and > 0")
    return value * mass_constant / ELEMENTARY_CHARGE_C


def mass_to_charge_th(mass_amu: float, charge_state: int) -> float:
    """Return unsigned mass-to-charge in Thomson for an integer charge state."""
    if charge_state == 0:
        raise ValueError("charge_state must be nonzero")
    return mass_amu / abs(charge_state)
