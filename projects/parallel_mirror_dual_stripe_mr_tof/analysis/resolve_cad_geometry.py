#!/usr/bin/env python3
"""Resolve SolidWorks assembly evidence into project-frame CAD envelopes.

This is an evidence-preserving bridge, not a CAD mesher.  It applies every
recorded component rigid transform before the frozen CAD-to-theory transform
and records both source and target boxes in a run-local manifest.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.cad_pose_contract import (
    load_cad_pose_contract,
    source_to_project,
)


def _source_transform(point_m: tuple[float, float, float], values: list[float]) -> tuple[float, float, float]:
    """Apply SolidWorks' row-major rotation and metre translation."""
    if len(values) != 16:
        raise ValueError("SolidWorks transform must contain sixteen values")
    rotation = values[:9]
    translation = values[9:12]
    return tuple(
        sum(rotation[row * 3 + column] * point_m[column] for column in range(3)) + translation[row]
        for row in range(3)
    )


def _corners(box_m: list[float]) -> list[tuple[float, float, float]]:
    if len(box_m) != 6:
        raise ValueError("part box must have six coordinates")
    return [tuple(point) for point in itertools.product((box_m[0], box_m[3]), (box_m[1], box_m[4]), (box_m[2], box_m[5]))]


def _box(points_mm: list[tuple[float, float, float]]) -> list[float]:
    return [min(point[axis] for point in points_mm) for axis in range(3)] + [max(point[axis] for point in points_mm) for axis in range(3)]


def resolve(assembly_evidence: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    resolved = []
    for component in assembly_evidence["components"]:
        local_box = component.get("local_part_box_m")
        if local_box is None or component.get("suppressed"):
            continue
        source_points_mm = [
            tuple(coordinate * 1000.0 for coordinate in _source_transform(corner, component["solidworks_transform_array"]))
            for corner in _corners(local_box)
        ]
        project_points_mm = [source_to_project(point, frame) for point in source_points_mm]
        resolved.append(
            {
                "instance_name": component["instance_name"],
                "part_path": component["part_path"],
                "source_assembly_box_mm": _box(source_points_mm),
                "project_box_mm": _box(project_points_mm),
            }
        )
    names = [item["instance_name"].lower() for item in resolved]
    for stripe in frame["stable_candidate_assignment"]["drift_stripe_set_1"] + frame["stable_candidate_assignment"]["drift_stripe_set_2"]:
        if not any(name.endswith(stripe) for name in names):
            raise ValueError(f"resolved CAD evidence lacks required physical Stripe {stripe!r}")
    return {
        "schema_version": 1,
        "project_id": "parallel_mirror_dual_stripe_mr_tof",
        "status": "candidate_cad_envelopes_resolved",
        "frame_id": frame["target_frame"],
        "input_assembly": assembly_evidence["assembly_path"],
        "components": sorted(resolved, key=lambda item: item["instance_name"].lower()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembly-evidence", type=Path, required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    evidence = json.loads(arguments.assembly_evidence.read_text(encoding="utf-8"))
    resolved = resolve(evidence, load_cad_pose_contract(arguments.frame))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CAD_GEOMETRY_RESOLVED: components={len(resolved['components'])} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
