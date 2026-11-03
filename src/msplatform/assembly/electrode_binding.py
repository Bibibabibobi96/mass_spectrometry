"""Validate scoped scientific electrodes without interpreting backend slots.

Providers own local groups. A binding records the caller's already frozen
provider input identities; this module neither invents hashes nor opens paths.
Native slot/selection validity belongs to the selected backend adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from msplatform.contracts.machine_contracts import ContractError, validate_schema


@dataclass(frozen=True, order=True)
class ElectrodeKey:
    """An instance-scoped scientific group, independent of native numbering."""

    instance_id: str
    electrode_group_id: str


def validate_electrode_bindings(
    interfaces: Mapping[str, Mapping[str, Any]], bindings: Mapping[str, Any], *,
    field_domain_id: str, provider_inputs: Mapping[str, Any],
    electrode_group_scope: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """Check declared-format group coverage, domain and frozen provider records.

    ``provider_inputs`` is supplied from the caller's actual frozen input
    records. Backend-specific fields on each row are intentionally opaque.
    Without ``electrode_group_scope`` every interface group is required. A
    caller may supply a provider-derived field-domain selection; the record
    must repeat it exactly and cannot authorize its own reduced coverage.
    The caller must validate domain membership against its frozen provider
    projection; this neutral checker only verifies the declared subset.
    Missing/extra/duplicate keys and stale provider records raise ContractError.
    """
    if not isinstance(field_domain_id, str) or not field_domain_id:
        raise ContractError("field_domain_id must be explicit and nonempty")
    required = {"schema_version", "role", "backend", "field_domain_id", "provider_inputs", "bindings"}
    if electrode_group_scope is not None:
        required.add("electrode_group_scope")
    if not isinstance(bindings, Mapping) or set(bindings) != required:
        raise ContractError("backend electrode binding record fields differ")
    if (type(bindings["schema_version"]) is not int or bindings["schema_version"] not in (1, 2)
            or bindings["role"] != "backend_electrode_bindings"
            or not isinstance(bindings["backend"], str) or not bindings["backend"]):
        raise ContractError("unsupported backend electrode binding record")
    current = bindings["schema_version"] == 2
    if electrode_group_scope is not None:
        if not current:
            raise ContractError("electrode group scope requires backend binding version 2")
        if (not isinstance(electrode_group_scope, Mapping)
                or set(electrode_group_scope) != set(interfaces)):
            raise ContractError("electrode group scope must cover exactly the selected instances")
        if bindings["electrode_group_scope"] != electrode_group_scope:
            raise ContractError("electrode group scope differs from the caller's provider projection")
    component_version = 3 if current else 2
    group_field = "electrode_group_id" if current else "scientific_id"
    interface_field = "electrode_group_id" if current else "component_electrode_id"
    if bindings["field_domain_id"] != field_domain_id:
        raise ContractError("electrode binding field domain differs")
    if not interfaces or set(provider_inputs) != set(interfaces) or any(not value for value in provider_inputs.values()):
        raise ContractError("provider input records must cover exactly the selected instances")
    if bindings["provider_inputs"] != provider_inputs:
        raise ContractError("electrode binding provider input identity differs")
    expected = set()
    for instance_id, interface in interfaces.items():
        if not isinstance(instance_id, str) or not instance_id:
            raise ContractError("electrode instance identity must be a nonempty string")
        if interface.get("schema_version") != component_version:
            raise ContractError("backend binding and component interface versions differ")
        validate_schema(dict(interface), f"component_geometry_interface_v{component_version}.schema.json")
        local = [row[interface_field] for row in interface["component_electrodes"]]
        if len(local) != len(set(local)):
            raise ContractError("provider scientific electrode identities are duplicated")
        if electrode_group_scope is not None:
            selected = electrode_group_scope[instance_id]
            if (not isinstance(selected, Sequence) or isinstance(selected, (str, bytes)) or not selected
                    or any(not isinstance(key, str) or not key for key in selected)
                    or len(selected) != len(set(selected)) or not set(selected) <= set(local)):
                raise ContractError(f"{instance_id}: electrode group scope must be a nonempty unique interface subset")
            local = selected
        expected.update(ElectrodeKey(instance_id, key) for key in local)
    rows = bindings["bindings"]
    if not isinstance(rows, list):
        raise ContractError("backend electrode bindings must be an explicit array")
    actual = set()
    for row in rows:
        aliases = ({"scientific_id", "component_electrode_id", "electrical_group_id"}
                   if current else {"electrode_group_id"})
        if isinstance(row, Mapping) and aliases.intersection(row):
            raise ContractError("electrode binding contains aliases from another format")
        if (not isinstance(row, Mapping) or not all(isinstance(row.get(key), str) and row[key]
                for key in ("instance_id", group_field))):
            raise ContractError(f"electrode binding must declare instance_id and {group_field}")
        key = ElectrodeKey(row["instance_id"], row[group_field])
        if key in actual:
            raise ContractError("duplicate scoped scientific electrode binding")
        actual.add(key)
    if actual != expected:
        raise ContractError(f"electrode binding coverage differs: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
