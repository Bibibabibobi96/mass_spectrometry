"""Independent accelerator-only three-zone identities and focus checks."""
from __future__ import annotations

import math
import unittest

import numpy as np

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    accelerator_state,
    time_to_fixed_plane_s,
)
from projects.orthogonal_accelerator.analysis.three_zone_ideal_theory import (
    AffineSource,
    OuterGeometry,
    TheoryDomainError,
    compute_accelerator_time_derivatives,
    derive_first_order_focus_drift,
    derive_three_zone_state,
    exact_accelerator_normalized_time,
    exact_accelerator_normalized_time_from_state,
    source_coordinate_for_energy,
    source_energy_per_charge,
)


class ThreeZoneIdealTheoryTest(unittest.TestCase):
    @staticmethod
    def source() -> AffineSource:
        return AffineSource.from_velocity(
            mass_to_charge_th=100.0, center_extraction_position_mm=1.5,
            center_velocity_m_per_s=-3.0,
            velocity_slope_m_per_s_per_mm=200.0,
        )

    @staticmethod
    def outer(split_fraction: float = 0.55) -> OuterGeometry:
        return OuterGeometry(4.5, 17.0, split_fraction, 250.0, 2000.0)

    def test_signed_source_energy_coordinate_round_trip(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), -2.0)
        positions = np.linspace(1.3, 1.7, 9)
        energies = source_energy_per_charge(source, state, positions)
        # Energy is formed by several operations at ~2 kV, then the nominal
        # energy is subtracted. Propagate eight energy ULPs through dW/dx;
        # a coordinate-only absolute tolerance would ignore cancellation.
        slopes = state.energy_position_first_v_per_mm + (
            state.energy_position_second_v_per_mm2*(positions-source.center_extraction_position_mm)
        )
        coordinate_roundoff_mm = (
            8*np.spacing(np.max(np.abs(energies)))/np.min(np.abs(slopes))
        )
        np.testing.assert_allclose(
            source_coordinate_for_energy(source, state, energies), positions,
            rtol=0.0, atol=coordinate_roundoff_mm,
        )
        self.assertLess(source.chi_center_sqrt_v, 0.0)

    def test_eta_zero_matches_two_zone_exact_transit(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), 0.0)
        positions = np.linspace(1.3, 1.7, 9)
        drift = derive_first_order_focus_drift(source, state)
        normalized = exact_accelerator_normalized_time(source, state, positions, drift)
        expected = [
            time_to_fixed_plane_s(
                state.repeller_v, state.grid1_v, state.zone1_length_mm,
                state.zone2_length_mm + state.zone3_length_mm, float(position),
                -3.0 + 200.0*(position-1.5), drift, 100.0,
            ) for position in positions
        ]
        np.testing.assert_allclose(
            normalized*source.time_scale_s_sqrt_v_per_mm, expected,
            rtol=5e-15, atol=0.0,
        )

    def test_eta_zero_is_independent_of_downstream_partition(self) -> None:
        source = self.source()
        first = derive_three_zone_state(source, self.outer(0.25), 0.0)
        second = derive_three_zone_state(source, self.outer(0.75), 0.0)
        self.assertEqual(first.field2_v_per_mm, first.field3_v_per_mm)
        self.assertAlmostEqual(
            derive_first_order_focus_drift(source, first),
            derive_first_order_focus_drift(source, second), places=12,
        )

    def test_stationary_two_zone_and_three_zone_focus_agree(self) -> None:
        source = AffineSource.from_velocity(
            mass_to_charge_th=100.0, center_extraction_position_mm=1.5,
            center_velocity_m_per_s=0.0, velocity_slope_m_per_s_per_mm=0.0,
        )
        state = derive_three_zone_state(source, self.outer(), 0.0)
        two = accelerator_state(state.repeller_v, state.grid1_v, 4.5, 17.0,
                                release_position_mm=1.5)
        self.assertAlmostEqual(
            derive_first_order_focus_drift(source, state),
            two.first_order_focus_drift_mm, places=12,
        )

    def test_first_focus_zeroes_affine_position_derivative(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), -2.0)
        drift = derive_first_order_focus_drift(source, state)
        components = compute_accelerator_time_derivatives(source, state, drift)
        self.assertLess(abs(components[0]), 1e-18)
        step = 1e-4
        times = exact_accelerator_normalized_time(
            source, state, np.array([1.5-step, 1.5+step]), drift,
        )
        residual_s_per_mm = (times[1]-times[0])/(2*step)*source.time_scale_s_sqrt_v_per_mm
        self.assertLess(abs(residual_s_per_mm), 1e-15)

    def test_independent_state_oracle_matches_affine_input(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), -2.0)
        positions = np.linspace(1.3, 1.7, 9)
        drift = derive_first_order_focus_drift(source, state)
        np.testing.assert_array_equal(
            exact_accelerator_normalized_time(source, state, positions, drift),
            exact_accelerator_normalized_time_from_state(
                state, positions, source.chi(positions), drift,
            ),
        )

    def test_invalid_partition_and_nonfinite_source_fail_closed(self) -> None:
        for split in (0.0, 1.0, math.nan):
            with self.assertRaises(TheoryDomainError):
                self.outer(split)
        with self.assertRaises(TheoryDomainError):
            AffineSource(1.5, math.inf, 0.0, 1.0)

    def test_uncrossable_grid_state_fails_closed(self) -> None:
        source = self.source()
        state = derive_three_zone_state(source, self.outer(), -2.0)
        with self.assertRaisesRegex(TheoryDomainError, "cannot cross"):
            exact_accelerator_normalized_time_from_state(state, 10.0, 0.0, 1.0)


    def test_public_units_coordinate_and_independent_si_transit(self) -> None:
        from dataclasses import asdict
        from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
            ATOMIC_MASS_CONSTANT_KG, ELEMENTARY_CHARGE_C,
        )

        mass_per_charge = 100.0 * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
        scale = 1e-3 * math.sqrt(mass_per_charge / 2)
        for velocity in (-3.0, 7.0):
            with self.subTest(velocity=velocity):
                source = AffineSource.from_velocity(
                    mass_to_charge_th=100.0, center_extraction_position_mm=1.5,
                    center_velocity_m_per_s=velocity, velocity_slope_m_per_s_per_mm=200.0,
                )
                self.assertEqual(source.time_scale_s_sqrt_v_per_mm, scale)
                self.assertEqual(set(asdict(source)), {
                    "center_extraction_position_mm", "chi_center_sqrt_v",
                    "chi_slope_sqrt_v_per_mm", "time_scale_s_sqrt_v_per_mm",
                })
                state = derive_three_zone_state(source, self.outer(), -0.7)
                speed, seconds = velocity, 0.0
                for length_mm, field in (
                    (state.zone1_length_mm - 1.5, state.field1_v_per_mm),
                    (state.zone2_length_mm, state.field2_v_per_mm),
                    (state.zone3_length_mm, state.field3_v_per_mm),
                ):
                    acceleration = field * 1e3 / mass_per_charge
                    next_speed = math.sqrt(speed**2 + 2 * acceleration * length_mm * 1e-3)
                    seconds += (next_speed - speed) / acceleration
                    speed = next_speed
                seconds += 0.01 / speed
                normalized = exact_accelerator_normalized_time(
                    source, state, extraction_position_mm=1.5, focus_drift_mm=10.0,
                )
                self.assertAlmostEqual(normalized * scale / seconds, 1.0, places=14)
                self.assertAlmostEqual(normalized * scale * 1e6, seconds * 1e6, places=12)
                self.assertAlmostEqual(normalized * scale * 1e9, seconds * 1e9, places=9)
                self.assertAlmostEqual(state.grid2_v,
                    state.field3_v_per_mm * state.zone3_length_mm, places=12)
                self.assertNotEqual(state.grid2_v, state.exit_v)
                # Nonzero mechanical origin: sectioned +z is measured from repeller.
                self.assertEqual(source.chi(extraction_position_mm=8.5 - 7.0),
                                 source.chi(extraction_position_mm=18.5 - 17.0))
                self.assertNotEqual(source.chi(extraction_position_mm=8.5),
                                    source.chi(extraction_position_mm=8.5 - 7.0))
