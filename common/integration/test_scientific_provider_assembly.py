"""Actual RF/OA mechanical providers, scoped groups and frozen plan-4 files.

No source sampling, native field solve, collision qualification or flight occurs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record
from common.integration.resolve_connection import resolve_assembly_recipe, verify_composition_plan
from msplatform.assembly.electrode_binding import ElectrodeKey, validate_electrode_bindings
from msplatform.assembly.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
from projects.orthogonal_accelerator.tests.analysis.test_assembly_interface import TWO_ZONE_PROFILE, two_zone_requirements
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
from projects.rf_multipole_ion_optics.core.electrode_topology import build_electrode_topology
from projects.rf_multipole_ion_optics.simion.electrode_mapping import build_simion_electrode_map
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request


ROOT = Path(__file__).resolve().parents[2]
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return path


def pose(interface: dict, rotation: list, translation: list) -> dict:
    return dict(schema_version=1, role="rigid_transform", from_frame_id=interface["local_frame_id"],
                to_frame_id="instrument_global", rotation=rotation, translation_mm=translation)


def actual_fixture() -> tuple[dict, dict, dict]:
    """Compile existing real request fixtures; place ports, not native solids."""
    request = design_request("quadrupole")
    resolved = compile_design_request(request, expected_identity=request["identity"])
    rf = build_assembly_interface(resolved, geometry_profile_id="actual_bare_quadrupole")
    oa_request = two_zone_requirements()
    oa = resolve_assembly_interface(oa_request, geometry_profile_id=TWO_ZONE_PROFILE)
    interfaces = dict(guide_a=copy.deepcopy(rf), guide_b=copy.deepcopy(rf), oa=oa)
    exit_z = rf["ports"]["mechanical_exit"]["center_mm"][2]
    entrance_z = rf["ports"]["mechanical_entrance"]["center_mm"][2]
    b_translation = [0, 0, exit_z + 1 - entrance_z]
    rotation = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # proper rotation: local -y -> world -z
    rotated = RigidTransform(oa["local_frame_id"], "instrument_global", rotation, [0, 0, 0]).transform_position(
        FramedPosition(oa["local_frame_id"], oa["ports"]["side_entry"]["center_mm"])).coordinates_mm
    target = [0, 0, exit_z + b_translation[2] + 1]
    translation = [value - origin for value, origin in zip(target, rotated, strict=True)]
    instances = [dict(instance_id=name, project_id=interfaces[name]["project_id"], transform=placement)
                 for name, placement in (("guide_a", pose(rf, IDENTITY, [0, 0, 0])),
                                         ("guide_b", pose(rf, IDENTITY, b_translation)),
                                         ("oa", pose(oa, rotation, translation)))]
    connections = [dict(connection_id=name, upstream=dict(instance_id=up, port_id="mechanical_exit"),
                        downstream=dict(instance_id=down, port_id=port), gap_mm=1,
                        coupling_mode="monolithic_joint_solve") for name, up, down, port in (
        ("a_to_b", "guide_a", "guide_b", "mechanical_entrance"), ("b_to_oa", "guide_b", "oa", "side_entry"))]
    recipe = dict(schema_version=1, role="assembly_recipe", integration_id="instrument_assembly",
                  recipe_id="actual_rf_rf_oa", assembly_frame_id="instrument_global",
                  position_tolerance_mm=1e-9, angular_tolerance_rad=1e-12,
                  instances=instances, connections=connections)
    return recipe, interfaces, dict(rf=resolved, rf_request=request, oa_request=oa_request)


def frozen_bindings(root: Path, interfaces: dict, sources: dict) -> tuple[dict, dict]:
    """Use existing file-record identity for actual provider JSON and OA profile."""
    rf_path = write_json(root / "rf_resolved.json", sources["rf"])
    oa_path = write_json(root / "oa_requirements.json", sources["oa_request"])
    profile = root / "oa_component_contract.json"
    shutil.copyfile(ROOT / "projects/orthogonal_accelerator/config/component_contract_v3.json", profile)
    inputs, rows = {}, []
    for instance, interface in interfaces.items():
        interface_path = write_json(root / (instance + "_interface.json"), interface)
        inputs[instance] = dict(source=file_record(oa_path if instance == "oa" else rf_path),
                                interface=file_record(interface_path))
        if instance == "oa":
            inputs[instance]["geometry_profile"] = file_record(profile)
        rows.extend(dict(instance_id=instance, electrode_group_id=item["electrode_group_id"],
                         native_selection=instance + "/" + item["electrode_group_id"])
                    for item in interface["component_electrodes"])
    binding = dict(schema_version=2, role="backend_electrode_bindings", backend="fixture_named_selection",
                   field_domain_id="complete_parent", provider_inputs=copy.deepcopy(inputs), bindings=rows)
    return inputs, binding


class ScientificProviderAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.recipe, self.interfaces, self.sources = actual_fixture()

    def test_actual_two_rf_instances_and_oa_compile_and_bind_in_one_frame(self):
        before = copy.deepcopy((self.recipe, self.interfaces, self.sources))
        plan = compile_assembly_layout(self.recipe, self.interfaces)
        self.assertEqual(plan["schema_version"], 5)
        self.assertEqual([row["schema_version"] for row in self.interfaces.values()], [3, 3, 3])
        checks = plan["connection_checks"]
        self.assertEqual([row["gap_mm"] for row in checks], [1, 1])
        self.assertEqual(checks[0]["upstream_center_mm"], [0, 0, 85])
        self.assertEqual(checks[0]["downstream_center_mm"], [0, 0, 86])
        self.assertEqual(checks[1]["downstream_center_mm"], [0, 0, 167])
        with tempfile.TemporaryDirectory() as directory:
            inputs, bindings = frozen_bindings(Path(directory), self.interfaces, self.sources)
            for records in inputs.values():
                for name, record in records.items():
                    verify_record(name, record)
            validate_electrode_bindings(self.interfaces, bindings, field_domain_id="complete_parent", provider_inputs=inputs)
            expected = {ElectrodeKey(instance, row["electrode_group_id"])
                        for instance, interface in self.interfaces.items() for row in interface["component_electrodes"]}
            actual = {ElectrodeKey(row["instance_id"], row["electrode_group_id"]) for row in bindings["bindings"]}
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 23)
            self.assertNotEqual(ElectrodeKey("guide_a", "rod_group_1"), ElectrodeKey("guide_b", "rod_group_1"))
        self.assertEqual((self.recipe, self.interfaces, self.sources), before)

    def test_instance_reorder_and_native_permutation_leave_scientific_geometry_bound(self):
        full = compile_assembly_layout(self.recipe, self.interfaces)
        reordered = copy.deepcopy(self.recipe)
        reordered["instances"].reverse()
        interfaces = dict(reversed(list(self.interfaces.items())))
        changed = compile_assembly_layout(reordered, interfaces)
        self.assertEqual(changed["components"], full["components"])
        self.assertEqual(changed["connection_checks"], full["connection_checks"])
        self.assertCountEqual(changed["scope"]["instance_ids"], full["scope"]["instance_ids"])
        topology = build_electrode_topology(self.sources["rf"])
        for values in ((17, 23), (23, 17)):
            mapping = dict(zip((row["electrode_group_id"] for row in topology), values, strict=True))
            self.assertEqual(build_simion_electrode_map(self.sources["rf"], topology, requested_native_ids=mapping), mapping)
            self.assertEqual(build_assembly_interface(self.sources["rf"], geometry_profile_id="actual_bare_quadrupole"), self.interfaces["guide_a"])
            self.assertEqual(compile_assembly_layout(self.recipe, self.interfaces), full)
        with tempfile.TemporaryDirectory() as directory:
            inputs, bindings = frozen_bindings(Path(directory), self.interfaces, self.sources)
            bindings["bindings"].reverse()
            validate_electrode_bindings(interfaces, bindings, field_domain_id="complete_parent", provider_inputs=inputs)
            bindings["bindings"][0]["instance_id"] = "guide_a"
            with self.assertRaises(ContractError):
                validate_electrode_bindings(interfaces, bindings, field_domain_id="complete_parent", provider_inputs=inputs)

    def test_public_file_adapter_verifies_plan4_and_preserves_full_local_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe_path = write_json(root / "recipe.json", self.recipe)
            components_path = write_json(root / "components.json", self.interfaces)
            plan = resolve_assembly_recipe(recipe_path, components_path, root)
            self.assertEqual(plan["schema_version"], 5)
            plan_path = write_json(root / "plan.json", plan)
            verify_composition_plan(plan_path, repo_root=root)
            before = copy.deepcopy(plan)
            declaration = dict(instance_ids=["guide_b", "oa"], research_scope="last real RF and OA",
                               boundary_assumptions="first guide omitted only in declared local scope")
            local = derive_assembly_scope(plan, local_scope=declaration)
            self.assertEqual(local["components"], plan["components"])
            self.assertEqual(local["scope"]["boundary_connection_ids"], ["a_to_b"])
            self.assertEqual(local["scope"]["connection_ids"], ["b_to_oa"])
            local_path = write_json(root / "local_plan.json", local)
            verify_composition_plan(local_path, repo_root=root)
            self.assertEqual(plan, before)
            recipe_path.write_text(recipe_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "stale"):
                verify_composition_plan(plan_path, repo_root=root)

    def test_missing_provider_record_stale_identity_and_unknown_version_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, bindings = frozen_bindings(Path(directory), self.interfaces, self.sources)
            missing = copy.deepcopy(inputs)
            del missing["guide_b"]
            with self.assertRaisesRegex(ContractError, "cover"):
                validate_electrode_bindings(self.interfaces, bindings, field_domain_id="complete_parent", provider_inputs=missing)
            stale = copy.deepcopy(bindings)
            stale["provider_inputs"]["oa"]["source"]["sha256"] = inputs["guide_a"]["source"]["sha256"]
            with self.assertRaisesRegex(ContractError, "identity differs"):
                validate_electrode_bindings(self.interfaces, stale, field_domain_id="complete_parent", provider_inputs=inputs)
        invalid = copy.deepcopy(self.interfaces)
        invalid["oa"]["schema_version"] = 99
        with self.assertRaisesRegex(ContractError, "version"):
            compile_assembly_layout(self.recipe, invalid)


if __name__ == "__main__":
    unittest.main()
