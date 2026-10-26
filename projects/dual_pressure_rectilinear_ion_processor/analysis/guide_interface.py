"""Export the native IP's continuous bare guide without source generation.

This provider API consumes an explicit resolved model and caller-verified frozen
input identities. It reads no files, changes no coordinates in the input, and
does not export the HP/LP metal, gas bath or numerical PA boundary as hardware.
"""
from __future__ import annotations

import copy
import itertools
import math
import re
from typing import Any

from common.contracts.rigid_transform import FramedPosition, RigidTransform
from common.ion_release.release import validate_release_spec
from common.multipole.round_rod_geometry import build_rod_array


MULTIPOLE_FRAME_ID = "multipole_cartesian_z_axis_v1"
# Native x becomes axial z; native y,z become transverse x,y. Proper rotation.
NATIVE_TO_MULTIPOLE_ROTATION = ((0, 1, 0), (0, 0, 1), (1, 0, 0))
_CSG_TOLERANCE_MM = 1e-12  # Float roundoff in the provider's circular layout.


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def _close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=_CSG_TOLERANCE_MM):
        raise ValueError(f"guide CSG {label} differs from the declared continuous rods")


def _identities(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"resolved_model", "source_spec", "release_csv"}:
        raise ValueError("guide input identities require resolved_model/source_spec/release_csv")
    for name, record in value.items():
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
            raise ValueError(f"{name} identity fields differ")
        if not isinstance(record["path"], str) or not record["path"].strip():
            raise ValueError(f"{name} identity path is missing")
        if type(record["bytes"]) is not int or record["bytes"] <= 0:
            raise ValueError(f"{name} identity bytes must be positive")
        if not isinstance(record["sha256"], str) or re.fullmatch(r"[0-9A-Fa-f]{64}", record["sha256"]) is None:
            raise ValueError(f"{name} identity SHA-256 differs")
    return copy.deepcopy(value)


def _guide_solids(projection: dict[str, Any]) -> list[dict[str, Any]]:
    if type(projection.get("schema_version")) is not int or projection["schema_version"] != 1 or projection.get("role") != "native_electrode_geometry_projection":
        raise ValueError("unsupported native guide projection schema")
    electrodes = projection["electrodes"]
    ids = [item["electrode_id"] for item in electrodes]
    if len(ids) != len(set(ids)):
        raise ValueError("native projection has duplicate electrode IDs")
    by_id = {item["electrode_id"]: item for item in electrodes}
    solids = []
    fields = {"shape", "x_min_mm", "x_max_mm", "center_y_mm", "center_z_mm", "radius_mm"}
    for group, name in ((1, "guide_positive"), (2, "guide_negative")):
        electrode = by_id[group]
        if set(electrode) != {"electrode_id", "name", "solids", "cutouts"} or electrode["name"] != name:
            raise ValueError("native guide electrode identity differs")
        if electrode["cutouts"] != [] or len(electrode["solids"]) != 4:
            raise ValueError("bare guide requires four continuous uncut rods per RF group")
        for solid in electrode["solids"]:
            if set(solid) != fields or solid["shape"] != "cylinder_x":
                raise ValueError("unsupported native guide solid")
            for key in fields - {"shape"}:
                _number(solid[key], key, positive=key == "radius_mm")
            solids.append({**solid, "electrode_group": group})
    return solids


