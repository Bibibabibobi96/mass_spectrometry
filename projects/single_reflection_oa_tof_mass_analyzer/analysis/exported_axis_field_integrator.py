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
    """Load and validate a strictly increasing total-axis field CSV."""
    with path.open(newline="", encoding="utf-8") as stream:
        values = list(csv.DictReader(stream))
    if len(values) < 2:
        raise ValueError("axis field needs at least two samples")
    z = np.asarray([float(row["z_mm"]) for row in values], dtype=float)
    ez = np.asarray([float(row["Ez_V_per_mm"]) for row in values], dtype=float)
    if not (np.all(np.isfinite(z)) and np.all(np.isfinite(ez)) and np.all(np.diff(z) > 0)):
        raise ValueError("axis field must be finite and strictly increasing")
    return AxisField(z_mm=z, ez_v_per_mm=ez)


def integrate_axis_to_plane_us(
    field: AxisField, *, z0_mm: float, vz0_mm_per_us: float, z_stop_mm: float,
    mass_th: float, charge_state: int, dt_us: float = 1.0e-5,
) -> float:
    """Integrate positive-z motion to ``z_stop_mm`` using RK4 with interpolated E.

    The caller must supply a start and stop within the exported field extent;
    failure to reach the stop plane is explicit rather than silently clipped.
    """
    if not (field.z_mm[0] <= z0_mm < z_stop_mm <= field.z_mm[-1]):
        raise ValueError("start/stop plane lies outside exported field")
    if mass_th <= 0 or charge_state == 0 or dt_us <= 0:
        raise ValueError("mass, charge, and time step must be nonzero and positive where applicable")
    q_over_m_si = charge_state * ELEMENTARY_CHARGE_C / (mass_th * ATOMIC_MASS_KG)
    # 1 V/mm = 1e3 V/m; 1 m/s^2 = 1e-9 mm/us^2.
    def acceleration(z_mm: float) -> float:
        return q_over_m_si * float(np.interp(z_mm, field.z_mm, field.ez_v_per_mm * 1.0e3)) * 1.0e-9
    z, v, elapsed = z0_mm, vz0_mm_per_us, 0.0
    for _ in range(10_000_000):
        if z >= z_stop_mm:
            return elapsed
        h = min(dt_us, (z_stop_mm - z) / max(v, 1.0e-12))
        a1 = acceleration(z); k1z, k1v = v, a1
        a2 = acceleration(z + 0.5 * h * k1z); k2z, k2v = v + 0.5 * h * k1v, a2
        a3 = acceleration(z + 0.5 * h * k2z); k3z, k3v = v + 0.5 * h * k2v, a3
        a4 = acceleration(z + h * k3z); k4z, k4v = v + h * k3v, a4
        z += h * (k1z + 2 * k2z + 2 * k3z + k4z) / 6
        v += h * (k1v + 2 * k2v + 2 * k3v + k4v) / 6
        elapsed += h
    raise RuntimeError("axis integration did not reach stop plane")
