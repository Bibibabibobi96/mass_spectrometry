"""Generate the SIMION GEM sources from the resolved geometry contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = PROJECT_ROOT / "config" / "resolved_geometry.json"
INCLUDE = PROJECT_ROOT / "simion" / "geometry" / "quad_include.gem"
MONOLITHIC = PROJECT_ROOT / "simion" / "geometry" / "quad_monolithic.gem"


def number(value: float | int) -> str:
    return format(float(value), ".15g")


def render() -> dict[Path, str]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    g = contract["geometry_mm"]
    digest = hashlib.sha256(CONTRACT.read_bytes()).hexdigest().upper()
    entrance_thickness = g["entrance_plate_z_max"] - g["entrance_plate_z_min"]
    exit_length = g["exit_enclosure_z_max"] - g["exit_enclosure_z_min"]
    exit_front_thickness = g["exit_enclosure_front_wall_end_z"] - g["exit_enclosure_z_min"]
    include = f"""; Generated from config/resolved_geometry.json; do not edit.
; resolved_geometry_sha256={digest}

# local r0 = {number(g['field_radius_r0'])}
# local rrod = {number(g['rod_radius'])}

locate(0,0,{number(g['rod_z_max'])}) {{
  e(1) {{
    fill {{ within {{ cylinder($(r0+rrod),0,0, $(rrod),, {number(g['rod_length'])}) }} }}
    fill {{ within {{ cylinder($(-r0-rrod),0,0, $(rrod),, {number(g['rod_length'])}) }} }}
  }}
  e(2) {{
    fill {{ within {{ cylinder(0,$(r0+rrod),0, $(rrod),, {number(g['rod_length'])}) }} }}
    fill {{ within {{ cylinder(0,$(-r0-rrod),0, $(rrod),, {number(g['rod_length'])}) }} }}
  }}
}}

locate(0,0,{number(g['entrance_plate_z_min'])}) {{
  e(3) {{
    fill {{
      within       {{ box3d(-1e6,-1e6,0, 1e6,1e6,{number(entrance_thickness)}) }}
      notin_inside {{ circle(0,0, {number(g['entrance_aperture_radius'])}) }}
    }}
  }}
}}

locate(0,0,{number(g['exit_enclosure_z_min'])}) {{
  e(4) {{
    fill {{
      within       {{ box3d({number(g['exit_enclosure_outer_half_width'])},{number(g['exit_enclosure_outer_half_width'])},0, -{number(g['exit_enclosure_outer_half_width'])},-{number(g['exit_enclosure_outer_half_width'])},{number(exit_length)}) }}
      notin_inside {{ box3d({number(g['exit_enclosure_inner_half_width'])},{number(g['exit_enclosure_inner_half_width'])},{number(exit_front_thickness)}, -{number(g['exit_enclosure_inner_half_width'])},-{number(g['exit_enclosure_inner_half_width'])},1E+6) }}
      notin_inside {{ circle(0,0, {number(g['exit_aperture_radius'])}) }}
    }}
  }}
  e(5) {{
    fill {{ within {{ cylinder(0,0,{number(exit_length)}, {number(g['detector_radius'])},, {number(g['detector_thickness'])}) }} }}
  }}
}}
"""
    monolithic = f"""; Generated from config/resolved_geometry.json; do not edit.
; resolved_geometry_sha256={digest}

# local mmgu = {number(g['simion_cell_mm'])}

pa_define($({number(g['exit_enclosure_outer_half_width'])}/mmgu+1), $({number(g['exit_enclosure_outer_half_width'])}/mmgu+1), $({number(g['model_z_span'])}/mmgu+1), planar,xy, electric,, $(mmgu), surface=fractional)

include(quad_include.gem)
"""
    return {INCLUDE: include, MONOLITHIC: monolithic}


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, expected in render().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != expected:
            stale.append(path)
            if args.write:
                path.write_text(expected, encoding="utf-8", newline="\n")
                print(f"UPDATED={path.relative_to(PROJECT_ROOT).as_posix()}")
    if stale and args.check:
        raise SystemExit("STALE=" + ",".join(path.relative_to(PROJECT_ROOT).as_posix() for path in stale))
    print("SIMION_GEOMETRY_SYNC=PASS")


if __name__ == "__main__":
    main()
