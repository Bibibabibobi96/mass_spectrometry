"""Small independent linear-response oracle; no SIMION process."""
from __future__ import annotations

import unittest

import numpy as np

from msplatform.analysis.reflectron_voltage_fit import optimize


class ReflectronVoltageFitTests(unittest.TestCase):
    def test_export_columns_and_nontrivial_monotone_fit(self) -> None:
        # Four independent ring responses are exact coordinate selectors.
        x = np.array([0.5, 1.5, 3.5, 4.5])
        basis = np.zeros((4, 8))
        basis[np.arange(4), [1, 2, 4, 5]] = 1.0
        actual_x, actual_basis = x, basis
        result = optimize(actual_x, actual_basis, stage1_count=2, stage2_count=2,
            stage1_length_mm=3.0, stage2_length_mm=3.0, midgrid_voltage_v=3.0,
            backplate_voltage_v=6.0, regularization=0.0)
        first = result["stage1_ring_voltages_V"]
        second = result["stage2_ring_voltages_V"]
        self.assertLessEqual(0.0, first[0])
        self.assertLessEqual(first[0], first[1])
        self.assertLessEqual(first[1], 3.0)
        self.assertLessEqual(3.0, second[0])
        self.assertLessEqual(second[0], second[1])
        self.assertLessEqual(second[1], 6.0)
        self.assertLess(result["fit"]["optimized_axis_potential_rms_error_V"],
                        result["fit"]["baseline_axis_potential_rms_error_V"])
        self.assertGreater(result["fit"]["maximum_voltage_change_V"], 0.0)

        # This fixed binary selector has a feasible analytic optimum equal to
        # x. The captured old implementation returned these values exactly;
        # this is a software fixture, not a physical tolerance.
        np.testing.assert_array_equal(first + second, x)

    def test_excluded_planes_do_not_affect_the_fit(self) -> None:
        x = np.array([0.5, 1.5, 3.5, 4.5])
        basis = np.zeros((4, 8))
        basis[np.arange(4), [1, 2, 4, 5]] = 1.0
        arguments = dict(stage1_count=2, stage2_count=2, stage1_length_mm=3.0,
                         stage2_length_mm=3.0, midgrid_voltage_v=3.0,
                         backplate_voltage_v=6.0, regularization=0.0)
        reference = optimize(x, basis, **arguments)
        poisoned = np.full((3, 8), 1e8)
        extended = optimize(np.concatenate((x, [0.0, 3.0, 6.0])),
                                np.vstack((basis, poisoned)), **arguments)
        self.assertEqual(extended, reference)

    def test_wrong_native_electrode_count_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "basis electrode count"):
            optimize(np.array([1.0]), np.zeros((1, 7)), stage1_count=2, stage2_count=2,
                stage1_length_mm=3.0, stage2_length_mm=3.0, midgrid_voltage_v=3.0,
                backplate_voltage_v=6.0, regularization=0.0)



if __name__ == "__main__":
    unittest.main()
