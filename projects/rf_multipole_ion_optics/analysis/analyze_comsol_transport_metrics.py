"""Derive finite-3D COMSOL transport metrics from canonical state/event exports."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import stdev
from typing import Any


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"CSV is empty: {path}")
    return rows


def _finite(row: dict[str, str], field: str) -> float:
    value = float(row[field])
    if not math.isfinite(value):
        raise ValueError(f"state field is not finite: {field}")
    return value


def _case_metrics(
    state_rows: list[dict[str, str]], event_rows: list[dict[str, str]], case_id: str,
    entrance_aperture_radius_mm: float, exit_aperture_radius_mm: float,
) -> dict[str, Any]:
    source = {row["particle_id"] for row in state_rows if row["event"] == "source"}
    terminal = [row for row in state_rows if row["event"] == "terminal"]
    if not source or {row["particle_id"] for row in terminal} != source:
        raise ValueError(f"terminal state does not close source cohort for {case_id}")
    transmitted = [row for row in terminal if row["status"] == "transmitted"]
    radii = [_finite(row, "radial_position_mm") for row in transmitted]
    energies = [_finite(row, "kinetic_energy_eV") for row in transmitted]
    max_rods = [_finite(row, "max_rod_radius_mm") for row in terminal]
    rows = [row for row in event_rows if row["case_id"] == case_id]
    if {row["particle_id"] for row in rows} != source:
        raise ValueError(f"event rows do not close source cohort for {case_id}")
    entrance = [float(row["entrance_aperture_radius_mm"]) for row in rows]
    exit_values = [float(row["exit_aperture_radius_mm"]) for row in rows]
    return {
        "particles": len(source),
        "transmitted": len(transmitted),
        "transmission_fraction": len(transmitted) / len(source),
        "entrance_passed": sum(value <= entrance_aperture_radius_mm for value in entrance if math.isfinite(value)),
        "exit_passed": sum(value <= exit_aperture_radius_mm for value in exit_values if math.isfinite(value)),
        "exit_rms_radius_mm": math.sqrt(sum(value * value for value in radii) / len(radii)) if radii else None,
        "mean_output_energy_eV": sum(energies) / len(energies) if energies else None,
        "output_energy_standard_deviation_eV": stdev(energies) if len(energies) > 1 else None,
        "maximum_rod_radius_mm": max(max_rods),
    }


def derive(events: list[dict[str, str]], primary_state: list[dict[str, str]], control_state: list[dict[str, str]], resolved: dict[str, Any], numerics: dict[str, Any]) -> dict[str, Any]:
    topology = resolved["axial_drive"]["topology"]
    geometry = resolved["geometry_mm"]
    interfaces = resolved["interfaces_mm"]
    if topology == "exit_aperture_plate_potential_step":
        primary_case, control_case = "exit_aperture_plate_acceleration_rf_on", "zero_exit_aperture_plate_drop_rf_on"
    elif topology == "segmented_rod_axial_acceleration":
        primary_case, control_case = "axial_acceleration_rf_on", "zero_axial_drop_rf_on"
    else:
        primary_case, control_case = "finite_3d_rf_on", "zero_rf_control"
    primary = _case_metrics(
        primary_state, events, primary_case, interfaces["entrance"]["aperture_radius_mm"],
        interfaces["exit"]["aperture_radius_mm"],
    )
    control = _case_metrics(
        control_state, events, control_case, interfaces["entrance"]["aperture_radius_mm"],
        interfaces["exit"]["aperture_radius_mm"],
    )
    return {
        "schema_version": 1,
        "role": "multipole_finite_3d_transport_metrics",
        "metrics_authority": "python_canonical_particle_state_and_events",
        "status": "UNQUALIFIED",
        "project_id": resolved["identity"]["project_id"],
        "model_level": "L3",
        "selected_geometry": {
            "rod_radius_ratio": geometry["rod_radius_ratio"],
            "rod_radius_mm": geometry["rod_radius"],
            "rod_center_radius_mm": geometry["rod_center_radius"],
        },
        "voltage_contract": resolved["drive"],
        "interface_geometry_mm": {
            "entrance_aperture_radius": interfaces["entrance"]["aperture_radius_mm"],
            "exit_aperture_radius": interfaces["exit"]["aperture_radius_mm"],
            "release_plane_z": interfaces["entrance"]["release_plane_z_mm"],
            "census_plane_z": interfaces["exit"]["census_plane_z_mm"],
        },
        "primary_case_id": primary_case,
        "control_case_id": control_case,
        "cases": {primary_case: primary, control_case: control},
        "rf_minus_zero_transmission": primary["transmission_fraction"] - control["transmission_fraction"],
        "axial_drive_topology": topology,
        "mesh": {
            "global_auto_level": numerics["mesh"]["global_auto_level"],
            "working_region_hmax_mm": numerics["mesh"]["working_region_maximum_element_size_mm"],
        },
        "claim_limit": "Python-derived canonical-state metrics only; no evidence claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--primary-state", type=Path, required=True)
    parser.add_argument("--control-state", type=Path, required=True)
    parser.add_argument("--resolved-design", type=Path, required=True)
    parser.add_argument("--numerics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = derive(
        _rows(args.events), _rows(args.primary_state), _rows(args.control_state),
        json.loads(args.resolved_design.read_text(encoding="utf-8-sig")),
        json.loads(args.numerics.read_text(encoding="utf-8-sig")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
