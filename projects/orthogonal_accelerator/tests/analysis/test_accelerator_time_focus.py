"""Regression tests for the independent two-zone accelerator reference."""
from __future__ import annotations

import unittest

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    accelerator_state,
    derive,
    fixed_energy_gap1_focus_sensitivity,
    focus_drift_mm,
    linear_phase_space_timing_coefficients,
    match_finite_phase_space_interval,
    match_phase_space_voltage_pair,
    time_to_fixed_plane_s,
)


class AcceleratorTimeFocusTest(unittest.TestCase):
    def test_fixed_energy_gap1_focus_sensitivity_matches_independent_fixture(self) -> None:
        result = fixed_energy_gap1_focus_sensitivity(
            4198.879726494095,
            1007.7311343585827,
            6.0,
            33.6,
            3.0,
        )
        self.assertAlmostEqual(
            result.accelerator_state.first_order_focus_drift_mm,
            0.2583736068220352,
            places=12,
        )
        self.assertAlmostEqual(
            result.focus_drift_derivative_mm_per_v,
            -0.12496596999073907,
            places=12,
        )

    def test_fixed_energy_gap1_focus_matches_existing_focus_api(self) -> None:
        energy = 2000.0
        voltage_drop = 480.0
        gap1 = 3.0
        gap2 = 16.8
        release = 1.5
        result = fixed_energy_gap1_focus_sensitivity(
            energy, voltage_drop, gap1, gap2, release,
        )
        repeller = energy + voltage_drop * release / gap1
        intermediate = repeller - voltage_drop
        expected = focus_drift_mm(
            repeller,
            intermediate,
            gap1,
            gap2,
            release_position_mm=release,
            require_downstream_focus=False,
            zero_tolerance_mm=0.0,
        )
        self.assertEqual(result.accelerator_state.first_order_focus_drift_mm, expected)

    def test_fixed_energy_gap1_focus_sensitivity_obeys_voltage_homogeneity(self) -> None:
        baseline = fixed_energy_gap1_focus_sensitivity(
            2000.0, 480.0, 3.0, 16.8, 1.5,
        )
        scale = 2.75
        scaled = fixed_energy_gap1_focus_sensitivity(
            scale * 2000.0, scale * 480.0, 3.0, 16.8, 1.5,
        )
        self.assertAlmostEqual(
            scaled.accelerator_state.first_order_focus_drift_mm,
            baseline.accelerator_state.first_order_focus_drift_mm,
            places=12,
        )
        self.assertAlmostEqual(
            scaled.focus_drift_derivative_mm_per_v,
            baseline.focus_drift_derivative_mm_per_v / scale,
            places=12,
        )

    def test_fixed_energy_gap1_focus_sensitivity_matches_independent_central_difference(self) -> None:
        energy = 2500.0
        voltage_drop = 600.0
        gap1 = 4.0
        gap2 = 20.0
        release = 1.3
        result = fixed_energy_gap1_focus_sensitivity(
            energy, voltage_drop, gap1, gap2, release,
        )

        def fixed_energy_focus(drop: float) -> float:
            repeller = energy + drop * release / gap1
            intermediate = repeller - drop
            return focus_drift_mm(
                repeller,
                intermediate,
                gap1,
                gap2,
                release_position_mm=release,
                require_downstream_focus=False,
                zero_tolerance_mm=0.0,
            )

        fixture_step_v = 1.0e-3
        numerical_derivative = (
            fixed_energy_focus(voltage_drop + fixture_step_v)
            - fixed_energy_focus(voltage_drop - fixture_step_v)
        ) / (2.0 * fixture_step_v)
        self.assertAlmostEqual(
            result.focus_drift_derivative_mm_per_v,
            numerical_derivative,
            places=9,
        )

    def test_fixed_energy_gap1_focus_sensitivity_retains_signed_upstream_focus(self) -> None:
        result = fixed_energy_gap1_focus_sensitivity(
            4198.879726494095,
            1010.0000186926505,
            6.0,
            33.6,
            3.0,
        )
        self.assertLess(result.accelerator_state.first_order_focus_drift_mm, 0.0)
        self.assertFalse(result.accelerator_state.focus_is_downstream)

    def test_fixed_energy_gap1_focus_sensitivity_rejects_invalid_domain(self) -> None:
        cases = (
            (0.0, 480.0, 3.0, 16.8, 1.5),
            (2000.0, 0.0, 3.0, 16.8, 1.5),
            (2000.0, 480.0, 0.0, 16.8, 1.5),
            (2000.0, 480.0, 3.0, 0.0, 1.5),
            (2000.0, 480.0, 3.0, 16.8, 0.0),
            (2000.0, 480.0, 3.0, 16.8, 3.0),
            (2000.0, 5000.0, 3.0, 16.8, 1.5),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    fixed_energy_gap1_focus_sensitivity(*arguments)

    def test_reference_assertion_keeps_accelerator_length_diagnostic(self) -> None:
        from projects.orthogonal_accelerator.analysis.accelerator_time_focus import _assert_expected

        with self.assertRaises(SystemExit) as caught:
            _assert_expected({"x": [1]}, {"x": [1, 2]}, "expected_derived", abs_tol=0, rel_tol=0)
        self.assertEqual(
            str(caught.exception),
            "MISMATCH expected_derived.x: actual length=1 expected=2",
        )

    def test_finite_interval_match_preserves_uniform_second_region(self) -> None:
        match = match_finite_phase_space_interval(
            3.0, 16.8, 1.5122728479061323, 2.2,
            2.7185554943246992, 154.9992858327178,
            100.0, 2000.0,
        )
        self.assertAlmostEqual(match.gap1_voltage_drop_v, 316.25, places=1)
        self.assertAlmostEqual(match.focus_drift_mm, 45.36, places=1)
        self.assertLess(match.theoretical_rms_time_ns, 0.078)
        self.assertLess(match.theoretical_peak_to_peak_time_ns, 0.39)
        self.assertEqual(match.canonical_grid2_z_mm, -match.focus_drift_mm)
        self.assertAlmostEqual(
            match.intermediate_v / 16.8,
            match.stage2_field_v_per_mm,
            places=12,
        )

    def test_finite_interval_match_rejects_source_touching_electrodes(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside gap 1"):
            match_finite_phase_space_interval(
                3.0, 16.8, 1.5, 3.0, 0.0, 0.0, 100.0, 2000.0
            )

    def test_terminal_finite_interval_match_closes_current_linear_beam(self) -> None:
        match = match_finite_phase_space_interval(
            3.0, 16.8, 1.498375640839315, 2.2,
            -2.9323518410018137, 228.80604377795845,
            100.0, 2000.0,
        )
        self.assertAlmostEqual(match.gap1_voltage_drop_v, 315.0776, places=3)
        self.assertAlmostEqual(match.focus_drift_mm, 47.5504, places=3)
        self.assertLess(match.theoretical_rms_time_ns, 0.082)
        self.assertLess(match.theoretical_peak_to_peak_time_ns, 0.407)

    def test_linear_phase_space_coefficients_match_fixed_focus_solution(self) -> None:
        state = accelerator_state(
            2247.5764701146,
            1756.4419427890,
            3.0,
            16.8,
            release_position_mm=1.5122728479,
            require_downstream_focus=False,
        )
        coefficients = linear_phase_space_timing_coefficients(
            state,
            100.0,
            2.7185555,
            154.9992858,
            0.129186803,
        )
        self.assertAlmostEqual(
            coefficients.actual_energy_per_charge_v, 2000.00000383091, places=9
        )
        self.assertLess(abs(coefficients.first_derivative_at_focus), 5.0e-12)
        self.assertAlmostEqual(
            coefficients.second_derivative_at_focus, 4.0173991396e-7, places=15
        )

    def test_moving_source_match_preserves_nominal_energy_and_fixed_geometry(self) -> None:
        match = match_phase_space_voltage_pair(
            3.0,
            16.8,
            1.51351888746295,
            3.1764566087244,
            155.507788709969,
            0.12918680341103,
            100.0,
            2000.0,
        )
        self.assertAlmostEqual(match.gap1_voltage_drop_v, 491.10791847, places=5)
        self.assertAlmostEqual(match.repeller_v, 2247.76703680, places=5)
        self.assertAlmostEqual(match.intermediate_v, 1756.65911833, places=5)
        energy = match.repeller_v - (
            match.gap1_voltage_drop_v / 3.0 * match.release_position_mm
        )
        self.assertAlmostEqual(energy, 2000.0, places=10)
        self.assertLess(abs(match.time_derivative_s_per_mm), 1.0e-15)

    def test_fixed_plane_time_accepts_nonzero_initial_velocity(self) -> None:
        moving = time_to_fixed_plane_s(
            2240.0, 1760.0, 3.0, 16.8, 1.5, 100.0, 0.12918680341103, 100.0
        )
        resting = time_to_fixed_plane_s(
            2240.0, 1760.0, 3.0, 16.8, 1.5, 0.0, 0.12918680341103, 100.0
        )
        self.assertLess(moving, resting)

    def test_formal_engineering_rounding_has_submicron_focus_residual(self) -> None:
        drift = focus_drift_mm(2240.0, 1760.0, 3.0, 16.83)
        self.assertAlmostEqual(drift, 0.000544666187299)
        self.assertLess(drift, 0.001)

    def test_derived_geometry_rejects_unequal_pitch_contract(self) -> None:
        contract = {
            "design": {
                "target_global_focus_z_mm": 19.83,
                "local_geometry_mm": {
                    "d1": 3.0,
                    "d2": 16.8,
                    "ring_count": 5,
                    "ring_pitch": 2.79,
                },
                "electrodes_V": {"repeller": 2240.0, "grid1": 1760.0},
            }
        }
        with self.assertRaisesRegex(ValueError, "equal"):
            derive(contract)

    def test_ring_count_rejects_silent_fractional_truncation(self) -> None:
        contract = {
            "design": {
                "target_global_focus_z_mm": 19.83,
                "local_geometry_mm": {
                    "d1": 3.0,
                    "d2": 16.8,
                    "ring_count": 5.5,
                    "ring_pitch": 2.8,
                },
                "electrodes_V": {"repeller": 2240.0, "grid1": 1760.0},
            }
        }
        with self.assertRaisesRegex(ValueError, "integer"):
            derive(contract)
