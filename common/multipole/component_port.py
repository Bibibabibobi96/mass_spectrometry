"""Compile a provided multipole exit port from one frozen resolved design."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.compile_design_request import resolved_design_sha256


def _exit_potential(resolved: Mapping[str, Any]) -> float:
    static = resolved["static_electrodes_V"]
    if static["role"] == "cylindrical_shield_static_electrodes":
        return float(static["exit_outer_endcap_aperture_plate_connector_V"])
    if static["role"] == "rectangular_reference_static_electrodes":
        return float(static["exit_outer_enclosure_and_connector_V"])
    raise ContractError("resolved design has an unsupported static-electrode role")


def build_exit_component_port(
    resolved_design: Mapping[str, Any],
    *,
    design_profile_id: str,
    authority_path: str,
    authority_sha256: str,
) -> dict[str, Any]:
    """Return a schema-valid provided port bound to one artifact authority.

    ``authority_path`` is workspace-relative and points to the exact resolved
    design frozen by the source run.  No operating-mode geometry or voltage is
    repeated outside that authority.
    """
    resolved = dict(resolved_design)
    validate_schema(resolved, "multipole_resolved_design.schema.json")
    if resolved_design_sha256(resolved) != resolved["resolved_sha256"]:
        raise ContractError("multipole exit-port resolved design hash is stale")
    exit_interface = resolved["interfaces_mm"]["exit"]
    port = {
        "schema_version": 1,
        "role": "component_port",
        "project_id": resolved["identity"]["project_id"],
        "port_id": "rf_multipole_exit",
        "direction": "provided",
        "profile_scope": {
            "scope_id": design_profile_id,
            "scope_kind": "design_profile",
            "family_experiment_port": True,
        },
        "authority": {
            "source_contract": authority_path,
            "source_sha256": authority_sha256,
            "bindings": [
                {
                    "port_json_pointer": "/project_id",
                    "source_json_pointer": "/identity/project_id",
                },
                {
                    "port_json_pointer": "/mating_surface/center_mm/2",
                    "source_json_pointer": "/interfaces_mm/exit/handoff_plane_z_mm",
                },
                {
                    "port_json_pointer": "/mating_surface/aperture_radius_mm",
                    "source_json_pointer": "/interfaces_mm/exit/aperture_radius_mm",
                },
            ],
        },
        "state_contract": {
            "schema_id": "component_particle_state",
            "schema_version": 1,
        },
        "coordinate_frame": {
            "frame_id": "multipole_cartesian_z_axis_v1",
            "length_unit": "mm",
            "handedness": "right_handed",
        },
        "mating_surface": {
            "center_mm": [0.0, 0.0, float(exit_interface["handoff_plane_z_mm"])],
            "outward_normal": [0.0, 0.0, 1.0],
            "aperture_radius_mm": float(exit_interface["aperture_radius_mm"]),
            "potential_V": _exit_potential(resolved),
        },
        "clock": {"time_unit": "s", "origin_id": "instrument_clock_epoch_v1"},
        "field_boundary": {"field_reaches_surface": True},
    }
    # The potential binding pointer depends on the resolved static-electrode role.
    potential_pointer = (
        "/static_electrodes_V/exit_outer_endcap_aperture_plate_connector_V"
        if resolved["static_electrodes_V"]["role"]
        == "cylindrical_shield_static_electrodes"
        else "/static_electrodes_V/exit_outer_enclosure_and_connector_V"
    )
    port["authority"]["bindings"].append(
        {
            "port_json_pointer": "/mating_surface/potential_V",
            "source_json_pointer": potential_pointer,
        }
    )
    validate_schema(port, "component_port.schema.json")
    return port
