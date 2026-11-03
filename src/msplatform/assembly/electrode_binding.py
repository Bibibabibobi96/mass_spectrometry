"""Validate scoped scientific electrodes without interpreting backend slots.

Providers own local groups. A binding records the caller's already frozen
provider input identities; this module neither invents hashes nor opens paths.
Native slot/selection validity belongs to the selected backend adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from msplatform.contracts.machine_contracts import ContractError, validate_schema


@dataclass(frozen=True, order=True)
class ElectrodeKey:
    """An instance-scoped scientific group, independent of native numbering."""

    instance_id: str
    scientific_id: str


def validate_electrode_bindings(
    interfaces: Mapping[str, Mapping[str, Any]], bindings: Mapping[str, Any], *,
    field_domain_id: str, provider_inputs: Mapping[str, Any],
) -> None:
    """Check exact v2 group coverage, domain and existing provider identities.

    ``provider_inputs`` is supplied from the caller's actual frozen input
    records. Backend-specific fields on each row are intentionally opaque.
    Missing/extra/duplicate keys and stale provider records raise ContractError.
    """
    if not isinstance(field_domain_id, str) or not field_domain_id:
        raise ContractError("field_domain_id must be explicit and nonempty")
    required = {"schema_version", "role", "backend", "field_domain_id", "provider_inputs", "bindings"}
    if not isinstance(bindings, Mapping) or set(bindings) != required:
        raise ContractError("backend electrode binding record fields differ")
    if (type(bindings["schema_version"]) is not int or bindings["schema_version"] != 1
            or bindings["role"] != "backend_electrode_bindings"
            or not isinstance(bindings["backend"], str) or not bindings["backend"]):
        raise ContractError("unsupported backend electrode binding record")
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
        validate_schema(dict(interface), "component_geometry_interface_v2.schema.json")
        local = [row["component_electrode_id"] for row in interface["component_electrodes"]]
        if len(local) != len(set(local)):
            raise ContractError("provider scientific electrode identities are duplicated")
        expected.update(ElectrodeKey(instance_id, key) for key in local)
    rows = bindings["bindings"]
    if not isinstance(rows, list):
        raise ContractError("backend electrode bindings must be an explicit array")
    actual = set()
    for row in rows:
        if (not isinstance(row, Mapping) or not all(isinstance(row.get(key), str) and row[key]
                for key in ("instance_id", "scientific_id"))):
            raise ContractError("electrode binding must declare instance_id and scientific_id")
        key = ElectrodeKey(row["instance_id"], row["scientific_id"])
        if key in actual:
            raise ContractError("duplicate scoped scientific electrode binding")
        actual.add(key)
    if actual != expected:
        raise ContractError(f"electrode binding coverage differs: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
