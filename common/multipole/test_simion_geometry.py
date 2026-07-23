from __future__ import annotations

import unittest

from common.multipole.simion_geometry import render_gem


def geometry(shape: str, length_mm: float) -> dict:
    return {
        "grounded_enclosure_mm": {
            "model": "rectangular_reference_enclosure_v1"
            if shape == "rectangular_bore"
            else "cylindrical_grounded_shield_v1",
            "shield_outer_radius": 10.0,
            "shield_inner_radius": 9.0,
            "vacuum_z_min": 0.0,
            "vacuum_z_max": 20.0,
            "reference_enclosure": {
                "outer_half_width_mm": 10.0,
                "inner_half_width_mm": 9.0,
                "exit_enclosure_z_min_mm": 15.0,
                "exit_enclosure_z_max_mm": 20.0,
                "exit_front_wall_end_z_mm": 16.0,
                "detector_thickness_mm": 0.5,
            },
        },
        "interfaces_mm": {
            "entrance_plate_z_min": 1.0,
            "entrance_plate_z_max": 1.5,
            "entrance_aperture_radius": 1.2,
            "entrance_connector_length": length_mm,
            "entrance_connector_shape": shape,
            "exit_plate_z_min": 15.0,
            "exit_plate_z_max": 16.0,
            "exit_aperture_radius": 1.2,
            "exit_connector_length": length_mm,
            "exit_connector_shape": shape,
            "detector_z": 20.0,
        },
        "array_mm": {
            "rods": [
                {
                    "electrode_group": 1,
                    "center_x_mm": 4.0,
                    "center_y_mm": 0.0,
                    "z_min_mm": 2.0,
                    "z_max_mm": 15.0,
                    "radius_mm": 1.0,
                }
            ]
        },
    }


class SimionGeometryTests(unittest.TestCase):
    def test_rectangular_connector_is_box_minus_cylinder(self) -> None:
        gem = render_gem(geometry("rectangular_bore", 1.0), 0.2)
        self.assertIn("box3d(", gem)
        self.assertIn("notin_inside { cylinder(", gem)
        self.assertIn("; connector_shape=rectangular_bore", gem)

    def test_cylindrical_connector_is_cylinder_minus_cylinder(self) -> None:
        gem = render_gem(geometry("cylindrical_bore", 1.0), 0.2)
        self.assertIn("; connector_shape=cylindrical_bore", gem)
        self.assertNotIn("; connector_shape=rectangular_bore", gem)

    def test_zero_length_creates_no_connector_feature(self) -> None:
        for shape in ("rectangular_bore", "cylindrical_bore"):
            gem = render_gem(geometry(shape, 0.0), 0.2)
            self.assertNotIn("; connector_shape=", gem)

    def test_unknown_connector_shape_is_rejected(self) -> None:
        invalid = geometry("cylindrical_bore", 1.0)
        invalid["interfaces_mm"]["exit_connector_shape"] = "square"
        with self.assertRaisesRegex(ValueError, "connector shape"):
            render_gem(invalid, 0.2)

    def test_rectangular_segments_anchor_cylinders_at_z_max(self) -> None:
        source = geometry("rectangular_bore", 0.0)
        base = source["array_mm"]["rods"][0]
        segmented = {
            "segment_count": 2,
            "electrodes": [
                {**base, "electrode_id": 1, "z_min_mm": 2.0, "z_max_mm": 7.0},
                {**base, "electrode_id": 3, "z_min_mm": 8.0, "z_max_mm": 15.0},
            ],
        }
        gem = render_gem(source, 0.2, segmented)
        self.assertIn("locate(0,0,7)", gem)
        self.assertIn("locate(0,0,15)", gem)
        self.assertNotIn("locate(0,0,2)", gem)
        self.assertNotIn("locate(0,0,8)", gem)


if __name__ == "__main__":
    unittest.main()
