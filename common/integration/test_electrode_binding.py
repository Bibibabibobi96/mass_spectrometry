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
    def test_provider_domain_scope_preserves_complete_interface_and_requires_caller_authority(self):
        _, interfaces, inputs, bindings = fixture()
        for interface in interfaces.values():
            interface["schema_version"] = 3
            interface["component_electrodes"] = [
                dict(electrode_group_id="repeller", role="repeller"),
                dict(electrode_group_id="exit_grid", role="exit_grid"),
                dict(electrode_group_id="reflectron_backplate", role="reflectron_backplate"),
            ]
        before = copy.deepcopy(interfaces)
        scope = {instance: ["repeller", "exit_grid"] for instance in interfaces}
        bindings.update(schema_version=2, electrode_group_scope=copy.deepcopy(scope))
        bindings["bindings"] = [dict(instance_id=instance, electrode_group_id=group,
                                     native_selection="opaque_" + group)
                                 for instance in interfaces for group in ("repeller", "exit_grid")]
        validate_electrode_bindings(interfaces, bindings, field_domain_id="parent", provider_inputs=inputs,
                                    electrode_group_scope=scope)
        self.assertEqual(interfaces, before)
        self.assertEqual([row["electrode_group_id"] for row in interfaces["oa"]["component_electrodes"]],
                         ["repeller", "exit_grid", "reflectron_backplate"])
        # The serialized record alone cannot approve omitted downstream groups.
        with self.assertRaisesRegex(ContractError, "record fields"):
            validate_electrode_bindings(interfaces, bindings, field_domain_id="parent", provider_inputs=inputs)
        whole = copy.deepcopy(bindings)
        del whole["electrode_group_scope"]
        with self.assertRaisesRegex(ContractError, "coverage"):
            validate_electrode_bindings(interfaces, whole, field_domain_id="parent", provider_inputs=inputs)
        cases = {}
        cases["missing_group"] = copy.deepcopy(bindings)
        cases["missing_group"]["bindings"].pop()
        cases["extra_downstream"] = copy.deepcopy(bindings)
        cases["extra_downstream"]["bindings"].append(dict(instance_id="oa", electrode_group_id="reflectron_backplate"))
        cases["stale_provider"] = copy.deepcopy(bindings)
        cases["stale_provider"]["provider_inputs"]["oa"]["sha256"] = "B" * 64
        cases["unapproved_scope"] = copy.deepcopy(bindings)
        cases["unapproved_scope"]["electrode_group_scope"]["oa"] = ["repeller"]
        cases["alias"] = copy.deepcopy(bindings)
        cases["alias"]["bindings"][0]["scientific_id"] = "repeller"
        cases["unknown_version"] = copy.deepcopy(bindings)
        cases["unknown_version"]["schema_version"] = 3
        cases["missing_record_scope"] = whole
        for name, bad in cases.items():
            with self.subTest(case=name), self.assertRaises(ContractError):
                validate_electrode_bindings(interfaces, bad, field_domain_id="parent", provider_inputs=inputs,
                                            electrode_group_scope=scope)

    def test_scope_rejects_invalid_instance_and_group_selections_and_legacy_version(self):
        _, interfaces, inputs, legacy = fixture()
        original = copy.deepcopy(legacy)
        for interface in interfaces.values():
            interface["schema_version"] = 3
            interface["component_electrodes"] = [dict(electrode_group_id="electrode", role="boundary")]
        original["schema_version"] = 2
        for row in original["bindings"]:
            row["electrode_group_id"] = row.pop("scientific_id")
        valid = {instance: ["electrode"] for instance in interfaces}
        selections = [None, [], ["electrode", "electrode"], ["unknown"], [True], [1], [""], "electrode"]
        for selected in selections:
            bad = copy.deepcopy(valid)
            bad["oa"] = selected
            record = dict(original, electrode_group_scope=copy.deepcopy(bad))
            with self.subTest(selected=selected), self.assertRaises(ContractError):
                validate_electrode_bindings(interfaces, record, field_domain_id="parent", provider_inputs=inputs,
                                            electrode_group_scope=bad)
        for bad in ({"oa": ["electrode"]}, dict(valid, unknown=["electrode"]), []):
            with self.subTest(scope=bad), self.assertRaises(ContractError):
                validate_electrode_bindings(interfaces, dict(original, electrode_group_scope=bad),
                                            field_domain_id="parent", provider_inputs=inputs, electrode_group_scope=bad)
        _, old_interfaces, _, _ = fixture()
        for record, supplied in ((legacy, None), (dict(legacy, electrode_group_scope=valid), None),
                                 (dict(legacy, electrode_group_scope=valid), valid)):
            if supplied is None and record is legacy:
                validate_electrode_bindings(old_interfaces, record, field_domain_id="parent", provider_inputs=inputs)
            else:
                with self.assertRaises(ContractError):
                    validate_electrode_bindings(old_interfaces, record, field_domain_id="parent", provider_inputs=inputs,
                                                electrode_group_scope=supplied)

    def test_current_groups_use_component_three_plan_five_and_binding_two(self):
        recipe, interfaces, inputs, bindings = fixture()
        for interface in interfaces.values():
            interface["schema_version"] = 3
            interface["component_electrodes"] = [dict(electrode_group_id="electrode", role="boundary")]
        bindings["schema_version"] = 2
        for row in bindings["bindings"]:
            row["electrode_group_id"] = row.pop("scientific_id")
        validate_electrode_bindings(interfaces, bindings, field_domain_id="parent", provider_inputs=inputs)
        plan = compile_assembly_layout(recipe, interfaces)
        self.assertEqual(plan["schema_version"], 5)
        self.assertEqual(derive_assembly_scope(plan), plan)
        with self.assertRaises(ContractError):
            validate_schema(plan, "composition_plan_v4.schema.json")
        for field in ("scientific_id", "component_electrode_id", "electrical_group_id"):
            bad = copy.deepcopy(bindings)
            bad["bindings"][0][field] = "electrode"
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, "aliases"):
                validate_electrode_bindings(interfaces, bad, field_domain_id="parent", provider_inputs=inputs)
        legacy = copy.deepcopy(interfaces)
        legacy["guide"]["schema_version"] = 2
        with self.assertRaises(ContractError):
            compile_assembly_layout(recipe, legacy)

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
