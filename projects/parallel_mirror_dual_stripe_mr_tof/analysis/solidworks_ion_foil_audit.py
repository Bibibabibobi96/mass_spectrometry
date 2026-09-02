#!/usr/bin/env python3
"""Read open Ion Foil parts from SolidWorks without modifying the CAD files.

This is deliberately a GUI-attached audit: it never opens, saves, rebuilds, or
closes a SolidWorks document.  It records local sketch curves and part bounds;
assembly-frame placement remains a separate, explicit extraction.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def _unpack_pair(value: float) -> tuple[int, int]:
    return struct.unpack("ii", struct.pack("d", float(value)))


def _point(point):
    return None if point is None else [float(point.X), float(point.Y), float(point.Z)]


def _segment(segment):
    kind = int(segment.GetType)
    result = {"type": kind}
    if kind == 0:  # swSketchLINE
        result["start_m"] = _point(segment.GetStartPoint2)
        result["end_m"] = _point(segment.GetEndPoint2)
    elif kind == 3:  # swSketchBSpline
        values = list(segment.GetCurve.GetBCurveParams3(True, False, True))
        # GetBCurveParams3 packs paired integer fields in its first two doubles:
        # (dimension, order), then (control_count, periodicity).
        dimension, order = _unpack_pair(values[0])
        control_count, periodic = _unpack_pair(values[1])
        knot_end = 2 + control_count + order
        control_values = values[knot_end : knot_end + control_count * dimension]
        result.update(
            curve="bspline",
            dimension=dimension,
            order=order,
            control_count=control_count,
            periodic=bool(periodic),
            knots=[float(value) for value in values[2:knot_end]],
            control_points_m=[
                [float(control_values[index * dimension + axis]) for axis in range(dimension)]
                for index in range(control_count)
            ],
        )
    else:
        result["start_m"] = _point(segment.GetStartPoint2)
        result["end_m"] = _point(segment.GetEndPoint2)
    return result


def _document(document):
    result = {
        "title": str(document.GetTitle),
        "path": str(document.GetPathName),
        "type": int(document.GetType),
        "units_raw": list(document.GetUnits),
        "is_open_read_only": bool(document.IsOpenedReadOnly),
        "part_box_m": [float(value) for value in document.GetPartBox(True)],
        "sketches": [],
    }
    feature = document.FirstFeature
    while feature is not None:
        if str(feature.GetTypeName2) == "ProfileFeature":
            sketch = feature.GetSpecificFeature2
            segments = [] if sketch is None else [_segment(item) for item in (sketch.GetSketchSegments or [])]
            result["sketches"].append({"name": str(feature.Name), "segments": segments})
        feature = feature.GetNextFeature
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    import win32com.client  # SolidWorks is intentionally required only at run time.

    application = win32com.client.GetActiveObject("SldWorks.Application.30")
    documents = []
    for document in application.GetDocuments:
        filename = Path(str(document.GetPathName)).name.lower()
        if any(f"ion foil {number}" in filename for number in (1, 2, 3, 4)):
            documents.append(_document(document))
    documents.sort(key=lambda item: item["path"].lower())
    payload = {
        "source": "running SolidWorks GUI; read-only extraction of user-opened documents",
        "documents": documents,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SOLIDWORKS_ION_FOIL_AUDIT: documents={len(documents)} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
