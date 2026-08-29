"""Independent 1D collisionless integration over a SIMION-exported total axis field.

The input CSV is a canonical table exported with ``simion.wb:efield``.  This
module does not call SIMION and is deliberately limited to the accelerator
axis; it supplies a local reference derivative, not a whole-instrument TOF.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_KG = 1.66053906660e-27


@dataclass(frozen=True)
class AxisField:
    z_mm: np.ndarray
    ez_v_per_mm: np.ndarray


def load_total_axis_field(path: Path) -> AxisField:
    """Load a total-axis field, folding only identical adjacent endpoints."""
    with path.open(newline="", encoding="utf-8") as stream:
        values = list(csv.DictReader(stream))
    if len(values) < 2:
        raise ValueError("axis field needs at least two samples")
    z = np.asarray([float(row["z_mm"]) for row in values], dtype=float)
    ez = np.asarray([float(row["Ez_V_per_mm"]) for row in values], dtype=float)
    if not (np.all(np.isfinite(z)) and np.all(np.isfinite(ez))):
        raise ValueError("axis field must be finite and strictly increasing")
    steps = np.diff(z)
    if np.any(steps < 0):
        raise ValueError("axis field must be finite and strictly increasing")
    duplicate_indices = np.flatnonzero(steps == 0)
    if duplicate_indices.size:
        if not np.allclose(ez[duplicate_indices], ez[duplicate_indices + 1], rtol=0.0, atol=1.0e-12):
            raise ValueError("axis field duplicate coordinates have conflicting Ez values")
        keep = np.concatenate(([True], steps > 0))
        z, ez = z[keep], ez[keep]
    if not np.all(np.diff(z) > 0):
        raise ValueError("axis field must be finite and strictly increasing")
    return AxisField(z_mm=z, ez_v_per_mm=ez)


def integrate_axis_to_plane_us(
    field: AxisField, *, z0_mm: float, vz0_mm_per_us: float, z_stop_mm: float,
    mass_th: float, charge_state: int, dt_us: float = 1.0e-4,
    max_elapsed_us: float = 10.0,
) -> float:
    """Integrate to the first positive-z crossing of ``z_stop_mm`` with RK4.

    The caller must supply a start and stop within the exported field extent;
    a particle may initially move upstream and turn around in the accelerator.
    Failure to reach the stop plane within the declared local propagation
    horizon is explicit rather than silently clipped or iterated to a generic
    implementation step cap.
    """
    if not (field.z_mm[0] <= z0_mm < z_stop_mm <= field.z_mm[-1]):
        raise ValueError("start/stop plane lies outside exported field")
    if mass_th <= 0 or charge_state == 0 or dt_us <= 0 or max_elapsed_us <= 0:
        raise ValueError("mass, charge, and time step must be nonzero and positive where applicable")
    q_over_m_si = charge_state * ELEMENTARY_CHARGE_C / (mass_th * ATOMIC_MASS_KG)
    # 1 V/mm = 1e3 V/m; 1 m/s^2 = 1e-9 mm/us^2.
    def acceleration(z_mm: float) -> float:
        return q_over_m_si * float(np.interp(z_mm, field.z_mm, field.ez_v_per_mm * 1.0e3)) * 1.0e-9
    z, v, elapsed = z0_mm, vz0_mm_per_us, 0.0
    maximum_steps = int(np.ceil(max_elapsed_us / dt_us))
    for _ in range(maximum_steps):
        if z >= z_stop_mm:
            return elapsed
        if not field.z_mm[0] <= z <= field.z_mm[-1]:
            raise RuntimeError("axis integration left exported field before reaching stop plane")
        h = dt_us
        previous_z = z
        a1 = acceleration(z); k1z, k1v = v, a1
        a2 = acceleration(z + 0.5 * h * k1z); k2z, k2v = v + 0.5 * h * k1v, a2
        a3 = acceleration(z + 0.5 * h * k2z); k3z, k3v = v + 0.5 * h * k2v, a3
        a4 = acceleration(z + h * k3z); k4z, k4v = v + h * k3v, a4
        z += h * (k1z + 2 * k2z + 2 * k3z + k4z) / 6
        v += h * (k1v + 2 * k2v + 2 * k3v + k4v) / 6
        elapsed += h
        if previous_z < z_stop_mm <= z:
            # The interpolation only localizes the final accepted RK4 step;
            # convergence is checked by varying ``dt_us`` in the C3 contract.
            fraction = (z_stop_mm - previous_z) / (z - previous_z)
            return elapsed - h + h * fraction
    raise RuntimeError("axis integration did not reach stop plane within max_elapsed_us")
