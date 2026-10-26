"""Independent 300-mm square-candidate mechanical vectors; no run artifacts."""
from __future__ import annotations

import copy
import unittest

from common.contracts.machine_contracts import validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_contract
from projects.orthogonal_accelerator.simion.sectioned_accelerator import render_accelerator_local_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import (
    ResolvedAcceleratorGeometry, project_side_opening, resolve_accelerator_geometry,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.assembly_interface import resolve_assembly_interface


def candidate_300mm_fixture() -> dict:
    """Grid-realized 7/56.1/236.9-mm candidate and 60-mm half-bore solids.

    The four-plane vector and 4+16 ring design are the existing 300-mm design;
    explicit dimensions here are independent of the production compiler.
    """
    planes = {
        "repeller": -342.74261546154855, "intermediate1": -335.74261546154855,
        "intermediate2": -279.64261546154853, "exit": -42.742615461548496,
    }
    zone2 = [planes["intermediate1"] + k * 56.1 / 5 for k in range(1, 5)]
    zone3 = [planes["intermediate2"] + k * 236.9 / 17 for k in range(1, 17)]
    partial = {
        "role": "oa_tof_resolved_contract_do_not_edit",
        "coordinate_convention": {"frame_id": "oatof_global", "accelerator_axis_x": -48.8},
        "geometry_mm": {
            "accelerator_repeller_thickness": 1, "accelerator_rear_clearance": 5,
            "accelerator_shield_wall": 4, "accelerator_bore_half": 60,
            "accelerator_ring_width": 5, "accelerator_insulation_gap": 5,
            "accelerator_ring_thickness": 1,
        },
        "geometry_derivation": {"accelerator": {"realization_id": "square_3d"}},
        "accelerator_topology": {
            "topology_id": "three_zone_accelerator_ideal_v1", "planes_global_z_mm": planes,
            "potentials_v": {"repeller": 2140, "intermediate1": 1860,
                             "intermediate2": 372.96685170832035, "exit": 0},
        },
        "rings": {"accelerator_count": 20, "accelerator_placement": {
            "policy_id": "three_zone_zonewise_equal_subdivision_v1",
            "zone_ring_counts": {"zone2": 4, "zone3": 16},
            "minimum_grid_to_ring_edge_clearance_mm": 1,
            "minimum_observed_grid_to_ring_edge_clearance_mm": 10.72,
            "ring_z_mm": zone2 + zone3,
        }},
    }
    resolved = resolve_contract()
    resolved["geometry_mm"].update(partial["geometry_mm"])
    resolved["coordinate_convention"].update(partial["coordinate_convention"])
    resolved["geometry_derivation"]["accelerator"].update(partial["geometry_derivation"]["accelerator"])
    resolved["accelerator_topology"] = partial["accelerator_topology"]
    resolved["rings"].update(partial["rings"])
    resolved["electrodes_V"].update(repeller=2140, grid1=1860, intermediate2=372.96685170832035, grid2=0)
    return resolved



def projected_candidate(*, width: float = 1, height: float = 4) -> ResolvedAcceleratorGeometry:
    projection = resolve_accelerator_geometry(candidate_300mm_fixture(), variant_id="three_zone_square")
    project_side_opening(
        projection.local_region,
        side_opening={"center_mm": [-122.8, 0, -340.74261546154855],
                      "width_mm": width, "height_mm": height},
        cell_mm_xyz={"x": .25, "y": .25, "z": .1},
        pa_origin_mm={"x": -132.8, "y": -74.5, "z": -352.84261546154855},
    )
    return projection


class AssemblyInterfaceTests(unittest.TestCase):
    def test_300mm_solids_outer_face_and_native_render_use_one_projection(self):
        projection = projected_candidate()
        before = copy.deepcopy(projection)
        interface = resolve_assembly_interface(candidate_300mm_fixture(), projection=projection, geometry_profile_id=None)
        validate_schema(interface, "component_geometry_interface.schema.json")
        self.assertEqual(interface["variant_id"], "three_zone_square")
        self.assertEqual(interface["local_frame_id"], "oatof_global")
        electrodes = interface["component_electrodes"]
        self.assertEqual(electrodes[0], dict(component_electrode_id=1,
            role="accelerator_side_shield", electrical_group_id=1))
        self.assertIn("reflectron_entry_grid", [item["role"] for item in electrodes])
        self.assertIn("detector", [item["role"] for item in electrodes])
        self.assertEqual(len({item["component_electrode_id"] for item in electrodes}), len(electrodes))
        self.assertFalse(any("marker" in item["role"] for item in electrodes))
        port = interface["ports"]["side_entry"]
        self.assertEqual(port["center_mm"], [-122.8, 0, -340.74261546154855])
        self.assertEqual(port["outward_normal"], [-1, 0, 0])
        self.assertEqual(port["wall_thickness_mm"], 4)
        self.assertEqual(port["cross_section"], {"shape": "rectangle", "width_mm": 1,
                         "height_mm": 4, "width_axis": [0, 1, 0], "height_axis": [0, 0, 1]})
        g = projection.local_region
        self.assertEqual(g["shield_outer_width_mm"], 148)
        self.assertEqual(g["shield_inner_width_mm"], 140)
        self.assertAlmostEqual(g["shield_span_z_mm"], 310)
        self.assertAlmostEqual(g["shield_back_z_mm"], -352.74261546154855)
        self.assertEqual(len(g["ring_z_mm"]), 20)
        # Arbitrary solver bindings demonstrate that the physical ID is not a PA ID.
        ids = {"grounded_shield_id": 71, "accelerator_repeller_id": 72,
               "accelerator_grid1_id": 73, "accelerator_intermediate2_id": 74,
               "accelerator_grid2_id": 75, "accelerator_ring_ids": list(range(80, 100))}
        gem = "\n".join(render_accelerator_local_geometry(
            g, cell_x_mm=.25, cell_z_mm=.1, electrodes=ids, render_intermediate2_sheet=True,
        ))
        self.assertIn("e(71)", gem)
        self.assertIn("centered_box3D(-48.8,0,-197.742615462,148,148,310)", gem)
        self.assertIn("centered_box3D(-120.8,0,-340.742615462,4.5,1,4)", gem)
        self.assertEqual(projection, before)

    def test_opening_width_is_explicit_and_shared_with_renderer(self):
        projection = projected_candidate(width=2.5, height=6)
        port = resolve_assembly_interface(candidate_300mm_fixture(), projection=projection, geometry_profile_id="square_fixture")["ports"]["side_entry"]
        self.assertEqual(port["cross_section"]["width_mm"], 2.5)
        self.assertEqual(port["cross_section"]["height_mm"], 6)
        self.assertEqual(projection.local_region["numerical_port_width_mm"], 2.5)
        self.assertEqual(projection.local_region["numerical_port_height_mm"], 6)

    def test_source_parameters_are_neither_required_nor_changed(self):
        source = candidate_300mm_fixture()
        source["particle_source"] = {"center_z_mm": 999}
        before = copy.deepcopy(source)
        resolve_accelerator_geometry(source, variant_id="three_zone_square")
        self.assertEqual(source, before)

    def test_unknown_variant_wrong_frame_and_incomplete_candidate_fail(self):
        for variant, mutation, error in (
            ("unknown", lambda c: None, "variant"),
            ("two_zone_square", lambda c: None, "topology"),
            ("three_zone_cylindrical", lambda c: None, "realization"),
            ("three_zone_square", lambda c: c["coordinate_convention"].update(frame_id="invented"), "frame"),
            ("three_zone_square", lambda c: c["geometry_mm"].pop("accelerator_shield_wall"), "incomplete"),
        ):
            with self.subTest(variant=variant, error=error):
                candidate = candidate_300mm_fixture()
                mutation(candidate)
                with self.assertRaisesRegex(ValueError, error):
                    resolve_accelerator_geometry(candidate, variant_id=variant)

    def test_missing_opening_and_false_outer_faces_fail(self):
        projection = resolve_accelerator_geometry(candidate_300mm_fixture(), variant_id="three_zone_square")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            resolve_assembly_interface(candidate_300mm_fixture(), projection=projection, geometry_profile_id=None)
        with self.assertRaisesRegex(ValueError, "outer wall"):
            project_side_opening(projection.local_region,
                                 side_opening={"center_mm": [-120.8, 0, -340.7], "width_mm": 1, "height_mm": 4},
                                 cell_mm_xyz={"x": .25, "y": .25, "z": .1}, pa_origin_mm={"x": 0, "y": 0, "z": 0})
        for mutation, error in (
            (lambda g: g["accelerator_port_aperture_discretization"].update(flange_min_mm=-120.8), "traverse"),
            (lambda g: g.update(shield_wall_mm=2), "traverse"),
            (lambda g: g["accelerator_port_aperture_discretization"].update(mechanical_height_mm=100), "axial end"),
            (lambda g: g["accelerator_port_aperture_discretization"].update(mechanical_width_mm=150), "corner"),
        ):
            with self.subTest(error=error):
                projection = projected_candidate()
                mutation(projection.local_region)
                with self.assertRaisesRegex(ValueError, error):
                    resolve_assembly_interface(candidate_300mm_fixture(), projection=projection, geometry_profile_id=None)

    def test_cylindrical_renderer_is_preserved_but_has_no_false_planar_interface(self):
        candidate = candidate_300mm_fixture()
        candidate["geometry_derivation"]["accelerator"]["realization_id"] = "cylindrical_3d"
        projection = resolve_accelerator_geometry(candidate, variant_id="three_zone_cylindrical")
        self.assertEqual(projection.local_region["cross_section"], "cylindrical")
        with self.assertRaisesRegex(ValueError, "does not support"):
            resolve_assembly_interface(candidate_300mm_fixture(), projection=projection, geometry_profile_id=None)


if __name__ == "__main__":
    unittest.main()
