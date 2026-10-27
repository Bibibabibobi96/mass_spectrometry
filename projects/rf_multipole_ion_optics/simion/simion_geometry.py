"""Export one canonical multipole resolved design to a SIMION GEM file."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from projects.rf_multipole_ion_optics.core.connector_geometry import CONNECTOR_SHAPES
from projects.rf_multipole_ion_optics.core.axial_acceleration import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
from projects.rf_multipole_ion_optics.runtime.simion_numerics import normalize_cell_mm_xyz


_GLOBAL_X_ROTATION_AXIS_SELECTOR = 1


def render_grouped_rod_array_gem(
    array: dict[str, Any],
    *,
    electrode_group_ids: dict[int, int] | None = None,
) -> str:
    """Render a shared rod array with optionally remapped SIMION electrodes."""
    rods = array["rods"]
    if not rods:
        raise ValueError("rod array must contain at least one rod")
    group_ids = _validate_electrode_group_ids(electrode_group_ids)
    z_max = float(rods[0]["z_max_mm"])
    lines = [f"locate(0,0,{z_max:.15g}) {{"]
    for group in (1, 2):
        lines.append(f"  e({group_ids[group]}) {{")
        for rod in rods:
            if int(rod["electrode_group"]) != group:
                continue
            x = 0.0 if abs(float(rod["center_x_mm"])) < 1e-12 else float(rod["center_x_mm"])
            y = 0.0 if abs(float(rod["center_y_mm"])) < 1e-12 else float(rod["center_y_mm"])
            length = float(rod["z_max_mm"]) - float(rod["z_min_mm"])
            if "radius_mm" in rod:
                lines.append(
                    "    fill { within { cylinder("
                    f"{x:.15g},{y:.15g},0, {float(rod['radius_mm']):.15g},, {length:.15g}) }} }}"
                )
            else:
                semi_major, semi_minor, angle_degrees = _ellipse_rod_values(rod)
                lines.append(
                    "    fill { within { locate("
                    f"{x:.15g},{y:.15g},0) {{ rotate_z({angle_degrees:.15g}) {{ "
                    f"cylinder(0,0,0,{semi_major:.15g},{semi_minor:.15g},{length:.15g}) "
                    "} } } }"
                )
        lines.append("  }")
    lines.extend(["}", ""])
    return "\n".join(lines)


def render_segmented_rod_array_gem(segmented: dict[str, Any]) -> str:
    """Render solver-neutral rod segments using their explicit electrode IDs."""
    return _render_located_segmented_rod_array_gem(
        segmented, significant_digits=15, legacy_spacing=True
    )


def _render_located_segmented_rod_array_gem(
    segmented: dict[str, Any], *, significant_digits: int, legacy_spacing: bool
) -> str:
    primitives = _segmented_rod_primitives(segmented)
    fmt = lambda value: format(value, f".{significant_digits}g")
    radius_prefix = " " if legacy_spacing else ""
    lines: list[str] = []
    for primitive in primitives:
        lines.append(f"locate(0,0,{fmt(primitive['z_max_mm'])}) {{")
        if "radius_mm" in primitive:
            lines.append(
                f"  e({primitive['electrode_id']}) {{ fill {{ within {{ cylinder("
                f"{fmt(primitive['center_x_mm'])},{fmt(primitive['center_y_mm'])},0,"
                f"{radius_prefix}{fmt(primitive['radius_mm'])},,{radius_prefix}"
                f"{fmt(primitive['length_mm'])}) }} }} }}"
            )
        else:
            lines.append(_render_ellipse_primitive(primitive, fmt, indent="  ", z_position=0.0))
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def segmented_rod_electrode_ids(segmented: dict[str, Any]) -> list[int]:
    """Return the canonical explicit electrode namespace of a segmented rod array."""
    return sorted({item["electrode_id"] for item in _segmented_rod_primitives(segmented)})


def physical_electrode_view(resolved: dict[str, Any]) -> list[dict[str, Any]]:
    """Return rods and the optional single grounded enclosure namespace.

    This is the narrow common view for the native renderer and ordinary-field
    consumers.  ``native_electrode_id`` is the GEM/SIMION namespace; the
    separate ``scientific_id`` names the physical electrical group.  Voltage
    sources point back into the resolved provider rather than copying any
    drive value into a second authority.
    """
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("physical electrode view requires a multipole resolved design")
    enclosure = resolved["geometry_mm"]["enclosure"]
    if enclosure["model"] not in {
        "bare", "cylindrical_grounded_shell",
    }:
        raise ValueError("physical electrode view requires a bare or grounded-shell multipole")

    rows: dict[int, dict[str, Any]] = {}

    def add(
        native_electrode_id: int,
        scientific_id: str,
        role: str,
        voltage_source: dict[str, Any],
        *,
        static_voltage_v: float | None = None,
    ) -> None:
        if (
            isinstance(native_electrode_id, bool)
            or not isinstance(native_electrode_id, int)
            or not 1 <= native_electrode_id <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
        ):
            raise ValueError("physical electrode native ID is outside the SIMION namespace")
        if voltage_source["kind"] == "static" and (
            isinstance(static_voltage_v, bool)
            or not isinstance(static_voltage_v, (int, float))
            or not math.isfinite(static_voltage_v)
        ):
            raise ValueError("physical electrode static potential must be finite")
        row = rows.get(native_electrode_id)
        if row is None:
            rows[native_electrode_id] = {
                "native_electrode_id": native_electrode_id,
                "scientific_id": scientific_id,
                "roles": [role],
                "voltage_source": voltage_source,
                "_static_voltage_v": static_voltage_v,
            }
            return
        if row["scientific_id"] != scientific_id:
            raise ValueError("physical electrode ID merges incompatible scientific groups")
        if row["voltage_source"]["kind"] != voltage_source["kind"]:
            raise ValueError("physical electrode ID merges RF and static groups")
        if row["voltage_source"]["kind"] == "rf_drive":
            if row["voltage_source"] != voltage_source:
                raise ValueError("physical rod electrode has conflicting resolved drive source")
        elif row["_static_voltage_v"] != static_voltage_v:
            raise ValueError("physical static electrode has conflicting resolved potentials")
        if role not in row["roles"]:
            row["roles"].append(role)

    segmented = resolved["segmentation"]["segmented_rod_array"]
    if segmented is None:
        rods = resolved["geometry_mm"]["rod_array"]["rods"]
        groups = sorted({int(rod["electrode_group"]) for rod in rods})
        if not groups or any(group not in {1, 2} for group in groups):
            raise ValueError("continuous rod group is outside the resolved RF groups")
        for group in groups:
            add(
                group,
                f"rod_group_{group}",
                "rod",
                {
                    "kind": "rf_drive",
                    "rf_group": group,
                    "common_mode_pointer": "/drive/common_mode_offset_V",
                    "dc_amplitude_pointer": "/drive/dc_amplitude_V_per_group",
                },
            )
    else:
        primitives = _segmented_rod_primitives(segmented)
        grouped_sources: dict[int, list[tuple[int, dict[str, Any]]]] = {}
        for index, source in enumerate(segmented["electrodes"]):
            grouped_sources.setdefault(int(source["electrode_id"]), []).append((index, source))
        expected_group_counts = {
            group: sum(1 for rod in resolved["geometry_mm"]["rod_array"]["rods"]
                       if int(rod["electrode_group"]) == group)
            for group in (1, 2)
        }
        validate_full_table = all(
            "segment_id" in source for source in segmented["electrodes"]
        )
        for native_electrode_id in sorted({int(item["electrode_id"]) for item in primitives}):
            entries = grouped_sources[native_electrode_id]
            position, source = entries[0]
            rf_group = source.get("electrode_group")
            if rf_group not in {1, 2}:
                raise ValueError("segmented rod electrode must declare one resolved RF group")
            common_mode = source.get("common_mode_V")
            if (
                isinstance(common_mode, bool)
                or not isinstance(common_mode, (int, float))
                or not math.isfinite(common_mode)
            ):
                raise ValueError("segmented rod electrode must declare finite common-mode voltage")
            if any(
                other.get("electrode_group") != rf_group
                or other.get("common_mode_V") != common_mode
                for _, other in entries[1:]
            ):
                raise ValueError("segmented rod electrode has conflicting resolved drive source")
            if validate_full_table and len(entries) != expected_group_counts[rf_group]:
                raise ValueError("segmented rod physical table is missing or duplicates a rod group")
            add(
                native_electrode_id,
                f"rod_group_{native_electrode_id}",
                "rod",
                {
                    "kind": "rf_drive",
                    "rf_group": rf_group,
                    "common_mode_pointer": (
                        f"/segmentation/segmented_rod_array/electrodes/{position}"
                        "/common_mode_V"
                    ),
                    "dc_amplitude_pointer": "/drive/dc_amplitude_V_per_group",
                },
            )

    layout = resolved["geometry_mm"]["enclosure_layout"]
    static = resolved["static_electrodes_V"]
    if layout["bodies"]:
        ground_electrode = max(rows) + 1
        if static["role"] != "grounded_shell_static_electrodes" or static["ground_V"] != 0:
            raise ValueError("the enclosure and its optional endcaps must share ground")
        for body in layout["bodies"]:
            add(
                ground_electrode, "grounded_shell", body["role"],
                {"kind": "static", "pointer": "/static_electrodes_V/ground_V"},
                static_voltage_v=static["ground_V"],
            )
    elif static != {"role": "bare_multipole_static_electrodes"}:
        raise ValueError("a bare multipole cannot declare enclosure voltages")
    view = []
    for native_electrode_id in sorted(rows):
        row = rows[native_electrode_id]
        row.pop("_static_voltage_v")
        view.append(row)
    return view


def _render_local_segmented_rod_array_gem(
    segmented: dict[str, Any], *, indent: str = "  ", significant_digits: int = 12,
    electrode_ids: dict[int, int] | None = None,
) -> str:
    """Render canonical rod primitives in their native local frame."""
    indent, significant_digits = _validate_render_format(indent, significant_digits)
    fmt = lambda value: format(value, f".{significant_digits}g")
    lines = []
    for item in _segmented_rod_primitives(segmented):
        if electrode_ids is not None:
            item = {**item, "electrode_id": electrode_ids[item["electrode_id"]]}
        if "radius_mm" in item:
            lines.append(
                f"{indent}e({item['electrode_id']}) {{ fill {{ within {{ cylinder("
                f"{fmt(item['center_x_mm'])},{fmt(item['center_y_mm'])},{fmt(item['z_max_mm'])},"
                f"{fmt(item['radius_mm'])},,{fmt(item['length_mm'])}) }} }} }}"
            )
        else:
            lines.append(
                _render_ellipse_primitive(
                    item,
                    fmt,
                    indent=indent,
                    z_position=item["z_max_mm"],
                )
            )
    return "\n".join(lines)


def render_axis_mapped_segmented_rod_array_gem(
    segmented: dict[str, Any],
    *,
    axial_origin_mm: float,
    transverse_origin_mm: tuple[float, float],
    rotation_axis: int,
    rotation_degrees: float,
    indent: str = "",
    significant_digits: int = 12,
) -> str:
    """Render local-z rod cylinders on the current assembly's global-X axis.

    The segmented rod contract remains the sole primitive and electrode-mapping
    authority. The caller supplies only the placement needed by its assembly.
    This narrow placement supports SIMION ``locate`` rotation selector 1 only;
    it is not a general-purpose arbitrary-axis renderer.
    """
    primitives = _segmented_rod_primitives(segmented)
    axial_origin = _finite_real(axial_origin_mm, "axial_origin_mm")
    if (
        not isinstance(transverse_origin_mm, tuple)
        or len(transverse_origin_mm) != 2
    ):
        raise ValueError("transverse_origin_mm must be one two-value tuple")
    transverse_x = _finite_real(transverse_origin_mm[0], "transverse_origin_mm[0]")
    transverse_y = _finite_real(transverse_origin_mm[1], "transverse_origin_mm[1]")
    if isinstance(rotation_axis, bool) or not isinstance(rotation_axis, int):
        raise ValueError("rotation_axis must be one official integer selector")
    if rotation_axis != _GLOBAL_X_ROTATION_AXIS_SELECTOR:
        raise ValueError("axis-mapped rod placement requires official selector 1")
    rotation = _finite_real(rotation_degrees, "rotation_degrees")
    indent, significant_digits = _validate_render_format(indent, significant_digits)

    def fmt(value: float) -> str:
        return format(float(value), f".{significant_digits}g")

    lines = []
    for primitive in primitives:
        prefix = (
            f"{indent}e({primitive['electrode_id']}) {{ fill {{ within {{ locate("
            f"{fmt(axial_origin+primitive['z_max_mm'])},"
            f"{fmt(transverse_x+primitive['center_x_mm'])},"
            f"{fmt(transverse_y+primitive['center_y_mm'])},{rotation_axis},"
            f"{fmt(rotation)}) {{"
        )
        if "radius_mm" in primitive:
            lines.append(
                f"{prefix} cylinder(0,0,0,{fmt(primitive['radius_mm'])},,"
                f"{fmt(primitive['length_mm'])}) }} }} }} }}"
            )
        else:
            semi_major, semi_minor, angle_degrees = _ellipse_rod_values(primitive)
            lines.append(
                f"{prefix} rotate_z({fmt(angle_degrees)}) {{ cylinder(0,0,0,"
                f"{fmt(semi_major)},{fmt(semi_minor)},{fmt(primitive['length_mm'])}) }} "
                "} } } }"
            )
    return "\n".join(lines)


def _validate_electrode_group_ids(
    electrode_group_ids: dict[int, int] | None,
) -> dict[int, int]:
    if electrode_group_ids is None:
        return {1: 1, 2: 2}
    if set(electrode_group_ids) != {1, 2}:
        raise ValueError("electrode_group_ids must map source groups 1 and 2")
    values = tuple(electrode_group_ids[group] for group in (1, 2))
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
        for value in values
    ) or values[0] == values[1]:
        raise ValueError("electrode_group_ids values must be distinct valid SIMION electrode IDs")
    return dict(electrode_group_ids)


def _ellipse_rod_values(rod: dict[str, Any]) -> tuple[float, float, float]:
    required = {"semi_major_axis_mm", "semi_minor_axis_mm", "major_axis_angle_rad"}
    if not required.issubset(rod) or "radius_mm" in rod:
        raise ValueError("ellipse rod contract is incomplete or mixes round and ellipse fields")
    semi_major, semi_minor, angle = (
        _finite_real(rod[key], key)
        for key in ("semi_major_axis_mm", "semi_minor_axis_mm", "major_axis_angle_rad")
    )
    if semi_major <= 0 or semi_minor <= 0 or semi_major < semi_minor:
        raise ValueError("ellipse rod semi-axes must be positive with major not below minor")
    return semi_major, semi_minor, math.degrees(angle)


def _render_ellipse_primitive(
    primitive: dict[str, Any],
    fmt: Any,
    *,
    indent: str,
    z_position: float,
) -> str:
    # Official GEM cylinder syntax accepts separate x/y radii; rotate_z is the
    # supported local-axis transform: https://simion.com/info/gem_geometry_file.html
    semi_major, semi_minor, angle_degrees = _ellipse_rod_values(primitive)
    return (
        f"{indent}e({primitive['electrode_id']}) {{ fill {{ within {{ locate("
        f"{fmt(primitive['center_x_mm'])},{fmt(primitive['center_y_mm'])},{fmt(z_position)}) {{ "
        f"rotate_z({fmt(angle_degrees)}) {{ cylinder(0,0,0,{fmt(semi_major)},"
        f"{fmt(semi_minor)},{fmt(primitive['length_mm'])}) }} }} }} }} }}"
    )


def _render_continuous_rod_gem(
    rod: dict[str, Any], *, indent: str, electrode_id: int | None = None,
) -> str:
    electrode_id = rod["electrode_group"] if electrode_id is None else electrode_id
    if "radius_mm" in rod:
        return (
            f"{indent}e({electrode_id}) {{ fill {{ within {{ cylinder("
            f"{rod['center_x_mm']:.12g},{rod['center_y_mm']:.12g},"
            f"{rod['z_max_mm']:.12g},{rod['radius_mm']:.12g},,"
            f"{rod['z_max_mm']-rod['z_min_mm']:.12g}) }} }} }}"
        )
    semi_major, semi_minor, angle_degrees = _ellipse_rod_values(rod)
    length = float(rod["z_max_mm"]) - float(rod["z_min_mm"])
    return (
        f"{indent}e({electrode_id}) {{ fill {{ within {{ locate("
        f"{float(rod['center_x_mm']):.12g},{float(rod['center_y_mm']):.12g},"
        f"{float(rod['z_max_mm']):.12g}) {{ rotate_z({angle_degrees:.12g}) {{ "
        f"cylinder(0,0,0,{semi_major:.12g},{semi_minor:.12g},{length:.12g}) "
        "} } } } }"
    )


def _finite_real(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be one finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _validate_render_format(indent: Any, significant_digits: Any) -> tuple[str, int]:
    if indent not in ("", "  ", "    "):
        raise ValueError("indent must be a supported whitespace prefix")
    if (
        isinstance(significant_digits, bool)
        or not isinstance(significant_digits, int)
        or not 1 <= significant_digits <= 17
    ):
        raise ValueError("significant_digits must be an integer from 1 through 17")
    return indent, significant_digits


def _segmented_rod_primitives(segmented: dict[str, Any]) -> list[dict[str, Any]]:
    segment_count = segmented.get("segment_count")
    electrodes = segmented.get("electrodes", [])
    if not isinstance(segment_count, int) or isinstance(segment_count, bool) or segment_count < 2:
        raise ValueError("segmented rod contract must declare at least two segments")
    if not isinstance(electrodes, list) or not electrodes:
        raise ValueError("segmented rod contract must contain electrodes")
    required = {"electrode_id", "center_x_mm", "center_y_mm", "z_min_mm", "z_max_mm"}
    primitives = []
    for electrode in electrodes:
        if not isinstance(electrode, dict) or not required.issubset(electrode):
            raise ValueError("segmented rod electrode contract is incomplete")
        electrode_id = electrode["electrode_id"]
        if (
            isinstance(electrode_id, bool)
            or not isinstance(electrode_id, int)
            or not 1 <= electrode_id <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
        ):
            raise ValueError("segmented rod electrode_id is outside the SIMION namespace")
        center_x, center_y, z_min, z_max = (
            _finite_real(electrode[key], key)
            for key in ("center_x_mm", "center_y_mm", "z_min_mm", "z_max_mm")
        )
        if z_max <= z_min:
            raise ValueError("segmented rod electrode length must be positive")
        primitive = {
            "electrode_id": electrode_id,
            "center_x_mm": center_x,
            "center_y_mm": center_y,
            "z_max_mm": z_max,
            "length_mm": z_max - z_min,
        }
        if "radius_mm" in electrode:
            radius = _finite_real(electrode["radius_mm"], "radius_mm")
            if radius <= 0:
                raise ValueError("segmented rod electrode radius must be positive")
            if any(
                key in electrode
                for key in ("semi_major_axis_mm", "semi_minor_axis_mm", "major_axis_angle_rad")
            ):
                raise ValueError("segmented rod electrode mixes round and ellipse fields")
            primitive["radius_mm"] = radius
        else:
            semi_major, semi_minor, angle_degrees = _ellipse_rod_values(electrode)
            primitive.update(
                semi_major_axis_mm=semi_major,
                semi_minor_axis_mm=semi_minor,
                major_axis_angle_rad=math.radians(angle_degrees),
            )
        primitives.append(primitive)
    expected_ids = set(range(1, 2 * segment_count + 1))
    if {item["electrode_id"] for item in primitives} != expected_ids:
        raise ValueError("segmented rod electrode IDs must be the complete segment-group namespace")
    return primitives


def render_gem(
    resolved: dict[str, Any],
    cell_mm_xyz: dict[str, float] | float,
) -> str:
    """Render one finite multipole directly from its authoritative resolved design."""
    return _render_native_gem(resolved, cell_mm_xyz, standalone=True, electrode_ids=None)


def render_physical_gem(
    resolved: dict[str, Any], cell_mm_xyz: dict[str, float] | float,
    *, electrode_ids: dict[int, int] | None = None,
) -> str:
    """Project frozen provider bodies in their native local millimetre frame.

    The numerical domain and observation planes add no physical electrode.
    Assembly placement belongs to the consumer and is applied once.
    """
    return _render_native_gem(resolved, cell_mm_xyz, standalone=False, electrode_ids=electrode_ids)


def _render_native_gem(
    resolved: dict[str, Any], cell_mm_xyz: dict[str, float] | float,
    *, standalone: bool, electrode_ids: dict[int, int] | None,
) -> str:
    """Use the same physical bodies for standalone and assembly projections."""
    cell = normalize_cell_mm_xyz(cell_mm_xyz)
    dx, dy, dz = cell["x"], cell["y"], cell["z"]
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("SIMION geometry requires a multipole resolved design")
    geometry = resolved["geometry_mm"]
    segmented = resolved["segmentation"]["segmented_rod_array"]
    if geometry["enclosure"]["model"] == "rectangular_reference_enclosure_v1":
        if not standalone:
            raise ValueError("rectangular reference geometry is not a physical component export")
        return _render_rectangular_reference_gem(
            geometry, _rectangular_reference_interfaces(resolved), cell,
            segmented, resolved["resolved_sha256"],
        )
    view = physical_electrode_view(resolved)
    physical_ids = {row["native_electrode_id"] for row in view}
    if electrode_ids is not None and (
        set(electrode_ids) != physical_ids
        or any(type(key) is not int for key in electrode_ids)
        or any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
               for value in electrode_ids.values())
        or len(set(electrode_ids.values())) != len(electrode_ids)
    ):
        raise ValueError("electrode_ids must map every physical native electrode to distinct valid solver IDs")
    if standalone:
        domain = geometry["numerical_domain"]
        radius = float(domain["radius_mm"])
        z_min, z_max = float(domain["z_min_mm"]), float(domain["z_max_mm"])
        nx, ny = math.ceil(2 * radius / dx) + 1, math.ceil(2 * radius / dy) + 1
        nz = math.ceil((z_max - z_min) / dz) + 1
        lines = [
            "; Generated from multipole_resolved_design; do not edit.",
            f"; parent_resolved_sha256={resolved['resolved_sha256']}",
            f"pa_define({nx},{ny},{nz},planar,none,electrostatic,,{dx:.12g},{dy:.12g},{dz:.12g},surface=fractional)",
            f"locate({radius:.12g},{radius:.12g},{-z_min:.12g}) {{",
        ]
    else:
        lines = []
    if segmented is not None:
        lines.extend(_render_local_segmented_rod_array_gem(
            segmented, electrode_ids=electrode_ids,
        ).splitlines())
    else:
        for rod in geometry["rod_array"]["rods"]:
            native_id = int(rod["electrode_group"])
            mapped_id = electrode_ids[native_id] if electrode_ids is not None else native_id
            lines.append(_render_continuous_rod_gem(rod, indent="  ", electrode_id=mapped_id))
    grounds = [row for row in view if row["scientific_id"] == "grounded_shell"]
    if grounds:
        native_id = grounds[0]["native_electrode_id"]
        ground_id = electrode_ids[native_id] if electrode_ids is not None else native_id
        for body in geometry["enclosure_layout"]["bodies"]:
            lo, hi = float(body["z_min_mm"]), float(body["z_max_mm"])
            inner, outer = float(body["inner_radius_mm"]), float(body["outer_radius_mm"])
            # The cut overruns only the ring end faces; no metal surface moves.
            lines.extend([
                f"  ; enclosure_role={body['role']}",
                f"  e({ground_id}) {{ fill {{",
                f"    within {{ cylinder(0,0,{hi:.12g},{outer:.12g},,{hi-lo:.12g}) }}",
                f"    notin_inside {{ cylinder(0,0,{hi+dz:.12g},{inner:.12g},,{hi-lo+2*dz:.12g}) }}",
                "  } }",
            ])
    if standalone:
        lines.append("}")
    return "\n".join(lines) + "\n"


def _rectangular_reference_interfaces(resolved: dict[str, Any]) -> dict[str, Any]:
    """Retain explicit optics only in the independent rectangular reference."""
    source = resolved["interfaces_mm"]
    result = {"census_plane_z": source["exit"]["census_plane_z_mm"],
              "census_radius": resolved["geometry_mm"]["enclosure"]["physical_detector_radius_mm"]}
    for side in ("entrance", "exit"):
        interface = source[side]
        result.update({
            f"{side}_plate_z_min": interface["aperture_plate_upstream_face_z_mm"],
            f"{side}_plate_z_max": interface["aperture_plate_downstream_face_z_mm"],
            f"{side}_aperture_radius": interface["aperture_radius_mm"],
            f"{side}_connector_length": interface["connector_length_mm"],
            f"{side}_connector_shape": interface["connector_shape"],
        })
    _validate_connector_shapes(result)
    return result


def _validate_connector_shapes(interface: dict[str, Any]) -> None:
    for side in ("entrance", "exit"):
        shape = interface.get(f"{side}_connector_shape")
        if shape not in CONNECTOR_SHAPES:
            raise ValueError(f"{side} connector shape is unsupported: {shape}")


def _render_rectangular_reference_gem(
    geometry: dict[str, Any],
    interface: dict[str, Any],
    cell_mm_xyz: dict[str, float],
    segmented_rods: dict[str, Any] | None,
    parent_hash: str,
) -> str:
    dx, dy, dz = (
        cell_mm_xyz["x"],
        cell_mm_xyz["y"],
        cell_mm_xyz["z"],
    )
    enclosure = geometry["enclosure"]
    rods = geometry["rod_array"]["rods"]
    if segmented_rods is not None:
        rods = segmented_rods.get("electrodes", [])
        segment_count = segmented_rods.get("segment_count")
        if not isinstance(segment_count, int) or segment_count < 2 or not rods:
            raise ValueError("segmented rod contract is incomplete")
        ground_electrode = 2 * segment_count + 1
        output_electrode = ground_electrode + 1
    else:
        ground_electrode = 3
        output_electrode = 4
    physical_detector_electrode = output_electrode + 1
    outer = float(enclosure["outer_half_width_mm"])
    inner = float(enclosure["inner_half_width_mm"])
    z_min = float(enclosure["vacuum_z_min_mm"])
    z_max = float(enclosure["vacuum_z_max_mm"])
    nx = math.ceil(outer / dx) + 1
    ny = math.ceil(outer / dy) + 1
    computational_z_max = z_max + 3 * dz
    nz = math.ceil((computational_z_max - z_min) / dz) + 1
    lines = [
        "; Generated from multipole_resolved_design; do not edit.",
        f"; parent_resolved_sha256={parent_hash}",
        f"pa_define({nx},{ny},{nz},planar,xy,electrostatic,,{dx:.12g},{dy:.12g},{dz:.12g},surface=fractional)",
    ]
    if segmented_rods is not None:
        lines.extend(
            _render_located_segmented_rod_array_gem(
                segmented_rods, significant_digits=12, legacy_spacing=False
            ).splitlines()
        )
    else:
        for rod in rods:
            z0 = float(rod["z_min_mm"])
            z1 = float(rod["z_max_mm"])
            lines.append(f"locate(0,0,{z1:.12g}) {{")
            if "radius_mm" in rod:
                lines.append(
                    f"  e({int(rod['electrode_group'])}) {{ fill {{ within {{ cylinder("
                    f"{float(rod['center_x_mm']):.12g},{float(rod['center_y_mm']):.12g},"
                    f"0,{float(rod['radius_mm']):.12g},,{z1-z0:.12g}) }} }} }}"
                )
            else:
                semi_major, semi_minor, angle_degrees = _ellipse_rod_values(rod)
                lines.append(
                    f"  e({int(rod['electrode_group'])}) {{ fill {{ within {{ locate("
                    f"{float(rod['center_x_mm']):.12g},{float(rod['center_y_mm']):.12g},0) {{ "
                    f"rotate_z({angle_degrees:.12g}) {{ cylinder(0,0,0,"
                    f"{semi_major:.12g},{semi_minor:.12g},{z1-z0:.12g}) }} }} }} }} }}"
                )
            lines.append("}")
    _append_rectangular_apertured_section(
        lines,
        ground_electrode,
        outer,
        interface["entrance_aperture_radius"],
        interface["entrance_plate_z_min"],
        float(interface["entrance_plate_z_max"]) - float(interface["entrance_plate_z_min"]),
    )
    exit_z_min = float(enclosure["exit_enclosure_z_min_mm"])
    exit_z_max = float(enclosure["exit_enclosure_z_max_mm"])
    front_end = float(enclosure["exit_front_wall_end_z_mm"])
    lines.extend(
        [
            f"locate(0,0,{exit_z_min:.12g}) {{",
            f"  e({output_electrode}) {{ fill {{",
            f"    within {{ box3d({outer:.12g},{outer:.12g},0,{-outer:.12g},{-outer:.12g},{exit_z_max-exit_z_min:.12g}) }}",
            f"    notin_inside {{ box3d({inner:.12g},{inner:.12g},{front_end-exit_z_min:.12g},{-inner:.12g},{-inner:.12g},1E+6) }}",
            f"    notin_inside {{ cylinder(0,0,{exit_z_max-exit_z_min+dz:.12g},{float(interface['exit_aperture_radius']):.12g},,{exit_z_max-exit_z_min+2*dz:.12g}) }}",
            "  } }",
            "  ; GUI-visible numerical absorber downstream of the census plane; not a physical detector.",
            f"  e({physical_detector_electrode}) {{ fill {{ within {{ cylinder(0,0,{float(interface['census_plane_z'])-exit_z_min+dz:.12g},{float(interface['census_radius']):.12g},,{dz:.12g}) }} }} }}",
            "}",
        ]
    )
    _append_connector(
        lines,
        ground_electrode,
        interface["entrance_connector_shape"],
        outer,
        interface["entrance_aperture_radius"],
        float(interface["entrance_plate_z_min"]) - float(interface["entrance_connector_length"]),
        interface["entrance_connector_length"],
        dz,
    )
    _append_connector(
        lines,
        output_electrode,
        interface["exit_connector_shape"],
        outer,
        interface["exit_aperture_radius"],
        interface["exit_plate_z_max"],
        interface["exit_connector_length"],
        dz,
    )
    lines.append("")
    return "\n".join(lines)


def _append_rectangular_apertured_section(
    lines: list[str],
    electrode: int,
    outer_half_width_mm: float,
    aperture_radius_mm: float,
    z_min_mm: float,
    length_mm: float,
) -> None:
    lines.extend(
        [
            f"locate(0,0,{float(z_min_mm):.12g}) {{",
            f"  e({electrode}) {{ fill {{",
            f"    within {{ box3d({outer_half_width_mm:.12g},{outer_half_width_mm:.12g},0,{-outer_half_width_mm:.12g},{-outer_half_width_mm:.12g},{float(length_mm):.12g}) }}",
            f"    notin_inside {{ cylinder(0,0,{float(length_mm):.12g},{float(aperture_radius_mm):.12g},,{float(length_mm):.12g}) }}",
            "  } }",
            "}",
        ]
    )


def _append_connector(
    lines: list[str],
    electrode: int,
    shape: str,
    outer_size_mm: float,
    aperture_radius_mm: float,
    z_min_mm: float,
    length_mm: float,
    cell_mm_z: float,
) -> None:
    length = float(length_mm)
    if length == 0:
        return
    lines.extend([f"; connector_shape={shape}", f"locate(0,0,{float(z_min_mm):.12g}) {{", f"  e({electrode}) {{ fill {{"])
    if shape == "rectangular_bore":
        lines.append(
            f"    within {{ box3d({outer_size_mm:.12g},{outer_size_mm:.12g},0,{-outer_size_mm:.12g},{-outer_size_mm:.12g},{length:.12g}) }}"
        )
    else:
        lines.append(f"    within {{ cylinder(0,0,{length:.12g},{outer_size_mm:.12g},,{length:.12g}) }}")
    lines.extend(
        [
            f"    notin_inside {{ cylinder(0,0,{length+cell_mm_z:.12g},{float(aperture_radius_mm):.12g},,{length+2*cell_mm_z:.12g}) }}",
            "  } }",
            "}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--cell-mm", type=float)
    parser.add_argument("--cell-mm-x", type=float)
    parser.add_argument("--cell-mm-y", type=float)
    parser.add_argument("--cell-mm-z", type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    axis_values = (args.cell_mm_x, args.cell_mm_y, args.cell_mm_z)
    if args.cell_mm is not None and any(value is not None for value in axis_values):
        parser.error("--cell-mm is mutually exclusive with three-axis cell spacing")
    if args.cell_mm is None and not all(value is not None for value in axis_values):
        parser.error("provide --cell-mm or all of --cell-mm-x/y/z")
    cell_mm_xyz: dict[str, float] | float = (
        args.cell_mm
        if args.cell_mm is not None
        else {"x": args.cell_mm_x, "y": args.cell_mm_y, "z": args.cell_mm_z}
    )
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_gem(resolved, cell_mm_xyz),
        encoding="ascii",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
