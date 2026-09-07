"""Unit-preserving SIMION legacy-GEM primitive serialization.

No device dimensions, voltages, coordinate transforms or mesh choices are made.
Callers provide all finite numeric dimensions in the same length unit (normally
resolved millimetres), including zero thickness for ideal sheet primitives.
"""
from __future__ import annotations

from math import isfinite


def format_number(value: float) -> str:
    """Retain the migrated 12-significant-digit GEM serialization convention."""
    number = float(value)
    if not isfinite(number):
        raise ValueError("GEM primitive coordinates must be finite")
    return format(number, ".12g")


def centered_box3d(
    cx: float, cy: float, cz: float, sx: float, sy: float, sz: float
) -> str:
    """Serialize the supplied center and full spans; zero span denotes a sheet."""
    return (
        f"centered_box3D({format_number(cx)},{format_number(cy)},{format_number(cz)},"
        f"{format_number(sx)},{format_number(sy)},{format_number(sz)})"
    )


def cylinder_z(cx: float, cy: float, cz: float, radius: float, length: float) -> str:
    """Return a z-axis cylinder primitive in millimetres; zero length is allowed."""

    return (
        f"locate({format_number(cx)},{format_number(cy)},{format_number(cz)}) {{ "
        f"cylinder(0,0,0,{format_number(radius)},,{format_number(length)}) }}"
    )
