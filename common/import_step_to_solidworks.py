"""Import COMSOL STEP solids into native SolidWorks parts and assemblies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pythoncom
import win32com.client


SW_MULTI_CAD_ENABLE_3D_INTERCONNECT = 691
SW_DOC_ASSEMBLY = 2
SW_ADD_COMPONENT_CURRENT_CONFIGURATION = 0
SOLIDWORKS_EXE = Path(
    r"D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SLDWORKS.exe"
)
ASSEMBLY_TEMPLATE = Path(
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2022\templates\gb_assembly.asmdot"
)


def save_native_document(document, destination: Path) -> tuple[int, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    save_errors = win32com.client.VARIANT(
        pythoncom.VT_BYREF | pythoncom.VT_I4, 0
    )
    save_warnings = win32com.client.VARIANT(
        pythoncom.VT_BYREF | pythoncom.VT_I4, 0
    )
    null_export_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    saved = document.Extension.SaveAs(
        str(destination), 0, 1, null_export_data, save_errors, save_warnings
    )
    if not saved:
        raise RuntimeError(
            f"SolidWorks SaveAs failed for {destination} "
            f"(error={save_errors.value}; warning={save_warnings.value})"
        )
    return save_errors.value, save_warnings.value


def document_title(document) -> str:
    member = document.GetTitle
    return str(member() if callable(member) else member)


def import_steps(
    step_paths: list[Path], sldprt_paths: list[Path], assembly_path: Path | None,
    visible: bool,
) -> dict:
    if len(step_paths) != len(sldprt_paths):
        raise ValueError("--step and --sldprt must be supplied in matching counts")
    if not step_paths:
        raise ValueError("At least one STEP file is required")
    for step_path in step_paths:
        if not step_path.is_file():
            raise FileNotFoundError(f"STEP file not found: {step_path}")
    if not SOLIDWORKS_EXE.is_file():
        raise FileNotFoundError(f"SolidWorks executable not found: {SOLIDWORKS_EXE}")
    if assembly_path is not None and not ASSEMBLY_TEMPLATE.is_file():
        raise FileNotFoundError(
            f"SolidWorks assembly template not found: {ASSEMBLY_TEMPLATE}"
        )

    pythoncom.CoInitialize()
    sw = None
    original_interconnect = None
    original_visible = None
    started_solidworks = False
    opened_parts = []
    assembly = None
    try:
        try:
            sw = win32com.client.GetActiveObject("SldWorks.Application.30")
        except pythoncom.com_error:
            # COM activation avoids the ordinary interactive startup path.
            # A missing default template can nevertheless still display a
            # user-facing modal dialog; the project document records that
            # residual interaction and the required user response.
            sw = win32com.client.Dispatch("SldWorks.Application.30")
            started_solidworks = True

        original_visible = bool(sw.Visible)
        sw.Visible = True
        revision = str(sw.RevisionNumber)
        original_interconnect = bool(
            sw.GetUserPreferenceToggle(SW_MULTI_CAD_ENABLE_3D_INTERCONNECT)
        )
        sw.SetUserPreferenceToggle(SW_MULTI_CAD_ENABLE_3D_INTERCONNECT, True)

        part_results = []
        diagnosis_code = -1
        for step_path, sldprt_path in zip(step_paths, sldprt_paths, strict=True):
            load_errors = win32com.client.VARIANT(
                pythoncom.VT_BYREF | pythoncom.VT_I4, 0
            )
            null_import_data = win32com.client.VARIANT(
                pythoncom.VT_DISPATCH, None
            )
            part = sw.LoadFile4(
                str(step_path), "", null_import_data, load_errors
            )
            if part is None:
                raise RuntimeError(
                    f"SolidWorks LoadFile4 returned no model document for "
                    f"{step_path} (error={load_errors.value})"
                )
            opened_parts.append(part)
            save_errors, save_warnings = save_native_document(part, sldprt_path)
            part_results.append({
                "stepPath": str(step_path),
                "sldprtPath": str(sldprt_path),
                "loadErrors": load_errors.value,
                "loadWarnings": 0,
                "importDiagnosisCode": diagnosis_code,
                "saveErrors": save_errors,
                "saveWarnings": save_warnings,
            })

        assembly_result = None
        if assembly_path is not None:
            assembly = sw.NewDocument(
                str(ASSEMBLY_TEMPLATE), SW_DOC_ASSEMBLY, 0.0, 0.0
            )
            if assembly is None:
                raise RuntimeError("SolidWorks could not create the assembly document")
            for sldprt_path in sldprt_paths:
                component = assembly.AddComponent5(
                    str(sldprt_path),
                    SW_ADD_COMPONENT_CURRENT_CONFIGURATION,
                    "",
                    False,
                    "",
                    0.0,
                    0.0,
                    0.0,
                )
                if component is None:
                    raise RuntimeError(
                        f"SolidWorks could not add component {sldprt_path}"
                    )
            save_errors, save_warnings = save_native_document(assembly, assembly_path)
            assembly_result = {
                "sldasmPath": str(assembly_path),
                "componentCount": len(sldprt_paths),
                "saveErrors": save_errors,
                "saveWarnings": save_warnings,
            }

        result = {
            "parts": part_results,
            "partCount": len(part_results),
            "assembly": assembly_result,
            "solidWorksRevision": revision,
            "startedSolidWorks": started_solidworks,
        }
        if len(part_results) == 1 and assembly_result is None:
            result.update(part_results[0])
        return result
    finally:
        if sw is not None:
            if assembly is not None:
                sw.CloseDoc(document_title(assembly))
            for part in opened_parts:
                sw.CloseDoc(document_title(part))
            if original_interconnect is not None:
                sw.SetUserPreferenceToggle(
                    SW_MULTI_CAD_ENABLE_3D_INTERCONNECT, original_interconnect
                )
            if started_solidworks:
                sw.ExitApp()
            elif original_visible is not None:
                sw.Visible = visible if visible else original_visible
        pythoncom.CoUninitialize()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True, type=Path, action="append")
    parser.add_argument("--sldprt", required=True, type=Path, action="append")
    parser.add_argument("--assembly", type=Path)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    print(json.dumps(import_steps(args.step, args.sldprt, args.assembly, args.visible)))


if __name__ == "__main__":
    main()
