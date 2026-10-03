"""Derive the native full-flight corridor from the resolved MR-TOF geometry."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


def _numbers(value: object, label: str, count: int) -> list[float]:
    if not isinstance(value, list) or len(value) != count:
        raise CandidateContractError(f"{label} must contain {count} numeric values")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _grid_shape(box: list[float], mesh: list[float]) -> list[int]:
    shape: list[int] = []
    for axis in range(3):
        cells = (box[axis + 3] - box[axis]) / mesh[axis]
        rounded = round(cells)
        if abs(cells - rounded) > 1e-8:
            raise CandidateContractError("native corridor extent is not aligned to its mesh")
        shape.append(int(rounded) + 1)
    return shape


def _native_settings(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        settings = contract["simion"]["native_corridor"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("native corridor settings are missing") from error
    if not isinstance(settings, Mapping):
        raise CandidateContractError("native corridor settings must be an object")
    return settings


def _native_mapping(settings: Mapping[str, Any]) -> tuple[dict[str, int], list[int]]:
    groups = settings.get("response_voltage_groups")
    fixed = settings.get("fixed_zero_electrode_ids")
    if not isinstance(groups, list) or len(groups) != 8 or not isinstance(fixed, list):
        raise CandidateContractError("native corridor response groups are invalid")
    mapping: dict[str, int] = {}
    for local_id, group in enumerate(groups, start=1):
        if not isinstance(group, list) or not group:
            raise CandidateContractError("native corridor response group is empty")
        for physical_id in group:
            if type(physical_id) is not int or not 1 <= physical_id <= 20 or str(physical_id) in mapping:
                raise CandidateContractError("native corridor response group IDs are invalid")
            mapping[str(physical_id)] = local_id
    fixed_ids = [int(value) for value in fixed]
    if len(set(fixed_ids)) != len(fixed_ids) or any(not 1 <= value <= 20 for value in fixed_ids):
        raise CandidateContractError("native corridor fixed-zero IDs are invalid")
    if set(mapping) & set(map(str, fixed_ids)) or set(mapping) | set(map(str, fixed_ids)) != {str(value) for value in range(1, 21)}:
        raise CandidateContractError("native corridor mapping must cover physical IDs 1..20")
    for physical_id in fixed_ids:
        mapping[str(physical_id)] = 0
    return mapping, fixed_ids


def derive_native_corridor_plan(contract_path: Path) -> dict[str, Any]:
    """Return the direct, current native corridor plan without local patches."""
    contract = load_contract(contract_path)
    settings = _native_settings(contract)
    resolved = resolve_geometry(contract)
    mesh = _numbers(settings.get("mesh_mm_per_gu"), "native corridor mesh", 3)
    surface_mode = settings.get("surface_mode")
    if surface_mode not in {"none", "fractional"}:
        raise CandidateContractError("native corridor surface mode must be none or fractional")
    margin = _numbers(settings.get("margin_mm"), "native corridor margin", 3)
    if any(value <= 0.0 for value in mesh) or any(value < 0.0 for value in margin):
        raise CandidateContractError("native corridor mesh/margin must be nonnegative and nonzero")
    slot = _numbers(resolved.get("mirror_slot"), "resolved mirror slot", 6)
    if settings.get("x_envelope_rule") != "x_mirrored_positive_half_beam_slot_and_prism_ground_shield_extent_plus_margin":
        raise CandidateContractError("native corridor x envelope rule differs")
    if settings.get("mirror_axes") != ["x"]:
        raise CandidateContractError("native corridor must use the qualified x mirror plane")
    x_edges = [slot[0], slot[3]]
    shields = resolved.get("prism_ground_shields")
    if not isinstance(shields, list) or not shields:
        raise CandidateContractError("native corridor Prism ground shields are missing")
    for shield in shields:
        if not isinstance(shield, Mapping):
            raise CandidateContractError("native corridor Prism ground shield is invalid")
        sections = shield.get("body_sections")
        if not isinstance(sections, list) or not sections:
            raise CandidateContractError("native corridor Prism ground-shield body sections are missing")
        for section in sections:
            if not isinstance(section, Mapping):
                raise CandidateContractError("native corridor Prism ground-shield body section is invalid")
            x_edges.extend(_numbers(section.get("x"), "native corridor Prism ground-shield x interval", 2))
    x_half_span = max(abs(value) for value in x_edges) + margin[0]
    roles = settings.get("yz_envelope_geometry_roles")
    if not isinstance(roles, list) or not roles:
        raise CandidateContractError("native corridor y/z geometry roles are missing")
    boxes: list[list[float]] = []
    for role in roles:
        values = resolved.get(str(role))
        if not isinstance(values, list):
            raise CandidateContractError(f"native corridor geometry role is missing: {role}")
        for item in values:
            if not isinstance(item, Mapping):
                raise CandidateContractError(f"native corridor geometry entry is invalid: {role}")
            boxes.append(_numbers(item.get("box"), f"native corridor {role} box", 6))
    if not boxes:
        raise CandidateContractError("native corridor has no geometry envelope")
    box = [
        0.0, min(item[1] for item in boxes) - margin[1], min(item[2] for item in boxes) - margin[2],
        x_half_span, max(item[4] for item in boxes) + margin[1], max(item[5] for item in boxes) + margin[2],
    ]
    shape = _grid_shape(box, mesh)
    mapping, fixed_ids = _native_mapping(settings)
    bytes_per_point = int(settings.get("storage_bytes_per_grid_point_estimate", 0))
    if bytes_per_point <= 0:
        raise CandidateContractError("native corridor storage estimate must be positive")
    points = math.prod(shape)
    family_bytes = points * 10 * bytes_per_point
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_full_flight_native_corridor",
        "status": "candidate__not_flown",
        "box_project_mm": box,
        "mesh_mm_per_gu": mesh,
        "surface_mode": surface_mode,
        "mirror_axes": ["x"],
        "grid_shape": shape,
        "bytes_per_grid_point_estimate": bytes_per_point,
        "grid_points_per_array": points,
        "family_bytes": family_bytes,
        "parity_bytes": 0,
        "staging_worker_bytes": 0,
        "peak_additional_bytes": family_bytes,
        "response_ids": list(range(1, 9)),
        "corridor_electrode_namespace": "local_response_ids_1_to_8",
        "native_family_members": 10,
        "physical_to_local_electrode_id": mapping,
        "fixed_zero_electrode_ids": fixed_ids,
        "derivation": "resolved_x_symmetric_positive_half_beam_slot_and_prism_ground_shield_extent_plus_mirror_conductor_yz_envelopes_and_native_margin",
        "qualification": "planning_only__no_corridor_pa_built_or_flown",
    }
