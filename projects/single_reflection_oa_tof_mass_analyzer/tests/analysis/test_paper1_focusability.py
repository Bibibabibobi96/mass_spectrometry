from __future__ import annotations

import unittest
import csv
import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_c1_source import (
    _verify_time_series_receipt,
    analyze_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_c1_stage import (
    assess_c1_stage,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_focusability import (
    FocusabilityProblem,
    assess_source_condition,
    assign_detector_blind_cohorts,
    choose_detector_blind_model,
    evaluate_focusability,
    fit_source_condition_model,
    load_frozen_pre_pulse_source,
    stack_focusability_problems,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c2_axial_oracle import (
    AxialC2Design,
    load_c2_axial_source,
    run_axial_c2_screen,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_c2_stage import (
    _target_gates,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
)


class Paper1FocusabilityTest(unittest.TestCase):
    def test_j3_revised_gate_does_not_smuggle_in_failed_j2_comparison(self) -> None:
        base = {
            "independent_g_derivative_le_1_percent": True,
            "G_step_platform_le_1_percent": True,
            "direction_spearman_ge_0p7": True,
            "direction_bootstrap_lower_gt_zero": True,
            "two_zone_is_zero_control_reference": True,
        }
        self.assertTrue(all(_target_gates(
            target="j3_local_direction", base_gates=base,
            weighted_beats_unweighted=False,
        ).values()))
        self.assertFalse(all(_target_gates(
            target="j2_j3", base_gates=base,
            weighted_beats_unweighted=False,
        ).values()))

    def test_assignment_is_deterministic_and_exhaustive(self) -> None:
        first = assign_detector_blind_cohorts(range(1, 101), salt="paper1-v1")
        second = assign_detector_blind_cohorts(range(1, 101), salt="paper1-v1")
        self.assertEqual(first, second)
        self.assertEqual({item.role for item in first}, {"development", "validation", "optimization", "locked_test"})

    def test_affine_model_beats_quadratic_overfit_on_affine_validation(self) -> None:
        condition = np.arange(30, dtype=float).reshape(-1, 1)
        state = np.column_stack((2.0 + 3.0 * condition[:, 0], -condition[:, 0]))
        affine = fit_source_condition_model(condition[:20], state[:20], condition_names=("z_mm",), state_names=("vz_m_per_s", "x_mm"), degree=1)
        quadratic = fit_source_condition_model(condition[:20], state[:20], condition_names=("z_mm",), state_names=("vz_m_per_s", "x_mm"), degree=2)
        selected = choose_detector_blind_model(condition[20:], state[20:], (affine, quadratic))
        self.assertEqual(selected.degree, 1)
        self.assertLess(selected.tail_fraction, 0.1)

    def test_tail_fraction_is_not_fixed_by_a_sample_quantile(self) -> None:
        condition = np.arange(40, dtype=float).reshape(-1, 1)
        state = np.column_stack((condition[:, 0], condition[:, 0]))
        state[-1, 1] += 100.0
        model = fit_source_condition_model(
            condition, state, condition_names=("z_mm",),
            state_names=("x_mm", "vx_m_per_s"), degree=1,
        )
        self.assertNotAlmostEqual(model.tail_fraction, 0.05, places=3)

    def test_source_assessment_is_detector_blind_and_reports_c1_diagnostics(self) -> None:
        generator = np.random.default_rng(7)
        condition = np.linspace(-2.0, 2.0, 48).reshape(-1, 1)
        state = np.column_stack((
            0.4 * condition[:, 0] + generator.normal(0.0, 0.02, 48),
            4.0 * condition[:, 0] + generator.normal(0.0, 0.2, 48),
            generator.normal(0.0, 0.1, 48),
            generator.normal(0.0, 2.0, 48),
        ))
        assessment = assess_source_condition(
            development_condition=condition[:32], development_state=state[:32],
            validation_condition=condition[32:], validation_state=state[32:],
            condition_names=("z_mm",),
            state_names=("x_mm", "vx_m_per_s", "y_mm", "vy_m_per_s"),
            pulse_eligible_fraction=0.8, covariance_bin_count=4,
            bootstrap_replicates=20, bootstrap_seed=11,
        )
        self.assertEqual(len(assessment.covariance_bins), 4)
        self.assertEqual(assessment.residual_mode_variance.shape, (4,))
        self.assertGreaterEqual(float(np.min(assessment.residual_mode_bootstrap_alignment)), 0.0)
        self.assertAlmostEqual(assessment.selected_model.pulse_eligible_fraction, 0.8)
        self.assertIsNotNone(assessment.selected_model.transverse_emittance_x_mm_m_per_s)

    def test_projector_respects_constraint_and_bound(self) -> None:
        result = evaluate_focusability(FocusabilityProblem(
            time_gradient=np.array([2.0, 1.0]),
            design_response=np.array([[1.0, 0.0], [0.0, 1.0]]),
            source_factor=np.eye(2),
            constraint_jacobian=np.array([[1.0, 0.0]]),
            parameter_scale=np.ones(2),
            lower_eta=np.array([-0.5]),
            upper_eta=np.array([0.5]),
            trust_radius=0.5,
        ))
        self.assertAlmostEqual(result.constraint_residual_norm, 0.0)
        self.assertLess(result.predicted_conditional_variance, result.initial_conditional_variance)
        self.assertIn("lower", result.active_constraints)

    def test_stacked_bins_preserve_shared_constraints_and_weights(self) -> None:
        bins = tuple(
            FocusabilityProblem(
                time_gradient=np.array([gradient]),
                design_response=np.array([[1.0, 1.0]]),
                source_factor=np.array([[factor]]),
                constraint_jacobian=np.array([[1.0, 0.0]]),
                parameter_scale=np.ones(2),
                rank_relative_tolerance=1e-10,
            )
            for gradient, factor in ((2.0, 1.0), (4.0, 2.0))
        )
        stacked = stack_focusability_problems(bins)
        result = evaluate_focusability(stacked)
        self.assertEqual(result.effective_rank, 1)
        self.assertAlmostEqual(result.constraint_residual_norm, 0.0)
        self.assertLess(result.predicted_conditional_variance, result.initial_conditional_variance)

    def test_fully_constrained_problem_reports_zero_control_not_failure(self) -> None:
        result = evaluate_focusability(FocusabilityProblem(
            time_gradient=np.array([1.0]), design_response=np.array([[1.0, 2.0]]),
            source_factor=np.eye(1), constraint_jacobian=np.eye(2),
            parameter_scale=np.ones(2), rank_relative_tolerance=1e-10,
        ))
        self.assertEqual(result.eta.size, 0)
        self.assertEqual(result.null_space.shape, (2, 0))
        self.assertAlmostEqual(
            result.predicted_conditional_variance,
            result.initial_conditional_variance,
        )

    def test_rejects_duplicate_particle_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            assign_detector_blind_cohorts((1, 1), salt="paper1-v1")

    def test_pre_pulse_loader_requires_common_checkpoint_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            fields = ["particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s", "pulse_eligibility"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for identifier in (1, 2, 3):
                    writer.writerow({"particle_id": identifier, "event": "pre_pulse_state", "instrument_time_us": 1.0, "x_mm": identifier, "y_mm": 0.0, "z_mm": identifier, "vx_m_per_s": 0.0, "vy_m_per_s": 0.0, "vz_m_per_s": 2.0, "pulse_eligibility": "eligible"})
            source = load_frozen_pre_pulse_source(path)
            self.assertEqual(source.state.shape, (3, 6))
            self.assertTrue(source.pulse_eligibility.all())
            with path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writerow({"particle_id": 4, "event": "rod_exit", "instrument_time_us": 1.0, "x_mm": 4.0, "y_mm": 0.0, "z_mm": 4.0, "vx_m_per_s": 0.0, "vy_m_per_s": 0.0, "vz_m_per_s": 2.0, "pulse_eligibility": "eligible"})
            with self.assertRaisesRegex(ValueError, "OA pre-pulse"):
                load_frozen_pre_pulse_source(path)

    def test_pre_pulse_loader_requires_selected_time_series_checkpoint_and_converts_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "time_series.csv"
            fields = ["particle_id", "event", "sample_index", "instrument_time_us", "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "survival_status"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for identifier in (1, 2, 3):
                    writer.writerow({"particle_id": identifier, "event": "pre_pulse_time_series_state", "sample_index": 1, "instrument_time_us": 1.0, "x_mm": 0.0, "y_mm": 0.0, "z_mm": identifier, "vx_mm_per_us": 1.25, "vy_mm_per_us": 0.0, "vz_mm_per_us": 2.5, "survival_status": "alive"})
            with self.assertRaisesRegex(ValueError, "requires one positive sample"):
                load_frozen_pre_pulse_source(path)
            source = load_frozen_pre_pulse_source(path, time_series_sample_index=1)
            self.assertTrue(source.pulse_eligibility.all())
            self.assertTrue(np.allclose(source.state[:, 3], 1250.0))
            self.assertTrue(np.allclose(source.state[:, 5], 2500.0))

    def test_c1_source_analysis_is_detector_blind_and_registers_all_cohorts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            fields = ["particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s", "pulse_eligibility"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for identifier in range(1, 161):
                    writer.writerow({"particle_id": identifier, "event": "pre_pulse_state", "instrument_time_us": 1.0, "x_mm": identifier / 100.0, "y_mm": 0.0, "z_mm": identifier / 80.0, "vx_m_per_s": identifier * 2.0, "vy_m_per_s": identifier / 10.0, "vz_m_per_s": 500.0 + identifier, "pulse_eligibility": "eligible"})
            result = analyze_source(
                state_path=path, source_id="test", cohort_salt="c1-test",
                time_series_sample_index=None, mother_particle_count=160,
                source_receipt=None, time_series_population_count=None,
                bootstrap_replicates=10, bootstrap_seed=7,
            )
            self.assertEqual(result["qualification"], "DETECTOR_BLIND_SOURCE_ONLY")
            self.assertEqual(sum(result["cohort"]["counts"].values()), 160)
            self.assertEqual(result["cohort"]["model_selection_roles"], ["development", "validation"])
            self.assertIn("locked-test model selection", result["claims_prohibited"])

    def test_c1_receipt_keeps_terminal_handoff_and_mother_denominators_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = root / "states.csv"
            receipt = root / "receipt.json"
            states.write_text("particle_id\n1\n", encoding="utf-8")
            receipt.write_text(json.dumps({
                "role": "rf_oatof_pre_pulse_time_series_screening_receipt",
                "status": "success", "pulse_disabled": True,
                "particle_count": 914,
                "outputs": {"states": {"sha256": hashlib.sha256(states.read_bytes()).hexdigest().upper()}},
                "sample_census": [{"sample_index": 1, "alive_count": 828, "missing_count": 86}],
            }), encoding="utf-8")
            verified = _verify_time_series_receipt(
                receipt, states, sample_index=1, mother_count=1000,
                screened_count=914,
            )
            self.assertEqual(verified["anchor_census"]["alive_count"], 828)
            with self.assertRaisesRegex(ValueError, "screened-population"):
                _verify_time_series_receipt(
                    receipt, states, sample_index=1, mother_count=1000,
                    screened_count=1000,
                )

    def test_c1_stage_requires_two_distinct_detector_blind_source_assessments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def assessment(source_id: str) -> dict[str, object]:
                return {
                    "role": "oatof_paper1_c1_source_assessment",
                    "qualification": "DETECTOR_BLIND_SOURCE_ONLY",
                    "source_id": source_id,
                    "anchor": {"instrument_time_us": 1.0},
                    "mother_cohort": {"count": 1000, "observed_pre_pulse_count": 800},
                    "cohort": {"salt": "fixed", "counts": {"development": 400, "validation": 200, "optimization": 200, "locked_test": 200}, "model_selection_roles": ["development", "validation"], "prohibited_from_model_selection": ["optimization", "locked_test"]},
                    "selected_model": {"degree": 1}, "covariance_bins": [],
                    "residual_modes": {"bootstrap_alignment_lower_95": [0.9]},
                }
            first, second = root / "first.json", root / "second.json"
            first.write_text(json.dumps(assessment("S1")), encoding="utf-8")
            second.write_text(json.dumps(assessment("S2")), encoding="utf-8")
            result = assess_c1_stage(first_path=first, second_path=second)
            self.assertEqual(result["conclusion"], "PASS_CONTINUE")
            second.write_text(json.dumps(assessment("S1")), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "distinct"):
                assess_c1_stage(first_path=first, second_path=second)

    def test_c2_axial_screen_uses_only_source_state_and_locked_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, assessment_path = root / "states.csv", root / "assessment.json"
            fields = ["particle_id", "event", "sample_index", "instrument_time_us", "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "kinetic_energy_eV", "survival_status"]
            with state_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for identifier in range(1, 241):
                    z = -61.0 + (identifier - 120) / 200.0
                    writer.writerow({"particle_id": identifier, "event": "pre_pulse_time_series_state", "sample_index": 1, "instrument_time_us": 1.0, "x_mm": 0.0, "y_mm": 0.0, "z_mm": z, "vx_mm_per_us": 4.0, "vy_mm_per_us": 0.0, "vz_mm_per_us": 0.01 + 0.0001 * z + (identifier % 5) * 1e-5, "kinetic_energy_eV": 10.0, "survival_status": "alive"})
            assessment_path.write_text(json.dumps({"qualification": "DETECTOR_BLIND_SOURCE_ONLY", "source_id": "synthetic", "anchor": {"time_series_sample_index": 1}, "state_table": {"path": str(state_path)}, "selected_model": {"degree": 1}, "cohort": {"salt": "c2-test"}}), encoding="utf-8")
            source = load_c2_axial_source(assessment_path=assessment_path, mass_to_charge_th=100.0, release_position_mm=1.498375640839315)
            design_source = AffineSource.from_velocity(mass_to_charge_th=100.0, center_x_mm=1.498375640839315, center_velocity_m_per_s=-2.9, velocity_slope_m_per_s_per_mm=228.0)
            design = AxialC2Design(design_source, OuterGeometry(3.25, 17.0, 0.3, 250.0, 2000.0), ReflectronGeometry(120.0, 96.1563, 600.0, 600.0), InnerSolution(1701.7426470171715, 9.880402594968652, -1.0391326394747527), True, np.array([50.0, 1.0, 0.2]))
            result = run_axial_c2_screen(source, design)
            self.assertEqual(result["architecture"], "three_zone")
            self.assertGreater(result["locked_test_count"], 0)
            self.assertEqual(result["weighted"]["prediction"]["effective_rank"], 1)
            self.assertEqual(set(result["directions"]), {"improve", "zero", "worsen"})
            self.assertLess(
                max(item["gradient_relative_error"] for item in result["derivative_audits"]),
                1e-4,
            )


if __name__ == "__main__":
    unittest.main()
