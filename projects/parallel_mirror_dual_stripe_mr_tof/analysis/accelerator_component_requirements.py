"""MR's non-topological request projection for the accelerator provider."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
)


def _provider_two_zone_axial_length_mm() -> float:
    """Read the sealed two-zone length from the provider's active profile.

    MR retains the global exit anchor, but it does not own the gap dimensions.
    Reading the provider contract here lets the legacy split-PA projection use
    the same resolved repeller-to-exit distance as the provider GEM.
    """
    profile_path = (
        Path(__file__).resolve().parents[2]
        / "orthogonal_accelerator"
        / "config"
        / "component_contract.json"
    )
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))["geometry_profiles"][
            "closed_two_zone_compact_mr_axial_r3_gap1_4mm"
        ]
        length = float(profile["gap_1_mm"]) + float(profile["gap_2_mm"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CandidateContractError("provider active two-zone axial profile is unavailable") from error
    if length <= 0.0:
        raise CandidateContractError("provider active two-zone axial length must be positive")
    return length


def build_two_zone_accelerator_requirements(contract: dict[str, Any]) -> dict[str, object]:
    """Return only source, focus, numerical-envelope and placement requirements."""
    accelerator = contract["accelerator"]
    mesh = contract["simion"]["component_mesh_mm_per_gu"]["accelerator"]
    span = contract["simion"]["accelerator_pa_span_mm"]
    if not isinstance(mesh, list) or not isinstance(span, list) or len(mesh) != 3 or len(span) != 3:
        raise CandidateContractError("accelerator PA mesh and span must have three values")
    margin_z = float(accelerator["pa_local_margin_z_mm"])
    if margin_z <= 0.0:
        raise CandidateContractError("accelerator.pa_local_margin_z_mm must be positive")
    source = accelerator["component_source_cylinder"]
    placement = derive_two_zone_placement(contract)
    provider_axial_length = _provider_two_zone_axial_length_mm()
    return {
        "schema_version": 1,
        "role": "orthogonal_accelerator_two_zone_requirements",
        "variant_id": "two_zone",
        "acceleration_direction": "-z",
        "source_cylinder": {"radius_mm": source["radius_mm"], "height_mm": source["height_mm"]},
        "focus": {"mode": "two_zone_time_focus", "focus_plane": accelerator["focus_plane"]},
        "compaction": {"axes": ["y", "z"], "objective": "minimize_subject_to_focus"},
        "local_pa": {"span_mm": span, "mesh_mm_per_gu": mesh, "exit_z_mm": margin_z, "margin_z_mm": margin_z},
        "placement": {
            "focus_y_mm": placement.focus_y_mm,
            "global_repeller_z_mm": placement.exit_grid_z_mm + provider_axial_length,
            "global_exit_z_mm": placement.exit_grid_z_mm,
        },
    }
