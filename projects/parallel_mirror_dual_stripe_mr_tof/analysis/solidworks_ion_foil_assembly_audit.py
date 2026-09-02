#!/usr/bin/env python3
"""Read global CAD poses for an already-open Ion Foil SolidWorks assembly.

The script is deliberately non-mutating: it attaches to the current GUI and
only reads loaded component metadata and rigid transforms.  It does not open,
save, rebuild, or close a SolidWorks document.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


INTERESTING_NAMES = ("ion foil", "prism", "grounded")


def _model_box(component):
    model = component.GetModelDoc2
    if model is None or int(model.GetType) != 1:  # swDocPART
        return None
    return [float(value) for value in model.GetPartBox(True)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    import win32com.client  # SolidWorks is only required while this script runs.

    application = win32com.client.GetActiveObject("SldWorks.Application.30")
    assemblies = []
    for document in application.GetDocuments:
        if int(document.GetType) != 2:
            continue
        components = document.GetComponents(True)
        if any("ion foil" in f"{component.Name2} {component.GetPathName}".lower() for component in components):
            assemblies.append(document)
    if len(assemblies) != 1:
        raise RuntimeError(f"expected exactly one open Ion Foil assembly; found {len(assemblies)}")
    assembly = assemblies[0]
    components = []
    for component in assembly.GetComponents(True):
        name = str(component.Name2)
        path = str(component.GetPathName)
        if not any(token in f"{name} {path}".lower() for token in INTERESTING_NAMES):
            continue
        transform = component.Transform2
        components.append(
            {
                "instance_name": name,
                "part_path": path,
                "suppressed": bool(component.IsSuppressed),
                "local_part_box_m": _model_box(component),
                "solidworks_transform_array": [] if transform is None else [float(value) for value in transform.ArrayData],
            }
        )
    components.sort(key=lambda item: item["instance_name"].lower())
    payload = {
        "source": "running SolidWorks GUI; read-only extraction from a user-visible assembly",
        "assembly_title": str(assembly.GetTitle),
        "assembly_path": str(assembly.GetPathName),
        "assembly_units_raw": list(assembly.GetUnits),
        "solidworks_transform_layout": "row-major 3x3 rotation at [0:9], translation_m at [9:12], scale at [12]",
        "components": components,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SOLIDWORKS_ION_FOIL_ASSEMBLY_AUDIT: components={len(components)} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
