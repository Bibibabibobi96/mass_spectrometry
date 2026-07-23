"""Adapt the quadrupole reference geometry to the shared finite-3D solver contract."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.particle_state import ion11_sources


def build_inputs(
    resolved: dict[str, Any],
    operating: dict[str, Any],
    particle_table: Path,
    entrance_connector_length_mm: float | None = None,
    exit_connector_length_mm: float | None = None,
) -> dict[str, Any]:
    """Return normalized shared-solver inputs without changing quadrupole geometry."""
    identity = operating["identity"]
    if identity["project_id"] != "rf_quadrupole_collision_cooling":
        raise ValueError("quadrupole adapter project identity differs")
    if (identity["radial_order_n"], identity["electrode_count"]) != (2, 4):
        raise ValueError("quadrupole adapter requires radial order 2 and four electrodes")
    states = ion11_sources(particle_table)
    validate_standard_particle_count(len(states))
    rows = [line for line in particle_table.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    first = [float(value) for value in rows[0].split(",")]
    if any(float(row.split(",")[1]) != first[1] or float(row.split(",")[2]) != first[2] for row in rows):
        raise ValueError("shared COMSOL run requires one mass and charge state")

    geometry = resolved["geometry_mm"]
    interfaces = resolved["interface_layout_mm"]
    rod_array = resolved["rod_array_mm"]
    mode = resolved["mode"]
    detector_radius = float(geometry["detector_radius"])
    entrance_connector_length = (
        float(interfaces["entrance"]["connector_length_mm"])
        if entrance_connector_length_mm is None
        else float(entrance_connector_length_mm)
    )
    exit_connector_length = (
        float(interfaces["exit"]["connector_length_mm"])
        if exit_connector_length_mm is None
        else float(exit_connector_length_mm)
    )
    if entrance_connector_length < 0 or exit_connector_length < 0:
        raise ValueError("connector lengths must be nonnegative")
    available_entrance_length = float(interfaces["entrance"]["plate_z_min_mm"]) - float(
        geometry["release_z"]
    )
    if entrance_connector_length > available_entrance_length:
        raise ValueError("entrance connector overlaps the quadrupole source plane")
    normalized_baseline = {
        "schema_version": 1,
        "project_id": identity["project_id"],
        "family_contract_id": identity["family_id"],
        "multipole": {
            "radial_order_n": 2,
            "electrode_count": 4,
            "orientation_rad": float(resolved["multipole"]["orientation_rad"]),
        },
        "conventions": {
            "coordinate_id": identity["coordinate_convention_id"],
            "voltage_id": identity["voltage_convention_id"],
            "r0_id": identity["r0_convention_id"],
        },
        "geometry_mm": {
            "inscribed_radius_r0": float(geometry["field_radius_r0"]),
            "effective_length": float(geometry["rod_length"]),
            "usable_radius": detector_radius,
        },
        "particle_source": {
            "count": len(states),
            "mass_amu": first[1],
            "charge_state": int(first[2]),
            "kinetic_energy_eV": sum(float(row.split(",")[8]) for row in rows) / len(rows),
        },
    }
    selected = {
        "rod_radius_ratio": float(geometry["rod_radius_ratio"]),
        "rod_radius_mm": float(geometry["rod_radius"]),
        "rod_center_radius_mm": float(geometry["rod_center_radius"]),
    }
    field_metrics = {"schema_version": 1, "selected_candidate": selected}
    round_rods = {
        "schema_version": 1,
        "role": "multipole_round_rod_geometry_resolved_contract",
        "project_id": identity["project_id"],
        "coordinate_id": identity["coordinate_convention_id"],
        "identity": {
            "radial_order_n": 2,
            "electrode_count": 4,
            "orientation_rad": float(resolved["multipole"]["orientation_rad"]),
        },
        "array_mm": rod_array,
    }
    contract = {
        "schema_version": 3,
        "role": "multipole_finite_3d_interface_transport_resolved_contract",
        "project_id": identity["project_id"],
        "model_level": "L3",
        "geometry_model": "rectangular_reference_enclosure_v1",
        "multipole": {"radial_order_n": 2, "electrode_count": 4},
        "geometry_mm": {
            "rod_z_min": float(geometry["rod_z_min"]),
            "working_region_radius": detector_radius,
            "detector_radius_mm": detector_radius,
            "entrance_interface": {
                "aperture_radius_mm": float(interfaces["entrance"]["aperture_radius_mm"]),
                "connector_length_mm": entrance_connector_length,
                "connector_shape": "rectangular_bore",
            },
            "exit_interface": {
                "aperture_radius_mm": float(interfaces["exit"]["aperture_radius_mm"]),
                "connector_length_mm": exit_connector_length,
                "connector_shape": "rectangular_bore",
            },
            "reference_enclosure": {
                "outer_half_width_mm": float(geometry["exit_enclosure_outer_half_width"]),
                "inner_half_width_mm": float(geometry["exit_enclosure_inner_half_width"]),
                "exit_enclosure_z_min_mm": float(geometry["exit_enclosure_z_min"]),
                "exit_enclosure_z_max_mm": float(geometry["exit_enclosure_z_max"]),
                "exit_front_wall_end_z_mm": float(geometry["exit_enclosure_front_wall_end_z"]),
                "detector_thickness_mm": float(geometry["detector_thickness"]),
            },
        },
        "derived_geometry_mm": {
            "rod_length": float(geometry["rod_length"]),
            "rod_z_max": float(geometry["rod_z_max"]),
            "vacuum_z_min": 0.0,
            "vacuum_z_max": float(geometry["model_z_span"]),
            "source_z": float(geometry["release_z"]),
            "detector_z": float(interfaces["exit"]["particle_plane_z_mm"]),
            "entrance_plate_z_min": float(interfaces["entrance"]["plate_z_min_mm"]),
            "entrance_plate_z_max": float(interfaces["entrance"]["plate_z_max_mm"]),
            "exit_plate_z_min": float(interfaces["exit"]["plate_z_min_mm"]),
            "exit_plate_z_max": float(interfaces["exit"]["plate_z_max_mm"]),
        },
        "mesh": {
            "global_auto_level": int(mode["numerics"]["comsol_mesh_auto_level"]),
            "working_region_maximum_element_size_mm": None,
        },
        "trajectory": {
            "rf_steps_per_period": int(mode["numerics"]["comsol_rf_steps_per_period"]),
            "maximum_global_time_us": float(mode["numerics"]["maximum_time_us"]),
        },
        "functional_acceptance": {
            "minimum_rf_transmission": float(mode["numerics"]["minimum_expected_transmission"]),
            "minimum_improvement_over_zero_rf": 0.0,
        },
        "claim_limit": "Quadrupole reference enclosure through the shared finite-3D COMSOL solver; functional only.",
    }
    particle_rows = []
    for particle_id, state in states.items():
        particle_rows.append(
            {
                "particle_id": particle_id,
                "birth_time_s": state["time_us"] * 1e-6,
                "x_mm": state["transverse_x_mm"],
                "y_mm": state["transverse_y_mm"],
                "z_mm": state["axial_z_mm"],
                "vx_m_s": state["velocity_x_m_s"],
                "vy_m_s": state["velocity_y_m_s"],
                "vz_m_s": state["velocity_axial_m_s"],
            }
        )
    return {
        "baseline": normalized_baseline,
        "contract": contract,
        "field_metrics": field_metrics,
        "round_rod_geometry": round_rods,
        "particle_source": particle_rows,
    }


def write_inputs(inputs: dict[str, Any], outputs: dict[str, Path]) -> None:
    """Write normalized JSON contracts and the canonical COMSOL source CSV."""
    for name in ("baseline", "contract", "field_metrics", "round_rod_geometry"):
        path = outputs[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(inputs[name], indent=2) + "\n", encoding="utf-8")
    source_path = outputs["particle_source"]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inputs["particle_source"][0]))
        writer.writeheader()
        writer.writerows(inputs["particle_source"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--operating", required=True, type=Path)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--entrance-connector-length-mm", type=float)
    parser.add_argument("--exit-connector-length-mm", type=float)
    for name in ("baseline", "contract", "field-metrics", "round-rod-geometry", "particle-source"):
        parser.add_argument(f"--{name}-output", required=True, type=Path)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    inputs = build_inputs(
        load(args.resolved),
        load(args.operating),
        args.particles,
        args.entrance_connector_length_mm,
        args.exit_connector_length_mm,
    )
    write_inputs(
        inputs,
        {
            "baseline": args.baseline_output,
            "contract": args.contract_output,
            "field_metrics": args.field_metrics_output,
            "round_rod_geometry": args.round_rod_geometry_output,
            "particle_source": args.particle_source_output,
        },
    )
    print(f"QUADRUPOLE_SHARED_L3_INPUTS=PASS PARTICLES={len(inputs['particle_source'])}")


if __name__ == "__main__":
    main()
