"""Small independent linear-response oracle; no SIMION process."""
from __future__ import annotations

import csv
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from msplatform.backends.simion import optimize_reflectron_ring_voltages as fit


class ReflectronVoltageFitTests(unittest.TestCase):
    def test_export_columns_and_nontrivial_monotone_fit(self) -> None:
        # Four independent ring responses are exact coordinate selectors.
        x = np.array([0.5, 1.5, 3.5, 4.5])
        basis = np.zeros((4, 8))
        basis[np.arange(4), [1, 2, 4, 5]] = 1.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "basis.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["x_mm", *[f"basis_{i}_V" for i in range(1, 9)]])
                for position, row in zip(x, basis, strict=True):
                    writer.writerow([position, *(row * 10000.0)])
            actual_x, actual_basis = fit._load_basis(path)
        np.testing.assert_array_equal(actual_x, x)
        np.testing.assert_array_equal(actual_basis, basis)
        result = fit.optimize(actual_x, actual_basis, stage1_count=2, stage2_count=2,
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
        reference = fit.optimize(x, basis, **arguments)
        poisoned = np.full((3, 8), 1e8)
        extended = fit.optimize(np.concatenate((x, [0.0, 3.0, 6.0])),
                                np.vstack((basis, poisoned)), **arguments)
        self.assertEqual(extended, reference)

    def test_wrong_native_electrode_count_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "basis electrode count"):
            fit.optimize(np.array([1.0]), np.zeros((1, 7)), stage1_count=2, stage2_count=2,
                stage1_length_mm=3.0, stage2_length_mm=3.0, midgrid_voltage_v=3.0,
                backplate_voltage_v=6.0, regularization=0.0)

    def test_standalone_cli_resolves_default_only_when_omitted(self) -> None:
        contract = {"rings": {"stage1_count": 2, "stage2_count": 2},
                    "geometry_mm": {"L_stage1": 3, "L_stage2": 3},
                    "electrodes_V": {"midgrid": 3, "backplate": 6}}
        result = {"schema_version": 1, "stage1_count": 2, "stage2_count": 2,
                  "stage1_ring_voltages_V": [1, 2], "stage2_ring_voltages_V": [4, 5]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            args = ["fit", "--basis-csv", str(root / "basis.csv"),
                    "--contract", str(contract_path), "--output", str(root / "fit.json")]
            for option, expected in (([], 0.0001), (["--regularization", "0"], 0.0)):
                with (self.subTest(option=option), patch.object(sys, "argv", args + option),
                        patch.object(fit, "_load_basis", return_value=([], [])),
                        patch.object(fit, "optimize", return_value=result) as optimize,
                        redirect_stdout(StringIO())):
                    fit.main()
                    self.assertEqual(optimize.call_args.kwargs["regularization"], expected)

    def test_missing_authoring_resource_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(fit, "files", return_value=Path(directory)):
            with self.assertRaises(FileNotFoundError):
                fit.load_authoring_default()


if __name__ == "__main__":
    unittest.main()
