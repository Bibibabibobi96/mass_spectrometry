"""Regression tests for solver-neutral two-zone accelerator geometry."""
from __future__ import annotations

import unittest

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    TwoZoneGeometryError,
    derive_shielded_rectangular_enclosure,
    derive_uniform_ring_planes,
)


class TwoZoneGeometryTest(unittest.TestCase):
    def test_descending_second_region_has_uniform_interior_ring_planes(self) -> None:
        layout = derive_uniform_ring_planes(33.6, 0.0, 5, ring_thickness_mm=1.0)
        self.assertAlmostEqual(layout.pitch_mm, 5.6)
        self.assertEqual(len(layout.centers_mm), 5)
        for actual, expected in zip(layout.centers_mm, (28.0, 22.4, 16.8, 11.2, 5.6)):
            self.assertAlmostEqual(actual, expected)

    def test_overlapping_ring_thickness_is_rejected(self) -> None:
        with self.assertRaises(TwoZoneGeometryError):
            derive_uniform_ring_planes(0.0, 5.0, 1, ring_thickness_mm=2.5)

    def test_shell_derivation_requires_declared_lateral_clearance(self) -> None:
        enclosure = derive_shielded_rectangular_enclosure(
            electrode_outer_width_x_mm=40.0, electrode_outer_height_y_mm=40.0,
            guard_outer_width_x_mm=48.0, guard_outer_height_y_mm=48.0,
            guard_wall_thickness_mm=2.0, lateral_clearance_mm=2.0,
            repeller_z_mm=45.6, repeller_thickness_z_mm=2.0, rear_gap_mm=5.0,
        )
        self.assertAlmostEqual(enclosure.rear_cap_inner_z_mm, 52.6)


if __name__ == "__main__":
    unittest.main()
