#!/usr/bin/env python3
"""Extract full top-level CAD poses without changing SolidWorks documents.

SolidWorks owns the composition of transforms for nested components.  This
reader asks its MathPoint implementation to transform the local origin and
three unit axes, rather than manually assuming an ArrayData multiplication
convention.  The resulting vectors are therefore a reusable, explicit CAD
top-level frame evidence record for the mirror and Ion-Foil subassemblies.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT_READ_ONLY = 3


def _member(value):
    return value() if callable(value) else value


def _point(application, transform, values: tuple[float, float, float]) -> list[float]:
    math_utility = application.GetMathUtility
    point = math_utility.CreatePoint(list(values))
    transformed = point.MultiplyTransform(transform)
    return [float(value) for value in transformed.ArrayData]


def _record(application, component) -> dict:
    transform = component.Transform2
    record = {
        "instance_name": str(_member(component.Name2)),
        "part_path": str(_member(component.GetPathName)),
        "suppressed": bool(_member(component.IsSuppressed)),
        "solidworks_transform_array": ([] if transform is None else [float(value) for value in transform.ArrayData]),
    }
    if transform is not None:
        origin = _point(application, transform, (0.0, 0.0, 0.0))
        axes = [_point(application, transform, axis) for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
        record["top_level_origin_m"] = origin
        record["top_level_local_axes"] = [
            [axes[index][coordinate] - origin[coordinate] for coordinate in range(3)]
            for index in range(3)
        ]
    return record


def audit(assembly: Path) -> dict:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    application = None
    document = None
    started_application = False
    try:
        try:
            application = win32com.client.GetActiveObject("SldWorks.Application.30")
        except pythoncom.com_error:
            application = win32com.client.Dispatch("SldWorks.Application.30")
            application.Visible = False
            started_application = True
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        document = application.OpenDoc6(str(assembly), SW_DOC_ASSEMBLY, SW_OPEN_SILENT_READ_ONLY, "", errors, warnings)
        if document is None:
            raise RuntimeError(f"SolidWorks OpenDoc6 failed (error={errors.value}; warning={warnings.value})")
        if not bool(_member(document.IsOpenedReadOnly)):
            raise RuntimeError("top-level pose audit requires a read-only document")
        # Top-level components are sufficient here.  Their transforms define
        # the parent frames used to compose the separately audited local mirror
        # and Ion-Foil component transforms.  Flattening the full, repeated
        # hardware tree is prohibitively slow on this large assembly and is
        # unnecessary for this frame-contract evidence.
        components = document.GetComponents(True)
        selected = [
            _record(application, component)
            for component in components
            if any(
                token in str(_member(component.Name2)).lower()
                for token in ("单套反射电极", "离子箔装配", "电极a", "电极e", "ion foil", "prism", "grounded")
            )
        ]
        selected.sort(key=lambda item: item["instance_name"].lower())
        return {
            "schema_version": 1,
            "source": "SolidWorks 2022 OpenDoc6(silent|read-only), MathPoint transformed nested component evidence",
            "assembly_path": str(assembly),
            "assembly_title": str(_member(document.GetTitle)),
            "solidworks_revision": str(_member(application.RevisionNumber)),
            "open_errors": int(errors.value),
            "open_warnings": int(warnings.value),
            "units_raw": [int(value) for value in document.GetUnits],
            "coordinate_units": "metres",
            "all_component_count": len(components),
            "selected_components": selected,
        }
    finally:
        if document is not None and application is not None:
            application.CloseDoc(str(_member(document.GetTitle)))
        if started_application and application is not None:
            application.ExitApp()
        pythoncom.CoUninitialize()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembly", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = audit(arguments.assembly.resolve(strict=True))
    except Exception as error:
        # A durable diagnostic is preferable to silently treating a failed
        # read-only CAD extraction as missing placement evidence.
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.with_suffix(".error.json").write_text(
            json.dumps({"assembly": str(arguments.assembly), "error": repr(error)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SOLIDWORKS_TOP_LEVEL_POSE_AUDIT: selected={len(result['selected_components'])} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
