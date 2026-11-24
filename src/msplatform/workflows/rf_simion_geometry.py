"""Generate the SIMION GEM sources from the resolved geometry contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from msplatform.io.file_identity import file_sha256
from msplatform.backends.simion.rf_finite_geometry import (
    render_grouped_rod_array_gem,
)
from msplatform.backends.simion.resources import native_resource_path


PROJECT_ROOT = Path(__file__).resolve().parents[1] / "components" / "rf_multipole"
_MODULE_PATH = Path(__file__).resolve()
REPOSITORY_ROOT = _MODULE_PATH.parents[3] if _MODULE_PATH.parents[2].name == "src" else _MODULE_PATH.parents[2]
CONTRACT = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_official.json"
INCLUDE = native_resource_path("quad_include.gem")
MONOLITHIC = native_resource_path("quad_monolithic.gem")


def number(value: float | int) -> str:
    return format(float(value), ".15g")


def render_contract(
    contract: dict,
    digest: str,
    rod_source: str,
    *,
    entrance_electrode: int = 3,
    output_electrode: int = 4,
    detector_electrode: int = 5,
    cell_mm: float = 0.2,
) -> tuple[str, str]:
    """Render the project enclosure around a supplied shared rod-array GEM."""
    g = contract["geometry_mm"]
    enclosure = g["enclosure"]
    entrance = contract["interfaces_mm"]["entrance"]
    exit_interface = contract["interfaces_mm"]["exit"]
    entrance_thickness = entrance["aperture_plate_downstream_face_z_mm"] - entrance["aperture_plate_upstream_face_z_mm"]
    exit_length = (
        enclosure["exit_enclosure_z_max_mm"]
        - enclosure["exit_enclosure_z_min_mm"]
    )
    exit_front_thickness = (
        enclosure["exit_front_wall_end_z_mm"]
        - enclosure["exit_enclosure_z_min_mm"]
    )
    include = f"""; Generated from config/resolved_design_official.json; do not edit.
; resolved_design_sha256={digest}

{rod_source}

locate(0,0,{number(entrance['aperture_plate_upstream_face_z_mm'])}) {{
  e({entrance_electrode}) {{
    fill {{
      within       {{ box3d(-1e6,-1e6,0, 1e6,1e6,{number(entrance_thickness)}) }}
      notin_inside {{ circle(0,0, {number(entrance['aperture_radius_mm'])}) }}
    }}
  }}
}}

locate(0,0,{number(enclosure['exit_enclosure_z_min_mm'])}) {{
  e({output_electrode}) {{
    fill {{
      within       {{ box3d({number(enclosure['outer_half_width_mm'])},{number(enclosure['outer_half_width_mm'])},0, -{number(enclosure['outer_half_width_mm'])},-{number(enclosure['outer_half_width_mm'])},{number(exit_length)}) }}
      notin_inside {{ box3d({number(enclosure['inner_half_width_mm'])},{number(enclosure['inner_half_width_mm'])},{number(exit_front_thickness)}, -{number(enclosure['inner_half_width_mm'])},-{number(enclosure['inner_half_width_mm'])},1E+6) }}
      notin_inside {{ circle(0,0, {number(exit_interface['aperture_radius_mm'])}) }}
    }}
  }}
  e({detector_electrode}) {{
    fill {{ within {{ cylinder(0,0,{number(exit_interface['census_plane_z_mm']-enclosure['exit_enclosure_z_min_mm'])}, {number(enclosure['physical_detector_radius_mm'])},, {number(enclosure['physical_detector_thickness_mm'])}) }} }}
  }}
}}
"""
    monolithic = f"""; Generated from config/resolved_design_official.json; do not edit.
; resolved_design_sha256={digest}

# local mmgu = {number(cell_mm)}

pa_define($({number(enclosure['outer_half_width_mm'])}/mmgu+1), $({number(enclosure['outer_half_width_mm'])}/mmgu+1), $({number(enclosure['vacuum_z_max_mm'])}/mmgu+1), planar,xy, electric,, $(mmgu), surface=fractional)

include(quad_include.gem)
"""
    return include, monolithic


def render(*, cell_mm: float = 0.2, contract_path: Path = CONTRACT) -> dict[Path, str]:
    """Render the installed native resources from an explicit resolved design."""
    contract_path = contract_path.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    digest = file_sha256(contract_path)
    include, monolithic = render_contract(
        contract,
        digest,
        render_grouped_rod_array_gem(contract["geometry_mm"]["rod_array"]),
        cell_mm=cell_mm,
    )
    return {INCLUDE: include, MONOLITHIC: monolithic}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell-mm", type=float, default=0.2)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    args = parser.parse_args()
    stale = []
    if args.cell_mm <= 0:
        raise SystemExit("--cell-mm must be positive")
    for path, expected in render(cell_mm=args.cell_mm, contract_path=args.contract).items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != expected:
            stale.append(path)
            if args.write:
                path.write_text(expected, encoding="utf-8", newline="\n")
                print(f"UPDATED={path.relative_to(REPOSITORY_ROOT).as_posix()}")
    if stale and args.check:
        raise SystemExit("STALE=" + ",".join(path.relative_to(REPOSITORY_ROOT).as_posix() for path in stale))
    print("SIMION_GEOMETRY_SYNC=PASS")


if __name__ == "__main__":
    main()
