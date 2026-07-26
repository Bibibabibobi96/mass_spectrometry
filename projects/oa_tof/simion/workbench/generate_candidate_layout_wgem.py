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
ROLE_SOURCE_GEMS = {
    "flight_tube_shield": "../oatof_flight_tube_ground.gem",
    "reflectron": "../../reflectron/oatof_reflectron_ideal_10_5.gem",
    "accelerator": "../../accelerator/oatof_accelerator_3d.gem",
    "detector": "../oatof_detector_ground.gem",
}


def render_wgem(resolved_path: Path = RESOLVED_GEOMETRY) -> str:
    """Return a four-slot W-GEM whose order is the GUI priority contract."""
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    instances = payload["derived"]["simion_instances"]
    if [item["role"] for item in instances] != list(ROLE_ORDER):
        raise ValueError("resolved SIMION instances must use the canonical four-slot order")
    source_sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
    lines = [
        "-- GENERATED: oa-TOF Candidate declarative workbench source",
        "-- Materialize in SIMION 8.2.1.4 GUI; do not edit generated transforms.",
        f"-- resolved_geometry_sha256={source_sha256}",
        "-- GUI priority is pa_define order: 1 flight_tube, 2 reflectron, 3 accelerator, 4 detector.",
        "",
    ]
    for expected_index, instance in enumerate(instances, start=1):
        if instance["workbench_index"] != expected_index or instance["priority_number"] != expected_index:
            raise ValueError(f"resolved instance priority is invalid: {instance['role']}")
        role = instance["role"]
        lines.extend((
            f"-- role={role}; workbench_index={expected_index}; priority_number={expected_index}; source={ROLE_SOURCE_GEMS[role]}",
            "locate({x:.15g},{y:.15g},{z:.15g},{az:.15g},0,0,1) {{".format(
                x=instance["x_mm"], y=instance["y_mm"], z=instance["z_mm"], az=instance["az_deg"]
            ),
            f"  include(\"{ROLE_SOURCE_GEMS[role]}\")",
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
