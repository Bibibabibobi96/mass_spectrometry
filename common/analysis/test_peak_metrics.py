"""Hand-calculated peak widths and invalid numerical-domain regressions."""

from dataclasses import replace
import unittest

import numpy as np

from common.analysis.peak_metrics import (
    AnalysisSettings, bootstrap_resolution_difference, compare_peak_shapes, half_height_width,
    compute_peak_metrics, compute_time_peak_metrics,
)


class AnalysisSettingsTests(unittest.TestCase):
    def test_defaults_and_valid_boundary_settings(self) -> None:
        defaults = AnalysisSettings()
        self.assertEqual(defaults.to_dict()["half_height_interpolation"], "linear")
        for threshold in (0.0, 1.0):
            settings = replace(defaults, grid_points=3, standardized_grid_points=3,
                               mode_threshold_fraction=threshold,
                               standardized_grid_min=-1.0, standardized_grid_max=1.0)
            self.assertEqual(settings.mode_threshold_fraction, threshold)

    def test_grid_point_counts_require_integers_of_at_least_three(self) -> None:
        for name in ("grid_points", "standardized_grid_points"):
            for value in (True, np.bool_(True), 2, 0, -1, 3.0, "3", np.nan, np.inf):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    AnalysisSettings(**{name: value})

    def test_real_settings_reject_nonfinite_and_nonnumeric_values(self) -> None:
        for name in ("bandwidth_multiplier", "mode_threshold_fraction",
                     "standardized_grid_min", "standardized_grid_max"):
            for value in (True, np.bool_(True), np.nan, np.inf, -np.inf, "0.5", 1 + 2j):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    AnalysisSettings(**{name: value})

    def test_bandwidth_threshold_and_standardized_domain_bounds(self) -> None:
        cases = (
            {"bandwidth_multiplier": 0.0},
            {"bandwidth_multiplier": -1.0},
            {"mode_threshold_fraction": -0.01},
            {"mode_threshold_fraction": 1.01},
            {"standardized_grid_min": 6.0},
            {"standardized_grid_max": -7.0},
        )
        for settings in cases:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                AnalysisSettings(**settings)


class HalfHeightWidthTests(unittest.TestCase):
    def test_asymmetric_triangle_has_hand_calculated_interpolated_width(self) -> None:
        # Unit peak at x=1 with zero endpoints at -1 and 4: crossings 0 and 2.5.
        self.assertEqual(half_height_width(np.array([-1, 1, 4]), np.array([0, 1, 0])),
                         (2.5, 0.0, 2.5, 1))

    def test_two_peaks_select_global_maximum_and_nearest_crossings(self) -> None:
        # Lower peak at x=1 also exceeds half-height, but the valley separates it.
        grid = np.arange(9, dtype=float)
        density = np.array([0, 3, 0, 0, 4, 3, 2, 1, 0], dtype=float)
        self.assertEqual(half_height_width(grid, density), (2.5, 3.5, 6.0, 4))

    def test_tied_global_peaks_keep_first_peak_policy(self) -> None:
        self.assertEqual(half_height_width(np.arange(5), np.array([0, 2, 0, 2, 0])),
                         (1.0, 0.5, 1.5, 1))

    def test_shapes_and_lengths_fail_before_peak_selection(self) -> None:
        cases = (
            (np.array(0.0), np.array([0, 1, 0]), "one-dimensional"),
            (np.arange(3), np.array([[0, 1, 0]]), "one-dimensional"),
            (np.empty((0, 3)), np.empty((0, 3)), "one-dimensional"),
            (np.array([]), np.array([]), "equal length of at least three"),
            (np.arange(2), np.array([0, 1]), "equal length of at least three"),
            (np.arange(4), np.array([0, 1, 0]), "equal length of at least three"),
        )
        for grid, density, message in cases:
            with self.subTest(grid=grid, density=density), self.assertRaisesRegex(ValueError, message):
                half_height_width(grid, density)

    def test_nonfinite_and_complex_values_are_rejected(self) -> None:
        for value in (np.nan, np.inf, -np.inf):
            for grid, density in ((np.array([0, value, 2]), np.array([0, 1, 0])),
                                  (np.arange(3), np.array([0, value, 0]))):
                with self.subTest(grid=grid, density=density), self.assertRaisesRegex(ValueError, "finite"):
                    half_height_width(grid, density)
        for grid, density in ((np.array([0, 1 + 1j, 2]), np.array([0, 1, 0])),
                              (np.arange(3), np.array([0, 1 + 1j, 0]))):
            with self.subTest(grid=grid, density=density), self.assertRaisesRegex(ValueError, "real"):
                half_height_width(grid, density)

    def test_grid_order_and_density_domain_are_rejected(self) -> None:
        for grid in (np.array([0, 1, 1]), np.array([2, 1, 0]), np.array([0, 2, 1])):
            with self.subTest(grid=grid), self.assertRaisesRegex(ValueError, "strictly increasing"):
                half_height_width(grid, np.array([0, 1, 0]))
        for density in (np.array([0, 0, 0]), np.array([-1, 1, 0])):
            with self.subTest(density=density), self.assertRaisesRegex(ValueError, "nonnegative.*positive"):
                half_height_width(np.arange(3), density)

    def test_missing_half_height_crossings_identify_the_truncated_side(self) -> None:
        for density, missing in (([3, 4, 0], "left"), ([0, 4, 3], "right"),
                                 ([3, 4, 3], "both"), ([4, 1, 0], "left"),
                                 ([0, 1, 4], "right")):
            with self.subTest(density=density), self.assertRaisesRegex(ValueError, missing + " half-height"):
                half_height_width(np.arange(3), np.array(density))


class TimePeakResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tof = np.array([1.1, 1.2, 1.4, 1.7, 1.8, 2.0])
        self.settings = AnalysisSettings(grid_points=401)

    def test_time_only_metrics_share_legacy_time_values_without_mass(self) -> None:
        legacy, old_spectra = compute_peak_metrics(self.tof, 524.0, self.settings)
        current, spectra = compute_time_peak_metrics(self.tof, self.settings)
        for key in current.keys() & legacy.keys():
            self.assertEqual(current[key], legacy[key], key)
        for key in spectra:
            np.testing.assert_array_equal(spectra[key], old_spectra[key])
        self.assertNotIn("nominal_mass_Da", current)
        self.assertNotIn("mass_grid_Da", spectra)
        self.assertNotIn("significant_kde_modes", current)
        metadata = current["analysis_metadata"]
        self.assertEqual(metadata["method_id"], "common_gaussian_kde_time_v2")
        self.assertIsNone(metadata["mass_axis"])
        self.assertEqual(metadata["time_reference"]["clock_qualification"], "unspecified")
        self.assertNotIn("analysis_metadata", legacy)
        self.assertEqual(metadata["settings"], self.settings.to_dict())
        self.assertEqual(metadata["sample_sigma_ddof"], 1)
        self.assertEqual(metadata["sample_count"], len(self.tof))
        self.assertEqual(metadata["units"], {"tof": "us", "time_width": "ns", "time_density": "1/us"})
        self.assertEqual(metadata["status"], "computed")
        self.assertEqual(metadata["scientific_qualification"], "not_assessed")

    def test_equal_relative_weights_preserve_kde_and_nonuniform_weights_fail(self) -> None:
        expected, expected_spectra = compute_time_peak_metrics(self.tof, self.settings)
        actual, spectra = compute_time_peak_metrics(self.tof, self.settings, weights=np.full(6, 3.5))
        self.assertEqual({key: value for key, value in actual.items() if key != "analysis_metadata"},
                         {key: value for key, value in expected.items() if key != "analysis_metadata"})
        self.assertEqual(actual["analysis_metadata"]["weight_sum"], 21.)
        self.assertEqual(expected["analysis_metadata"]["weight_sum"], 6.)
        self.assertEqual(actual["analysis_metadata"]["effective_sample_count"], 6.)
        for key in spectra:
            np.testing.assert_array_equal(spectra[key], expected_spectra[key])
        for weights in ([1, 1, 1, 1, 1, 2], [0]*6, [-1]*6, [np.nan]*6,
                        [np.inf]*6, [1]*5, [[1]*6], [1+1j]*6, [True]*6, ["3.5"]*6,
                        [True, 1, 1, 1, 1, 1], [np.finfo(float).max]*6):
            with self.subTest(weights=weights):
                with self.assertRaises(ValueError):
                    compute_time_peak_metrics(self.tof, self.settings, weights=weights)
                with self.assertRaises(ValueError):
                    compute_peak_metrics(self.tof, 524, self.settings, weights=weights)

    def test_time_input_domain_is_explicit(self) -> None:
        for sample in ([[1, 2, 3]], [1+1j, 2, 3], [1, 2, np.nan], [0, 1, 2],
                       [-1, 1, 2], [1, 2], [1, 1, 1]):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                compute_time_peak_metrics(sample, self.settings)

    def test_translation_changes_time_ratio_but_not_width(self) -> None:
        original, _ = compute_time_peak_metrics(self.tof, self.settings)
        shifted, _ = compute_time_peak_metrics(self.tof + 10, self.settings)
        self.assertAlmostEqual(original["direct_fwhm_tof_ns"], shifted["direct_fwhm_tof_ns"], places=10)
        self.assertAlmostEqual(shifted["time_equivalent_resolution"] / original["time_equivalent_resolution"],
                               (self.tof.mean()+10)/self.tof.mean(), places=12)

    def test_nominal_mass_mapping_names_relative_axis_and_preserves_scaling(self) -> None:
        low, _ = compute_peak_metrics(self.tof, 262, self.settings, include_result_metadata=True)
        high, _ = compute_peak_metrics(self.tof, 524, self.settings, include_result_metadata=True)
        self.assertEqual(high["direct_fwhm_mass_Da"], 2*low["direct_fwhm_mass_Da"])
        self.assertEqual(high["mass_resolution"], low["mass_resolution"])
        axis = high["analysis_metadata"]["mass_axis"]
        self.assertEqual((axis["quantity"], axis["unit"]), ("mass", "Da"))
        self.assertEqual(axis["mapping_method"], "nominal_mean_relative_square_v1")
        self.assertFalse(axis["absolute_calibration"])
        self.assertEqual(axis["reference_tof_us"], float(self.tof.mean()))

    def test_time_and_mass_mode_counts_have_distinct_domains(self) -> None:
        # Fixed synthetic shoulder: squaring stretches the right tail, changing
        # the separately fitted KDE's mode count. This is not historical data.
        rng = np.random.default_rng(200)
        for index in range(4):
            sample = np.r_[rng.normal(1, .15, 30), rng.normal(1.5+index/100, .08, 8)]
        legacy, _ = compute_peak_metrics(sample, 524, self.settings)
        current, _ = compute_time_peak_metrics(sample, self.settings)
        self.assertEqual(legacy["significant_kde_modes"], 2)
        self.assertEqual(current["significant_time_kde_modes"], 1)


class PeakPairingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tof = np.array([71.99, 72.01, 71.98, 72.03, 72.04, 71.97, 72.0])
        self.ids = np.array([31, 7, 90, 12, 101, 55, 4])
        self.settings = AnalysisSettings(grid_points=101, standardized_grid_points=101)

    def test_equal_length_without_ids_only_compares_distributions(self) -> None:
        comparison, spectra = compare_peak_shapes(self.tof, self.tof[::-1], self.settings)
        self.assertIsNone(comparison["paired_standardized_tof_correlation"])
        self.assertEqual(comparison["standardized_ks_distance"], 0.0)
        np.testing.assert_allclose(spectra["left_density"], spectra["right_density"], rtol=1e-14)

    def test_distribution_comparison_accepts_unequal_sample_counts(self) -> None:
        comparison, _ = compare_peak_shapes(self.tof, self.tof[:5], self.settings)
        self.assertEqual((comparison["left_particles"], comparison["right_particles"]), (7, 5))
        self.assertIsNone(comparison["paired_standardized_tof_correlation"])

    def test_explicit_nonconsecutive_ids_enable_paired_correlation(self) -> None:
        comparison, _ = compare_peak_shapes(
            self.tof, self.tof.copy(), self.settings,
            left_particle_ids=self.ids, right_particle_ids=self.ids.copy(),
        )
        self.assertAlmostEqual(comparison["paired_standardized_tof_correlation"], 1.0, places=12)

    def test_identical_paired_samples_have_zero_bootstrap_difference(self) -> None:
        result = bootstrap_resolution_difference(
            self.tof, self.tof.copy(), 524.0, resamples=12, seed=7, settings=self.settings,
            left_particle_ids=self.ids, right_particle_ids=self.ids.copy(),
        )
        self.assertEqual(result["resamples_valid"], 12)
        for suffix in ("p2p5", "median", "p97p5"):
            self.assertEqual(result[f"absolute_resolution_difference_pct_{suffix}"], 0.0)

    def test_pairing_rejects_missing_duplicate_nonnumeric_and_misaligned_ids(self) -> None:
        invalid_ids = (
            None, self.ids[:-1], self.ids.reshape(1, -1),
            np.array([31, 7, 90, 12, 101, 55, 31]),
            self.ids.astype(float), self.ids.astype(str), np.ones(7, dtype=bool),
            [True, 7, 90, 12, 101, 55, 4], [np.nan, 7, 90, 12, 101, 55, 4],
            self.ids + 1, self.ids[::-1],
        )
        for invalid in invalid_ids:
            for left_ids, right_ids in ((invalid, self.ids), (self.ids, invalid)):
                arguments = dict(left_particle_ids=left_ids, right_particle_ids=right_ids)
                with self.subTest(ids=arguments):
                    with self.assertRaises(ValueError):
                        compare_peak_shapes(self.tof, self.tof, self.settings, **arguments)
                    with self.assertRaises(ValueError):
                        bootstrap_resolution_difference(
                            self.tof, self.tof, 524.0, resamples=1, settings=self.settings, **arguments,
                        )

    def test_ids_matching_different_sample_lengths_cannot_be_paired(self) -> None:
        arguments = dict(left_particle_ids=self.ids, right_particle_ids=self.ids[:5])
        with self.assertRaises(ValueError):
            compare_peak_shapes(self.tof, self.tof[:5], self.settings, **arguments)
        with self.assertRaises(ValueError):
            bootstrap_resolution_difference(
                self.tof, self.tof[:5], 524.0, resamples=1, settings=self.settings, **arguments,
            )

    def test_bootstrap_requires_both_explicit_id_arguments(self) -> None:
        with self.assertRaises(TypeError):
            bootstrap_resolution_difference(self.tof, self.tof, 524.0)
        with self.assertRaises(ValueError):
            bootstrap_resolution_difference(
                self.tof, self.tof, 524.0, left_particle_ids=None, right_particle_ids=None,
            )

    def test_large_integer_ids_are_not_narrowed_to_float(self) -> None:
        ids = np.arange(7, dtype=np.uint64) + np.uint64(2**63)
        comparison, _ = compare_peak_shapes(
            self.tof, self.tof, self.settings, left_particle_ids=ids, right_particle_ids=ids.copy(),
        )
        self.assertAlmostEqual(comparison["paired_standardized_tof_correlation"], 1.0, places=12)
        changed = ids.copy()
        changed[0] += np.uint64(8)
        with self.assertRaisesRegex(ValueError, "identical ordered"):
            compare_peak_shapes(self.tof, self.tof, self.settings,
                                left_particle_ids=ids, right_particle_ids=changed)


if __name__ == "__main__":
    unittest.main()