def _rod_array(solids: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    first = solids[0]
    radius = float(first["radius_mm"])
    r0 = math.hypot(first["center_y_mm"], first["center_z_mm"]) - radius
    array = build_rod_array(
        radial_order_n=4, electrode_count=8, inscribed_radius_r0_mm=r0,
        rod_radius_mm=radius, rod_z_min_mm=first["x_min_mm"], rod_z_max_mm=first["x_max_mm"],
    )
    g, n = baseline["geometry"], baseline["native_geometry"]
    if type(g["guide_order"]) is not int or g["guide_order"] != 4:
        raise ValueError("bare guide interface supports the native eight-rod topology only")
    _close(array["inscribed_radius_r0"], _number(g["guide_r0_mm"], "guide r0", positive=True), "r0")
    _close(radius, _number(n["guide_rod_radius_mm"], "guide rod radius", positive=True), "radius")
    _close(first["x_min_mm"], 0, "upstream endpoint")
    length = _number(g["guide_length_mm"], "guide length", positive=True)
    gap = _number(n["guide_rod_end_gap_mm"], "guide end gap")
    if gap < 0:
        raise ValueError("guide end gap must be nonnegative")
    _close(first["x_max_mm"], length - gap, "downstream endpoint")
    remaining = list(solids)
    for rod in array["rods"]:
        matches = [item for item in remaining if item["electrode_group"] == rod["electrode_group"]
                   and math.isclose(item["center_y_mm"], rod["center_x_mm"], rel_tol=0, abs_tol=_CSG_TOLERANCE_MM)
                   and math.isclose(item["center_z_mm"], rod["center_y_mm"], rel_tol=0, abs_tol=_CSG_TOLERANCE_MM)]
        if len(matches) != 1:
            raise ValueError("native guide positions or alternating RF groups differ")
        match = matches[0]
        for original, canonical in (("x_min_mm", "z_min_mm"), ("x_max_mm", "z_max_mm"), ("radius_mm", "radius_mm")):
            _close(match[original], rod[canonical], original)
        remaining.remove(match)
        rod.update(physical_electrode_id=rod["rod_id"], source_electrode_id=rod["electrode_group"])
    return array


def _source_envelope(source: dict[str, Any], transform: RigidTransform) -> dict[str, list[float]]:
    geometry = source["geometry"]
    center = geometry["center_mm"]
    half = [geometry["height_mm"] / 2, geometry["radius_mm"], geometry["radius_mm"]]
    # This fixed proper permutation maps the cylinder AABB exactly; no release
    # states are generated, propagated, selected, or recentered.
    corners = [transform.transform_position(FramedPosition(transform.from_frame_id, point)).coordinates_mm
               for point in itertools.product(*[(c-h, c+h) for c, h in zip(center, half)])]
    return {"min_mm": [min(p[a] for p in corners) for a in range(3)],
            "max_mm": [max(p[a] for p in corners) for a in range(3)]}


def export_guide_contract(resolved_model: dict[str, Any], input_identities: dict[str, Any]) -> dict[str, Any]:
    """Return schema-1 continuous bare rods, original drive, and proper mapping.

    Input identities are validated structurally, not read or rehashed here; the
    consuming preparation boundary must verify their frozen bytes. Unknown
    guide geometry/schema or gas-profile fields raise ValueError. The vacuum
    rule is this provider's native runtime policy: gas acts only from HP onward.
    No promise of equal fields follows from copying rods into a new assembly.
    """
    identities = _identities(input_identities)
    baseline = resolved_model["baseline"]
    if type(baseline.get("schema_version")) is not int or baseline["schema_version"] != 1:
        raise ValueError("unsupported IP baseline schema")
    source = resolved_model["source"]
    validate_release_spec(source)
    projection = resolved_model["native_projection"]
    frame = baseline["clock"]["frame_id"]
    if source["frame_id"] != frame or projection["frame_id"] != frame:
        raise ValueError("native guide/source frame differs")
    if source["geometry"].get("shape") != "cylinder" or source["geometry"].get("axis") != "x":
        raise ValueError("native guide source axis must be +x")
    gas_fields = {"temperature_k", "mass_amu", "hp_pressure_pa", "lp_pressure_pa", "cross_section_m2", "mean_free_path_mm"}
    if set(baseline["gas"]) != gas_fields:
        raise ValueError("unsupported guide gas profile; native guide must remain vacuum")
    for key, value in baseline["gas"].items():
        number = _number(value, key)
        if key != "mean_free_path_mm" and number < 0:
            raise ValueError("gas bath parameters cannot be negative")
    array = _rod_array(_guide_solids(projection), baseline)
    electric, clock = baseline["electric"], baseline["clock"]
    transform = RigidTransform(frame, MULTIPOLE_FRAME_ID, NATIVE_TO_MULTIPOLE_ROTATION, (0, 0, 0))
    return {
        "schema_version": 1, "role": "ion_processor_bare_guide_interface",
        "provider_project_id": "dual_pressure_rectilinear_ion_processor",
        "inputs": identities, "input_identity_validation": "structure_only__caller_must_verify_frozen_bytes",
        "coordinate_transform": transform.to_contract(), "frame_id": MULTIPOLE_FRAME_ID,
        "length_unit": "mm", "rod_array": array,
        "source_envelope_bounds_mm": _source_envelope(source, transform),
        "source_particle_count": source["particle_count"],
        "mother_particle_count": source["mother_particle_count"],
        "drive": {
            "waveform": "cosine", "frequency_hz": _number(electric["rf_frequency_hz"], "RF frequency", positive=True),
            "phase_rad": _number(clock["rf_phase_rad"], "RF phase"),
            "rf_amplitude_v": _number(electric["guide_rf_peak_to_peak_v"], "guide Vpp", positive=True) / 2,
            "group_dc_v": [0.0, 0.0],
            "common_mode_v": _number(resolved_model["native_operating_point"]["guide_offset_v"], "guide offset"),
            "group_polarities": {"1": 1, "2": -1},
        },
        "clock": {"epoch_us": _number(clock["epoch_us"], "clock epoch"), "spatial_mapping_changes_time": False},
        "vacuum": {"pressure_pa": 0.0, "collision_model": "none", "policy_id": "native_guide_before_hp_vacuum_v1"},
        "mechanical_components": {"shield": False, "entrance_plate": False, "exit_plate": False, "reference_sleeve": False},
        "guide_exit_surface": {"center_mm": [0.0, 0.0, array["rods"][0]["z_max_mm"]], "normal": [0, 0, 1]},
        "numerical_boundary_semantics": "not_exported_as_mechanical_metal__consumer_must_declare_new_domain",
        "claim": "same_eight_continuous_rods_and_drive__new_assembly_fields_require_solving",
    }


def export_guide_assembly_interface(guide: dict[str, Any]) -> dict[str, Any]:
    """Publish mechanical registration and rod identities from a guide contract.

    Input must be the provider's already verified export_guide_contract output.
    No files, particle states, voltages or clocks are produced. The exit's open
    rod envelope is a geometry scale, not a plate aperture or acceptance cut.
    """
    if guide.get("schema_version") != 1 or guide.get("role") != "ion_processor_bare_guide_interface":
        raise ValueError("guide assembly interface requires the native bare-guide contract")
    rods = guide["rod_array"]["rods"]
    identities = [rod["physical_electrode_id"] for rod in rods]
    if len(identities) != len(set(identities)) or not identities:
        raise ValueError("guide assembly interface requires distinct physical rod identities")
    radius = _number(guide["rod_array"]["inscribed_radius_r0"], "rod clear envelope", positive=True)
    return {
        "schema_version": 1,
        "role": "component_geometry_interface",
        "project_id": guide["provider_project_id"],
        "variant_id": "continuous_bare_octupole_guide",
        "geometry_profile_id": None,
        "local_frame_id": guide["frame_id"],
        "length_unit": "mm",
        "ports": {"guide_exit": {
            "surface_kind": "open_rod_exit",
            "center_mm": list(guide["guide_exit_surface"]["center_mm"]),
            "outward_normal": list(guide["guide_exit_surface"]["normal"]),
            "cross_section": {"shape": "open_rod_envelope", "inscribed_radius_mm": radius},
            "wall_thickness_mm": None,
        }},
        "component_electrodes": [
            {"component_electrode_id": rod["physical_electrode_id"],
             "role": f"guide_rod_{rod['physical_electrode_id']}",
             "electrical_group_id": rod["source_electrode_id"]}
            for rod in rods
        ],
    }
