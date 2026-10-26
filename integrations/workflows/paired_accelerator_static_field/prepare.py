"""Freeze the solver-neutral contract for an OA-only static field comparison.

The existing native geometry compiler renders the OA-only GEM from the same
frozen parent and provider. This stage solves no fields and creates no PA. Both
solvers consume the frozen common box, ON voltages and vacuum sample points.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
from common.integration.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from projects.single_reflection_oa_tof_mass_analyzer.analysis.assembly_interface import resolve_assembly_interface

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_electrical import (
    resolve_accelerator_electrical_design,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import (
    resolve_accelerator_geometry, project_side_opening,
)

_ROLE = "oatof_paired_accelerator_static_field_request"
_REQUIRED_RECORDS = {"parent_manifest", "frontend_geometry", "oatof_resolved"}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _record(value: object, label: str, base_dir: Path, *, snapshot: Path | None = None) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"path", "bytes", "sha256"}:
        raise ValueError(f"{label} requires path, bytes, and sha256")
    path = record_path(value, base_dir=base_dir).resolve()
    consumed = path if snapshot is None else snapshot.resolve()
    try:
        verify_record(label, {**value, "path": str(consumed)}, base_dir=base_dir)
    except AssertionError as error:
        raise ValueError(str(error)) from error
    return consumed, {"path": str(path), "bytes": value["bytes"], "sha256": value["sha256"].upper()}


def _bound_sources(manifest: dict, records: dict[str, dict]) -> None:
    if manifest.get("role") != "simulation_run_manifest" or not isinstance(manifest.get("inputs"), dict) or not isinstance(manifest.get("outputs"), list):
        raise ValueError("parent manifest must publish input/output records")
    published = [*manifest["inputs"].values(), *manifest["outputs"]]
    base = Path(records["parent_manifest"]["path"]).parent
    for name in ("frontend_geometry", "oatof_resolved"):
        expected = records[name]
        if not any(record_path(row, base_dir=base).resolve() == Path(expected["path"])
                   and row.get("bytes") == expected["bytes"]
                   and str(row.get("sha256", "")).upper() == expected["sha256"] for row in published):
            raise ValueError(f"parent manifest does not bind {name}")


def _provider_projection(frontend: dict, oatof: dict, variant: str) -> tuple[Any, dict, str, dict]:
    original = frontend["composition_plan"]
    parent = compile_assembly_layout(original["recipe"], original["components"])
    expected = (compile_assembly_layout(original["recipe"], original["components"], local_scope=original["local_scope"])
                if "local_scope" in original else parent)
    if {key: value for key, value in original.items() if key != "input_files"} != expected:
        raise ValueError("frontend composition plan differs from frozen embedded inputs")
    oatof_id, bindings = _local_electrodes(frontend)
    selected = derive_assembly_scope(parent, local_scope=dict(instance_ids=[oatof_id],
        research_scope="OA-only static field comparison", boundary_assumptions="Omit other instances; isolated OA with the declared common zero-normal outer box"))
    interface = parent["components"][oatof_id]
    if interface["local_frame_id"] != "oatof_global":
        raise ValueError("paired OA static fields require the oaTOF provider local frame")
    port = interface["ports"]["side_entry"]
    section = port["cross_section"]
    if section["shape"] != "rectangle":
        raise ValueError("paired OA static fields require the provider rectangular side opening")
    opening = dict(center_mm=port["center_mm"], width_mm=section["width_mm"], height_mm=section["height_mm"])
    domain = frontend["numerical_domains"]["parent"]
    projection = resolve_accelerator_geometry(oatof, variant_id=variant)
    project_side_opening(projection.local_region, side_opening=opening,
        cell_mm_xyz=domain["cell_mm_xyz"], pa_origin_mm=domain["instance_origin_mm"])
    if projection.local_region != frontend["accelerator_projection"]:
        raise ValueError("frontend physical accelerator projection differs from its resolved provider and mechanical side opening")
    if resolve_assembly_interface(oatof, projection=projection, geometry_profile_id=interface["geometry_profile_id"]) != interface:
        raise ValueError("parent oaTOF mechanical interface differs from the actual provider projection")
    return projection, selected, oatof_id, bindings


def _finite(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric")
    result = float(value)
    if positive and result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _box(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {f"{axis}_{side}" for axis in "xyz" for side in ("min", "max")}:
        raise ValueError("pa_bounds_mm requires exactly x/y/z min/max")
    result = {key: _finite(number, f"pa_bounds_mm.{key}") for key, number in value.items()}
    if any(result[f"{axis}_min"] >= result[f"{axis}_max"] for axis in "xyz"):
        raise ValueError("pa_bounds_mm requires increasing limits")
    return result


def _pitch(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set("xyz"):
        raise ValueError("cell_mm_xyz requires x, y, and z")
    return {axis: _finite(value[axis], f"cell_mm_xyz.{axis}", positive=True) for axis in "xyz"}


def _local_electrodes(frontend: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    plan = frontend.get("composition_plan")
    if not isinstance(plan, dict):
        raise ValueError("frontend geometry lacks composition_plan")
    scope = plan.get("scope")
    components = plan.get("components")
    if not isinstance(scope, dict) or not isinstance(components, dict):
        raise ValueError("frontend geometry composition plan is incomplete")
    instance_ids = scope.get("instance_ids")
    if not isinstance(instance_ids, list):
        raise ValueError("frontend geometry scope lacks instance IDs")
    candidates = [
        instance_id
        for instance_id in instance_ids
        if isinstance(instance_id, str)
        and isinstance(components.get(instance_id), dict)
        and components[instance_id].get("project_id") == "single_reflection_oa_tof_mass_analyzer"
    ]
    if len(candidates) != 1:
        raise ValueError("OA-only comparison requires exactly one oaTOF instance in scope")
    oatof_id = candidates[0]
    bindings = frontend.get("electrode_bindings")
    if not isinstance(bindings, dict) or oatof_id not in bindings or not isinstance(bindings[oatof_id], dict):
        raise ValueError("frontend geometry lacks oaTOF electrode bindings")
    return oatof_id, bindings[oatof_id]


def _on_voltages(electrical: dict[str, Any], bindings: dict[str, Any]) -> dict[str, float]:
    required = {
        "grounded_shield_id",
        "accelerator_repeller_id",
        "accelerator_grid1_id",
        "accelerator_intermediate2_id",
        "accelerator_grid2_id",
        "accelerator_ring_ids",
    }
    if set(bindings) != required:
        raise ValueError("OA-only comparison requires the exact three-zone OA electrode bindings")
    values = electrical["operating_voltages_v"]
    ids: dict[str, float] = {
        str(bindings["grounded_shield_id"]): float(values["shield"]),
        str(bindings["accelerator_repeller_id"]): float(values["repeller"]),
        str(bindings["accelerator_grid1_id"]): float(values["grid1"]),
        str(bindings["accelerator_intermediate2_id"]): float(values["intermediate2"]),
        str(bindings["accelerator_grid2_id"]): float(values["grid2"]),
    }
    ring_ids, ring_values = bindings["accelerator_ring_ids"], values["rings"]
    if not isinstance(ring_ids, list) or len(ring_ids) != len(ring_values):
        raise ValueError("OA ring binding differs from provider ON voltage projection")
    ids.update({str(electrode_id): float(voltage) for electrode_id, voltage in zip(ring_ids, ring_values, strict=True)})
    if len(ids) != 5 + len(ring_ids) or any(not math.isfinite(value) for value in ids.values()):
        raise ValueError("OA static ON electrode table is invalid")
    return ids


def _validate_grid_dimensions(box: dict[str, float], pitch: dict[str, float]) -> None:
    """Require a realizable common PA box without creating a PA."""
    for axis in "xyz":
        cells = (box[f"{axis}_max"] - box[f"{axis}_min"]) / pitch[axis]
        if cells < 2 or not math.isclose(cells, round(cells), rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"pa_bounds_mm.{axis} span must be an integral count of at least two cells")


def _validate_box_covers_provider(
    box: dict[str, float],
    geometry: dict[str, Any],
    metal_clearance_mm: float,
) -> None:
    """Keep the declared common numerical domain outside the real OA envelope."""
    axis_x = float(geometry["axis_x_mm"])
    outer_half = float(geometry["shield_outer_width_mm"]) / 2.0
    required = {
        "x_min": axis_x - outer_half - metal_clearance_mm,
        "x_max": axis_x + outer_half + metal_clearance_mm,
        "y_min": -outer_half - metal_clearance_mm,
        "y_max": outer_half + metal_clearance_mm,
        "z_min": float(geometry["shield_back_z_mm"]) - metal_clearance_mm,
        "z_max": float(geometry["grid2_z_mm"]) + metal_clearance_mm,
    }
    for key, boundary in required.items():
        if key.endswith("min") and box[key] > boundary:
            raise ValueError(f"pa_bounds_mm clips the OA provider at {key}")
        if key.endswith("max") and box[key] < boundary:
            raise ValueError(f"pa_bounds_mm clips the OA provider at {key}")


def _validate_points(
    points: object, *, box: dict[str, float], geometry: dict[str, Any], policy: dict[str, float]
) -> list[dict[str, float | int]]:
    if not isinstance(points, list) or not points:
        raise ValueError("sample_points requires at least one point")
    sheet_z = [geometry["grid1_z_mm"], geometry["intermediate2_z_mm"], geometry["grid2_z_mm"]]
    axis_x, bore_half = float(geometry["axis_x_mm"]), float(geometry["bore_width_mm"]) / 2
    inner_half = float(geometry["shield_inner_width_mm"]) / 2
    metal, sheet = policy["metal_clearance_mm"], policy["sheet_clearance_mm"]
    result: list[dict[str, float | int]] = []
    ids: set[int] = set()
    for row in points:
        if not isinstance(row, dict) or set(row) != {"point_id", "x_mm", "y_mm", "z_mm"}:
            raise ValueError("each sample point requires point_id, x_mm, y_mm, z_mm")
        point_id = row["point_id"]
        if type(point_id) is not int or point_id < 0 or point_id in ids:
            raise ValueError("sample point IDs must be unique nonnegative integers")
        ids.add(point_id)
        point = {axis: _finite(row[f"{axis}_mm"], f"sample point {point_id} {axis}") for axis in "xyz"}
        if any(
            point[axis] <= box[f"{axis}_min"] + metal or point[axis] >= box[f"{axis}_max"] - metal for axis in "xyz"
        ):
            raise ValueError(f"sample point {point_id} is not inside the common numerical box with metal clearance")
        if not geometry["repeller_front_z_mm"] + metal < point["z"] < geometry["grid2_z_mm"] - sheet:
            raise ValueError(f"sample point {point_id} is outside the open bore between repeller and exit")
        # Restrict to the open axial bore.  This is intentionally conservative:
        # it proves common vacuum without inventing a separate solid classifier.
        if abs(point["x"] - axis_x) >= bore_half - metal or abs(point["y"]) >= bore_half - metal:
            raise ValueError(f"sample point {point_id} is not in the OA bore vacuum with metal clearance")
        if abs(point["x"] - axis_x) >= inner_half - metal or abs(point["y"]) >= inner_half - metal:
            raise ValueError(f"sample point {point_id} is too close to the OA shield")
        if any(abs(point["z"] - plane) <= sheet for plane in sheet_z):
            raise ValueError(f"sample point {point_id} is too close to an ideal grid sheet")
        result.append({"point_id": point_id, **{f"{axis}_mm": point[axis] for axis in "xyz"}})
    return sorted(result, key=lambda row: int(row["point_id"]))


def prepare(request_path: Path, output_dir: Path, *, source_snapshot_root: Path | None = None,
            source_base_dir: Path | None = None) -> dict[str, Any]:
    request = _read(request_path)
    required = {
        "schema_version",
        "role",
        "source_records",
        "accelerator_variant",
        "numerical_domain",
        "clearance_policy",
        "sample_points",
    }
    if set(request) != required or request["schema_version"] != 2 or request["role"] != _ROLE:
        raise ValueError("paired accelerator static field request schema differs")
    sources = request["source_records"]
    if not isinstance(sources, dict) or set(sources) != _REQUIRED_RECORDS:
        raise ValueError("source_records requires parent_manifest, frontend_geometry, oatof_resolved")
    frozen: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}
    for name in sorted(_REQUIRED_RECORDS):
        snapshot = None if source_snapshot_root is None else source_snapshot_root / f"{name}.json"
        source_paths[name], frozen[name] = _record(sources[name], name,
            request_path.parent if source_base_dir is None else source_base_dir, snapshot=snapshot)
    _bound_sources(_read(source_paths["parent_manifest"]), frozen)
    frontend, oatof = _read(source_paths["frontend_geometry"]), _read(source_paths["oatof_resolved"])
    if request["accelerator_variant"] != "three_zone_square":
        raise ValueError("paired OA-only static field validation supports only three_zone_square")
    domain = request["numerical_domain"]
    if not isinstance(domain, dict) or set(domain) != {
        "pa_bounds_mm",
        "cell_mm_xyz",
        "boundary_policy",
        "comsol_outer_boundary",
        "comsol_mesh",
    }:
        raise ValueError("numerical_domain contract differs")
    if domain["boundary_policy"] != "native_zero_neumann" or domain["comsol_outer_boundary"] != "zero_charge":
        raise ValueError("paired field requires native_zero_neumann and COMSOL zero_charge outer boundaries")
    box, pitch = _box(domain["pa_bounds_mm"]), _pitch(domain["cell_mm_xyz"])
    _validate_grid_dimensions(box, pitch)
    mesh = domain["comsol_mesh"]
    if not isinstance(mesh, dict) or set(mesh) != {
        "global_automatic_level", "electrode_boundary_maximum_element_size_mm", "electrode_boundary_growth_rate"
    }:
        raise ValueError("comsol_mesh requires global_automatic_level, electrode_boundary_maximum_element_size_mm and electrode_boundary_growth_rate")
    level = mesh["global_automatic_level"]
    if type(level) is not int or not 1 <= level <= 9:
        raise ValueError("COMSOL global_automatic_level must be an integer from 1 to 9")
    mesh = {
        "global_automatic_level": level,
        **{name: _finite(mesh[name], f"COMSOL {name}", positive=True) for name in (
            "electrode_boundary_maximum_element_size_mm", "electrode_boundary_growth_rate")},
    }
    if mesh["electrode_boundary_growth_rate"] < 1:
        raise ValueError("COMSOL electrode_boundary_growth_rate must be at least 1")
    policy = request["clearance_policy"]
    if not isinstance(policy, dict) or set(policy) != {"metal_clearance_mm", "sheet_clearance_mm"}:
        raise ValueError("clearance_policy requires metal_clearance_mm and sheet_clearance_mm")
    policy = {name: _finite(policy[name], name, positive=True) for name in policy}
    provider, scope, oatof_id, bindings = _provider_projection(frontend, oatof, request["accelerator_variant"])
    # Validate the frozen physical projection on its original grid, then derive
    # only the new numerical aperture rasterization for the common BVP grid.
    projection = provider.local_region
    interface = scope["components"][oatof_id]["ports"]["side_entry"]
    opening = dict(center_mm=interface["center_mm"], width_mm=interface["cross_section"]["width_mm"],
                   height_mm=interface["cross_section"]["height_mm"])
    project_side_opening(projection, side_opening=opening, cell_mm_xyz=pitch,
        pa_origin_mm={axis: box[f"{axis}_min"] for axis in "xyz"})
    _validate_box_covers_provider(box, projection, policy["metal_clearance_mm"])
    electrical = resolve_accelerator_electrical_design(oatof, variant_id=request["accelerator_variant"])
    points = _validate_points(request["sample_points"], box=box, geometry=projection, policy=policy)
    gems, compiled = compile_frontend_geometry({}, oatof, composition_plan=scope,
        accelerator_variant=request["accelerator_variant"],
        numerical_domains={"parent": dict(pa_bounds_mm=box, cell_mm_xyz=pitch)},
        electrode_bindings={oatof_id: bindings})
    grid = compiled["numerical_domains"]["parent"]
    if (compiled["accelerator_projection"] != projection or compiled["composition_plan"] != scope
            or grid["bounds_mm"] != box or grid["cell_mm_xyz"] != pitch):
        raise ValueError("compiled OA geometry differs from the frozen physical projection or common domain")
    on_voltages = _on_voltages(electrical, compiled["electrode_bindings"][oatof_id])
    output_dir.mkdir(parents=True, exist_ok=True)
    gem_path = output_dir / "paired_accelerator.gem"
    gem_path.write_text(gems["parent"], encoding="utf-8", newline="\n")
    geometry_path = output_dir / "paired_accelerator_geometry.json"
    geometry_path.write_text(json.dumps(compiled, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
    point_path = output_dir / "paired_accelerator_field_points.csv"
    with point_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["point_id", "x_mm", "y_mm", "z_mm"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(points)
    plan = {
        "schema_version": 2,
        "role": "oatof_paired_accelerator_static_field_plan",
        "claim_limit": "OA-only provider GEM and common BVP preparation only; no native field, numerical-equivalence, particle, RF, pulse, or full-instrument conclusion.",
        "source_records": frozen,
        "accelerator_variant": request["accelerator_variant"],
        "oatof_instance_id": oatof_id,
        "composition_plan": scope,
        "coordinate_frame": "oatof_global",
        "numerical_domain": {
            "pa_bounds_mm": box,
            "cell_mm_xyz": pitch,
            "boundary_policy": domain["boundary_policy"],
            "comsol_outer_boundary": domain["comsol_outer_boundary"],
            "comsol_mesh": mesh,
        },
        "clearance_policy": policy,
        "accelerator_geometry": projection,
        "accelerator_electrical": electrical,
        "static_on_electrode_voltages_v": on_voltages,
        "sample_points": {
            "path": str(point_path.resolve()),
            "count": len(points),
            "schema": ["point_id", "x_mm", "y_mm", "z_mm"],
        },
        "native_geometry_compilation": {
            "status": "compiled_gem",
            "local_scope_instance_id": oatof_id,
            "gem_record": file_record(gem_path),
            "geometry_record": file_record(geometry_path),
            "grid": grid,
            "electrode_bindings": compiled["electrode_bindings"],
        },
    }
    plan_path = output_dir / "paired_accelerator_static_field_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return plan
