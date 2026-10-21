"""Analytic and CLI regression tests for conditional TOF planning budgets."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

from common.analysis.tof_error_budget import calculate_tof_error_budget


class TofErrorBudgetTest(unittest.TestCase):
    def test_known_peak_width_and_remaining_margin(self):
        result = calculate_tof_error_budget(2.0, 10.0, minimum_resolution=8.0)
        self.assertAlmostEqual(result["reference_fwhm_s"], 0.1)
        self.assertAlmostEqual(result["maximum_fwhm_s"], 0.125)
        self.assertAlmostEqual(result["remaining_fwhm_margin_s"], 0.025)
        self.assertTrue(result["reference_meets_target"])
        self.assertFalse(result["qualification"])

    def test_gaussian_limits_reconstruct_requested_resolution(self):
        # A unit-width normal density has half-height at +/-sqrt(2 ln 2).
        # Independent errors add variances; affine errors add standard deviations.
        half_height = math.sqrt(2.0 * math.log(2.0))
        result = calculate_tof_error_budget(2.0, 10.0, minimum_resolution=8.0)
        gaussian = result["gaussian_planning"]
        sigma = gaussian["reference_sigma_s"]
        independent = gaussian["independent_zero_mean_sigma_limit_s"]
        correlated = gaussian["worst_positive_correlation_sigma_limit_s"]
        for final_sigma in (math.hypot(sigma, independent), sigma + correlated):
            final_width = 2.0 * half_height * final_sigma
            self.assertAlmostEqual(2.0 / (2.0 * final_width), 8.0, places=13)
        # For 25% width headroom the independent allowance is three times larger.
        self.assertAlmostEqual(independent / correlated, 3.0, places=13)

    def test_budgets_scale_with_flight_time_and_inverse_resolution(self):
        original = calculate_tof_error_budget(1.0, 100.0, minimum_resolution=90.0)
        longer = calculate_tof_error_budget(3.0, 100.0, minimum_resolution=90.0)
        higher = calculate_tof_error_budget(1.0, 300.0, minimum_resolution=270.0)
        for key in ("reference_fwhm_s", "maximum_fwhm_s", "remaining_fwhm_margin_s"):
            self.assertAlmostEqual(longer[key] / original[key], 3.0)
            self.assertAlmostEqual(higher[key] / original[key], 1.0 / 3.0)
        for key in ("independent_zero_mean_sigma_limit_s",
                    "worst_positive_correlation_sigma_limit_s"):
            base = original["gaussian_planning"][key]
            self.assertAlmostEqual(longer["gaussian_planning"][key] / base, 3.0)
            self.assertAlmostEqual(higher["gaussian_planning"][key] / base, 1.0 / 3.0)

    def test_equal_target_has_zero_added_noise_budget(self):
        result = calculate_tof_error_budget(1.0, 10.0, minimum_resolution=10.0)
        self.assertTrue(result["reference_meets_target"])
        self.assertEqual(result["remaining_fwhm_margin_s"], 0.0)
        self.assertEqual(result["gaussian_planning"]["independent_zero_mean_sigma_limit_s"], 0.0)
        self.assertEqual(result["gaussian_planning"]["worst_positive_correlation_sigma_limit_s"], 0.0)

    def test_unmet_target_has_null_noise_budget_and_negative_margin(self):
        result = calculate_tof_error_budget(1.0, 10.0, minimum_resolution=20.0)
        self.assertFalse(result["reference_meets_target"])
        self.assertAlmostEqual(result["remaining_fwhm_margin_s"], -0.025)
        self.assertIsNone(result["gaussian_planning"]["independent_zero_mean_sigma_limit_s"])
        self.assertIsNone(result["gaussian_planning"]["worst_positive_correlation_sigma_limit_s"])

    def test_mass_bias_bound_protects_both_signs_with_fixed_calibration(self):
        result = calculate_tof_error_budget(
            2.0, 10.0, minimum_resolution=8.0, mass_bias_limit_ppm=210000.0
        )
        bias = result["common_bias"]["maximum_absolute_bias_s"]
        self.assertAlmostEqual(bias, 0.2, places=14)
        self.assertAlmostEqual(((2.0 + bias) / 2.0) ** 2 - 1.0, 0.21)
        self.assertLess(abs(((2.0 - bias) / 2.0) ** 2 - 1.0), 0.21)
        no_bias = calculate_tof_error_budget(2.0, 10.0, minimum_resolution=8.0)
        self.assertEqual(result["gaussian_planning"], no_bias["gaussian_planning"])
        self.assertIsNone(no_bias["common_bias"]["maximum_absolute_bias_s"])

    def test_tiny_and_zero_mass_budgets_do_not_cancel(self):
        zero = calculate_tof_error_budget(1.0, 10.0, minimum_resolution=8.0, mass_bias_limit_ppm=0)
        tiny = calculate_tof_error_budget(1.0, 10.0, minimum_resolution=8.0, mass_bias_limit_ppm=1e-12)
        self.assertEqual(zero["common_bias"]["maximum_absolute_bias_s"], 0.0)
        self.assertGreater(tiny["common_bias"]["maximum_absolute_bias_s"], 0.0)
        self.assertAlmostEqual(tiny["common_bias"]["maximum_absolute_bias_s"] / 5e-19, 1.0)

    def test_invalid_positive_inputs_are_rejected(self):
        for field in ("flight_time_s", "reference_resolution", "minimum_resolution"):
            for invalid in (0, -1, math.nan, math.inf, -math.inf, True, "1", None):
                with self.subTest(field=field, invalid=invalid):
                    values = dict(flight_time_s=1.0, reference_resolution=10.0, minimum_resolution=8.0)
                    values[field] = invalid
                    with self.assertRaises(ValueError):
                        calculate_tof_error_budget(**values)

    def test_invalid_mass_budget_is_rejected(self):
        for invalid in (-1, 1e6, math.inf, math.nan, True, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                calculate_tof_error_budget(1, 10, minimum_resolution=8, mass_bias_limit_ppm=invalid)

    def test_nonrepresentable_derived_values_fail_closed(self):
        for inputs in ((1e308, 1e-308, 1e-308), (1e-308, 1e308, 1e308), (1, 1e308, 1e-308)):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                calculate_tof_error_budget(inputs[0], inputs[1], minimum_resolution=inputs[2])


class TofErrorBudgetCliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", "-m", "common.analysis.tof_error_budget", *arguments],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            check=False,
        )

    def test_cli_converts_microseconds_and_loss_to_explicit_minimum(self):
        process = self.run_cli(
            "--flight-time-us", "100", "--reference-resolution", "100000",
            "--max-resolution-loss-pct", "1", "--mass-bias-ppm", "1",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertAlmostEqual(result["flight_time_s"], 1e-4)
        self.assertEqual(result["minimum_resolution"], 99000.0)
        self.assertAlmostEqual(result["reference_fwhm_s"] / 5e-10, 1.0)
        self.assertFalse(result["qualification"])

    def test_cli_explicit_minimum_matches_public_function(self):
        process = self.run_cli(
            "--flight-time-us", "1000000", "--reference-resolution", "10",
            "--minimum-resolution", "8",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), calculate_tof_error_budget(1, 10, minimum_resolution=8))

    def test_cli_markdown_displays_us_and_ps_without_changing_budget(self):
        process = self.run_cli(
            "--flight-time-us", "100", "--reference-resolution", "100000",
            "--minimum-resolution", "80000", "--format", "markdown",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        for row in ("| Flight time T | 100 | us |", "| Reference FWHM | 500 | ps |",
                    "| Maximum FWHM | 625 | ps |", "| Remaining FWHM margin | 125 | ps |"):
            self.assertIn(row, process.stdout)
        self.assertIn("**Planning only; not qualification.**", process.stdout)
        self.assertIn("not per-particle maximum errors, dt or rtol", process.stdout)
        self.assertIn("Maximum absolute common bias | Not allocated / not applicable | ps", process.stdout)

    def test_cli_markdown_unmet_target_keeps_negative_margin_and_null_budgets(self):
        process = self.run_cli(
            "--flight-time-us", "100", "--reference-resolution", "100000",
            "--minimum-resolution", "200000", "--format", "markdown",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("Reference meets target: no.", process.stdout)
        self.assertIn("| Remaining FWHM margin | -250 | ps |", process.stdout)
        for label in ("Independent Gaussian sigma budget", "Positive-correlated Gaussian sigma budget"):
            self.assertIn(f"| {label} | Not allocated / not applicable | ps |", process.stdout)

    def test_cli_rejects_missing_or_conflicting_targets(self):
        base = ("--flight-time-us", "1", "--reference-resolution", "10")
        for target in ((), ("--minimum-resolution", "8", "--max-resolution-loss-pct", "1")):
            with self.subTest(target=target):
                process = self.run_cli(*base, *target)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")

    def test_cli_rejects_invalid_loss_percent_and_nonfinite_input(self):
        for loss in ("-1", "100", "nan", "inf"):
            with self.subTest(loss=loss):
                process = self.run_cli(
                    "--flight-time-us", "1", "--reference-resolution", "10",
                    "--max-resolution-loss-pct", loss,
                )
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
        process = self.run_cli(
            "--flight-time-us", "nan", "--reference-resolution", "10", "--minimum-resolution", "8"
        )
        self.assertEqual(process.returncode, 2)


if __name__ == "__main__":
    unittest.main()
