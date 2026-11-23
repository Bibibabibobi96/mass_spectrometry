"""Solver-free checks for Assembly workflow registry contracts."""

from __future__ import annotations

import copy
import unittest

from msplatform.contracts.machine_contracts import ContractError, validate_schema


class AssemblyRegistryTests(unittest.TestCase):
    def _registry(self) -> dict:
        return {
            "schema_version": 1,
            "role": "assembly_registry",
            "assemblies": [{
                "assembly_id": "instrument_assembly",
                "profile_registry": "src/msplatform/workflows/config/connections.json",
            }],
        }

    def test_canonical_package_registry_is_accepted(self) -> None:
        validate_schema(self._registry(), "assembly_registry.schema.json")

    def test_paths_reject_traversal_absolute_and_unregistered_shapes(self) -> None:
        for value in (
            "src/msplatform/workflows/config/../profiles.json",
            "src/msplatform/workflows/config/sub/profiles.json",
            "C:/src/msplatform/workflows/config/profiles.json",
            "/src/msplatform/workflows/config/profiles.json",
            "src\\msplatform\\workflows\\config\\profiles.json",
            "integrations/config/profiles.json",
        ):
            with self.subTest(value=value):
                registry = copy.deepcopy(self._registry())
                registry["assemblies"][0]["profile_registry"] = value
                with self.assertRaises(ContractError):
                    validate_schema(registry, "assembly_registry.schema.json")

    def test_legacy_registry_names_and_source_root_are_rejected(self) -> None:
        legacy = {
            "schema_version": 1,
            "role": "integration_registry",
            "integrations": [{
                "integration_id": "instrument_assembly",
                "root": "integrations",
            }],
        }
        with self.assertRaises(ContractError):
            validate_schema(legacy, "assembly_registry.schema.json")
        registry = self._registry()
        registry["assemblies"][0]["root"] = "src/msplatform/workflows"
        with self.assertRaises(ContractError):
            validate_schema(registry, "assembly_registry.schema.json")


if __name__ == "__main__":
    unittest.main()
