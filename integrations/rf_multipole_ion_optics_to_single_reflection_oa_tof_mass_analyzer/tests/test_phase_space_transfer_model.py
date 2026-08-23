from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.phase_space_transfer_model import (
    ACCEPTANCE_FEATURE_NAMES,
    AcceptanceCoverageError,
    TransferModelContractError,
    build_campaign_theoretical_acceptance_window_profile,
    campaign_fixed_id_split,
    campaign_transfer_settings,
    evaluate_pulse_eligible_coverage,
    evaluate_campaign_pulse_eligible_coverage,
    fit_second_order_transfer_model,
    fixed_id_train_validation_split,
    freeze_theoretical_acceptance_window,
    freeze_campaign_theoretical_acceptance_window,
    generate_constrained_voltage_candidates,
    load_theoretical_acceptance_window_profile,
    phase_space_to_acceptance_coordinates,
    quadratic_design_matrix,
    quadratic_feature_names,
)


CAMPAIGN = Path(__file__).resolve().parents[1] / "docs" / "history" / "retired_campaigns" / "root_campaigns" / "pulse_resolution_direct_baseline_successor_r09_campaign.json"
CANDIDATE_CAMPAIGN = (
    Path(__file__).resolve().parents[1] / "docs" / "history" / "retired_campaigns" / "root_campaigns" / "pulse_resolution_direct_candidate_campaign.json"
)


