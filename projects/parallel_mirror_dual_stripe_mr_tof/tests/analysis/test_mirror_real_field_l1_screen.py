from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    ACCELERATION_MM_US2_PER_V_MM,
    GROUPS,
    CombinedField,
    RealFieldL1Error,
    ResponseBasis,
    evaluate_member,
    l1_probe_at_energy,
    load_response_basis_csv,
    rank_screened_members,
    screen_feasible_family,
)


def harmonic_basis(*, unstable_x: bool = False, electrode_peak: bool = False) -> ResponseBasis:
    mass = 1.0
    charge = 1.0
    acceleration = ACCELERATION_MM_US2_PER_V_MM * charge / mass
    omega_z = 1.0
    omega_x = 0.5
    x = np.linspace(-4.0, 4.0, 33)
    z = np.linspace(-18.0, 18.0, 145)
    potential = np.zeros((len(x), len(z), 4), dtype=float)
    field = np.zeros((len(x), len(z), 4, 3), dtype=float)
    transverse_sign = -1.0 if unstable_x else 1.0
    for ix, xv in enumerate(x):
        for iz, zv in enumerate(z):
            potential[ix, iz, 0] = (
                transverse_sign * omega_x * omega_x * xv * xv + omega_z * omega_z * zv * zv
            ) / (2.0 * acceleration)
            field[ix, iz, 0, 0] = -transverse_sign * omega_x * omega_x * xv / acceleration
            field[ix, iz, 0, 2] = -omega_z * omega_z * zv / acceleration
    mask = np.zeros((len(x), len(z)), dtype=bool)
    if electrode_peak:
        mask[-1, -1] = True
        field[-1, -1, 0, :] = (1.0e6, 1.0e6, 1.0e6)
    return ResponseBasis(x, z, potential, field, mask, 1.0, 280.0)


TRACE = {
    "particle_mass_th": 1.0,
    "particle_charge_e": 1.0,
    "relative_tolerance": 1.0e-9,
    "absolute_tolerance": 1.0e-11,
    "maximum_step_us": 0.02,
    "maximum_leg_time_us": 10.0,
    "central_plane_offset_mm": 1.0e-8,
}


