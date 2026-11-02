"""Deterministic NumPy sampling for a rectangular source and filled cone.

The sampler is solver-neutral: positions and energy remain in the declared
millimetre/electron-volt units and direction cosines use the declared positive
z axis.  Callers own any coordinate-frame projection and solver rendering.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np


BOX_CONE_FIELDS = (
    "transverse_1_mm",
    "transverse_2_mm",
    "energy_eV",
    "direction_transverse_1",
    "direction_transverse_2",
    "direction_axial",
    "phase_rad",
)


def _finite_interval(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, Mapping) or set(value) < {"min", "max"}:
        raise ValueError(f"{name} must contain min and max")
    minimum = value["min"]
    maximum = value["max"]
    if isinstance(minimum, bool) or isinstance(maximum, bool):
        raise ValueError(f"{name} bounds must be finite numbers")
    lower = float(minimum)
    upper = float(maximum)
    if not math.isfinite(lower) or not math.isfinite(upper) or upper < lower:
        raise ValueError(f"{name} bounds are invalid")
    return lower, upper


def sample_numpy_box_cone_phase_space(
    *,
    source: Mapping[str, Any],
    seed: int,
    particle_count: int,
) -> dict[str, np.ndarray]:
    """Sample a deterministic rectangular position, energy, cone and phase set.

    ``source`` supplies ``position_mm.transverse_1/transverse_2``,
    ``kinetic_energy_eV`` and ``direction.half_angle_deg``.  The sequence is
    intentionally stable for the established NumPy generator call order:
    axial direction, azimuth, two transverse coordinates, energy, then phase.
    Invalid requests raise ``ValueError`` without producing partial output.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(particle_count, bool) or not isinstance(particle_count, int) or particle_count < 1:
        raise ValueError("particle_count must be a positive integer")
    position = source.get("position_mm")
    energy = source.get("kinetic_energy_eV")
    direction = source.get("direction")
    if not isinstance(position, Mapping) or not isinstance(energy, Mapping) or not isinstance(direction, Mapping):
        raise ValueError("box-cone source requires position_mm, kinetic_energy_eV and direction")
    transverse_1 = _finite_interval(position.get("transverse_1"), "position_mm.transverse_1")
    transverse_2 = _finite_interval(position.get("transverse_2"), "position_mm.transverse_2")
    energy_ev = _finite_interval(energy, "kinetic_energy_eV")
    half_angle_deg = direction.get("half_angle_deg")
    if isinstance(half_angle_deg, bool):
        raise ValueError("direction.half_angle_deg must be finite")
    half_angle_deg = float(half_angle_deg)
    if not math.isfinite(half_angle_deg) or half_angle_deg < 0.0 or half_angle_deg >= 90.0:
        raise ValueError("direction.half_angle_deg must be in [0, 90)")

    rng = np.random.default_rng(seed)
    direction_axial = rng.uniform(math.cos(math.radians(half_angle_deg)), 1.0, particle_count)
    transverse_magnitude = np.sqrt(1.0 - direction_axial**2)
    azimuth = rng.uniform(0.0, 2.0 * math.pi, particle_count)
    return {
        "transverse_1_mm": rng.uniform(*transverse_1, particle_count),
        "transverse_2_mm": rng.uniform(*transverse_2, particle_count),
        "energy_eV": rng.uniform(*energy_ev, particle_count),
        "direction_transverse_1": transverse_magnitude * np.cos(azimuth),
        "direction_transverse_2": transverse_magnitude * np.sin(azimuth),
        "direction_axial": direction_axial,
        "phase_rad": rng.uniform(0.0, 2.0 * math.pi, particle_count),
    }
