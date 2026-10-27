"""Solver-free checks for integration discovery source layouts."""

from __future__ import annotations

import copy
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema


class IntegrationRegistryTests(unittest.TestCase):
    def _registry(self, root: str) -> dict:
        return {
            "schema_version": 1,
            "role": "integration_registry",
            "integrations": [{
                "integration_id": "instrument_assembly",
                "root": root,
                "profile_registry": f"{root}/config/connections.json",
            }],
        }

    def test_direct_and_family_source_roots_accept_explicit_owner(self) -> None:
        for root in ("integrations", "integrations/active_family"):
            with self.subTest(root=root):
                registry = self._registry(root)
                validate_schema(registry, "integration_registry.schema.json")

    def test_direct_and_family_layouts_cannot_be_mixed(self) -> None:
        for root, other in (
            ("integrations", "integrations/active_family"),
            ("integrations/active_family", "integrations"),
        ):
            for field in ("profile_registry",):
                with self.subTest(root=root, field=field):
                    registry = self._registry(root)
                    registry["integrations"][0][field] = f"{other}/config/profiles.json"
                    with self.assertRaises(ContractError):
                        validate_schema(registry, "integration_registry.schema.json")

    def test_paths_reject_traversal_absolute_and_unregistered_shapes(self) -> None:
        valid = self._registry("integrations")
        for field, values in {
            "root": ("../integrations", "integrations/../other", "integrations/", "projects/example"),
            "profile_registry": (
                "integrations/config/../profiles.json",
                "integrations/config/sub/profiles.json",
                "C:/integrations/config/profiles.json",
                "/integrations/config/profiles.json",
                "integrations\\config\\profiles.json",
            ),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    registry = copy.deepcopy(valid)
                    registry["integrations"][0][field] = value
                    with self.assertRaises(ContractError):
                        validate_schema(registry, "integration_registry.schema.json")


if __name__ == "__main__":
    unittest.main()
