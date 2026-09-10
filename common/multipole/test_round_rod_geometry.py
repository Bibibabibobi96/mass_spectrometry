import json
import hashlib
import math
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    compile_design_request,
)
from common.multipole.interface_geometry import build_axial_interface_layout
from common.multipole.round_rod_geometry import (
    build_rod_array,
    build_round_rod_array,
    points_inside_rods,
)
from common.multipole.simion_geometry import (
    render_axis_mapped_segmented_rod_array_gem,
    render_gem,
    render_grouped_rod_array_gem,
    render_segmented_rod_array_gem,
)
from common.multipole import simion_geometry
ROOT = Path(__file__).resolve().parents[2]


class RoundRodGeometryTest(unittest.TestCase):
    def test_comsol_renderer_keeps_round_default_and_adds_explicit_ellipse(self):
        source = (ROOT / "common/comsol/create_multipole_round_rods.m").read_text(
            encoding="utf-8"
        )
        self.assertIn("if isRound", source)
        self.assertIn("'Cylinder'", source)
        self.assertIn("'ECone'", source)
        self.assertIn("set('rat','1')", source)
        self.assertIn("major_axis_angle_rad", source)

    def test_round_default_preserves_legacy_document_bytes_and_values(self):
        inputs = {
            "radial_order_n": 2,
            "electrode_count": 4,
            "inscribed_radius_r0_mm": 4.0,
            "rod_radius_mm": 4.592,
            "rod_z_min_mm": 5.8,
            "rod_z_max_mm": 85.4,
            "orientation_rad": 0.17,
        }
        center_radius = inputs["inscribed_radius_r0_mm"] + inputs["rod_radius_mm"]
        rods = []
        for index in range(inputs["electrode_count"]):
            angle = inputs["orientation_rad"] + 2 * math.pi * index / inputs["electrode_count"]
            rods.append(
                {
                    "rod_id": index + 1,
                    "electrode_group": 1 if index % 2 == 0 else 2,
                    "angle_rad": angle,
                    "center_x_mm": center_radius * math.cos(angle),
                    "center_y_mm": center_radius * math.sin(angle),
                    "radius_mm": inputs["rod_radius_mm"],
                    "z_min_mm": inputs["rod_z_min_mm"],
                    "z_max_mm": inputs["rod_z_max_mm"],
                }
            )
        legacy = {
            "inscribed_radius_r0": inputs["inscribed_radius_r0_mm"],
            "rod_radius": inputs["rod_radius_mm"],
            "rod_center_radius": center_radius,
            "rod_length": inputs["rod_z_max_mm"] - inputs["rod_z_min_mm"],
            "rods": rods,
        }
        default = build_rod_array(**inputs)
        wrapper = build_round_rod_array(**inputs)
        self.assertEqual(default, legacy)
        self.assertEqual(wrapper, legacy)
        self.assertEqual(
            json.dumps(default, separators=(",", ":")),
            json.dumps(legacy, separators=(",", ":")),
        )

    def test_ellipse_centers_orientation_and_point_membership(self):
        array = build_rod_array(
            radial_order_n=2,
            electrode_count=4,
            inscribed_radius_r0_mm=3.74,
            rod_z_min_mm=0.0,
            rod_z_max_mm=20.0,
            cross_section={
                "shape": "ellipse",
                "semi_major_axis_mm": 4.3,
                "semi_minor_axis_mm": 1.88,
                "major_axis_orientation": "tangential",
            },
        )
        self.assertAlmostEqual(array["rod_center_radius"], 5.62)
        first, opposite = array["rods"][0], array["rods"][2]
        self.assertAlmostEqual(first["center_x_mm"], 5.62)
        self.assertAlmostEqual(first["center_y_mm"], 0.0)
        self.assertAlmostEqual(first["major_axis_angle_rad"], math.pi / 2)
        self.assertAlmostEqual(
            (first["center_x_mm"] - first["semi_minor_axis_mm"])
            - (opposite["center_x_mm"] + opposite["semi_minor_axis_mm"]),
            7.48,
        )
        for rod in array["rods"]:
            relative_angle = (rod["major_axis_angle_rad"] - rod["angle_rad"]) % math.pi
            self.assertAlmostEqual(relative_angle, math.pi / 2)
        points = np.array(
            [
                [first["center_x_mm"], first["center_y_mm"]],
                [first["center_x_mm"], first["center_y_mm"] + 4.3],
                [first["center_x_mm"], first["center_y_mm"] + 4.31],
                [0.0, 0.0],
            ]
        )
        np.testing.assert_array_equal(
            points_inside_rods(points, array),
            np.array([True, True, False, False]),
        )
        radial = build_rod_array(
            radial_order_n=2,
            electrode_count=4,
            inscribed_radius_r0_mm=3.74,
            rod_z_min_mm=0.0,
            rod_z_max_mm=20.0,
            cross_section={
                "shape": "ellipse",
                "semi_major_axis_mm": 4.3,
                "semi_minor_axis_mm": 1.88,
                "major_axis_orientation": "radial",
            },
        )
        self.assertAlmostEqual(radial["rod_center_radius"], 8.04)
        self.assertAlmostEqual(radial["rods"][0]["major_axis_angle_rad"], 0.0)

    def test_segmented_renderer_canonical_family_geometry_and_hashes(self):
        expected = {
            "quadrupole": (16, 4, "427647f0200eda36fad92c40a0c36739ca6d316bcbf7e7e8fc7d5f67dff960f7", "c811a0ff39044a3caee40dc3b058cfd7bc77c53edb1045340a304481e15a2b7d"),
            "hexapole": (24, 6, "be36a3afbd12358358050ec7f738be1b23b11680ad20e95414f398a8d117fb68", "ee39c8445a1c7a090130b37d43e9d71c54db74d30cc0518132386cc8601c3d36"),
            "octupole": (32, 8, "934f81aff5ac381240a0c353ad0f701083afb9b02c3a13c18fbd39e64d65a087", "3e80b28238e8e0b39c43a78d829d6c64fb3842666b61ec4b7601ef8cc7a4be45"),
        }
        for family, (rod_count, center_count, canonical_sha256, mapped_sha256) in expected.items():
            with self.subTest(family=family):
                resolved = json.loads(
                    (
                        ROOT
                        / f"projects/rf_{family}_ion_optics/config/resolved_design_no_acceleration_full_length.json"
                    ).read_text(encoding="utf-8")
                )
                segmented = resolved["segmentation"]["segmented_rod_array"]
                electrodes = segmented["electrodes"]
                self.assertEqual(segmented["segment_count"], 4)
                self.assertEqual(len(electrodes), rod_count)
                self.assertEqual(
                    len({(item["center_x_mm"], item["center_y_mm"]) for item in electrodes}),
                    center_count,
                )
                self.assertEqual({item["radius_mm"] for item in electrodes}, {2.0})
                self.assertEqual(
                    {int(item["electrode_id"]) for item in electrodes}, set(range(1, 9))
                )
                self.assertEqual(
                    len({(item["z_min_mm"], item["z_max_mm"]) for item in electrodes}), 4
                )
                gem = render_segmented_rod_array_gem(segmented)
                self.assertEqual(hashlib.sha256(gem.encode()).hexdigest(), canonical_sha256)
                mapped = render_axis_mapped_segmented_rod_array_gem(
                    segmented,
                    axial_origin_mm=-148.4,
                    transverse_origin_mm=(2.5, -1.25),
                    rotation_axis=1,
                    rotation_degrees=90,
                    indent="  ",
                    significant_digits=12,
                )
                self.assertEqual(len(mapped.splitlines()), rod_count)
                self.assertEqual(hashlib.sha256(mapped.encode()).hexdigest(), mapped_sha256)

    def test_segmented_renderer_rejects_invalid_primitives(self):
        valid = {
            "segment_count": 2,
            "electrodes": [
                {
                    "electrode_id": electrode_id,
                    "center_x_mm": float(electrode_id),
                    "center_y_mm": 1.0,
                    "z_min_mm": 0.0,
                    "z_max_mm": 1.0,
                    "radius_mm": 0.5,
                }
                for electrode_id in range(1, 5)
            ],
        }
        render_segmented_rod_array_gem(valid)
        for label, pattern, mutate in (
            ("segment_count", "segments", lambda value: value.update(segment_count=True)),
            ("length", "length", lambda value: value["electrodes"][0].update(z_max_mm=0.0)),
            ("radius", "finite", lambda value: value["electrodes"][0].update(radius_mm=float("nan"))),
            ("incomplete", "incomplete", lambda value: value["electrodes"][0].pop("center_x_mm")),
            ("bool_id", "namespace", lambda value: value["electrodes"][0].update(electrode_id=True)),
            ("fractional_id", "namespace", lambda value: value["electrodes"][0].update(electrode_id=1.5)),
            ("gapped_id", "complete", lambda value: value["electrodes"][0].update(electrode_id=5)),
        ):
            with self.subTest(label=label):
                candidate = json.loads(json.dumps(valid))
                mutate(candidate)
                with self.assertRaisesRegex(ValueError, pattern):
                    render_segmented_rod_array_gem(candidate)

    def test_axis_mapped_renderer_strictly_validates_placement(self):
        resolved = json.loads(
            (
                ROOT
                / "projects/rf_quadrupole_ion_optics/config/resolved_design_no_acceleration_full_length.json"
            ).read_text(encoding="utf-8")
        )
        segmented = resolved["segmentation"]["segmented_rod_array"]
        base = {
            "axial_origin_mm": 0.0,
            "transverse_origin_mm": (0.0, 0.0),
            "rotation_axis": 1,
            "rotation_degrees": 90.0,
            "indent": "  ",
            "significant_digits": 12,
        }
        for label, pattern, override in (
            ("bool_origin", "axial_origin", {"axial_origin_mm": True}),
            ("nan_origin", "finite", {"axial_origin_mm": float("nan")}),
            ("inf_transverse", "finite", {"transverse_origin_mm": (0.0, float("inf"))}),
            ("list_transverse", "tuple", {"transverse_origin_mm": [0.0, 0.0]}),
            ("bool_axis", "selector", {"rotation_axis": True}),
            ("fractional_axis", "selector", {"rotation_axis": 1.5}),
            ("invalid_axis", "selector 1", {"rotation_axis": 2}),
            ("nan_degrees", "finite", {"rotation_degrees": float("nan")}),
            ("bool_degrees", "rotation_degrees", {"rotation_degrees": False}),
            ("bool_digits", "significant_digits", {"significant_digits": True}),
            ("low_digits", "significant_digits", {"significant_digits": 0}),
            ("high_digits", "significant_digits", {"significant_digits": 18}),
            ("bad_indent", "indent", {"indent": "\t"}),
        ):
            with self.subTest(label=label):
                kwargs = {**base, **override}
                with self.assertRaisesRegex(ValueError, pattern):
                    render_axis_mapped_segmented_rod_array_gem(segmented, **kwargs)

    def test_production_render_gem_uses_shared_local_segmented_primitive(self):
        for family in ("quadrupole", "hexapole", "octupole"):
            resolved = json.loads(
                (
                    ROOT
                    / f"projects/rf_{family}_ion_optics/config/resolved_design_no_acceleration_full_length.json"
                ).read_text(encoding="utf-8")
            )
            with self.subTest(family=family), patch.object(
                simion_geometry,
                "_render_local_segmented_rod_array_gem",
                wraps=simion_geometry._render_local_segmented_rod_array_gem,
            ) as renderer:
                gem = render_gem(resolved, 0.2)
                renderer.assert_called_once_with(
                    resolved["segmentation"]["segmented_rod_array"],
                    indent="  ",
                    significant_digits=12,
                )
                local = simion_geometry._render_local_segmented_rod_array_gem(
                    resolved["segmentation"]["segmented_rod_array"],
                    indent="  ",
                    significant_digits=12,
                )
                self.assertIn(local, gem)

    def test_quadrupole_uses_same_array_generator(self):
        array = build_round_rod_array(
            radial_order_n=2,
            electrode_count=4,
            inscribed_radius_r0_mm=4.0,
            rod_radius_mm=4.592,
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
        )
        self.assertEqual([rod["electrode_group"] for rod in array["rods"]], [1, 2, 1, 2])
        positions = [(round(rod["center_x_mm"], 12), round(rod["center_y_mm"], 12)) for rod in array["rods"]]
        self.assertEqual(positions, [(8.592, 0.0), (0.0, 8.592), (-8.592, 0.0), (0.0, -8.592)])
        gem = render_grouped_rod_array_gem(array)
        self.assertIn("cylinder(8.592,0,0, 4.592,, 79.6)", gem)
        self.assertEqual(gem.count("fill { within { cylinder"), 4)

    def test_shared_interface_layout_supports_direct_and_connected_ends(self):
        base = {
            "aperture_radius_mm": 1.2,
            "plate_thickness_mm": 0.8,
            "rod_clearance_mm": 4.0,
            "connector_length_mm": 0.0,
            "connector_shape": "rectangular_bore",
            "release_offset_mm": 1.0,
        }
        exit_interface = dict(base, aperture_radius_mm=3.6, connector_length_mm=2.0)
        exit_interface["census_offset_mm"] = exit_interface.pop("release_offset_mm")
        layout = build_axial_interface_layout(
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
            entrance=base,
            exit_interface=exit_interface,
        )
        self.assertEqual(layout["entrance"]["connector_length_mm"], 0.0)
        self.assertAlmostEqual(layout["entrance"]["release_plane_z_mm"], 0.0)
        self.assertAlmostEqual(layout["exit"]["handoff_plane_z_mm"], 92.2)
        self.assertAlmostEqual(layout["exit"]["census_plane_z_mm"], 93.2)

    def test_axial_layout_accepts_interfaces_without_connector_shape(self):
        entrance = {
            "aperture_radius_mm": 1.2,
            "plate_thickness_mm": 0.8,
            "rod_clearance_mm": 4.0,
            "connector_length_mm": 0.0,
            "release_offset_mm": 1.0,
        }
        exit_interface = dict(entrance)
        exit_interface["census_offset_mm"] = exit_interface.pop("release_offset_mm")
        layout = build_axial_interface_layout(
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
            entrance=entrance,
            exit_interface=exit_interface,
        )
        self.assertNotIn("connector_shape", layout["entrance"])

    def resolve(self, project: str, ratio: float):
        root = ROOT / "projects" / project
        request = json.loads(
            (root / "config/requests/mechanical_base.json").read_text(encoding="utf-8")
        )
        request["geometry_mm"]["rod_radius_ratio"] = ratio
        return compile_design_request(request, expected_identity=request["identity"])

    def test_hexapole_and_octupole_share_one_generator(self):
        for project, count, ratio in (
            ("rf_hexapole_ion_optics", 6, 0.55),
            ("rf_octupole_ion_optics", 8, 0.36),
        ):
            geometry = self.resolve(project, ratio)
            rods = geometry["geometry_mm"]["rod_array"]["rods"]
            self.assertEqual(len(rods), count)
            self.assertEqual([rod["electrode_group"] for rod in rods], [1, 2] * (count // 2))
            for rod in rods:
                radius = math.hypot(rod["center_x_mm"], rod["center_y_mm"])
                self.assertAlmostEqual(
                    radius, geometry["geometry_mm"]["rod_array"]["rod_center_radius"]
                )

    def test_zero_length_connector_is_direct_connection(self):
        geometry = self.resolve("rf_hexapole_ion_optics", 0.55)
        self.assertEqual(geometry["interfaces_mm"]["entrance"]["connector_length_mm"], 0.0)
        self.assertEqual(geometry["interfaces_mm"]["exit"]["connector_length_mm"], 0.0)
        self.assertEqual(
            geometry["interfaces_mm"]["entrance"]["connector_shape"],
            "cylindrical_bore",
        )

    def test_same_geometry_exports_all_rods_to_simion(self):
        resolved = json.loads(
            (
                ROOT
                / "projects/rf_octupole_ion_optics/config/resolved_design_no_acceleration_full_length.json"
            ).read_text()
        )
        gem = render_gem(resolved, 0.2)
        self.assertEqual(gem.count("e(1) { fill { within { cylinder"), 4)
        self.assertEqual(gem.count("e(2) { fill { within { cylinder"), 4)
        self.assertIn("planar,none", gem)
        self.assertIn(f"parent_resolved_sha256={resolved['resolved_sha256']}", gem)

    def test_positive_connector_shifts_planes_and_exports_tube(self):
        request = json.loads(
            (ROOT / "projects/rf_hexapole_ion_optics/config/requests/baseline.json").read_text()
        )
        request["geometry_mm"]["exit_interface"]["connector_length_mm"] = 2.0
        request["geometry_mm"]["enclosure"]["vacuum_z_max_mm"] += 2.0
        resolved = compile_design_request(request, expected_identity=request["identity"])
        self.assertEqual(resolved["interfaces_mm"]["exit"]["connector_length_mm"], 2.0)
        self.assertIn(",,2)", render_gem(resolved, 0.2))

    def test_design_request_rejects_unknown_connector_shape(self):
        root = ROOT / "projects/rf_hexapole_ion_optics"
        request = json.loads(
            (root / "config/requests/mechanical_base.json").read_text(encoding="utf-8")
        )
        request["geometry_mm"]["entrance_interface"]["connector_shape"] = "square"
        with self.assertRaisesRegex(MultipoleDesignCompileError, "connector_shape"):
            compile_design_request(request, expected_identity=request["identity"])

    def test_segmented_simion_geometry_separates_rods_ground_and_output(self):
        resolved = json.loads(
            (
                ROOT
                / "projects/rf_hexapole_ion_optics/config/resolved_design_no_acceleration_full_length.json"
            ).read_text(encoding="utf-8")
        )
        segmented = resolved["segmentation"]["segmented_rod_array"]
        gem = render_gem(resolved, 0.2)
        for electrode_id in range(1, 9):
            self.assertIn(f"e({electrode_id}) {{ fill {{ within {{ cylinder", gem)
        self.assertIn("e(9) { fill {", gem)
        self.assertIn("e(10) { fill {", gem)
        self.assertNotIn("e(3) { fill {\n    within { cylinder(0,0", gem)
        quad_gem = render_segmented_rod_array_gem(segmented)
        self.assertEqual(quad_gem.count("locate(0,0,"), 24)
        self.assertIn("e(8) { fill { within { cylinder(", quad_gem)
        first = segmented["electrodes"][0]
        self.assertIn(f"locate(0,0,{first['z_max_mm']:.15g})", quad_gem)

    def test_exit_aperture_plate_mode_keeps_continuous_rods_and_separates_output(self):
        resolved = json.loads(
            (
                ROOT
                / "projects/rf_hexapole_ion_optics/config/resolved_design_no_acceleration_full_length.json"
            ).read_text()
        )
        with self.assertRaises(TypeError):
            render_gem(resolved, 0.2, separate_output_electrode=True)

    def test_design_request_rejects_negative_connector_length(self):
        root = ROOT / "projects/rf_hexapole_ion_optics"
        request = json.loads(
            (root / "config/requests/mechanical_base.json").read_text(encoding="utf-8")
        )
        request["geometry_mm"]["entrance_interface"]["connector_length_mm"] = -0.1
        with self.assertRaises(MultipoleDesignCompileError):
            compile_design_request(request, expected_identity=request["identity"])


if __name__ == "__main__":
    unittest.main()
