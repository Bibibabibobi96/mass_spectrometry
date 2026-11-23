"""Pure trajectory analysis uses complete mother arithmetic and existing peaks."""
from __future__ import annotations

import ast
import copy
import json
import math
from pathlib import Path
import unittest

import numpy as np

from msplatform.analysis import trajectory
from msplatform.analysis.peak_metrics import AnalysisSettings, compute_time_peak_metrics
from msplatform.contracts.clock import ClockIdentity


class TrajectoryAnalysisTests(unittest.TestCase):
    def arguments(self):
        return dict(mother_particle_ids=[41, 9, 88, 701, 55],
            relative_weights={41: 2., 9: 2., 88: 2., 701: 3., 55: 5.},
            classifications=[(41, "detected"), (9, "detected"), (88, "detected"),
                             (701, "unknown"), (55, "censored")],
            categories=["detected", "unknown", "censored"],
            observations=[dict(particle_id=41, instrument_time_us=11.),
                          dict(particle_id=9, instrument_time_us=12.),
                          dict(particle_id=88, instrument_time_us=14.)],
            selected_particle_ids=[41, 9, 88], clock=ClockIdentity("original", "A" * 64),
            method="time_peak", time_reference_instrument_us=10.,
            settings=AnalysisSettings(grid_points=301, standardized_grid_points=101))

    def test_time_peak_common_reference_independent_mean_sigma_and_original_metadata(self):
        args = self.arguments()
        before = copy.deepcopy(args)
        result = trajectory.analyze_trajectory(**args)
        self.assertEqual(result["status"], "analysis_completed")
        metrics = result["peak_metrics"]
        self.assertAlmostEqual(metrics["mean_tof_us"], 7 / 3)
        self.assertAlmostEqual(metrics["std_tof_ns"], math.sqrt(7 / 3) * 1000)
        expected, spectra = compute_time_peak_metrics(np.asarray([1., 2., 4.]), args["settings"],
                                                     weights=np.asarray([2., 2., 2.]))
        self.assertEqual(metrics, expected)
        self.assertEqual(result["spectra"], {key: value.tolist() for key, value in spectra.items()})
        self.assertIsNone(metrics["analysis_metadata"]["mass_axis"])
        self.assertNotIn("mass_resolution", metrics)
        self.assertEqual(result["time_axis"]["reference_instrument_time_us"], 10.)
        self.assertEqual(args, before)
        json.dumps(result, allow_nan=False)

    def test_weighted_complete_mother_denominator_keeps_unknown_and_censored(self):
        args = self.arguments()
        args["method"] = "census"
        result = trajectory.analyze_trajectory(**args)
        self.assertEqual(result["census"]["mother_count"], 5)
        self.assertEqual(result["census"]["mother_weight_sum"], 14.)
        self.assertEqual(result["census"]["weight_sums"], {"detected": 6., "unknown": 3., "censored": 5.})
        self.assertEqual(result["observed_population"]["denominator_particle_ids"], [41, 9, 88, 701, 55])
        self.assertEqual(result["observed_population"]["relative_weight_fraction"], 6 / 14)
        self.assertEqual(result["observed_population"]["count_fraction"], 3 / 5)
        self.assertIsNone(result["peak_metrics"])

    def test_explicit_occurrence_not_latest_or_survivor_selection(self):
        args = self.arguments()
        original = args["observations"]
        args["observation_selection"] = dict(observation_id="exit", direction="outward", occurrence=1)
        args["observations"] = [dict(row, **args["observation_selection"]) for row in original]
        args["observations"] += [dict(row, observation_id="exit", direction="outward", occurrence=2,
                                      instrument_time_us=row["instrument_time_us"] + 100) for row in original]
        result = trajectory.analyze_trajectory(**args)
        self.assertAlmostEqual(result["peak_metrics"]["mean_tof_us"], 7 / 3)
        del args["observation_selection"]
        with self.assertRaisesRegex(ValueError, "explicit occurrence"):
            trajectory.analyze_trajectory(**args)

    def test_event_identity_requires_selection_even_with_one_row_per_particle(self):
        for field, value in (("observation_id", "another_plane"), ("direction", "inward"), ("occurrence", 2)):
            with self.subTest(field=field):
                args = self.arguments()
                args["observations"] = [dict(row, observation_id="exit", direction="outward", occurrence=1)
                                        for row in args["observations"]]
                args["observations"][1][field] = value
                with self.assertRaisesRegex(ValueError, "explicit occurrence selection"):
                    trajectory.analyze_trajectory(**args)
        args = self.arguments()
        args["observations"] = [dict(row, observation_id="exit", direction="outward", occurrence=1)
                                for row in args["observations"]]
        with self.assertRaisesRegex(ValueError, "explicit occurrence selection"):
            trajectory.analyze_trajectory(**args)

    def test_explicit_first_occurrence_keeps_missing_ids_instead_of_mixed_peak(self):
        args = self.arguments()
        args["observations"] = [dict(particle_id=pid, instrument_time_us=time, observation_id="exit",
                                     direction="outward", occurrence=occurrence)
                                for pid, time, occurrence in ((41, 11., 1), (9, 112., 2), (88, 114., 2))]
        args["observation_selection"] = dict(observation_id="exit", direction="outward", occurrence=1)
        result = trajectory.analyze_trajectory(**args)
        self.assertEqual(result["status"], "insufficient_observations")
        self.assertEqual(result["observed_particle_ids"], [41])
        self.assertEqual(result["missing_observation_particle_ids"], [9, 88])
        self.assertIsNone(result["peak_metrics"])
        self.assertEqual(result["selected_population"]["denominator_weight_sum"], 14.)
        self.assertEqual(result["census"]["mother_count"], 5)

    def test_partial_or_mixed_event_and_projected_rows_are_rejected(self):
        for case in ("partial", "mixed_without_selector", "mixed_with_selector", "projected_with_selector"):
            with self.subTest(case=case):
                args = self.arguments()
                if case == "partial":
                    args["observations"][0]["observation_id"] = "exit"
                elif case != "projected_with_selector":
                    args["observations"][0].update(observation_id="exit", direction="outward", occurrence=1)
                if case in {"mixed_with_selector", "projected_with_selector"}:
                    args["observation_selection"] = dict(observation_id="exit", direction="outward", occurrence=1)
                with self.assertRaisesRegex(ValueError, "(identity is incomplete|explicit occurrence selection|identity on every)"):
                    trajectory.analyze_trajectory(**args)

    def test_missing_fewer_than_three_and_zero_variance_are_not_peaks(self):
        for case in ("missing", "small", "zero"):
            with self.subTest(case=case):
                args = self.arguments()
                if case == "missing":
                    args["selected_particle_ids"].append(701)
                elif case == "small":
                    args["selected_particle_ids"] = [41, 9]
                else:
                    for row in args["observations"]:
                        row["instrument_time_us"] = 11.
                result = trajectory.analyze_trajectory(**args)
                self.assertEqual(result["status"], "insufficient_observations")
                self.assertIsNone(result["peak_metrics"])
                self.assertEqual(result["census"]["mother_count"], 5)
                if case == "missing":
                    self.assertEqual(result["missing_observation_particle_ids"], [701])
                    self.assertEqual(result["selected_population"]["denominator_weight_sum"], 14.)

    def test_nonuniform_weights_report_unsupported_without_losing_census(self):
        args = self.arguments()
        args["relative_weights"][9] = 4.
        result = trajectory.analyze_trajectory(**args)
        self.assertEqual(result["status"], "unsupported_weight_policy")
        self.assertEqual(result["census"]["mother_weight_sum"], 16.)
        self.assertIsNone(result["peak_metrics"])

    def test_invalid_source_selection_clock_and_time_fail_instead_of_filtering(self):
        for case in ("unknown_id", "duplicate", "nan", "clock", "reference", "bad_time", "partial_mother"):
            with self.subTest(case=case):
                args = self.arguments()
                if case == "unknown_id": args["observations"][0]["particle_id"] = 999
                elif case == "duplicate": args["observations"].append(dict(args["observations"][0]))
                elif case == "nan": args["observations"][0]["instrument_time_us"] = float("nan")
                elif case == "clock": args["clock"] = None
                elif case == "reference": args["time_reference_instrument_us"] = None
                elif case == "bad_time": args["time_reference_instrument_us"] = 11.
                else: args["classifications"].pop()
                with self.assertRaises(ValueError): trajectory.analyze_trajectory(**args)

    def test_zero_execution_observations_keep_full_mother_not_fake_peak(self):
        args = self.arguments()
        args["observations"] = []
        args["selected_particle_ids"] = []
        result = trajectory.analyze_trajectory(**args)
        self.assertEqual(result["status"], "insufficient_observations")
        self.assertEqual(result["census"]["mother_weight_sum"], 14.)
        self.assertEqual(result["observed_population"]["denominator_count"], 5)
        self.assertEqual(result["observed_population"]["numerator_count"], 0)
        self.assertIsNone(result["peak_metrics"])

    def test_module_has_only_scientific_dependencies_and_no_file_or_process_loader(self):
        source = Path(trajectory.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name and name.startswith(("msplatform.backends", "msplatform.execution", "msplatform.io",
                                                       "common", "projects", "integrations")) for name in imports))
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                             node.func.id in {"open", "eval", "exec"} for node in ast.walk(tree)))
