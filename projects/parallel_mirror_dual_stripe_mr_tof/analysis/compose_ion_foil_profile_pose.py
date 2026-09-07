"""Compose read-only Ion-Foil body curves into the project coordinate frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.cad_pose_contract import (
    load_cad_pose_contract,
    source_to_project,
)


def _transform_point(point_m: list[float], array: list[float]) -> tuple[float, float, float]:
    """Apply a SolidWorks row-vector rigid transform and return source mm."""
    if len(array) < 13 or abs(float(array[12]) - 1.0) > 1e-12:
        raise ValueError("SolidWorks transform must be a unit-scale rigid ArrayData")
    return tuple(
        (sum(float(point_m[index]) * float(array[index * 3 + column]) for index in range(3)) + float(array[9 + column])) * 1000.0
        for column in range(3)
    )


def _pose_index(top_level: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = top_level.get("ion_foil_component_poses")
    if not isinstance(records, list):
        raise ValueError("top-level pose lacks ion_foil_component_poses")
    return {str(record["local_instance"]): record for record in records}


def _project_edge(edge: dict[str, Any], transform: list[float], frame: dict[str, Any]) -> dict[str, Any]:
    spline = edge["bspline"]
    controls = spline.get("control_points_component_m")
    if not isinstance(controls, list):
        raise ValueError("profile receipt must provide component-local B-spline controls")
    points = [list(source_to_project(_transform_point(point, transform), frame)) for point in controls]
    return {
        "edge_index": int(edge["edge_index"]),
        "order": int(spline["order"]),
        "periodic": bool(spline["periodic"]),
        "knots": [float(value) for value in spline["knots"]],
        "control_points_project_mm": points,
    }


def _project_component(record: dict[str, Any], poses: dict[str, dict[str, Any]], frame: dict[str, Any]) -> dict[str, Any]:
    source_name = str(record["source_instance_name"])
    pose = poses.get(source_name)
    if pose is None:
        raise ValueError(f"top-level pose is missing {source_name}")
    transform = [float(value) for value in pose["solidworks_transform_array"]]
    return {
        "instance_name": str(record["instance_name"]),
        "source_instance_name": source_name,
        "long_bspline_edges": [_project_edge(edge, transform, frame) for edge in record["long_bspline_edges"]],
    }


def compose(profile: dict[str, Any], top_level: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    """Return the stable project-frame B-spline receipt for all Ion-Foil bodies."""
    if profile.get("coordinate_frame") != "opened Ion-Foil assembly, millimetres":
        raise ValueError("profile receipt must retain its assembly coordinate identity")
    poses = _pose_index(top_level)
    return {
        "schema_version": 1,
        "frame_id": frame["target_frame"],
        "method": "component-local B-spline controls -> top-level SolidWorks row-vector transform -> cad_to_theory_frame",
        "stripes": [_project_component(record, poses, frame) for record in profile["stripes"]],
        "central_ground": _project_component(profile["central_ground"], poses, frame),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--top-level-pose", required=True, type=Path)
    parser.add_argument("--frame", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = compose(
        json.loads(arguments.profiles.read_text(encoding="utf-8")),
        json.loads(arguments.top_level_pose.read_text(encoding="utf-8")),
        load_cad_pose_contract(arguments.frame),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"COMPOSE_ION_FOIL_PROFILE_POSE: stripes={len(result['stripes'])} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
