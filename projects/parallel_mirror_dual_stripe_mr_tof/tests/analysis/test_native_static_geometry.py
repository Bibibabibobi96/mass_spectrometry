"""Pure C0 static projection tests; no solver or artifact dependency."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import (
    build_static_c0_gem,
)

MODULE = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry"


def box(values):
    return {
        f"{axis}_{side}_mm": values[i + 3 * j] for j, side in enumerate(("min", "max")) for i, axis in enumerate("xyz")
    }


def fixture():
    detector = {"id": 18, "box": [-1, -2, 7, 1, 2, 8]}
    outer = box([-2, -2, 1, 2, 2, 4])
    opening = box([-1, -1, 1, 1, 1, 2])
    oa = {
        "local_to_pa_translation_mm": [0, 2, 0],
        "acceleration_direction": "-z",
        "grounded_enclosure": {
            "component_electrode_id": 15,
            "outer_box_mm": outer,
            "cavity_box_mm": box([-1.5, -1.5, 1, 1.5, 1.5, 3.5]),
            "exit_opening_box_mm": opening,
        },
        "repeller": {"component_electrode_id": 22, "solid_box_mm": outer},
        "grid_supports": [
            {
                "component_electrode_id": 23,
                "frame_outer_box_mm": outer,
                "aperture_box_mm": opening,
                "ideal_sheet_mm": {"x_min_mm": -1, "x_max_mm": 1, "y_min_mm": -1, "y_max_mm": 1, "z_mm": 2},
                "transmission": "ideal_transparent",
            }
        ],
        "rings": [{"component_electrode_id": 26, "outer_box_mm": outer, "aperture_box_mm": opening}],
    }
    voltages = [0.0] * 20
    voltages[10:14] = [-27.0, -27.0, 55.0, 55.0]
    authority = {
        "boundary_contract": {"mode": "grounded_enclosure", "box_mm": [0, -10, -10, 10, 20, 20], "voltage_v": 0},
        "analyzer_electrode_voltages_v": voltages,
        "component_voltages_v": [
            {"component_namespace": namespace, "component_electrode_id": number, "voltage_v": voltage}
            for namespace, number, voltage in [
                ("accelerator", 15, 0),
                ("accelerator", 22, 60),
                ("accelerator", 23, 30),
                ("accelerator", 26, 12),
                ("detector", 18, 3),
            ]
        ],
        "assembly": {
            "accelerator_resolved_electrodes": oa,
            "accelerator_iob_origin_mm": [0, -5, -2],
            "detector": detector,
        },
    }
    grid = {
        "box_mm": [0, -10, -10, 10, 20, 20],
        "pitch_mm": [1, 1, 1],
        "dimensions": [11, 31, 31],
        "mirror_axes": ["x"],
        "surface": "fractional",
    }
    return {"detector": detector}, authority, grid


class NativeStaticGeometryTest(unittest.TestCase):
    def setUp(self):
        self.geometry, self.authority, self.grid = fixture()
        self.analyzer = patch(
            MODULE + "._analyzer_geometry_lines",
            return_value=["  e(11) { box(0,0,0,1,1,1) }", "  e(18) { box(0,1,0,1,2,1) }"],
        )
        self.analyzer.start()
        self.addCleanup(self.analyzer.stop)

    def build(self, mode="grounded_enclosure"):
        return build_static_c0_gem(self.geometry, self.authority, self.grid, boundary_mode=mode)

    def test_namespace_voltage_and_single_coordinate_translation(self):
        gem, report = self.build()
        self.assertIn("e(-27)", gem)
        self.assertIn("e(30)", gem)
        self.assertEqual(report["oa_project_offset_mm"], [0, -3, -2])
        self.assertEqual(report["oa_bodies"][0]["box_mm"], [-2, -5, -1, 2, -1, 2])
        self.assertIn("e(3)", gem)
        self.assertEqual(report["analyzer_emission_counts"], {"11": 1, "18": 1})

    def test_sheet_and_through_aperture(self):
        gem, report = self.build()
        sheet = next(v for v in report["oa_bodies"] if v["name"] == "oa_grid_sheet_1")
        self.assertEqual(sheet["box_mm"], [-1, -4, 0, 1, -2, 0])
        self.assertEqual(sheet["transmission"], "ideal_transparent")
        self.assertIn("notin_inside { box3D(-1,-4,-4,1,-2,3) }", gem)
        self.assertIn("notin { box3D(-1,-4,-2,1,-2,1) }", gem)

    def test_parent_five_faces_and_local_no_walls(self):
        _, parent = self.build()
        self.assertEqual(len(parent["outer_ground_faces"]), 5)
        self.assertFalse(parent["x0_dirichlet_wall"])
        self.grid.update(box_mm=[0, -8, -8, 8, 18, 18], dimensions=[9, 27, 27])
        gem, local = self.build("x_mirror_five_faces")
        self.assertEqual(local["outer_ground_faces"], [])
        self.assertIn("surface=fractional", gem)
        self.assertEqual(local["oa_bodies"], parent["oa_bodies"])

    def test_invalid_grid_and_boundary(self):
        for field, value in [
            ("dimensions", [2, 2, 2]),
            ("pitch_mm", [1, 0, 1]),
            ("mirror_axes", []),
            ("surface", "none"),
        ]:
            with self.subTest(field=field):
                grid = copy.deepcopy(self.grid)
                grid[field] = value
                with self.assertRaises(ValueError):
                    build_static_c0_gem(self.geometry, self.authority, grid, boundary_mode="grounded_enclosure")
        with self.assertRaises(ValueError):
            self.build("unknown")

    def test_voltage_and_component_identity_reject(self):
        self.authority["analyzer_electrode_voltages_v"][0] = float("nan")
        with self.assertRaises(ValueError):
            self.build()
        self.authority["analyzer_electrode_voltages_v"][0] = 0
        self.authority["component_voltages_v"].append(copy.deepcopy(self.authority["component_voltages_v"][0]))
        with self.assertRaises(ValueError):
            self.build()

    def test_frozen_detector_and_transparency_reject(self):
        self.geometry["detector"] = {"id": 18, "box": [0] * 6}
        with self.assertRaises(ValueError):
            self.build()
        self.geometry["detector"] = self.authority["assembly"]["detector"]
        self.authority["assembly"]["accelerator_resolved_electrodes"]["grid_supports"][0]["transmission"] = "opaque"
        with self.assertRaises(ValueError):
            self.build()


if __name__ == "__main__":
    unittest.main()
