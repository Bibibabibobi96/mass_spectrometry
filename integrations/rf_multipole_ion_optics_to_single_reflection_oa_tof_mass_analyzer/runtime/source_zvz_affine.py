"""Identify and freeze a source ``v_z = a + b z`` relation.

This is a source-contract feature, independent of the selected accelerator field
profile.  It never projects particle states or changes field voltages.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    compute_time_derivatives,
    derive_first_order_focus_drift,
    derive_three_zone_state,
)


POLICY_ID = "source_zvz_affine_identify_and_bind_v1"
ROLE = "rf_oatof_source_zvz_affine_receipt"


def _finite(value: object, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def identify(*, source_state_path: Path) -> dict[str, Any]:
    """Fit OLS from a frozen state and return the contract-bound relation."""
    with source_state_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("source state is empty or lacks z--vz columns")
    fields = set(rows[0])
    if {"position_z_mm", "velocity_z_m_s"}.issubset(fields):
        z_key, vz_key = "position_z_mm", "velocity_z_m_s"
    elif {"z_mm", "vz_m_s"}.issubset(fields):
        z_key, vz_key = "z_mm", "vz_m_s"
    else:
        raise ValueError("source state is empty or lacks z--vz columns")
    required = {"particle_id", "mass_amu", "charge_state", z_key, vz_key}
    if not required.issubset(fields):
        raise ValueError("source state is empty or lacks z--vz columns")
    ids = [int(row["particle_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("source state particle IDs are not unique")
    masses = {_finite(row["mass_amu"], "mass_amu") for row in rows}
    charges = {_finite(row["charge_state"], "charge_state") for row in rows}
    if len(masses) != 1 or len(charges) != 1 or next(iter(charges)) == 0.0:
        raise ValueError("source state must have one non-zero mass/charge")
    z = np.asarray([_finite(row[z_key], z_key) for row in rows])
    vz = np.asarray([_finite(row[vz_key], vz_key) for row in rows])
    centered = z - float(np.mean(z))
    if z.size < 3 or float(np.dot(centered, centered)) <= 1.0e-18:
        raise ValueError("source z--vz fit is degenerate")
    slope, intercept = np.polyfit(z, vz, 1)
    residual = vz - (intercept + slope * z)
    ordered = json.dumps(ids, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "role": ROLE,
        "policy_id": POLICY_ID,
        "source_state": {
            "sha256": file_sha256(source_state_path),
            "particle_count": len(rows),
            "ordered_particle_id_sha256": hashlib.sha256(ordered).hexdigest().upper(),
            "mean_global_z_mm": float(np.mean(z)),
            "mean_vz_m_per_s": float(np.mean(vz)),
            "ols_intercept_vz_m_per_s": float(intercept),
            "ols_slope_vz_m_per_s_per_mm": float(slope),
            "residual_rms_m_per_s": float(np.sqrt(np.mean(residual * residual))),
            "residual_max_abs_m_per_s": float(np.max(np.abs(residual))),
            "mass_to_charge_th": abs(next(iter(masses)) / next(iter(charges))),
        },
        "claim_limit": "The relation is a frozen run input for compatible analysis; it does not alter particle state, geometry, PA, or electrode potentials.",
    }


def write_receipt(output_path: Path, *, source_state_path: Path) -> dict[str, Any]:
    receipt = identify(source_state_path=source_state_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def _bisect(function: Any, lower: float, upper: float, label: str) -> float:
    left, right = _finite(lower, label + " lower"), _finite(upper, label + " upper")
    f_left, f_right = float(function(left)), float(function(right))
    if not math.isfinite(f_left) or not math.isfinite(f_right) or f_left * f_right > 0:
        raise ValueError(f"{label} is not bracketed")
    for _ in range(128):
        middle = (left + right) / 2.0
        value = float(function(middle))
        if not math.isfinite(value):
            raise ValueError(f"{label} became non-finite")
        if abs(value) < 1.0e-13:
            return middle
        if f_left * value <= 0:
            right, f_right = middle, value
        else:
            left, f_left = middle, value
    return (left + right) / 2.0


def derive_three_zone_working_point(
    *, source_receipt: dict[str, Any], resolved_geometry: dict[str, Any],
    resolved_geometry_input_sha256: str, theory_request: dict[str, Any],
) -> dict[str, Any]:
    """Derive all electrode potentials from source, geometry and explicit primitives.

    ``theory_request`` contains the *approved native constraints* of the design:
    ``first_zone_drop_v``, ``nominal_energy_per_charge_v`` and
    ``reflectron_stage1_voltage_v``.  All remaining voltages are derived; no
    historical candidate potential is an input to this routine.
    """
    geometry_sha256 = str(resolved_geometry_input_sha256).upper()
    if len(geometry_sha256) != 64 or any(
        character not in "0123456789ABCDEF" for character in geometry_sha256
    ):
        raise ValueError("resolved geometry input SHA-256 is invalid")
    required = {
        "first_zone_drop_v", "nominal_energy_per_charge_v",
        "reflectron_stage1_voltage_v",
    }
    if set(theory_request) != required:
        raise ValueError("theory request must contain exactly the native constraints")
    topology = resolved_geometry.get("accelerator_topology")
    if not isinstance(topology, dict) or topology.get("topology_id") != "three_zone_accelerator_ideal_v1":
        raise ValueError("automatic working point requires three-zone topology")
    planes = topology.get("planes_global_z_mm")
    if not isinstance(planes, dict):
        raise ValueError("three-zone plane mapping is missing")
    names = ("repeller", "intermediate1", "intermediate2", "exit")
    p = {name: _finite(planes[name], "plane " + name) for name in names}
    if not all(p[a] < p[b] for a, b in zip(names, names[1:])):
        raise ValueError("three-zone planes are not ordered")
    source = source_receipt.get("source_state", {})
    if source_receipt.get("role") != ROLE or source_receipt.get("policy_id") != POLICY_ID:
        raise ValueError("source receipt identity is unsupported")
    mass_to_charge = _finite(source["mass_to_charge_th"], "mass_to_charge_th")
    if mass_to_charge <= 0:
        raise ValueError("mass_to_charge_th must be positive")
    affine = AffineSource.from_velocity(
        mass_to_charge_th=mass_to_charge,
        center_x_mm=_finite(source["mean_global_z_mm"], "mean_global_z_mm") - p["repeller"],
        center_velocity_m_per_s=_finite(source["mean_vz_m_per_s"], "mean_vz_m_per_s"),
        velocity_slope_m_per_s_per_mm=_finite(source["ols_slope_vz_m_per_s_per_mm"], "OLS slope"),
    )
    d1, d2, d3 = p["intermediate1"] - p["repeller"], p["intermediate2"] - p["intermediate1"], p["exit"] - p["intermediate2"]
    first_drop = _finite(theory_request["first_zone_drop_v"], "first_zone_drop_v")
    nominal = _finite(theory_request["nominal_energy_per_charge_v"], "nominal_energy_per_charge_v")
    if first_drop <= 0 or nominal <= 0:
        raise ValueError("native voltage constraints must be positive")
    outer = OuterGeometry(d1, d2 + d3, d2 / (d2 + d3), first_drop, nominal)
    target_focus = _finite(
        resolved_geometry["geometry_derivation"]["accelerator"]["focus_drift_after_grid2_mm"],
        "focus_drift_after_grid2_mm",
    )
    eta = _bisect(
        lambda value: derive_first_order_focus_drift(
            affine, derive_three_zone_state(affine, outer, value)
        ) - target_focus,
        -8.0, 8.0, "accelerator first-order focus",
    )
    state = derive_three_zone_state(affine, outer, eta)
    geometry = resolved_geometry["geometry_mm"]
    reflectron = ReflectronGeometry(
        _finite(geometry["L_stage1"], "L_stage1"), _finite(geometry["L_stage2"], "L_stage2"),
        _finite(geometry["L_flight"], "L_flight"), _finite(geometry["L_flight"], "L_flight"),
    )
    stage1 = _finite(theory_request["reflectron_stage1_voltage_v"], "reflectron_stage1_voltage_v")
    stage2 = _bisect(
        lambda field: compute_time_derivatives(
            affine, state, reflectron, InnerSolution(stage1, field, eta)
        ).d1,
        1.0e-6, 1.0e4, "reflectron first-order focus",
    )
    derivatives = compute_time_derivatives(affine, state, reflectron, InnerSolution(stage1, stage2, eta))
    return {
        "role": "rf_oatof_theory_working_point",
        "policy_id": "source_zvz_three_zone_theory_working_point_v1",
        "source_state_sha256": source["sha256"],
        "resolved_geometry_input_sha256": geometry_sha256,
        "native_constraints": {key: _finite(theory_request[key], key) for key in sorted(required)},
        "accelerator_topology": {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": p,
            "potentials_v": {"repeller": state.repeller_v, "intermediate1": state.grid1_v, "intermediate2": state.grid2_v, "exit": state.exit_v},
        },
        "reflectron": {"entrance_voltage_v": 0.0, "stage1_voltage_v": stage1, "stage2_field_v_per_mm": stage2, "backplate_voltage_v": stage1 + stage2 * reflectron.stage2_length_mm},
        "verification": {"accelerator_focus_drift_mm": derive_first_order_focus_drift(affine, state), "reflectron_d1_mm_per_sqrt_v": derivatives.d1},
    }
