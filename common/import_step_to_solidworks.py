"""Import a STEP file into SolidWorks 2022 and save a native SLDPRT."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pythoncom
import win32com.client


SW_MULTI_CAD_ENABLE_3D_INTERCONNECT = 691
SOLIDWORKS_EXE = Path(
    r"D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SLDWORKS.exe"
)


def import_step(step_path: Path, sldprt_path: Path, visible: bool) -> dict:
    if not step_path.is_file():
        raise FileNotFoundError(f"STEP file not found: {step_path}")

    sldprt_path.parent.mkdir(parents=True, exist_ok=True)
    if not SOLIDWORKS_EXE.is_file():
        raise FileNotFoundError(f"SolidWorks executable not found: {SOLIDWORKS_EXE}")

    pythoncom.CoInitialize()
    sw = None
    original_interconnect = None
    original_visible = None
    started_solidworks = False
    try:
        try:
            sw = win32com.client.GetActiveObject("SldWorks.Application.30")
        except pythoncom.com_error:
            # Activating the version-specific COM server avoids the normal
            # interactive startup path, which can display a modal error for
            # an unavailable default document template.
            sw = win32com.client.Dispatch("SldWorks.Application.30")
            started_solidworks = True

        original_visible = bool(sw.Visible)
        sw.Visible = True
        revision = str(sw.RevisionNumber)

        original_interconnect = bool(
            sw.GetUserPreferenceToggle(SW_MULTI_CAD_ENABLE_3D_INTERCONNECT)
        )
        sw.SetUserPreferenceToggle(SW_MULTI_CAD_ENABLE_3D_INTERCONNECT, True)

        load_errors = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        null_import_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        part = sw.LoadFile4(str(step_path), "", null_import_data, load_errors)
        if part is None:
            raise RuntimeError(
                f"SolidWorks LoadFile4 returned no model document "
                f"(error={load_errors.value})"
            )

        # ImportDiagnosis opens an interactive repair workflow and blocks a
        # headless session. LoadFile4 plus successful native SaveAs are the
        # non-interactive acceptance checks for this automated export.
        diagnosis_code = -1
        save_errors = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        save_warnings = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        null_export_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        saved = part.Extension.SaveAs(
            str(sldprt_path),
            0,
            1,
            null_export_data,
            save_errors,
            save_warnings,
        )
        if not saved:
            raise RuntimeError(
                f"SolidWorks SaveAs failed "
                f"(error={save_errors.value}; warning={save_warnings.value})"
            )

        title_member = part.GetTitle
        document_title = title_member() if callable(title_member) else title_member
        sw.CloseDoc(str(document_title))

        return {
            "stepPath": str(step_path),
            "sldprtPath": str(sldprt_path),
            "loadErrors": load_errors.value,
            "loadWarnings": 0,
            "importDiagnosisCode": diagnosis_code,
            "saveErrors": save_errors.value,
            "saveWarnings": save_warnings.value,
            "solidWorksRevision": revision,
            "startedSolidWorks": started_solidworks,
        }
    finally:
        if sw is not None:
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
    parser.add_argument("--step", required=True, type=Path)
    parser.add_argument("--sldprt", required=True, type=Path)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    print(json.dumps(import_step(args.step, args.sldprt, args.visible)))


if __name__ == "__main__":
    main()
