"""Canonical inputs and static COMSOL wiring; does not execute MATLAB or COMSOL."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_contract, resolve_physical_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import resolve_accelerator_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_electrical import resolve_accelerator_electrical_design
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_accelerator_electrical import three_zone_fixture, two_zone_fixture

ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / "projects/single_reflection_oa_tof_mass_analyzer"
OA = ROOT / "projects/orthogonal_accelerator/comsol"


def source(name):
    return (PROJECT / name).read_text(encoding="utf-8")


class ComsolAcceleratorProjectionTests(unittest.TestCase):
    def test_explicit_detector_position_does_not_follow_mirror_or_focus(self):
        resolved = resolve_contract()
        resolved["coordinate_convention"]["detector_x"] = 69.01362184380704
        resolved["geometry_mm"]["detector_z"] = 12.5
        before = copy.deepcopy(resolved)
        physical = resolve_physical_geometry(resolved)
        detector = next(item for item in physical["electrodes"] if item["role"] == "detector")
        self.assertEqual(detector["geometry"]["base_center_mm"],
                         [69.01362184380704, 0, 12.5 - resolved["geometry_mm"]["detector_thickness"]])
        self.assertEqual(physical["detector_active_face"]["center_mm"], [69.01362184380704, 0, 12.5])
        self.assertNotEqual(69.01362184380704, -resolved["coordinate_convention"]["accelerator_axis_x"])
        self.assertNotEqual(12.5, resolved["geometry_mm"]["accelerator_focus_z"])
        self.assertEqual(resolved, before)

    def test_existing_three_zone_authorities_supply_actual_ring_positions_and_on_voltages(self):
        resolved=three_zone_fixture()
        before=copy.deepcopy(resolved)
        geometry=resolve_accelerator_geometry(resolved,variant_id="three_zone_square").local_region
        electrical=resolve_accelerator_electrical_design(resolved,variant_id="three_zone_square")
        self.assertEqual(resolved,before)
        self.assertEqual(geometry["ring_z_mm"],electrical["ring_z_mm"])
        self.assertEqual(len(geometry["ring_z_mm"]),20)
        self.assertNotAlmostEqual(geometry["ring_z_mm"][1]-geometry["ring_z_mm"][0],
                                  geometry["ring_z_mm"][5]-geometry["ring_z_mm"][4])
        self.assertEqual(electrical["planes_z_mm"]["intermediate2"],geometry["intermediate2_z_mm"])
        self.assertEqual(electrical["operating_voltages_v"]["rings"][0],1562.5933703416636)
        self.assertEqual(electrical["operating_voltages_v"]["rings"][-1],21.93922657107771)

    def test_two_zone_scientific_golden_is_unchanged(self):
        resolved=two_zone_fixture()
        electrical=resolve_accelerator_electrical_design(resolved,variant_id="two_zone_square")
        self.assertEqual(electrical["operating_voltages_v"]["repeller"],2240.)
        self.assertEqual(electrical["operating_voltages_v"]["grid1"],1760.)
        self.assertEqual(electrical["planes_z_mm"]["grid1"],-16.92918680341103)
        adapter=source("comsol/oatof_build_accelerator_geometry.m")
        self.assertIn("if nargin < 3, interfacePort = struct('enabled',false); end",adapter)
        self.assertIn("'z_accel_grid1',k,'accel_stage2_length',acceleratorRingCount+1",adapter)


    def test_common_body_uses_explicit_ring_positions_and_mechanical_hole(self):
        self.assertFalse((OA/"build_two_zone_geometry.m").exists())
        body=(OA/"build_sectioned_geometry.m").read_text(encoding="utf-8")
        self.assertIn("center = char(layout.ring_z{k})",body)
        self.assertNotIn("layout.stage2_length",body)
        adapter=source("comsol/oatof_build_accelerator_geometry.m")
        self.assertIn("layout.ring_z=arrayfun(@mm,g.ring_z_mm(:).',",adapter)
        self.assertIn("opening.width_mm",adapter)
        self.assertIn("opening.height_mm",adapter)
        self.assertIn("center(1)-g.negative_x_face_mm",adapter)
        self.assertIn("layout=rmfield(layout,'boolean_cut_padding_mm')",adapter)
        self.assertNotIn("numerical_port",adapter)
        self.assertNotIn("numerical_carve",adapter)
        self.assertIn("build_sectioned_geometry(geom1, layout, interfacePort)",adapter)

    def test_all_three_sheets_are_zero_thickness_and_embedded_in_vacuum_union(self):
        self.assertFalse((OA/"build_two_zone_grids.m").exists())
        body=(OA/"build_accelerator_grids.m").read_text(encoding="utf-8")
        self.assertIn("'WorkPlane'",body)
        self.assertIn("'Rectangle'",body)
        self.assertNotIn("'Block'",body)
        grids=source("comsol/oatof_build_grid_geometry.m")
        self.assertIn("roles={'grid1','intermediate2','grid2'}",grids)
        self.assertIn("acceleratorGridTags{:},'wp_entgrid','wp_midgrid'",grids)
        self.assertIn(".set('intbnd', true)",grids)
        self.assertIn("geometry.([role '_z_mm'])",grids)


    def test_loader_preserves_total_derivation_and_validates_third_plane_and_source_rule(self):
        loader=source("load_oatof_contract.m")
        self.assertIn("g.L_accel, a.d1_mm + a.d2_mm",loader)
        self.assertIn("a.zone2_length_mm,planes.intermediate2-planes.intermediate1",loader)
        self.assertIn("a.zone3_length_mm,planes.exit-planes.intermediate2",loader)
        self.assertIn("a.d2_mm,a.zone2_length_mm+a.zone3_length_mm",loader)
        self.assertIn("geometry_derivation.accelerator.source_center_from_repeller_mm",loader)
        self.assertIn("topology.potentials_v.(item{2})",loader)

    def test_ideal_three_zone_expression_uses_each_declared_endpoint_and_length(self):
        particle=source("comsol/oatof_configure_particle_model.m")
        self.assertIn("(V_repeller-V_grid1)/accel_stage1_length",particle)
        self.assertIn("z<z_accel_intermediate2",particle)
        self.assertIn("(V_grid1-V_intermediate2)/accel_zone2_length",particle)
        self.assertIn("(V_intermediate2-V_grid2)/accel_zone3_length",particle)
        # Existing two-zone expression remains the distinct physical topology.
        self.assertIn("V_grid1/accel_stage2_length",particle)




if __name__ == "__main__":
    unittest.main()