class PhaseSpaceTransferModelTests(unittest.TestCase):
    def test_campaign_adapter_freezes_feature_order_budget_coverage_and_split(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        settings = campaign_transfer_settings(campaign)
        self.assertEqual(
            settings.campaign_feature_order,
            ("x", "y", "z", "angle_x", "angle_y"),
        )
        self.assertEqual(settings.final_time_budget_ns, 0.537)
        self.assertEqual(settings.minimum_pulse_eligible_coverage, 0.70)
        self.assertEqual(
            settings.execution_state,
            "n100_baseline_registration_only",
        )
        first = campaign_fixed_id_split(campaign, np.arange(1, 1001))
        second = campaign_fixed_id_split(campaign, np.arange(1000, 0, -1))
        self.assertEqual(first.train_ids, second.train_ids)
        self.assertEqual(first.validation_ids, second.validation_ids)
        self.assertEqual(len(first.validation_ids), 100)

    def test_campaign_adapter_rejects_feature_reorder_and_execution_enablement(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        campaign["pulse_resolution_optimization"]["acceptance_window"]["allowed_coordinates"] = [
            "z",
            "x",
            "y",
            "angle_x",
            "angle_y",
        ]
        with self.assertRaisesRegex(TransferModelContractError, "feature order"):
            campaign_transfer_settings(campaign)
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        campaign["pulse_resolution_optimization"]["execution_state"] = "executable"
        with self.assertRaisesRegex(TransferModelContractError, "cannot make"):
            campaign_transfer_settings(campaign)

        pending_candidate = json.loads(CANDIDATE_CAMPAIGN.read_text(encoding="utf-8"))
        settings = campaign_transfer_settings(pending_candidate)
        self.assertEqual(settings.campaign_id, "pulse_resolution_direct_candidates_v5")
        self.assertEqual(settings.execution_state, "n100_full_domain_piecewise_ideal_field_screening")
        pending_candidate["pulse_resolution_optimization"]["execution_state"] = "executable"
        with self.assertRaisesRegex(TransferModelContractError, "cannot make"):
            campaign_transfer_settings(pending_candidate)

    def test_campaign_window_maps_angles_and_rejects_nonforward_particles(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        axes = [np.asarray([-1.0, 0.0, 1.0])] * 5
        acceptance_grid = np.asarray(np.meshgrid(*axes, indexing="ij")).reshape(5, -1).T
        vz = np.full(len(acceptance_grid), 1000.0)
        phase_grid = np.column_stack(
            [
                acceptance_grid[:, :3],
                vz * np.tan(acceptance_grid[:, 3] / 1000.0),
                vz * np.tan(acceptance_grid[:, 4] / 1000.0),
                vz,
            ]
        )
        mapped = phase_space_to_acceptance_coordinates(phase_grid)
        np.testing.assert_allclose(mapped, acceptance_grid, atol=1.0e-12)
        field_error = np.full(len(phase_grid), 0.1)
        window = freeze_campaign_theoretical_acceptance_window(
            campaign, phase_grid, field_error, np.zeros(5), np.ones(5)
        )
        coverage = evaluate_campaign_pulse_eligible_coverage(
            campaign, window, np.arange(1, len(phase_grid) + 1), phase_grid
        )
        self.assertEqual(coverage.coverage_fraction, 1.0)
        phase_grid[0, 5] = 0.0
        with self.assertRaisesRegex(TransferModelContractError, "positive global vz"):
            phase_space_to_acceptance_coordinates(phase_grid)

    def test_quadratic_map_contains_and_recovers_all_cross_terms(self) -> None:
        rng = np.random.default_rng(20260812)
        phase = rng.normal(size=(180, 6))
        design, names = quadratic_design_matrix(phase)
        self.assertEqual(design.shape[1], 28)
        self.assertEqual(names, quadratic_feature_names())
        self.assertIn("x_mm*vy_m_per_s", names)
        self.assertIn("z_mm*vz_m_per_s", names)
        self.assertIn("vz_m_per_s^2", names)
        focus = 2.0 + 0.7 * phase[:, 0] * phase[:, 4] - 0.2 * phase[:, 2] ** 2
        detector = 30.0 - 0.5 * phase[:, 2] * phase[:, 5] + 0.1 * phase[:, 1]
        radius = 1.0 + 0.4 * phase[:, 0] * phase[:, 1] + 0.3 * phase[:, 3] ** 2
        hit = radius < np.median(radius)
        fit = fit_second_order_transfer_model(
            np.arange(1, 181),
            phase,
            {
                "focus_time_ns": focus,
                "detector_time_ns": detector,
                "detector_radius_mm": radius,
            },
            hit,
            validation_fraction=0.25,
            ridge=0.0,
        )
        prediction = fit.model.predict(phase)
        np.testing.assert_allclose(prediction.focus_time_ns, focus, atol=1e-11)
        np.testing.assert_allclose(prediction.detector_time_ns, detector, atol=1e-11)
        np.testing.assert_allclose(prediction.detector_radius_mm, radius, atol=1e-11)
        self.assertEqual(
            set(fit.model.split.train_ids) | set(fit.model.split.validation_ids),
            set(range(1, 181)),
        )

    def test_loss_particles_remain_in_population_with_per_output_finite_labels(self) -> None:
        rng = np.random.default_rng(812)
        count = 240
        ids = np.arange(1, count + 1)
        phase = rng.normal(size=(count, 6))
        focus = 4.0 + 0.2 * phase[:, 0] * phase[:, 5]
        hit = phase[:, 0] + 0.3 * phase[:, 1] > 0.0
        detector = 32.0 - 0.4 * phase[:, 2] * phase[:, 5]
        radius = 1.0 + 0.1 * phase[:, 0] ** 2 + 0.2 * phase[:, 1] * phase[:, 3]
        detector[~hit] = np.nan
        radius[~hit] = np.nan
        fit = fit_second_order_transfer_model(
            ids,
            phase,
            {
                "focus_time_ns": focus,
                "detector_time_ns": detector,
                "detector_radius_mm": radius,
            },
            hit,
            validation_fraction=0.25,
        )
        split_ids = set(fit.model.split.train_ids) | set(fit.model.split.validation_ids)
        self.assertEqual(split_ids, set(ids.tolist()))
        self.assertTrue(set(ids[~hit].tolist()).issubset(split_ids))
        detector_census = fit.continuous_label_census["detector_time_ns"]
        self.assertEqual(detector_census.population_count, count)
        self.assertEqual(detector_census.finite_label_count, int(np.count_nonzero(hit)))
        self.assertEqual(
            detector_census.train_finite_label_count + detector_census.validation_finite_label_count,
            detector_census.finite_label_count,
        )
        self.assertEqual(fit.continuous_label_census["focus_time_ns"].finite_label_count, count)
        prediction = fit.model.predict(phase)
        self.assertEqual(prediction.predicted_hit.shape, (count,))
        self.assertTrue(np.all(np.isfinite(prediction.detector_time_ns)))
        self.assertTrue(np.all(np.isfinite(prediction.detector_radius_mm)))
        self.assertIsNotNone(fit.validation_rmse["detector_time_ns"])

    def test_infinite_continuous_label_is_rejected(self) -> None:
        rng = np.random.default_rng(17)
        phase = rng.normal(size=(80, 6))
        detector = np.zeros(80)
        detector[0] = np.inf
        with self.assertRaisesRegex(TransferModelContractError, "finite or explicitly missing"):
            fit_second_order_transfer_model(
                np.arange(80),
                phase,
                {
                    "focus_time_ns": np.zeros(80),
                    "detector_time_ns": detector,
                    "detector_radius_mm": np.zeros(80),
                },
                np.zeros(80, dtype=bool),
            )

    def test_fixed_split_is_identity_based_and_order_independent(self) -> None:
        ids = list(range(1, 101))
        first = fixed_id_train_validation_split(ids, validation_fraction=0.2, seed=77)
        second = fixed_id_train_validation_split(ids[::-1], validation_fraction=0.2, seed=77)
        self.assertEqual(first.train_ids, second.train_ids)
        self.assertEqual(first.validation_ids, second.validation_ids)
        self.assertEqual(len(first.validation_ids), 20)
        with self.assertRaisesRegex(TransferModelContractError, "unique"):
            fixed_id_train_validation_split([1, 1, 2])

    def test_acceptance_window_is_detector_blind_and_uses_0537_ns_budget(self) -> None:
        axes = [np.asarray([-1.0, 0.0, 1.0])] * 5
        grid = np.asarray(np.meshgrid(*axes, indexing="ij")).reshape(5, -1).T
        radii = np.max(np.abs(grid), axis=1)
        field_error = np.where(radii <= 0.5, 0.1, 0.8)
        window = freeze_theoretical_acceptance_window(
            grid,
            field_error,
            np.zeros(5),
            np.ones(5),
        )
        self.assertEqual(window.feature_names, ACCEPTANCE_FEATURE_NAMES)
        self.assertEqual(window.final_time_budget_ns, 0.537)
        self.assertFalse(window.detector_results_used)
        self.assertEqual(window.homothetic_scale, 0.0)
        signature = inspect.signature(freeze_theoretical_acceptance_window)
        self.assertNotIn("detector_time", signature.parameters)
        self.assertNotIn("hit_status", signature.parameters)
        self.assertNotIn("detector_results_used", signature.parameters)
        with self.assertRaisesRegex(TypeError, "unexpected keyword"):
            freeze_theoretical_acceptance_window(
                grid,
                field_error,
                np.zeros(5),
                np.ones(5),
                detector_time_ns=np.zeros(len(grid)),
            )

    def test_coverage_below_seventy_percent_fails_closed(self) -> None:
        grid = np.zeros((3, 5))
        grid[1] = 0.5
        grid[2] = -0.5
        window = freeze_theoretical_acceptance_window(
            grid,
            [0.1, 0.1, 0.1],
            np.zeros(5),
            np.full(5, 0.5),
        )
        eligible = np.zeros((10, 5))
        eligible[6:, 0] = 2.0
        with self.assertRaisesRegex(AcceptanceCoverageError, "below 0.700000"):
            evaluate_pulse_eligible_coverage(window, range(1, 11), eligible)
        eligible[6, 0] = 0.0
        coverage = evaluate_pulse_eligible_coverage(window, range(1, 11), eligible)
        self.assertEqual(coverage.accepted_count, 7)
        self.assertEqual(coverage.coverage_fraction, 0.7)

    def test_campaign_window_profile_is_json_roundtrippable_and_detector_blind(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        axes = [np.asarray([-1.0, 0.0, 1.0])] * 5
        grid = np.asarray(np.meshgrid(*axes, indexing="ij")).reshape(5, -1).T
        window = freeze_theoretical_acceptance_window(
            grid,
            np.full(len(grid), 0.1),
            np.zeros(5),
            np.ones(5),
        )
        eligible = grid[:20]
        coverage = evaluate_pulse_eligible_coverage(window, np.arange(1, 21), eligible)
        profile = build_campaign_theoretical_acceptance_window_profile(campaign, window, coverage)
        serialized = json.dumps(profile, sort_keys=True)
        restored = load_theoretical_acceptance_window_profile(json.loads(serialized))
        self.assertEqual(profile["feature_order"], list(ACCEPTANCE_FEATURE_NAMES))
        self.assertEqual(profile["field_error_budget_ns"], 0.537)
        self.assertEqual(profile["pulse_eligible_coverage"]["fraction"], 1.0)
        self.assertEqual(
            profile["detector_blind_contract"],
            {
                "detector_results_used": False,
                "selection_uses_detector_outcome": False,
                "freeze_before_real_beam_application": True,
                "outside_window_remains_in_full_beam": True,
            },
        )
        np.testing.assert_array_equal(restored.contains(eligible), np.ones(len(eligible), dtype=bool))
        tampered = json.loads(serialized)
        tampered["bounds"]["x_mm"]["upper"] = 0.5
        with self.assertRaisesRegex(TransferModelContractError, "digest differs"):
            load_theoretical_acceptance_window_profile(tampered)

    def test_voltage_candidates_enforce_count_endpoints_monotonicity_and_envelope(self) -> None:
        nominal = np.asarray([0.0, 100.0, 200.0, 300.0, 400.0])
        basis = np.asarray([[0.0, 10.0, 0.0, -10.0, 0.0]])
        candidates = generate_constrained_voltage_candidates(
            nominal,
            basis,
            np.asarray([[-0.5], [0.0], [0.5]]),
            [(-1.0, 1.0)],
            nominal - 20.0,
            nominal + 20.0,
            fixed_endpoint_indices=[0, 2, 4],
        )
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(not candidate.pa_rebuild_required for candidate in candidates))
        for candidate in candidates:
            np.testing.assert_allclose(candidate.electrode_voltages_v[[0, 2, 4]], nominal[[0, 2, 4]])
            self.assertTrue(np.all(np.diff(candidate.electrode_voltages_v) >= 0.0))
        with self.assertRaisesRegex(TransferModelContractError, "between one and five"):
            generate_constrained_voltage_candidates(
                nominal,
                basis,
                np.zeros((6, 1)),
                [(-1.0, 1.0)],
                nominal - 20.0,
                nominal + 20.0,
                fixed_endpoint_indices=[0, 2, 4],
            )
        with self.assertRaisesRegex(TransferModelContractError, "not monotone"):
            generate_constrained_voltage_candidates(
                nominal,
                np.asarray([[0.0, 0.0, 0.0, -250.0, 0.0]]),
                np.asarray([[1.0]]),
                [(-1.0, 1.0)],
                nominal - 300.0,
                nominal + 20.0,
                fixed_endpoint_indices=[0, 2, 4],
            )


if __name__ == "__main__":
    unittest.main()
