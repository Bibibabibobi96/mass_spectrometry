"""Solver-free regression tests for common NumPy multipole adapters."""

from __future__ import annotations

import unittest

import numpy as np

from common.multipole.family_contract import VoltageDrive, rf_waveform_voltage
from common.multipole.ideal_transport import (
    electric_field_xy,
    electric_field_xy_array,
    rf_waveform_voltage_array,
)


class IdealTransportArrayTest(unittest.TestCase):
    def test_rf_waveform_array_matches_scalar_voltage_oracle(self):
        times = np.array([0.0, 0.12e-6, 0.47e-6])
        for waveform in ("sine", "cosine"):
            with self.subTest(waveform=waveform):
                drive = VoltageDrive(waveform, 83.0, 0.0, 0.0, 1.2e6, 0.37)
                expected = np.array(
                    [rf_waveform_voltage(drive, float(time)) for time in times]
                )
                np.testing.assert_allclose(
                    rf_waveform_voltage_array(drive, times),
                    expected,
                    rtol=0.0,
                    atol=1e-13,
                )

    def test_field_array_matches_scalar_oracle_and_broadcasts_voltage(self):
        x_m = np.array([0.1e-3, -0.2e-3, 0.3e-3])
        y_m = np.array([-0.2e-3, 0.3e-3, 0.1e-3])
        for order in (2, 3, 4):
            with self.subTest(order=order):
                field_x, field_y = electric_field_xy_array(
                    order, 2.5e-3, np.array(83.0), x_m, y_m
                )
                expected = np.array(
                    [
                        electric_field_xy(order, 2.5e-3, 83.0, x, y)
                        for x, y in zip(x_m, y_m, strict=True)
                    ]
                )
                np.testing.assert_allclose(field_x, expected[:, 0], rtol=1e-14, atol=1e-12)
                np.testing.assert_allclose(field_y, expected[:, 1], rtol=1e-14, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
