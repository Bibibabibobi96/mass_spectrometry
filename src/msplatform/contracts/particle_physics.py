"""Solver- and device-neutral particle physics formulas and constants."""

from __future__ import annotations

import math
from decimal import Decimal, localcontext
from hashlib import sha256
from importlib.resources import files
import json
from types import MappingProxyType

FROZEN_PACKAGE_RESOURCES = ("physics/data/reference.json", "physics/data/electron.json")


_root = files("msplatform").joinpath("physics/data")
_reference_bytes = _root.joinpath("reference.json").read_bytes()
REFERENCE_DATASET_SHA256 = sha256(_reference_bytes).hexdigest().upper()
_reference = json.loads(_reference_bytes)
if _reference["schema_version"] != 1 or _reference["dataset_id"] != "repository_reference_physics_v1":
    raise ValueError("unsupported reference physics dataset")
_constants = _reference["constants"]
CONSTANTS = MappingProxyType({
    "version": _constants["version"],
    "atomic_mass_constant_kg": float(_constants["atomic_mass_constant_kg"]),
    "elementary_charge_c": float(_constants["elementary_charge_c"]),
    "boltzmann_constant_j_k": float(_constants["boltzmann_constant_j_k"]),
})
AMU_KG = CONSTANTS["atomic_mass_constant_kg"]
ELEMENTARY_CHARGE_C = CONSTANTS["elementary_charge_c"]
BOLTZMANN_CONSTANT_J_K = CONSTANTS["boltzmann_constant_j_k"]
# Frozen oa-TOF references predate the repository-wide mass authority and bind
# this value into their published numerical fixtures.  New calculations must
# use ``AMU_KG``; this named compatibility constant exists only so those
# references do not silently change while their contracts are requalified.
LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG = 1.66053906892e-27
_electron_bytes = _root.joinpath("electron.json").read_bytes()
_electron = json.loads(_electron_bytes)
if _electron["schema_version"] != 1 or _electron["dataset_id"] != "electron_mass_codata2022_repository_u_v1":
    raise ValueError("unsupported electron mass dataset")
_electron_mass_kg = float(_electron["mass_kg"])
ELECTRON_CONSTANTS = MappingProxyType({
    "version": _electron["dataset_id"],
    "dataset_sha256": sha256(_electron_bytes).hexdigest(),
    "mass_kg": _electron_mass_kg,
    "mass_u": _electron_mass_kg / AMU_KG,
    "atomic_mass_constant_version": CONSTANTS["version"],
})

# The kg value uses CODATA 2022; u is derived using the frozen repository unit.
ELECTRON_MASS_KG = ELECTRON_CONSTANTS["mass_kg"]
ELECTRON_MASS_U = ELECTRON_CONSTANTS["mass_u"]


def normalize_charge_c(charge_state: int, charge_c: float | Decimal | int) -> float:
    """Validate charge against the frozen constant and return canonical binary64."""
    if type(charge_state) is not int or charge_state == 0 or not -(2**63) <= charge_state < 2**63:
        raise ValueError("charge_state must be a nonzero signed int64")
    if isinstance(charge_c, bool) or not isinstance(charge_c, (int, float, Decimal)):
        raise ValueError("charge_c must be finite and numeric")
    value = float(charge_c)
    if not math.isfinite(value):
        raise ValueError("charge_c must be finite and numeric")
    canonical = charge_state * CONSTANTS["elementary_charge_c"]
    with localcontext() as context:
        context.prec = 50
        decimal_product = float(Decimal(charge_state) * Decimal(str(CONSTANTS["elementary_charge_c"])))
    if value != canonical and value != decimal_product:
        raise ValueError("charge_c disagrees with charge_state and constants")
    return canonical


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
