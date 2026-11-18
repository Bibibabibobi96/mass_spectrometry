"""Resolve the registered SolidWorks 2022 installation on Windows."""

from __future__ import annotations

import os
from pathlib import Path
import winreg


REGISTRY_KEYS = (
    r"SOFTWARE\SolidWorks\SOLIDWORKS 2022\Setup",
    r"SOFTWARE\WOW6432Node\SolidWorks\SOLIDWORKS 2022\Setup",
)


def resolve_solidworks_2022_root() -> Path:
    """Return a validated SolidWorks 2022 installation directory."""
    configured = os.environ.get("SOLIDWORKS_2022_ROOT")
    candidates: list[Path] = [Path(configured)] if configured else []
    for key_name in REGISTRY_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name) as key:
                value, _ = winreg.QueryValueEx(key, "SolidWorks Folder")
                candidates.append(Path(value))
        except FileNotFoundError:
            continue
    for candidate in candidates:
        root = candidate.resolve()
        if root.is_dir() and (root / "SLDWORKS.exe").is_file():
            return root
    raise FileNotFoundError(
        "SolidWorks 2022 installation was not found; set SOLIDWORKS_2022_ROOT "
        "or repair its registry entry"
    )
