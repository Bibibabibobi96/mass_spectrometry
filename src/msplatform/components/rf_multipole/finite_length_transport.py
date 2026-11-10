"""Finite ideal quadrupole velocity-Verlet kernel; no fringe or native fields."""
from __future__ import annotations
import math
from typing import Any
import numpy as np
from scipy.constants import atomic_mass, elementary_charge

def simulate_mass(
    mass_Th: float,
    particles: dict[str, np.ndarray],
    resolved: dict[str, Any],
    steps_per_rf_period: int,
) -> dict[str, float | int]:
    """Track one mass through the finite ideal rod region and hard ``r0`` aperture."""
    geometry = resolved["geometry_mm"]
    drive = resolved["drive"]
    mass_kg = float(mass_Th) * atomic_mass
    r0_m = float(geometry["inscribed_radius_r0"]) * 1e-3
    rod_length_m = (
        float(geometry["rod_z_max"]) - float(geometry["rod_z_min"])
    ) * 1e-3
    frequency_hz = float(drive["frequency_Hz"])
    omega = 2.0 * math.pi * frequency_hz
    time_step_s = 1.0 / (frequency_hz * steps_per_rf_period)
    dc_v = float(drive["dc_amplitude_V_per_group"])
    rf_v = float(drive["rf_amplitude_V_zero_to_peak_per_group"])

    speed = np.sqrt(2.0 * particles["energy_j"] / mass_kg)
    x = particles["x_m"].copy()
    y = particles["y_m"].copy()
    z = np.zeros_like(x)
    vx = speed * particles["direction_x"]
    vy = speed * particles["direction_y"]
    vz = speed * particles["direction_z"]
    phase = particles["rf_phase_rad"]
    alive = np.ones(x.size, dtype=bool)
    maximum_steps = math.ceil(rod_length_m / float(np.min(vz)) / time_step_s)
    acceleration_scale = 2.0 * elementary_charge / (mass_kg * r0_m**2)
    time_s = 0.0

    for _ in range(maximum_steps):
        active = alive & (z < rod_length_m)
        if not np.any(active):
            break
        voltage = dc_v - rf_v * np.cos(omega * time_s + phase)
        ax = -acceleration_scale * voltage * x
        ay = acceleration_scale * voltage * y
        vx[active] += 0.5 * time_step_s * ax[active]
        vy[active] += 0.5 * time_step_s * ay[active]
        x[active] += time_step_s * vx[active]
        y[active] += time_step_s * vy[active]
        z[active] += time_step_s * vz[active]
        time_s += time_step_s
        voltage = dc_v - rf_v * np.cos(omega * time_s + phase)
        ax = -acceleration_scale * voltage * x
        ay = acceleration_scale * voltage * y
        vx[active] += 0.5 * time_step_s * ax[active]
        vy[active] += 0.5 * time_step_s * ay[active]
        alive &= x**2 + y**2 < r0_m**2

    transmitted = int(np.count_nonzero(alive & (z >= rod_length_m)))
    return {
        "mass_Th": float(mass_Th),
        "particles": int(x.size),
        "transmitted": transmitted,
        "transmission_fraction": transmitted / int(x.size),
    }
