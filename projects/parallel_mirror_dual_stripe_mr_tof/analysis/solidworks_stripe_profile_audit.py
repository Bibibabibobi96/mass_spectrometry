#!/usr/bin/env python3
"""Read long physical Stripe boundary B-splines from the open CAD assembly."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.cad_pose_contract import (
    load_cad_pose_contract,
    source_to_project,
)


def _pair(value: float) -> tuple[int, int]:
    return struct.unpack("ii", struct.pack("d", float(value)))


def _sw_to_source(point_m, transform):
    return tuple(
        (sum(float(transform[row * 3 + column]) * float(point_m[column]) for column in range(3)) + float(transform[9 + row])) * 1000.0
        for row in range(3)
    )


def _project(point_m, transform, frame):
    return source_to_project(_sw_to_source(point_m, transform), frame)


def _bspline(edge, transform, frame):
    values = list(edge.GetCurve.GetBCurveParams3(True, False, True))
    dimension, order = _pair(values[0])
    count, periodic = _pair(values[1])
    knot_end = 2 + count + order
    controls = values[knot_end:knot_end + count * dimension]
    if dimension != 3 or len(controls) != count * dimension:
        raise RuntimeError("unexpected SolidWorks B-spline layout")
    points = [
        _project(controls[index * dimension:(index + 1) * dimension], transform, frame)
        for index in range(count)
    ]
    return {
        "order": order,
        "periodic": bool(periodic),
        "knots": [float(value) for value in values[2:knot_end]],
        "control_points_project_mm": [list(point) for point in points],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    frame = load_cad_pose_contract(arguments.frame)

    import win32com.client

    application = win32com.client.GetActiveObject("SldWorks.Application.30")
    assemblies = [
        document for document in application.GetDocuments
        if int(document.GetType) == 2
        and any("ion foil 1" in f"{component.Name2} {component.GetPathName}".lower() for component in document.GetComponents(True))
    ]
    if len(assemblies) != 1:
        raise RuntimeError(f"expected one Ion Foil assembly, found {len(assemblies)}")
    assignments = frame["stable_candidate_assignment"]
    wanted = assignments["drift_stripe_set_1"] + assignments["drift_stripe_set_2"]
    records = []
    for component in assemblies[0].GetComponents(True):
        instance = str(component.Name2).lower()
        matched = next((name for name in wanted if instance.endswith(name)), None)
        if matched is None:
            continue
        body = component.GetModelDoc2.GetBodies2(0, True)[0]
        transform = list(component.Transform2.ArrayData)
        long_edges = []
        for index, edge in enumerate(body.GetEdges()):
            start = edge.GetStartVertex
            end = edge.GetEndVertex
            if start is None or end is None:
                continue
            start_project = _project(start.GetPoint, transform, frame)
            end_project = _project(end.GetPoint, transform, frame)
            if abs(start_project[1] - end_project[1]) < 300.0:
                continue
            try:
                spline = _bspline(edge, transform, frame)
            except Exception:
                continue
            long_edges.append({"edge_index": index, "start_project_mm": list(start_project), "end_project_mm": list(end_project), "bspline": spline})
        records.append({"instance_name": matched, "long_bspline_edges": long_edges})
    records.sort(key=lambda record: wanted.index(record["instance_name"]))
    if [record["instance_name"] for record in records] != wanted:
        raise RuntimeError("not all four physical Stripe instances were found")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps({"schema_version": 1, "frame_id": frame["target_frame"], "stripes": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SOLIDWORKS_STRIPE_PROFILE_AUDIT: stripes={len(records)} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
