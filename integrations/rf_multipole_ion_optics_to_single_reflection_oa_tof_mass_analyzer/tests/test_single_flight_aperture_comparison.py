from __future__ import annotations

import math
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_apertures import (
    _pair_event,
    analyze_multi_arm_runs,
    analyze_pre_pulse_source_only_apertures,
)


def _state(time_us: float, x_mm: float) -> dict[str, float]:
    return {
        "time_us": time_us,
        "x_mm": x_mm,
        "y_mm": 0.0,
        "z_mm": 0.0,
        "vx_mm_per_us": 1.0,
        "vy_mm_per_us": 0.0,
        "vz_mm_per_us": 0.0,
    }


def _pre_pulse_run(
    root: Path, name: str, *, shape: str, height_mm: float, selected_z_mm: list[float]
) -> Path:
    run = root / name
    (run / "inputs").mkdir(parents=True)
    (run / "results").mkdir()
    (run / "run_manifest.json").write_text(json.dumps({"status": "success", "run_id": name}), encoding="utf-8")
    (run / "summary.json").write_text(json.dumps({"status": "success", "role": "rf_oatof_simion_single_flight_summary"}), encoding="utf-8")
    (run / "run_config.json").write_text(json.dumps({"parameters": {
        "execution_mode": "real_pa_rf_pre_pulse_time_series",
        "source_release_full_width_mm": 4.0,
        "layout_profile_id": f"three_zone_ideal_acceptance_300mm_{shape}_kinematic_envelope_v1",
        "accelerator_entrance_local_aperture_mm": {"width": 1.0, "height": height_mm},
    }}), encoding="utf-8")
    (run / "inputs" / "resolved_connection.json").write_text(json.dumps({
        "spatial_registration": {"expected_gap_mm": 102.4}, "connector": {"length_mm": 102.4},
    }), encoding="utf-8")
    pd.DataFrame({"particle_id": range(1, 5001)}).to_csv(
        run / "inputs" / "single_flight_initial_global_state.csv", index=False
    )
    selected = pd.DataFrame({
        "particle_id": [1, 2, 3], "sample_index": [2, 2, 2],
        "z_mm": selected_z_mm, "vz_mm_per_us": [1 + .5 * z for z in selected_z_mm],
    })
    terminal = selected.assign(sample_index=3, z_mm=[20.0, 25.0, 30.0])
    pd.concat((selected, terminal), ignore_index=True).to_csv(
        run / "results" / "pre_pulse_time_series_states.csv", index=False
    )
    (run / "results" / "pre_pulse_time_series_screening_receipt.json").write_text(json.dumps({
        "terminal_census": {"window_complete": {"count": 3}, "splat": {"count": 4997}},
    }), encoding="utf-8")
    (run / "results" / "detector_blind_pulse_timing_candidate_receipt.json").write_text(json.dumps({
        "role": "rf_oatof_detector_blind_real_field_pulse_timing_selection_receipt",
        "status": "success", "qualification": "candidate_selection",
        "selection_uses_detector_outcome": False, "detector_results_used": False,
        "selected_time_us": 2.0,
        "candidates_ranked": [{"sample_index": 2, "candidate_time_us": 2.0}],
    }), encoding="utf-8")
    return run


def _pre_pulse_matrix(root: Path, *, selected_z_mm: list[float]) -> dict[str, Path]:
    return {
        f"{shape}_h{int(height * 100):03d}": _pre_pulse_run(
            root, f"{shape}_h{int(height * 100):03d}", shape=shape,
            height_mm=height, selected_z_mm=selected_z_mm,
        )
        for shape in ("square", "cylindrical")
        for height in (1.0, 1.5, 2.0, 2.5)
    }


