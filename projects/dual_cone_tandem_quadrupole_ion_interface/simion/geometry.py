"""Compile the resolved dual-cone geometry to one monolithic SIMION GEM."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.simion_geometry import render_grouped_rod_array_gem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESOLVED = PROJECT_ROOT / "config" / "resolved_geometry.json"
DEFAULT_NUMERICS = PROJECT_ROOT / "config" / "simion_solver_numerics.json"


def _number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("GEM values must be finite")
    return format(number, ".15g")


def _load(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("role") != role:
        raise ValueError(f"unexpected contract role: {path}")
    return value


def _cone_electrode(cone: dict[str, Any], electrode_id: int, radius: float) -> str:
    z0 = float(cone["aperture_reference_z_mm"])
    angle = math.radians(float(cone["half_angle_deg"]))
    slope = math.tan(angle)
    inner0 = float(cone["aperture_radius_mm"])
    thickness = float(cone["wall_normal_thickness_mm"])
    outer0 = inner0 + thickness / math.cos(angle)
    inner_z1 = z0 + (radius - inner0) / slope
    outer_z1 = z0 + (radius - outer0) / slope
    return (
        f"  e({electrode_id}) {{ rotate_y(-90) {{ revolve_xy() {{ polyline("
        f"{_number(z0)},{_number(outer0)},{_number(outer_z1)},{_number(radius)},"
        f"{_number(inner_z1)},{_number(radius)},{_number(z0)},{_number(inner0)}) }} }} }}"
    )


def render_gem(resolved: dict[str, Any], numerics: dict[str, Any]) -> str:
    if resolved.get("role") != "dual_cone_tandem_quadrupole_resolved_geometry":
        raise ValueError("resolved geometry role differs")
    if numerics.get("role") != "dual_cone_simion_solver_numerics":
        raise ValueError("SIMION numerics role differs")
    cell = numerics["pa"]["cell_mm_xyz"]
    if len({float(cell[axis]) for axis in "xyz"}) != 1:
        raise ValueError("the first GEM compiler requires isotropic SIMION cells")
    mmgu = float(cell["x"])
    if not math.isfinite(mmgu) or mmgu <= 0:
        raise ValueError("SIMION cell size must be positive and finite")
    geometry = resolved["geometry_mm"]
    radius = float(geometry["low_pressure_enclosure"]["radius_mm"])
    transverse_span = 2.0 * (radius + 2.0)
    z_min = -2.0
    center = 0.5 * transverse_span
    offset = -z_min
    lines = [
        "; Generated from config/resolved_geometry.json; do not edit.",
        "; Device-to-array map: (x,y,z) -> (x+25.5,y+25.5,z+2.0) mm.",
        "; C0 limitation: stage-1 upstream faces are flat at the minimum resolved z.",
        "; The cone-following cut remains blocked pending a governed project CSG mask.",
        f"# local mmgu = {_number(mmgu)}",
        "pa_define($(51/mmgu+1),$(51/mmgu+1),$(112/mmgu+1),planar,non-mirror,"
        "electric,,$(mmgu),surface=fractional)",
        "",
        f"locate({_number(center)},{_number(center)},{_number(offset)}) {{",
        _cone_electrode(geometry["first_cone"], 1, radius),
        _cone_electrode(geometry["second_cone"], 2, radius),
        render_grouped_rod_array_gem(
            geometry["stage_1_elliptical_quadrupole"]["rod_array"],
            electrode_group_ids={1: 11, 2: 12},
        ).rstrip(),
        render_grouped_rod_array_gem(
            geometry["stage_2_round_quadrupole"]["rod_array"],
            electrode_group_ids={1: 21, 2: 22},
        ).rstrip(),
        "}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", type=Path, default=DEFAULT_RESOLVED)
    parser.add_argument("--numerics", type=Path, default=DEFAULT_NUMERICS)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    resolved = _load(args.resolved, "dual_cone_tandem_quadrupole_resolved_geometry")
    numerics = _load(args.numerics, "dual_cone_simion_solver_numerics")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_gem(resolved, numerics), encoding="utf-8")
    print(f"DUAL_CONE_SIMION_GEM=PASS PATH={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
