"""Build the pulse-before identity used by future verified pulse reuse."""

from __future__ import annotations

import copy
from typing import Any

from common.contracts.file_identity import canonical_json_sha256 as _canonical_sha256


_POPULATION_IDENTITY_KEYS = {
    "campaign_id",
    "experiment_id",
    "experiment_row_sha256",
    "resolved_source_contract_sha256",
    "resolved_population_contract_sha256",
    "mother_particle_source_sha256",
    "ordered_particle_id_sha256",
}
_PROVIDER_QUALITY_KEYS = {
    "field_profile_id",
    "region_field_semantic_sha256",
    "oatof_numerical_profile_id",
    "trajectory_quality_profile_id",
    "time_integration_profile_id",
}
_CONNECTION_KEYS = (
    "selection",
    "spatial_registration",
    "connector",
    "port_geometry",
    "transition_aperture",
    "effective_clear_radius_mm",
    "potential_alignment",
    "clock_alignment",
    "field_ownership_segments",
)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _source_distribution_projection(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("role") != "rf_multipole_oatof_source_contract":
        raise ValueError("resolved source contract identity differs")
    return {
        "upstream_project_id": source.get("upstream_project_id"),
        "selector": copy.deepcopy(_require_mapping(source.get("selector"), "source selector")),
        "canonical_state": copy.deepcopy(
            _require_mapping(source.get("canonical_state"), "canonical source state")
        ),
    }


def _pulse_epoch_geometry_projection(geometry: dict[str, Any]) -> dict[str, Any]:
    if geometry.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("resolved geometry identity differs")
    topology = copy.deepcopy(
        _require_mapping(geometry.get("accelerator_topology"), "accelerator topology")
    )
    topology.pop("potentials_v", None)
    return {
        "coordinate_convention": copy.deepcopy(
            _require_mapping(
                geometry.get("coordinate_convention"), "geometry coordinate convention"
            )
        ),
        "particle_source": copy.deepcopy(
            _require_mapping(geometry.get("particle_source"), "geometry particle source")
        ),
        "accelerator_topology_without_post_pulse_potentials": topology,
    }


def build_verified_pulse_reuse_projection(
    *,
    screening_contract: dict[str, Any],
    resolved_source: dict[str, Any],
    resolved_connection: dict[str, Any],
    resolved_geometry: dict[str, Any],
    spatial_profile: dict[str, Any],
    pa_cache_keys: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return a population- and post-pulse-independent verified reuse identity.

    The input screening contract remains the provider evidence, so its canonical
    pre-pulse integration and trajectory-quality choices are retained. Consumer
    particle count, batching, post-pulse integration, and post-pulse accelerator
    field are intentionally not inputs to this projection.
    """

    if screening_contract.get("role") != (
        "rf_oatof_pre_pulse_time_series_screening_contract"
    ):
        raise ValueError("screening contract identity differs")
    identities = copy.deepcopy(
        _require_mapping(screening_contract.get("identities"), "screening identities")
    )
    provider_quality = {
        key: identities.pop(key)
        for key in sorted(_PROVIDER_QUALITY_KEYS)
        if key in identities
    }
    for key in _POPULATION_IDENTITY_KEYS:
        identities.pop(key, None)
    required_connection = {
        key: copy.deepcopy(resolved_connection[key])
        for key in _CONNECTION_KEYS
        if key in resolved_connection
    }
    if set(required_connection) != set(_CONNECTION_KEYS):
        raise ValueError("resolved connection pulse identity is incomplete")
    frontend_key = pa_cache_keys.get("frontend")
    overlay_key = pa_cache_keys.get("accelerator_overlay")
    if (
        not isinstance(frontend_key, str)
        or not frontend_key
        or not isinstance(overlay_key, str)
        or not overlay_key
        or pa_cache_keys.get("flight_tube") is not None
        or pa_cache_keys.get("reflectron") is not None
    ):
        raise ValueError("pulse reuse requires frontend and accelerator-overlay PA keys only")
    time_grid = copy.deepcopy(
        _require_mapping(screening_contract.get("rf_time_grid"), "RF time grid")
    )
    basis = {
        "schema_version": 1,
        "role": "rf_oatof_verified_pulse_reuse_projection",
        "source_distribution": _source_distribution_projection(resolved_source),
        "connection": required_connection,
        "pulse_epoch_geometry": _pulse_epoch_geometry_projection(resolved_geometry),
        "rf_time_grid": time_grid,
        "selector": {
            "identities": identities,
            "spatial_profile": copy.deepcopy(spatial_profile),
            "selection_order": copy.deepcopy(
                screening_contract.get("selection_order", [])
            ),
        },
        "provider_pre_pulse_evidence": {
            "quality_profiles": provider_quality,
            "pulse_disabled": screening_contract.get("pulse_disabled"),
            "terminate_at_window_end": screening_contract.get(
                "terminate_at_window_end"
            ),
            "resolution_claim_allowed": screening_contract.get(
                "resolution_claim_allowed"
            ),
        },
        "pa_cache_keys": {
            "frontend": frontend_key,
            "accelerator_overlay": overlay_key,
        },
    }
    return basis, _canonical_sha256(basis)
