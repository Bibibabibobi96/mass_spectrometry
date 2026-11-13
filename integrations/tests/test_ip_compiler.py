"""Pure joint RF–IP geometry compiler tests."""
from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path

from msplatform.assembly.factory import assemble
from msplatform.backends.simion.ip_compiler import _inside_ip_electrode, _rf_physical_bounds, compile_ip_assembly_geometry
from msplatform.components.catalog import resolve_component
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology

ROOT = Path(__file__).resolve().parents[2]


class IpCompilerTests(unittest.TestCase):
    def setUp(self):
        baseline = json.loads((ROOT / "projects/dual_pressure_rectilinear_ion_processor/config/baseline.json").read_text(encoding="utf-8"))
        baseline["physical_design_selection"] = {"native_grid_mm": .1, "native_aux_segments": 60}
        example = json.loads((ROOT / "src/msplatform/examples/rf_oatof_functional_v1.json").read_text(encoding="utf-8"))
        rf = resolve_component(example["component_requests"]["multipole"])
        ip = resolve_component(dict(provider_id="dual_pressure_rectilinear_ion_processor", design=dict(baseline=baseline)))
        recipe = copy.deepcopy(example["recipe"])
        rf_row, ip_row = recipe["instances"]
        rf_row["transform"]["translation_mm"] = [-rf.assembly_interface["ports"]["mechanical_exit"]["center_mm"][2], 0, 0]
        ip_row.update(instance_id="ion_processor", project_id="dual_pressure_rectilinear_ion_processor")
        ip_row["transform"]["from_frame_id"] = ip.assembly_interface["local_frame_id"]
        recipe["connections"] = [dict(connection_id="mp_ip", upstream=dict(instance_id="multipole", port_id="mechanical_exit"), downstream=dict(instance_id="ion_processor", port_id="guide_inlet"), gap_mm=0., coupling_mode="monolithic_joint_solve")]
        self.assembly = assemble(recipe, {"multipole": rf, "ion_processor": ip})
        rf_names = [row["electrode_group_id"] for row in build_electrode_topology(rf.resolved_design)]
        ip_names = [row["electrode_group_id"] for row in ip.assembly_interface["component_electrodes"]]
        self.numerics = dict(parent_domain=dict(cell_mm_xyz=dict(x=.1, y=.1, z=.1),
            pa_bounds_mm=dict(x_min=-100., x_max=250., y_min=-30., y_max=30., z_min=-30., z_max=30.)),
            boundary="grounded_pa_faces", representation="fractional_legacy_within",
            electrode_group_native_ids={"multipole": {n: i+1 for i,n in enumerate(rf_names)},
                                        "ion_processor": {n: i+101 for i,n in enumerate(ip_names)}})

    def test_actual_assembly_compiles_full_body_and_explicit_contract(self):
        before = copy.deepcopy((self.assembly.composition_plan, self.assembly.components_resolved, self.numerics))
        result = compile_ip_assembly_geometry(self.assembly, numerics=self.numerics)
        gem = result.frontend_gems["parent"]
        self.assertIn("surface=fractional", gem)
        self.assertIn("locate(-79.6,0,0,1,90,90,0)", gem)
        self.assertIn("e(101) { ; guide_positive", gem)
        self.assertIn("e(115) { ; hp_commonmode_shield", gem)
        self.assertIn("e(0) { ; numerical grounded faces", gem)
        self.assertEqual(len(result.frontend_geometry["electrode_bindings"]["ion_processor"]), 15)
        self.assertEqual(result.frontend_geometry["representation"], "fractional_legacy_within")
        self.assertEqual((self.assembly.composition_plan, self.assembly.components_resolved, self.numerics), before)

    def test_bad_mapping_domain_and_representation_refused(self):
        for change in (lambda n: n["electrode_group_native_ids"]["ion_processor"].pop("guide_positive"),
                       lambda n: n["electrode_group_native_ids"]["ion_processor"].__setitem__("guide_positive", 1),
                       lambda n: n["parent_domain"]["pa_bounds_mm"].__setitem__("x_max", 10.),
                       lambda n: n["parent_domain"]["pa_bounds_mm"].__setitem__("x_min", -50.),
                       lambda n: n.__setitem__("representation", "surface_none"),
                       lambda n: n.__setitem__("boundary", "implicit")):
            with self.subTest(change=change):
                args = copy.deepcopy(self.numerics)
                change(args)
                with self.assertRaises(ValueError):
                    compile_ip_assembly_geometry(self.assembly, numerics=args)

    def test_rotated_bare_rods_fit_where_circular_envelope_overrejects(self):
        example = json.loads((ROOT / "src/msplatform/examples/rf_oatof_functional_v1.json").read_text(encoding="utf-8"))
        request = example["component_requests"]["multipole"]
        request["design"]["coordinate"]["orientation_rad"] = math.pi / 8
        design = resolve_component(request).resolved_design
        lower, upper = _rf_physical_bounds(design, (0., 0., 0.))
        rods = design["geometry_mm"]["rod_array"]["rods"]
        circular = max(math.hypot(r["center_x_mm"], r["center_y_mm"]) + r["radius_mm"] for r in rods)
        self.assertLess(max(abs(lower[1]), abs(upper[1]), abs(lower[2]), abs(upper[2])), 7.7)
        self.assertGreater(circular, 7.7)
        rotated_rf = resolve_component(request)
        components = self.assembly.components
        components["multipole"] = rotated_rf
        assembly = assemble(self.assembly.composition_plan["recipe"], components)
        numerics = copy.deepcopy(self.numerics)
        for axis in ("y", "z"):
            numerics["parent_domain"]["cell_mm_xyz"][axis] = .1
            numerics["parent_domain"]["pa_bounds_mm"][axis + "_min"] = -7.7
            numerics["parent_domain"]["pa_bounds_mm"][axis + "_max"] = 7.7
        result = compile_ip_assembly_geometry(assembly, numerics=numerics)
        self.assertIn("parent", result.frontend_gems)

    def test_notin_inside_cutout_retains_boundary(self):
        solid = dict(shape="box",min_mm=[0.,0.,0.],max_mm=[3.,3.,3.])
        cut = dict(shape="box",min_mm=[1.,1.,1.],max_mm=[2.,2.,2.])
        electrode = dict(solids=[solid],cutouts=[cut])
        self.assertTrue(_inside_ip_electrode(electrode,[1.,1.5,1.5]))
        self.assertFalse(_inside_ip_electrode(electrode,[1.5,1.5,1.5]))

    def test_unsupported_valid_rotation_is_refused(self):
        recipe = self.assembly.composition_plan["recipe"]
        rf, ip = recipe["instances"]
        rf["transform"]["rotation"] = [[0, 0, 1], [-1, 0, 0], [0, -1, 0]]
        ip["transform"]["rotation"] = [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
        rotated = assemble(recipe, self.assembly.components)
        with self.assertRaisesRegex(ValueError, "unsupported RF–IP pose rotation"):
            compile_ip_assembly_geometry(rotated, numerics=self.numerics)

    def test_forged_selected_geometry_is_refused(self):
        forged = copy.deepcopy(self.assembly)
        forged._components["ion_processor"]._resolved_design["projection"]["electrodes"][0]["solids"].pop()
        with self.assertRaises(ValueError):
            compile_ip_assembly_geometry(forged, numerics=self.numerics)


    def test_two_complete_ip_instances_allow_unconnected_layout(self):
        from msplatform.assembly.resolve_assembly import derive_assembly_scope
        ip = self.assembly.components["ion_processor"]
        recipe = copy.deepcopy(self.assembly.composition_plan["recipe"])
        row = copy.deepcopy(next(x for x in recipe["instances"] if x["instance_id"] == "ion_processor"))
        other = copy.deepcopy(row)
        other["instance_id"] = "ip_second"
        other["transform"]["rotation"] = [[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]]
        other["transform"]["translation_mm"] = [300., 4., -7.]
        recipe["instances"] = [row, other]
        recipe["connections"] = []
        components = {"ion_processor": ip, "ip_second": ip}
        before = copy.deepcopy(recipe)
        result = assemble(recipe, components)
        plan = result.composition_plan
        self.assertEqual(plan["stage"], "layout_only")
        self.assertEqual(plan["schema_version"], 5)
        self.assertEqual(plan["connection_checks"], [])
        self.assertEqual(plan["scope"]["instance_ids"], ["ion_processor", "ip_second"])
        self.assertEqual(plan["scope"]["connection_ids"], [])
        self.assertEqual(plan["scope"]["boundary_connection_ids"], [])
        self.assertEqual(plan["recipe"], before)
        self.assertEqual(recipe, before)
        self.assertEqual(derive_assembly_scope(plan), plan)
        self.assertEqual(result.components_resolved["ion_processor"], result.components_resolved["ip_second"])

    def test_unconnected_continuous_rf_ip_refuses(self):
        recipe = copy.deepcopy(self.assembly.composition_plan["recipe"])
        recipe["connections"] = []
        unconnected = assemble(recipe, self.assembly.components)
        with self.assertRaisesRegex(ValueError, "actual continuous mechanical connection"):
            compile_ip_assembly_geometry(unconnected, numerics=self.numerics)

    def test_unconnected_continuous_rf_oa_refuses(self):
        from msplatform.backends.simion.rf_oa_compiler import compile_rf_oa_geometry
        from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
        example = json.loads((ROOT / "src/msplatform/examples/oa_two_three_geometric_v1.json").read_text(encoding="utf-8"))
        oa = resolve_component(example["component_requests"]["three"])
        recipe = copy.deepcopy(self.assembly.composition_plan["recipe"])
        row = recipe["instances"][1]
        row.update(instance_id="oa", project_id="orthogonal_accelerator")
        row["transform"]["from_frame_id"] = oa.assembly_interface["local_frame_id"]
        recipe["connections"] = []
        assembly = assemble(recipe, {"multipole": self.assembly.components["multipole"], "oa": oa})
        numerics = copy.deepcopy(self.numerics)
        numerics["electrode_group_native_ids"].pop("ion_processor")
        names = list(dict.fromkeys(x["electrode_group_id"] for x in iter_geometry_members(oa.resolved_design)))
        numerics["electrode_group_native_ids"]["oa"] = {name: i+101 for i,name in enumerate(names)}
        with self.assertRaisesRegex(ValueError, "explicit mechanical exit to side-entry connection"):
            compile_rf_oa_geometry(assembly, numerics=numerics)

    def test_named_connections_and_invalid_assembly_still_refuse(self):
        original = self.assembly.composition_plan["recipe"]
        self.assertEqual(len(self.assembly.composition_plan["connection_checks"]), 1)
        for mutation in ("bad_port", "bad_gap", "bad_pose", "duplicate", "missing_provider"):
            with self.subTest(mutation=mutation):
                recipe = copy.deepcopy(original)
                components = dict(self.assembly.components)
                if mutation == "bad_port": recipe["connections"][0]["downstream"]["port_id"] = "not_a_port"
                elif mutation == "bad_gap": recipe["connections"][0]["gap_mm"] += 1
                elif mutation == "bad_pose": recipe["instances"][0]["transform"]["rotation"][0][0] = 2
                elif mutation == "duplicate": recipe["instances"].append(copy.deepcopy(recipe["instances"][0]))
                else: components.pop("ion_processor")
                with self.assertRaises(ValueError): assemble(recipe, components)

    def test_legacy_schema_requires_nonempty_recipe_even_with_fabricated_check(self):
        from msplatform.assembly.resolve_assembly import validate_composition_plan_contract
        from integrations.tests import test_single_reflection_geometry as legacy
        source = legacy.multipole_source("octupole")
        geometry = legacy.candidate_300mm_fixture()
        plan = legacy.inputs(source, geometry)["composition_plan"]
        self.assertEqual(plan["schema_version"], 3)
        validate_composition_plan_contract(plan)
        forged = copy.deepcopy(plan)
        forged["recipe"]["connections"] = []
        self.assertTrue(forged["connection_checks"])
        with self.assertRaises(ValueError): validate_composition_plan_contract(forged)
        # Real provider source fixture, rebuilt with the existing supported v2
        # interfaces so the full production validator selects plan version 4.
        from common.integration.test_scientific_provider_assembly import actual_fixture, TWO_ZONE_PROFILE
        from msplatform.backends.simion.rf_assembly_interface import build_legacy_assembly_interface
        from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
        from msplatform.assembly.resolve_assembly import compile_assembly_layout
        recipe4, _, sources4 = actual_fixture()
        rf4 = build_legacy_assembly_interface(sources4["rf"], geometry_profile_id="actual_bare_quadrupole", schema_version=2)
        oa4 = resolve_assembly_interface(sources4["oa_request"], geometry_profile_id=TWO_ZONE_PROFILE, schema_version=2)
        plan4 = compile_assembly_layout(recipe4, {"guide_a": rf4, "guide_b": rf4, "oa": oa4})
        self.assertEqual(plan4["schema_version"], 4)
        validate_composition_plan_contract(plan4)
        forged4 = copy.deepcopy(plan4)
        forged4["recipe"]["connections"] = []
        self.assertTrue(forged4["connection_checks"])
        with self.assertRaises(ValueError): validate_composition_plan_contract(forged4)


if __name__ == "__main__":
    unittest.main()
