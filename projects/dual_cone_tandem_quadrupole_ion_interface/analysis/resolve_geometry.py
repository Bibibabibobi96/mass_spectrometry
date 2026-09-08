"""Validate the author geometry and derive one solver-neutral resolved geometry."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.round_rod_geometry import build_rod_array


PROJECT_ID = "dual_cone_tandem_quadrupole_ion_interface"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "baseline.json"
DEFAULT_RESOLVED = PROJECT_ROOT / "config" / "resolved_geometry.json"


def _positive(label: str, value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return number


def load_baseline(path: Path = DEFAULT_BASELINE) -> dict[str, Any]:
    """Load and minimally validate the version-1 author geometry."""
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("schema_version") != 1 or document.get("role") != (
        "dual_cone_tandem_quadrupole_geometry_baseline"
    ):
        raise ValueError("geometry baseline schema or role differs")
    if document.get("project_id") != PROJECT_ID:
        raise ValueError("geometry baseline project identity differs")
    return document


def resolve_geometry(baseline: dict[str, Any]) -> dict[str, Any]:
    """Derive all axial coordinates, semiaxes, centre radii, and clear radii."""
    geometry = baseline["geometry_mm"]
    first = geometry["first_cone"]
    second = geometry["second_cone"]
    enclosure = geometry["low_pressure_enclosure"]
    ellipse = geometry["elliptical_quadrupole"]
    round_rods = geometry["round_quadrupole"]

    first_angle = _positive("first cone included angle", first["included_angle_deg"])
    second_angle = _positive("second cone included angle", second["included_angle_deg"])
    if first_angle >= 180 or second_angle >= 180:
        raise ValueError("cone included angles must be below 180 degrees")
    first_aperture_z = float(first["aperture_reference_z_mm"])
    second_aperture_z = first_aperture_z + _positive(
        "cone virtual apex separation", second["virtual_apex_separation_mm"]
    )
    low_pressure_end_z = second_aperture_z + _positive(
        "low-pressure axial length", enclosure["axial_length_from_second_aperture_mm"]
    )

    major_semi_axis = 0.5 * _positive("ellipse major diameter", ellipse["major_axis_diameter_mm"])
    minor_semi_axis = 0.5 * _positive("ellipse minor diameter", ellipse["minor_axis_diameter_mm"])
    if major_semi_axis <= minor_semi_axis:
        raise ValueError("ellipse major axis must exceed its minor axis")
    stage_1_r0 = 0.5 * _positive("opposed ellipse gap", ellipse["opposed_inner_surface_gap_mm"])

    round_radius = _positive("round rod radius", round_rods["rod_radius_mm"])
    adjacent_distance = _positive(
        "adjacent round rod center distance", round_rods["adjacent_rod_center_distance_mm"]
    )
    stage_2_center_radius = adjacent_distance / math.sqrt(2.0)
    stage_2_r0 = stage_2_center_radius - round_radius
    if stage_2_r0 <= 0:
        raise ValueError("round rods overlap the central axis")
    stage_2_end_z = low_pressure_end_z
    stage_2_start_z = stage_2_end_z - _positive(
        "round quadrupole effective length", round_rods["effective_length_mm"]
    )
    stage_1_end_z = stage_2_start_z - _positive(
        "interstage face gap", geometry["interstage_flat_face_gap_mm"]
    )
    stage_1_axis_start_z = second_aperture_z + _positive(
        "ellipse upstream axial offset", ellipse["upstream_cone_axial_offset_mm"]
    )
    if not second_aperture_z < stage_1_axis_start_z < stage_1_end_z < stage_2_start_z < stage_2_end_z:
        raise ValueError("derived quadrupole axial sections are not strictly ordered")

    second_half_angle_rad = math.radians(second_angle / 2.0)
    cone_base_z = second_aperture_z + _positive(
        "enclosure radius", enclosure["cylinder_radius_mm"]
    ) / math.tan(second_half_angle_rad)
    stage_1_rod_array = build_rod_array(
        radial_order_n=2,
        electrode_count=4,
        inscribed_radius_r0_mm=stage_1_r0,
        rod_z_min_mm=stage_1_axis_start_z,
        rod_z_max_mm=stage_1_end_z,
        cross_section={
            "shape": "ellipse",
            "semi_major_axis_mm": major_semi_axis,
            "semi_minor_axis_mm": minor_semi_axis,
            "major_axis_orientation": "tangential",
        },
    )
    stage_2_rod_array = build_rod_array(
        radial_order_n=2,
        electrode_count=4,
        inscribed_radius_r0_mm=stage_2_r0,
        rod_radius_mm=round_radius,
        rod_z_min_mm=stage_2_start_z,
        rod_z_max_mm=stage_2_end_z,
    )
    return {
        "schema_version": 1,
        "role": "dual_cone_tandem_quadrupole_resolved_geometry",
        "status": "generated_from_provisional_geometry_interpretations",
        "project_id": PROJECT_ID,
        "coordinate_frame": baseline["coordinate_frame"],
        "geometry_mm": {
            "first_cone": {
                "included_angle_deg": first_angle,
                "half_angle_deg": first_angle / 2.0,
                "aperture_radius_mm": 0.5 * _positive(
                    "first cone aperture diameter", first["aperture_diameter_mm"]
                ),
                "aperture_reference_z_mm": first_aperture_z,
            },
            "second_cone": {
                "included_angle_deg": second_angle,
                "half_angle_deg": second_angle / 2.0,
                "aperture_radius_mm": 0.5 * _positive(
                    "second cone aperture diameter", second["aperture_diameter_mm"]
                ),
                "aperture_reference_z_mm": second_aperture_z,
                "theoretical_base_z_at_enclosure_radius_mm": cone_base_z,
            },
            "low_pressure_enclosure": {
                "radius_mm": _positive("enclosure radius", enclosure["cylinder_radius_mm"]),
                "start_z_mm": second_aperture_z,
                "end_z_mm": low_pressure_end_z,
            },
            "stage_1_elliptical_quadrupole": {
                "ideal_field_radius_r0_mm": stage_1_r0,
                "axis_upstream_start_z_mm": stage_1_axis_start_z,
                "downstream_flat_end_z_mm": stage_1_end_z,
                "rod_array": stage_1_rod_array,
                "upstream_end_surface": {
                    "model": "second_cone_surface_plus_axial_offset",
                    "axial_offset_mm": float(ellipse["upstream_cone_axial_offset_mm"]),
                    "formula": "z_start_mm = second_aperture_z_mm + axial_offset_mm + radial_position_mm / tan(second_half_angle_rad)",
                },
            },
            "interstage": {
                "upstream_face_z_mm": stage_1_end_z,
                "downstream_face_z_mm": stage_2_start_z,
                "clear_gap_mm": stage_2_start_z - stage_1_end_z,
            },
            "stage_2_round_quadrupole": {
                "adjacent_rod_center_distance_mm": adjacent_distance,
                "ideal_field_radius_r0_mm": stage_2_r0,
                "upstream_flat_start_z_mm": stage_2_start_z,
                "downstream_flat_end_z_mm": stage_2_end_z,
                "rod_array": stage_2_rod_array,
            },
        },
        "provisional_interpretations": [
            first["angle_interpretation"],
            second["angle_interpretation"],
            enclosure["length_origin_interpretation"],
            ellipse["upstream_end_model"],
            round_rods["center_distance_interpretation"],
            round_rods["downstream_alignment"],
        ],
        "omitted_geometry": baseline["missing_mechanical_inputs"],
    }


def serialized(document: dict[str, Any]) -> str:
    """Return the canonical tracked JSON representation."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write", type=Path, nargs="?", const=DEFAULT_RESOLVED)
    actions.add_argument("--check", type=Path, nargs="?", const=DEFAULT_RESOLVED)
    args = parser.parse_args()
    result = serialized(resolve_geometry(load_baseline(args.baseline.resolve())))
    destination = (args.write or args.check).resolve()
    if args.check:
        if not destination.is_file() or destination.read_text(encoding="utf-8-sig") != result:
            raise SystemExit(f"RESOLVED_GEOMETRY=FAIL stale_or_missing={destination}")
        print(f"RESOLVED_GEOMETRY=PASS PATH={destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result, encoding="utf-8", newline="\n")
    print(f"RESOLVED_GEOMETRY=BUILT PATH={destination}")


if __name__ == "__main__":
    main()
