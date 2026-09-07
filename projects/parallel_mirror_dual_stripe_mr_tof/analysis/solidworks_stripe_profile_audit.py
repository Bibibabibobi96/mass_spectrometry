#!/usr/bin/env python3
"""Read long physical Stripe and central-ground B-splines from CAD read-only."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.cad_pose_contract import load_cad_pose_contract


SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT_READ_ONLY = 3


def _pair(value: float) -> tuple[int, int]:
    return struct.unpack("ii", struct.pack("d", float(value)))


def _sw_to_source(point_m, transform):
    return tuple(
        (sum(float(transform[row * 3 + column]) * float(point_m[column]) for column in range(3)) + float(transform[9 + row])) * 1000.0
        for row in range(3)
    )


def _bspline(edge, transform):
    values = list(edge.GetCurve.GetBCurveParams3(True, False, True))
    dimension, order = _pair(values[0])
    count, periodic = _pair(values[1])
    knot_end = 2 + count + order
    controls = values[knot_end:knot_end + count * dimension]
    if dimension != 3 or len(controls) != count * dimension:
        raise RuntimeError("unexpected SolidWorks B-spline layout")
    component_points = [controls[index * dimension:(index + 1) * dimension] for index in range(count)]
    assembly_points = [_sw_to_source(point, transform) for point in component_points]
    return {
        "order": order,
        "periodic": bool(periodic),
        "knots": [float(value) for value in values[2:knot_end]],
        "control_points_component_m": [list(map(float, point)) for point in component_points],
        "control_points_assembly_mm": [list(point) for point in assembly_points],
    }


def _long_bspline_edges(component, transform):
    """Return long B-spline edges in the opened assembly's own coordinates."""
    bodies = component.GetModelDoc2.GetBodies2(0, True)
    if not bodies:
        raise RuntimeError(f"component {component.Name2} has no solid body")
    long_edges = []
    for index, edge in enumerate(bodies[0].GetEdges()):
        start = edge.GetStartVertex
        end = edge.GetEndVertex
        if start is None or end is None:
            continue
        start_assembly = _sw_to_source(start.GetPoint, transform)
        end_assembly = _sw_to_source(end.GetPoint, transform)
        if max(abs(left - right) for left, right in zip(start_assembly, end_assembly)) < 300.0:
            continue
        try:
            spline = _bspline(edge, transform)
        except Exception:
            continue
        long_edges.append({"edge_index": index, "start_assembly_mm": list(start_assembly), "end_assembly_mm": list(end_assembly), "bspline": spline})
    return long_edges


def _open_read_only_assembly(application, assembly: Path):
    """Open an explicit assembly without rebuilding, saving or showing it."""
    import pythoncom
    import win32com.client

    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    document = application.OpenDoc6(
        str(assembly.resolve(strict=True)), SW_DOC_ASSEMBLY, SW_OPEN_SILENT_READ_ONLY, "", errors, warnings
    )
    if document is None:
        raise RuntimeError(f"SolidWorks OpenDoc6 failed (error={errors.value}; warning={warnings.value})")
    if not bool(document.IsOpenedReadOnly):
        raise RuntimeError("Stripe audit requires a read-only SolidWorks document")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assembly", type=Path, help="explicit Ion-Foil assembly opened silently read-only")
    arguments = parser.parse_args()
    frame = load_cad_pose_contract(arguments.frame)

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    application = None
    document = None
    started_application = False
    try:
        if arguments.assembly is not None:
            try:
                application = win32com.client.GetActiveObject("SldWorks.Application.30")
            except pythoncom.com_error:
                application = win32com.client.Dispatch("SldWorks.Application.30")
                application.Visible = False
                started_application = True
            document = _open_read_only_assembly(application, arguments.assembly)
        else:
            application = win32com.client.GetActiveObject("SldWorks.Application.30")
            assemblies = [
                item for item in application.GetDocuments
                if int(item.GetType) == SW_DOC_ASSEMBLY
                and any("ion foil 1" in f"{component.Name2} {component.GetPathName}".lower() for component in item.GetComponents(True))
            ]
            if len(assemblies) != 1:
                raise RuntimeError(f"expected one open Ion Foil assembly, found {len(assemblies)}")
            document = assemblies[0]
        components = document.GetComponents(True)
        assignments = frame["stable_candidate_assignment"]
        wanted = assignments["drift_stripe_set_1"] + assignments["drift_stripe_set_2"]
        records = []
        central_ground = None
        for component in components:
            instance = str(component.Name2).lower()
            matched = next((name for name in wanted if instance.endswith(name)), None)
            ground_match = instance.endswith(assignments["central_ground_candidate"])
            if matched is None and not ground_match:
                continue
            transform = list(component.Transform2.ArrayData)
            record = {"instance_name": matched or assignments["central_ground_candidate"], "source_instance_name": str(component.Name2), "long_bspline_edges": _long_bspline_edges(component, transform)}
            if ground_match:
                central_ground = record
            else:
                records.append(record)
        records.sort(key=lambda record: wanted.index(record["instance_name"]))
        if [record["instance_name"] for record in records] != wanted:
            raise RuntimeError("not all four physical Stripe instances were found")
        if central_ground is None:
            raise RuntimeError("central Ion-Foil-2 candidate was not found")
        payload = {
            "schema_version": 3,
            "coordinate_frame": "opened Ion-Foil assembly, millimetres",
            "target_frame_requires": "top-level rigid transform composition followed by cad_to_theory_frame",
            "target_frame": frame["target_frame"],
            "stripes": records,
            "central_ground": central_ground,
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"SOLIDWORKS_STRIPE_PROFILE_AUDIT: stripes={len(records)} central_ground_edges={len(central_ground['long_bspline_edges'])} output={arguments.output}")
    finally:
        if arguments.assembly is not None and document is not None and application is not None:
            application.CloseDoc(str(document.GetTitle))
        if started_application and application is not None:
            application.ExitApp()
        pythoncom.CoUninitialize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
