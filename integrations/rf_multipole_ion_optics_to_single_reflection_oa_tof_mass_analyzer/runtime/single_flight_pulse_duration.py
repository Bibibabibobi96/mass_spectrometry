"""Derive a detector-blind pulse duration from a frozen restart population.

This adapter maps instrument coordinates to the accelerator's existing ideal
three-zone oracle. It does not fit a source manifold or predict real-field hits.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

from common.contracts.machine_contracts import ContractError
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
)
from projects.orthogonal_accelerator.analysis.three_zone_ideal_theory import (
    exact_accelerator_normalized_time_from_state,
)


DURATION_POLICY_ID = "frozen_restart_ideal_focus_envelope_v1"


def derive_pulse_duration(
    rows: list[dict[str, Any]], geometry: dict[str, Any], *, minimum_width_us: float,
) -> dict[str, Any]:
    """Return the longest ideal time to the existing focus, in us.

All canonical global restart rows participate. The configured width is a lower
bound, never shortened. Invalid or out-of-stage-one states fail explicitly:
discarding them would silently change the population used for this estimate.
"""
    topology = geometry["accelerator_topology"]
    planes, potentials = topology["planes_global_z_mm"], topology["potentials_v"]
    names = ("repeller", "intermediate1", "intermediate2", "exit")
    positions = [float(planes[name]) for name in names]
    voltages = [float(potentials[name]) for name in names]
    drift = float(geometry["geometry_mm"]["accelerator_focus_z"]) - positions[-1]
    if not rows or not all(math.isfinite(v) for v in positions + voltages + [drift, minimum_width_us]):
        raise ContractError("pulse duration requires finite geometry and nonempty restart states")
    lengths = [b - a for a, b in zip(positions, positions[1:])]
    drops = [a - b for a, b in zip(voltages, voltages[1:])]
    if min(lengths + drops + [minimum_width_us]) <= 0 or drift < 0:
        raise ContractError("pulse duration requires three accelerating zones and a downstream focus")
    fields = [drop / length for drop, length in zip(drops, lengths)]
    # The oracle only reads these six field properties. Subtract the exit
    # potential to preserve gauge invariance without re-solving the design.
    state = SimpleNamespace(
        repeller_v=voltages[0] - voltages[3], grid1_v=voltages[1] - voltages[3],
        grid2_v=voltages[2] - voltages[3], field1_v_per_mm=fields[0],
        field2_v_per_mm=fields[1], field3_v_per_mm=fields[2],
    )
    exit_times, focus_times = [], []
    for row in rows:
        x = float(row["position_z_mm"]) - positions[0]
        vz = float(row["velocity_z_m_s"])
        mass, charge = float(row["mass_amu"]), float(row["charge_state"])
        if not all(math.isfinite(v) for v in (x, vz, mass, charge)) or min(mass, charge) <= 0:
            raise ContractError("pulse duration restart state has invalid mass, charge or axial state")
        scale = math.sqrt(mass * ATOMIC_MASS_CONSTANT_KG / (2 * charge * ELEMENTARY_CHARGE_C))
        chi = vz * scale
        if not 0 < x < lengths[0] or (vz < 0 and chi * chi >= fields[0] * x):
            raise ContractError("pulse duration oracle requires stage-one states not striking the repeller")
        exit_times.append(float(exact_accelerator_normalized_time_from_state(state, x, chi, 0)) * scale * 1000)
        focus_times.append(float(exact_accelerator_normalized_time_from_state(state, x, chi, drift)) * scale * 1000)
    limiting = max(range(len(rows)), key=focus_times.__getitem__)
    return {
        "policy_id": DURATION_POLICY_ID,
        "particle_count": len(rows),
        "limiting_particle_id": int(rows[limiting]["particle_id"]),
        "minimum_width_us": minimum_width_us,
        "ideal_max_exit_time_us": max(exit_times),
        "ideal_max_focus_time_us": focus_times[limiting],
        "focus_drift_mm": drift,
        "pulse_width_us": max(minimum_width_us, focus_times[limiting]),
        "claim_limit": "IDEAL_FIELD_DURATION_ESTIMATE_NOT_REAL_FIELD_EXIT_GUARANTEE",
    }
