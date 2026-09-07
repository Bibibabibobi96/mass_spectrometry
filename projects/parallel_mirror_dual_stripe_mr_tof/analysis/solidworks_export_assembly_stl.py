#!/usr/bin/env python3
"""Export resolved CAD component solids as reusable STL geometry evidence.

The source assembly and its parts are opened only from a working copy in
SolidWorks read-only mode.  Each distinct unsuppressed part is saved to a
separate STL while every assembly instance retains its own rigid transform in
the manifest.  Consumers must apply that transform; an STL alone is local-part
geometry, not a project-frame placement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT_READ_ONLY = 3  # swOpenDocOptions_Silent (1) | ReadOnly (2)
SW_SAVE_AS_SILENT = 1


def _member(value):
    return value() if callable(value) else value


def _safe_stem(path: Path) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    return normalized or "solidworks_part"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(assembly: Path, output_dir: Path) -> dict:
    """Export every unique, resolved part in ``assembly`` and return a manifest."""
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
        if document is None or not bool(_member(document.IsOpenedReadOnly)):
            raise RuntimeError("SolidWorks must open the assembly read-only")
        output_dir.mkdir(parents=True, exist_ok=True)
        part_exports: dict[str, dict] = {}
        instances = []
        for component in document.GetComponents(True):
            part_path = Path(str(_member(component.GetPathName)))
            suppressed = bool(_member(component.IsSuppressed))
            model = component.GetModelDoc2
            transform = component.Transform2
            instance = {
                "instance_name": str(_member(component.Name2)),
                "part_path": str(part_path),
                "suppressed": suppressed,
                "solidworks_transform_array": (
                    [] if transform is None else [float(value) for value in transform.ArrayData]
                ),
                "stl_path": None,
            }
            if suppressed or model is None or not part_path.is_file():
                instances.append(instance)
                continue
            # GetComponents(True) includes nested assemblies as well as leaf
            # parts.  SaveAs(STL) is a part export here: attempting it on a
            # nested SLDASM can fail after valid leaf exports and would make
            # an otherwise usable read-only audit lose its manifest.
            if part_path.suffix.lower() != ".sldprt":
                instance["not_exported_reason"] = "nested_assembly_not_a_leaf_part"
                instances.append(instance)
                continue
            identity = str(part_path.resolve()).lower()
            if identity not in part_exports:
                target = output_dir / f"{_safe_stem(part_path)}__{hashlib.sha256(identity.encode()).hexdigest()[:12]}.stl"
                activate_errors = win32com.client.VARIANT(
                    pythoncom.VT_BYREF | pythoncom.VT_I4, 0
                )
                active_model = application.ActivateDoc3(
                    str(_member(model.GetTitle)), False, 0, activate_errors
                )
                if active_model is None:
                    raise RuntimeError(
                        f"SolidWorks could not activate read-only part {part_path} "
                        f"(error={activate_errors.value})"
                    )
                save_errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                save_warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                null_export_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
                saved = active_model.Extension.SaveAs(
                    str(target), 0, SW_SAVE_AS_SILENT, null_export_data, save_errors, save_warnings
                )
                if not saved or not target.is_file():
                    raise RuntimeError(
                        f"STL export failed for {part_path} "
                        f"(error={save_errors.value}; warning={save_warnings.value})"
                    )
                part_exports[identity] = {
                    "part_path": str(part_path),
                    "stl_path": str(target),
                    "stl_sha256": _sha256(target),
                    "save_errors": int(save_errors.value),
                    "save_warnings": int(save_warnings.value),
                }
            instance["stl_path"] = part_exports[identity]["stl_path"]
            instances.append(instance)
        instances.sort(key=lambda item: item["instance_name"].lower())
        return {
            "schema_version": 1,
            "source": "SolidWorks 2022 read-only working-copy STL export",
            "assembly_path": str(assembly),
            "assembly_title": str(_member(document.GetTitle)),
            "solidworks_revision": str(_member(application.RevisionNumber)),
            "open_errors": int(errors.value),
            "open_warnings": int(warnings.value),
            "stl_coordinate_frame": "part-local metres; apply per-instance solidworks_transform_array",
            "parts": sorted(part_exports.values(), key=lambda item: item["part_path"].lower()),
            "instances": instances,
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
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    result = export(arguments.assembly.resolve(strict=True), arguments.output_dir)
    arguments.manifest.parent.mkdir(parents=True, exist_ok=True)
    arguments.manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"SOLIDWORKS_STL_EXPORT: parts={len(result['parts'])} "
        f"instances={len(result['instances'])} manifest={arguments.manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