class SingleFlightApertureComparisonTests(unittest.TestCase):
    def test_multi_arm_comparison_keeps_complete_detector_peaks_and_pairs_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, cases = Path(temporary), {}
            for index, name in enumerate(("square_0p9", "round_1p5", "round_2p5")):
                run = root / name; (run / "inputs").mkdir(parents=True); (run / "results").mkdir()
                (run / "run_manifest.json").write_text(json.dumps({"status": "success", "run_id": name}), encoding="utf-8")
                (run / "summary.json").write_text(json.dumps({"status": "success", "role": "rf_oatof_simion_single_flight_summary"}), encoding="utf-8")
                pd.DataFrame({"particle_id": [1, 2, 3, 4]}).to_csv(run / "inputs" / "single_flight_initial_global_state.csv", index=False)
                rows = []
                for particle_id in range(1, 5):
                    for event in ("source_release", "multipole_handoff", "pre_pulse_state", "local_accelerator_exit"):
                        rows.append({"particle_id": particle_id, "event": event, "instrument_time_us": particle_id, "x_mm": 0., "y_mm": 0., "z_mm": 0., "vx_mm_per_us": 1., "vy_mm_per_us": 0., "vz_mm_per_us": 0.})
                    if particle_id != 4 or index == 0:
                        rows.append({"particle_id": particle_id, "event": "detector_crossing", "instrument_time_us": particle_id + index * .001, "x_mm": 0., "y_mm": 0., "z_mm": 0., "vx_mm_per_us": 1., "vy_mm_per_us": 0., "vz_mm_per_us": 0.})
                pd.DataFrame(rows).to_csv(run / "results" / "single_flight_particle_checkpoints.csv", index=False); cases[name] = run
            result = analyze_multi_arm_runs(cases, baseline_case="square_0p9", bootstrap_samples=20)
            pd.DataFrame({"particle_id": [1, 2, 3, 5]}).to_csv(cases["round_2p5"] / "inputs" / "single_flight_initial_global_state.csv", index=False)
            with self.assertRaisesRegex(Exception, "identical mother particle IDs"):
                analyze_multi_arm_runs(cases, baseline_case="square_0p9", bootstrap_samples=2)
        arm = result["arms"]["round_1p5"]
        self.assertEqual(arm["mother_cohort_count"], 4)
        self.assertEqual(arm["all_detector_peak_metrics"]["particles"], 3)
        paired = result["comparisons"]["round_1p5"]["paired_common_detector_time_difference_ns"]
        self.assertEqual(paired["common_particle_count"], 3)
        self.assertIn("complete detector cohort", result["comparisons"]["round_1p5"]["all_detector_peak_delta"]["population_definition"])
    def test_pre_pulse_source_only_comparison_uses_full_mother_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cases = _pre_pulse_matrix(Path(temporary), selected_z_mm=[0.0, 1.0, 2.0])
            result = analyze_pre_pulse_source_only_apertures(cases)
        square = result["cases"]["square_h100"]
        self.assertEqual(square["mother_cohort_count"], 5000)
        self.assertEqual(square["accelerator_entry_count"], 3)
        self.assertEqual(square["transmission_fraction_of_mother"], 3 / 5000)
        self.assertEqual(square["accelerator_entry_axial_width_mm"]["full_width"], 2.)
        acceptance = square["accelerator_entry_axial_full_width_acceptance"]
        self.assertEqual(acceptance["threshold_full_width_mm"], 4.0)
        self.assertEqual(acceptance["observed_full_width_mm"], 2.0)
        self.assertTrue(acceptance["passed"])
        self.assertEqual(square["detector_blind_pulse_timing"]["selected_sample_index"], 2)
        self.assertEqual(square["detector_blind_pulse_timing"]["selected_time_us"], 2.0)
        self.assertEqual(square["matrix_arm"]["connector_gap_mm"], 102.4)
        self.assertAlmostEqual(square["z_vz_linear_fit"]["slope_vz_mm_per_us_per_mm"], .5)
        self.assertAlmostEqual(square["z_vz_linear_fit"]["k_per_us"], .5)
        self.assertAlmostEqual(square["z_vz_linear_fit"]["slope_per_us"], .5)
        diagnostics = square["z_vz_polynomial_diagnostics"]
        self.assertAlmostEqual(
            diagnostics["linear"]["residual_sample_sigma_mm_per_us"], 0.0, places=12
        )
        self.assertAlmostEqual(
            diagnostics["quadratic"]["residual_sample_sigma_mm_per_us"], 0.0, places=12
        )
        self.assertAlmostEqual(diagnostics["linear"]["k_per_us"], .5)
        self.assertEqual(
            diagnostics["quadratic"]["coefficient_units_descending_power"],
            ["mm_per_us_per_mm2", "mm_per_us_per_mm", "mm_per_us"],
        )
        self.assertIsNone(diagnostics["cubic"])
        self.assertIn("highest reported polynomial", diagnostics["random_residual_interpretation"])
        self.assertNotIn("fwhm", json.dumps(result).lower())
        self.assertNotIn("resolution", json.dumps(result).lower())

    def test_pre_pulse_source_only_comparison_rejects_empty_or_nonfinite_selected_state(self) -> None:
        for bad_state in (
            pd.DataFrame(columns=["particle_id", "sample_index", "z_mm", "vz_mm_per_us"]),
            pd.DataFrame({
                "particle_id": [1, 2], "sample_index": [2, 2],
                "z_mm": [0.0, math.nan], "vz_mm_per_us": [1.0, 2.0],
            }),
        ):
            with self.subTest(rows=len(bad_state)), tempfile.TemporaryDirectory() as temporary:
                cases = _pre_pulse_matrix(Path(temporary), selected_z_mm=[0.0, 1.0, 2.0])
                bad_state.to_csv(
                    cases["cylindrical_h250"] / "results" / "pre_pulse_time_series_states.csv", index=False
                )
                expected = "selected detector-blind sample is absent" if bad_state.empty else "needs two finite selected pre-pulse states"
                with self.assertRaisesRegex(Exception, expected):
                    analyze_pre_pulse_source_only_apertures(cases)

    def test_pre_pulse_source_only_comparison_rejects_absent_detector_blind_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cases = _pre_pulse_matrix(Path(temporary), selected_z_mm=[0.0, 1.0, 2.0])
            receipt_path = cases["square_h100"] / "results" / "detector_blind_pulse_timing_candidate_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["candidates_ranked"][0]["sample_index"] = 4
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "selected detector-blind sample is absent"):
                analyze_pre_pulse_source_only_apertures(cases)

    def test_pre_pulse_source_only_comparison_requires_complete_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cases = _pre_pulse_matrix(Path(temporary), selected_z_mm=[0.0, 1.0, 2.0])
            cases.pop("cylindrical_h250")
            with self.assertRaisesRegex(Exception, "complete eight-arm matrix"):
                analyze_pre_pulse_source_only_apertures(cases)

    def test_pair_event_preserves_common_and_unique_identities(self) -> None:
        metrics, rows = _pair_event(
            {1: _state(10.0, 1.0), 2: _state(20.0, 2.0)},
            {2: _state(20.002, 2.1), 3: _state(30.0, 3.0)},
        )
        self.assertEqual(metrics["common_particles"], 1)
        self.assertEqual(metrics["wide_only_particles"], 1)
        self.assertEqual(metrics["small_only_particles"], 1)
        self.assertAlmostEqual(metrics["jaccard_identity"], 1 / 3)
        self.assertEqual(rows[0]["particle_id"], 2)
        self.assertAlmostEqual(rows[0]["delta_time_small_minus_wide_ns"], 2.0)
        self.assertAlmostEqual(metrics["position_vector_rms_mm"], 0.1)

    def test_pair_event_supports_detector_rows_without_velocity(self) -> None:
        wide = _state(1.0, 0.0)
        small = _state(1.001, 0.0)
        for state in (wide, small):
            state["vx_mm_per_us"] = math.nan
            state["vy_mm_per_us"] = math.nan
            state["vz_mm_per_us"] = math.nan
        metrics, _ = _pair_event({7: wide}, {7: small})
        self.assertIsNone(metrics["velocity_vector_rms_m_s"])
        self.assertAlmostEqual(metrics["rms_delta_time_ns"], 1.0)


if __name__ == "__main__":
    unittest.main()
