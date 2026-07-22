"""Validate and resolve finite-3D multipole interface geometry.

Inputs use millimetres and are solver independent.  The resolved contract adds
absolute axial coordinates consumed by COMSOL and particle-source generation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.family_contract import from_high_order_baseline


class Finite3DContractError(ValueError):
    """Raised when a finite-3D interface contract is inconsistent."""


def _finite_number(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise Finite3DContractError(f"{key} must be a finite number")
    return float(value)


def _positive_number(mapping: dict[str, Any], key: str) -> float:
    value = _finite_number(mapping, key)
    if value <= 0:
        raise Finite3DContractError(f"{key} must be a finite positive number")
    return value


def _nonnegative_number(mapping: dict[str, Any], key: str) -> float:
    value = _finite_number(mapping, key)
    if value < 0:
        raise Finite3DContractError(f"{key} must be a finite nonnegative number")
    return value


def _require_exact_keys(mapping: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(mapping)
    if actual != expected:
        raise Finite3DContractError(
            f"{context} fields differ: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def _resolve_interface(interface: dict[str, Any], name: str) -> dict[str, float]:
    if not isinstance(interface, dict):
        raise Finite3DContractError(f"geometry_mm.{name}_interface must be an object")
    _require_exact_keys(
        interface,
        {
            "aperture_radius_mm",
            "plate_thickness_mm",
            "rod_clearance_mm",
            "particle_plane_distance_mm",
            "outer_ground_clearance_mm",
            "connector_length_mm",
        },
        f"geometry_mm.{name}_interface",
    )
    return {
        "aperture_radius_mm": _positive_number(interface, "aperture_radius_mm"),
        "plate_thickness_mm": _positive_number(interface, "plate_thickness_mm"),
        "rod_clearance_mm": _nonnegative_number(interface, "rod_clearance_mm"),
        "particle_plane_distance_mm": _positive_number(interface, "particle_plane_distance_mm"),
        "outer_ground_clearance_mm": _positive_number(interface, "outer_ground_clearance_mm"),
        "connector_length_mm": _nonnegative_number(interface, "connector_length_mm"),
    }


def resolve_contract(baseline: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Return a validated contract with all axial coordinates resolved."""
    operating = from_high_order_baseline(baseline)
    _require_exact_keys(
        contract,
        {
            "schema_version",
            "role",
            "project_id",
            "model_level",
            "multipole",
            "geometry_mm",
            "mesh",
            "trajectory",
            "functional_acceptance",
            "claim_limit",
        },
        "finite-3D contract",
    )
    if contract.get("schema_version") != 2:
        raise Finite3DContractError("finite-3D contract schema_version must be 2")
    if contract.get("role") != "multipole_finite_3d_interface_transport_contract":
        raise Finite3DContractError("finite-3D contract role is invalid")
    if contract.get("project_id") != baseline.get("project_id"):
        raise Finite3DContractError("baseline and finite-3D project_id differ")
    if contract.get("model_level") != "L3":
        raise Finite3DContractError("finite-3D interface contract must remain model level L3")
    multipole = contract.get("multipole")
    expected_identity = {
        "radial_order_n": operating.identity.radial_order_n,
        "electrode_count": operating.identity.electrode_count,
    }
    if not isinstance(multipole, dict) or multipole != expected_identity:
        raise Finite3DContractError("baseline and finite-3D multipole identities differ")

    geometry = contract.get("geometry_mm")
    if not isinstance(geometry, dict):
        raise Finite3DContractError("geometry_mm must be an object")
    _require_exact_keys(
        geometry,
        {
            "rod_z_min",
            "grounded_shield_inner_radius",
            "grounded_shield_wall_thickness",
            "grounded_outer_end_cap_thickness",
            "working_region_radius",
            "entrance_interface",
            "exit_interface",
        },
        "geometry_mm",
    )
    rod_z_min = _finite_number(geometry, "rod_z_min")
    shield_radius = _positive_number(geometry, "grounded_shield_inner_radius")
    shield_wall = _positive_number(geometry, "grounded_shield_wall_thickness")
    outer_cap = _positive_number(geometry, "grounded_outer_end_cap_thickness")
    working_radius = _positive_number(geometry, "working_region_radius")
    entrance = _resolve_interface(geometry.get("entrance_interface"), "entrance")
    exit_interface = _resolve_interface(geometry.get("exit_interface"), "exit")
    rod_length = operating.geometry.effective_length_mm
    usable_radius = _positive_number(baseline.get("geometry_mm", {}), "usable_radius")
    if working_radius > usable_radius:
        raise Finite3DContractError("working_region_radius exceeds baseline usable_radius")
    for name, interface in (("entrance", entrance), ("exit", exit_interface)):
        if interface["aperture_radius_mm"] > working_radius:
            raise Finite3DContractError(f"{name} aperture_radius_mm exceeds working_region_radius")
        if interface["aperture_radius_mm"] >= shield_radius:
            raise Finite3DContractError(f"{name} aperture_radius_mm must be inside the grounded shield")

    mesh = contract.get("mesh")
    if not isinstance(mesh, dict):
        raise Finite3DContractError("mesh must be an object")
    _require_exact_keys(mesh, {"global_auto_level", "working_region_maximum_element_size_mm"}, "mesh")
    auto_level = mesh.get("global_auto_level")
    if not isinstance(auto_level, int) or isinstance(auto_level, bool) or not 1 <= auto_level <= 9:
        raise Finite3DContractError("global_auto_level must be an integer from 1 through 9")
    _positive_number(mesh, "working_region_maximum_element_size_mm")

    trajectory = contract.get("trajectory")
    if not isinstance(trajectory, dict):
        raise Finite3DContractError("trajectory must be an object")
    _require_exact_keys(trajectory, {"rf_steps_per_period", "maximum_global_time_us"}, "trajectory")
    steps = trajectory.get("rf_steps_per_period")
    if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0:
        raise Finite3DContractError("rf_steps_per_period must be a positive integer")
    _positive_number(trajectory, "maximum_global_time_us")

    acceptance = contract.get("functional_acceptance")
    if not isinstance(acceptance, dict):
        raise Finite3DContractError("functional_acceptance must be an object")
    _require_exact_keys(
        acceptance,
        {"minimum_rf_transmission", "minimum_improvement_over_zero_rf"},
        "functional_acceptance",
    )
    for key in ("minimum_rf_transmission", "minimum_improvement_over_zero_rf"):
        value = _finite_number(acceptance, key)
        if not 0 <= value <= 1:
            raise Finite3DContractError(f"{key} must be between zero and one")
    if not isinstance(contract.get("claim_limit"), str) or not contract["claim_limit"].strip():
        raise Finite3DContractError("claim_limit must be a nonempty string")

    rod_z_max = rod_z_min + rod_length
    entrance_plate_z_max = rod_z_min - entrance["rod_clearance_mm"]
    entrance_plate_z_min = entrance_plate_z_max - entrance["plate_thickness_mm"]
    source_z = entrance_plate_z_min - entrance["connector_length_mm"] - entrance["particle_plane_distance_mm"]
    entrance_outer_ground_inner_z = source_z - entrance["outer_ground_clearance_mm"]
    vacuum_z_min = entrance_outer_ground_inner_z - outer_cap

    exit_plate_z_min = rod_z_max + exit_interface["rod_clearance_mm"]
    exit_plate_z_max = exit_plate_z_min + exit_interface["plate_thickness_mm"]
    detector_z = exit_plate_z_max + exit_interface["connector_length_mm"] + exit_interface["particle_plane_distance_mm"]
    exit_outer_ground_inner_z = detector_z + exit_interface["outer_ground_clearance_mm"]
    vacuum_z_max = exit_outer_ground_inner_z + outer_cap
    if entrance_plate_z_max > rod_z_min or exit_plate_z_min < rod_z_max:
        raise Finite3DContractError("interface plate overlaps a rod end")

    resolved = json.loads(json.dumps(contract))
    resolved["role"] = "multipole_finite_3d_interface_transport_resolved_contract"
    resolved["derived_geometry_mm"] = {
        "rod_length": rod_length,
        "rod_z_max": rod_z_max,
        "vacuum_z_min": vacuum_z_min,
        "vacuum_z_max": vacuum_z_max,
        "source_z": source_z,
        "detector_z": detector_z,
        "entrance_plate_z_min": entrance_plate_z_min,
        "entrance_plate_z_max": entrance_plate_z_max,
        "exit_plate_z_min": exit_plate_z_min,
        "exit_plate_z_max": exit_plate_z_max,
        "entrance_outer_ground_inner_z": entrance_outer_ground_inner_z,
        "exit_outer_ground_inner_z": exit_outer_ground_inner_z,
        "shield_outer_radius": shield_radius + shield_wall,
    }
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    resolved = resolve_contract(baseline, contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
