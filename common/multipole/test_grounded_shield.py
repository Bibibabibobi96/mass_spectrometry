"""Regression tests for the common grounded shield connector."""

from __future__ import annotations

import unittest

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
            cell_mm=0.2,
        )
        gem = "\n".join(lines)
        self.assertEqual(contract["shield_potential_V"], 0.0)
        self.assertEqual(contract["grounded_sleeve_length_mm"], 0.5)
        self.assertEqual(contract["flange_thickness_mm"], 4.0)
        self.assertTrue(contract["full_radial_enclosure"])
        self.assertEqual(gem.count("e(9)"), 2)
        self.assertIn("centered_box3D", gem)


if __name__ == "__main__":
    unittest.main()
