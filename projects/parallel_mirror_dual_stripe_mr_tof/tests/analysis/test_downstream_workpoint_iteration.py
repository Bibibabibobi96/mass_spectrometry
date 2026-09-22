from __future__ import annotations

import copy
import json
import contextlib
import io
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
    _print_iteration_summary,
    decide_iteration,
    merge_s_local_jacobian,
    refresh_s_local_jacobian,
    resolve_operating_cache_binding,
    select_best_physical_workpoint,
    solver_failure_decision,
    validate_s_local_jacobian_against_history,
)


class DownstreamWorkpointIterationTests(unittest.TestCase):
    def test_cache_key_comes_from_manifest_bound_protection_receipt(self):
        cache_key = "4EF52AA6960BB0412BEE61ADD6F49A181A49B9627EBD54414710E8B8726F090A"
        identity = {
            "schema_version": 2,
            "role": "simion_standalone_operating_pa_group",
            "members": [],
            "synthesis": {},
        }
        protection = {
            "schema_version": 1,
            "role": "mrtof_local_operating_cache_protection_renewal",
            "status": "success",
            "lease_id": "lease-r7",
            "lease_owner": "owner-r7",
            "cache_key": cache_key,
            "generation_directory": rf"C:\cache\{cache_key}\generations\generation-r7",
            "renewal": {
                "lease_id": "lease-r7",
                "owner": "owner-r7",
                "protected_cache_keys": [cache_key.lower()],
            },
        }

        result = resolve_operating_cache_binding(
            identity,
            protection,
            expected_lease_id="lease-r7",
            expected_lease_owner="owner-r7",
        )

        self.assertNotIn("cache_key", identity)
        self.assertEqual(result["cache_key"], cache_key)

    def test_cache_binding_rejects_receipt_that_did_not_protect_key(self):
        cache_key = "A" * 64
        identity = {
            "schema_version": 2,
            "role": "simion_standalone_operating_pa_group",
            "members": [],
            "synthesis": {},
        }
        protection = {
            "schema_version": 1,
            "role": "mrtof_local_operating_cache_protection_renewal",
            "status": "success",
            "lease_id": "lease",
            "lease_owner": "owner",
            "cache_key": cache_key,
            "generation_directory": rf"C:\cache\{cache_key}\generations\generation",
            "renewal": {
                "lease_id": "lease",
                "owner": "owner",
                "protected_cache_keys": ["B" * 64],
            },
        }

        with self.assertRaisesRegex(Exception, "does not protect"):
            resolve_operating_cache_binding(identity, protection)

    def test_native_binding_requires_same_bank_generation_and_protected_key(self):
        key, generation = "A" * 64, "B" * 64
        path = rf"C:\cache\{key}\generations\g"
        identity = {
            "schema_version": 1, "role": "mrtof_private_native_corridor_family", "status": "prepared",
            "cache_key": key, "generation_sha256": generation, "generation_directory": path,
            "response_refine_performed": False, "published_native_members_opened": False,
            "controller_refine": "solutions={0}",
        }
        protection = {
            "schema_version": 1, "role": "mrtof_local_operating_cache_protection_renewal", "status": "success",
            "lease_id": "lease", "lease_owner": "owner", "cache_key": key, "generation_directory": path,
            "renewal": {"lease_id": "lease", "owner": "owner", "protected_cache_keys": [key]},
        }
        result = resolve_operating_cache_binding(identity, protection)
        self.assertEqual(result["native_bank_identity"], {"cache_key": key, "generation_sha256": generation})
        for change, message in [({"cache_key": "C" * 64}, "cache_key differs"),
                                ({"generation_directory": path + "other"}, "generation_directory differs"),
                                ({"response_refine_performed": True}, "receipt is invalid")]:
            with self.subTest(change=change), self.assertRaisesRegex(Exception, message):
                resolve_operating_cache_binding({**identity, **change}, protection)

    def fixtures(self):
        names = [
            "P1_P2_positive_mirror_turn_y_mm",
            "P1_P2_P2_shield_low_field_signed_vy_over_vz",
            "Stripe_slow_turn_y_minus_L_mm",
            "Stripe_target_phase_y_minus_origin_mm",
        ]
        prior = {
            "status": "linearized_candidate_step",
            "unknown_names": [
                "stripe_1_voltage_v", "stripe_2_voltage_v",
                "prism_1_voltage_v", "prism_2_voltage_v",
            ],
            "residual_names": names,
            "baseline_voltages_v": [-24.0, 52.0, 190.0, -192.0],
            "physical_jacobian_rows": [
                [-0.0015, 0.00018, 0.19, 0.068],
                [1.4e-7, 1.8e-7, 2.2e-4, 2.3e-4],
                [1.245, -2.092, 0.85, 0.92],
                [5.646, -0.715, -1.40, -1.39],
            ],
            "resolved_numerics": {
                "parameter_scales_v": [25, 52, 190, 192],
                "maximum_abs_step_v": [2, 2, 2, 2],
                "lower_bounds_v": [-4000, 1, 100, -300],
                "upper_bounds_v": [-1, 3900, 300, -100],
            },
        }
        observation = {
            "status": "full_drift_observed",
            "return_topology": "exact_target_k_phase_return",
            "termination_diagnostic": {"physical_collision": False},
            "static_return_diagnostic": {"status": "detector_hit", "event_contract_ok": True},
            "residuals": dict(zip(names, [0.001, 1e-6, -1.0, 2.0], strict=True)),
        }
        materialization = {
            "stripe_biases_v": [-25.35, 51.85],
            "prism_voltages_v": [190.6, -191.94],
            "target_low_field_tangent_ratio_vy_over_vz": 0.033686,
        }
        contract = {"downstream_fixed_grid_workpoint_profile": {
            "schema_version": 1,
            "automatic_iteration": {
                "schema_version": 1,
                "maximum_iterations": 8,
                "damping_factor": 0.5,
                "minimum_step_linf_v": 1e-6,
                "minimum_relative_improvement": 0.01,
                "maximum_consecutive_non_improving_iterations": 3,
                "cycle_voltage_tolerance_v": 1e-8,
                "oscillation_window": 4,
                "capacity_protection_ttl_seconds": 14400,
                "acceptance_tolerances": {
                    names[0]: 0.01,
                    "P1_P2_P2_shield_low_field_angle_degrees": 0.01,
                    names[2]: 0.01,
                    names[3]: 0.01,
                },
            },
        }}
        return prior, observation, materialization, contract

    def test_updates_prisms_first_when_injection_contract_fails(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 0.2
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["state"], "continue")
        self.assertEqual(result["coordinate_group"], "prism_1_prism_2")
        self.assertEqual(result["applied_correction_v"][:2], [0.0, 0.0])

    def test_updates_stripes_after_prism_handoff_passes(self):
        result = decide_iteration(*self.fixtures(), [], 1)
        self.assertEqual(result["coordinate_group"], "stripe_1_stripe_2")
        self.assertEqual(result["applied_correction_v"][2:], [0.0, 0.0])

    def test_accepts_only_real_residual_and_detector_contract(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["residuals"].update({
            "Stripe_slow_turn_y_minus_L_mm": 0.001,
            "Stripe_target_phase_y_minus_origin_mm": -0.002,
        })
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["terminal_reason"], "success")

    def test_missing_real_target_phase_backtracks(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["return_topology"] = "coordinate_return_before_target_phase"
        del observation["residuals"]["Stripe_target_phase_y_minus_origin_mm"]
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["state"], "continue")
        self.assertEqual(result["invalid_trial_reason"], "missing_target_phase")
        self.assertEqual(result["coordinate_group"], "physical_topology_backtrack")

    def test_collision_backtracks_toward_last_valid_point(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["termination_diagnostic"]["physical_collision"] = True
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["state"], "continue")
        self.assertEqual(result["invalid_trial_reason"], "collision_or_invalid_topology")
        self.assertEqual(result["proposed_voltages_v"], [-24.675, 51.925, 190.3, -191.97])

    def test_first_s_only_topology_loss_refreshes_independent_columns(self):
        prior, observation, materialization, contract = self.fixtures()
        accepted = decide_iteration(prior, observation, materialization, contract, [], 1)
        invalid = copy.deepcopy(observation)
        invalid["termination_diagnostic"]["physical_collision"] = True
        candidate = copy.deepcopy(materialization)
        candidate["stripe_biases_v"] = accepted["proposed_voltages_v"][:2]
        candidate["prism_voltages_v"] = accepted["proposed_voltages_v"][2:]
        result = decide_iteration(prior, invalid, candidate, contract, [accepted], 2)
        self.assertEqual(result["state"], "recovery_required")
        self.assertEqual(result["recovery_state"]["model_invalid_reason"], "s_only_topology_loss")
        self.assertEqual(result["recovery_state"]["initial_probe_directions"], [
            1 if candidate["stripe_biases_v"][axis] > accepted["observation_record"]["voltages_v"][axis] else -1
            for axis in range(2)
        ])
        self.assertEqual(result["invalid_candidate_voltages_v"], [
            *candidate["stripe_biases_v"], *candidate["prism_voltages_v"],
        ])

    def test_incomplete_static_return_backtracks(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["static_return_diagnostic"]["status"] = "return_positive_mirror_turn_missing"
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["state"], "continue")
        self.assertEqual(result["invalid_trial_reason"], "collision_or_invalid_topology")

    def test_invalid_retry_uses_latest_valid_history_and_ignores_earlier_backtrack(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["termination_diagnostic"]["physical_collision"] = True
        history = [
            {"observation_record": {
                "voltages_v": [-25.0, 51.0, 191.0, -193.0],
                "scaled_residual_norm": 10.0,
                "physical_acceptance_residuals": dict.fromkeys(prior["residual_names"], 1.0),
            }},
            {"coordinate_group": "physical_topology_backtrack"},
        ]
        result = decide_iteration(prior, observation, materialization, contract, history, 3)
        self.assertEqual(result["backtrack_anchor_voltages_v"], [-25.0, 51.0, 191.0, -193.0])
        self.assertEqual(result["proposed_voltages_v"], [-25.0875, 51.2125, 190.9, -192.735])

    def test_backtrack_history_resets_at_latest_accepted_workpoint(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["termination_diagnostic"]["physical_collision"] = True
        accepted = {
            "voltages_v": [-24.0, 52.0, 190.0, -192.0],
            "physical_acceptance_residuals": dict.fromkeys(prior["residual_names"], 0.1),
            "acceptance_tolerances": dict.fromkeys(
                [prior["residual_names"][0], "P1_P2_P2_shield_low_field_angle_degrees", *prior["residual_names"][2:]],
                0.01,
            ),
        }
        history = [
            {"coordinate_group": "physical_topology_backtrack"},
            {"coordinate_group": "stripe_1_stripe_2", "accepted_workpoint": accepted},
        ]
        result = decide_iteration(prior, observation, materialization, contract, history, 3)
        self.assertEqual(result["backtrack_factor"], 0.5)
        self.assertEqual(result["backtrack_anchor_voltages_v"], accepted["voltages_v"])

    def test_backtrack_shrinks_the_original_rejected_ray_once_per_retry(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["termination_diagnostic"]["physical_collision"] = True
        first = decide_iteration(prior, observation, materialization, contract, [], 1)
        retry_materialization = copy.deepcopy(materialization)
        retry_materialization["stripe_biases_v"] = first["proposed_voltages_v"][:2]
        retry_materialization["prism_voltages_v"] = first["proposed_voltages_v"][2:]
        second = decide_iteration(prior, observation, retry_materialization, contract, [first], 2)
        self.assertAlmostEqual(first["backtrack_factor"], 0.5)
        self.assertAlmostEqual(second["backtrack_factor"], 0.25)
        self.assertEqual(second["proposed_voltages_v"], [-24.3375, 51.9625, 190.15, -191.985])

    def test_uses_separate_advance_and_backtrack_multipliers_when_configured(self):
        prior, observation, materialization, contract = self.fixtures()
        loop = contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
        loop["advance_multiplier"] = 0.75
        loop["backtrack_multiplier"] = 0.25
        observation["termination_diagnostic"]["physical_collision"] = True
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertAlmostEqual(result["backtrack_factor"], 0.25)
        self.assertAlmostEqual(result["recovery_state"]["advance_multiplier"], 0.75)

    def test_opposite_prediction_direction_requests_local_s_recovery(self):
        prior, observation, materialization, contract = self.fixtures()
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)
        predicted = seed["predicted_physical_acceptance_residuals"]
        current = copy.deepcopy(observation)
        for name in prior["residual_names"][2:]:
            base = seed["observation_record"]["physical_acceptance_residuals"][name]
            current["residuals"][name] = base - 2.0 * (predicted[name] - base)
        next_materialization = copy.deepcopy(materialization)
        next_materialization["stripe_biases_v"] = seed["proposed_voltages_v"][:2]
        next_materialization["prism_voltages_v"] = seed["proposed_voltages_v"][2:]
        result = decide_iteration(prior, current, next_materialization, contract, [seed], 2)
        self.assertEqual(result["state"], "recovery_required")
        self.assertEqual(result["recovery_state"]["model_invalid_reason"], "prediction_direction_wrong")
        self.assertFalse(result["candidate_accepted"])
        json.dumps(result)

    def test_poor_but_improving_prediction_shrinks_the_next_advance_multiplier(self):
        prior, observation, materialization, contract = self.fixtures()
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)
        predicted = seed["predicted_physical_acceptance_residuals"]
        current = copy.deepcopy(observation)
        for name in prior["residual_names"][2:]:
            base = seed["observation_record"]["physical_acceptance_residuals"][name]
            current["residuals"][name] = base + 0.1 * (predicted[name] - base)
        next_materialization = copy.deepcopy(materialization)
        next_materialization["stripe_biases_v"] = seed["proposed_voltages_v"][:2]
        next_materialization["prism_voltages_v"] = seed["proposed_voltages_v"][2:]
        result = decide_iteration(prior, current, next_materialization, contract, [seed], 2)
        self.assertTrue(result["candidate_accepted"])
        self.assertEqual(result["prediction_assessment"]["prediction_confidence"], "poor_shrunk")
        self.assertAlmostEqual(result["prediction_assessment"]["next_advance_multiplier"], 0.25)

    def test_best_physical_handoff_keeps_a_valid_subthreshold_improvement(self):
        prior, observation, materialization, contract = self.fixtures()
        accepted = decide_iteration(prior, observation, materialization, contract, [], 1)
        subthreshold = copy.deepcopy(accepted)
        subthreshold["candidate_accepted"] = False
        subthreshold["invalid_trial_reason"] = "residual_stagnation"
        subthreshold["observation_record"]["scaled_residual_norm"] = 1.0
        subthreshold["observation_record"]["physical_acceptance_residuals"][prior["residual_names"][3]] = 0.02
        handoff = select_best_physical_workpoint([accepted, subthreshold])
        self.assertEqual(handoff["status"], "warning")
        self.assertEqual(handoff["selected_history_ordinal"], 2)
        self.assertEqual(handoff["selected_workpoint"]["voltages_v"], subthreshold["observation_record"]["voltages_v"])

    def test_best_physical_handoff_prefers_lower_prism_magnitude_after_p_qualification(self):
        prior, observation, materialization, contract = self.fixtures()
        high_voltage = decide_iteration(prior, observation, materialization, contract, [], 1)
        lower_voltage = copy.deepcopy(high_voltage)
        lower_voltage["observation_record"]["voltages_v"][2:] = [180.0, -180.0]
        handoff = select_best_physical_workpoint([high_voltage, lower_voltage])
        self.assertEqual(handoff["selected_history_ordinal"], 2)
        self.assertEqual(handoff["selected_p1_p2_voltage_magnitude"], {
            "maximum_abs_v": 180.0, "sum_abs_v": 360.0,
        })

        better_residual = copy.deepcopy(high_voltage)
        better_residual["observation_record"]["scaled_residual_norm"] = 0.5
        better_residual["observation_record"]["maximum_scaled_abs_residual"] = 0.5
        handoff = select_best_physical_workpoint([better_residual, lower_voltage])
        self.assertEqual(handoff["selected_history_ordinal"], 2)

    def test_best_physical_handoff_rejects_invalid_or_p_unqualified_lower_voltage_records(self):
        prior, observation, materialization, contract = self.fixtures()
        accepted = decide_iteration(prior, observation, materialization, contract, [], 1)
        invalid = copy.deepcopy(accepted)
        invalid["candidate_accepted"] = False
        invalid["invalid_trial_reason"] = "collision_or_invalid_topology"
        invalid["observation_record"]["scaled_residual_norm"] = 0.1
        invalid["observation_record"]["voltages_v"][2:] = [1.0, -1.0]
        p_unqualified = copy.deepcopy(accepted)
        p_unqualified["observation_record"]["scaled_residual_norm"] = 0.2
        p_unqualified["observation_record"]["voltages_v"][2:] = [2.0, -2.0]
        p_unqualified["observation_record"]["physical_acceptance_residuals"][
            "P1_P2_positive_mirror_turn_y_mm"
        ] = 0.02
        handoff = select_best_physical_workpoint([invalid, p_unqualified, accepted])
        self.assertEqual(handoff["selected_history_ordinal"], 3)

    def test_two_same_ray_rejections_request_local_s_recovery(self):
        prior, observation, materialization, contract = self.fixtures()
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)
        anchor = seed["observation_record"]
        rejected_history = []
        for offset in (0.25, 0.5):
            record = copy.deepcopy(anchor)
            record["voltages_v"][0] += offset
            record["physical_acceptance_residuals"][prior["residual_names"][2]] = -3.0
            record["physical_acceptance_residuals"][prior["residual_names"][3]] = 3.0
            rejected_history.append({
                "coordinate_group": "physical_topology_backtrack",
                "rejected_coordinate_group": "stripe_1_stripe_2",
                "candidate_accepted": False,
                "observation_record": record,
            })
        current = copy.deepcopy(observation)
        current["residuals"][prior["residual_names"][2]] = -4.0
        current["residuals"][prior["residual_names"][3]] = 4.0
        next_materialization = copy.deepcopy(materialization)
        next_materialization["stripe_biases_v"][0] += 0.75
        result = decide_iteration(
            prior, current, next_materialization, contract, [seed, *rejected_history], 4
        )
        self.assertEqual(result["state"], "recovery_required")
        self.assertEqual(
            result["recovery_state"]["model_invalid_reason"],
            "consecutive_same_direction_rejected_candidates",
        )

    def test_recovery_resume_derives_first_s_candidate_without_reflying_anchor(self):
        prior, observation, materialization, contract = self.fixtures()
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)
        recovered_model = {
            "coordinate_group": "stripe_1_stripe_2",
            "local_s_physical_jacobian_columns": [
                [-0.0015, 0.00018], [1.4e-7, 1.8e-7], [1.245, -2.092], [5.646, -0.715],
            ],
            "local_s_model_validation": {
                "passed": True,
                "validation_status": "provisional_no_nearby_history",
                "first_correction_requires_real_prediction_acceptance": True,
                "first_correction_max_linf_v": 0.02,
            },
        }
        result = decide_iteration(
            prior, observation, materialization, contract, [seed, recovered_model], 2,
            recovery_resume=True,
        )
        self.assertEqual(result["state"], "continue")
        self.assertTrue(result["recovery_resume_proposal"])
        self.assertTrue(result["prediction_assessment"]["first_real_prediction_acceptance_required"])
        self.assertLessEqual(max(abs(value) for value in result["applied_correction_v"][:2]), 0.02)
        self.assertEqual(result["applied_correction_v"][2:], [0.0, 0.0])

    def test_refresh_s_local_jacobian_requires_independent_anchor_perturbations(self):
        prior, observation, materialization, contract = self.fixtures()
        anchor = decide_iteration(prior, observation, materialization, contract, [], 1)["observation_record"]
        s1, s2 = copy.deepcopy(anchor), copy.deepcopy(anchor)
        s1["voltages_v"][0] += 0.1
        s2["voltages_v"][1] += 0.1
        s1["physical_acceptance_residuals"][prior["residual_names"][2]] += 0.2
        s2["physical_acceptance_residuals"][prior["residual_names"][3]] -= 0.3
        jacobian = refresh_s_local_jacobian(anchor, s1, s2)
        self.assertEqual(jacobian.shape, (4, 2))
        self.assertAlmostEqual(jacobian[2, 0], 2.0)
        self.assertAlmostEqual(jacobian[3, 1], -3.0)
        s2["voltages_v"][0] += 0.1
        with self.assertRaisesRegex(Exception, "independently perturb"):
            refresh_s_local_jacobian(anchor, s1, s2)

    def test_validates_refreshed_s_columns_against_existing_anchor_local_history(self):
        prior, observation, materialization, contract = self.fixtures()
        anchor = decide_iteration(prior, observation, materialization, contract, [], 1)["observation_record"]
        columns = [[0.0, 0.0], [0.0, 0.0], [2.0, -1.0], [3.0, 4.0]]
        sample = copy.deepcopy(anchor)
        sample["voltages_v"][0] += 0.1
        sample["physical_acceptance_residuals"][prior["residual_names"][2]] += 0.2
        sample["physical_acceptance_residuals"][prior["residual_names"][3]] += 0.3
        coupled = copy.deepcopy(sample)
        coupled["voltages_v"][2] += 1.0
        validation = validate_s_local_jacobian_against_history(anchor, columns, [
            {"observation_record": sample}, {"observation_record": coupled},
        ])
        self.assertTrue(validation["passed"])
        self.assertEqual(validation["comparable_observation_count"], 1)
        sample["physical_acceptance_residuals"][prior["residual_names"][3]] -= 1.0
        self.assertFalse(validate_s_local_jacobian_against_history(
            anchor, columns, [{"observation_record": sample}]
        )["passed"])

    def test_local_history_validation_uses_only_directionally_supported_nearby_evidence(self):
        prior, observation, materialization, contract = self.fixtures()
        anchor = decide_iteration(prior, observation, materialization, contract, [], 1)["observation_record"]
        columns = [[0.0, 0.0], [0.0, 0.0], [2.0, -1.0], [3.0, 4.0]]
        near_negative = copy.deepcopy(anchor)
        near_negative["voltages_v"][1] -= 0.01
        near_negative["physical_acceptance_residuals"] = dict(anchor["physical_acceptance_residuals"])
        residual_names = prior["residual_names"]
        anchor_vector = [anchor["physical_acceptance_residuals"][name] for name in residual_names]
        near_negative_vector = [anchor_vector[index] - 0.01 * columns[index][1] for index in range(4)]
        near_negative["physical_acceptance_residuals"] = dict(zip(residual_names, near_negative_vector, strict=True))
        far_negative = copy.deepcopy(near_negative)
        far_negative["voltages_v"][1] = anchor["voltages_v"][1] - 0.04
        far_negative["physical_acceptance_residuals"] = dict(zip(
            residual_names, [anchor_vector[index] - 0.04 * columns[index][1] for index in range(4)], strict=True
        ))
        validation = validate_s_local_jacobian_against_history(
            anchor, columns, [{"observation_record": far_negative}, {"observation_record": near_negative}],
            trusted_radius_linf_v=0.02, supported_directions=[1, -1],
        )
        self.assertTrue(validation["passed"])
        self.assertEqual(validation["eligible_observation_count"], 1)
        self.assertFalse(validation["comparisons"][0]["within_trusted_radius"])
        json.dumps(validation)

    def test_merges_explicit_s_columns_without_mutating_p_columns(self):
        base = [[float(row * 4 + column) for column in range(4)] for row in range(4)]
        columns = [[10.0, 11.0], [12.0, 13.0], [14.0, 15.0], [16.0, 17.0]]
        merged = merge_s_local_jacobian(base, columns)
        self.assertEqual(merged[:, :2].tolist(), columns)
        self.assertEqual(merged[:, 2:].tolist(), [[2.0, 3.0], [6.0, 7.0], [10.0, 11.0], [14.0, 15.0]])

    def test_backtracks_do_not_consume_valid_iteration_budget(self):
        prior, observation, materialization, contract = self.fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 2
        history = [{"coordinate_group": "physical_topology_backtrack"}]
        result = decide_iteration(prior, observation, materialization, contract, history, 2)
        self.assertEqual(result["state"], "continue")
        self.assertIsNone(result["terminal_reason"])

    def test_prism_iterations_do_not_consume_stripe_iteration_budget(self):
        prior, observation, materialization, contract = self.fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 2
        record = decide_iteration(prior, observation, materialization, contract, [], 1)["observation_record"]
        history = [{"coordinate_group": "prism_1_prism_2", "observation_record": record}]
        result = decide_iteration(prior, observation, materialization, contract, history, 2)
        self.assertEqual(result["state"], "continue")
        self.assertEqual(result["coordinate_group"], "stripe_1_stripe_2")

    def test_invalid_backtrack_budget_is_independently_bounded(self):
        prior, observation, materialization, contract = self.fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 2
        observation["termination_diagnostic"]["physical_collision"] = True
        history = [{"coordinate_group": "physical_topology_backtrack"}]
        result = decide_iteration(prior, observation, materialization, contract, history, 2)
        self.assertEqual(result["state"], "terminal")
        self.assertEqual(result["terminal_reason"], "collision_or_invalid_topology")

    def test_two_point_cycle_stops(self):
        prior, observation, materialization, contract = self.fixtures()
        current = materialization["stripe_biases_v"] + materialization["prism_voltages_v"]
        history = [
            {"observation_record": {"voltages_v": current, "scaled_residual_norm": 300.0,
                                    "physical_acceptance_residuals": dict.fromkeys(prior["residual_names"], 1.0)}},
            {"observation_record": {"voltages_v": [-26, 52, 191, -192], "scaled_residual_norm": 250.0,
                                    "physical_acceptance_residuals": dict.fromkeys(prior["residual_names"], -1.0)}},
        ]
        result = decide_iteration(prior, observation, materialization, contract, history, 3)
        self.assertEqual(result["terminal_reason"], "two_point_cycle")

    def test_stagnation_and_iteration_budget_are_terminal(self):
        prior, observation, materialization, contract = self.fixtures()
        decision = decide_iteration(prior, observation, materialization, contract, [], 1)
        record = decision["observation_record"]
        history = []
        for scale in (0.999, 0.998, 0.997):
            item = copy.deepcopy(record)
            for name in prior["residual_names"][2:]:
                item["physical_acceptance_residuals"][name] *= scale
            item["voltages_v"][0] += scale
            history.append({"coordinate_group": "stripe_1_stripe_2", "observation_record": item})
        result = decide_iteration(prior, observation, materialization, contract, history, 4)
        self.assertEqual(result["state"], "continue")
        self.assertFalse(result["candidate_accepted"])
        self.assertEqual(result["coordinate_group"], "physical_topology_backtrack")
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 1
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["terminal_reason"], "maximum_iterations")

    def test_prism_progress_is_not_masked_by_uncontrolled_stripe_residuals(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["residuals"].update({
            prior["residual_names"][0]: 0.03,
            prior["residual_names"][1]: 1e-6,
            prior["residual_names"][2]: -4.0,
            prior["residual_names"][3]: 8.0,
        })
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)
        history = []
        for index, (mirror_y, stripe_scale) in enumerate(((0.12, 1.0), (0.06, 2.0)), 1):
            item = copy.deepcopy(seed["observation_record"])
            item["voltages_v"][2] += index
            item["physical_acceptance_residuals"][prior["residual_names"][0]] = mirror_y
            item["physical_acceptance_residuals"][prior["residual_names"][2]] *= stripe_scale
            item["physical_acceptance_residuals"][prior["residual_names"][3]] *= stripe_scale
            history.append({"coordinate_group": "prism_1_prism_2", "observation_record": item})
        result = decide_iteration(prior, observation, materialization, contract, history, 3)
        self.assertEqual(result["state"], "continue")
        self.assertEqual(result["coordinate_group"], "prism_1_prism_2")

    def test_console_summary_reports_values_limits_and_results(self):
        prior, observation, materialization, contract = self.fixtures()
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            _print_iteration_summary(result, observation)
        text = output.getvalue()
        self.assertIn("MRTOF_WORKPOINT_TOLERANCE", text)
        self.assertIn("mirror_y_mm_limit=0.01", text)
        self.assertIn("target_phase_y_mm_result=FAIL", text)
        self.assertIn("MRTOF_WORKPOINT_STEP", text)

    def test_step_floor_and_voltage_bound_are_terminal(self):
        prior, observation, materialization, contract = self.fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["minimum_step_linf_v"] = 100.0
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["terminal_reason"], "step_too_small")
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["minimum_step_linf_v"] = 1e-6
        prior["resolved_numerics"]["lower_bounds_v"][:2] = materialization["stripe_biases_v"]
        prior["resolved_numerics"]["upper_bounds_v"][:2] = materialization["stripe_biases_v"]
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["terminal_reason"], "voltage_bound")

    def test_alternating_residual_direction_stops_as_oscillation(self):
        prior, observation, materialization, contract = self.fixtures()
        loop = contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
        loop["minimum_relative_improvement"] = 0.0
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)["observation_record"]
        history = []
        for index, sign in enumerate((-1.0, 1.0, -1.0)):
            item = copy.deepcopy(seed)
            item["voltages_v"][0] += index + 1
            item["physical_acceptance_residuals"] = {
                name: sign * abs(value)
                for name, value in item["physical_acceptance_residuals"].items()
            }
            history.append({"coordinate_group": "stripe_1_stripe_2", "observation_record": item})
        result = decide_iteration(prior, observation, materialization, contract, history, 4)
        self.assertEqual(result["terminal_reason"], "oscillation")

    def test_rank_deficient_selected_solver_is_terminal(self):
        prior, observation, materialization, contract = self.fixtures()
        prior["physical_jacobian_rows"][2][0:2] = [1.0, 2.0]
        prior["physical_jacobian_rows"][3][0:2] = [2.0, 4.0]
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertEqual(result["terminal_reason"], "solver_failure")

    def test_solver_failure_has_explicit_state(self):
        result = solver_failure_decision(2, "child exited 1")
        self.assertEqual(result["terminal_reason"], "solver_failure")


if __name__ == "__main__":
    unittest.main()
