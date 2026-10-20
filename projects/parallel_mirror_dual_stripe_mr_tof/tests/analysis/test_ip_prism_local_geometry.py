"""Pure fixtures for the local IP/P1 physical distance comparison."""
from __future__ import annotations

import copy
import re
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_geometry import prepare_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import (
    transform_shape, _bounds, _primitive,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import contains_shape


def fixture() -> dict:
    """Small CSG fixture with measured-plane z=0 and the canonical P1 shape."""
    electrodes = []
    for identifier in range(1, 16):
        low_y, high_y = (-56.25, -53.75) if identifier == 11 else (-94.5, -34.0)
        electrodes.append(dict(electrode_id=identifier, name=f"IP{identifier}",
                               solids=[dict(shape="box", min_mm=[-3, low_y, 6.3],
                                            max_mm=[3, high_y, 6.8])], cutouts=[]))
    electrodes[0]["solids"] = [dict(shape="cylinder3d", endpoints_mm=[[0, -150, 9], [0, -100, 9]], radius_mm=0.5)]
    polygon = [[-42.828, -65], [-67.828, -90], [-67.828, -40]]
    outer = [[-33, -100], [-77, -100], [-77, 5.3], [-33, 5.3]]
    return dict(frame_id="test_frame", ion_processor_electrodes=electrodes,
                prism_electrodes=[dict(id=16, station="accelerator_exit", parts=[
                    dict(x=[-12, -2], polygon_yz_mm=copy.deepcopy(polygon)),
                    dict(x=[2, 12], polygon_yz_mm=copy.deepcopy(polygon))])],
                prism_ground_shields=[dict(id=18, station="accelerator_exit", x=[-12, 12],
                    outer_polygon_yz_mm=copy.deepcopy(outer),
                    body_sections=[dict(x=[-12, 12], polygon_yz_mm=copy.deepcopy(outer))],
                    prism_clearance_polygon_yz_mm=[[-40, -65], [-70, -95], [-70, -35]],
                    rectangular_slots_mm=[[-2, -75, -100, 2, -35, 5.3]],
                    extension_to_accelerator_exit=dict(clearance_mm=1))],
                mirror_electrodes=[{"must_not_be_emitted": True}])


class IpPrismLocalGeometryTest(unittest.TestCase):
    def prepare(self, distance=10, **updates):
        arguments = dict(geometry=fixture(), ip_voltages=list(range(15)), prism_voltage=191,
                         distance_mm=distance, box_mm=[0, -105, -120, 16, -25, 25],
                         pitch_mm=[0.1, 0.2, 0.2], convergence_v=1e-5)
        arguments.update(updates)
        return prepare_geometry(**arguments)

    def test_four_distances_preserve_gap_and_change_real_solids(self):
        for distance in (52.828, 10, 15, 20):
            with self.subTest(distance=distance):
                result = self.prepare(distance)
                self.assertAlmostEqual(result["exit_z_mm"], distance - 52.828)
                self.assertAlmostEqual(result["gap_mm"], 1)
                shield = result["geometry"]["prism_ground_shields"][0]
                expected_front = 5.3 + result["delta_z_mm"]
                self.assertAlmostEqual(max(p[1] for p in shield["body_sections"][0]["polygon_yz_mm"]), expected_front)
                self.assertAlmostEqual(shield["rectangular_slots_mm"][0][5], expected_front)
                self.assertEqual(result["geometry"]["prism_electrodes"], fixture()["prism_electrodes"])
                self.assertAlmostEqual(result["geometry_checks"]["ip_to_p1_z_separation_mm"], distance - 6.528)

    def test_caller_inputs_unchanged_and_clipping_explicit(self):
        source = fixture()
        original = copy.deepcopy(source)
        result = self.prepare(geometry=source)
        self.assertEqual(source, original)
        clipped = result["geometry_checks"]["clipped_ip_solids"]
        self.assertTrue(any(r["electrode_id"] == 1 and "y" in r["clipped_axes"] for r in clipped))
        self.assertNotIn("mirror_electrodes", result["geometry"])
        self.assertIn("extrude_yz", result["gem"])
        self.assertIn("cylinder3d", result["gem"])
        self.assertIn("e(191)", result["gem"])
        self.assertEqual(result["gem"].count("e(0) {"), 7)  # IP1 at 0 V, shield, five exterior faces.
        self.assertEqual(result["geometry_checks"]["grid_dimensions"], [161, 401, 726])

    def test_convex_axis_permutation_preserves_vertices_and_exact_bounds(self):
        shape = dict(shape="convex_polyhedron", vertices_mm=[[0, 0, 0], [2, 0, 0], [0, 3, 0], [0, 0, 4]])
        original = copy.deepcopy(shape)
        transformed = transform_shape(shape, [[0, 0, -1], [1, 0, 0], [0, -1, 0]], [10, 20, 30])
        self.assertEqual(transformed, dict(shape="convex_polyhedron", vertices_mm=[
            [10, 20, 30], [10, 22, 30], [10, 20, 27], [6, 20, 30]]))
        self.assertEqual(_bounds(transformed), [6, 20, 27, 10, 22, 30])
        self.assertEqual(shape, original)
        self.assertTrue(contains_shape(transformed, [9.5, 20.25, 29.625]))
        self.assertFalse(contains_shape(transformed, [6, 22, 27]))  # Inside AABB, outside tetrahedron.

    def test_convex_primitive_is_intersection_of_outward_halfspaces(self):
        shape = dict(shape="convex_polyhedron", vertices_mm=[[0, 0, 0], [2, 0, 0], [0, 3, 0], [0, 0, 4]])
        rendered = _primitive(shape)
        self.assertNotIn("box", rendered)
        planes = [[float(v) for v in group.split(",")] for group in re.findall(r"half_space\(([^)]*)\)", rendered)]
        self.assertEqual(len(planes), 4)
        for point, expected in [([0.2, 0.3, 0.4], True), ([1.9, 2.9, 3.9], False), ([-0.1, 0.2, 0.3], False)]:
            inside = all(sum((point[a]-p[a])*p[a+3] for a in range(3)) <= 1e-12 for p in planes)
            self.assertEqual(inside, expected)
            self.assertEqual(inside, contains_shape(shape, point))

    def test_local_convex_translation_keeps_full_geometry_with_x_mirror(self):
        geometry = fixture()
        shape = dict(shape="convex_polyhedron", vertices_mm=[[-3, -55, 7], [3, -55, 7], [0, -54, 7], [0, -55, 8]])
        geometry["ion_processor_electrodes"][1]["solids"] = [shape]
        geometry["ion_processor_electrodes"][1]["cutouts"] = [copy.deepcopy(shape)]
        original = copy.deepcopy(geometry)
        result = self.prepare(geometry=geometry)
        moved = result["geometry"]["ion_processor_electrodes"][1]
        expected = [[x, y, z+result["delta_z_mm"]] for x, y, z in shape["vertices_mm"]]
        self.assertEqual(moved["solids"][0]["vertices_mm"], expected)
        self.assertEqual(moved["cutouts"][0]["vertices_mm"], expected)
        self.assertEqual(_bounds(moved["solids"][0])[:2], [-3, -55])
        self.assertEqual(_bounds(moved["solids"][0])[3:5], [3, -54])
        self.assertEqual(geometry, original)
        self.assertIn("planar,x,electrostatic", result["gem"])
        self.assertIn("half_space(", result["gem"])
        self.assertEqual(result["geometry_checks"]["negative_x_geometry"],
                         "Represented by the x=0 mirror boundary, not physical clipping")
        self.assertFalse(any(r["electrode_id"] == 2 for r in result["geometry_checks"]["clipped_ip_solids"]))

    def test_degenerate_convex_geometry_fails_before_rendering(self):
        shape = dict(shape="convex_polyhedron", vertices_mm=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]])
        for action in (lambda: transform_shape(shape, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0]),
                       lambda: _bounds(shape), lambda: _primitive(shape)):
            with self.assertRaises(ValueError):
                action()

    def aperture(self, shape="circle", **updates):
        """Test-only finite world-z plate dimensions; no production defaults."""
        spec = dict(frame_id="test_frame", shape=shape, center_mm=[0, -55, -45], normal=[0, 0, -1],
                    thickness_mm=.4, outer_half_widths_mm=[3, 1], voltage_v=0, connection="prism_ground_shield")
        spec.update(radius_mm=.3) if shape == "circle" else spec.update(half_widths_mm=[.8, .3])
        spec.update(updates)
        return spec

    def test_physical_circle_and_y_slit_are_finite_through_csg_not_virtual_masks(self):
        for shape in ("circle", "y_slit"):
            spec = self.aperture(shape)
            original = copy.deepcopy(spec)
            base = self.prepare()
            result = self.prepare(physical_aperture=spec, downstream_observation_z_mm=-98)
            plate = result["geometry"]["aperture_electrodes"][0]
            self.assertEqual(spec, original)
            self.assertEqual(plate["solids"], [dict(shape="box", min_mm=[-3, -56, -45.2], max_mm=[3, -54, -44.8])])
            self.assertTrue(plate["shield_contact"])
            self.assertEqual(plate["namespace"], "physical_aperture")
            self.assertEqual(result["geometry"]["ion_processor_electrodes"], base["geometry"]["ion_processor_electrodes"])
            self.assertEqual(result["geometry"]["prism_electrodes"], base["geometry"]["prism_electrodes"])
            self.assertEqual(result["geometry"]["prism_ground_shields"], base["geometry"]["prism_ground_shields"])
            self.assertIn("; namespace=physical_aperture", result["gem"])
            self.assertEqual(result["gem"].count("notin {"), base["gem"].count("notin {")+1)
            if shape == "circle":
                self.assertEqual(plate["cutouts"], [dict(shape="cylinder3d", endpoints_mm=[[0, -55, -45.2], [0, -55, -44.8]], radius_mm=.3)])
                self.assertIn("notin { cylinder3d(0,-55,-120.2,0,-55,25.2,0.3) }", result["gem"])
            else:
                self.assertEqual(plate["cutouts"][0]["min_mm"], [-.8, -55.3, -45.2])
                self.assertEqual(plate["cutouts"][0]["max_mm"], [.8, -54.7, -44.8])

    def test_axial_gem_tool_never_changes_physical_bore_or_plate(self):
        for pitch in ([.1, .2, .1], [.05, .1, .05]):
            for shape in ("circle", "y_slit"):
                spec = self.aperture(shape, center_mm=[0, -55, -20])
                before = copy.deepcopy(spec)
                result = self.prepare(distance=52.828, physical_aperture=spec, pitch_mm=pitch, downstream_observation_z_mm=-98)
                aperture = result["geometry"]["aperture_electrodes"][0]
                self.assertEqual(spec, before)
                self.assertEqual(aperture["solids"][0]["min_mm"][2], -20.2)
                self.assertEqual(aperture["solids"][0]["max_mm"][2], -19.8)
                tool = aperture["gem_subtraction"]["cutting_tool"]
                z = [-120-pitch[2], 25+pitch[2]]
                self.assertEqual(aperture["gem_subtraction"]["cutting_tool_z_extent_mm"], z)
                self.assertFalse(aperture["gem_subtraction"]["physical_geometry_changed"])
                self.assertEqual(aperture["gem_subtraction"]["transverse_hole_expansion_mm"], 0)
                physical = aperture["cutouts"][0]
                if shape == "circle":
                    self.assertEqual(physical["endpoints_mm"], [[0, -55, -20.2], [0, -55, -19.8]])
                    self.assertEqual(tool["radius_mm"], physical["radius_mm"])
                    self.assertEqual([p[:2] for p in tool["endpoints_mm"]], [p[:2] for p in physical["endpoints_mm"]])
                    self.assertEqual([p[2] for p in tool["endpoints_mm"]], z)
                else:
                    self.assertEqual(physical["min_mm"][2], -20.2)
                    self.assertEqual(physical["max_mm"][2], -19.8)
                    self.assertEqual(tool["min_mm"][:2], physical["min_mm"][:2])
                    self.assertEqual(tool["max_mm"][:2], physical["max_mm"][:2])
                    self.assertEqual([tool["min_mm"][2], tool["max_mm"][2]], z)

    def test_aperture_electrical_contact_uses_actual_shield_holes_not_outer_envelope(self):
        # Fully inside the rectangular x=+-2 mm channel: no metal connection.
        spec = self.aperture(outer_half_widths_mm=[1, 1], connection="isolated", voltage_v=12)
        result = self.prepare(physical_aperture=spec, downstream_observation_z_mm=-98)
        self.assertFalse(result["geometry"]["aperture_electrodes"][0]["shield_contact"])
        with self.assertRaisesRegex(ValueError, "shield contact differs"):
            self.prepare(physical_aperture=dict(spec, connection="prism_ground_shield", voltage_v=0), downstream_observation_z_mm=-98)
        with self.assertRaisesRegex(ValueError, "shield contact differs"):
            self.prepare(physical_aperture=self.aperture(connection="isolated"), downstream_observation_z_mm=-98)
        # Wider than that channel, yet inside the real triangular shield cutout.
        clear = self.aperture(center_mm=[0, -55, -51.5], thickness_mm=.2, connection="isolated")
        result = self.prepare(physical_aperture=clear, downstream_observation_z_mm=-98)
        self.assertFalse(result["geometry"]["aperture_electrodes"][0]["shield_contact"])
        with self.assertRaisesRegex(ValueError, "shield contact differs"):
            self.prepare(physical_aperture=dict(clear, connection="prism_ground_shield"), downstream_observation_z_mm=-98)
        # An exact shared face at the channel wall is a contact, not just volume overlap.
        face = self.aperture(outer_half_widths_mm=[2, 1])
        result = self.prepare(physical_aperture=face, downstream_observation_z_mm=-98)
        self.assertTrue(result["geometry"]["aperture_electrodes"][0]["shield_contact"])

    def test_aperture_cannot_hide_corner_contact_with_p1_or_connect_at_different_voltage(self):
        with self.assertRaisesRegex(ValueError, "nonzero P1 material"):
            self.prepare(physical_aperture=self.aperture(center_mm=[0, -55, -60]), downstream_observation_z_mm=-98)
        # Mean-axis point lies before P1; the lower-y plate corner intersects it.
        with self.assertRaisesRegex(ValueError, "nonzero P1 material"):
            self.prepare(physical_aperture=self.aperture(center_mm=[0, -55, -52.4],
                         outer_half_widths_mm=[3, 1.1], thickness_mm=.2), downstream_observation_z_mm=-98)
        with self.assertRaisesRegex(ValueError, "zero volts"):
            self.prepare(physical_aperture=self.aperture(voltage_v=1), downstream_observation_z_mm=-98)

    def test_aperture_contract_mirror_domain_and_ordering_fail_closed(self):
        updates = [dict(extra=True), dict(frame_id="wrong"), dict(normal=[1, 0, 0]),
                   dict(center_mm=[.1, -55, -45]), dict(thickness_mm=0), dict(voltage_v=float("nan")),
                   dict(outer_half_widths_mm=[16, 1]), dict(radius_mm=1), dict(connection="assumed_ground"),
                   dict(center_mm=[0, -55, -42]), dict(center_mm=[0, -55, -99]), dict(shape="circle", half_widths_mm=[1, 1])]
        for update in updates:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.prepare(physical_aperture=self.aperture(**update), downstream_observation_z_mm=-98)
        with self.assertRaisesRegex(ValueError, "downstream observation"):
            self.prepare(physical_aperture=self.aperture())

    def test_null_physical_aperture_preserves_existing_geometry_and_gem(self):
        original = self.prepare()
        explicit = self.prepare(physical_aperture=None)
        self.assertEqual(explicit, original)
        self.assertNotIn("aperture_electrodes", original["geometry"])

    def lens(self, **updates):
        spec = dict(name="Q1", frame_id="test_frame", center_mm=[0,-55,-13],
                    length_mm=3, inscribed_radius_mm=1.4, rod_radius_mm=.2, voltage_v=12.5)
        spec.update(updates)
        return spec

    def test_empty_lenses_preserve_exact_old_result(self):
        old = self.prepare(distance=52.828)
        self.assertEqual(old,self.prepare(distance=52.828,lens_elements=None))
        self.assertEqual(old,self.prepare(distance=52.828,lens_elements=[]))
        self.assertNotIn("lens_electrodes",old["geometry"])

    def test_quadrupole_has_real_four_rods_and_three_half_domain_primitives(self):
        spec = self.lens()
        original = copy.deepcopy(spec)
        base = self.prepare(distance=52.828)
        result = self.prepare(distance=52.828,lens_elements=[spec],downstream_observation_z_mm=-98)
        self.assertEqual(spec,original)
        rods = result["geometry"]["lens_electrodes"]
        self.assertEqual(len(rods),4)
        self.assertEqual(len({r["electrode_id"] for r in rods}),4)
        for rod in rods:
            self.assertEqual(rod["namespace"],"quadrupole_lens")
            self.assertEqual(rod["specification"],spec)
            self.assertEqual(rod["cutouts"],[])
            solid = rod["solids"][0]
            self.assertEqual(solid["shape"],"cylinder3d")
            self.assertEqual(solid["radius_mm"],.2)
            self.assertEqual([p[2] for p in solid["endpoints_mm"]],[-14.5,-11.5])
            center = solid["endpoints_mm"][0]
            self.assertAlmostEqual(abs(center[0] if rod["pair"]=="x" else center[1]+55),1.6)
            self.assertEqual(rod["voltage_v"],12.5 if rod["pair"]=="x" else -12.5)
            self.assertEqual(rod["represented_by_x_mirror"],rod["pair"]=="x" and center[0]<0)
        for key in ("ion_processor_electrodes","prism_electrodes","prism_ground_shields"):
            self.assertEqual(result["geometry"][key],base["geometry"][key])
        self.assertEqual(result["gem"].count("; namespace=quadrupole_lens"),3)
        self.assertEqual(result["gem"].count("cylinder3d("),base["gem"].count("cylinder3d(")+3)
        self.assertEqual(result["gem"].count("e(12.5) {"),1)
        self.assertEqual(result["gem"].count("e(-12.5) {"),2)
        self.assertIn("PASS_sufficient_conservative",result["geometry_checks"]["lens_geometry_checks"]["status"])

    def test_doublet_polarity_and_input_order_are_explicit(self):
        elements=[self.lens(),self.lens(name="Q2",center_mm=[0,-55,-20],length_mm=4,voltage_v=-17)]
        result=self.prepare(distance=52.828,lens_elements=elements,downstream_observation_z_mm=-98)
        reverse=self.prepare(distance=52.828,lens_elements=list(reversed(elements)),downstream_observation_z_mm=-98)
        self.assertEqual(result,reverse)
        second=[r for r in result["geometry"]["lens_electrodes"] if r["element_name"]=="Q2"]
        self.assertEqual([r["voltage_v"] for r in second],[-17,-17,17,17])

    def test_lens_contract_rejects_malformed_nonfinite_unknown_and_duplicate(self):
        changes=[dict(extra=1),dict(name=""),dict(frame_id="other"),dict(center_mm=[0,-55]),
                 dict(center_mm=[True,-55,-13]),dict(center_mm=[.1,-55,-13]),
                 dict(length_mm=True),dict(length_mm=0),dict(rod_radius_mm=-1),
                 dict(inscribed_radius_mm=float("inf")),dict(voltage_v=float("nan"))]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.prepare(distance=52.828,lens_elements=[self.lens(**change)],downstream_observation_z_mm=-98)
        for elements in ({},"quad",[self.lens(),self.lens()]):
            with self.subTest(elements=elements),self.assertRaises(ValueError):
                self.prepare(distance=52.828,lens_elements=elements,downstream_observation_z_mm=-98)

    def test_lens_order_domain_and_metal_contacts_fail_closed(self):
        changes=[dict(center_mm=[0,-55,-1],length_mm=2),dict(center_mm=[0,-55,-97],length_mm=2),
                 dict(center_mm=[0,-26,-13]),dict(inscribed_radius_mm=1.6),
                 dict(inscribed_radius_mm=.1,rod_radius_mm=.8),
                 dict(center_mm=[0,-55,-60],inscribed_radius_mm=2)]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.prepare(distance=52.828,lens_elements=[self.lens(**change)],downstream_observation_z_mm=-98)
        with self.assertRaisesRegex(ValueError,"contact each other"):
            self.prepare(distance=52.828,lens_elements=[self.lens(),self.lens(name="Q2")],downstream_observation_z_mm=-98)
        with self.assertRaisesRegex(ValueError,"downstream observation"):
            self.prepare(distance=52.828,lens_elements=[self.lens()])

    def test_lens_clearance_recognizes_real_ground_slot_and_retains_contacts(self):
        geometry=fixture()
        geometry["prism_ground_shields"][0]["rectangular_slots_mm"]=[]
        with self.assertRaisesRegex(ValueError,"actual shield"):
            self.prepare(distance=52.828,geometry=geometry,lens_elements=[self.lens()],downstream_observation_z_mm=-98)
        geometry=fixture()
        # A separate IP solid in the measured downstream region must not be hidden.
        geometry["ion_processor_electrodes"][0]["solids"]=[dict(shape="box",min_mm=[1.5,-55.1,-14],max_mm=[1.7,-54.9,-12])]
        with self.assertRaises(ValueError):
            self.prepare(distance=52.828,geometry=geometry,lens_elements=[self.lens()],downstream_observation_z_mm=-98)

    def test_invalid_geometry_gap_and_grid_fail(self):
        for changes in (dict(distance_mm=5), dict(distance_mm=float("nan")),
                        dict(pitch_mm=[0.015, 0.2, 0.2]), dict(ip_voltages=[0]*14),
                        dict(box_mm=[1, -105, -120, 16, -25, 25]), dict(convergence_v=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(**changes)
        geometry = fixture()
        geometry["prism_ground_shields"][0]["extension_to_accelerator_exit"]["clearance_mm"] = 2
        with self.assertRaisesRegex(ValueError, "1 mm"):
            self.prepare(geometry=geometry)


if __name__ == "__main__":
    unittest.main()
