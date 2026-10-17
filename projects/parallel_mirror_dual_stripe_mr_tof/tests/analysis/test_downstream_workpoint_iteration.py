from __future__ import annotations

import copy
import json
import math
import contextlib
import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
    _print_iteration_summary,
    _observation_record,
    _load_stage_trial,
    assert_bounded_controller_resume,
    assess_staged_prediction,
    RESIDUAL_NAMES,
    compact_saved_iteration_state,
    decide_iteration,
    decide_prism_preclosure,
    decide_transported_prism_preclosure,
    decide_preclosure_stage,
    decide_stripe_preclosure,
    main,
    merge_s_local_jacobian,
    refresh_s_local_jacobian,
    resolve_operating_cache_binding,
    resolve_prism_controller_policy,
    select_best_physical_workpoint,
    solver_failure_decision,
    validate_s_local_jacobian_against_history,
)


class DownstreamWorkpointIterationTests(unittest.TestCase):
    def test_measured_acquisition_uses_public_request_and_never_changes_source_energy(self):
        from common.contracts.write_run_manifest import file_record
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
            load_measured_centroid_initial_proposal,prepare_measured_centroid_acquisition,
        )
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            evidence=root/"evidence.json";evidence.write_text('{}')
            proposal=dict(schema_version=1,role="mrtof_measured_centroid_prism_initial_proposal",
                initial_prism_voltages_v=[342.96882193031615,-186.47253641442782],
                prism_bounds_v=dict(p1=[100,500],p2=[-500,-50]),
                inputs={key:file_record(evidence) for key in ("interface_energy_field_audit","old_oa_flight_log","ip_baseline_flight_log","seed_derivation")},
                derivation="synthetic unit fixture",qualification="initial_topology_seed_only",full_workpoint_qualified=False,
                source_state_unchanged=True,target_authority_status="not_assigned_until_actual_clean_reference_is_observed")
            path=root/"proposal.json";path.write_text(json.dumps(proposal))
            self.assertEqual(load_measured_centroid_initial_proposal(path)["initial_prism_voltages_v"],proposal["initial_prism_voltages_v"])
            p1=root/"p1.json";p2=root/"p2.json"
            p1.write_text(json.dumps(dict(axis="p1")));p2.write_text(json.dumps(dict(axis="p2")))
            values=[0]*20;values[10]=-27.0
            binding=dict(accelerator_provider="dual_pressure_rectilinear_ion_processor",manifest="source_manifest.json",
                         authority=dict(analyzer_electrode_voltages_v=values))
            source=evidence.read_bytes()
            with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface.verified_reference",return_value=evidence),\
                 patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding",return_value=binding),\
                 patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_native_response_basis",side_effect=lambda p,b:dict(response_basis=dict(axis=json.loads(p.read_text())["axis"]))):
                result=prepare_measured_centroid_acquisition(prepared_run=root,contract_path=evidence,proposal_path=path,
                    p1_response=p1,p2_response=p2,field_run_id="test-field",output_directory=root/"frozen")
                binding["descriptor_owner"]="extended_fine_manifest.json"
                split=prepare_measured_centroid_acquisition(prepared_run=root,contract_path=evidence,proposal_path=path,
                    p1_response=p1,p2_response=p2,field_run_id="split-owner-field",output_directory=root/"split-owner")
            request=json.loads(Path(result["field_request"]["path"]).read_text())
            split_request=json.loads(Path(split["field_request"]["path"]).read_text())
            self.assertEqual(request["source_field_manifest"],binding["manifest"])
            self.assertEqual(split_request["source_field_manifest"],binding["descriptor_owner"])
            for name in ("source_binding_path","candidate_voltages_v","response_basis_paths"):
                self.assertEqual(split_request[name],request[name])
            self.assertEqual(request["candidate_voltages_v"],dict(s1=-27.0,s2=0,p1=342.96882193031615,p2=-186.47253641442782))
            self.assertEqual(set(request["response_basis_paths"]),{"p1","p2"})
            self.assertNotIn("source_energy",request)
            self.assertFalse(result["physical_target_assigned"])
            self.assertEqual(evidence.read_bytes(),source)
            proposal["initial_prism_voltages_v"][0]=501
            path.write_text(json.dumps(proposal))
            with self.assertRaisesRegex(ValueError,"bounds"):
                load_measured_centroid_initial_proposal(path)
            proposal["initial_prism_voltages_v"][0]=342
            path.write_text(json.dumps(proposal));evidence.write_text('{"changed":true}')
            with self.assertRaises((ValueError,AssertionError)):
                load_measured_centroid_initial_proposal(path)

    def test_staged_quality_uses_original_tolerances_and_missing_evidence_is_unmeasured(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import _stripe_stage_record
        baseline, sample, _, contract, _ = self.stripe_preclosure_fixtures()
        record = _stripe_stage_record(sample, contract["downstream_fixed_grid_workpoint_profile"])
        sample["voltages_v"] = record["voltages_v"]
        decision = dict(next_action="run_S_candidate", next_voltages_v=sample["voltages_v"],
                        predicted_physical_acceptance_residuals=copy.deepcopy(record["physical_acceptance_residuals"]))
        policy = dict(prediction_error_fraction_of_acceptance_tolerance=.1, path="sealed-p-quality.json")
        self.assertEqual(assess_staged_prediction(decision, baseline, sample, contract, policy)["status"], "trusted")
        decision["predicted_physical_acceptance_residuals"][RESIDUAL_NAMES[3]] += .02
        poor = assess_staged_prediction(decision, baseline, sample, contract, policy)
        self.assertEqual(poor["status"], "poor")
        self.assertAlmostEqual(poor["maximum_normalized_error"], .02 /
                               contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["acceptance_tolerances"][RESIDUAL_NAMES[3]])
        for missing in (None, {}):
            self.assertEqual(assess_staged_prediction(dict(next_action="run_S_candidate"), baseline, sample, contract, missing)["status"], "unmeasured")
        bad = copy.deepcopy(sample)
        bad["observation"]["return_topology"] = "other-branch"
        self.assertEqual(assess_staged_prediction(decision, baseline, bad, contract, policy)["status"], "unmeasured")

    def test_staged_p_quality_uses_frozen_compiled_bounds_and_rejects_invalid_plan(self):
        baseline, _, _, contract, numerics = self.prism_preclosure_fixtures()
        baseline["materialization"]["prism_voltages_v"] = [356.46, -197.94]
        baseline["observation"]["prism_voltages_v"] = [356.46, -197.94]
        numerics = copy.deepcopy(numerics)
        numerics["lower_bounds_v"][2:] = [100., -500.]
        numerics["upper_bounds_v"][2:] = [500., -50.]
        actual = decide_prism_preclosure(baseline, None, None, contract, numerics, require_columns=False)
        baseline["voltages_v"] = actual["voltages_v"]
        decision = dict(next_action="run_P_candidate", next_voltages_v=actual["voltages_v"],
                        predicted_physical_acceptance_residuals=actual["physical_acceptance_residuals"],
                        resolved_numerics=numerics)
        saved = copy.deepcopy(decision)
        policy = dict(prediction_error_fraction_of_acceptance_tolerance=.1)
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with patch(module+".resolve_numerics", side_effect=AssertionError("must consume frozen plan")):
            assessment = assess_staged_prediction(decision, baseline, baseline, contract, policy)
            self.assertEqual(assessment["status"], "trusted")
            self.assertEqual(assessment["maximum_normalized_error"], 0.)
            for invalid in (None, {}, dict(numerics, upper_bounds_v=[0., 0., 300., -50.]),
                            dict(numerics, lower_bounds_v=[0., 0., 501., -500.])):
                with self.subTest(invalid=invalid):
                    bad = dict(decision, resolved_numerics=invalid)
                    self.assertEqual(assess_staged_prediction(bad, baseline, baseline, contract, policy)["status"], "unmeasured")
        self.assertEqual(decision, saved)
        fallback = dict(decision)
        fallback.pop("resolved_numerics")
        with patch(module+".resolve_numerics", return_value=numerics) as resolver:
            self.assertEqual(assess_staged_prediction(fallback, baseline, baseline, contract, policy)["status"], "trusted")
            resolver.assert_called_once_with(contract, baseline)

    def test_staged_quality_predicts_executed_p_and_s_half_steps_and_rejects_wrong_direction(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import _stripe_stage_record, ACCEPTANCE_NAMES
        baseline, sample, _, contract, _ = self.stripe_preclosure_fixtures()
        template = _stripe_stage_record(sample, contract["downstream_fixed_grid_workpoint_profile"])
        policy = dict(prediction_error_fraction_of_acceptance_tolerance=.1, path="sealed-quality.json")
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        for prism in (False, True):
            names = ACCEPTANCE_NAMES[:2] if prism else RESIDUAL_NAMES
            base = np.asarray([.1, .001] if prism else [.1, .001, -.05, -.47])
            matrix = np.asarray([[.1, 0.], [.001, 0.]]) if prism else np.asarray([[.01], [.002], [.3], [9.]])
            origin = [-27., 0., 190., -190.]
            axis = 2 if prism else 0
            target, actual_v = origin.copy(), origin.copy()
            target[axis] += .05
            actual_v[axis] += .025
            delta = np.asarray([.025, 0.] if prism else [.025])
            observed = base + matrix @ delta
            decision = dict(next_action="run_P_candidate" if prism else "run_S_candidate", voltages_v=origin,
                next_voltages_v=target, predicted_physical_acceptance_residuals=dict(zip(names, (base+2*(matrix@delta)).tolist())))
            if prism:
                decision.update(physical_acceptance_residuals=dict(zip(names, base.tolist())), physical_jacobian_rows=matrix.tolist())
            else:
                decision.update(observation_record=dict(physical_acceptance_residuals=dict(zip(names, base.tolist()))),
                                joint_active_axes=[0], joint_physical_jacobian_columns=matrix.tolist())
            executed = copy.deepcopy(sample)
            executed["voltages_v"] = actual_v
            record = copy.deepcopy(template)
            record["physical_acceptance_residuals"] = dict(zip(names, observed.tolist()))
            if prism:
                result = dict(physical_acceptance_residuals=record["physical_acceptance_residuals"],
                              prism_acceptance_names=list(names), prism_acceptance_tolerances=[.1, .01])
                mocked = patch(module+".decide_prism_preclosure", return_value=result)
            else:
                mocked = patch(module+"._stripe_stage_record", return_value=record)
            with mocked, patch(module+".resolve_numerics", return_value={}), self.subTest(prism=prism):
                assessment = assess_staged_prediction(decision, baseline, executed, contract, policy)
                self.assertEqual(assessment["status"], "trusted")
                self.assertLess(assessment["maximum_normalized_error"], 1e-10)
                record["physical_acceptance_residuals"].update(dict(zip(names, (base-matrix@delta).tolist())))
                wrong = assess_staged_prediction(decision, baseline, executed, contract, policy)
                self.assertEqual(wrong["status"], "poor")
                self.assertTrue(wrong["prediction_direction_wrong"])
            missing = copy.deepcopy(decision)
            missing.pop("physical_jacobian_rows" if prism else "joint_physical_jacobian_columns")
            self.assertEqual(assess_staged_prediction(missing, baseline, executed, contract, policy)["status"], "unmeasured")

    def test_bounded_controller_resume_preserves_state_and_only_two_declared_changes(self):
        old = {"source": {"energy": 5.374}, "grid": [.25, .25, .1], "voltages": [1, 2],
               "downstream_fixed_grid_workpoint_profile": {"automatic_iteration": {
                   "damping_factor": .5, "maximum_iterations": 5, "acceptance_tolerances": {"phase": .1}}}}
        state = {"candidate_count": 5, "flight_count": 12, "columns": {"0": "same"},
                 "pending_trial": {"voltages_v": [1, 2], "decision": {"advance": .5}}}
        saved = copy.deepcopy(state)
        new = copy.deepcopy(old)
        loop = new["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
        loop.update(advance_multiplier=1., maximum_iterations=6)
        changed = assert_bounded_controller_resume(old, new, state)
        self.assertEqual(changed["preserved_candidate_count"], 5)
        self.assertEqual(state, saved)
        loop["maximum_iterations"] = 5
        self.assertEqual(assert_bounded_controller_resume(old, new, state)["maximum_iterations"]["current"], 5)
        mutations = (
            lambda c: c.update(source={"energy": 6.}), lambda c: c.update(grid=[.2, .2, .1]),
            lambda c: c.update(voltages=[1, 3]),
            lambda c: c["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(maximum_iterations=7),
            lambda c: c["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(maximum_iterations=4),
            lambda c: c["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(advance_multiplier=.75),
            lambda c: c["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(damping_factor=1.),
            lambda c: c["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(acceptance_tolerances={"phase": 1.}),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(new)
                mutation(bad)
                with self.assertRaises(ValueError):
                    assert_bounded_controller_resume(old, bad, state)
        with self.assertRaises(ValueError):
            assert_bounded_controller_resume(old, new, dict(state, candidate_count=6))

    def test_execution_budget_resume_preserves_all_other_fields_and_cumulative_debits(self):
        old = dict(source=dict(velocity=[1,2,3],clock=9),target=dict(y=360,k=24.5),
            geometry=dict(gap=4),field=dict(operator='original'),numerics=dict(grid=.1,step=.004,quality=8),
            downstream_fixed_grid_workpoint_profile=dict(automatic_iteration=dict(
                damping_factor=.5,advance_multiplier=1.,maximum_iterations=5,
                acceptance_tolerances=dict(phase=.1),relative_step_cap=.01)))
        new=copy.deepcopy(old)
        new['downstream_fixed_grid_workpoint_profile']['automatic_iteration']['maximum_iterations']=30
        state=dict(candidate_count=5,flight_count=17,columns={'2':'P1'},history=['old'],
                   pending_trial=dict(child_run_id='existing-child'),lineage=['retired-but-sealed'])
        original=copy.deepcopy(state)
        result=assert_bounded_controller_resume(old,new,state,budget_only=True)
        self.assertEqual(result['maximum_iterations'],dict(previous=5,current=30))
        self.assertEqual(result['preserved_candidate_count'],5)
        self.assertEqual(result['change_kind'],'execution_budget_only')
        self.assertEqual(state,original)
        self.assertIsNone(assert_bounded_controller_resume(old,new,None,budget_only=True)['preserved_candidate_count'])
        for section,key in (('source','velocity'),('source','clock'),('target','y'),('target','k'),
                            ('geometry','gap'),('field','operator'),('numerics','grid'),('numerics','step'),('numerics','quality')):
            with self.subTest(section=section,key=key):
                wrong=copy.deepcopy(new);wrong[section][key]='changed'
                with self.assertRaises(ValueError):assert_bounded_controller_resume(old,wrong,state,budget_only=True)
        for key,value in (('advance_multiplier',.5),('damping_factor',1),('relative_step_cap',.02),
                          ('acceptance_tolerances',dict(phase=1)),('maximum_iterations',4),
                          ('maximum_iterations',5),('maximum_iterations',30.0),('maximum_iterations',True)):
            with self.subTest(key=key,value=value):
                wrong=copy.deepcopy(new);wrong['downstream_fixed_grid_workpoint_profile']['automatic_iteration'][key]=value
                with self.assertRaises(ValueError):assert_bounded_controller_resume(old,wrong,state,budget_only=True)
        for used in (-1,6,True,1.0):
            with self.subTest(used=used),self.assertRaises(ValueError):
                assert_bounded_controller_resume(old,new,dict(state,candidate_count=used),budget_only=True)
        wrong=copy.deepcopy(new)
        wrong['downstream_fixed_grid_workpoint_profile']['automatic_iteration'].pop('advance_multiplier')
        with self.assertRaises(ValueError):assert_bounded_controller_resume(old,wrong,state,budget_only=True)

    def test_clean_energy_prism_model_uses_energy_units_and_ignores_diagnostic_angle(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import CONVERGING_PRISM_ENERGY_RESIDUAL as energy_name
        base, p1, p2, contract, numerics = self.prism_preclosure_fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["active_stripe_axes"] = ["stripe_1_voltage_v"]
        target = {"mode": "converging_clean_phase_energy", "energy_tolerance_per_charge_v": .05234301827329357,
                  "slow_energy_reference_per_charge_v": 5.374387143093758}
        for index, trial in enumerate((base, p1, p2)):
            trial["materialization"].update(prism_handoff_target=copy.deepcopy(target))
            trial["materialization"]["stripe_biases_v"][1] = 0.
            trial["frozen_problem"]["targets"] = {"target_slow_turn_y_mm": 340.}
            stage = trial["observation"]["center_particle_prism_handoff_validation"]
            stage["first_clean_phase_state"] = {"position_mm": [0., 9., 0.], "velocity_mm_per_us": [0., 1.3, -40.],
                                                "t_us": 30., "event": "central_plane_directional__n1__minus_z"}
            stage["residuals"][energy_name] = -.37 if index != 2 else -1.37
            if index in (1, 2):
                axis, delta = (0, 10.) if index == 1 else (1, -10.)
                trial["materialization"]["prism_voltages_v"][axis] = base["materialization"]["prism_voltages_v"][axis]+delta
                trial["observation"]["prism_voltages_v"] = trial["materialization"]["prism_voltages_v"]
                if index == 1:
                    stage["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 2.
        decision = decide_prism_preclosure(base, p1, p2, contract, numerics)
        self.assertEqual(decision["status"], "proposed")
        self.assertEqual(decision["prism_residual_names"][1], energy_name)
        self.assertAlmostEqual(decision["physical_jacobian_rows"][1][1], .1)
        self.assertEqual(decision["next_voltages_v"][1], 0.)
        current = copy.deepcopy(base)
        current["materialization"]["prism_voltages_v"] = decision["next_voltages_v"][2:]
        current["observation"]["prism_voltages_v"] = current["materialization"]["prism_voltages_v"]
        residual = current["observation"]["center_particle_prism_handoff_validation"]["residuals"]
        shift = np.asarray(decision["applied_step_v"])[2:]
        predicted = np.array([1., -.37])+np.array(decision["physical_jacobian_rows"])@shift
        residual["P1_P2_positive_mirror_turn_y_mm"], residual[energy_name] = predicted.tolist()
        transported = decide_transported_prism_preclosure(current, decision, base, contract, numerics)
        self.assertEqual(transported["status"], "proposed")
        self.assertIn(energy_name, transported["predicted_physical_acceptance_residuals"])
        stage = base["observation"]["center_particle_prism_handoff_validation"]
        stage["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 0.
        stage["residuals"][energy_name] = 0.
        stage["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"] = 10.
        self.assertEqual(decide_prism_preclosure(base, None, None, contract, numerics)["status"], "stage_passed")
        p1["materialization"]["prism_handoff_target"]["slow_energy_reference_per_charge_v"] = 5.
        stage["residuals"][energy_name] = -.37
        with self.assertRaisesRegex(ValueError, "frozen prism_handoff_target"):
            decide_prism_preclosure(base, p1, p2, contract, numerics)

    def test_clean_energy_stripe_rechecks_prism_and_retains_all_four_acceptance_rows(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import CONVERGING_PRISM_ENERGY_RESIDUAL as energy_name
        baseline, s1, contract, numerics = self.single_stripe_fixtures()
        target = {"mode": "converging_clean_phase_energy", "energy_tolerance_per_charge_v": .05234301827329357,
                  "slow_energy_reference_per_charge_v": 5.374387143093758}
        for trial in (baseline, s1):
            trial["materialization"]["prism_handoff_target"] = copy.deepcopy(target)
            trial["frozen_problem"]["targets"] = {"target_slow_turn_y_mm": 340.}
            stage = trial["observation"]["center_particle_prism_handoff_validation"]
            stage["first_clean_phase_state"] = {"position_mm": [0., 9., 0.], "velocity_mm_per_us": [0., 1.3, -40.],
                                                "t_us": 30., "event": "central_plane_directional__n1__minus_z"}
            stage["residuals"][energy_name] = 0.
            stage["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"] = 10.
            trial["observation"]["center_particle_workpoint_validation"]["residuals"][energy_name] = 0.
        result = decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["next_voltages_v"][1], 0.)
        baseline["observation"]["center_particle_prism_handoff_validation"]["residuals"][energy_name] = .1
        self.assertEqual(decide_stripe_preclosure(baseline, s1, None, contract, numerics)["next_action"], "prism_preclosure")
        baseline["observation"]["center_particle_prism_handoff_validation"]["residuals"][energy_name] = 0.
        centre = baseline["observation"]["center_particle_workpoint_validation"]
        centre["residuals"]["Stripe_slow_turn_y_minus_L_mm"] = 0.
        centre["residuals"]["Stripe_target_phase_y_minus_origin_mm"] = 0.
        baseline["observation"]["status"] = "full_drift_observed"
        baseline["observation"]["return_topology"] = "exact_target_k_phase_return"
        baseline["observation"]["static_return_diagnostic"] = {"status": "detector_hit", "event_contract_ok": True}
        self.assertTrue(decide_stripe_preclosure(baseline, None, None, contract, numerics)["full_workpoint_qualified"])
        centre["residuals"][energy_name] = .1
        self.assertFalse(decide_stripe_preclosure(baseline, None, None, contract, numerics)["full_workpoint_qualified"])

    @staticmethod
    def prism_policy():
        return {"schema_version": 1, "role": "mrtof_prism_controller_policy",
                "scope": "future_prism_proposals",
                "prediction_error_fraction_of_acceptance_tolerance": .1,
                "trusted_advance_multiplier": 1.}

    def joint_ps_fixtures(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import CONVERGING_PRISM_ENERGY_RESIDUAL as energy_name
        baseline, _, contract, numerics = self.single_stripe_fixtures()
        profile = contract["downstream_fixed_grid_workpoint_profile"]
        profile["single_stripe_refinement_mode"] = "joint_ps_constrained"
        profile["automatic_iteration"]["advance_multiplier"] = 1.
        target = {"mode": "converging_clean_phase_energy", "energy_tolerance_per_charge_v": .05234301827329357,
                  "slow_energy_reference_per_charge_v": 5.374387143093758}
        baseline["materialization"]["prism_handoff_target"] = target
        baseline["frozen_problem"]["targets"] = {"target_slow_turn_y_mm": 340.}
        obs = baseline["observation"]
        obs["return_topology"] = "exact_target_k_phase_return"
        obs["status"] = "full_drift_observed"
        obs["static_return_diagnostic"] = {"status": "detector_hit", "event_contract_ok": True}
        p = obs["center_particle_prism_handoff_validation"]
        p["first_clean_phase_state"] = {"position_mm": [0., 9., 0.], "velocity_mm_per_us": [0., 1.3, -40.],
                                       "t_us": 30., "event": "central_plane_directional__n1__minus_z"}
        p["residuals"][energy_name] = 0.
        obs["center_particle_workpoint_validation"]["residuals"][energy_name] = 0.
        names = ["P1_P2_positive_mirror_turn_y_mm", energy_name,
                 "Stripe_slow_turn_y_minus_L_mm", "Stripe_target_phase_y_minus_origin_mm"]
        columns = np.asarray([[0., 1., 0.], [0., 0., .1], [10., 10., 0.], [10., 0., 10.]])
        samples = []
        for col, axis in enumerate((0, 2, 3)):
            sample = copy.deepcopy(baseline)
            step = .2
            if axis == 0:
                sample["materialization"]["stripe_biases_v"][0] += step
            else:
                sample["materialization"]["prism_voltages_v"][axis-2] += step
                sample["observation"]["prism_voltages_v"] = sample["materialization"]["prism_voltages_v"]
            values = np.asarray([0., 0., 1., 2.])+columns[:, col]*step
            centre = sample["observation"]["center_particle_workpoint_validation"]
            for name, value in zip(names, values, strict=True):
                centre["residuals"][name] = float(value)
                if name in names[:2]:
                    sample["observation"]["center_particle_prism_handoff_validation"]["residuals"][name] = float(value)
            samples.append(sample)
        numerics["compatibility_tolerance"] = 1e-8
        return baseline, samples, contract, numerics

    def test_joint_ps_fits_two_s_rows_with_original_prism_inequalities_and_grounded_s2(self):
        baseline, samples, contract, numerics = self.joint_ps_fixtures()
        missing = decide_stripe_preclosure(baseline, None, None, contract, numerics)
        self.assertEqual(missing["required_axes"], [0, 2, 3])
        result = decide_preclosure_stage("stripe_preclosure", baseline, samples[0], None, contract, numerics,
                                         joint_prism_trials=samples[1:])
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["joint_active_axes"], [0, 2, 3])
        self.assertEqual(np.asarray(result["joint_physical_jacobian_columns"]).shape, (4, 3))
        self.assertEqual(result["next_voltages_v"][1], 0.)
        self.assertGreater(np.max(np.abs(result["applied_step_v"][2:])), 0.)
        predicted = list(result["predicted_physical_acceptance_residuals"].values())
        self.assertLessEqual(abs(predicted[0]), .1+1e-8)
        self.assertLessEqual(abs(predicted[1]), .05234301827329357+1e-8)
        np.testing.assert_allclose(predicted[2:], 0., atol=1e-8)
        self.assertFalse(result["full_workpoint_qualified"])
        # Absent mode retains the original single-S1 branch and irreducible pair.
        del contract["downstream_fixed_grid_workpoint_profile"]["single_stripe_refinement_mode"]
        single = decide_stripe_preclosure(baseline, samples[0], None, contract, numerics)
        self.assertGreater(max(abs(x) for x in single["predicted_s_residuals_mm"]), .1)

    def test_joint_ps_rejects_missing_branch_and_wrong_scheme_and_respects_maximum_step(self):
        baseline, samples, contract, numerics = self.joint_ps_fixtures()
        samples[1]["observation"]["static_return_diagnostic"]["status"] = "detector_not_observed"
        missing = decide_stripe_preclosure(baseline, samples[0], None, contract, numerics,
                                           prism_1_trial=samples[1], prism_2_trial=samples[2])
        self.assertEqual(missing["required_axes"], [2])
        baseline, samples, contract, numerics = self.joint_ps_fixtures()
        numerics["maximum_abs_step_v"] = [.001, 0., .001, .001]
        result = decide_stripe_preclosure(baseline, samples[0], None, contract, numerics,
                                          prism_1_trial=samples[1], prism_2_trial=samples[2])
        if result["status"] == "proposed":
            self.assertLessEqual(max(abs(x) for x in result["applied_step_v"]), .001+1e-12)
        else:
            self.assertEqual(result["status"], "residual_stagnation")
        baseline["materialization"]["prism_handoff_target"] = None
        with self.assertRaisesRegex(ValueError, "joint P/S refinement"):
            decide_stripe_preclosure(baseline, samples[0], None, contract, numerics)

    def test_joint_stage_cli_loads_s1_p1_p2_and_failed_lp_never_qualifies(self):
        from types import SimpleNamespace
        baseline, samples, contract, numerics = self.joint_ps_fixtures()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root/name for name in ("base.json", "s1.json", "p1.json", "p2.json")]
            trials = dict(zip(paths, (baseline, *samples), strict=True))
            output = root/"decision.json"
            argv = ["stage", "--control-stage", "stripe_preclosure", "--child-manifest", str(paths[0]),
                    "--s1-child-manifest", str(paths[1]), "--p1-child-manifest", str(paths[2]),
                    "--p2-child-manifest", str(paths[3]), "--contract", str(root/"contract.json"), "--output", str(output)]
            module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
            with patch("sys.argv", argv), patch(module+"._load", return_value=contract), \
                    patch(module+"._load_stage_trial", side_effect=lambda path, _replay: trials[path]), \
                    patch(module+".resolve_numerics", return_value=numerics):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.read_text())["joint_active_axes"], [0, 2, 3])
        with patch(module+".linprog", return_value=SimpleNamespace(success=False, status=2, message="infeasible")):
            failed = decide_stripe_preclosure(baseline, samples[0], None, contract, numerics,
                                              prism_1_trial=samples[1], prism_2_trial=samples[2])
        self.assertEqual(failed["terminal_reason"], "solver_failure")
        self.assertFalse(failed["full_workpoint_qualified"])

    def test_prism_policy_is_explicit_validated_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for change in ({"scope": "all_stages"}, {"trusted_advance_multiplier": 2.},
                           {"prediction_error_fraction_of_acceptance_tolerance": float("nan")},
                           {"medium_maximum_scaled_residual": 3.}):
                path.write_text(json.dumps({**self.prism_policy(), **change}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    resolve_prism_controller_policy(path)
            path.write_text(json.dumps(self.prism_policy()), encoding="utf-8")
            policy = resolve_prism_controller_policy(path)
            self.assertEqual(policy["path"], str(path.resolve()))
            self.assertEqual(len(policy["sha256"]), 64)

    def test_prism_policy_provisional_and_trusted_steps_preserve_measured_extent(self):
        baseline, current, prior, contract, numerics = self.transported_prism_fixtures()
        original = copy.deepcopy(contract)
        policy = self.prism_policy()
        previous = list(prior["physical_acceptance_residuals"].values())
        shift = [a-b for a,b in zip(current["materialization"]["prism_voltages_v"],
                                    prior["voltages_v"][2:])]
        predicted = [r+sum(j*d for j,d in zip(row, shift))
                     for r,row in zip(previous, prior["physical_jacobian_rows"])]
        stage = current["observation"]["center_particle_prism_handoff_validation"]["residuals"]
        stage["P1_P2_positive_mirror_turn_y_mm"] = predicted[0]
        ratio = prior["observation_record"]["target_low_field_tangent_ratio_vy_over_vz"]
        stage["P1_P2_P2_shield_low_field_signed_vy_over_vz"] = math.tan(
            math.atan(ratio)+math.radians(predicted[1]))-ratio
        trusted = decide_transported_prism_preclosure(current, prior, baseline, contract, numerics,
                                                      controller_policy=policy)
        self.assertEqual(trusted["prediction_quality"]["status"], "trusted")
        self.assertEqual(trusted["resolved_advance_multiplier"], 1.)
        self.assertEqual(trusted["relative_trust_tier"], .01)
        for value, lo, hi in zip(trusted["next_voltages_v"][2:], *trusted["measured_model_bounds_v"]):
            self.assertLessEqual(lo, value)
            self.assertLessEqual(value, hi)
        self.assertEqual(contract, original)
        stage["P1_P2_positive_mirror_turn_y_mm"] -= .1
        bad = decide_transported_prism_preclosure(current, prior, baseline, contract, numerics,
                                                  controller_policy=policy)
        self.assertEqual(bad["status"], "needs_stencil")
        self.assertEqual(bad["model_refresh_reason"], "P_model_prediction_error")

    def test_prism_policy_cli_does_not_change_contract_or_stripe(self):
        baseline, p1, p2, contract, numerics = self.prism_preclosure_fixtures()
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c, p, out = root / "contract.json", root / "policy.json", root / "decision.json"
            c.write_text(json.dumps(contract), encoding="utf-8")
            p.write_text(json.dumps(self.prism_policy()), encoding="utf-8")
            original = c.read_bytes()
            argv = ["stage", "--control-stage", "prism_preclosure", "--child-manifest", str(root / "base.json"),
                    "--p1-child-manifest", str(root / "p1.json"), "--p2-child-manifest", str(root / "p2.json"),
                    "--contract", str(c), "--prism-controller-policy", str(p), "--output", str(out)]
            with patch("sys.argv", argv), patch(module+"._load_stage_trial", side_effect=[baseline,p1,p2]), \
                    patch(module+".resolve_numerics", return_value=numerics), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            result = json.loads(out.read_text())
            self.assertEqual(result["prediction_quality"]["status"], "provisional_new_measured_model")
            self.assertEqual(result["resolved_advance_multiplier"], .5)
            self.assertEqual(c.read_bytes(), original)
            self.assertEqual(result["next_voltages_v"][:2], baseline["materialization"]["stripe_biases_v"])
            argv[argv.index("prism_preclosure")] = "stripe_preclosure"
            with patch("sys.argv", argv), patch(module+"._load_stage_trial", return_value=baseline), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main()

    def test_legacy_stage_loader_derives_sealed_015_016_signatures_without_rewriting(self):
        from common.contracts.write_run_manifest import file_record
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        baseline = self.stripe_preclosure_fixtures()[0]
        with tempfile.TemporaryDirectory() as directory:
            for index, left, right, direction, slow_time, slow_y, slow_z, left_vy, right_vy in (
                (15, 24, 25, -1, 382.323150744, 364.434982803, 73.1161034471, .0913865473007, .00467067481175),
                (16, 25, 26, 1, 396.913639187, 365.225620767, -78.5060071164, .0190441613963, -.0616823620562),
            ):
                root = Path(directory) / str(index)
                root.mkdir()
                def save(name, value):
                    path = root / name
                    path.write_text(json.dumps(value), encoding="utf-8")
                    return path
                obs = copy.deepcopy(baseline["observation"])
                stage = obs["center_particle_workpoint_validation"]
                stage["residuals"]["Stripe_slow_turn_y_minus_L_mm"] = slow_y - 340.
                material = {**baseline["materialization"], "target_slow_turn_y_mm": 340.}
                log = root / "native_two_prism_flight.log"
                def line(kind, time, **values):
                    return "MRTOF_EVENT " + kind + " " + " ".join(
                        f"{k}={v}" for k, v in dict(ion=1, t_us=time, x_mm=0, y_mm=slow_y,
                        z_mm=slow_z, vx_mm_us=0, vy_mm_us=1, vz_mm_us=0, **values).items())
                # Existing parser receives actual first-zero coordinates and half-cycle identities.
                lines = [line("drift_phase_origin", 23.),
                         line("fast_turn", slow_time - 5., n=left),
                         line("slow_turn", slow_time, n=1),
                         line("central_plane_directional", slow_time + .5, n=right, direction_z=direction),
                         line("fast_turn", slow_time + 5., n=right)]
                lines[1] = lines[1].replace("vy_mm_us=1", f"vy_mm_us={left_vy}")
                lines[4] = lines[4].replace("vy_mm_us=1", f"vy_mm_us={right_vy}")
                log.write_text("\n".join(lines), encoding="utf-8")
                observation_path = save("observation.json", obs)
                records = {"two_prism_trial_observation.json": file_record(observation_path),
                           "two_prism_trial_materialization.json": file_record(save("material.json", material))}
                manifest = save("manifest.json", {"outputs": [file_record(log)]})
                original_bytes = observation_path.read_bytes()
                with patch(module + "._trial", return_value={"consumer_projection": {"records": records}}):
                    loaded = _load_stage_trial(manifest)
                    signature = loaded["observation"]["center_particle_workpoint_validation"]["first_slow_turn_signature"]
                    self.assertEqual(signature["status"], "observed")
                    self.assertEqual(signature["phase_key"]["fast_turn_numbers"], [left, right])
                    self.assertEqual(signature["phase_key"]["direction_z"], direction)
                    self.assertEqual(signature["first_slow_turn"]["y_mm"], slow_y)
                    self.assertEqual(observation_path.read_bytes(), original_bytes)
                    stage["residuals"]["Stripe_slow_turn_y_minus_L_mm"] += 1.
                    save("observation.json", obs)
                    with self.assertRaisesRegex(ValueError, "value differs"):
                        _load_stage_trial(manifest)

    def test_registered_replay_overlays_only_stage_evidence_for_anchor_and_s1(self):
        from common.contracts.write_run_manifest import file_record
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def save(name, value):
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                return path
            originals = {}
            inputs, outputs = {}, []
            config = save("config.json", {"parameters": {"source_runs": {"anchor": "anchor", "s1": "s1"}}})
            for label in ("anchor", "s1", "s2"):
                manifest = save(label + "_manifest.json", {"run_id": label})
                material = save(label + "_material.json", {"volts": label})
                observation = save(label + "_old.json", {
                    "status": "collision", "termination_diagnostic": {"physical_collision": True},
                    "center_particle_workpoint_validation": {"status": "incomplete"}})
                originals[manifest] = {"manifest_sha256": file_record(manifest)["sha256"],
                    "frozen_problem": {"field": "unchanged"}, "consumer_projection": {"records": {
                        "two_prism_trial_observation.json": file_record(observation),
                        "two_prism_trial_materialization.json": file_record(material)}}}
                if label != "s2":
                    inputs[label + "_manifest"] = file_record(manifest)
                    inputs[label + "_materialization"] = file_record(material)
                    outputs.append(file_record(save(label + "_observation.json", {
                        "status": "must_not_overlay", "termination_diagnostic": {},
                        "center_particle_stripe_stage_validation": {"status": "incomplete", "reason": "explicit"}
                        if label == "s1" else {"status": "observed", "particle_id": 1},
                        "center_particle_prism_handoff_validation": {"status": "observed", "particle_id": 1}})))
            replay = save("replay.json", {"status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "prism_handoff_log_reanalysis", "run_config": file_record(config),
                "inputs": inputs, "outputs": outputs})
            with patch(module + "._trial", side_effect=lambda path, **kw: copy.deepcopy(originals[path])):
                for label in ("anchor", "s1"):
                    result = _load_stage_trial(root / (label + "_manifest.json"), replay)
                    self.assertEqual(result["observation"]["status"], "collision")
                    self.assertTrue(result["observation"]["termination_diagnostic"]["physical_collision"])
                    self.assertEqual(result["observation"]["center_particle_workpoint_validation"]["status"], "incomplete")
                    self.assertIn("center_particle_stripe_stage_validation", result["observation"])
                    self.assertEqual(result["replayed_stage_fields"], [
                        "center_particle_prism_handoff_validation", "center_particle_stripe_stage_validation"])
                    self.assertEqual(result["frozen_problem"], {"field": "unchanged"})
                self.assertEqual(_load_stage_trial(root / "s1_manifest.json", replay)["observation"][
                    "center_particle_stripe_stage_validation"]["status"], "incomplete")
                with patch(module + ".verify_record", wraps=__import__(module, fromlist=["verify_record"]).verify_record) as verify:
                    result = _load_stage_trial(root / "s2_manifest.json", replay)
                    self.assertNotIn("center_particle_stripe_stage_validation", result["observation"])
                    self.assertEqual(verify.call_count, 1)  # Only the replay's source-list authority.
                originals[root / "s1_manifest.json"]["manifest_sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "original trial evidence"):
                    _load_stage_trial(root / "s1_manifest.json", replay)
                originals[root / "s1_manifest.json"]["manifest_sha256"] = inputs["s1_manifest"]["sha256"]
                originals[root / "s1_manifest.json"]["consumer_projection"]["records"][
                    "two_prism_trial_materialization.json"]["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "original trial evidence"):
                    _load_stage_trial(root / "s1_manifest.json", replay)

    def stripe_preclosure_fixtures(self):
        baseline, _, _, contract, numerics = self.prism_preclosure_fixtures()
        names = self.fixtures()[0]["residual_names"]
        def trial(axis=None):
            sample = copy.deepcopy(baseline)
            obs = sample["observation"]
            values = [0., 0., 1., 2.]
            if axis is not None:
                sample["materialization"]["stripe_biases_v"][axis] += 0.1
                values[2 + axis] += 0.1
            obs["residuals"] = dict(zip(names, values, strict=True))
            obs["center_particle_prism_handoff_validation"]["residuals"] = dict(zip(names[:2], values[:2], strict=True))
            obs["center_particle_workpoint_validation"] = {
                "status": "observed", "particle_id": 1, "residuals": copy.deepcopy(obs["residuals"])}
            obs["termination_diagnostic"] = {"physical_collision": False}
            obs["static_return_diagnostic"] = {"status": "detector_not_observed", "event_contract_ok": False}
            return sample
        return trial(), trial(0), trial(1), contract, numerics

    def single_stripe_fixtures(self):
        baseline, s1, _, contract, numerics = self.stripe_preclosure_fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["active_stripe_axes"] = ["stripe_1_voltage_v"]
        numerics["lower_bounds_v"][1] = numerics["upper_bounds_v"][1] = 0.0
        for trial in (baseline, s1):
            trial["materialization"]["stripe_biases_v"][1] = 0.0
            trial["observation"]["center_particle_workpoint_validation"]["residuals"] = trial["observation"]["residuals"]
        names = list(s1["observation"]["center_particle_workpoint_validation"]["residuals"])
        s1["observation"]["center_particle_workpoint_validation"]["residuals"][names[3]] = 2.2
        return baseline, s1, contract, numerics

    def test_single_stripe_proposes_bounded_rectangular_step_and_keeps_s2_grounded(self):
        baseline, s1, contract, numerics = self.single_stripe_fixtures()
        missing = decide_stripe_preclosure(baseline, None, None, contract, numerics)
        self.assertEqual(missing["required_axes"], [0])
        result = decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["active_stripe_axes"], ["stripe_1_voltage_v"])
        self.assertEqual(result["scaled_rank"], 1)
        self.assertEqual(result["model_solver"], "scaled_rectangular_least_squares")
        self.assertEqual(np.asarray(result["local_s_physical_jacobian_columns"]).shape, (4, 1))
        self.assertEqual(result["next_voltages_v"][1], 0.0)
        self.assertEqual(result["applied_step_v"][1:], [0., 0., 0.])
        self.assertFalse(result["full_workpoint_qualified"])
        delta = result["applied_step_v"][0]
        np.testing.assert_allclose(result["predicted_s_residuals_mm"], [1.+delta, 2.+2.*delta])
        self.assertLessEqual(abs(delta), .01 * abs(result["voltages_v"][0]))

    def test_single_stripe_retains_irreducible_residual_and_requires_both_to_pass(self):
        baseline, s1, contract, numerics = self.single_stripe_fixtures()
        name = "Stripe_target_phase_y_minus_origin_mm"
        s1["observation"]["center_particle_workpoint_validation"]["residuals"][name] = 2.0
        result = decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        self.assertEqual(result["predicted_s_residuals_mm"][1], 2.0)
        self.assertFalse(result["full_workpoint_qualified"])
        baseline["observation"]["center_particle_workpoint_validation"]["residuals"]["Stripe_slow_turn_y_minus_L_mm"] = 0.
        self.assertFalse(decide_stripe_preclosure(baseline, s1, None, contract, numerics)["full_workpoint_qualified"])
        baseline["observation"]["center_particle_workpoint_validation"]["residuals"][name] = 0.
        baseline["observation"]["status"] = "full_drift_observed"
        baseline["observation"]["return_topology"] = "exact_target_k_phase_return"
        baseline["observation"]["static_return_diagnostic"] = {"status": "detector_hit", "event_contract_ok": True}
        self.assertTrue(decide_stripe_preclosure(baseline, None, None, contract, numerics)["full_workpoint_qualified"])
        # No useful active response is a solver failure, never fictitious closure.
        baseline, s1, contract, numerics = self.single_stripe_fixtures()
        s1["observation"]["center_particle_workpoint_validation"]["residuals"] = copy.deepcopy(
            baseline["observation"]["center_particle_workpoint_validation"]["residuals"])
        s1["observation"]["residuals"] = s1["observation"]["center_particle_workpoint_validation"]["residuals"]
        self.assertEqual(decide_stripe_preclosure(baseline, s1, None, contract, numerics)["terminal_reason"], "solver_failure")

    def test_single_stripe_rejects_inactive_change_and_missing_events(self):
        baseline, s1, contract, numerics = self.single_stripe_fixtures()
        with self.assertRaisesRegex(ValueError, "inactive S2"):
            decide_stripe_preclosure(baseline, s1, s1, contract, numerics)
        baseline["materialization"]["stripe_biases_v"][1] = .01
        with self.assertRaisesRegex(ValueError, "inactive S2"):
            decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        baseline["materialization"]["stripe_biases_v"][1] = 0.
        s1["materialization"]["stripe_biases_v"][1] = .001
        with self.assertRaisesRegex(ValueError, "named voltage axis"):
            decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        s1["materialization"]["stripe_biases_v"][1] = 0.
        s1["observation"]["center_particle_workpoint_validation"]["status"] = "incomplete"
        self.assertEqual(decide_stripe_preclosure(baseline, s1, None, contract, numerics)["required_axes"], [0])

    def test_single_stripe_respects_bound_and_cannot_enter_dual_recovery(self):
        baseline, s1, contract, numerics = self.single_stripe_fixtures()
        numerics["lower_bounds_v"][0] = baseline["materialization"]["stripe_biases_v"][0]
        result = decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        self.assertEqual(result["status"], "voltage_bound")
        prior, observation, materialization, _ = self.fixtures()
        with self.assertRaisesRegex(ValueError, "staged controller"):
            decide_iteration(prior, observation, materialization, contract, [], 1)

    def controlled_center_stencil_fixtures(self):
        baseline, s1, _, contract, numerics = self.stripe_preclosure_fixtures()
        for count, trial in ((13, baseline), (1, s1)):
            trial["materialization"]["inputs"] = {
                "contract_sha256": str(count), "reviewed_contract_sha256": str(count),
                "accelerator_receipt_sha256": "oa"}
            trial["materialization"]["source_selection"] = {
                "role": "contiguous_frozen_source_diagnostic_selection",
                "source_receipt_sha256": "mother", "parent_particle_states_sha256": "states",
                "parent_particle_count": 100, "particle_id_max": count}
            trial["frozen_problem"]["inputs"] = {
                "trajectory_physics_contract_sha256": "science",
                "reviewed_physics_contract_sha256": "science"}
            trial["frozen_problem"]["source_center_projection"] = {
                "source_release_state": {"position_mm": [0., -56., 32.],
                    "velocity_mm_per_us": [0., 1.4, 0.], "time_us": 0.,
                    "particle_mass_th": 524., "charge_state": 1},
                "frame_id": "frame", "clock_basis": "common_birth"}
        return baseline, s1, contract, numerics

    def test_controlled_n13_center_and_same_mother_n1_use_science_identity(self):
        baseline, s1, contract, numerics = self.controlled_center_stencil_fixtures()
        result = decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        self.assertEqual(result["status"], "needs_stencil")
        self.assertEqual(result["required_axes"], [1])
        self.assertFalse(result["stencil_rejections"])

    def test_controlled_same_center_from_different_mothers_keeps_science_identity(self):
        baseline, s1, contract, numerics = self.controlled_center_stencil_fixtures()
        s1["materialization"]["source_selection"].update(
            source_receipt_sha256="other-mother", parent_particle_states_sha256="other-states")
        result = decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        self.assertEqual(result["status"], "needs_stencil")
        self.assertFalse(result["stencil_rejections"])

    def test_controlled_center_stencil_still_rejects_oa_and_science_changes(self):
        mutations = (
            lambda t: t["materialization"]["inputs"].update(accelerator_receipt_sha256="other"),
            lambda t: t["frozen_problem"]["inputs"].update(reviewed_physics_contract_sha256="other"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                baseline, s1, contract, numerics = self.controlled_center_stencil_fixtures()
                mutate(s1)
                with self.assertRaisesRegex(ValueError, "frozen"):
                    decide_stripe_preclosure(baseline, s1, None, contract, numerics)
        for field, value in (("position_mm", [0., -55., 32.]),
                             ("velocity_mm_per_us", [0., 1.5, 0.]), ("time_us", 1.),
                             ("particle_mass_th", 525.), ("charge_state", 2)):
            with self.subTest(field=field):
                baseline, s1, contract, numerics = self.controlled_center_stencil_fixtures()
                s1["frozen_problem"]["source_center_projection"]["source_release_state"][field] = value
                with self.assertRaisesRegex(ValueError, "frozen"):
                    decide_stripe_preclosure(baseline, s1, None, contract, numerics)

    def test_existing_p_pass_and_s_events_advance_without_another_flight(self):
        baseline, _, _, contract, numerics = self.stripe_preclosure_fixtures()
        result = decide_preclosure_stage("prism_preclosure", baseline, None, None, contract, numerics)
        self.assertEqual(result["next_action"], "stripe_preclosure")
        self.assertFalse(result["full_workpoint_qualified"])

    def test_s_stage_corrects_real_events_despite_failed_full_return_and_keeps_p(self):
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["next_voltages_v"][2:], baseline["materialization"]["prism_voltages_v"])
        self.assertEqual(len(result["local_s_physical_jacobian_columns"]), 4)
        self.assertTrue(all(len(row) == 2 for row in result["local_s_physical_jacobian_columns"]))
        for old, change in zip(result["voltages_v"][:2], result["applied_step_v"][:2], strict=True):
            self.assertLessEqual(abs(change), .01 * abs(old) + 1e-12)
        self.assertFalse(result["full_workpoint_qualified"])

    def test_s_stage_rejects_evidenced_first_zero_phase_jump_only(self):
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        key = {"fast_turn_numbers": [24, 25], "direction_z": -1, "sampled_vy_signs": [1, 1]}
        for trial in (baseline, s1, s2):
            trial["observation"]["center_particle_workpoint_validation"]["first_slow_turn_signature"] = {
                "status": "observed", "phase_key": copy.deepcopy(key)}
        stable = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(stable["status"], "proposed")
        self.assertEqual(stable["slow_turn_signature_compatibility"]["status"], "matched")
        s1["observation"]["center_particle_workpoint_validation"]["first_slow_turn_signature"]["phase_key"]["sampled_vy_signs"] = [1, -1]
        same_half_cycle = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(same_half_cycle["status"], "proposed")
        self.assertEqual(same_half_cycle["slow_turn_signature_compatibility"]["status"], "matched")
        s1["observation"]["center_particle_workpoint_validation"]["first_slow_turn_signature"]["phase_key"] = {
            "fast_turn_numbers": [25, 26], "direction_z": 1, "sampled_vy_signs": [1, -1]}
        jumped = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(jumped["status"], "needs_stencil")
        self.assertEqual(jumped["required_axes"], [0])
        self.assertEqual(jumped["slow_turn_signature_compatibility"]["axes"], {"0": "mismatch", "1": "matched"})
        self.assertIn("local phase/direction", jumped["stencil_rejections"]["0"])
        self.assertNotIn("local_s_physical_jacobian_columns", jumped)
        del s1["observation"]["center_particle_workpoint_validation"]["first_slow_turn_signature"]
        legacy = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(legacy["status"], "proposed")
        self.assertEqual(legacy["slow_turn_signature_compatibility"]["status"], "unknown")
        self.assertFalse(legacy["full_workpoint_qualified"])
        s1["observation"]["center_particle_workpoint_validation"]["first_slow_turn_signature"] = {
            "status": "observed", "phase_key": {**key, "direction_z": 0}}
        with self.assertRaisesRegex(ValueError, "phase/direction"):
            decide_stripe_preclosure(baseline, s1, s2, contract, numerics)

    def test_s_stage_legacy_anchor_signature_is_explicit_unknown(self):
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["slow_turn_signature_compatibility"]["status"], "unknown")
        self.assertEqual(result["observation_record"]["first_slow_turn_signature"]["status"], "unknown")

    def test_stage_requests_only_missing_or_physically_rejected_columns(self):
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        s2["observation"]["center_particle_workpoint_validation"] = {"status": "incomplete", "reason": "no target K"}
        result = decide_preclosure_stage("stripe_preclosure", baseline, s1, s2, contract, numerics)
        self.assertEqual(result["required_axes"], [1])
        self.assertEqual(result["stencil_rejections"], {"1": "no target K"})
        p, _, _, contract, numerics = self.prism_preclosure_fixtures()
        result = decide_preclosure_stage("prism_preclosure", p, None, None, contract, numerics)
        self.assertEqual(result["required_axes"], [2, 3])

    def test_s_stencil_rejects_only_column_with_p_outside_tolerance(self):
        for axis, name, value in (
            (0, "P1_P2_positive_mirror_turn_y_mm", 10.),
            (1, "P1_P2_P2_shield_low_field_signed_vy_over_vz", .1),
        ):
            with self.subTest(axis=axis):
                baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
                observation = (s1, s2)[axis]["observation"]
                observation["center_particle_prism_handoff_validation"]["residuals"][name] = value
                observation["center_particle_workpoint_validation"]["residuals"][name] = value
                observation["residuals"][name] = value
                result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
                self.assertEqual(result["status"], "needs_stencil")
                self.assertEqual(result["required_axes"], [axis])
                self.assertEqual(result["stencil_rejections"], {
                    str(axis): "S stencil P handoff is not within acceptance tolerances"})
                self.assertFalse(result["full_workpoint_qualified"])

    def test_s_stencil_keeps_current_p_pass_despite_later_topology_rejection(self):
        import math

        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"][
            "acceptance_tolerances"]["P1_P2_positive_mirror_turn_y_mm"] = .1
        ratio = s1["materialization"]["target_low_field_tangent_ratio_vy_over_vz"]
        residuals = {
            "P1_P2_positive_mirror_turn_y_mm": -.0203824941716,
            "P1_P2_P2_shield_low_field_signed_vy_over_vz":
                math.tan(math.atan(ratio) + math.radians(-.009175320260217697)) - ratio,
        }
        observation = s1["observation"]
        for stage in ("center_particle_prism_handoff_validation", "center_particle_workpoint_validation"):
            observation[stage]["residuals"].update(residuals)
        observation["residuals"].update(residuals)
        observation["center_particle_stripe_stage_validation"] = copy.deepcopy(
            observation["center_particle_workpoint_validation"])
        observation["center_particle_workpoint_validation"] = {"status": "incomplete"}
        observation["termination_diagnostic"] = {
            "physical_collision": False, "kind": "programmatic_topology_rejection",
            "reason": "accelerator_reentry_after_safe_exit"}
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertFalse(result["full_workpoint_qualified"])

    def test_explicit_completed_s_stage_survives_downstream_collision_without_qualification(self):
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        for sample in (baseline, s1, s2):
            obs = sample["observation"]
            obs["center_particle_stripe_stage_validation"] = copy.deepcopy(obs["center_particle_workpoint_validation"])
            obs["center_particle_workpoint_validation"] = {"status": "incomplete", "reason": "later collision"}
            obs["residuals"] = None
            obs["termination_diagnostic"] = {"physical_collision": True}
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertFalse(result["full_workpoint_qualified"])
        s1["observation"]["center_particle_stripe_stage_validation"]["status"] = "incomplete"
        s1["observation"]["center_particle_workpoint_validation"] = copy.deepcopy(s2["observation"]["center_particle_stripe_stage_validation"])
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["required_axes"], [0])
        for name in baseline["observation"]["center_particle_stripe_stage_validation"]["residuals"]:
            baseline["observation"]["center_particle_stripe_stage_validation"]["residuals"][name] = 0.
        result = decide_stripe_preclosure(baseline, None, None, contract, numerics)
        self.assertFalse(result["full_workpoint_qualified"])
        self.assertEqual(result["terminal_reason"], "collision_or_invalid_topology")

    def test_s_stage_rejects_other_p_anchor_and_changed_mesh_source(self):
        for kind in ("p", "mesh", "source"):
            baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
            if kind == "p":
                s2["materialization"]["prism_voltages_v"][0] += 1.
            else:
                s2["frozen_problem"][kind] = "changed"
            with self.assertRaises(ValueError):
                decide_stripe_preclosure(baseline, s1, s2, contract, numerics)

    def test_s_stage_requires_controlled_centre_not_top_level_only(self):
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        baseline["observation"]["center_particle_workpoint_validation"]["status"] = "incomplete"
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["terminal_reason"], "missing_target_phase")
        self.assertFalse(result["full_workpoint_qualified"])
        baseline["observation"]["termination_diagnostic"]["physical_collision"] = True
        result = decide_stripe_preclosure(baseline, s1, s2, contract, numerics)
        self.assertEqual(result["terminal_reason"], "collision_or_invalid_topology")
        baseline["observation"]["center_particle_workpoint_validation"]["status"] = "observed"
        baseline["observation"]["center_particle_workpoint_validation"]["residuals"][
            "Stripe_slow_turn_y_minus_L_mm"] = float("nan")
        with self.assertRaises(ValueError):
            decide_stripe_preclosure(baseline, s1, s2, contract, numerics)

    def test_s_pass_does_not_qualify_failed_return_but_real_full_pass_does(self):
        baseline, _, _, contract, numerics = self.stripe_preclosure_fixtures()
        obs = baseline["observation"]
        for name in self.fixtures()[0]["residual_names"][2:]:
            obs["residuals"][name] = 0.
            obs["center_particle_workpoint_validation"]["residuals"][name] = 0.
        result = decide_stripe_preclosure(baseline, None, None, contract, numerics)
        self.assertEqual(result["terminal_reason"], "collision_or_invalid_topology")
        self.assertFalse(result["full_workpoint_qualified"])
        obs.update(status="full_drift_observed", return_topology="exact_target_k_phase_return",
                   static_return_diagnostic={"status": "detector_hit", "event_contract_ok": True})
        result = decide_stripe_preclosure(baseline, None, None, contract, numerics)
        self.assertEqual(result["terminal_reason"], "success")
        self.assertTrue(result["full_workpoint_qualified"])
        self.assertIn("physical_acceptance_residuals", result["observation_record"])

    def test_stage_cli_uses_named_manifest_and_compiled_numerics(self):
        baseline, _, _, contract, numerics = self.stripe_preclosure_fixtures()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            contract_path, output = path / "contract.json", path / "output.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            argv = ["stage", "--control-stage", "stripe_preclosure", "--child-manifest", str(path / "trial.json"),
                    "--contract", str(contract_path), "--output", str(output)]
            module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
            with patch("sys.argv", argv), patch(module + "._load_stage_trial", return_value=baseline), \
                    patch(module + ".resolve_numerics", return_value=numerics), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["required_axes"], [0, 1])
            self.assertEqual(result["replayed_stage_axes"], [])
            self.assertEqual(result["resolved_numerics"], numerics)
            self.assertEqual(result["backtrack_multiplier"], .5)

    def test_stage_cli_identifies_only_replayed_s_column(self):
        baseline, s1, _, contract, numerics = self.stripe_preclosure_fixtures()
        s1["replayed_stage_fields"] = ["center_particle_stripe_stage_validation"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            contract_path, output = path / "contract.json", path / "output.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            argv = ["stage", "--control-stage", "stripe_preclosure", "--child-manifest", str(path / "trial.json"),
                    "--s1-child-manifest", str(path / "s1.json"), "--contract", str(contract_path), "--output", str(output)]
            module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
            with patch("sys.argv", argv), patch(module + "._load_stage_trial", side_effect=[baseline, s1]), \
                    patch(module + ".resolve_numerics", return_value=numerics), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["required_axes"], [1])
            self.assertEqual(result["replayed_stage_axes"], [0])

    def prism_preclosure_fixtures(self):
        prior, _, materialization, contract = self.fixtures()
        contract["prism_transport"] = {"energy_partition": {
            "drift_kinetic_energy_ev": 5.0, "fast_reflection_kinetic_energy_ev": 4000.0}}
        contract["dual_stripe_l0"] = {
            "manufactured_design_abs_drift_length_L_mm": 400.0,
            "determination_numerics": {"relative_singular_value_rank_tolerance": 1e-12}}
        materialization = copy.deepcopy(materialization)
        materialization.update(
            inputs={}, target_positive_mirror_turn_y_mm=0.0,
            p2_low_field_reference_section={"identity": "fixed_reference"})
        def trial(delta, residual):
            receipt = copy.deepcopy(materialization)
            receipt["prism_voltages_v"] = [
                receipt["prism_voltages_v"][i] + delta[i] for i in range(2)]
            stage = {
                "status": "observed", "particle_id": 1,
                "residuals": dict(zip((
                    "P1_P2_positive_mirror_turn_y_mm",
                    "P1_P2_P2_shield_low_field_signed_vy_over_vz"), residual, strict=True)),
                "p2_low_field_reference_state": {
                    "position_mm": [0., 0., 20.], "velocity_mm_per_us": [0., 1., 2.]},
                "positive_mirror_turn_state": {
                    "position_mm": [0., residual[0], 280.], "velocity_mm_per_us": [0., 1., 0.]}}
            return {"observation": {
                "status": "collided_after_prism", "residuals": {},
                "prism_voltages_v": receipt["prism_voltages_v"],
                "center_particle_prism_handoff_validation": stage},
                "materialization": receipt,
                "frozen_problem": {"geometry": "g", "mesh": "m", "source": "s", "clock": 0}}
        return (trial([0., 0.], [1., .002]),
                trial([1., 0.], [1.1, .002]),
                trial([0., -1.], [1., .001]), contract, prior["resolved_numerics"])

    def test_partial_p_preclosure_is_bounded_and_keeps_s_and_full_state(self):
        baseline, p1, p2, contract, numerics = self.prism_preclosure_fixtures()
        original = copy.deepcopy(baseline)
        result = decide_prism_preclosure(baseline, p1, p2, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["next_voltages_v"][:2], baseline["materialization"]["stripe_biases_v"])
        self.assertEqual(baseline, original)
        self.assertFalse(result["full_workpoint_qualified"])
        self.assertLessEqual(max(abs(v) for v in result["applied_step_v"][2:]),
                             max(abs(v) for v in result["voltages_v"][2:]) * .01)

    def transported_prism_fixtures(self):
        baseline, p1, p2, contract, numerics = self.prism_preclosure_fixtures()
        for trial, axis, delta in ((p1, 0, 10.0), (p2, 1, -10.0)):
            trial["materialization"]["prism_voltages_v"][axis] = baseline["materialization"]["prism_voltages_v"][axis] + delta
            trial["observation"]["prism_voltages_v"] = trial["materialization"]["prism_voltages_v"]
        p1["observation"]["center_particle_prism_handoff_validation"]["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 2.0
        p2["observation"]["center_particle_prism_handoff_validation"]["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"] = -.008
        prior = decide_prism_preclosure(baseline, p1, p2, contract, numerics)
        current = copy.deepcopy(baseline)
        current["materialization"]["prism_voltages_v"] = prior["next_voltages_v"][2:]
        current["observation"]["prism_voltages_v"] = prior["next_voltages_v"][2:]
        stage = current["observation"]["center_particle_prism_handoff_validation"]
        stage["residuals"]["P1_P2_positive_mirror_turn_y_mm"] *= .8
        stage["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"] *= .8
        return baseline, current, prior, contract, numerics

    def test_transported_p_uses_confirmed_real_improvement_and_original_bounds(self):
        baseline, current, prior, contract, numerics = self.transported_prism_fixtures()
        result = decide_transported_prism_preclosure(current, prior, baseline, contract, numerics)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["model_representation"], "transported_local_approximation")
        self.assertTrue(result["requires_real_flight"])
        self.assertFalse(result["full_workpoint_qualified"])
        self.assertEqual(result["next_voltages_v"][:2], prior["voltages_v"][:2])

    def test_transported_p_rejects_changed_s_field_source_and_clock(self):
        baseline, current, prior, contract, numerics = self.transported_prism_fixtures()
        for field in ("mesh", "source", "clock"):
            changed = copy.deepcopy(current)
            changed["frozen_problem"][field] = "different"
            with self.assertRaises(ValueError):
                decide_transported_prism_preclosure(changed, prior, baseline, contract, numerics)
        current["materialization"]["stripe_biases_v"][0] += .01
        with self.assertRaises(ValueError):
            decide_transported_prism_preclosure(current, prior, baseline, contract, numerics)

    def test_transported_p_no_improvement_or_outside_measurement_requests_columns(self):
        baseline, current, prior, contract, numerics = self.transported_prism_fixtures()
        current["observation"]["center_particle_prism_handoff_validation"]["residuals"] = copy.deepcopy(
            baseline["observation"]["center_particle_prism_handoff_validation"]["residuals"])
        result = decide_transported_prism_preclosure(current, prior, baseline, contract, numerics)
        self.assertEqual(result["status"], "needs_stencil")
        current["materialization"]["prism_voltages_v"][0] += 20
        current["observation"]["prism_voltages_v"] = current["materialization"]["prism_voltages_v"]
        result = decide_transported_prism_preclosure(current, prior, baseline, contract, numerics)
        self.assertEqual(result["model_refresh_reason"], "outside_measured_P_extent")

    def test_transported_p_pass_requires_no_model(self):
        baseline, current, _, contract, numerics = self.transported_prism_fixtures()
        stage = current["observation"]["center_particle_prism_handoff_validation"]
        stage["residuals"] = {name: 0.0 for name in stage["residuals"]}
        result = decide_transported_prism_preclosure(current, {}, baseline, contract, numerics)
        self.assertEqual(result["status"], "stage_passed")

    def test_transported_p_opposite_prediction_requires_real_columns(self):
        baseline, current, prior, contract, numerics = self.transported_prism_fixtures()
        prior["physical_jacobian_rows"] = [[-value for value in row] for row in prior["physical_jacobian_rows"]]
        result = decide_transported_prism_preclosure(current, prior, baseline, contract, numerics)
        self.assertEqual(result["status"], "needs_stencil")
        self.assertEqual(result["model_refresh_reason"], "unconfirmed_P_model_improvement")

    def test_prior_p_loader_requires_sealed_success_and_matching_contract(self):
        from common.contracts.write_run_manifest import file_record
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import _load_prior_prism_decision
        baseline, _, prior, contract, _ = self.transported_prism_fixtures()
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            anchor, contract_path, decision_path = root / "anchor.json", root / "contract.json", root / "decision.json"
            anchor.write_text("{}", encoding="utf-8")
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            prior["anchor_manifest"] = str(anchor)
            decision_path.write_text(json.dumps(prior), encoding="utf-8")
            manifest = {"status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
                        "inputs": {"baseline_manifest": file_record(anchor), "workpoint_contract": file_record(contract_path)},
                        "outputs": [file_record(decision_path)]}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch(module + "._load_stage_trial", return_value=baseline):
                self.assertEqual(_load_prior_prism_decision(path, contract)[0], json.loads(json.dumps(prior)))
                with self.assertRaises(ValueError):
                    _load_prior_prism_decision(path, dict(contract, different=True))
                manifest["status"] = "failed"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _load_prior_prism_decision(path, contract)

    def test_prism_transport_cli_consumes_registered_model_and_current_point(self):
        baseline, current, prior, contract, numerics = self.transported_prism_fixtures()
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path, output = root / "contract.json", root / "decision.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            argv = ["iteration", "--control-stage", "prism_preclosure", "--child-manifest",
                    str(root / "current.json"), "--prior-prism-decision-manifest",
                    str(root / "prior.json"), "--contract", str(contract_path), "--output", str(output)]
            with patch("sys.argv", argv), patch(module + "._load_stage_trial", return_value=current), \
                    patch(module + "._load_prior_prism_decision", return_value=(prior, baseline)), \
                    patch(module + ".resolve_numerics", return_value=numerics), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "proposed")
            self.assertEqual(result["required_axes"], [2, 3])
            self.assertEqual(result["measured_model_decision_manifest"], str((root / "prior.json").resolve()))

    def test_p_stage_pass_only_requests_complete_n1_without_s_residuals(self):
        baseline, _, _, contract, numerics = self.prism_preclosure_fixtures()
        baseline["observation"]["center_particle_prism_handoff_validation"]["residuals"] = {
            "P1_P2_positive_mirror_turn_y_mm": 0.,
            "P1_P2_P2_shield_low_field_signed_vy_over_vz": 0.}
        result = decide_prism_preclosure(baseline, None, None, contract, numerics)
        self.assertEqual(result["status"], "stage_passed")
        self.assertEqual(result["next_action"], "complete_N1")
        self.assertFalse(result["full_workpoint_qualified"])

    def test_p_preclosure_requires_both_columns_same_problem_and_fixed_s(self):
        baseline, p1, p2, contract, numerics = self.prism_preclosure_fixtures()
        for missing in ((p1, None), (None, p2)):
            with self.assertRaises(ValueError):
                decide_prism_preclosure(baseline, *missing, contract, numerics)
        p2["frozen_problem"]["mesh"] = "different"
        with self.assertRaises(ValueError):
            decide_prism_preclosure(baseline, p1, p2, contract, numerics)
        p2["frozen_problem"]["mesh"] = "m"
        p2["materialization"]["stripe_biases_v"][0] += .1
        with self.assertRaises(ValueError):
            decide_prism_preclosure(baseline, p1, p2, contract, numerics)

    def test_p_preclosure_obeys_compiled_bounds_and_rejects_incomplete_stage(self):
        baseline, p1, p2, contract, numerics = self.prism_preclosure_fixtures()
        numerics["lower_bounds_v"][2] = baseline["materialization"]["prism_voltages_v"][0] - .0001
        result = decide_prism_preclosure(baseline, p1, p2, contract, numerics)
        self.assertGreaterEqual(result["next_voltages_v"][2], numerics["lower_bounds_v"][2])
        baseline["observation"]["center_particle_prism_handoff_validation"]["status"] = "incomplete"
        result = decide_prism_preclosure(baseline, p1, p2, contract, numerics)
        self.assertEqual(result["terminal_reason"], "collision_or_invalid_topology")
        self.assertFalse(result["stage_observation_available"])

    def test_missing_p_candidate_events_reject_in_both_stage_modes(self):
        for stage in ("prism_preclosure", "stripe_preclosure"):
            for status in (None, "incomplete", "not_available__legacy_source_receipt"):
                baseline, _, _, contract, numerics = self.stripe_preclosure_fixtures()
                if status is None:
                    baseline["observation"].pop("center_particle_prism_handoff_validation")
                else:
                    baseline["observation"]["center_particle_prism_handoff_validation"] = {
                        "status": status, "reason": "collision before first positive turn"}
                baseline["observation"]["termination_diagnostic"] = {"physical_collision": True}
                result = decide_preclosure_stage(stage, baseline, None, None, contract, numerics)
                self.assertEqual(result["status"], "terminal")
                self.assertFalse(result["full_workpoint_qualified"])
                self.assertFalse(result["stage_observation_available"])
                self.assertEqual(result["termination_diagnostic"], {"physical_collision": True})

    def test_invalid_p_identity_or_observed_content_is_not_a_physical_reject(self):
        for change in ("identity", "voltage", "id", "nan"):
            baseline, _, _, contract, numerics = self.stripe_preclosure_fixtures()
            if change == "identity":
                baseline["frozen_problem"] = {}
                baseline["observation"].pop("center_particle_prism_handoff_validation")
            elif change == "voltage":
                baseline["observation"]["prism_voltages_v"] = [0., 0.]
                baseline["observation"].pop("center_particle_prism_handoff_validation")
            elif change == "id":
                baseline["observation"]["center_particle_prism_handoff_validation"]["particle_id"] = 2
            else:
                baseline["observation"]["center_particle_prism_handoff_validation"]["residuals"][
                    "P1_P2_positive_mirror_turn_y_mm"] = float("nan")
            with self.assertRaises(ValueError):
                decide_preclosure_stage("prism_preclosure", baseline, None, None, contract, numerics)
        baseline, s1, s2, contract, numerics = self.stripe_preclosure_fixtures()
        s2["observation"]["center_particle_workpoint_validation"]["particle_id"] = 2
        with self.assertRaises(ValueError):
            decide_preclosure_stage("stripe_preclosure", baseline, s1, s2, contract, numerics)

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
            "schema_version": 1, "role": "mrtof_native_corridor_protection_renewal", "status": "success",
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
            "active_stripe_axes": ["stripe_1_voltage_v", "stripe_2_voltage_v"],
            "jacobian_relative_step_tiers": {
                "coarse": 0.01,
                "medium": 0.0025,
                "fine": 0.0005,
                "medium_maximum_scaled_residual": 10.0,
                "fine_maximum_scaled_residual": 2.0,
            },
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

    def test_trust_limit_uses_relative_convergence_tiers(self):
        prior, observation, materialization, contract = self.fixtures()
        for residual, expected in ((2.0, 0.01), (0.05, 0.0025), (0.015, 0.0005)):
            candidate = copy.deepcopy(observation)
            candidate["residuals"][prior["residual_names"][2]] = residual
            candidate["residuals"][prior["residual_names"][3]] = residual
            result = decide_iteration(prior, candidate, materialization, contract, [], 1)
            self.assertEqual(result["relative_trust_limit"], expected)

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

    def test_valid_improving_topology_midpoint_becomes_new_anchor_below_global_floor(self):
        prior, observation, materialization, contract = self.fixtures()
        observation["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 0.2
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)

        collided = copy.deepcopy(observation)
        collided["termination_diagnostic"]["physical_collision"] = True
        collided_materialization = copy.deepcopy(materialization)
        collided_materialization["stripe_biases_v"] = seed["proposed_voltages_v"][:2]
        collided_materialization["prism_voltages_v"] = seed["proposed_voltages_v"][2:]
        backtrack = decide_iteration(
            prior, collided, collided_materialization, contract, [seed], 2
        )
        self.assertEqual(backtrack["coordinate_group"], "physical_topology_backtrack")

        midpoint = copy.deepcopy(observation)
        midpoint["residuals"]["P1_P2_positive_mirror_turn_y_mm"] = 0.199
        midpoint_materialization = copy.deepcopy(materialization)
        midpoint_materialization["stripe_biases_v"] = backtrack["proposed_voltages_v"][:2]
        midpoint_materialization["prism_voltages_v"] = backtrack["proposed_voltages_v"][2:]
        result = decide_iteration(
            prior, midpoint, midpoint_materialization, contract, [seed, backtrack], 3
        )

        self.assertTrue(result["candidate_accepted"])
        self.assertEqual(
            result["prediction_assessment"]["acceptance_basis"],
            "improving_topology_backtrack",
        )
        self.assertEqual(
            result["accepted_workpoint"]["voltages_v"],
            result["observation_record"]["voltages_v"],
        )

    def test_uses_separate_advance_and_backtrack_multipliers_when_configured(self):
        prior, observation, materialization, contract = self.fixtures()
        loop = contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
        loop["advance_multiplier"] = 0.75
        loop["backtrack_multiplier"] = 0.25
        observation["termination_diagnostic"]["physical_collision"] = True
        result = decide_iteration(prior, observation, materialization, contract, [], 1)
        self.assertAlmostEqual(result["backtrack_factor"], 0.25)
        self.assertAlmostEqual(result["recovery_state"]["advance_multiplier"], 0.75)

    def test_valid_prism_backtrack_bisects_remaining_known_invalid_gap(self):
        prior, observation, materialization, contract = self.fixtures()
        residual_name = prior["residual_names"][0]
        observation["residuals"][residual_name] = 0.2
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)

        invalid = copy.deepcopy(observation)
        invalid["termination_diagnostic"]["physical_collision"] = True
        invalid_materialization = copy.deepcopy(materialization)
        invalid_materialization["prism_voltages_v"] = seed["proposed_voltages_v"][2:]
        backtrack = decide_iteration(
            prior, invalid, invalid_materialization, contract, [seed], 2
        )

        second_invalid_materialization = copy.deepcopy(materialization)
        second_invalid_materialization["prism_voltages_v"] = backtrack["proposed_voltages_v"][2:]
        second_backtrack = decide_iteration(
            prior, invalid, second_invalid_materialization, contract, [seed, backtrack], 3
        )

        valid = copy.deepcopy(observation)
        valid["residuals"][residual_name] = 0.18
        valid_materialization = copy.deepcopy(materialization)
        valid_materialization["prism_voltages_v"] = second_backtrack["proposed_voltages_v"][2:]
        result = decide_iteration(
            prior, valid, valid_materialization, contract, [seed, backtrack, second_backtrack], 4
        )

        invalid_origin = backtrack["proposed_voltages_v"][2:]
        current = valid_materialization["prism_voltages_v"]
        remaining_linf = max(abs(a - b) for a, b in zip(invalid_origin, current, strict=True))
        applied_linf = max(abs(value) for value in result["applied_correction_v"][2:])
        self.assertLessEqual(applied_linf, 0.5 * remaining_linf + 1e-12)
        self.assertEqual(
            result["recovery_state"]["topology_boundary_voltages_v"],
            backtrack["proposed_voltages_v"],
        )

        limited = copy.deepcopy(observation)
        limited["residuals"][residual_name] = 0.1795
        limited_materialization = copy.deepcopy(materialization)
        limited_materialization["prism_voltages_v"] = result["proposed_voltages_v"][2:]
        accepted = decide_iteration(
            prior,
            limited,
            limited_materialization,
            contract,
            [seed, backtrack, second_backtrack, result],
            5,
        )
        self.assertTrue(accepted["candidate_accepted"])
        self.assertEqual(
            accepted["prediction_assessment"]["acceptance_basis"],
            "improving_topology_backtrack",
        )
        self.assertEqual(
            accepted["recovery_state"]["topology_boundary_voltages_v"],
            backtrack["proposed_voltages_v"],
        )

    def test_residual_rejection_preserves_existing_topology_boundary(self):
        prior, observation, materialization, contract = self.fixtures()
        residual_name = prior["residual_names"][0]
        observation["residuals"][residual_name] = 0.2
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)

        invalid = copy.deepcopy(observation)
        invalid["termination_diagnostic"]["physical_collision"] = True
        invalid_materialization = copy.deepcopy(materialization)
        invalid_materialization["prism_voltages_v"] = seed["proposed_voltages_v"][2:]
        backtrack = decide_iteration(
            prior, invalid, invalid_materialization, contract, [seed], 2
        )

        valid = copy.deepcopy(observation)
        valid["residuals"][residual_name] = 0.19
        valid_materialization = copy.deepcopy(materialization)
        valid_materialization["prism_voltages_v"] = backtrack["proposed_voltages_v"][2:]
        bounded = decide_iteration(
            prior, valid, valid_materialization, contract, [seed, backtrack], 3
        )

        worse = copy.deepcopy(observation)
        worse["residuals"][residual_name] = 0.195
        worse_materialization = copy.deepcopy(materialization)
        worse_materialization["prism_voltages_v"] = bounded["proposed_voltages_v"][2:]
        rejected = decide_iteration(
            prior, worse, worse_materialization, contract, [seed, backtrack, bounded], 4
        )
        self.assertFalse(rejected["candidate_accepted"])
        self.assertEqual(rejected["invalid_trial_reason"], "residual_stagnation")
        self.assertEqual(
            rejected["recovery_state"]["topology_boundary_voltages_v"],
            bounded["recovery_state"]["topology_boundary_voltages_v"],
        )

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
        for name in prior["residual_names"]:
            accepted["observation_record"]["physical_acceptance_residuals"][name] = 0.0
        accepted["observation_record"]["scaled_residual_norm"] = 1.0
        accepted["observation_record"]["maximum_scaled_abs_residual"] = 1.0
        subthreshold = copy.deepcopy(accepted)
        subthreshold["candidate_accepted"] = False
        subthreshold["invalid_trial_reason"] = "residual_stagnation"
        subthreshold["observation_record"]["scaled_residual_norm"] = 0.01
        subthreshold["observation_record"]["maximum_scaled_abs_residual"] = 0.01
        subthreshold["observation_record"]["physical_acceptance_residuals"][prior["residual_names"][3]] = 0.0
        handoff = select_best_physical_workpoint([accepted, subthreshold])
        self.assertEqual(handoff["status"], "within_tolerance")
        self.assertEqual(handoff["selected_history_ordinal"], 2)
        self.assertEqual(handoff["selected_workpoint"]["voltages_v"], subthreshold["observation_record"]["voltages_v"])

    def test_best_physical_handoff_prefers_lower_prism_magnitude_after_p_qualification(self):
        prior, observation, materialization, contract = self.fixtures()
        high_voltage = decide_iteration(prior, observation, materialization, contract, [], 1)
        for name in prior["residual_names"]:
            high_voltage["observation_record"]["physical_acceptance_residuals"][name] = 0.0
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

    def test_terminal_success_is_eligible_without_candidate_accepted_marker(self):
        prior, observation, materialization, contract = self.fixtures()
        terminal = decide_iteration(prior, observation, materialization, contract, [], 1)
        for name in prior["residual_names"]:
            terminal["observation_record"]["physical_acceptance_residuals"][name] = 0.0
        terminal.pop("candidate_accepted", None)
        terminal["terminal_reason"] = "success"
        handoff = select_best_physical_workpoint([terminal])
        self.assertEqual(handoff["status"], "within_tolerance")

    def test_best_physical_handoff_rejects_invalid_or_p_unqualified_lower_voltage_records(self):
        prior, observation, materialization, contract = self.fixtures()
        accepted = decide_iteration(prior, observation, materialization, contract, [], 1)
        for name in prior["residual_names"]:
            accepted["observation_record"]["physical_acceptance_residuals"][name] = 0.0
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
        ] = 1.0
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

    def test_recovery_anchor_replay_is_not_a_two_point_cycle(self):
        prior, observation, materialization, contract = self.fixtures()
        seed = decide_iteration(prior, observation, materialization, contract, [], 1)
        intervening = copy.deepcopy(seed)
        intervening["observation_record"]["voltages_v"][0] += 0.1
        intervening["candidate_accepted"] = False
        intervening["coordinate_group"] = "physical_topology_backtrack"
        intervening["rejected_coordinate_group"] = "stripe_1_stripe_2"
        intervening["accepted_workpoint"] = seed["observation_record"]
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
            prior, observation, materialization, contract,
            [seed, intervening, recovered_model], 3, recovery_resume=True,
        )
        self.assertEqual(result["state"], "continue", result)
        self.assertIsNone(result["terminal_reason"])
        self.assertTrue(result["recovery_resume_proposal"])

    def test_trusted_recovery_radius_grows_gradually_after_first_real_prediction(self):
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
        first = decide_iteration(
            prior, observation, materialization, contract, [seed, recovered_model], 2,
            recovery_resume=True,
        )
        measured = copy.deepcopy(observation)
        measured["residuals"] = copy.deepcopy(first["predicted_physical_acceptance_residuals"])
        next_materialization = copy.deepcopy(materialization)
        next_materialization["stripe_biases_v"] = first["proposed_voltages_v"][:2]
        second = decide_iteration(
            prior, measured, next_materialization, contract, [seed, recovered_model, first], 2,
        )
        self.assertEqual(second["state"], "continue")
        self.assertLessEqual(max(abs(value) for value in second["applied_correction_v"][:2]), 0.04)
        self.assertEqual(second["prediction_assessment"]["recovery_trust_bound_v"], 0.04)

    def test_trusted_bounded_recovery_prediction_is_not_rejected_by_global_improvement_floor(self):
        prior, observation, materialization, contract = self.fixtures()
        contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"][
            "minimum_relative_improvement"
        ] = 0.5
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
        first = decide_iteration(
            prior, observation, materialization, contract, [seed, recovered_model], 2,
            recovery_resume=True,
        )
        measured = copy.deepcopy(observation)
        measured["residuals"] = copy.deepcopy(first["predicted_physical_acceptance_residuals"])
        next_materialization = copy.deepcopy(materialization)
        next_materialization["stripe_biases_v"] = first["proposed_voltages_v"][:2]
        second = decide_iteration(
            prior, measured, next_materialization, contract, [seed, recovered_model, first], 2,
        )
        self.assertEqual(second["state"], "continue")
        self.assertTrue(second["candidate_accepted"])
        self.assertEqual(
            second["prediction_assessment"]["acceptance_basis"],
            "trusted_recovery_prediction",
        )

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



    def test_static_observation_preserves_actual_field_without_aliasing(self):
        _, observation, materialization, contract = self.fixtures()
        binding = {"mode": "comsol_static_scalar_v", "path": "selected-child-field.json",
                   "representation": "exploratory_response_combination",
                   "response_weight_l1_norm": 3.0,
                   "sources": {"baseline": "baseline-binding.json"},
                   "response_terms": [{"coefficient": -1.0, "binding_path": "baseline-binding.json", "binding": {
                       "path": "baseline-binding.json", "geometry": {"large": "x" * 100000},
                       "records": {"scalar_pa": {"sha256": "a" * 64}}}}],
                   "records": {"scalar_pa": {"sha256": "a" * 64}}}
        materialization["field_binding"] = binding
        record, _, _ = _observation_record(
            observation, materialization, contract["downstream_fixed_grid_workpoint_profile"])
        expected = {"mode": binding["mode"], "path": binding["path"],
                    "representation": binding["representation"], "response_weight_l1_norm": 3.0,
                    "sources": {"baseline": "baseline-binding.json"},
                    "response_terms": [{"coefficient": -1.0,
                                        "binding_path": "baseline-binding.json"}]}
        self.assertEqual(record["field_binding"], expected)
        binding["sources"]["baseline"] = "changed.json"
        self.assertEqual(record["field_binding"]["sources"]["baseline"], "baseline-binding.json")
        self.assertLess(len(json.dumps(record)), 2500)
        self.assertEqual(set(record["residuals"]), set(observation["residuals"]))

    def test_static_observation_rejects_missing_actual_binding_path(self):
        _, observation, materialization, contract = self.fixtures()
        materialization["field_binding"] = {"mode": "comsol_static_scalar_v"}
        with self.assertRaisesRegex(Exception, "actually flown field"):
            _observation_record(observation, materialization,
                                contract["downstream_fixed_grid_workpoint_profile"])

    def test_saved_state_compaction_preserves_physics_and_is_idempotent(self):
        binding = {"mode": "comsol_static_scalar_v", "path": "actual.json",
                   "representation": "exploratory_response_combination",
                   "response_weight_l1_norm": 2.01,
                   "response_terms": [{"coefficient": -0.505, "binding_path": "base.json", "binding": {
                       "path": "base.json", "geometry": {"large": "x" * 100000}}}]}
        record = {"voltages_v": [1, 2, 3, 4], "residuals": {"s": 5.0},
                  "field_binding": binding}
        original = {"stage_state": {"flight_count": 17, "candidate_count": 8},
                    "stage_history": {"decisions": [{"state": "terminal",
                        "terminal_reason": "model_recovery_exhausted",
                        "full_workpoint_qualified": False, "observation_record": record,
                        "stage_observation_record": copy.deepcopy(record)}]},
                    "stage_lineage": {"children": [{"child_manifest": "real-child.json"}]},
                    "frozen_problem": {"scientific_family": {"geometry": "unchanged"}}}
        frozen = copy.deepcopy(original)
        result = compact_saved_iteration_state(original)
        self.assertEqual(original, frozen)
        self.assertEqual(compact_saved_iteration_state(result), result)
        self.assertEqual(result["stage_state"], original["stage_state"])
        self.assertEqual(result["stage_lineage"], original["stage_lineage"])
        self.assertEqual(result["frozen_problem"], original["frozen_problem"])
        decision = result["stage_history"]["decisions"][0]
        self.assertFalse(decision["full_workpoint_qualified"])
        self.assertEqual(decision["terminal_reason"], "model_recovery_exhausted")
        self.assertNotIn("stage_observation_record", decision)
        self.assertEqual(decision["observation_record"]["residuals"], record["residuals"])
        self.assertLess(len(json.dumps(result)), 2500)
        only_stage = compact_saved_iteration_state({"stage_observation_record": record})
        self.assertIn("observation_record", only_stage)

    def test_best_physical_handoff_keeps_selected_field_not_latest(self):
        prior, observation, materialization, contract = self.fixtures()
        first = decide_iteration(prior, observation, materialization, contract, [], 1)
        for name in prior["residual_names"]:
            first["observation_record"]["physical_acceptance_residuals"][name] = 0.0
        first["observation_record"]["field_binding"] = {
            "mode": "comsol_static_scalar_v", "path": "earlier-selected-field.json"}
        latest = copy.deepcopy(first)
        latest["observation_record"]["voltages_v"][2:] = [250.0, -250.0]
        latest["observation_record"]["field_binding"]["path"] = "latest-field.json"
        result = select_best_physical_workpoint([first, latest])
        self.assertEqual(result["selected_history_ordinal"], 1)
        self.assertEqual(result["selected_workpoint"]["field_binding"]["path"],
                         "earlier-selected-field.json")

if __name__ == "__main__":
    unittest.main()
