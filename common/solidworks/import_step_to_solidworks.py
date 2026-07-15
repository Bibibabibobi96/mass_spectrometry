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


def create_transform(math_utility, array_data: list[float]):
    """Create an IMathTransform through SolidWorks' indexed property API."""
    transform_data = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, array_data
    )
    dispid = math_utility._oleobj_.GetIDsOfNames("CreateTransform")
    transform_dispatch = math_utility._oleobj_.Invoke(
        dispid, 0, pythoncom.DISPATCH_PROPERTYGET, True, transform_data
    )
    return win32com.client.Dispatch(transform_dispatch)


def part_box_center_m(document) -> tuple[float, float, float]:
    box = document.GetPartBox(True)
    return tuple((box[axis] + box[axis + 3]) / 2.0 for axis in range(3))


def import_steps(
    step_paths: list[Path], sldprt_paths: list[Path], assembly_path: Path | None,
    translations_mm: list[tuple[float, float, float]], visible: bool,
) -> dict:
    if len(step_paths) != len(sldprt_paths):
        raise ValueError("--step and --sldprt must be supplied in matching counts")
    if not step_paths:
        raise ValueError("At least one STEP file is required")
    if len(translations_mm) != len(step_paths):
        raise ValueError("One --translation is required for every STEP file")
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
        for step_path, sldprt_path, translation_mm in zip(
            step_paths, sldprt_paths, translations_mm, strict=True
        ):
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
            local_center_m = part_box_center_m(part)
            part_results.append({
                "stepPath": str(step_path),
                "sldprtPath": str(sldprt_path),
                "loadErrors": load_errors.value,
                "loadWarnings": 0,
                "importDiagnosisCode": diagnosis_code,
                "saveErrors": save_errors,
                "saveWarnings": save_warnings,
                "translationMm": translation_mm,
                "localCenterM": local_center_m,
            })

        assembly_result = None
        if assembly_path is not None:
            assembly = sw.NewDocument(
                str(ASSEMBLY_TEMPLATE), SW_DOC_ASSEMBLY, 0.0, 0.0
            )
            if assembly is None:
                raise RuntimeError("SolidWorks could not create the assembly document")
            # pywin32 exposes ISldWorks::GetMathUtility as a dispatch
            # property in this SolidWorks 2022 installation, not a callable.
            math_utility = sw.GetMathUtility
            component_translations_m = []
            component_world_centers_m = []
            for sldprt_path, target_center_mm, part_result in zip(
                sldprt_paths, translations_mm, part_results, strict=True
            ):
                target_center_m = tuple(value / 1000.0 for value in target_center_mm)
                local_center_m = tuple(part_result["localCenterM"])
                translation_m = tuple(
                    target - local
                    for target, local in zip(target_center_m, local_center_m, strict=True)
                )
                component = assembly.AddComponent5(
                    str(sldprt_path),
                    SW_ADD_COMPONENT_CURRENT_CONFIGURATION,
                    "",
                    False,
                    "",
                    *translation_m,
                )
                if component is None:
                    raise RuntimeError(
                        f"SolidWorks could not add component {sldprt_path}"
                    )
                if component.IsFixed:
                    assembly.ClearSelection2(True)
                    null_selection_data = win32com.client.VARIANT(
                        pythoncom.VT_DISPATCH, None
                    )
                    component.Select4(False, null_selection_data, False)
                    assembly.UnfixComponent()
                transform = create_transform(math_utility, [
                    1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0,
                    *translation_m,
                    1.0,
                    0.0, 0.0, 0.0,
                ])
                component.Transform2 = transform
                transform_data = component.Transform2.ArrayData
                actual_translation_m = tuple(transform_data[9:12])
                component_translations_m.append(actual_translation_m)
                component_world_centers_m.append(tuple(
                    local + translation
                    for local, translation in zip(
                        local_center_m, actual_translation_m, strict=True
                    )
                ))
            # The dynamic pywin32 wrapper invokes this COM member on access
            # and returns its Boolean result.
            _ = assembly.EditRebuild3
            save_errors, save_warnings = save_native_document(assembly, assembly_path)
            assembly_result = {
                "sldasmPath": str(assembly_path),
                "componentCount": len(sldprt_paths),
                "componentTranslationsM": component_translations_m,
                "componentWorldCentersM": component_world_centers_m,
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
    parser.add_argument("--manifest", type=Path,
                        help="JSON manifest used for large parameterized assemblies")
    parser.add_argument("--step", type=Path, action="append")
    parser.add_argument("--sldprt", type=Path, action="append")
    parser.add_argument("--translation", action="append")
    parser.add_argument("--assembly", type=Path)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    if args.manifest is not None:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        step_paths = [Path(value) for value in payload["stepPaths"]]
        sldprt_paths = [Path(value) for value in payload["sldprtPaths"]]
        translations_mm = [tuple(float(value) for value in row)
                           for row in payload["translationsMm"]]
        assembly_value = payload.get("assemblyPath", "")
        assembly_path = Path(assembly_value) if assembly_value else None
    else:
        if not (args.step and args.sldprt and args.translation):
            parser.error("--manifest or matching --step/--sldprt/--translation options are required")
        translations_mm = []
        for translation in args.translation:
            values = tuple(float(value) for value in translation.split(","))
            if len(values) != 3:
                raise ValueError("--translation must be comma-separated x,y,z in mm")
            translations_mm.append(values)
        step_paths = args.step
        sldprt_paths = args.sldprt
        assembly_path = args.assembly
    print(json.dumps(import_steps(
        step_paths, sldprt_paths, assembly_path, translations_mm, args.visible
    )))


if __name__ == "__main__":
    main()
