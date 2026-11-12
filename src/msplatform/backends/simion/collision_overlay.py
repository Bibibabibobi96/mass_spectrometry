"""SIMION collision-only occupancy headers and overlay carrier coverage."""
from __future__ import annotations

import math
from pathlib import Path
import struct
from typing import Any

from msplatform.backends.simion.standalone_pa_composition import PaHeader

# Installed official examples/matlab/simion_pa_save.m: NOTREFINABLE = 2^28.
COLLISION_NOTREFINABLE_FLAG = 1 << 28


def collision_pa_header(path: Path) -> PaHeader:
    """Read occupancy bounds only, including SIMION's ordinary unit-grid format.

    Installed SIMION 2020 lib/python/SIMION/PA.py load/save defines mode -1
    with 32 header bytes and implicit unit pitch. The affine composer remains
    mode -2 only; this reader cannot authorize field composition or PA families.
    """
    with path.open("rb") as stream:
        raw = stream.read(32)
        pitch_raw = stream.read(24)
    if len(raw) != 32:
        raise ValueError("collision occupancy header is truncated")
    values = struct.unpack("<iidiiii", raw)
    if values[0] == -2 and len(pitch_raw) != 24:
        raise ValueError("collision occupancy pitch header is truncated")
    header = PaHeader(*values, *(struct.unpack("<ddd", pitch_raw) if values[0] == -2 else (1, 1, 1)))
    # The collision-only reader accepts the documented persistent not-refinable
    # flag; affine composition and all source field readers remain unchanged.
    known_flags = ((1 << 21)-1) | COLLISION_NOTREFINABLE_FLAG
    if (path.suffix.lower() != ".pa" or header.mode not in (-1, -2) or header.symmetry != 1
            or header.raw_mirror < 0 or header.raw_mirror & 8 or header.raw_mirror & ~known_flags
            or min(header.nx, header.ny, header.nz) < 1
            or not math.isfinite(header.max_voltage) or header.max_voltage <= 0
            or any(not math.isfinite(v) or v <= 0 for v in (header.dx_mm, header.dy_mm, header.dz_mm))
            or path.stat().st_size != (56 if header.mode == -2 else 32)+header.node_count*8):
        raise ValueError("invalid ordinary collision occupancy header or payload")
    return header


def verify_collision_overlay_support(source: dict[str, Any], plan: dict[str, Any]) -> None:
    """Check real carrier coverage only inside the caller's payload read guards."""
    box = plan["box_mm"]
    carrier_bounds = {}
    def bounds(instance):
        key = (instance["pa_path"], tuple(instance["origin_mm"]))
        if key in carrier_bounds:
            return carrier_bounds[key]
        header = collision_pa_header(Path(instance["pa_path"]))
        if header.symmetry != 1 or header.raw_mirror & 7 not in (0, 1):
            raise ValueError("collision overlay requires planar independent collision instances")
        origin = instance["origin_mm"]
        extent = [(n-1)*d for n, d in zip((header.nx, header.ny, header.nz),
                  (header.dx_mm, header.dy_mm, header.dz_mm), strict=True)]
        carrier_bounds[key] = [origin[0]-extent[0] if header.raw_mirror & 1 else origin[0], *origin[1:],
                               *[origin[a]+extent[a] for a in range(3)]]
        return carrier_bounds[key]
    effective = [-box[3], box[1], box[2], *box[3:]]
    corridor = bounds(source["instances"][1])
    if any(effective[a] < corridor[a] or effective[a+3] > corridor[a+3] for a in range(3)):
        raise ValueError("collision overlay must remain inside the original corridor")
    for instance in source["instances"][2:]:
        other = bounds(instance)
        if all(effective[a] <= other[a+3] and other[a] <= effective[a+3] for a in range(3)):
            raise ValueError("collision overlay cannot mask the IP or detector PA volume")
    for probe in plan["priority_probes"]:
        point = probe["point_mm"]
        if not all(corridor[a] <= point[a] <= corridor[a+3] for a in range(3)):
            raise ValueError("collision overlay probe lies outside the original corridor")
        for instance in source["instances"][2:]:
            other = bounds(instance)
            if all(other[a] <= point[a] <= other[a+3] for a in range(3)):
                raise ValueError("collision overlay exterior probe is masked by another instance")
