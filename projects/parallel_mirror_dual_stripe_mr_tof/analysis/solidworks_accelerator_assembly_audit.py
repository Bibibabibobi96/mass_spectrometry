#!/usr/bin/env python3
"""Read the working-copy accelerator assembly without modifying CAD.

The output is a mechanical baseline only.  It captures component identities,
native part envelopes and rigid placements so that a subsequent MR-TOF
two-zone focusing redesign can retain the CAD package's external envelope,
apertures and installation reference without inheriting its non-focusing field.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT_READ_ONLY = 3  # swOpenDocOptions_Silent (1) | ReadOnly (2)


def _member(value):
    return value() if callable(value) else value


def _part_box(component):
    model = component.GetModelDoc2
    if model is None or int(_member(model.GetType)) != 1:
        return None
    return [float(value) for value in model.GetPartBox(True)]


def _record_component(component):
    transform = component.Transform2
    return {
        "instance_name": str(_member(component.Name2)),
        "part_path": str(_member(component.GetPathName)),
        "suppressed": bool(_member(component.IsSuppressed)),
        "local_part_box_m": _part_box(component),
        "solidworks_transform_array": (
            [] if transform is None else [float(value) for value in transform.ArrayData]
        ),
    }


def audit(assembly: Path) -> dict:
    """Open ``assembly`` read-only and return its complete placement evidence."""
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
        document = application.OpenDoc6(
            str(assembly), SW_DOC_ASSEMBLY, SW_OPEN_SILENT_READ_ONLY, "", errors, warnings
        )
        if document is None:
            raise RuntimeError(
                f"SolidWorks OpenDoc6 failed (error={errors.value}; warning={warnings.value})"
            )
        if not bool(_member(document.IsOpenedReadOnly)):
            raise RuntimeError("accelerator audit requires a read-only document")
        components = [_record_component(component) for component in document.GetComponents(True)]
        components.sort(key=lambda item: item["instance_name"].lower())
        return {
            "schema_version": 1,
            "source": "SolidWorks 2022 OpenDoc6(silent|read-only) working-copy audit",
            "role": "nonfocusing_accelerator_cad_mechanical_baseline",
            "assembly_path": str(assembly),
            "assembly_title": str(_member(document.GetTitle)),
            "solidworks_revision": str(_member(application.RevisionNumber)),
            "open_errors": int(errors.value),
            "open_warnings": int(warnings.value),
            "assembly_units_raw": [int(value) for value in document.GetUnits],
            "solidworks_transform_layout": (
                "row-major 3x3 rotation at [0:9], translation_m at [9:12], scale at [12]"
            ),
            "components": components,
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
    assembly = arguments.assembly.resolve(strict=True)
    result = audit(assembly)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"SOLIDWORKS_ACCELERATOR_AUDIT: components={len(result['components'])} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
