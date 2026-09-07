"""Solver-free regression for the migrated rectangular SIMION emitter."""
from __future__ import annotations

from dataclasses import replace
import unittest

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    TwoZoneGeometryError,
    derive_shielded_rectangular_enclosure,
)
from projects.orthogonal_accelerator.simion.rectangular_accelerator import (
    emit_grounded_enclosure,
    emit_ideal_grid,
    emit_open_rectangular_frame,
)


class RectangularAcceleratorTest(unittest.TestCase):
    def test_open_frame_preserves_frozen_csg(self) -> None:
        self.assertEqual(emit_open_rectangular_frame(
            2, outer_half_x_mm=20.0, outer_half_y_mm=20.0,
            aperture_half_x_mm=12.5, aperture_half_y_mm=12.5,
            front_z_mm=45.6, back_z_mm=47.6, cut_padding_mm=1.0,
        ), "  e(2) { box3D(-20,-20,45.6,20,20,47.6) notin_inside { box3D(-12.5,-12.5,44.6,12.5,12.5,48.6) } }")

    def test_zero_thickness_grid_preserves_frozen_csg(self) -> None:
        self.assertEqual(emit_ideal_grid(4, half_x_mm=22.0, half_y_mm=22.0, z_mm=6.0),
                         "  e(4) { box3D(-22,-22,6,22,22,6) }")

    def test_hollow_enclosure_preserves_frozen_csg(self) -> None:
        enclosure = derive_shielded_rectangular_enclosure(
            electrode_outer_width_x_mm=40.0, electrode_outer_height_y_mm=40.0,
            guard_outer_width_x_mm=48.0, guard_outer_height_y_mm=48.0,
            guard_wall_thickness_mm=2.0, lateral_clearance_mm=2.0,
            repeller_z_mm=45.6, repeller_thickness_z_mm=2.0, rear_gap_mm=5.0,
        )
        self.assertEqual(emit_grounded_enclosure(enclosure, exit_z_mm=6.0),
                         "box3D(-24,-24,6,24,24,54.6) notin { box3D(-22,-22,6,22,22,52.6) }")
        with self.assertRaises(TwoZoneGeometryError):
            emit_grounded_enclosure(replace(enclosure, rear_cap_inner_z_mm=5.0), exit_z_mm=6.0)

    def test_invalid_solid_and_grid_fail_closed(self) -> None:
        for invalid in (0, -1, True, 1.5):
            with self.subTest(electrode_id=invalid), self.assertRaises(TwoZoneGeometryError):
                emit_ideal_grid(invalid, half_x_mm=2.0, half_y_mm=2.0, z_mm=0.0)
        with self.assertRaises(TwoZoneGeometryError):
            emit_open_rectangular_frame(
                1, outer_half_x_mm=2.0, outer_half_y_mm=2.0,
                aperture_half_x_mm=3.0, aperture_half_y_mm=1.0,
                front_z_mm=0.0, back_z_mm=1.0, cut_padding_mm=0.1,
            )
        with self.assertRaises(TwoZoneGeometryError):
            emit_ideal_grid(1, half_x_mm=2.0, half_y_mm=2.0, z_mm=float('nan'))


if __name__ == "__main__":
    unittest.main()
