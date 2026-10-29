"""Controller decisions and explicit checkpoint import without a solver."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.workpoint_controller_state import (
    RECOVERY_VERSION, advance_recovery_round, import_recovery_checkpoint,
    prepare_recovery_state, relative_voltage_step, voltage_stencil_steps, validate_recovery_policy,
    complete_staged_trial, dispatch_controller_request, plan_staged_trial,
    recovery_probe_directions, interrupted_topology_recovery_decision,
    bootstrap_stencil_configuration, continuation_transport_candidates, center_trial_physical_gate,
    plan_bootstrap_stencil,
    prepare_imported_stencil_column,
    plan_recovery_probe, complete_recovery_model,
    restored_stage_columns, main_iteration_budget,
)

PROJECT = Path(__file__).resolve().parents[2]


class ControllerStateTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((PROJECT / "config/simion_candidate_two_zone.json").read_text())["downstream_fixed_grid_workpoint_profile"]
        self.policy = json.loads((PROJECT / "config/local_model_recovery_policy.json").read_text())
        self.anchor = dict(voltages_v=[-27., 54., 190., -190.], maximum_scaled_abs_residual=20.)
        self.decision = dict(iteration=6, recovery_state=dict(accepted_anchor=self.anchor, model_invalid_reason="topology_loss"))
        self.evidence = dict(materialization="accepted.json", observation="observed.json")
        self.history = dict(decisions=[])

    def fresh(self, history=None):
        return prepare_recovery_state(self.decision, self.evidence, None, self.profile, self.policy,
                                      self.history if history is None else history)

    def staged(self):
        state = dict(stage="stripe_preclosure", anchor_manifest="anchor", columns={}, attempts=[],
                     flight_count=7, candidate_count=2, step_factor=.5, completion_attempted=False,
                     local_model_tier_index=0, consecutive_candidate_rejections=0)
        decision = dict(status="needs_stencil", next_action="measure_stencil", voltages_v=[-27., 54., 190., -190.],
                        next_voltages_v=[-27., 54., 190., -190.], required_axes=[0], maximum_scaled_abs_residual=20.,
                        resolved_numerics=dict(lower_bounds_v=[-300.] * 4, upper_bounds_v=[300.] * 4))
        return state, decision

    def test_transport_candidates_match_original_powershell_vectors(self):
        # Captured from the production PS function before this migration. Each
        # rejected physical trial was recorded by its real dispatch boundary.
        cases = (
            ([219.0625, -173.75], [[120., 280.], [-200., 400.]], [
                [219.0625, -173.75], [221.253125, -173.75], [216.871875, -173.75],
                [219.0625, -172.0125], [219.0625, -175.4875],
                [219.61015625, -173.75], [218.51484375, -173.75],
                [219.0625, -173.315625], [219.0625, -174.184375],
                [219.17203125, -173.75], [218.95296875, -173.75],
                [219.0625, -173.663125], [219.0625, -173.836875]]),
            ([0., -.5], [[-.01, .01], [-.505, -.495]], [
                [0., -.5], [.01, -.5], [-.01, -.5], [.0025, -.5], [-.0025, -.5],
                [0., -.4975], [0., -.5025], [.0005, -.5], [-.0005, -.5], [0., -.4995], [0., -.5005]]),
            ([190., -190.], [[188.1, 191.9], [-191.9, -188.1]], [
                [190., -190.], [191.9, -190.], [188.1, -190.], [190., -188.1], [190., -191.9],
                [190.475, -190.], [189.525, -190.], [190., -189.525], [190., -190.475],
                [190.095, -190.], [189.905, -190.], [190., -189.905], [190., -190.095]]),
        )
        for origin, bounds, expected in cases:
            seed = dict(prism_voltages_v=origin, prism_voltage_bounds_v=bounds)
            before = copy.deepcopy((seed, self.profile))
            actual = continuation_transport_candidates(seed, self.profile)
            self.assertEqual([[v.hex() for v in row] for row in actual],
                             [[v.hex() for v in row] for row in expected])
            self.assertEqual((seed, self.profile), before)
            self.assertEqual(dispatch_controller_request(dict(action="continuation_transport_candidates",
                                                               seed=seed, profile=self.profile)), actual)
        for medium in (.01, -.0025, float("nan")):
            profile = copy.deepcopy(self.profile)
            profile["jacobian_relative_step_tiers"]["medium"] = medium
            with self.assertRaises(CandidateContractError):
                continuation_transport_candidates(seed, profile)

    def test_bootstrap_configuration_preserves_existing_step_and_scale_values(self):
        result = bootstrap_stencil_configuration([-27., 54., 190., -190.], self.profile)
        self.assertEqual([v.hex() for v in result["forward_steps_v"]],
                         [v.hex() for v in [.27, .54, 1.9000000000000001, 1.9000000000000001]])
        self.assertEqual([v.hex() for v in result["stencil_step_scales"]],
                         [v.hex() for v in [1., .25, .05]])
        self.assertEqual(dispatch_controller_request(dict(action="bootstrap_stencil_configuration",
                                                           voltages_v=[-27., 54., 190., -190.], profile=self.profile)), result)

    def test_physical_gate_matches_original_powershell_classification(self):
        valid = dict(status="detected", termination_diagnostic=dict(physical_collision=False),
                     residuals=dict(Stripe_target_phase_y_minus_origin_mm=0.),
                     static_return_diagnostic=dict(status="detector_hit", event_contract_ok=True))
        cases = [({}, []), (dict(status="DETECTED", static_return_diagnostic=dict(status="DETECTOR_HIT", event_contract_ok=True)), []),
                 (dict(termination_diagnostic=dict(physical_collision=True)), ["collision_absence_not_proven"]),
                 (dict(termination_diagnostic=dict(physical_collision=0)), ["collision_absence_not_proven"]),
                 (dict(static_return_diagnostic=dict(status="detector_hit", event_contract_ok="true")), ["static_detector_contract_failed"])]
        for value, reasons in ((None, ["target_phase_residual_missing"]), (True, []), ("0.125", []),
                               (float("nan"), ["target_phase_residual_missing"]), (float("inf"), ["target_phase_residual_missing"])):
            cases.append((dict(residuals=dict(Stripe_target_phase_y_minus_origin_mm=value)), reasons))
        cases.append((dict(status="lost", termination_diagnostic={}, residuals={}, static_return_diagnostic={}),
                      ["target_phase_status_invalid", "collision_absence_not_proven", "target_phase_residual_missing", "static_detector_contract_failed"]))
        for changes, reasons in cases:
            observation = dict(valid, **changes)
            result = center_trial_physical_gate(observation)
            self.assertEqual(result, dict(passed=not reasons, reasons=reasons))
            self.assertEqual(dispatch_controller_request(dict(action="center_trial_physical_gate", observation=observation)), result)
        with self.assertRaises(ValueError):
            center_trial_physical_gate(dict(valid, residuals=dict(Stripe_target_phase_y_minus_origin_mm="invalid")))

    def test_stencil_plan_matches_original_twenty_five_dispatches(self):
        seed = [-27., 54., 190., -190.]
        steps = [.27, .54, 1.9000000000000001, 1.9000000000000001]
        scales = [1., .25, .05]
        before = copy.deepcopy((seed, steps, scales))
        result = plan_bootstrap_stencil(seed, steps, scales)
        self.assertEqual([group["axis"] for group in result["groups"]], [-1, 0, 1, 2, 3])
        self.assertEqual([len(group["trials"]) for group in result["groups"]], [1, 6, 6, 6, 6])
        self.assertEqual(result["groups"][0]["trials"], [dict(direction=0, step_scale=1., signed_step_v=0., voltages_v=seed, tier_index=0)])
        # Original actual PS dispatch and saved signed-step values, not a
        # recomputation through the new planner's arithmetic.
        targets = [[-26.73, -27.27, -26.9325, -27.0675, -26.9865, -27.0135],
                   [54.54, 53.46, 54.135, 53.865, 54.027, 53.973],
                   [191.9, 188.1, 190.475, 189.525, 190.095, 189.905],
                   [-188.1, -191.9, -189.525, -190.475, -189.905, -190.095]]
        signed_steps = [[.27, -.27, .0675, -.0675, .013500000000000002, -.013500000000000002],
                        [.54, -.54, .135, -.135, .027000000000000003, -.027000000000000003],
                        [1.9000000000000001, -1.9000000000000001, .47500000000000003, -.47500000000000003, .09500000000000001, -.09500000000000001]]
        signed_steps.append(signed_steps[-1])
        for axis, group in enumerate(result["groups"][1:]):
            self.assertEqual([trial["direction"] for trial in group["trials"]], [1, -1, 1, -1, 1, -1])
            self.assertEqual([trial["tier_index"] for trial in group["trials"]], [0, 0, 2, 2, 3, 3])
            for index, trial in enumerate(group["trials"]):
                voltage = seed[:]; voltage[axis] = targets[axis][index]
                self.assertEqual([value.hex() for value in trial["voltages_v"]], [value.hex() for value in voltage])
                self.assertEqual(trial["signed_step_v"].hex(), signed_steps[axis][index].hex())
        self.assertEqual((seed, steps, scales), before)
        self.assertEqual(dispatch_controller_request(dict(action="plan_bootstrap_stencil", voltages_v=seed,
                                                           forward_steps_v=steps, step_scales=scales)), result)
        self.assertEqual([len(group["trials"]) for group in plan_bootstrap_stencil(seed, steps)["groups"]], [1, 2, 2, 2, 2])
        duplicate = plan_bootstrap_stencil(seed, steps, [.25, 1., .25])["groups"][1]["trials"]
        self.assertEqual([trial["tier_index"] for trial in duplicate], [1, 1, 0, 0, 1, 1])
        for invalid in ([], [0.], [-.1], [1.1], [float("nan")], [float("inf")]):
            with self.assertRaises(CandidateContractError):
                plan_bootstrap_stencil(seed, steps, invalid)

    def test_imported_column_matches_original_powershell_tier_and_debit(self):
        anchor = [-27., 54., 189., -190.]
        for label, axis, actual, tier, tiers, expected_tier, signed in (
            ("coarse", 0, [-26.73, 54., 189., -190.], 0, [.01, .0025, .0005], 0, .2699999999999996),
            ("fine_negative", 1, [-27., 53.973, 189., -190.], 0, [.01, .0025, .0005], 2, -.027000000000001023),
            ("unmatched", 0, [-26.9, 54., 189., -190.], 1, [.01, .0025, .0005], 1, .10000000000000142),
            ("duplicate", 0, [-26.73, 54., 189., -190.], 1, [.01, .01, .0005], 1, .2699999999999996),
            ("retain_fine", 0, [-26.9325, 54., 189., -190.], 2, [.01, .0025, .0005], 2, .067499999999999),
        ):
            with self.subTest(label=label):
                state = dict(stage="stripe_preclosure", anchor_manifest="seed", local_model_tier_index=tier,
                             flight_count=5, columns={"saved": "unchanged"})
                before = copy.deepcopy((state, anchor, actual, tiers))
                result = prepare_imported_stencil_column(state, axis, anchor, actual, tiers)
                self.assertEqual(result["state"], dict(state, local_model_tier_index=expected_tier, flight_count=6))
                self.assertEqual(result["selected"]["axis"], axis)
                self.assertEqual(result["selected"]["signed_step_v"].hex(), signed.hex())
                self.assertEqual((state, anchor, actual, tiers), before)
                self.assertEqual(dispatch_controller_request(dict(action="prepare_imported_stencil_column",
                    state=state, axis=axis, anchor_v=anchor, actual_v=actual, tiers=tiers)), result)

    def test_staged_planner_matches_pre_migration_powershell_vectors(self):
        # Recorded by executing the original production PS block before migration,
        # including the binary64 1.9000000000000001 P step, not rounded fixtures.
        state, decision = self.staged()
        for label, changes, request, signed, tier, voltage in (
            ("coarse_plus", {}, {}, .27, 0, -26.73),
            ("coarse_minus", dict(attempts=[dict(axis=0, signed_step_v=.27)]), {}, -.27, 0, -27.27),
            ("medium", dict(attempts=[dict(axis=0, signed_step_v=.27), dict(axis=0, signed_step_v=-.27)]), {}, .0675, 1, -26.9325),
            ("residual_medium", {}, dict(maximum_scaled_abs_residual=10.), .0675, 1, -26.9325),
            ("residual_fine", {}, dict(maximum_scaled_abs_residual=2.), .0135, 2, -26.9865),
            ("fine_retained", dict(local_model_tier_index=2), {}, .0135, 2, -26.9865),
            ("prism", dict(stage="prism_preclosure"), dict(required_axes=[2]), 1.9000000000000001, 0, 191.9),
        ):
            with self.subTest(label=label):
                given = dict(state, **changes); proposal = dict(decision, **request)
                before = copy.deepcopy((given, proposal, self.profile))
                actual = plan_staged_trial(given, self.profile, proposal)
                axis = proposal["required_axes"][0]
                expected_v = decision["voltages_v"][:]; expected_v[axis] = voltage
                self.assertEqual(actual["voltages_v"], expected_v)
                self.assertEqual(actual["selected"], dict(axis=axis, signed_step_v=signed))
                self.assertEqual(actual["state"], dict(given, flight_count=8, local_model_tier_index=tier))
                self.assertIsNone(actual["terminal"])
                self.assertEqual((given, proposal, self.profile), before)
        proposal = dict(decision, status="proposed", next_action="run_candidate", next_voltages_v=[-26., 55., 192., -189.])
        for action in ("run_candidate", "complete_N1"):
            actual = plan_staged_trial(state, self.profile, dict(proposal, next_action=action))
            self.assertEqual(actual["voltages_v"], [-26.5, 54.5, 191., -189.5])
            self.assertEqual(actual["state"], dict(state, flight_count=8, candidate_count=3))
        for floor, reason in ((1., None), (1.0001, "step_too_small")):
            profile = copy.deepcopy(self.profile); profile["automatic_iteration"]["minimum_step_linf_v"] = floor
            actual = plan_staged_trial(state, profile, proposal)
            self.assertEqual(actual["terminal"]["terminal_reason"] if reason else actual["terminal"], reason)
            self.assertEqual(actual["state"], state if reason else dict(state, flight_count=8, candidate_count=3))
        exhausted = dict(state, candidate_count=self.profile["automatic_iteration"]["maximum_iterations"])
        actual = plan_staged_trial(exhausted, self.profile, proposal)
        self.assertEqual(actual["state"], exhausted)
        self.assertEqual(actual["terminal"]["terminal_reason"], "maximum_iterations")
        self.assertEqual(actual["voltages_v"], proposal["next_voltages_v"])
        n1 = dict(decision, status="incomplete", next_action="complete_N1")
        actual = plan_staged_trial(state, self.profile, n1)
        self.assertEqual(actual["state"], dict(state, flight_count=8, completion_attempted=True))
        actual = plan_staged_trial(dict(state, completion_attempted=True), self.profile, n1)
        self.assertEqual(actual["terminal"]["terminal_reason"], "missing_target_phase")
        self.assertEqual(actual["state"]["flight_count"], 7)
        closed = dict(decision, resolved_numerics=dict(lower_bounds_v=decision["voltages_v"], upper_bounds_v=decision["voltages_v"]))
        actual = plan_staged_trial(state, self.profile, closed)
        self.assertEqual(actual["state"], state)
        self.assertEqual(actual["terminal"]["detail"], "No measurable same-anchor stage column within contract tiers.")

    def test_staged_reset_and_transition_preserve_budget_and_history_projection(self):
        state, decision = self.staged()
        state.update(columns={"0": "old"}, attempts=[dict(axis=0, signed_step_v=.27)],
                     consecutive_candidate_rejections=self.profile["automatic_iteration"]["maximum_consecutive_non_improving_iterations"])
        result = plan_staged_trial(state, self.profile, phase="prepare")
        self.assertEqual(result["state"], dict(state, columns={}, attempts=[], local_model_tier_index=1,
                                               consecutive_candidate_rejections=0, step_factor=1.))
        self.assertEqual(result["history_decision"]["previous_columns"], {"0": "old"})
        self.assertEqual(result["history_decision"]["next_relative_tier"], .0025)
        terminal = plan_staged_trial(dict(state, local_model_tier_index=2), self.profile, phase="prepare")
        self.assertEqual(terminal["terminal"]["detail"], "All contract S local-model tiers rejected candidates.")
        state["prism_model_manifest"] = "model"
        result = plan_staged_trial(state, self.profile, dict(decision, next_action="prism_preclosure"))
        self.assertEqual(result["action"], "stage_transition")
        self.assertNotIn("prism_model_manifest", result["state"])
        self.assertEqual((result["state"]["flight_count"], result["state"]["candidate_count"]), (7, 2))

    def test_staged_inclusive_bounds_joint_axes_and_invalid_inputs(self):
        state, decision = self.staged()
        decision["resolved_numerics"]["upper_bounds_v"][0] = -26.73
        self.assertEqual(plan_staged_trial(state, self.profile, decision)["selected"]["signed_step_v"], .27)
        decision["resolved_numerics"]["upper_bounds_v"][0] = -26.7300001
        self.assertEqual(plan_staged_trial(state, self.profile, decision)["selected"]["signed_step_v"], -.27)
        single = dict(self.profile, active_stripe_axes=["stripe_1_voltage_v"], single_stripe_refinement_mode="joint_ps_constrained")
        decision["voltages_v"][1] = decision["next_voltages_v"][1] = 0.
        for axis in (0, 2, 3):
            self.assertEqual(plan_staged_trial(state, single, dict(decision, required_axes=[axis]))["selected"]["axis"], axis)
        with self.assertRaisesRegex(CandidateContractError, "inactive"):
            plan_staged_trial(state, single, dict(decision, required_axes=[1]))
        for bad in (True, float("nan"), float("inf")):
            invalid = dict(decision, voltages_v=[bad, 0., 190., -190.])
            with self.assertRaises(CandidateContractError):
                plan_staged_trial(state, self.profile, invalid)
        for changes in (dict(local_model_tier_index=-1), dict(local_model_tier_index=True), dict(flight_count=-1), dict(stage="unknown")):
            with self.assertRaises(CandidateContractError):
                plan_staged_trial(dict(state, **changes), self.profile, decision)
        with self.assertRaises(CandidateContractError):
            plan_staged_trial(state, self.profile, dict(decision, next_voltages_v=[1, 2]))
        with self.assertRaises(CandidateContractError):
            plan_staged_trial(state, self.profile, decision, phase="unknown")

    def test_recovery_probe_plan_preserves_signed_order_debits_and_actual_columns(self):
        state = self.fresh()
        original = copy.deepcopy(state)
        # Original PS uses preferred S1, its reverse after rejection, then S2.
        expected = ((0, 1, .27, [-26.73, 54., 190., -190.]),
                    (0, -1, -.27, [-27.27, 54., 190., -190.]),
                    (1, 1, .54, [-27., 54.54, 190., -190.]))
        for index, (axis, direction, signed, volts) in enumerate(expected):
            before = copy.deepcopy(state)
            planned = dispatch_controller_request(dict(action="plan_recovery_probe", state=state,
                                                        directions=[1, 1], profile=self.profile))
            self.assertEqual(state, before)
            self.assertEqual(planned["action"], "probe")
            self.assertEqual([v.hex() for v in planned["voltages_v"]], [v.hex() for v in volts])
            state = planned["state"]
            self.assertEqual(state["probe_budget_remaining"], 11 - index)
            probe = state["probes"][-1]
            self.assertEqual((probe["axis"], probe["direction"], probe["signed_step_v"].hex()),
                             (axis, direction, signed.hex()))
            probe.update(run_id=f"probe-{index}", status="rejected_physical_probe" if index == 0 else "accepted_physical_probe")
        planned = plan_recovery_probe(state, [1, 1], self.profile)
        self.assertEqual(planned["action"], "refresh")
        self.assertEqual(planned["supported_directions"], [-1, 1])
        self.assertEqual(planned["trusted_radius_linf_v"].hex(), .54.hex())
        self.assertEqual([p["run_id"] for p in planned["columns"]], ["probe-1", "probe-2"])
        self.assertEqual(original["probes"], [])

    def test_recovery_probe_plan_keeps_late_column_failure_and_exhaustion_boundary(self):
        state = self.fresh()
        state["probes"] = [dict(axis=1, round=1, direction=1, status="accepted_physical_probe")] * 2
        planned = plan_recovery_probe(state, [1, 1], self.profile)
        self.assertEqual(planned["state"]["probes"][-1]["axis"], 0)
        planned["state"]["probes"][-1]["status"] = "accepted_physical_probe"
        with self.assertRaisesRegex(CandidateContractError, "more than one accepted"):
            plan_recovery_probe(planned["state"], [1, 1], self.profile)
        for round_number, expected in ((1, "retry"), (3, "terminal")):
            state = self.fresh()
            state.update(recovery_round=round_number, probe_budget_remaining=0)
            planned = plan_recovery_probe(state, [1, 1], self.profile)
            self.assertEqual(planned["action"], "return")
            self.assertEqual(planned["state"]["status"], expected)
            self.assertEqual(planned["state"]["probe_budget_remaining"], 0)
        state = self.fresh()
        state["probes"] = [dict(axis=0, round=1, direction=1, status="started")]
        planned = plan_recovery_probe(state, [1, 1], self.profile)
        self.assertEqual(planned["state"]["probes"][-1]["direction"], -1)

    def test_recovery_model_keeps_original_final_radius_and_strict_pass_policy(self):
        for passed, count, round_number, status, published in (
                (True, 2, 1, "validated", False), (False, 2, 1, "retry", False),
                (False, 0, 1, "retry", False), (False, 0, 3, "validated", True),
                (False, 2, 3, "terminal", False), ("false", 0, 3, "terminal", False),
                (None, 0, 3, "validated", True), (False, .9, 3, "terminal", False),
                (False, .5, 3, "validated", True)):
            with self.subTest(passed=passed, count=count, round_number=round_number):
                state = self.fresh()
                for _ in range(1, round_number):
                    state = advance_recovery_round(state, self.profile)
                state.update(probe_budget_remaining=10, probes=[dict(axis=axis, round=round_number,
                             direction=direction, status="accepted_physical_probe") for axis, direction in ((0, -1), (1, 1))])
                model = dict(history_validation=dict(passed=passed, eligible_observation_count=count),
                             local_s_physical_jacobian_columns=[[1., 0.], [0., 1.], [1., 1.], [2., 2.]])
                before = copy.deepcopy((state, model))
                result = dispatch_controller_request(dict(action="complete_recovery_model", state=state, model=model, profile=self.profile))
                self.assertEqual((state, model), before)
                self.assertEqual(result["state"]["status"], status)
                self.assertEqual(result["publish_model"], published)
                self.assertEqual(result["state"]["probe_budget_remaining"], 12 if status == "retry" else 10)
                if status == "validated":
                    self.assertEqual(result["model_projection"]["trusted_radius_linf_v"].hex(), max(state["probe_steps_v"]).hex())
                    self.assertEqual(result["model_projection"]["supported_directions"], [-1, 1])
                    self.assertNotIn("sha256", result["model_projection"])
                if published:
                    self.assertIs(result["model"]["history_validation"]["first_correction_requires_real_prediction_acceptance"], True)
                else:
                    self.assertEqual(result["model"], model)
        with self.assertRaises(CandidateContractError):
            complete_recovery_model(state, dict(history_validation=None), self.profile)

    def test_recovery_direction_actual_dictionary_semantics_and_override_order(self):
        anchor = dict(voltages_v=[0., 0., 100., -100.])
        records = [dict(observation_record=dict(voltages_v=v)) for v in ([-2., 1., 100., -100.], [1., -1., 100., -100.])]
        # These four expectations were executed against the pre-migration PS helper.
        for history, expected in ((dict(decisions=records), [1, 1]), (records, [1, -1]),
                                  (records[::-1] + records, [1, -1]),
                                  ([dict(observation_record=dict(voltages_v=[1e-12, -1e-12, 100., -100.]))], [1, 1])):
            self.assertEqual(recovery_probe_directions(history, anchor, {}, {}), expected)
        trigger = dict(trigger=dict(decision=dict(observation_record=dict(voltages_v=[-1., 1e-12, 100., -100.]))))
        self.assertEqual(recovery_probe_directions(dict(decisions=records), anchor, trigger, {}), [-1, 1])
        for hint, expected in (([1, -1], [1, -1]), ([0, 1], [-1, 1]), ([1], [-1, 1]), ([.9, -1.1], [1, -1])):
            self.assertEqual(recovery_probe_directions({}, anchor, trigger, dict(recovery_state=dict(initial_probe_directions=hint))), expected)
        request = dict(action="prepare_recovery_state", decision=self.decision, evidence=self.evidence, stored=None,
                       profile=self.profile, policy=self.policy, history=self.history)
        original = dispatch_controller_request(request)
        response = dispatch_controller_request(dict(request, include_probe_directions=True))
        self.assertEqual(response, dict(state=original, required_directions=[1, 1]))

    def test_restored_axes_share_policy_without_rewriting_old_input_representation(self):
        single = dict(active_stripe_axes=["stripe_1_voltage_v"])
        self.assertEqual(restored_stage_columns("PRISM_PRECLOSURE", {}), [2, 3])
        self.assertEqual(restored_stage_columns("saved_unknown_stage", single), [0])
        self.assertEqual(restored_stage_columns("stripe_preclosure", dict(single, single_stripe_refinement_mode="JOINT_PS_CONSTRAINED")), [0, 2, 3])
        uppercase = dict(active_stripe_axes=["STRIPE_1_VOLTAGE_V"])
        self.assertEqual(restored_stage_columns("stripe_preclosure", uppercase), [-1])
        with self.assertRaises(CandidateContractError):
            restored_stage_columns("stripe_preclosure", dict(uppercase, single_stripe_refinement_mode="joint_ps_constrained"))
        # Ordinary planning continues to require its original canonical schema.
        state, decision = self.staged()
        with self.assertRaises(CandidateContractError):
            plan_staged_trial(state, dict(self.profile, **uppercase), decision)

    def test_main_budget_does_not_precompute_post_loop_decision_or_replace_existing_terminal(self):
        for start in (1, 8, 9, 12):
            result = dispatch_controller_request(dict(action="main_iteration_budget", maximum_iterations=8,
                                                     terminal_decision=None, next_iteration=start, phase="start"))
            self.assertEqual(result["maximum_flight_attempts"], 8)
            if start <= 8:
                self.assertIsNone(result["terminal_decision"])
            else:
                self.assertEqual(result["terminal_decision"]["iteration"], start - 1)
                self.assertEqual(result["terminal_decision"]["terminal_reason"], "maximum_iterations")
        exhausted = main_iteration_budget(8, None, phase="exhausted")
        self.assertEqual(exhausted["terminal_decision"]["iteration"], 8)
        existing = dict(state="terminal", terminal_reason="existing", nested=dict(values=[1, 2]))
        for phase in ("start", "exhausted"):
            result = main_iteration_budget(8, existing, next_iteration=12, phase=phase)
            self.assertEqual(result["terminal_decision"], existing)
            self.assertIsNot(result["terminal_decision"]["nested"], existing["nested"])

    def test_persisted_topology_recovery_is_narrow_and_keeps_first_rejection(self):
        anchor = dict(coordinate_group="stripe_1_stripe_2", accepted_workpoint=self.anchor)
        first = dict(coordinate_group="physical_topology_backtrack", invalid_trial_reason="collision_or_invalid_topology",
                     iteration=7, recovery_state=dict(recovery_origin_voltages_v=[-28., 55., 190., -190.], advance_multiplier=1.2, backtrack_multiplier=.5))
        history = dict(decisions=[anchor, first, dict(state="recovery_required")])
        result = interrupted_topology_recovery_decision(history)
        self.assertEqual(result["recovery_state"]["initial_probe_directions"], [-1, 1])
        self.assertEqual(result["accepted_workpoint"], self.anchor)
        self.assertEqual(result["iteration"], 7)
        self.assertEqual(result, dispatch_controller_request(dict(action="interrupted_topology_recovery_decision", history=history)))
        for values in ([], [anchor], [anchor, dict(state="recovery_required"), first], [anchor, first, anchor]):
            self.assertIsNone(interrupted_topology_recovery_decision(dict(decisions=values)))
        for voltage in ([-27., 55., 190., -190.], [-28., 55., 191., -190.], [-28., 55.]):
            rejected = copy.deepcopy(first); rejected["recovery_state"]["recovery_origin_voltages_v"] = voltage
            self.assertIsNone(interrupted_topology_recovery_decision(dict(decisions=[anchor, rejected])))

    def test_stencil_tier_boundaries_and_voltage_scale(self):
        for residual, expected in ((None, .01), (10., .0025), (2., .0005), (11., .01)):
            self.assertEqual(relative_voltage_step(self.profile, residual), expected)
            self.assertEqual(voltage_stencil_steps([-.5, 0, 100, -100], self.profile, residual),
                             [expected, expected, 100*expected, 100*expected])
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(CandidateContractError):
                voltage_stencil_steps([value, 0, 1, 2], self.profile)

    def test_recovery_policy_is_required_and_frozen(self):
        with self.assertRaises(CandidateContractError):
            validate_recovery_policy({})
        state = self.fresh()
        changed = dict(self.policy, total_probe_budget=20)
        with self.assertRaisesRegex(CandidateContractError, "frozen policy"):
            prepare_recovery_state(self.decision, self.evidence, state, self.profile, changed, self.history)

    def test_ordinary_prepare_rejects_all_old_and_unknown_formats(self):
        for version in (1, 5, 6, 7, 9):
            with self.subTest(version=version):
                state = self.fresh(); state["recovery_policy_version"] = version
                with self.assertRaisesRegex(CandidateContractError, "import.*explicitly"):
                    prepare_recovery_state(self.decision, self.evidence, state, self.profile, self.policy, self.history)

    def test_import_v5_preserves_signed_probes_and_counts_used_budget(self):
        state = self.fresh()
        state.update(recovery_policy_version=5, status="terminal", terminal_reason="model_recovery_exhausted",
                     probe_budget_remaining=0, probes=[dict(round=1, axis=0, direction=-1, signed_step_v=-.27,
                                                           run_id="frozen-probe", status="accepted_physical_probe")])
        before = copy.deepcopy(state)
        imported = import_recovery_checkpoint(state, self.history, self.profile, self.policy)
        self.assertEqual(state, before)
        self.assertEqual(imported["probes"], before["probes"])
        self.assertEqual(imported["probe_budget_remaining"], 11)
        self.assertEqual(imported["recovery_round"], 2)
        self.assertEqual(imported["probe_steps_v"], [.0675, .135])
        self.assertEqual(imported["recovery_policy_version"], RECOVERY_VERSION)

    def test_import_v6_repeated_recovery_uses_existing_fine_rule(self):
        state = self.fresh(); state["recovery_policy_version"] = 6
        imported = import_recovery_checkpoint(state, dict(decisions=[dict(recovery_resume_proposal=True)]),
                                              self.profile, self.policy)
        self.assertEqual(imported["probe_steps_v"], [.0135, .027])
        self.assertEqual(imported["recovery_round"], 3)
        self.assertEqual(imported["probe_budget_remaining"], 12)

    def test_import_corrects_anchor_before_old_repeat_recovery_transition(self):
        history = dict(decisions=[dict(recovery_resume_proposal=True)])
        corrected = dict(self.evidence, materialization="corrected.json")
        for version in (5, 6):
            with self.subTest(version=version):
                state = self.fresh()
                state.update(recovery_policy_version=version, status="validated", model={"sha256": "old"})
                imported = import_recovery_checkpoint(state, history, self.profile, self.policy, self.decision, corrected)
                current = prepare_recovery_state(self.decision, corrected, imported, self.profile, self.policy, history)
                self.assertEqual(current["recovery_round"], 3)
                self.assertEqual(current["probe_steps_v"], [.0135, .027])
                self.assertEqual(current["next_action"], "refresh_independent_s_columns_at_persisted_fine_relative_tier")
                self.assertEqual(current["accepted_anchor"]["evidence"], corrected)
                self.assertIsNone(current["model"])
                self.assertEqual(state["accepted_anchor"]["evidence"], self.evidence)

    def test_import_v7_and_current_preserve_accepted_evidence_and_are_idempotent(self):
        state = self.fresh(); state.update(recovery_policy_version=7, status="validated", model={"sha256": "frozen"})
        imported = import_recovery_checkpoint(state, self.history, self.profile, self.policy)
        self.assertEqual(imported["model"], state["model"])
        self.assertEqual(imported["accepted_anchor"], state["accepted_anchor"])
        self.assertEqual(import_recovery_checkpoint(imported, self.history, self.profile, self.policy), imported)
        for version in (None, 1, 4, 9, True):
            with self.assertRaises(CandidateContractError):
                import_recovery_checkpoint(dict(state, recovery_policy_version=version), self.history, self.profile, self.policy)

    def test_new_recovery_after_accepted_prediction_stays_at_fine_tier(self):
        state = self.fresh(dict(decisions=[dict(recovery_resume_proposal=True)]))
        self.assertEqual(state["probe_steps_v"], [.0135, .027])
        self.assertEqual(state["recovery_round"], 3)

    def test_round_reduction_derives_ratios_from_the_contract(self):
        profile = copy.deepcopy(self.profile)
        profile["jacobian_relative_step_tiers"].update(coarse=.02, medium=.004, fine=.001)
        state = self.fresh()
        reduced = advance_recovery_round(state, profile)
        self.assertEqual(reduced["probe_steps_v"], [.054000000000000006, .10800000000000001])
        self.assertEqual(reduced["probe_budget_remaining"], state["probe_budget_remaining"])
        again = advance_recovery_round(reduced, profile, replenish_columns=True)
        self.assertEqual(again["probe_budget_remaining"], state["probe_budget_remaining"] + 2)
        with self.assertRaises(CandidateContractError):
            advance_recovery_round(again, profile)

    def test_current_state_reuses_probes_and_revalidates_changed_anchor_evidence(self):
        state = self.fresh(); state.update(status="validated", model={"sha256": "old"})
        current = prepare_recovery_state(self.decision, self.evidence, state, self.profile, self.policy, self.history)
        self.assertEqual(current, state)
        corrected = dict(self.evidence, materialization="corrected.json")
        changed = prepare_recovery_state(self.decision, corrected, state, self.profile, self.policy, self.history)
        self.assertEqual(changed["status"], "probing")
        self.assertIsNone(changed["model"])
        self.assertEqual(changed["accepted_anchor"]["evidence"], corrected)

    def test_new_trigger_does_not_reuse_an_old_models_probes_or_budget(self):
        stored = self.fresh()
        stored.update(probes=[dict(run_id="old-probe")], probe_budget_remaining=1)
        for key, value in (("iteration", 7), ("reason", "different_reason")):
            with self.subTest(trigger=key):
                old = copy.deepcopy(stored); old["trigger"][key] = value
                current = prepare_recovery_state(self.decision, self.evidence, old, self.profile, self.policy, self.history)
                self.assertEqual(current["probes"], [])
                self.assertEqual(current["probe_budget_remaining"], self.policy["total_probe_budget"])

    def test_exhausted_current_model_uses_only_the_existing_smaller_or_final_radius_rule(self):
        state = self.fresh()
        state.update(status="terminal", terminal_reason="model_recovery_exhausted", model=None,
                     history_validation=dict(eligible_observation_count=1, passed=False))
        current = prepare_recovery_state(self.decision, self.evidence, state, self.profile, self.policy, self.history)
        self.assertEqual(current["status"], "probing")
        self.assertEqual(current["recovery_round"], 2)
        self.assertEqual(current["probe_budget_remaining"], state["probe_budget_remaining"] + 2)
        state.update(recovery_round=3, history_validation=dict(eligible_observation_count=0, passed=False))
        current = prepare_recovery_state(self.decision, self.evidence, state, self.profile, self.policy, self.history)
        self.assertEqual(current["status"], "probing")
        self.assertEqual(current["recovery_round"], 3)
        self.assertEqual(current["probe_budget_remaining"], state["probe_budget_remaining"])

    def test_staged_candidate_acceptance_and_rejection_keep_debits_and_parent_state(self):
        pending = dict(child_manifest="measured-child", decision=dict(status="proposed", next_action="run_S_candidate",
                       maximum_scaled_abs_residual=4., backtrack_multiplier=.5))
        state = dict(stage="stripe_preclosure", anchor_manifest="accepted-parent", columns={"0": "column"},
                     attempts=[dict(axis=0)], flight_count=11, candidate_count=3, step_factor=.5,
                     completion_attempted=True, pending_trial=pending, local_model_tier_index=1,
                     consecutive_candidate_rejections=2, prism_model_manifest="accepted-model")
        checked = dict(status="needs_stencil", next_action="measure_stencil", full_workpoint_qualified=False,
                       maximum_scaled_abs_residual=2.)
        cases = (
            ("improved", {}, {}, "trusted", True, 1., "keep"),
            ("poor_prediction", {}, {}, "poor", True, .25, "keep"),
            ("not_improved", {"maximum_scaled_abs_residual": 3.9}, {}, "trusted", False, .25, "keep"),
            ("terminal_rejected", {"status": "terminal"}, {}, "trusted", False, .25, "rejected_candidate"),
            ("joint_p_rejected", {"next_action": "prism_preclosure"}, {"refinement_mode": "joint_ps_constrained"}, "trusted", False, .25, "rejected_candidate"),
            ("stage_changed", {"next_action": "prism_preclosure", "maximum_scaled_abs_residual": 8.}, {}, "trusted", True, 1., "keep"),
            ("qualified", {"status": "terminal", "full_workpoint_qualified": True}, {}, "trusted", True, 1., "keep"),
        )
        for label, observed, proposal, quality, accepted, factor, payload in cases:
            with self.subTest(case=label):
                trial = copy.deepcopy(pending); trial["decision"].update(proposal)
                before = copy.deepcopy(state)
                result = complete_staged_trial(state, trial, dict(checked, **observed), dict(status=quality),
                                               dict(minimum_relative_improvement=.1))
                self.assertEqual(state, before)
                current = result["state"]
                self.assertEqual((current["flight_count"], current["candidate_count"]), (11, 3))
                self.assertEqual(current["anchor_manifest"], "measured-child" if accepted else "accepted-parent")
                self.assertEqual(current["step_factor"], factor)
                self.assertEqual(current["consecutive_candidate_rejections"], 0 if accepted else 3)
                self.assertEqual(result["compose_payload_use"], payload)
                self.assertNotIn("pending_trial", current)
                if label == "stage_changed":
                    self.assertEqual(current["local_model_tier_index"], 0)
                    self.assertNotIn("prism_model_manifest", current)

    def test_staged_stencil_records_column_or_accepts_full_workpoint(self):
        state = dict(stage="stripe_preclosure", anchor_manifest="parent", columns={}, attempts=[],
                     flight_count=4, candidate_count=1, step_factor=.25, completion_attempted=True)
        pending = dict(child_manifest="child", selected=dict(axis=0, signed_step_v=-.1), decision=dict(status="needs_stencil"))
        for qualified in (False, True):
            with self.subTest(qualified=qualified):
                checked = dict(full_workpoint_qualified=qualified)
                result = complete_staged_trial(state, pending, checked, {}, {})
                current = result["state"]
                if qualified:
                    self.assertEqual(current["anchor_manifest"], "child")
                    self.assertEqual(current["columns"], {})
                    self.assertEqual(result["history_decision"], checked)
                    self.assertFalse(current["completion_attempted"])
                else:
                    self.assertEqual(current["columns"], {"0": "child"})
                    self.assertEqual(current["attempts"], [pending["selected"]])
                    self.assertIsNone(result["history_decision"])
                self.assertEqual(result["compose_payload_use"], "keep" if qualified else "stencil")


if __name__ == "__main__":
    unittest.main()
