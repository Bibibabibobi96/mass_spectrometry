"""Static validator for the solver-neutral oaTOF radial-factor matrix."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_SHA256 = re.compile(r"^[A-F0-9]{64}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _changed_fields(left: Mapping[str, Any], right: Mapping[str, Any]) -> set[str]:
    return {key for key in left if key != "id" and left[key] != right[key]}


def validate_radial_factor_matrix(document: Mapping[str, Any]) -> None:
    """Reject authority drift or non-causal arms before any solver execution."""
    _require(document.get("schema_version") == 1, "unsupported schema_version")
    _require(
        document.get("role") == "rf_multipole_oatof_radial_factor_attribution_matrix",
        "unexpected contract role",
    )
    _require(document.get("status") == "planning_only_until_adapter_support", "status must remain planning-only")
    _require(document.get("execution_authorized") is False, "matrix cannot authorize execution")
    _require(
        document.get("existing_execution_entry")
        == "projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/run_campaign.py",
        "matrix must reuse the existing radial_compaction entry",
    )

    frozen = document["frozen_context"]
    for key in ("source_manifest_sha256", "source_state_sha256", "particle_source_sha256"):
        _require(bool(_SHA256.fullmatch(frozen[key])), f"invalid frozen {key}")
    _require(frozen["resolution_time_basis"] == "detector_time_minus_pulse_effective_time", "clock drift")
    _require(frozen["population_basis"] == "all_pulse_eligible_particles", "cohort drift")
    _require(frozen["same_ordered_particle_ids_required"] is True, "paired particle IDs are required")
    _require(frozen["voltage_policy"] == "inherit_one_frozen_base_request_without_overrides", "voltage drift")

    profiles = document["design_profiles"]
    by_id = {row["id"]: row for row in profiles}
    _require(len(by_id) == len(profiles), "design profile IDs must be unique")
    _require(all(row["bore_r_mm"] < row["ring_outer_r_mm"] < row["shield_inner_r_mm"] for row in profiles),
             "radial geometry must be nested")
    _require({row["reflectron_axial_cell_mm"] for row in profiles} == {0.1}, "factor mesh must stay at 0.1 mm")

    contrasts = document["contrasts"]
    shield_rows = [by_id[item] for item in contrasts["shield_only"]]
    _require([row["shield_inner_r_mm"] for row in shield_rows] == [100, 180, 350], "shield sweep drift")
    _require(all(_changed_fields(shield_rows[0], row) <= {"shield_inner_r_mm"} for row in shield_rows[1:]),
             "shield-only contrast changes another factor")

    compact, large = [by_id[item] for item in contrasts["radial_electrode_bundle"]]
    _require(_changed_fields(compact, large) == {"bore_r_mm", "ring_outer_r_mm"}, "bundle contrast drift")
    _require([(compact["bore_r_mm"], compact["ring_outer_r_mm"]),
              (large["bore_r_mm"], large["ring_outer_r_mm"])] == [(35, 70), (250, 300)],
             "bundle radii drift")

    topology = [by_id[item] for item in contrasts["r100_topology_sequence"]]
    _require([(row["stage1_rings"], row["stage2_rings"], row["ring_thickness_mm"]) for row in topology]
             == [(10, 5, 5), (8, 15, 5), (8, 15, 2)], "r100 topology sequence drift")
    _require({(row["bore_r_mm"], row["ring_outer_r_mm"], row["shield_inner_r_mm"]) for row in topology}
             == {(35, 70, 100)}, "r100 topology contrast changes radial geometry")

    anchor = by_id[contrasts["large_anchor"]]
    _require((anchor["bore_r_mm"], anchor["ring_outer_r_mm"], anchor["shield_inner_r_mm"])
             == (250, 300, 350), "large anchor drift")
    _require(document["grid_convergence"]["reflectron_axial_cell_mm"] == [0.2, 0.1, 0.05], "grid ladder drift")
    promotion = document["promotion"]
    _require((promotion["screening_count"], promotion["qualification_count"]) == (100, 1000), "promotion sizes drift")
    _require(promotion["n100_is_ranking_authority"] is False, "N100 cannot rank designs")
    _require(promotion["promotion_requires_all_contrast_arms_complete"] is True, "incomplete contrasts cannot promote")
