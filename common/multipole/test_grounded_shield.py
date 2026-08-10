"""Regression tests for the common grounded shield connector."""

from __future__ import annotations

import unittest

from common.contracts.machine_contracts import validate_schema

from common.multipole.grounded_shield import (
    render_grounded_circular_to_rectangular_connection,
    require_grounded_potential,
)


class GroundedShieldTests(unittest.TestCase):
    def test_voltage_contract_rejects_every_nonzero_or_nonfinite_value(self) -> None:
        self.assertEqual(require_grounded_potential(0.0, "shield"), 0.0)
        for value in (3.0, -1e-15, float("nan"), float("inf"), True, "0"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exactly 0 V"):
                    require_grounded_potential(value, "shield")

    def test_connection_closes_sleeve_with_grounded_apertured_flange(self) -> None:
        lines, contract = render_grounded_circular_to_rectangular_connection(
            electrode_id=9,
            sleeve_x_min_mm=-68.3,
            sleeve_x_max_mm=-67.8,
            flange_thickness_mm=4.0,
            center_y_mm=0.0,
            center_z_mm=-18.42918680341103,
            outer_radius_mm=20.776,
            inner_radius_mm=20.276,
            aperture_width_mm=1.0,
            aperture_height_mm=0.9,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.2},
            pa_origin_y_mm=-21.2,
            pa_origin_z_mm=-39.7,
        )
        gem = "\n".join(lines)
        self.assertEqual(contract["shield_potential_V"], 0.0)
        self.assertEqual(contract["grounded_sleeve_length_mm"], 0.5)
        self.assertEqual(contract["flange_thickness_mm"], 4.0)
        self.assertTrue(contract["full_radial_enclosure"])
        self.assertEqual(gem.count("e(9)"), 2)
        self.assertIn("centered_box3D", gem)

    def test_cell_sized_aperture_excludes_boolean_boundary_without_resizing(self) -> None:
        lines, contract = render_grounded_circular_to_rectangular_connection(
            electrode_id=9,
            sleeve_x_min_mm=-68.3,
            sleeve_x_max_mm=-67.8,
            flange_thickness_mm=4.0,
            center_y_mm=0.0,
            center_z_mm=-18.4,
            outer_radius_mm=20.776,
            inner_radius_mm=20.276,
            aperture_width_mm=0.5,
            aperture_height_mm=0.2,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.2},
            pa_origin_y_mm=-2.0,
            pa_origin_z_mm=-20.5,
        )
        discretization = contract["aperture_discretization"]
        validate_schema(
            discretization,
            "simion_rectangular_aperture_discretization.schema.json",
        )
        self.assertEqual(discretization["mechanical_width_mm"], 0.5)
        self.assertEqual(discretization["mechanical_height_mm"], 0.2)
        self.assertEqual(
            discretization["boolean_boundary_policy"],
            "exclude_shape_inside_or_on_v1",
        )
        self.assertEqual(discretization["numerical_carve_width_mm"], 0.5)
        self.assertEqual(discretization["numerical_carve_height_mm"], 0.2)
        self.assertTrue(discretization["compiled_pa_open_column_check_required"])
        self.assertEqual(discretization["grid_alignment"]["height_cells"], 1.0)
        self.assertTrue(
            discretization["grid_alignment"]["height_is_integer_cell_multiple"]
        )
        self.assertEqual(
            discretization["grid_alignment"]["warnings"],
            [
                "aperture_width_not_integer_cell_multiple",
                "aperture_y_edges_not_on_grid_nodes",
            ],
        )
        self.assertIn(
            "notin_inside_or_on { centered_box3D(-65.8,0,-18.4,4.4,0.5,0.2)",
            "\n".join(lines),
        )

    def test_rejects_aperture_smaller_than_one_cell_in_either_axis(self) -> None:
        common = {
            "electrode_id": 9,
            "sleeve_x_min_mm": -68.3,
            "sleeve_x_max_mm": -67.8,
            "flange_thickness_mm": 4.0,
            "center_y_mm": 0.0,
            "center_z_mm": -18.4,
            "outer_radius_mm": 20.776,
            "inner_radius_mm": 20.276,
            "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.2},
            "pa_origin_y_mm": -2.0,
            "pa_origin_z_mm": -20.5,
        }
        for width, height in ((0.199, 0.5), (0.5, 0.199)):
            with self.subTest(width=width, height=height):
                with self.assertRaisesRegex(ValueError, "at least one SIMION cell"):
                    render_grounded_circular_to_rectangular_connection(
                        **common,
                        aperture_width_mm=width,
                        aperture_height_mm=height,
                    )


if __name__ == "__main__":
    unittest.main()
