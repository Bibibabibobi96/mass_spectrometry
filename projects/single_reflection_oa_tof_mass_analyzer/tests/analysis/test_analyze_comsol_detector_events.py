from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events import (
    analyze_request,
)


class AnalyzeComsolDetectorEventsTest(unittest.TestCase):
    def test_comsol_core_exports_raw_events_without_peak_math(self) -> None:
        root = Path(__file__).resolve().parents[2]
        core = (root / "comsol" / "oatof_build_model_core.m").read_text(encoding="utf-8")
        self.assertIn("oatof_export_detector_events", core)
        for prohibited in ("polyfit(", "mass_fwhm_direct", "R_fwhm_sigma_proxy", "mass_bandwidth"):
            self.assertNotIn(prohibited, core)

    def test_python_owns_metrics_for_raw_comsol_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / "events.csv"
            events.write_text(
                "Ion,TofUs,XMm,YMm,Hit,Status,Event,DetectorRadiusMm,X0Mm,Y0Mm,Z0Mm\n"
                "1,71.0000,0,0,true,detector_hit,crossing,0,0,0,-1\n"
                "2,71.0001,0,0,true,detector_hit,crossing,0,0,0,0\n"
                "3,71.0002,0,0,true,detector_hit,crossing,0,0,0,1\n",
                encoding="utf-8",
            )
            request = root / "request.json"
            output = root / "analysis"
            request.write_text(json.dumps({
                "schema_version": 1,
                "role": "oatof_comsol_detector_events_analysis_request",
                "solver": "COMSOL",
                "label": "fixture",
                "nominal_mass_Da": 524.0,
                "raw_events_csv": str(events),
                "analysis_output_dir": str(output),
                "event_extraction": "solver_native_detector_crossing_or_freeze",
                "aggregate_metrics_owner": "python_reference_analysis",
            }), encoding="utf-8")

            receipt = analyze_request(request)

            self.assertEqual(receipt["status"], "PASS")
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["metrics"]["particles"], 3)
            self.assertTrue((output / "analysis_receipt.json").is_file())

    def test_rejects_non_python_metric_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "schema_version": 1,
                "role": "oatof_comsol_detector_events_analysis_request",
                "solver": "COMSOL",
                "label": "fixture",
                "nominal_mass_Da": 524.0,
                "raw_events_csv": str(root / "events.csv"),
                "analysis_output_dir": str(root / "analysis"),
                "event_extraction": "solver_native_detector_crossing_or_freeze",
                "aggregate_metrics_owner": "matlab",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "delegate metrics to Python"):
                analyze_request(request)
