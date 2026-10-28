from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics import (
    analyze_simion_log,
    build_benchmark_metrics,
    calculate_pulse_timing,
    compare_field_reports,
    compare_particle_exports,
    mass_spectrum_max_tof_us,
    read_ion_table,
)


class SolverDiagnosticsTest(unittest.TestCase):
    def test_ion_charge_uses_exact_signed_integer_encodings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ion, log = root / "particles.ion", root / "empty.log"
            ion.write_text("".join(f"0,524,{charge},0,0,0,0,0,5,1,0\n"
                                   for charge in ("1", "1.0", "1e0", "-2", "-2.0", "-2e0")), encoding="ascii")
            log.write_text("", encoding="utf-8")
            source = read_ion_table(ion)
            self.assertEqual(source["ChargeState"].tolist(), [1, 1, 1, -2, -2, -2])
            self.assertEqual(str(source["ChargeState"].dtype), "int64")
            particles, summary = analyze_simion_log(log, ion, mode="test", distribution="fixed",
                                                    detector_radius_mm=40., allow_incomplete_census=True)
            self.assertEqual(particles["ChargeState"].tolist(), source["ChargeState"].tolist())
            self.assertEqual(summary["UnobservedParticleIds"], [1, 2, 3, 4, 5, 6])
            self.assertFalse(summary["ResolutionClaim"])

    def test_ion_charge_rejects_fractional_zero_boolean_and_nonfinite_source_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ion = Path(directory) / "particles.ion"
            for charge in ("1.5", "-1.5", "1.00000000000000001", "0", "nan", "inf", "True"):
                with self.subTest(charge=charge):
                    ion.write_text(f"0,524,{charge},0,0,0,0,0,5,1,0\n", encoding="ascii")
                    with self.assertRaisesRegex(ValueError, "charge_state.*integer"):
                        read_ion_table(ion)

    def test_proxy_cli_rejects_fractional_charge_before_particle_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ion, log, output = root / "particles.ion", root / "empty.log", root / "output.csv"
            ion.write_text("0,524,1.5,0,0,0,0,0,5,1,0\n", encoding="ascii")
            log.write_text("", encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-B", "-m", "projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics",
                "analyze-simion-log", "--log", str(log), "--ion-file", str(ion),
                "--mode", "test", "--distribution", "fixed", "--allow-incomplete-census", "--particle-csv", str(output),
            ], cwd=Path(__file__).resolve().parents[4], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("charge_state must be a finite nonzero integer", result.stderr)
            self.assertFalse(output.exists())

    def test_powershell_wrapper_resolves_relative_inputs_from_callers_directory(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        if not shutil.which("pwsh"):
            self.skipTest("PowerShell wrapper requires pwsh")
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
            freeze_candidate_source_closure, verify_candidate_source_closure,
        )
        source_id = "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "particles.ion").write_text("0,524,1,0,0,0,0,0,5,1,0\n", encoding="ascii")
            (root / "simion.log").write_text("", encoding="utf-8")
            code = root / "frozen code"
            closure = freeze_candidate_source_closure(code, root / "artifacts", Path(sys.executable))
            verify_candidate_source_closure(closure)
            frozen_source = (code / source_id).read_text(encoding="utf-8")
            self.assertNotIn("SIMULATION_PYTHON_EXE", frozen_source)
            self.assertNotIn("Join-Path $repoRoot '.venv", frozen_source)
            for label, wrapper, python_override in (
                ("live", repo / source_id, sys.executable),
                ("frozen", code / source_id, str(root / "unavailable-python.exe")),
            ):
                with self.subTest(label=label):
                    quoted_wrapper = str(wrapper).replace("'", "''")
                    command = (
                        f"& '{quoted_wrapper}' -Log simion.log -IonFile particles.ion "
                        f"-Mode test -Distribution fixed -ParticleCsv {label}.csv -AllowIncompleteCensus "
                        "| ConvertTo-Json -Depth 5"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-Command", command], cwd=root, check=True,
                        env={**os.environ, "SIMULATION_PYTHON_EXE": python_override},
                        capture_output=True, text=True, encoding="utf-8", timeout=60,
                    )
                    report = json.loads(result.stdout)
                    self.assertEqual(report["PeakStatus"], "no_hits")
                    self.assertEqual(report["UnobservedParticleIds"], [1])
                    self.assertEqual(pd.read_csv(root / f"{label}.csv")["ObservationStatus"].tolist(), ["not_observed"])

    def _analyze_events(
        self,
        events: list[tuple[int, float]],
        *,
        birth_us: float = 0.0,
        allow_incomplete: bool = True,
    ) -> tuple[pd.DataFrame, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ion, log = root / "particles.ion", root / "simion.log"
            ion.write_text(
                f"{birth_us},524,1,0,0,0,0,0,5,1,0\n" * 3,
                encoding="ascii",
            )
            log.write_text(
                "".join(
                    f"TRACE: detector_crossing ion={ion_id} t={time_us} "
                    "x=0 y=0 z=0 r=0 zmax=4\n"
                    for ion_id, time_us in events
                ),
                encoding="utf-8",
            )
            return analyze_simion_log(
                log, ion, mode="test", distribution="fixed",
                detector_radius_mm=1.0, allow_incomplete_census=allow_incomplete,
            )

    def test_no_crossings_preserves_unobserved_source_population(self) -> None:
        particles, summary = self._analyze_events([])
        self.assertEqual(particles["Ion"].tolist(), [1, 2, 3])
        self.assertEqual(particles["ObservationStatus"].tolist(), ["not_observed"] * 3)
        self.assertFalse(particles["Hit"].any())
        self.assertEqual(summary["UnobservedParticleIds"], [1, 2, 3])
        self.assertEqual(summary["CrossingParticleIds"], [])
        self.assertEqual(summary["PeakStatus"], "no_hits")
        self.assertEqual(summary["EfficiencyPct"], 0.0)
        self.assertIsNone(summary["GaussianProxyFwhmTofNs"])
        self.assertIsNone(summary["GaussianProxyTimeEquivalentResolution"])
        json.dumps(summary, allow_nan=False)

    def test_complete_census_still_rejects_no_crossings(self) -> None:
        with self.assertRaisesRegex(ValueError, "No detector_crossing"):
            self._analyze_events([], allow_incomplete=False)

    def test_allow_incomplete_does_not_allow_duplicate_particle_events(self) -> None:
        for allow_incomplete in (False, True):
            with self.subTest(allow_incomplete=allow_incomplete):
                with self.assertRaisesRegex(ValueError, "Duplicate.*ion 1"):
                    self._analyze_events([(1, 10.0)] * 4, allow_incomplete=allow_incomplete)

    def test_constant_and_single_hit_have_explicit_proxy_status(self) -> None:
        cases = [([(1, 10.0)], "insufficient_samples", None),
                 ([(1, 10.0), (2, 10.0), (3, 10.0)], "zero_variance", 0.0)]
        for events, status, width in cases:
            with self.subTest(status=status):
                _, summary = self._analyze_events(events)
                self.assertEqual(summary["PeakStatus"], status)
                self.assertEqual(summary["GaussianProxyFwhmTofNs"], width)
                self.assertIsNone(summary["GaussianProxyTimeEquivalentResolution"])
                json.dumps(summary, allow_nan=False)

    def test_gaussian_proxy_keeps_sample_sigma_and_birth_time_reference(self) -> None:
        events = [(3, 11.0), (1, 9.0), (2, 10.0)]
        _, summary = self._analyze_events(events, allow_incomplete=False)
        expected_width_us = 2.0 * math.sqrt(2.0 * math.log(2.0))
        self.assertAlmostEqual(summary["StdTofNs"], 1000.0)
        self.assertAlmostEqual(summary["GaussianProxyFwhmTofNs"], 1000.0 * expected_width_us)
        self.assertAlmostEqual(summary["GaussianProxyTimeEquivalentResolution"], 10.0 / (2 * expected_width_us))
        self.assertEqual(summary["HitParticleIds"], [1, 2, 3])
        self.assertEqual(summary["PeakStatus"], "computed")
        self.assertEqual(summary["TofTimeReference"], "particle_birth")
        self.assertFalse(summary["ResolutionClaim"])
        self.assertNotIn("FwhmTofNs", summary)
        self.assertNotIn("ResolutionFwhm", summary)
        _, shifted = self._analyze_events(
            [(ion_id, time_us + 100.0) for ion_id, time_us in events], birth_us=100.0
        )
        self.assertEqual(summary["MeanTofUs"], shifted["MeanTofUs"])
        self.assertEqual(summary["GaussianProxyFwhmTofNs"], shifted["GaussianProxyFwhmTofNs"])

    def test_proxy_metadata_declares_method_units_and_each_sample_population_in_all_states(self) -> None:
        cases = [([], "no_hits"), ([(1, 10.)], "insufficient_samples"),
                 ([(1, 10.), (2, 10.), (3, 10.)], "zero_variance"),
                 ([(1, 9.), (2, 10.), (3, 11.)], "computed")]
        for events, status in cases:
            with self.subTest(status=status):
                _, summary = self._analyze_events(events)
                metadata = summary["analysis_metadata"]
                self.assertEqual(metadata["method_id"], summary["DiagnosticMethod"])
                self.assertEqual(metadata["status"], status)
                self.assertEqual(metadata["sample_sigma_ddof"], 1)
                self.assertEqual(metadata["weight_policy"], "equal_particle_ids")
                self.assertEqual(metadata["sample_count"], len(events))
                self.assertEqual(metadata["weight_sum"], len(events))
                self.assertEqual(metadata["effective_sample_count"], len(events))
                self.assertEqual(metadata["time_reference"]["kind"], "particle_birth")
                self.assertEqual(metadata["time_reference"]["clock_qualification"], "birth_relative_only_no_pulse_epoch")
                self.assertEqual(metadata["units"]["time_width"], "ns")
                self.assertEqual(metadata["observation"]["event"], "detector_crossing")
                self.assertEqual(metadata["metric_scope"]["AllCrossingStdTofNs"], "recorded_crossings")
                self.assertEqual(metadata["cohorts"]["source"], {
                    "sample_count": 3, "weight_sum": 3., "effective_sample_count": 3.,
                })
                for key in ("sample_count", "weight_sum", "effective_sample_count"):
                    self.assertEqual(metadata["cohorts"]["recorded_crossings"][key], len(events))
                    self.assertEqual(metadata["cohorts"]["non_hits_including_unobserved_source_ids"][key], 3-len(events))
                self.assertFalse(metadata["resolution_claim_allowed"])
                self.assertEqual(metadata["scientific_qualification"], "not_assessed")
                json.dumps(summary, allow_nan=False)

    def test_empty_proxy_cli_serializes_complete_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ion, log = root / "particles.ion", root / "simion.log"
            ion.write_text("0,524,1,0,0,0,0,0,5,1,0\n", encoding="ascii")
            log.write_text("", encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-B", "-m", "projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics",
                "analyze-simion-log", "--log", str(log), "--ion-file", str(ion),
                "--mode", "test", "--distribution", "fixed", "--allow-incomplete-census",
            ], cwd=Path(__file__).resolve().parents[4], capture_output=True, text=True, timeout=60, check=True)
            metadata = json.loads(result.stdout)["analysis_metadata"]
            self.assertEqual(metadata["status"], "no_hits")
            self.assertEqual(metadata["weight_sum"], 0.)
            self.assertEqual(metadata["cohorts"]["source"]["sample_count"], 1)

    def test_crossing_rejects_unknown_identity_nonpositive_tof_and_nonfinite_time(self) -> None:
        for event, message in [((4, 10.0), "absent ion"), ((1, 0.0), "birth-relative"),
                               ((1, float("inf")), "Malformed detector")]:
            with self.subTest(event=event):
                with self.assertRaisesRegex(ValueError, message):
                    self._analyze_events([event])

    def test_log_analysis_preserves_census_and_detector_radius(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ion = root / "particles.ion"
            log = root / "simion.log"
            ion.write_text(
                "0,5.24E2,1,-4.88E1,0,0,0,0,5,1,0\n"
                "0,5.24E2,1,-4.88E1,0,0,0,0,5,1,0\n",
                encoding="ascii",
            )
            log.write_text(
                "TRACE: detector_crossing ion=1 t=10 x=1 y=2 z=3 r=2 zmax=4\n",
                encoding="utf-8",
            )

            particles, summary = analyze_simion_log(
                log,
                ion,
                mode="test",
                distribution="fixed",
                detector_radius_mm=1.0,
                allow_incomplete_census=True,
            )

            self.assertEqual(len(particles), 2)
            self.assertEqual(summary["Crossed"], 1)
            self.assertEqual(summary["Hit"], 0)
            self.assertEqual(summary["analysis_metadata"]["cohorts"]["recorded_crossings"]["sample_count"], 1)
            self.assertEqual(summary["analysis_metadata"]["sample_count"], 0)
            self.assertEqual(summary["analysis_metadata"]["cohorts"]["non_hits_including_unobserved_source_ids"]["sample_count"], 2)

    def test_particle_comparison_pairs_by_id_not_row_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.csv"
            candidate = root / "candidate.csv"
            pd.DataFrame(
                {"Ion": [1, 2], "TofUs": [10, 20], "XMm": [0, 1], "YMm": [0, 0]}
            ).to_csv(reference, index=False)
            pd.DataFrame(
                {"Ion": [2, 1], "TofUs": [20, 10], "XMm": [1, 0], "YMm": [0, 0]}
            ).to_csv(candidate, index=False)

            report = compare_particle_exports(
                reference,
                candidate,
                max_tof_difference_us=0.0,
                max_landing_difference_mm=0.0,
            )

            self.assertEqual(report["status"], "PASS")

    def test_particle_comparison_rejects_incomplete_id_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.csv"
            candidate = root / "candidate.csv"
            pd.DataFrame(
                {"Ion": [1, 2], "TofUs": [10, 20], "XMm": [0, 1], "YMm": [0, 0]}
            ).to_csv(reference, index=False)
            pd.DataFrame(
                {"Ion": [1], "TofUs": [10], "XMm": [0], "YMm": [0]}
            ).to_csv(candidate, index=False)

            with self.assertRaisesRegex(ValueError, "coverage differs"):
                compare_particle_exports(
                    reference,
                    candidate,
                    max_tof_difference_us=1,
                    max_landing_difference_mm=1,
                )

    def test_pulse_timing_uses_three_dimensional_handoff_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.csv"
            pd.DataFrame(
                {
                    "instrument_time_us": [1.0, 3.0],
                    "velocity_x_m_s": [2000.0, 2000.0],
                }
            ).to_csv(path, index=False)

            timing = calculate_pulse_timing(
                path, source_center_x_mm=5.0, target_origin_x_mm=1.0
            )

            self.assertEqual(timing["pulse_time_us"], 4.0)

    def test_benchmark_fit_is_computed_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.csv"
            pd.DataFrame(
                {
                    "solver": ["COMSOL", "COMSOL", "SIMION", "SIMION"],
                    "particle_count": [100, 1000, 100, 1000],
                    "wall_seconds": [20, 110, 2, 11],
                    "particle_seconds": [10, 100, float("nan"), float("nan")],
                }
            ).to_csv(path, index=False)

            metrics = build_benchmark_metrics(
                path,
                run_id="run",
                mass_amu=500,
                charge_state=1,
                simion_repeats=1,
            )

            self.assertAlmostEqual(
                metrics["comsol_wall_fit"]["slope_seconds_per_particle"], 0.1
            )

    def test_mass_spectrum_time_scales_with_heaviest_species(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mode.json"
            path.write_text(
                '{"species":[{"mass_amu":100},{"mass_amu":400}]}',
                encoding="utf-8",
            )

            value = mass_spectrum_max_tof_us(path, 100)

            self.assertEqual(value, 180.0)

    def test_field_reports_require_complete_sample_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left.txt"
            right = root / "right.txt"
            left.write_text(
                "FIELD_A_PA_LOCAL_E_V_PER_MM=1,0,0\n"
                "FIELD_B_PA_LOCAL_E_V_PER_MM=0,0,0\n",
                encoding="utf-8",
            )
            right.write_text(
                "FIELD_A_PA_LOCAL_E_V_PER_MM=1,0,0\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "coverage differs"):
                compare_field_reports(left, right)


if __name__ == "__main__":
    unittest.main()
