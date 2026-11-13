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


if __name__ == "__main__":
    unittest.main()
