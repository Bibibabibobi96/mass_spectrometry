"""Explicit scientific-map rendering uses real members and unchanged shapes."""
from __future__ import annotations

import copy
import unittest

from msplatform.components.rf_multipole.compile_design_request import compile_design_request
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.backends.simion.rf_electrode_mapping import build_simion_electrode_map
from projects.rf_multipole_ion_optics.simion.simion_geometry import render_physical_gem
from projects.rf_multipole_ion_optics.tests.domain.test_capacity_contract_versions import request
from projects.rf_multipole_ion_optics.tests.domain.test_simion_geometry import resolved_design, shell


class ScientificGeometryTests(unittest.TestCase):
    def test_real_continuous_rods_shell_and_caps_reuse_exact_shape_operators(self):
        cap = dict(aperture_radius_mm=2., thickness_mm=.5)
        source = resolved_design(shell(dict(entrance=cap, exit=cap)))
        before = copy.deepcopy(source)
        mapping = dict(rod_group_1=17, rod_group_2=23, grounded_shell=31)
        body = render_physical_gem(source, .2, electrode_group_native_ids=mapping)
        self.assertEqual(body.count("e(17)"), 2)
        self.assertEqual(body.count("e(23)"), 2)
        self.assertEqual(body.count("e(31)"), 3)
        for member in source["geometry_mm"]["enclosure_layout"]["bodies"]:
            self.assertIn(f"cylinder(0,0,{member['z_max_mm']:.12g},{member['outer_radius_mm']:.12g},,{member['z_max_mm']-member['z_min_mm']:.12g})", body)
        for rod in source["geometry_mm"]["rod_array"]["rods"]:
            expected = f"e({mapping['rod_group_'+str(rod['electrode_group'])]}) {{ fill {{ within {{ cylinder({rod['center_x_mm']:.12g},{rod['center_y_mm']:.12g},15,1,,13)"
            self.assertIn(expected, body)
        self.assertEqual(body.count("notin_inside"), 3)
        self.assertEqual(source, before)

    def test_old_native_permutation_cannot_change_scientific_gem(self):
        source = resolved_design(shell(), segmented=True)
        topology = build_electrode_topology(source)
        mapping = dict(zip((g["electrode_group_id"] for g in topology), [17,23,31,37,41], strict=True))
        before = render_physical_gem(source, .2, electrode_group_native_ids=mapping)
        permutation = {1:2, 2:1, 3:4, 4:3}
        for member in source["segmentation"]["segmented_rod_array"]["electrodes"]:
            member["electrode_id"] = permutation[member["electrode_id"]]
        self.assertEqual(render_physical_gem(source, .2, electrode_group_native_ids=mapping), before)
        for native in (17,23,31,37):
            self.assertEqual(before.count(f"e({native})"), 2)
        self.assertIn("e(41)", before)

    def test_versions_three_and_four_render_same_science_with_explicit_mapping(self):
        bodies = []
        for version in (3,4):
            author = request(version, 2)
            source = compile_design_request(author, expected_identity=author["identity"])
            before = copy.deepcopy(source)
            topology = build_electrode_topology(source)
            mapping = dict(zip((g["electrode_group_id"] for g in topology), [17,23,31,37], strict=True))
            bodies.append(render_physical_gem(source, .2, electrode_group_native_ids=mapping))
            self.assertEqual(source, before)
            if version == 4:
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    render_physical_gem(source, .2)
        self.assertEqual(bodies[0], bodies[1])
        self.assertIn("85,2,,40)", bodies[1])

    def test_invalid_or_ambiguous_maps_are_rejected_before_rendering(self):
        source = resolved_design()
        for mapping in ({}, {"rod_group_1":17}, {"rod_group_1":17,"rod_group_2":23,"extra":31},
                        {"rod_group_1":True,"rod_group_2":23}, {"rod_group_1":17,"rod_group_2":17},
                        {"rod_group_1":17,"rod_group_2":1001}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                render_physical_gem(source, .2, electrode_group_native_ids=mapping)
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            render_physical_gem(source, .2, electrode_ids={1:1,2:2},
                                electrode_group_native_ids={"rod_group_1":17,"rod_group_2":23})
        with self.assertRaises(TypeError):
            render_physical_gem(source, .2, electrode_group_native_ids={"rod_group_1":17,"rod_group_2":23},
                                **{'scientific_electrode_ids': {'rod_group_1': 31, 'rod_group_2': 37}})

    def test_polluted_or_nonfinite_real_member_shape_is_not_silently_rendered(self):
        for segmented in (False, True):
            source = resolved_design(segmented=segmented)
            mapping = build_simion_electrode_map(source, build_electrode_topology(source))
            members = (source['segmentation']['segmented_rod_array']['electrodes'] if segmented
                       else source['geometry_mm']['rod_array']['rods'])
            for change in (dict(semi_major_axis_mm=2., semi_minor_axis_mm=1., major_axis_angle_rad=.2),
                           dict(radius_mm=float('nan')), dict(center_x_mm=float('inf'))):
                before = dict(members[0]); members[0].update(change)
                with self.subTest(segmented=segmented, change=change), self.assertRaises(ValueError):
                    render_physical_gem(source,.2,electrode_group_native_ids=mapping)
                members[0].clear(); members[0].update(before)

    def test_public_500_segment_metadata_renders_and_501_rejects_capacity(self):
        for count in (500,501):
            author = request(count=count)
            source = compile_design_request(author, expected_identity=author["identity"])
            topology = build_electrode_topology(source)
            if count == 500:
                mapping = build_simion_electrode_map(source, topology)
                body = render_physical_gem(source, .2, electrode_group_native_ids=mapping)
                self.assertEqual(body.count("cylinder("), 2000)
                self.assertEqual(body.count("e(1000)"), 2)
            else:
                mapping = {g["electrode_group_id"]:i for i,g in enumerate(topology,1)}
                with self.assertRaisesRegex(ValueError, "capacity"):
                    render_physical_gem(source, .2, electrode_group_native_ids=mapping)


if __name__ == "__main__":
    unittest.main()
