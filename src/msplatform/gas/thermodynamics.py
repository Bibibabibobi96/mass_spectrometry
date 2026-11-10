"""Ideal-gas views from explicit pressure/temperature and existing constants."""
from __future__ import annotations
import math
from msplatform.contracts.gas import GasSpecies
from msplatform.contracts.particle_physics import AMU_KG, BOLTZMANN_CONSTANT_J_K


def number_density_m3(pressure_pa: float, temperature_k: float) -> float:
    if (type(pressure_pa) not in (int, float) or not math.isfinite(pressure_pa) or pressure_pa < 0
            or type(temperature_k) not in (int, float) or not math.isfinite(temperature_k) or temperature_k <= 0):
        raise ValueError("ideal gas needs finite nonnegative pressure and positive temperature")
    denominator = BOLTZMANN_CONSTANT_J_K * temperature_k
    if denominator == 0:
        raise ValueError("ideal-gas density is not representable")
    density = pressure_pa / denominator
    if not math.isfinite(density):
        raise ValueError("ideal-gas density is not finite")
    return density


def mass_density_kg_m3(number_density: float, composition: tuple[GasSpecies, ...]) -> float:
    if type(number_density) not in (int, float) or not math.isfinite(number_density) or number_density < 0:
        raise ValueError("number density must be finite and nonnegative")
    if not composition or any(not isinstance(s, GasSpecies) for s in composition) or not math.isclose(sum(s.mole_fraction for s in composition), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("normalized composition required")
    density = number_density * (sum(s.mole_fraction * s.mass_amu for s in composition) * AMU_KG)
    if not math.isfinite(density):
        raise ValueError("mass density is not finite")
    return density
