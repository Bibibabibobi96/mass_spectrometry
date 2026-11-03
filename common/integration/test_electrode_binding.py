"""Scoped electrode coverage and explicit version dispatch; no native solve."""
from __future__ import annotations

import copy
import unittest

from common.integration.test_resolve_assembly import direct_fixture
from msplatform.assembly.electrode_binding import ElectrodeKey, validate_electrode_bindings
from msplatform.assembly.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from msplatform.contracts.machine_contracts import ContractError, validate_schema


def fixture() -> tuple[dict, dict, dict, dict]:
    """Use the existing layout fixture for schema/coverage unit tests only."""
    recipe, interfaces = direct_fixture()
    for interface in interfaces.values():
        interface["schema_version"] = 2
        interface["component_electrodes"] = [dict(component_electrode_id="electrode", role="boundary")]
    inputs = {key: dict(path=key + "/resolved.json", sha256="A" * 64) for key in interfaces}
    bindings = dict(schema_version=1, role="backend_electrode_bindings", backend="fixture_backend",
                    field_domain_id="parent", provider_inputs=copy.deepcopy(inputs), bindings=[
        dict(instance_id=key, scientific_id="electrode", native_selection="named_selection") for key in interfaces])
    return recipe, interfaces, inputs, bindings


class ElectrodeBindingTests(unittest.TestCase):
    def test_instance_scope_and_opaque_backend_targets(self):
        _, interfaces, inputs, bindings = fixture()
        validate_electrode_bindings(interfaces, bindings, field_domain_id="parent", provider_inputs=inputs)
        self.assertNotEqual(ElectrodeKey("guide", "electrode"), ElectrodeKey("oa", "electrode"))
        bindings["bindings"].reverse()
        validate_electrode_bindings(dict(reversed(list(interfaces.items()))), bindings,
                                    field_domain_id="parent", provider_inputs=inputs)

    def test_missing_extra_duplicate_and_wrong_provider_fail(self):
        _, interfaces, inputs, original = fixture()
        cases = []
        missing = copy.deepcopy(original); missing["bindings"].pop(); cases.append(missing)
        extra = copy.deepcopy(original); extra["bindings"].append(dict(instance_id="unknown", scientific_id="electrode")); cases.append(extra)
        duplicate = copy.deepcopy(original); duplicate["bindings"].append(copy.deepcopy(duplicate["bindings"][0])); cases.append(duplicate)
        stale = copy.deepcopy(original); stale["provider_inputs"]["guide"]["sha256"] = "B" * 64; cases.append(stale)
        domain = copy.deepcopy(original); domain["field_domain_id"] = "other"; cases.append(domain)
        for broken in cases:
            with self.subTest(broken=broken), self.assertRaises(ContractError):
                validate_electrode_bindings(interfaces, broken, field_domain_id="parent", provider_inputs=inputs)

    def test_versions_dispatch_explicitly_and_preserve_old_contracts(self):
        old_recipe, old_interfaces = direct_fixture()
        old = compile_assembly_layout(old_recipe, old_interfaces)
        self.assertEqual(old["schema_version"], 3)
        recipe, interfaces, _, _ = fixture()
        current = compile_assembly_layout(recipe, interfaces)
        self.assertEqual(current["schema_version"], 4)
        self.assertEqual(derive_assembly_scope(current), current)
        local = derive_assembly_scope(current, local_scope=dict(instance_ids=["guide"],
            research_scope="guide only", boundary_assumptions="external downstream boundary"))
        self.assertEqual(local["scope"]["instance_ids"], ["guide"])
        self.assertEqual(local["components"], current["components"])
        self.assertTrue(local["scope"]["boundary_connection_ids"])
        with self.assertRaises(ContractError):
            validate_schema(current, "composition_plan.schema.json")
        with self.assertRaises(ContractError):
            validate_schema(old, "composition_plan_v4.schema.json")
        interfaces["guide"] = old_interfaces["guide"]
        with self.assertRaisesRegex(ContractError, "version"):
            compile_assembly_layout(recipe, interfaces)


if __name__ == "__main__":
    unittest.main()
