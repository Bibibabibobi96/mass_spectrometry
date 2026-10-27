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
    complete_staged_trial,
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
