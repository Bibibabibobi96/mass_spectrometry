from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events import (
    analyze_request,
)


class AnalyzeComsolDetectorEventsTest(unittest.TestCase):
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

            original_events = events.read_bytes()
            original_request = request.read_bytes()
            completed = subprocess.run(
                [sys.executable, "-m",
                 "projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events",
                 "--request", str(request)], cwd=Path(__file__).resolve().parents[4],
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            receipt = json.loads((output / "analysis_receipt.json").read_text(encoding="utf-8"))

            self.assertEqual(receipt["status"], "PASS")
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["metrics"]["particles"], 3)
            self.assertEqual(receipt["schema_version"], 2)
            self.assertEqual(receipt["result_schema_version"], 4)
            self.assertEqual(metrics["schema_version"], 4)
            self.assertEqual(metrics["analysis_contract_schema_version"], 3)
            values = metrics["metrics"]
            self.assertNotIn("mass_resolution", values)
            self.assertEqual(values["nominal_mass_resolution_fwhm"],
                             524.0 / values["direct_fwhm_mass_Da"])
            metadata = values["analysis_metadata"]
            self.assertEqual(metadata["schema_version"], 2)
            self.assertEqual(metadata["method_id"], "common_gaussian_kde_nominal_mass_v1")
            self.assertFalse(metadata["mass_axis"]["absolute_calibration"])
            self.assertEqual(metadata["time_reference"]["clock_qualification"], "unspecified")
            for key, path in (("request", request), ("raw_events", events),
                              ("metrics", output / "metrics.json")):
                self.assertEqual(receipt[key]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest().upper())
            self.assertEqual(events.read_bytes(), original_events)
            self.assertEqual(request.read_bytes(), original_request)
            self.assertEqual(len((output / "particles_normalized.csv").read_text().splitlines()), 4)
            self.assertGreater((output / "spectra.csv").stat().st_size, 0)
            self.assertTrue((output / "peak_overview.png").read_bytes().startswith(b"\x89PNG"))

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