class ResponseBasisTests(unittest.TestCase):
    def test_loader_requires_complete_regular_grid(self) -> None:
        columns = ["x_mm", "z_mm", "is_electrode"]
        for group in GROUPS:
            columns += [f"{group}_potential_v", *(f"{group}_e{axis}_v_per_mm" for axis in "xyz")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "basis.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                for x, z in ((0, -1), (0, 1), (1, -1)):  # missing (1, 1)
                    row = {name: 0 for name in columns}
                    row.update({"x_mm": x, "z_mm": z, "is_electrode": 0})
                    writer.writerow(row)
            with self.assertRaisesRegex(RealFieldL1Error, "complete regular"):
                load_response_basis_csv(path, normalization_v=1.0, probe_y_mm=280.0)

    def test_response_shape_is_validated(self) -> None:
        with self.assertRaisesRegex(RealFieldL1Error, "do not match"):
            ResponseBasis(
                np.array([-1.0, 1.0]), np.array([-1.0, 0.0, 1.0]),
                np.zeros((2, 3, 3)), np.zeros((2, 3, 4, 3)),
                np.zeros((2, 3), dtype=bool), 1.0, 0.0,
            )

    def test_sampled_peak_excludes_electrode_nodes(self) -> None:
        field = CombinedField(harmonic_basis(electrode_peak=True), (1.0, 0.0, 0.0, 0.0))
        peak = field.sampled_peak_field()
        self.assertEqual(peak["electrode_nodes_excluded"], 1)
        self.assertLess(peak["magnitude_v_per_mm"], 1.0e5)


class TrajectoryTests(unittest.TestCase):
    def test_harmonic_field_has_ninety_degree_stable_map(self) -> None:
        field = CombinedField(harmonic_basis(), (1.0, 0.0, 0.0, 0.0))
        result = l1_probe_at_energy(
            field, energy_per_charge_v=1.0, launch_direction=1,
            position_probe_mm=0.01, angle_probe_rad=0.001, trace_controls=TRACE,
        )
        self.assertTrue(result["stable"])
        self.assertAlmostEqual(result["gamma_degrees"], 90.0, delta=0.03)
        self.assertAlmostEqual(result["determinant"], 1.0, delta=2.0e-3)
        self.assertAlmostEqual(result["reversibility_difference"], 0.0, delta=2.0e-3)
        self.assertAlmostEqual(result["full_two_mirror_period_us"], 2.0 * math.pi, delta=2.0e-4)
        self.assertAlmostEqual(result["Tbar_xx_us_per_mm2"], 0.0, delta=2.0e-5)

    def test_positive_and_negative_launches_are_symmetric(self) -> None:
        field = CombinedField(harmonic_basis(), (1.0, 0.0, 0.0, 0.0))
        positive = l1_probe_at_energy(
            field, energy_per_charge_v=1.0, launch_direction=1,
            position_probe_mm=0.01, angle_probe_rad=0.001, trace_controls=TRACE,
        )
        negative = l1_probe_at_energy(
            field, energy_per_charge_v=1.0, launch_direction=-1,
            position_probe_mm=0.01, angle_probe_rad=0.001, trace_controls=TRACE,
        )
        np.testing.assert_allclose(positive["matrix"], negative["matrix"], rtol=0, atol=2.0e-7)
        self.assertAlmostEqual(
            positive["full_two_mirror_period_us"], negative["full_two_mirror_period_us"], delta=1.0e-8,
        )

    def test_inverted_transverse_field_is_unstable(self) -> None:
        field = CombinedField(harmonic_basis(unstable_x=True), (1.0, 0.0, 0.0, 0.0))
        result = l1_probe_at_energy(
            field, energy_per_charge_v=1.0, launch_direction=1,
            position_probe_mm=0.01, angle_probe_rad=0.001, trace_controls=TRACE,
        )
        self.assertFalse(result["stable"])
        self.assertIsNone(result["gamma_degrees"])
        self.assertIsNone(result["Tbar_xx_us_per_mm2"])

    def test_member_reports_three_scale_convergence_and_l0_slopes(self) -> None:
        result = evaluate_member(
            harmonic_basis(), [0.0, 1.0, 0.0, 0.0, 0.0],
            energy_points_v=(0.9, 1.0, 1.1), period_slope_derivative_step_v=0.01,
            probe_scale_factors=(1.0, 2.0, 4.0), position_probe_mm=0.005,
            angle_probe_rad=0.0005, trace_controls=TRACE, target_gamma_degrees=90.0,
            maximum_gamma_target_residual_degrees=0.05,
            maximum_adjacent_gamma_change_degrees=0.05,
            maximum_adjacent_relative_tbar_change=0.1,
            tbar_relative_change_absolute_floor_us_per_mm2=1.0e-4,
            minimum_stability_margin=0.9,
            maximum_abs_normalized_period_slope_per_v=1.0e-4,
        )
        self.assertEqual(result["status"], "screen_pass_diagnostic_only")
        self.assertEqual(len(result["normalized_period_slopes_per_v"]), 3)
        self.assertLess(max(abs(value) for value in result["normalized_period_slopes_per_v"]), 1.0e-5)
        json.dumps(result, allow_nan=False)
        for direction in ("-1", "1"):
            for energy in ("0.90000000000000002", "1", "1.1000000000000001"):
                expected_scale_count = 3 if energy == "1" else 1
                self.assertEqual(
                    len(result["directions"][direction][energy]["scales"]),
                    expected_scale_count,
                )
                if energy != "1":
                    self.assertIsNone(
                        result["directions"][direction][energy][
                            "last_adjacent_gamma_change_degrees"
                        ]
                    )


class RankingTests(unittest.TestCase):
    @staticmethod
    def report(tbar: float, margin: float, peak: float, voltage: float, *, passed: bool = True):
        return {
            "status": "screen_pass_diagnostic_only" if passed else "screen_fail_diagnostic_only",
            "selection_metrics": {
                "maximum_absolute_Tbar_xx_us_per_mm2": tbar,
                "minimum_transverse_stability_margin": margin,
                "sampled_peak_field_v_per_mm": peak,
                "maximum_absolute_mirror_voltage_v": voltage,
            },
        }

    def test_ranking_is_lexicographic_and_retains_declared_ties(self) -> None:
        reports = [
            self.report(1.0, 0.2, 5.0, 8.0),
            self.report(1.0004, 0.3, 6.0, 7.0),
            self.report(0.2, 0.9, 1.0, 1.0, passed=False),
        ]
        tied = rank_screened_members(reports, metric_tolerances=(0.001, 0.11, 2.0, 2.0))
        self.assertEqual(tied["selected_member_indices"], [0, 1])
        self.assertTrue(tied["tie_retained"])
        selected = rank_screened_members(reports, metric_tolerances=(0.001, 0.01, 2.0, 2.0))
        self.assertEqual(selected["selected_member_indices"], [1])
        self.assertEqual(selected["primary_member_index"], 1)

    def test_family_screen_rejects_inconsistent_feasible_count(self) -> None:
        family = {"role": "mrtof_real_3d_mirror_l0_voltage_family", "feasible_member_count": 2,
                  "members": [{"l0_feasible": True, "mirror_voltages_v": [0, 1, 0, 0, 0]}]}
        with self.assertRaisesRegex(RealFieldL1Error, "feasible-member count"):
            screen_feasible_family(
                family, harmonic_basis(), evaluation_arguments={}, ranking_metric_tolerances=(0, 0, 0, 0),
            )


if __name__ == "__main__":
    unittest.main()
