"""Explicit v1 interface adapter for named legacy native consumers.

The active scientific publisher is core.component_port. This adapter preserves
old native identities for request-v9 readers; it is not a second topology.
Exit after those consumers migrate, no later than P4.
"""
from __future__ import annotations

from typing import Any, Mapping

from msplatform.contracts.machine_contracts import validate_schema
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
from msplatform.backends.simion.rf_geometry import physical_electrode_view


def build_legacy_assembly_interface(resolved_design: Mapping[str, Any], *, geometry_profile_id: str,
                                    schema_version: int = 1) -> dict[str, Any]:
    """Read the deployed native interface without redefining scientific IDs."""
    result = build_assembly_interface(resolved_design, geometry_profile_id=geometry_profile_id)
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError("legacy RF interface requires explicit version 1 or 2")
    result["schema_version"] = schema_version
    if schema_version == 1:
        result["component_electrodes"] = [dict(component_electrode_id=row["native_electrode_id"], role=row["scientific_id"])
                                          for row in physical_electrode_view(dict(resolved_design))]
    else:
        result["component_electrodes"] = [dict(component_electrode_id=row["electrode_group_id"], role=row["role"])
                                          for row in result["component_electrodes"]]
    schema = "component_geometry_interface.schema.json" if schema_version == 1 else "component_geometry_interface_v2.schema.json"
    validate_schema(result, schema)
    return result
