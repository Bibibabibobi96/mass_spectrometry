"""Compile the resolved dual-cone geometry to one monolithic SIMION GEM."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from msplatform.backends.simion.rf_geometry import render_grouped_rod_array_gem


def device_to_workbench_offsets(numerics: dict[str, Any]) -> tuple[float, float, float]:
    """Return the governed device-to-workbench translation in x, y, z order."""
    record = numerics["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]
    offsets = tuple(float(record[axis]) for axis in "xyz")
    if not all(math.isfinite(value) for value in offsets):
        raise ValueError("SIMION coordinate offsets must be finite")
    return offsets


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


def _aperture_plate_electrode(plate: dict[str, Any], electrode_id: int) -> str:
    z0 = float(plate["upstream_face_z_mm"])
    thickness = float(plate["thickness_mm"])
    radius = float(plate["outer_radius_mm"])
    aperture = float(plate["aperture_radius_mm"])
    return "\n".join(
        [
            f"  e({electrode_id}) {{ fill {{",
            f"    within {{ cylinder(0,0,{_number(z0)},{_number(radius)},{_number(radius)},{_number(thickness)}) }}",
            f"    notin_inside {{ cylinder(0,0,{_number(z0)},{_number(aperture)},{_number(aperture)},{_number(thickness)}) }}",
            "  } }",
        ]
    )


def geometry_grid(resolved: dict[str, Any], numerics: dict[str, Any]) -> dict[str, Any]:
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
    counts = numerics["pa"]["grid_points_xyz"]
    if not isinstance(counts, dict) or set(counts) != set("xyz") or any(
        type(counts[axis]) is not int or counts[axis] < 3 for axis in "xyz"
    ):
        raise ValueError("PA grid_points_xyz must contain integer counts of at least three")
    offsets = device_to_workbench_offsets(numerics)
    spans = tuple((counts[axis] - 1) * mmgu for axis in "xyz")
    geometry = resolved["geometry_mm"]
    radius = float(geometry["low_pressure_enclosure"]["radius_mm"])
    bounds = []
    for name in ("first_cone", "second_cone"):
        cone = geometry[name]
        bounds.append(((-radius, radius), (-radius, radius),
                       (float(cone["aperture_reference_z_mm"]),
                        float(cone["theoretical_base_z_at_enclosure_radius_mm"]))))
    plate = geometry["downstream_aperture_plate"]
    pr = float(plate["outer_radius_mm"])
    bounds.append(((-pr, pr), (-pr, pr),
                   (float(plate["upstream_face_z_mm"]), float(plate["downstream_face_z_mm"]))))
    for name in ("stage_1_elliptical_quadrupole", "stage_2_round_quadrupole"):
        for rod in geometry[name]["rod_array"]["rods"]:
            if "radius_mm" in rod:
                ex = ey = float(rod["radius_mm"])
            else:
                a, b, angle = (float(rod[key]) for key in
                               ("semi_major_axis_mm", "semi_minor_axis_mm", "major_axis_angle_rad"))
                ex = math.hypot(a * math.cos(angle), b * math.sin(angle))
                ey = math.hypot(a * math.sin(angle), b * math.cos(angle))
            x, y = float(rod["center_x_mm"]), float(rod["center_y_mm"])
            bounds.append(((x-ex, x+ex), (y-ey, y+ey),
                           (float(rod["z_min_mm"]), float(rod["z_max_mm"]))))
    for body in bounds:
        for (lo, hi), offset, span in zip(body, offsets, spans, strict=True):
            if not all(math.isfinite(v) for v in (lo, hi, span)) or lo > hi or lo+offset < 0 or hi+offset > span:
                raise ValueError("declared metal geometry lies outside the explicit PA grid")
    return {"nx": counts["x"], "ny": counts["y"], "nz": counts["z"],
            "dx_mm": mmgu, "dy_mm": mmgu, "dz_mm": mmgu}


def render_gem(resolved: dict[str, Any], numerics: dict[str, Any]) -> str:
    grid = geometry_grid(resolved, numerics)
    mmgu = grid["dx_mm"]
    transverse_span = (grid["nx"] - 1) * mmgu
    transverse_y_span = (grid["ny"] - 1) * mmgu
    axial_span = (grid["nz"] - 1) * mmgu
    geometry = resolved["geometry_mm"]
    radius = float(geometry["low_pressure_enclosure"]["radius_mm"])
    offset_x, offset_y, offset_z = device_to_workbench_offsets(numerics)
    lines = [
        "; Generated from config/resolved_geometry.json; do not edit.",
        "; Device-to-array map is governed by config/simion_solver_numerics.json.",
        "; C0 limitation: stage-1 upstream faces are flat at the minimum resolved z.",
        "; The cone-following cut remains blocked pending a governed project CSG mask.",
        f"# local mmgu = {_number(mmgu)}",
        f"pa_define($({_number(transverse_span)}/mmgu+1),$({_number(transverse_y_span)}/mmgu+1),$({_number(axial_span)}/mmgu+1),"
        "planar,non-mirror,electric,,$(mmgu),surface=fractional)",
        "",
        f"locate({_number(offset_x)},{_number(offset_y)},{_number(offset_z)}) {{",
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
        _aperture_plate_electrode(geometry["downstream_aperture_plate"], 3),
        "}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--numerics", type=Path, required=True)
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


def native_geometry_specification(resolved, numerics, solver):
    """One actual raw-geometry/witness request for fresh and saved stages."""
    from pathlib import Path
    from .dual_cone_stages import ELECTRODE_IDS

    solver = Path(solver)
    raw = solver / "dual_cone_tandem.pa#"
    grid = geometry_grid(resolved, numerics)
    offsets = numerics["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]
    return dict(
        schema_version=1,
        role="simion_frontend_raw_geometry",
        domain_id="dual_cone",
        gem=str(solver / "dual_cone_tandem.gem"),
        output=str(raw),
        grid=grid,
        physical_samples=[
            dict(
                gu=[round(offsets["x"] / grid["dx_mm"]), round(offsets["y"] / grid["dy_mm"]), 1],
                metal=False,
                label="upstream_axis_vacuum",
            )
        ],
        electrode_witness_ids=list(ELECTRODE_IDS),
        fractional_surface=str(raw.with_suffix(".pa-surf")),
        surface_witnesses=str(solver / "dual_cone_surface.csv"),
    )
