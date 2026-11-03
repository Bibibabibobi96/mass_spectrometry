"""Pure geometry regressions for the existing sectioned provider adapter."""
from __future__ import annotations

from projects.orthogonal_accelerator.analysis.sectioned_geometry import resolve_bare_three_zone_component

import copy
import unittest

from projects.orthogonal_accelerator.simion.bare_three_zone_component import (
    render_bare_three_zone_electrode_body,
)
from projects.orthogonal_accelerator.simion.sectioned_accelerator import render_accelerator_local_geometry


def three_zone_requirements_fixture() -> dict:
    """An explicit compact functional fixture, not a literature/default design."""
    return dict(schema_version=1, role="orthogonal_accelerator_bare_three_zone_requirements", variant_id="three_zone",
        geometry=dict(cross_section="square", axis_x_mm=0., axis_y_mm=0., shield_center_z_mm=15.,
            shield_outer_width_mm=34., shield_inner_width_mm=32., shield_span_z_mm=38.,
            negative_x_face_mm=-17., shield_wall_mm=1., shield_back_z_mm=-4.,
            port_center_y_mm=0., port_center_z_mm=2., numerical_port_width_mm=3., numerical_port_height_mm=2.8,
            electrode_width_mm=30., bore_width_mm=26., repeller_front_z_mm=0., repeller_thickness_mm=1.,
            grid1_z_mm=4., intermediate2_z_mm=14., grid2_z_mm=34., ring_count=4,
            ring_thickness_mm=.5, ring_z_mm=[6., 10., 20., 28.]))


class BareThreeZoneComponentTests(unittest.TestCase):
    def test_body_is_exact_existing_provider_with_explicit_namespace(self):
        for cross_section in ("square", "cylindrical"):
            request = three_zone_requirements_fixture()
            request["geometry"]["cross_section"] = cross_section
            resolved = resolve_bare_three_zone_component(request)
            ids = {i: i+40 for i in range(1, 10)}
            mapped = {k: [ids[i] for i in v] if isinstance(v, list) else ids[v]
                      for k, v in resolved["electrodes"].items()}
            actual = render_bare_three_zone_electrode_body(resolved, cell_mm_xyz=dict(x=.2,y=.1,z=.1), local_electrode_ids=ids)
            expected = render_accelerator_local_geometry(request["geometry"], cell_x_mm=.2,cell_z_mm=.1,
                                                        electrodes=mapped,render_intermediate2_sheet=True)
            self.assertEqual(actual, expected)
            self.assertEqual(resolved["port"]["normal_axis"], "x")
            self.assertEqual(resolved["port"]["boolean_boundary_policy"], "exclude_shape_inside_or_on_v1")
            self.assertNotIn("grid_supports", resolved["canonical_electrodes"])
            self.assertEqual([s["name"] for s in resolved["canonical_electrodes"]["ideal_sheets"]], ["grid1","intermediate2","exit"])

    def test_no_hidden_dimensions_or_invalid_clearance(self):
        original = three_zone_requirements_fixture()
        for mutation in ("missing", "unknown", "wall", "port", "plane", "ring", "no_zone3"):
            request = copy.deepcopy(original)
            g = request["geometry"]
            if mutation == "missing": del g["ring_thickness_mm"]
            elif mutation == "unknown": g["implicit_voltage"] = 0
            elif mutation == "wall": g["shield_wall_mm"] = 2.
            elif mutation == "port": g["numerical_port_height_mm"] = 4.
            elif mutation == "plane": g["intermediate2_z_mm"] = 40.
            elif mutation == "ring": g["ring_z_mm"][0] = 4.
            else: g["ring_z_mm"] = [6.,7.,8.,9.]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                resolve_bare_three_zone_component(request)

    def test_actual_axis_and_namespace_cannot_be_replaced_by_dummy_electrodes(self):
        request = three_zone_requirements_fixture()
        g = request["geometry"]
        g.update(axis_x_mm=3.,axis_y_mm=2.,negative_x_face_mm=-14.,port_center_y_mm=2.)
        resolved = resolve_bare_three_zone_component(request)
        self.assertEqual(resolved["actual_bounds_mm"]["x_min"], -14.)
        self.assertEqual(resolved["port"]["center_mm"], [-13.5,2.,2.])
        with self.assertRaises(ValueError):
            render_bare_three_zone_electrode_body(resolved, cell_mm_xyz=dict(x=.1,y=.2,z=.1), local_electrode_ids={1:9})


    def test_instrument_projection_is_explicit_and_does_not_grant_first_gap_capability(self):
        from projects.orthogonal_accelerator.analysis.sectioned_geometry import project_instrument_sectioned_mechanics
        from projects.orthogonal_accelerator.analysis.electrode_topology import _mechanical_groups

        request = three_zone_requirements_fixture()
        request["geometry"]["numerical_port_height_mm"] = 4.0
        before = copy.deepcopy(request)
        with self.assertRaisesRegex(ValueError, "first gap"):
            resolve_bare_three_zone_component(request)
        source = dict(schema_version=1, role="oatof_validated_sectioned_accelerator_geometry",
                      producer="single_reflection_oa_tof_mass_analyzer", frame_id="oatof_global",
                      geometry=request["geometry"])
        low = project_instrument_sectioned_mechanics(source)
        self.assertEqual(low["geometry"], request["geometry"])
        self.assertEqual(low["port"]["height_mm"], 4)
        self.assertFalse(low["standalone_component_capability"])
        self.assertEqual(_mechanical_groups(low)[1][3][0], "intermediate_grid_2")
        self.assertEqual(request, before)
        for key, value in (("producer", "unknown"), ("schema_version", 2),
                           ("schema_version", True), ("role", "unknown"), ("frame_id", "unknown")):
            invalid = copy.deepcopy(source)
            invalid[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "source"):
                project_instrument_sectioned_mechanics(invalid)
        for key, value in (("producer", "unknown"), ("source_schema_version", 2),
                           ("standalone_component_capability", True)):
            invalid = copy.deepcopy(low)
            invalid[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "source or capability"):
                _mechanical_groups(invalid)

    def test_shared_mechanical_constructor_keeps_original_standalone_vectors(self):
        from projects.orthogonal_accelerator.analysis.sectioned_geometry import project_instrument_sectioned_mechanics

        request = three_zone_requirements_fixture()
        standalone = resolve_bare_three_zone_component(request)
        projected = project_instrument_sectioned_mechanics(dict(
            schema_version=1, role="oatof_validated_sectioned_accelerator_geometry",
            producer="single_reflection_oa_tof_mass_analyzer", frame_id="oatof_global", geometry=request["geometry"],
        ))
        for key in standalone:
            if key != "role":
                self.assertEqual(projected[key], standalone[key], key)
        self.assertEqual(standalone["canonical_electrodes"]["repeller"]["solid_box_mm"],
                         dict(x_min_mm=-15, x_max_mm=15, y_min_mm=-15, y_max_mm=15, z_min_mm=-1, z_max_mm=0))


if __name__ == "__main__":
    unittest.main()
