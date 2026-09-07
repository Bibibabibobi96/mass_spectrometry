from __future__ import annotations

import unittest

from projects.orthogonal_accelerator.analysis.two_zone_theory import (
    TwoZoneTheoryError, derive_two_zone_time_focus,
)
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    time_to_fixed_plane_s,
)


class TwoZoneTheoryTest(unittest.TestCase):
    def test_equal_fields_focus_at_twice_release_to_exit_distance(self) -> None:
        result = derive_two_zone_time_focus(
            repeller_v=30.0, intermediate_v=20.0, exit_v=0.0,
            gap_1_mm=10.0, gap_2_mm=20.0, release_position_in_gap_1_mm=5.0,
        )
        self.assertAlmostEqual(result.focus_after_exit_mm, 50.0, places=12)

    def test_focus_zeroes_independent_transit_time_position_derivative(self) -> None:
        result = derive_two_zone_time_focus(
            repeller_v=4480.0, intermediate_v=3520.0, exit_v=0.0,
            gap_1_mm=6.0, gap_2_mm=33.6, release_position_in_gap_1_mm=3.0,
        )
        step = 1.0e-4

        def derivative(drift: float) -> float:
            before = time_to_fixed_plane_s(
                4480.0, 3520.0, 6.0, 33.6, 3.0-step, 0.0, drift, 100.0,
            )
            after = time_to_fixed_plane_s(
                4480.0, 3520.0, 6.0, 33.6, 3.0+step, 0.0, drift, 100.0,
            )
            return (after-before)/(2.0*step)

        # Five orders separate floating-point/stencil residual from the old
        # factor-of-two error; the tolerance is not an instrument pass limit.
        residual = abs(derivative(result.focus_after_exit_mm))
        old_residual = abs(derivative(result.focus_after_exit_mm/2.0))
        self.assertLess(residual, 1.0e-15)
        self.assertGreater(old_residual, 1.0e5*residual)

    def test_derives_a_downstream_focus_without_device_coordinates(self) -> None:
        result = derive_two_zone_time_focus(
            repeller_v=4480.0, intermediate_v=3520.0, exit_v=0.0,
            gap_1_mm=6.0, gap_2_mm=33.6, release_position_in_gap_1_mm=3.0,
        )
        self.assertGreater(result.focus_after_exit_mm, 0.0)
        self.assertAlmostEqual(result.energy_per_charge_v, 4000.0)

    def test_rejects_an_invalid_voltage_order(self) -> None:
        with self.assertRaises(TwoZoneTheoryError):
            derive_two_zone_time_focus(
                repeller_v=100.0, intermediate_v=100.0, exit_v=0.0,
                gap_1_mm=1.0, gap_2_mm=1.0, release_position_in_gap_1_mm=0.5,
            )
