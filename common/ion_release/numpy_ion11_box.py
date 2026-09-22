"""Deterministic NumPy ION11 box-release sampling shared by multipole projects.

This module owns a compact historical ION11 source family: uniform birth time,
two transverse rectangular coordinates, a filled cone and a uniform-energy
quantile.  It intentionally returns solver-neutral latent values so a project
can apply its declared frame mapping before rendering ION11 or canonical CSV.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np


LATENT_FIELDS = (
    "birth_time_us",
    "transverse_1_mm",
    "transverse_2_mm",
    "energy_quantile",
    "phi_rad",
    "cos_theta",
)


def _finite_interval(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, Mapping) or not {"min", "max"}.issubset(value):
        raise ValueError(f"{name} must contain min and max")
    minimum = value["min"]
    maximum = value["max"]
    if isinstance(minimum, bool) or isinstance(maximum, bool):
        raise ValueError(f"{name} bounds must be finite numbers")
    minimum = float(minimum)
    maximum = float(maximum)
    if not math.isfinite(minimum) or not math.isfinite(maximum) or maximum < minimum:
        raise ValueError(f"{name} bounds are invalid")
    return minimum, maximum


def _sampling_intervals(distribution: Mapping[str, Any]) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], float]:
    """Validate and extract the uniform box/cone sampling fields."""
    birth = _finite_interval(distribution.get("time_of_birth_us"), "time_of_birth_us")
    position = distribution.get("position_mm")
    direction = distribution.get("direction")
    if not isinstance(position, Mapping) or not isinstance(direction, Mapping):
        raise ValueError("ION11 box distribution requires position_mm and direction")
    transverse_1 = _finite_interval(position.get("transverse_1"), "position_mm.transverse_1")
    transverse_2 = _finite_interval(position.get("transverse_2"), "position_mm.transverse_2")
    half_angle = direction.get("half_angle_deg")
    if isinstance(half_angle, bool):
        raise ValueError("direction.half_angle_deg must be finite")
    half_angle = float(half_angle)
    if not math.isfinite(half_angle) or half_angle < 0.0 or half_angle >= 90.0:
        raise ValueError("direction.half_angle_deg must be in [0, 90)")
    return birth, transverse_1, transverse_2, half_angle


def _legacy_latent(
    *,
    distribution: Mapping[str, Any],
    seed: int,
    count: int,
) -> dict[str, np.ndarray]:
    birth, transverse_1, transverse_2, half_angle = _sampling_intervals(distribution)
    rng = np.random.default_rng(seed)
    return {
        "birth_time_us": rng.uniform(*birth, count),
        "transverse_1_mm": rng.uniform(*transverse_1, count),
        "transverse_2_mm": rng.uniform(*transverse_2, count),
        "energy_quantile": rng.random(count),
        "phi_rad": rng.uniform(0.0, 2.0 * np.pi, count),
        "cos_theta": rng.uniform(math.cos(math.radians(half_angle)), 1.0, count),
    }


def sample_numpy_ion11_box_latent(
    *,
    distribution: Mapping[str, Any],
    seed: int,
    particle_count: int,
    master_particle_count: int = 1000,
) -> dict[str, np.ndarray]:
    """Return a deterministic, prefix-stable rectangular ION11 source family.

    The first ``master_particle_count`` rows preserve the historical single-RNG
    stream.  Larger requests append independent named streams, retaining the
    registered N=100/N=1000 rows exactly.  Returned arrays are ordered by
    ``LATENT_FIELDS`` and are suitable for distinct declared energy points.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(particle_count, bool) or not isinstance(particle_count, int) or particle_count < 1:
        raise ValueError("particle_count must be a positive integer")
    if isinstance(master_particle_count, bool) or not isinstance(master_particle_count, int) or master_particle_count < 1:
        raise ValueError("master_particle_count must be a positive integer")
    # NumPy consumes the full vector for each physical variable before moving
    # to the next one.  Build the established master cohort first, then slice,
    # so N=100 is exactly the N=1000 prefix instead of a separately seeded run.
    legacy = _legacy_latent(
        distribution=distribution,
        seed=seed,
        count=master_particle_count,
    )
    if particle_count <= master_particle_count:
        return {field: values[:particle_count] for field, values in legacy.items()}
    extension_count = particle_count - master_particle_count
    birth, transverse_1, transverse_2, half_angle = _sampling_intervals(distribution)
    generators = [np.random.default_rng(stream) for stream in np.random.SeedSequence(seed).spawn(6)]
    extension = {
        "birth_time_us": generators[0].uniform(*birth, extension_count),
        "transverse_1_mm": generators[1].uniform(*transverse_1, extension_count),
        "transverse_2_mm": generators[2].uniform(*transverse_2, extension_count),
        "energy_quantile": generators[3].random(extension_count),
        "phi_rad": generators[4].uniform(0.0, 2.0 * np.pi, extension_count),
        "cos_theta": generators[5].uniform(math.cos(math.radians(half_angle)), 1.0, extension_count),
    }
    return {field: np.concatenate((legacy[field], extension[field])) for field in LATENT_FIELDS}


def render_numpy_ion11_box_table(
    *,
    latent: Mapping[str, np.ndarray],
    mass_amu: float,
    charge_state: int,
    axial_mm: float,
    energy_min_ev: float,
    energy_max_ev: float,
    cwf: float,
    color: float,
) -> np.ndarray:
    """Render sampled rectangular box latents into the standard ION11 columns."""
    arrays = [latent.get(field) for field in LATENT_FIELDS]
    if any(not isinstance(value, np.ndarray) or value.ndim != 1 for value in arrays):
        raise ValueError("latent family is incomplete")
    count = len(arrays[0])
    if any(len(value) != count for value in arrays):
        raise ValueError("latent family arrays have inconsistent lengths")
    numeric = (mass_amu, axial_mm, energy_min_ev, energy_max_ev, cwf, color)
    if not all(math.isfinite(float(value)) for value in numeric) or mass_amu <= 0.0 or energy_min_ev <= 0.0 or energy_max_ev < energy_min_ev:
        raise ValueError("ION11 box table parameters are invalid")
    if isinstance(charge_state, bool) or not isinstance(charge_state, int) or charge_state == 0:
        raise ValueError("charge_state must be a nonzero integer")
    birth, transverse_1, transverse_2, energy_quantile, phi, cos_theta = arrays
    theta = np.arccos(cos_theta)
    transverse_1_direction = np.sin(theta) * np.cos(phi)
    transverse_2_direction = np.sin(theta) * np.sin(phi)
    return np.column_stack((
        birth,
        np.full(count, mass_amu),
        np.full(count, charge_state),
        np.full(count, axial_mm),
        transverse_1,
        transverse_2,
        np.rad2deg(np.arctan2(transverse_1_direction, np.cos(theta))),
        np.rad2deg(np.arcsin(transverse_2_direction)),
        energy_min_ev + (energy_max_ev - energy_min_ev) * energy_quantile,
        np.full(count, cwf),
        np.full(count, color),
    ))
