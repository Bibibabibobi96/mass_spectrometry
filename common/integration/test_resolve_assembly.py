"""Direct mechanical placement tests; no solver or external artifacts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, REPO_ROOT
from common.integration.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from common.integration.resolve_connection import resolve_assembly_recipe, verify_composition_plan


def direct_fixture() -> tuple[dict, dict]:
    def pose(frame: str, rotation: list, translation: list) -> dict:
        return dict(
            schema_version=1,
            role="rigid_transform",
            from_frame_id=frame,
            to_frame_id="instrument_global",
            rotation=rotation,
            translation_mm=translation,
        )

    guide = dict(
        schema_version=1,
        role="component_geometry_interface",
        project_id="guide_provider",
        variant_id="bare_guide",
        geometry_profile_id=None,
        local_frame_id="guide_local",
        length_unit="mm",
        ports={
            "exit": dict(
                surface_kind="open_rod_exit",
                center_mm=[0, 0, 29],
                outward_normal=[0, 0, 1],
                cross_section=dict(shape="open_rod_envelope", inscribed_radius_mm=2),
                wall_thickness_mm=None,
            )
        },
        component_electrodes=[dict(component_electrode_id=1, role="rod", electrical_group_id=1)],
    )
    accelerator = dict(
        schema_version=1,
        role="component_geometry_interface",
        project_id="accelerator_provider",
        variant_id="two_zone",
        geometry_profile_id=None,
        local_frame_id="accelerator_local",
        length_unit="mm",
        ports={
            "entry": dict(
                surface_kind="aperture_outer_face",
                center_mm=[0, -17, 38],
                outward_normal=[0, -1, 0],
                cross_section=dict(
                    shape="rectangle", width_mm=3, height_mm=2.8, width_axis=[1, 0, 0], height_axis=[0, 0, 1]
                ),
                wall_thickness_mm=1,
            )
        },
        component_electrodes=[dict(component_electrode_id=22, role="repeller")],
    )
    recipe = dict(
        schema_version=1,
        role="assembly_recipe",
        integration_id="instrument_assembly",
        recipe_id="direct_frontend",
        assembly_frame_id="instrument_global",
        position_tolerance_mm=1e-9,
        angular_tolerance_rad=1e-12,
        instances=[
            dict(
                instance_id="guide",
                project_id="guide_provider",
                transform=pose("guide_local", [[1, 0, 0], [0, 0, 1], [0, -1, 0]], [0, -97, 32]),
            ),
            dict(
                instance_id="oa",
                project_id="accelerator_provider",
                transform=pose("accelerator_local", [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, -50, -6]),
            ),
        ],
        connections=[
            dict(
                connection_id="guide_to_oa",
                upstream=dict(instance_id="guide", port_id="exit"),
                downstream=dict(instance_id="oa", port_id="entry"),
                gap_mm=1,
                coupling_mode="monolithic_joint_solve",
            )
        ],
    )
    return recipe, {"guide": guide, "oa": accelerator}


class DirectAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recipe, self.components = direct_fixture()

    def test_frozen_parent_scope_uses_embedded_authority_and_rejects_derived_or_changed_parent(self):
        full = compile_assembly_layout(self.recipe, self.components)
        full['input_files'] = {'recipe': dict(path='unavailable.json', sha256='A'*64)}
        snapshot = copy.deepcopy(full)
        declaration = dict(instance_ids=[self.recipe['instances'][-1]['instance_id']],
            research_scope='downstream only', boundary_assumptions='explicit omitted upstream metal')
        local = derive_assembly_scope(full, local_scope=declaration)
        self.assertEqual(local, compile_assembly_layout(self.recipe, self.components, local_scope=declaration))
        self.assertEqual(full, snapshot)
        self.assertEqual(derive_assembly_scope(full)['scope']['kind'], 'full')
        with self.assertRaisesRegex(ContractError, 'frozen full assembly'):
            derive_assembly_scope(local)
        full['scope']['instance_ids'].pop()
        with self.assertRaisesRegex(ContractError, 'frozen full assembly'):
            derive_assembly_scope(full)

    @staticmethod
    def _extend_upstream(recipe: dict, components: dict, instance_id: str) -> None:
        # Native guide exit at z=29 and entrance at z=0; rotation maps +z to +y.
        downstream_id = recipe["instances"][0]["instance_id"]
        downstream = recipe["instances"][0]
        components[downstream_id]["ports"]["entry"] = dict(
            surface_kind="open_rod_entrance", center_mm=[0, 0, 0],
            outward_normal=[0, 0, -1],
            cross_section=dict(shape="open_rod_envelope", inscribed_radius_mm=2),
            wall_thickness_mm=None,
        )
        instance = copy.deepcopy(downstream)
        instance["instance_id"] = instance_id
        instance["transform"]["translation_mm"][1] -= 29
        recipe["instances"].insert(0, instance)
        components[instance_id] = copy.deepcopy(components[downstream_id])
        recipe["connections"].append(dict(
            connection_id=f"{instance_id}_to_{downstream_id}",
            upstream=dict(instance_id=instance_id, port_id="exit"),
            downstream=dict(instance_id=downstream_id, port_id="entry"),
            gap_mm=0, coupling_mode="monolithic_joint_solve",
        ))

    def test_complete_scope_tracks_only_the_selected_recipe_and_keeps_old_plan_frozen(self) -> None:
        frozen = compile_assembly_layout(self.recipe, self.components)
        snapshot = copy.deepcopy(frozen)
        plans = [frozen]
        for instance_id in ("cooler", "ion_source"):
            self._extend_upstream(self.recipe, self.components, instance_id)
            plans.append(compile_assembly_layout(self.recipe, self.components))
        self.assertEqual([len(plan["scope"]["instance_ids"]) for plan in plans], [2, 3, 4])
        for plan in plans:
            self.assertEqual(plan["schema_version"], 3)
            self.assertEqual(plan["scope"]["kind"], "full")
            self.assertEqual(plan["scope"]["instance_ids"],
                             [item["instance_id"] for item in plan["recipe"]["instances"]])
            self.assertEqual(plan["scope"]["boundary_connection_ids"], [])
            self.assertEqual(set(plan["scope"]["connection_ids"]),
                             {item["connection_id"] for item in plan["recipe"]["connections"]})
            self.assertNotIn("local_scope", plan)
        self.assertEqual(frozen, snapshot)
        self.assertEqual(plans[-1]["components"]["guide"]["project_id"],
                         plans[-1]["components"]["ion_source"]["project_id"])

    def test_local_scope_preserves_poses_and_updates_cut_connections_when_parent_grows(self) -> None:
        declaration = dict(instance_ids=["guide"], research_scope="Guide transport",
                           boundary_assumptions="External fields omitted at the declared cut surfaces")
        local = compile_assembly_layout(self.recipe, self.components, local_scope=declaration)
        before = copy.deepcopy(local)
        self.assertEqual(local["scope"], dict(kind="local", instance_ids=["guide"],
            connection_ids=[], boundary_connection_ids=["guide_to_oa"]))
        self._extend_upstream(self.recipe, self.components, "cooler")
        grown = compile_assembly_layout(self.recipe, self.components, local_scope=declaration)
        self.assertEqual(grown["scope"]["instance_ids"], ["guide"])
        self.assertEqual(grown["scope"]["boundary_connection_ids"], ["cooler_to_guide", "guide_to_oa"])
        self.assertEqual(grown["local_scope"], declaration)
        self.assertEqual(grown["recipe"]["instances"][1]["transform"],
                         local["recipe"]["instances"][0]["transform"])
        self.assertEqual(local, before)
        # A caller's source-instance/frame binding stays in the selected scope;
        # this parser does not create or transform particle-source data.
        source_instance, source_frame = "guide", "guide_local"
        full = compile_assembly_layout(self.recipe, self.components)
        for plan in (grown, full):
            self.assertIn(source_instance, plan["scope"]["instance_ids"])
            self.assertEqual(plan["components"][source_instance]["local_frame_id"], source_frame)
        self.assertNotIn("source", grown)

    def test_explicit_local_selection_may_include_all_parent_instances(self) -> None:
        declaration = dict(instance_ids=["oa", "guide"], research_scope="Local research scope",
                           boundary_assumptions="Both components retained")
        plan = compile_assembly_layout(self.recipe, self.components, local_scope=declaration)
        self.assertEqual(plan["scope"], dict(kind="local", instance_ids=["guide", "oa"],
            connection_ids=["guide_to_oa"], boundary_connection_ids=[]))
        self.assertEqual(plan["local_scope"], declaration)

    def test_invalid_local_declarations_fail_without_fallback(self) -> None:
        valid = dict(instance_ids=["guide"], research_scope="Guide transport",
                     boundary_assumptions="External fields omitted")
        invalid = [None, "guide", {}, [], ["guide", "guide"], ["missing"], [1], [{}]]
        for selection in invalid:
            with self.subTest(selection=selection), self.assertRaises(ContractError):
                compile_assembly_layout(self.recipe, self.components,
                    local_scope={**valid, "instance_ids": selection})
        for field in ("research_scope", "boundary_assumptions"):
            for value in (None, "", "   "):
                declaration = {**valid, field: value}
                with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                    compile_assembly_layout(self.recipe, self.components, local_scope=declaration)
            declaration = dict(valid)
            del declaration[field]
            with self.assertRaises(ContractError):
                compile_assembly_layout(self.recipe, self.components, local_scope=declaration)
        with self.assertRaises(ContractError):
            compile_assembly_layout(self.recipe, self.components, local_scope={**valid, "source": {}})

    def test_cli_local_scope_is_frozen_reverified_and_cannot_be_supplied_to_pair_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            declaration = dict(instance_ids=["guide"], research_scope="Guide transport",
                               boundary_assumptions="External fields omitted")
            for name, value in (("recipe", self.recipe), ("components", self.components),
                                ("local_scope", declaration)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            command = [sys.executable, "-m", "common.integration.resolve_connection"]
            result = subprocess.run(command + ["--recipe", str(root / "recipe.json"),
                "--components", str(root / "components.json"), "--local-scope", str(root / "local_scope.json"),
                "--repo-root", str(root), "--plan-output", str(root / "plan.json")],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            path = root / "plan.json"
            plan = json.loads(path.read_text())
            self.assertEqual(plan["local_scope"], declaration)
            self.assertIn("local_scope", plan["input_files"])
            result = subprocess.run(command + ["--verify-plan", str(path), "--verify-repo-root", str(root)],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            edited = copy.deepcopy(plan)
            edited["scope"]["boundary_connection_ids"] = []
            path.write_text(json.dumps(edited), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "differs"):
                verify_composition_plan(path, repo_root=root)
            path.write_text(json.dumps(plan), encoding="utf-8")
            declaration["boundary_assumptions"] = "Changed assumption"
            (root / "local_scope.json").write_text(json.dumps(declaration), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "local_scope source identity is stale"):
                verify_composition_plan(path, repo_root=root)
            result = subprocess.run(command + ["--local-scope", str(root / "local_scope.json")],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--local-scope requires --recipe", result.stderr)

    def test_old_v2_plan_is_not_an_active_format(self) -> None:
        plan = compile_assembly_layout(self.recipe, self.components)
        plan["schema_version"] = 2
        del plan["scope"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaises(ContractError):
                verify_composition_plan(path)

    def test_actual_outer_wall_and_open_rod_exit_are_compared_in_one_world_frame(self) -> None:
        before = copy.deepcopy((self.recipe, self.components))
        plan = compile_assembly_layout(self.recipe, self.components)
        self.assertEqual((self.recipe, self.components), before)
        self.assertEqual(
            plan["connection_checks"],
            [
                dict(
                    connection_id="guide_to_oa",
                    upstream_center_mm=[0, -68, 32],
                    downstream_center_mm=[0, -67, 32],
                    upstream_outward_normal=[0, 1, 0],
                    downstream_outward_normal=[0, -1, 0],
                    gap_mm=1,
                )
            ],
        )
        self.assertEqual(plan["recipe"]["instances"], self.recipe["instances"])
        self.assertNotIn("execution_steps", plan)
        self.assertNotIn("potential_V", plan["components"]["guide"]["ports"]["exit"])

    def test_midwall_or_opposite_translation_does_not_get_compensated(self) -> None:
        for move in (0.5, -1, 1):
            with self.subTest(move=move):
                recipe = copy.deepcopy(self.recipe)
                recipe["instances"][1]["transform"]["translation_mm"][1] += move
                with self.assertRaisesRegex(ContractError, "declared gap or alignment"):
                    compile_assembly_layout(recipe, self.components)

    def test_provider_frame_names_are_preserved_without_assembly_aliases(self) -> None:
        frame = "astral.xyz.reflection_z.drift_y.transverse_x.v2"
        self.recipe["assembly_frame_id"] = frame
        for instance in self.recipe["instances"]:
            instance["transform"]["to_frame_id"] = frame
        local = "ion_processor.xyz.reflection_z.drift_y.transverse_x.local.v2"
        self.components["guide"]["local_frame_id"] = local
        self.recipe["instances"][0]["transform"]["from_frame_id"] = local
        plan = compile_assembly_layout(self.recipe, self.components)
        self.assertEqual(plan["assembly_frame_id"], frame)
        self.assertEqual(plan["components"]["guide"]["local_frame_id"], local)
        self.assertEqual(plan["recipe"]["instances"], self.recipe["instances"])

    def test_continuous_entry_frame_does_not_require_an_invented_wall_thickness(self) -> None:
        interface = self.components["oa"]
        interface["variant_id"] = "prism_entry_frame"
        interface["ports"]["entry"]["wall_thickness_mm"] = None
        plan = compile_assembly_layout(self.recipe, self.components)
        self.assertIsNone(plan["components"]["oa"]["ports"]["entry"]["wall_thickness_mm"])
        interface["ports"]["entry"]["wall_thickness_mm"] = -1
        with self.assertRaises(ContractError):
            compile_assembly_layout(self.recipe, self.components)

    def test_round_gate_keeps_its_actual_circle_against_a_rectangular_entry(self) -> None:
        port = self.components["guide"]["ports"]["exit"]
        port.update(surface_kind="aperture_outer_face", wall_thickness_mm=0.5,
                    cross_section=dict(shape="circle", radius_mm=1))
        plan = compile_assembly_layout(self.recipe, self.components)
        self.assertEqual(plan["components"]["guide"]["ports"]["exit"]["cross_section"],
                         dict(shape="circle", radius_mm=1))
        port["cross_section"]["radius_mm"] = 0
        with self.assertRaises(ContractError):
            compile_assembly_layout(self.recipe, self.components)

    def test_open_rod_entrance_allows_direct_mating_without_a_fictitious_wall(self) -> None:
        port = self.components["oa"]["ports"]["entry"]
        port.update(surface_kind="open_rod_entrance", wall_thickness_mm=None,
                    cross_section=dict(shape="open_rod_envelope", inscribed_radius_mm=2))
        self.recipe["instances"][1]["transform"]["translation_mm"] = [0, -51, -6]
        self.recipe["connections"][0].update(gap_mm=0, coupling_mode="state_handoff")
        plan = compile_assembly_layout(self.recipe, self.components)
        self.assertEqual(plan["connection_checks"][0]["gap_mm"], 0)
        port["wall_thickness_mm"] = 1
        with self.assertRaises(ContractError):
            compile_assembly_layout(self.recipe, self.components)

    def test_component_order_does_not_change_connection_checks(self) -> None:
        expected = compile_assembly_layout(self.recipe, self.components)["connection_checks"]
        self.recipe["instances"].reverse()
        self.assertEqual(compile_assembly_layout(self.recipe, self.components)["connection_checks"], expected)

    def test_one_provider_may_have_two_explicit_instances(self) -> None:
        another = copy.deepcopy(self.recipe["instances"][0])
        another["instance_id"] = "another_guide"
        another["transform"]["translation_mm"][0] = 100
        self.recipe["instances"].append(another)
        self.components["another_guide"] = copy.deepcopy(self.components["guide"])
        plan = compile_assembly_layout(self.recipe, self.components)
        self.assertEqual(len(plan["recipe"]["instances"]), 3)

    def test_three_quadrupole_interfaces_keep_instance_local_geometry_and_ids(self) -> None:
        # Synthetic mechanical views exercise instance identity, not three-stage
        # quadrupole fields, independent drives or a qualified instrument.
        recipe = copy.deepcopy(self.recipe)
        recipe["instances"], recipe["connections"] = [], []
        components = {}
        for instance_id, variant, entry, exit_z, radius, translation in (
            ("q1", "round_rods", 0, 10, 1, 0),
            ("q2", "segmented_rods", -2, 18, 2, 13),
            ("q3", "tapered_rods", 5, 35, 3, 28),
        ):
            interface = copy.deepcopy(self.components["guide"])
            interface.update(project_id="rf_multipole_ion_optics", variant_id=variant,
                             geometry_profile_id=f"fixture_{instance_id}")
            interface["ports"]["exit"]["center_mm"] = [0, 0, exit_z]
            interface["ports"]["exit"]["cross_section"]["inscribed_radius_mm"] = radius
            interface["ports"]["entry"] = copy.deepcopy(interface["ports"]["exit"])
            interface["ports"]["entry"].update(surface_kind="open_rod_entrance",
                center_mm=[0, 0, entry], outward_normal=[0, 0, -1])
            components[instance_id] = interface
            instance = copy.deepcopy(self.recipe["instances"][0])
            instance.update(instance_id=instance_id, project_id=interface["project_id"])
            instance["transform"].update(rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                                         translation_mm=[0, 0, translation])
            recipe["instances"].append(instance)
        for upstream, downstream, gap in (("q1", "q2", 1), ("q2", "q3", 2)):
            recipe["connections"].append(dict(connection_id=f"{upstream}_to_{downstream}",
                upstream=dict(instance_id=upstream, port_id="exit"),
                downstream=dict(instance_id=downstream, port_id="entry"),
                gap_mm=gap, coupling_mode="monolithic_joint_solve"))
        plan = compile_assembly_layout(recipe, components)
        frozen = copy.deepcopy(plan)
        self.assertEqual(plan["components"], components)
        self.assertEqual(plan["recipe"]["instances"], recipe["instances"])
        self.assertEqual(plan["scope"]["instance_ids"], ["q1", "q2", "q3"])
        self.assertEqual([row["upstream_center_mm"] for row in plan["connection_checks"]],
                         [[0, 0, 10], [0, 0, 31]])
        self.assertEqual([row["downstream_center_mm"] for row in plan["connection_checks"]],
                         [[0, 0, 11], [0, 0, 33]])
        self.assertEqual([components[key]["component_electrodes"][0]["component_electrode_id"]
                          for key in ("q1", "q2", "q3")], [1, 1, 1])
        declaration = dict(instance_ids=["q2"], research_scope="Second quadrupole geometry",
                           boundary_assumptions="External fields at both cut surfaces omitted")
        local = compile_assembly_layout(recipe, components, local_scope=declaration)
        self.assertEqual(local["scope"], dict(kind="local", instance_ids=["q2"],
            connection_ids=[], boundary_connection_ids=["q1_to_q2", "q2_to_q3"]))
        self.assertEqual(local["components"], plan["components"])
        self.assertEqual(local["recipe"], plan["recipe"])
        components["q2"]["ports"]["exit"]["cross_section"]["inscribed_radius_mm"] = 2.5
        changed = compile_assembly_layout(recipe, components)
        self.assertNotEqual(changed["components"]["q2"], plan["components"]["q2"])
        for instance_id in ("q1", "q3"):
            self.assertEqual(changed["components"][instance_id], plan["components"][instance_id])
        self.assertEqual(plan, frozen)
        self.assertEqual(local["components"], frozen["components"])

    def test_wrong_frames_project_and_duplicate_physical_ids_fail(self) -> None:
        for mutation in ("frame", "project", "electrode", "instance", "missing"):
            recipe, components = copy.deepcopy((self.recipe, self.components))
            if mutation == "frame":
                recipe["instances"][0]["transform"]["from_frame_id"] = "wrong"
            elif mutation == "project":
                components["guide"]["project_id"] = "wrong"
            elif mutation == "electrode":
                components["guide"]["component_electrodes"] *= 2
            elif mutation == "instance":
                recipe["instances"].append(recipe["instances"][0])
            else:
                components.pop("oa")
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                compile_assembly_layout(recipe, components)

    def test_reflection_is_invalid_even_with_loose_mating_tolerance(self) -> None:
        self.recipe["angular_tolerance_rad"] = 3
        self.recipe["instances"][0]["transform"]["rotation"] = [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]
        with self.assertRaisesRegex(ContractError, "right handed"):
            compile_assembly_layout(self.recipe, self.components)

    def test_nonfinite_normal_and_wrong_cross_section_axes_fail(self) -> None:
        for mutation in ("nan", "normal", "axes"):
            recipe, components = copy.deepcopy((self.recipe, self.components))
            if mutation == "nan":
                recipe["instances"][0]["transform"]["translation_mm"][0] = float("nan")
            elif mutation == "normal":
                components["guide"]["ports"]["exit"]["outward_normal"] = [0, 0, 2]
            else:
                components["oa"]["ports"]["entry"]["cross_section"]["height_axis"] = [1, 0, 0]
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                compile_assembly_layout(recipe, components)

    def test_cli_freezes_inputs_and_rejects_edited_output_or_stale_provider_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe_path = root / "recipe.json"
            components_path = root / "components.json"
            plan_path = root / "plan.json"
            recipe_path.write_text(json.dumps(self.recipe), encoding="utf-8")
            components_path.write_text(json.dumps(self.components), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "common.integration.resolve_connection",
                    "--recipe",
                    str(recipe_path),
                    "--components",
                    str(components_path),
                    "--plan-output",
                    str(plan_path),
                    "--repo-root",
                    str(root),
                ],
                cwd=REPO_ROOT,
                timeout=60,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            verify_composition_plan(plan_path, repo_root=root)
            plan = json.loads(plan_path.read_text())
            plan["connection_checks"][0]["gap_mm"] = 2
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "differs"):
                verify_composition_plan(plan_path, repo_root=root)
            plan = resolve_assembly_recipe(recipe_path, components_path, root)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            components_path.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "stale"):
                verify_composition_plan(plan_path, repo_root=root)


if __name__ == "__main__":
    unittest.main()
