"""Solver- and device-neutral particle physics formulas and constants."""

from __future__ import annotations


AMU_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19


def kinetic_energy_ev(
    mass_amu: float,
    velocity_x_m_s: float,
    velocity_y_m_s: float,
    velocity_z_m_s: float,
) -> float:
    """Return nonrelativistic kinetic energy in eV for a particle state."""
    speed_squared = velocity_x_m_s**2 + velocity_y_m_s**2 + velocity_z_m_s**2
    return 0.5 * mass_amu * AMU_KG * speed_squared / ELEMENTARY_CHARGE_C


def mass_to_charge_th(mass_amu: float, charge_state: int) -> float:
    """Return unsigned mass-to-charge in Thomson for an integer charge state."""
    if charge_state == 0:
        raise ValueError("charge_state must be nonzero")
    return mass_amu / abs(charge_state)
