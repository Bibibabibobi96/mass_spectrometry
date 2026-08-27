"""Focused checks of equation-first ideal acceptance construction."""

from __future__ import annotations

import json
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_linear_design import (
    LinearDesignError,
    find_fixed_length_designs,
    solve_linear_third_order_design,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import NumericalSourceSpec
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    ReflectronGeometry,
    exact_total_normalized_time,
)


class LinearDesignTests(unittest.TestCase):
    def setUp(self):
        self.spec = NumericalSourceSpec(100., 1.498375640839315,
                                        -2.9323518410018137, 228.80604377795845)
        self.mirror = ReflectronGeometry(120., 96.1563, 600., 600.)
        self.controls = dict(
            field1_v_per_mm=250/3.25,
            center_to_grid1_mm=3.25-self.spec.center_x_mm,
            grid2_voltage_fraction=1619.6945038929748/1865.2596646799475,
            reflectron_stage1_voltage_v=1701.7426470174573,
            nominal_energy_per_charge_v=2000.,
            focus_drift_mm=42.742615461548496,
            characteristic_half_width_mm=1.4,
            condition_limit=1e12,
            coefficient_tolerance_ns=1e-6,
        )

    def solve(self, **changes):
        return solve_linear_third_order_design(self.spec, self.mirror,
                                               **(self.controls | changes))

    def test_recovers_existing_third_order_solution(self):
        result = self.solve()
        np.testing.assert_allclose(result.report["zone_lengths_mm"], [3.25, 5.1, 11.9], rtol=2e-8)
        np.testing.assert_allclose(result.report["fields_v_per_mm"],
                                   [250/3.25, 48.15003152685739, 136.1087818397458,
                                    9.880402594970798], rtol=2e-8)
        self.assertTrue(result.report["equation_closed"])
        self.assertAlmostEqual(result.report["fourth_order_coefficient_ns_per_mm4"], .261432, places=5)
        json.dumps(result.report, allow_nan=False)

    def test_fixed_inputs_preserved_and_exact_oracle_reused(self):
        result = self.solve()
        point = result.point
        self.assertEqual(point.reflectron, self.mirror)
        self.assertEqual(point.design_source, self.spec.affine())
        self.assertEqual(point.focus_drift_mm, self.controls["focus_drift_mm"])
        self.assertEqual(point.inner.stage1_voltage_drop_v,
                         self.controls["reflectron_stage1_voltage_v"])
        y = np.array([-.03, 0., .03])
        exact = np.asarray(exact_total_normalized_time(
            point.design_source, point.state, point.reflectron, point.inner,
            self.spec.center_x_mm+y, point.focus_drift_mm
        )) * point.design_source.time_scale_s_per_mm_sqrt_v * 1e9
        polynomial = np.polynomial.polynomial.polyval(y, result.report["coefficients_ns_per_mm_power"])
        np.testing.assert_allclose(exact, polynomial, atol=2e-10, rtol=0)
        self.assertFalse(result.report["particle_peak_optimization_performed"])

    def test_nonpositive_field_root_rejected(self):
        with self.assertRaises(LinearDesignError) as caught:
            self.solve(center_to_grid1_mm=10., grid2_voltage_fraction=.5,
                       reflectron_stage1_voltage_v=1200.)
        self.assertEqual(caught.exception.reason, "NO_POSITIVE_FIELD_SOLUTION")
        self.assertIn("inverse_fields_mm_per_v", caught.exception.report)

    def test_condition_threshold_is_caller_owned(self):
        with self.assertRaises(LinearDesignError) as caught:
            self.solve(condition_limit=1.)
        self.assertEqual(caught.exception.reason, "SINGULAR_OR_ILL_CONDITIONED_EQUATION_MATRIX")

    def test_invalid_controls_and_center_events(self):
        for changes in ({"center_to_grid1_mm": -1.},
                        {"grid2_voltage_fraction": 1.},
                        {"field1_v_per_mm": float("nan")},
                        {"reflectron_stage1_voltage_v": 3000.},
                        {"center_to_grid1_mm": 30.}):
            with self.subTest(changes=changes), self.assertRaises(LinearDesignError):
                self.solve(**changes)

    def fixed_length(self, **changes):
        controls = {key: value for key, value in self.controls.items()
                    if key != "reflectron_stage1_voltage_v"}
        controls.update(total_accel_length_mm=20.25,
                        stage1_voltage_grid_v=list(np.arange(1300., 1950., 15.)),
                        length_tolerance_mm=1e-7, root_xtol_v=1e-10)
        return find_fixed_length_designs(self.spec, self.mirror, **(controls | changes))

    def test_fixed_length_recovers_original_point_without_peak_ranking(self):
        results = self.fixed_length(stage1_voltage_grid_v=list(np.arange(1690., 1711., 1.)))
        self.assertTrue(results)
        closest = min(results, key=lambda result: abs(
            result.point.inner.stage1_voltage_drop_v-self.controls["reflectron_stage1_voltage_v"]))
        self.assertAlmostEqual(closest.point.inner.stage1_voltage_drop_v,
                               self.controls["reflectron_stage1_voltage_v"], places=6)
        for result in results:
            self.assertLess(abs(sum(result.report["zone_lengths_mm"])-20.25), 1e-7)
            self.assertTrue(result.report["equation_closed"])
            self.assertFalse(result.report["fixed_length_equation"]["all_roots_in_continuous_domain_proved"])

    def test_fixed_length_returns_multiple_roots(self):
        self.spec = replace(self.spec, center_x_mm=4.5)
        roots = self.fixed_length(field1_v_per_mm=50., center_to_grid1_mm=4.5,
                                  grid2_voltage_fraction=.99)
        voltages = [result.point.inner.stage1_voltage_drop_v for result in roots]
        self.assertEqual(len(voltages), 2)
        np.testing.assert_allclose(voltages, [1765.1587877126208, 1791.7631558603202], atol=1e-6)

    def test_fixed_length_rejects_a_pole_and_invalid_interior(self):
        reference = self.solve()
        module = "projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_linear_design"
        for invalid_midpoint in (False, True):
            def fabricated(*args, reflectron_stage1_voltage_v, **kwargs):
                u = reflectron_stage1_voltage_v
                if invalid_midpoint and u == 1700.:
                    raise LinearDesignError("NO_POSITIVE_FIELD_SOLUTION")
                delta = u-1700.
                error = delta if invalid_midpoint else 1/delta
                report = {**reference.report, "zone_lengths_mm": [20.25+error, 0., 0.],
                          "normalized_matrix_determinant_sign": 1. if invalid_midpoint else np.sign(delta)}
                return replace(reference, report=report)
            with self.subTest(invalid_midpoint=invalid_midpoint), patch(
                    module+".solve_linear_third_order_design", side_effect=fabricated):
                self.assertEqual(self.fixed_length(stage1_voltage_grid_v=[1699., 1701.]), [])

    def test_fixed_length_invalid_grid_and_tolerances_rejected(self):
        for changes in ({"stage1_voltage_grid_v": [1700., 1700.]},
                        {"stage1_voltage_grid_v": [1700.]},
                        {"total_accel_length_mm": 0.},
                        {"root_xtol_v": -1.}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.fixed_length(**changes)


if __name__ == "__main__":
    unittest.main()
