#!/usr/bin/env python3
"""Record read-only SolidWorks leaf-part face topology for CAD aperture audits.

The JSON is intentionally local-part evidence.  A consumer must apply the
separately audited assembly transform before treating any value as a project
coordinate.  This tool neither rebuilds nor saves CAD documents.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SW_DOC_PART = 1
SW_OPEN_SILENT_READ_ONLY = 3


def _member(value: Any) -> Any:
    return value() if callable(value) else value


def _face_record(index: int, face: Any) -> dict[str, object]:
    edges = [] if _member(face.GetEdges) is None else list(_member(face.GetEdges))
    result: dict[str, object] = {
        "face_index": index,
        "face_box_m": [float(value) for value in _member(face.GetBox)],
        "edge_count": len(edges),
    }
    # This installed COM typelib exposes Face2's edge loop and bounding box,
    # but does not expose the optional GetSurface member through late binding.
    # Do not turn an aperture audit into a failed export for metadata that is
    # neither needed nor reliably portable between the installed SW builds.
    return result


def audit_part(application: Any, part_path: Path) -> dict[str, object]:
    import pythoncom
    import win32com.client

    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    document = application.OpenDoc6(
        str(part_path), SW_DOC_PART, SW_OPEN_SILENT_READ_ONLY, "", errors, warnings
    )
    if document is None or not bool(_member(document.IsOpenedReadOnly)):
        raise RuntimeError(f"SolidWorks must open {part_path} read-only")
    try:
        bodies = list(_member(document.GetBodies2(0, False)) or [])
        return {
            "part_path": str(part_path),
            "title": str(_member(document.GetTitle)),
            "part_box_m": [float(value) for value in _member(document.GetPartBox(True))],
            "open_errors": int(errors.value),
            "open_warnings": int(warnings.value),
            "bodies": [
                {
                    "body_index": index,
                    "face_count": len(list(_member(body.GetFaces) or [])),
                    "faces": [
                        _face_record(face_index, face)
                        for face_index, face in enumerate(list(_member(body.GetFaces) or []))
                    ],
                }
                for index, body in enumerate(bodies)
            ],
        }
    finally:
        application.CloseDoc(str(_member(document.GetTitle)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    application = None
    started_application = False
    try:
        try:
            application = win32com.client.GetActiveObject("SldWorks.Application.30")
        except pythoncom.com_error:
            application = win32com.client.Dispatch("SldWorks.Application.30")
            application.Visible = False
            started_application = True
        payload = {
            "schema_version": 1,
            "source": "SolidWorks 2022 read-only leaf-part face topology audit",
            "solidworks_revision": str(_member(application.RevisionNumber)),
            "parts": [audit_part(application, path.resolve(strict=True)) for path in arguments.part],
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"SOLIDWORKS_PART_FACE_TOPOLOGY_AUDIT: parts={len(payload['parts'])} output={arguments.output}")
        return 0
    finally:
        if started_application and application is not None:
            application.ExitApp()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
