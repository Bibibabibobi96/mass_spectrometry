from __future__ import annotations

import copy
import unittest

from common.multipole.simion_geometry import render_gem


def resolved_design(
    connector_shape: str,
    length_mm: float,
    *,
    enclosure_model: str = "cylindrical_grounded_shield_v1",
) -> dict:
    if enclosure_model == "cylindrical_grounded_shield_v1":
        enclosure = {
            "model": enclosure_model,
            "working_region_radius_mm": 3.0,
            "vacuum_z_min_mm": 0.0,
            "vacuum_z_max_mm": 20.0,
            "shield_inner_radius_mm": 9.0,
            "shield_outer_radius_mm": 10.0,
            "entrance_endcap_z_min_mm": 0.0,
            "entrance_endcap_z_max_mm": 0.5,
            "exit_endcap_z_min_mm": 19.5,
            "exit_endcap_z_max_mm": 20.0,
        }
    else:
        enclosure = {
            "model": enclosure_model,
            "working_region_radius_mm": 3.0,
            "vacuum_z_min_mm": 0.0,
            "vacuum_z_max_mm": 20.0,
            "outer_half_width_mm": 10.0,
            "inner_half_width_mm": 9.0,
            "exit_enclosure_z_min_mm": 15.0,
            "exit_enclosure_z_max_mm": 20.0,
            "exit_front_wall_end_z_mm": 16.0,
            "detector_radius_mm": 1.2,
            "detector_thickness_mm": 0.5,
        }
    rod = {
        "rod_id": 1,
        "electrode_group": 1,
        "angle_rad": 0.0,
        "center_x_mm": 4.0,
        "center_y_mm": 0.0,
        "z_min_mm": 2.0,
        "z_max_mm": 15.0,
        "radius_mm": 1.0,
    }
    return {
        "role": "multipole_resolved_design_do_not_edit",
        "resolved_sha256": "A" * 64,
        "geometry_mm": {
            "enclosure": enclosure,
            "rod_array": {"rods": [rod]},
        },
        "interfaces_mm": {
            "entrance": {
                "plate_z_min_mm": 1.0,
                "plate_z_max_mm": 1.5,
                "aperture_radius_mm": 1.2,
                "connector_length_mm": length_mm,
                "connector_shape": connector_shape,
                "particle_plane_z_mm": 0.5,
            },
            "exit": {
                "plate_z_min_mm": 15.0,
                "plate_z_max_mm": 16.0,
                "aperture_radius_mm": 1.2,
                "connector_length_mm": length_mm,
                "connector_shape": connector_shape,
                "particle_plane_z_mm": 20.0,
            },
        },
        "segmentation": {
            "strategy": "off",
            "axial_acceleration": None,
            "segmented_rod_array": None,
        },
    }


class SimionGeometryTests(unittest.TestCase):
    def test_rectangular_connector_is_box_minus_cylinder(self) -> None:
        source = resolved_design(
            "rectangular_bore",
            1.0,
            enclosure_model="rectangular_reference_enclosure_v1",
        )
        gem = render_gem(source, 0.2)
        self.assertIn("box3d(", gem)
        self.assertIn("notin_inside { cylinder(", gem)
        self.assertIn("; connector_shape=rectangular_bore", gem)
        self.assertIn("parent_resolved_sha256=" + "A" * 64, gem)

    def test_cylindrical_connector_is_cylinder_minus_cylinder(self) -> None:
        gem = render_gem(resolved_design("cylindrical_bore", 1.0), 0.2)
        connector = gem.index("; connector_shape=cylindrical_bore")
        next_connector = gem.index("; connector_shape=cylindrical_bore", connector + 1)
        self.assertIn("within { cylinder(", gem[connector:next_connector])
        self.assertNotIn("within { box3d(", gem[connector:next_connector])

    def test_cylindrical_enclosure_preserves_rectangular_connector_shape(self) -> None:
        gem = render_gem(resolved_design("rectangular_bore", 1.0), 0.2)
        entrance = gem.index("; connector_shape=rectangular_bore")
        exit_connector = gem.index("; connector_shape=rectangular_bore", entrance + 1)
        self.assertIn("within { box3d(", gem[entrance:exit_connector])
        self.assertIn("within { box3d(", gem[exit_connector:])

    def test_zero_length_creates_no_connector_feature(self) -> None:
        for shape in ("rectangular_bore", "cylindrical_bore"):
            gem = render_gem(resolved_design(shape, 0.0), 0.2)
            self.assertNotIn("; connector_shape=", gem)

    def test_unknown_connector_shape_is_rejected(self) -> None:
        invalid = resolved_design("cylindrical_bore", 1.0)
        invalid["interfaces_mm"]["exit"]["connector_shape"] = "square"
        with self.assertRaisesRegex(ValueError, "connector shape"):
            render_gem(invalid, 0.2)

    def test_rectangular_segments_anchor_cylinders_at_z_max(self) -> None:
        source = resolved_design(
            "rectangular_bore",
            0.0,
            enclosure_model="rectangular_reference_enclosure_v1",
        )
        base = source["geometry_mm"]["rod_array"]["rods"][0]
        source["segmentation"] = {
            "strategy": "explicit",
            "axial_acceleration": {"role": "multipole_axial_acceleration_resolved_contract"},
            "segmented_rod_array": {
                "segment_count": 2,
                "electrodes": [
                    {**base, "electrode_id": 1, "z_min_mm": 2.0, "z_max_mm": 7.0},
                    {**base, "electrode_id": 3, "z_min_mm": 8.0, "z_max_mm": 15.0},
                ],
            },
        }
        gem = render_gem(source, 0.2)
        self.assertIn("locate(0,0,7)", gem)
        self.assertIn("locate(0,0,15)", gem)
        self.assertNotIn("locate(0,0,2)", gem)
        self.assertNotIn("locate(0,0,8)", gem)

    def test_five_segment_geometry_reserves_electrodes_eleven_and_twelve(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        base = source["geometry_mm"]["rod_array"]["rods"][0]
        source["segmentation"] = {
            "strategy": "uniform",
            "axial_acceleration": {"role": "multipole_axial_acceleration_resolved_contract"},
            "segmented_rod_array": {
                "segment_count": 5,
                "electrodes": [
                    {**copy.deepcopy(base), "electrode_id": electrode_id}
                    for electrode_id in range(1, 11)
                ],
            },
        }
        gem = render_gem(source, 0.2)
        self.assertIn("e(11)", gem)
        self.assertIn("e(12)", gem)


if __name__ == "__main__":
    unittest.main()
