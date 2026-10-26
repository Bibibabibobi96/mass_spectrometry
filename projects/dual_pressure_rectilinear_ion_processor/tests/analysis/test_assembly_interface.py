"""Independent mechanical vectors for the complete native IP interface."""
import copy
import unittest

from common.contracts.machine_contracts import validate_schema

from projects.dual_pressure_rectilinear_ion_processor.analysis.assembly_interface import (
    resolve_assembly_interface,
)


def projection():
    from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
    from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import load_config
    config = load_config()
    return native_projection(config["baseline"], config["numerics"])


class ExtractionShieldInterfaceTests(unittest.TestCase):
    def test_actual_native_guide_inlet_is_open_rod_end_not_hp_lens(self):
        from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
        from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import load_config
        config = load_config()
        native = native_projection(config["baseline"], config["numerics"])
        before = copy.deepcopy(native)
        interface = resolve_assembly_interface(native)
        validate_schema(interface, "component_geometry_interface.schema.json")
        port = interface["ports"]["guide_inlet"]
        self.assertEqual(port["center_mm"], [0, 0, 0])
        self.assertEqual(port["outward_normal"], [-1, 0, 0])
        self.assertEqual(port["surface_kind"], "open_rod_entrance")
        self.assertIsNone(port["wall_thickness_mm"])
        self.assertAlmostEqual(port["cross_section"]["inscribed_radius_mm"], 2.)
        self.assertEqual([row["component_electrode_id"] for row in interface["component_electrodes"]], list(range(1, 16)))
        self.assertTrue(all(row["electrical_group_id"] == row["component_electrode_id"] for row in interface["component_electrodes"]))
        self.assertEqual(set(interface["ports"]), {"guide_inlet", "extraction_exit"})
        self.assertEqual(native, before)

    def test_true_outer_face_width_normal_and_identity_without_mutation(self):
        source = projection()
        before = copy.deepcopy(source)
        interface = resolve_assembly_interface(source)
        validate_schema(interface, "component_geometry_interface.schema.json")
        port = interface["ports"]["extraction_exit"]
        self.assertEqual(source, before)
        self.assertEqual(interface["variant_id"], "native_ion_processor")
        self.assertIn(dict(component_electrode_id=14, role="lp_commonmode_shield", electrical_group_id=14), interface["component_electrodes"])
        self.assertEqual(port["center_mm"], [170, 3.5, 0])
        self.assertEqual(port["outward_normal"], [0, 1, 0])
        self.assertEqual(port["wall_thickness_mm"], .5)
        self.assertEqual(port["cross_section"], dict(shape="rectangle", width_mm=.8, height_mm=8,
            width_axis=[0, 0, -1], height_axis=[1, 0, 0]))

    def test_nondefault_cutout_and_wall_define_port(self):
        source = projection()
        shield = next(item for item in source["electrodes"] if item["electrode_id"] == 14)
        max(shield["solids"], key=lambda item: item["max_mm"][1])["max_mm"][1] = 3.8
        shield["cutouts"][0]["max_mm"][1] = 3.9
        shield["cutouts"][0]["min_mm"][2] = -.6
        shield["cutouts"][0]["max_mm"][2] = .6
        port = resolve_assembly_interface(source)["ports"]["extraction_exit"]
        self.assertEqual(port["center_mm"], [170, 3.8, 0])
        self.assertEqual(port["cross_section"]["width_mm"], 1.2)
        self.assertAlmostEqual(port["wall_thickness_mm"], .8)

    def test_nonpenetrating_or_open_rim_cutout_is_rejected(self):
        for bound, axis, value in (("max_mm", 1, 3.4), ("min_mm", 1, 3.1), ("max_mm", 2, 3.5)):
            with self.subTest(bound=bound, axis=axis):
                source = projection()
                next(item for item in source["electrodes"] if item["electrode_id"] == 14)["cutouts"][0][bound][axis] = value
                with self.assertRaisesRegex(ValueError, "E14.*cutout"):
                    resolve_assembly_interface(source)

    def test_missing_ambiguous_and_wrong_frame_fail_at_provider(self):
        for kind in ("missing", "duplicate", "frame"):
            source = projection()
            if kind == "missing":
                source["electrodes"] = []
            elif kind == "duplicate":
                source["electrodes"] *= 2
            else:
                source["frame_id"] = "assembly_frame"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                resolve_assembly_interface(source)
