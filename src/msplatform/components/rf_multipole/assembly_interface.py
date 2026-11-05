"""Publish RF component3 from a verified scientific resolved document."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from msplatform.contracts.machine_contracts import ContractError, validate_schema
from msplatform.components.rf_multipole.compile_design_request import resolved_design_sha256, validate_resolved_design_contract
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology

def build_assembly_interface(resolved_design: Mapping[str, Any], *, geometry_profile_id: str) -> dict[str, Any]:
    """Publish the frozen real rod/shell faces independently of observations."""
    validate_resolved_design_contract(dict(resolved_design))
    if resolved_design_sha256(resolved_design) != resolved_design["resolved_sha256"]:
        raise ContractError("multipole mechanical interface resolved design hash is stale")
    geometry = resolved_design["geometry_mm"]
    if geometry["enclosure"]["model"] == "rectangular_reference_enclosure_v1":
        raise ContractError("the independent rectangular reference has no bare/shell assembly interface")
    result = dict(schema_version=3, role="component_geometry_interface",
        project_id=resolved_design["identity"]["project_id"],
        variant_id="bare_rods" if geometry["enclosure"]["model"] == "bare" else "cylindrical_grounded_shell",
        geometry_profile_id=geometry_profile_id, local_frame_id=resolved_design["coordinate"]["coordinate_id"],
        length_unit="mm", ports=geometry["enclosure_layout"]["ports"],
        component_electrodes=[dict(electrode_group_id=row['electrode_group_id'], role=row['roles'][0])
                              for row in build_electrode_topology(resolved_design)])
    validate_schema(result, "component_geometry_interface_v3.schema.json")
    return result
