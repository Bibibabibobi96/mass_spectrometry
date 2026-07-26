"""Render the auditable oa-TOF Candidate Workbench GEM source.

This is deliberately a source generator, not a SIMION launcher.  SIMION GUI
materializes the binary IOB/CON from the resulting W-GEM, after which the
existing registration gate owns structure verification and provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOLVED_GEOMETRY = PROJECT_ROOT / "config" / "resolved_geometry.json"
ROLE_ORDER = ("flight_tube_shield", "reflectron", "accelerator", "detector")
ROLE_SYMMETRY = {
    "flight_tube_shield": "cylindrical",
    "reflectron": "cylindrical",
    "accelerator": "planar",
    "detector": "planar",
}


def render_wgem(resolved_path: Path = RESOLVED_GEOMETRY) -> str:
    """Return a four-slot W-GEM whose order is the GUI priority contract."""
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    instances = payload["derived"]["simion_instances"]
    build = payload["simion_geometry_build"]
    detector = payload["simion_detector_marker"]
    if [item["role"] for item in instances] != list(ROLE_ORDER):
        raise ValueError("resolved SIMION instances must use the canonical four-slot order")
    source_sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
    lines = [
        "-- GENERATED: oa-TOF Candidate declarative workbench source",
        "-- Materialize via SIMION New/Modify then View; do not edit generated transforms.",
        f"-- resolved_geometry_sha256={source_sha256}",
        "-- GUI priority is pa_define order: 1 flight_tube, 2 reflectron, 3 accelerator, 4 detector.",
        "-- This structural template defines no electrodes; the existing Candidate PA builders remain the only field source.",
        "",
    ]
    for expected_index, instance in enumerate(instances, start=1):
        if instance["workbench_index"] != expected_index or instance["priority_number"] != expected_index:
            raise ValueError(f"resolved instance priority is invalid: {instance['role']}")
        role = instance["role"]
        if role == "accelerator":
            dx, dy, dz = build["accelerator"]["cell_xy_mm"], build["accelerator"]["cell_xy_mm"], build["accelerator"]["cell_z_mm"]
        elif role == "detector":
            dx, dy, dz = detector["cell_xy_mm"], detector["cell_xy_mm"], detector["cell_z_mm"]
        elif role == "reflectron":
            dx, dy, dz = build["reflectron"]["cell_axial_mm"], build["reflectron"]["cell_radial_mm"], build["reflectron"]["cell_radial_mm"]
        else:
            dx, dy, dz = build["flight_tube"]["cell_axial_mm"], build["flight_tube"]["cell_radial_mm"], build["flight_tube"]["cell_radial_mm"]
        lines.extend((
            f"-- role={role}; workbench_index={expected_index}; priority_number={expected_index}; filename={instance['name']}",
            "locate({x:.15g},{y:.15g},{z:.15g},1,1,1,{az:.15g},0,0) {{".format(
                x=instance["x_mm"], y=instance["y_mm"], z=instance["z_mm"], az=instance["az_deg"]
            ),
            "  pa_define {{nx={nx}, ny={ny}, nz={nz}, symmetry='{symmetry}', dx={dx:.15g}, dy={dy:.15g}, dz={dz:.15g}, filename='{filename}'}}".format(
                nx=instance["nx"], ny=instance["ny"], nz=instance["nz"], symmetry=ROLE_SYMMETRY[role],
                dx=dx, dy=dy, dz=dz, filename=instance["name"],
            ),
            "}",
            "",
        ))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render oa-TOF Candidate W-GEM without launching SIMION.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolved-geometry", type=Path, default=RESOLVED_GEOMETRY)
    args = parser.parse_args()
    args.output.write_text(render_wgem(args.resolved_geometry), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
