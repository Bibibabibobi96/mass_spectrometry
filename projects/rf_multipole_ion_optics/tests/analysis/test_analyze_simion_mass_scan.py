from __future__ import annotations

import unittest
import csv
import json
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

from common.analysis.peak_metrics import half_height_width
from projects.rf_multipole_ion_optics.core import mass_response

from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    evaluate_simion as MODULE,
)


PROJECT_ROOT = Path(__file__).parents[2]


def sampled_response(values: list[float], masses: list[float] | None = None) -> list[dict]:
    return [
        {"mass_Th": mass, "particles": 100, "transmitted": round(value * 100) if math.isfinite(value) else 0,
         "transmission_fraction": value}
        for mass, value in zip(masses or [100.0 + index for index in range(len(values))], values)
    ]


class SampledResponseAnalysisTests(unittest.TestCase):
    def test_triangle_uses_common_interpolation_and_retains_sample_envelope(self) -> None:
        with patch.object(mass_response, "half_height_width", wraps=half_height_width) as common_width:
            result = mass_response.prepare_response_analysis(sampled_response([0, 1, 0], [100, 101, 104]))
        common_width.assert_called_once()
        self.assertEqual(result["method_id"], "sampled_mass_response_linear_half_height_v1")
        self.assertEqual(result["status"], "computed")
        self.assertEqual(result["observed_half_maximum_band_Th"], [101, 101])
        self.assertEqual(result["half_height_crossings_Th"], [100.5, 102.5])
        self.assertEqual(result["interpolated_main_peak_fwhm_Th"], 2)
        self.assertEqual(result["mass_axis"]["unit"], "Th")
        self.assertFalse(result["resolution_claim_allowed"])

    def test_plateau_and_multiple_peaks_use_nearest_crossings_of_first_global_peak(self) -> None:
        for values, peak, width, band in (
            ([0, 1, 1, 1, 0], 101, 3, [101, 103]),
            ([0, 1, 0, 0, 1, 0, 0], 101, 1, [101, 104]),
            ([0, 0.6, 0, 0, 1, 0, 0], 104, 1, [101, 104]),
        ):
            with self.subTest(values=values):
                result = mass_response.prepare_response_analysis(sampled_response(values))
                self.assertEqual(result["peak_mass_Th"], peak)
                self.assertEqual(result["interpolated_main_peak_fwhm_Th"], width)
                self.assertEqual(result["observed_half_maximum_band_Th"], band)

    def test_truncated_and_zero_responses_do_not_invent_a_width(self) -> None:
        for values, missing in (([1, 0.8, 0], ["left"]), ([0, 0.8, 1], ["right"]),
                                ([0.8, 1, 0.8], ["left", "right"])):
            with self.subTest(values=values):
                result = mass_response.prepare_response_analysis(sampled_response(values))
                self.assertEqual(result["status"], "unavailable_missing_half_height_crossings")
                self.assertEqual(result["missing_half_height_crossings"], missing)
                self.assertIsNone(result["interpolated_main_peak_fwhm_Th"])
                self.assertIsNone(result["half_height_crossings_Th"])
        zero = mass_response.prepare_response_analysis(sampled_response([0, 0, 0]))
        self.assertEqual(zero["status"], "unavailable_no_positive_response")
        self.assertIsNone(zero["peak_mass_Th"])
        self.assertIsNone(zero["observed_half_maximum_band_Th"])
        self.assertIsNone(zero["interpolated_main_peak_fwhm_Th"])

    def test_invalid_response_domain_is_rejected(self) -> None:
        cases = [sampled_response(values) for values in ([], [0, 1], [0, -0.1, 0],
                                                        [0, 1.1, 0], [0, float("nan"), 0],
                                                        [0, float("inf"), 0])]
        cases.extend(sampled_response([0, 1, 0], masses) for masses in (
            [100, 100, 102], [100, 102, 101], [100, float("nan"), 102], [100, 101, float("inf")],
        ))
        for response in cases:
            with self.subTest(response=response), self.assertRaises(ValueError):
                mass_response.prepare_response_analysis(response)


class AnalyzeSimionMassScanTests(unittest.TestCase):
    def test_functional_response_passes_center_and_endpoint_contrast(self) -> None:
        response = [
            {"mass_Th": 96.0, "particles": 25, "transmitted": 0, "transmission_fraction": 0.0},
            {"mass_Th": 101.5, "particles": 25, "transmitted": 25, "transmission_fraction": 1.0},
            {"mass_Th": 106.0, "particles": 25, "transmitted": 1, "transmission_fraction": 0.04},
        ]
        baseline = MODULE.json.loads((PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json").read_text(encoding="utf-8"))
        mode = MODULE.json.loads(
            (PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json").read_text(encoding="utf-8")
        )
        metrics = MODULE.evaluate(response, baseline, mode)
        self.assertEqual(metrics["status"], "PASS")
        self.assertAlmostEqual(metrics["center_to_endpoint_contrast"], 0.96)
        self.assertEqual(metrics["sampled_response_analysis"]["status"], "computed")

    def test_actual_simion_analyzer_shares_prepared_result_with_json_and_plot(self) -> None:
        baseline = PROJECT_ROOT / "variants/quadrupole/config/baseline.json"
        mode_path = PROJECT_ROOT / "config/modes/quadrupole_mass_filter_reference.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            particles, states = root / "scan.ion", root / "states.csv"
            ion_rows, terminal_rows = [], []
            for mass, hits in zip(mode["mass_scan_spec"]["paired_source_masses_Th"], [0, 1, 5, 5, 4, 1, 0]):
                for index in range(5):
                    ion_rows.append([0, mass, 1, 0, 0, 0, 0, 0, 1, 1, 1])
                    terminal_rows.append([len(ion_rows), "terminal", "transmitted" if index < hits else "lost"])
            with particles.open("w", newline="") as stream:
                csv.writer(stream).writerows(ion_rows)
            with states.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["particle_id", "event", "status"])
                writer.writerows(terminal_rows)
            with patch.object(MODULE, "export_response_figure", wraps=MODULE.export_response_figure) as plot:
                metrics = MODULE.analyze(states, particles, baseline, mode_path, root / "response.csv",
                                         root / "metrics.json", root / "response.png")
            self.assertEqual(metrics["status"], "PASS")
            self.assertIs(plot.call_args.args[4], metrics["sampled_response_analysis"])
            self.assertEqual(json.loads((root / "metrics.json").read_text())["sampled_response_analysis"],
                             metrics["sampled_response_analysis"])
            self.assertTrue((root / "response.png").is_file())

    def test_particle_identity_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "particle IDs differ"):
            MODULE.aggregate_response({1: 100.0}, {2: "transmitted"})


if __name__ == "__main__":
    unittest.main()
