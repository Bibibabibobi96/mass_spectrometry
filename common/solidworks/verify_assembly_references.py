"""Verify that a SolidWorks assembly opens with all component files resolved."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client


def verify(assembly: Path, expected_count: int) -> dict[str, object]:
    pythoncom.CoInitialize()
    solidworks = None
    document = None
    try:
        solidworks = win32com.client.Dispatch("SldWorks.Application.30")
        solidworks.Visible = False
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        document = solidworks.OpenDoc6(
            str(assembly), 2, 1, "", errors, warnings
        )
        if document is None:
            raise RuntimeError(
                f"SolidWorks OpenDoc6 failed (error={errors.value}; "
                f"warning={warnings.value})"
            )

        components = []
        for component in document.GetComponents(True):
            path = Path(str(component.GetPathName))
            components.append(
                {
                    "name": str(component.Name2),
                    "path": str(path),
                    "pathExists": path.is_file(),
                }
            )
        missing = [item for item in components if not item["pathExists"]]
        passed = (
            errors.value == 0
            and len(components) == expected_count
            and not missing
        )
        return {
            "schema_version": 1,
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "PASS" if passed else "FAIL",
            "assembly_path": str(assembly),
            "solidworks_revision": str(solidworks.RevisionNumber),
            "open_errors": errors.value,
            "open_warnings": warnings.value,
            "expected_component_count": expected_count,
            "component_count": len(components),
            "missing_reference_count": len(missing),
            "components": components,
        }
    finally:
        if solidworks is not None:
            if document is not None:
                solidworks.CloseAllDocuments(True)
            solidworks.ExitApp()
        pythoncom.CoUninitialize()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-component-count", type=int, default=25)
    args = parser.parse_args()

    assembly = args.assembly.resolve(strict=True)
    if args.expected_component_count < 1:
        parser.error("--expected-component-count must be positive")
    result = verify(assembly, args.expected_component_count)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "PASS":
        raise RuntimeError(
            "Assembly reference gate failed: "
            f"components={result['component_count']}/"
            f"{result['expected_component_count']}, "
            f"missing={result['missing_reference_count']}, "
            f"open_errors={result['open_errors']}. See {args.report.resolve()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
