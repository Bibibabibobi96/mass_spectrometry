from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from projects.oa_tof.analysis.solver_diagnostics import (
    analyze_simion_log,
    build_benchmark_metrics,
    calculate_pulse_timing,
    compare_field_reports,
    compare_particle_exports,
    mass_spectrum_max_tof_us,
)


class SolverDiagnosticsTest(unittest.TestCase):
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
