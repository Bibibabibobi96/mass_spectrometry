"""Enclosure layouts use actual poses/envelopes, never invented mating ports."""
from __future__ import annotations

import copy
import unittest

from msplatform.assembly.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from msplatform.assembly.electrode_binding import validate_electrode_bindings
from msplatform.contracts.machine_contracts import ContractError


def enclosure_fixture():
    def interface(name, bounds, domains):
        return dict(schema_version=4, role="component_geometry_interface", project_id=name,
                    variant_id="three_zone", geometry_profile_id=None, local_frame_id=name + "_local",
                    length_unit="mm", ports={},
                    component_electrodes=[dict(electrode_group_id="ground", role="ground")],
                    material_bounds_mm=bounds, vacuum_domains=domains)
    domain = dict(domain_id="cavity", shape="cylinder", axis="z", center_xy_mm=[0, 0],
                  z_min_mm=-10, z_max_mm=10, radius_mm=10)
    components = {"inner": interface("inner", dict(min=[-1, -1, -1], max=[1, 1, 1]), []),
                  "outer": interface("outer", dict(min=[-11, -11, -11], max=[11, 11, 11]), [domain])}
    instances = [dict(instance_id=name, project_id=name,
                      transform=dict(schema_version=1, role="rigid_transform", from_frame_id=name + "_local",
                                     to_frame_id="world", rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                                     translation_mm=[2, 0, 0] if name == "inner" else [0, 0, 0]))
                 for name in components]
    recipe = dict(schema_version=2, role="assembly_recipe", integration_id="instrument_assembly", recipe_id="nested",
                  assembly_frame_id="world", position_tolerance_mm=1e-9, angular_tolerance_rad=1e-12,
                  instances=instances, connections=[], containments=[dict(relation_id="inner_in_outer",
                      container_instance_id="outer", contained_instance_id="inner", domain_id="cavity",
                      coupling_mode="monolithic_joint_solve")])
    return recipe, components


class ContainmentLayoutTests(unittest.TestCase):
    def test_electrodes_keep_instance_scope_in_version4_enclosures(self):
        _, interfaces = enclosure_fixture()
        records = {name: {"sha256": name} for name in interfaces}
        bindings = dict(schema_version=2, role="backend_electrode_bindings", backend="simion",
                        field_domain_id="world", provider_inputs=records,
                        bindings=[dict(instance_id=name, electrode_group_id="ground", native_id=index)
                                  for index, name in enumerate(interfaces, 1)])
        validate_electrode_bindings(interfaces, bindings, field_domain_id="world", provider_inputs=records)
        bindings["bindings"][1]["instance_id"] = "inner"
        with self.assertRaisesRegex(ContractError, "duplicate"):
            validate_electrode_bindings(interfaces, bindings, field_domain_id="world", provider_inputs=records)

    def test_containment_with_no_mechanical_ports_has_auditable_coordinates(self):
        recipe, components = enclosure_fixture()
        plan = compile_assembly_layout(recipe, components)
        self.assertEqual(plan["schema_version"], 6)
        self.assertEqual(plan["connection_checks"], [])
        self.assertEqual(plan["scope"]["containment_ids"], ["inner_in_outer"])
        check = plan["containment_checks"][0]
        self.assertEqual(check["status"], "contained_in_envelope")
        self.assertEqual({point[0] for point in check["contained_corners_in_container_mm"]}, {1, 3})
        self.assertEqual(derive_assembly_scope(plan), plan)
        original = copy.deepcopy(plan)
        local = derive_assembly_scope(plan, local_scope=dict(instance_ids=["inner"],
            research_scope="local member", boundary_assumptions="parent enclosure retained as boundary evidence"))
        self.assertEqual(local["scope"]["boundary_containment_ids"], ["inner_in_outer"])
        self.assertEqual(plan, original)

    def test_world_rotation_and_translation_preserve_relative_containment(self):
        recipe, components = enclosure_fixture()
        for row in recipe["instances"]:
            row["transform"]["rotation"] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
            row["transform"]["translation_mm"] = [20, 32, 40] if row["instance_id"] == "inner" else [20, 30, 40]
        plan = compile_assembly_layout(recipe, components)
        self.assertEqual({p[0] for p in plan["containment_checks"][0]["contained_corners_in_container_mm"]}, {1, 3})

    def test_invalid_enclosures_relations_and_disconnected_instruments_fail(self):
        def duplicate(r, c):
            r["containments"].append(copy.deepcopy(r["containments"][0]))
        changes = [lambda r, c: r["containments"].clear(), duplicate,
                   lambda r, c: r["containments"][0].update(domain_id="missing"),
                   lambda r, c: r["containments"][0].update(contained_instance_id="outer"),
                   lambda r, c: r["instances"][0]["transform"].update(translation_mm=[20, 0, 0]),
                   lambda r, c: c["inner"]["material_bounds_mm"].update(min=[2, 2, 2]),
                   lambda r, c: c["outer"]["vacuum_domains"][0].update(z_max_mm=-10),
                   lambda r, c: c["outer"]["vacuum_domains"].append(copy.deepcopy(c["outer"]["vacuum_domains"][0])),
                   lambda r, c: c["inner"]["material_bounds_mm"]["min"].__setitem__(0, float("nan"))]
        for change in changes:
            recipe, components = enclosure_fixture()
            change(recipe, components)
            with self.subTest(change=change), self.assertRaises(ContractError):
                compile_assembly_layout(recipe, components)

    def test_legacy_recipe_does_not_silently_accept_containment(self):
        recipe, components = enclosure_fixture()
        recipe["schema_version"] = 1
        with self.assertRaises(ContractError):
            compile_assembly_layout(recipe, components)


if __name__ == "__main__":
    unittest.main()
