from __future__ import annotations

import hashlib
import json
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import two_prism_simion_trial
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _accelerator_energy_binding,
    _apply_terminal_mirror_variation,
    _apply_trajectory_step_scale,
    _accelerator_safe_exit_observation,
    _load_frozen_accelerator_pulse_schedule,
    _mirror_regions,
    _resolve_trial_geometry,
    _fixed_mirror_stripe_source_state,
    _schema5_native_source_state,
    _single_center_source_state,
    _single_center_source_fly2,
    _p2_handoff_targets,
    _static_return_diagnostic,
    _termination_diagnostic,
    analyze_trial,
    freeze_single_center_pulse_schedule,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_shape_adapter import (
    native_stripe_geometry_projection_sha256,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class TwoPrismSimionTrialTest(unittest.TestCase):
    def test_mirror_regions_projects_the_single_resolved_geometry(self) -> None:
        resolved = {
            "mirror_ground_shields": [{"box": [0, 0, -9, 1, 1, -8]}],
            "mirror_electrodes": [
                {"box": [0, 0, -7, 1, 1, -6]},
                {"box": [0, 0, 6, 1, 1, 7]},
            ],
            "mirror_e_closures": [{"box": [0, 0, 8, 1, 1, 9]}],
        }
        self.assertEqual(
            _mirror_regions(resolved),
            {"negative": [-9, -6], "positive": [6, 9]},
        )

    def test_cli_uses_only_the_declared_workbench_accelerator_instance(self) -> None:
        source = Path(two_prism_simion_trial.__file__).read_text(encoding="utf-8")
        self.assertIn("accelerator_instance=args.workbench_accelerator_instance", source)
        self.assertNotIn("accelerator_instance=args.accelerator_instance", source)

    def test_provider_pose_comes_only_from_the_active_mr_contract(self) -> None:
        source = Path(two_prism_simion_trial.__file__).read_text(encoding="utf-8")
        provider_branch = source[source.index("if provider_geometry is None:"):]
        self.assertIn("placement = derive_two_zone_placement(contract)", provider_branch)
        self.assertNotIn("placement = derive_two_zone_placement(reviewed_contract)", provider_branch)

    def test_terminal_mirror_variation_is_authority_bound_and_envelope_checked(self) -> None:
        contract_path = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"
        contract = two_prism_simion_trial.load_contract(contract_path)
        base = [0.0, -5920.610006, -2612.981546, 4190.462801, 6029.159820]
        variation = {
            "schema_version": 1,
            "role": "mrtof_terminal_time_mirror_voltage_variation",
            "status": "screening_candidate_materialized",
            "qualification": "diagnostic_only__complete_3d_detector_response_pending",
            "mode": "TE1",
            "coordinate": 1,
            "base_mirror_voltages_v": base,
            "target_mirror_voltages_v": [0.0, base[1] + 2, base[2] - 10, base[3] + 6, base[4] + 5],
            "voltage_delta_v": [2.0, -10.0, 6.0, 5.0],
            "source_seed": {"sha256": "a" * 64},
        }
        target, identity = _apply_terminal_mirror_variation(
            variation=variation, base_voltages=base, contract=contract,
            axial_energy_v=4372.010347796,
        )
        self.assertEqual(target, variation["target_mirror_voltages_v"])
        self.assertEqual(identity["mode"], "TE1")
        invalid = copy.deepcopy(variation)
        invalid["base_mirror_voltages_v"][1] += 1
        with self.assertRaisesRegex(CandidateContractError, "not bound"):
            _apply_terminal_mirror_variation(
                variation=invalid, base_voltages=base, contract=contract,
                axial_energy_v=4372.010347796,
            )

    def test_trajectory_step_scale_derives_0p001_from_screening_profile(self) -> None:
        base = {
            "profile_id": "center_screening", "trajectory_quality": 8,
            "maximum_step_us": 0.002, "purpose": "screening",
        }
        scaled = _apply_trajectory_step_scale(base, 0.5)
        self.assertEqual(scaled["maximum_step_us"], 0.001)
        self.assertEqual(scaled["base_profile_id"], "center_screening")
        self.assertEqual(base["maximum_step_us"], 0.002)
        with self.assertRaisesRegex(CandidateContractError, r"\(0, 1\]"):
            _apply_trajectory_step_scale(base, 1.1)

    def test_accelerator_energy_binding_distinguishes_command_from_target(self) -> None:
        target = 4198.824969860909
        correction = 0.7536110122964601
        binding = _accelerator_energy_binding({
            "energy_per_charge_v": target + correction,
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": correction,
        }, target)
        self.assertEqual(binding["target_axial_energy_per_charge_v"], target)
        self.assertEqual(binding["finite_3d_gain_correction_v"], correction)
        self.assertAlmostEqual(
            binding["applied_net_gain_parameter_v"], target + correction,
        )

    def test_accelerator_energy_binding_fails_closed_on_wrong_target_or_identity(self) -> None:
        target = 4198.824969860909
        correction = 0.7536110122964601
        valid = {
            "energy_per_charge_v": target + correction,
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": correction,
        }
        with self.assertRaisesRegex(
            CandidateContractError, "target axial energy and analyser",
        ):
            _accelerator_energy_binding(
                {**valid, "target_axial_energy_per_charge_v": target - 1.0}, target,
            )
        with self.assertRaisesRegex(
            CandidateContractError, "finite-3D correction.*inconsistent",
        ):
            _accelerator_energy_binding(
                {**valid, "finite_3d_gain_correction_v": correction + 0.1}, target,
            )

    def test_trial_geometry_keeps_reviewed_conductors_and_current_event_authority(self) -> None:
        reviewed = {
            "identity": "reviewed-physical-geometry",
            "accelerator": {"reviewed_conductor": "retained"},
        }
        current = {"identity": "current-topology-and-observation-authority"}
        accelerator = {
            "accelerator": {
                "component_source_cylinder": {"radius_mm": 0.1, "height_mm": 2.0},
                "focus_y_anchor": {"project_y_mm": -45.0},
                "unused_provider_field": "not-forwarded",
            },
        }
        expected = {"resolved": True}
        with patch.object(
            two_prism_simion_trial, "resolve_geometry", return_value=expected,
        ) as resolver:
            self.assertIs(_resolve_trial_geometry(reviewed, current, accelerator), expected)
        forwarded = resolver.call_args.args[0]
        self.assertEqual(forwarded["identity"], "reviewed-physical-geometry")
        self.assertEqual(forwarded["accelerator"]["reviewed_conductor"], "retained")
        self.assertEqual(
            forwarded["accelerator"]["component_source_cylinder"],
            accelerator["accelerator"]["component_source_cylinder"],
        )
        self.assertEqual(
            forwarded["accelerator"]["focus_y_anchor"],
            accelerator["accelerator"]["focus_y_anchor"],
        )
        self.assertNotIn("unused_provider_field", forwarded["accelerator"])
        self.assertNotIn("component_source_cylinder", reviewed["accelerator"])
        self.assertEqual(
            resolver.call_args.kwargs,
            {"inherited_dual_stripe_topology_contract": current},
        )

    @staticmethod
    def _analyze_with_handoff_events(
        *, log: Path, receipt: Path, output: Path,
    ) -> dict[str, object]:
        """Insert the P2 low-field section into compact downstream fixtures."""
        events = parse_events(log.read_text(encoding="utf-8"))
        p2_index = next(
            index for index, event in enumerate(events)
            if event["kind"] == "prism_pass" and event.get("n") == 2
        )
        events.insert(p2_index + 1, {
            "kind": "p2_low_field_reference",
            "ion": 1,
            "t_us": 3.25,
            "x_mm": 0.0,
            "y_mm": -1.0,
            "z_mm": 33.0,
            "vx_mm_us": 0.0,
            "vy_mm_us": 1.0,
            "vz_mm_us": 2.0,
        })
        with patch.object(two_prism_simion_trial, "parse_events", return_value=events):
            return analyze_trial(
                log_path=log, trial_receipt_path=receipt, output_path=output,
            )

    @staticmethod
    def _single_center_source_fields() -> dict[str, object]:
        return {
            "source_slow_kinetic_energy_per_charge_v": 5.0,
            "source_direction_project": [0.0, 1.0, 0.0],
            "source_particle_count": 1,
            "source_time_of_birth_us": 0.0,
        }

    @staticmethod
    def _schema5_source_fixture() -> tuple[dict[str, object], dict[str, object]]:
        contract: dict[str, object] = {
            "nominal": {"energy_per_charge_v": 4000.0},
            "accelerator_energy_contract": {
                "net_gain_reference_center_per_charge_v": 4000.0,
                "net_gain_center_search_half_range_per_charge_v": 500.0,
            },
            "prism_transport": {
                "energy_partition": {"drift_kinetic_energy_ev": 5.0},
            },
            "dual_stripe": {
                "theory_profile": {
                    "set_1": {"curve": [[0.0, 4.0], [340.0, 3.0]]},
                    "set_2": {"curve": [[0.0, 2.0], [340.0, 1.0]]},
                },
            },
            "dual_stripe_l0": {
                "coordinate_mapping": {
                    "origin_project_y_mm": 0.0,
                    "theory_positive_project_y_sign": 1,
                },
                "theory_function_coordinate_registration": {
                    "function_y_zero_project_y_mm": 0.0,
                    "active_theory_curve_domain_project_y_mm": [0.0, 390.0],
                },
                "manufactured_design_abs_drift_length_L_mm": 340.0,
            },
        }
        geometry_identity = (
            "canonical_json_sha256:"
            f"{native_stripe_geometry_projection_sha256(contract)}"
        )
        shape_root = {
            "geometry_input_identity_source": geometry_identity,
            "kappa_1": 1.48896973866,
        }
        biases = [-25.3180924893, 50.3596877998]
        summary: dict[str, object] = {
            "schema_version": 5,
            "role": "mrtof_dual_stripe_exact_k_downstream_operating_seed",
            "status": "native_shape_source_energy_inverse_and_stripe_on_exact_k_complete",
            "selected_exact_k_operating_point": {
                "axial_energy_per_charge_v": 4000.0,
                "kappa_1": shape_root["kappa_1"],
            },
            "native_stripe_spatial_shape_root": shape_root,
            "selected_seed": {
                "nominal_kappa_1": shape_root["kappa_1"],
                "nominal_injection_angle_degrees": 1.2,
                "stripe_biases_v": biases,
                "native_spatial_return_materialization": {
                    "shape_root": dict(shape_root),
                    "axial_energy_per_charge_v": 4000.0,
                    "source_slow_energy_per_charge_v": 5.0,
                    # This is intentionally different: it is a derived turn
                    # diagnostic, never the released source energy authority.
                    "turning_pseudopotential_v": 4.955863026,
                    "stripe_biases_v": list(biases),
                },
            },
        }
        return summary, contract

    def test_handoff_targets_come_from_frozen_seed_and_registration(self) -> None:
        summary, contract = self._schema5_source_fixture()
        seed = summary["selected_seed"]
        target_y, angle_degrees, tangent_ratio = _p2_handoff_targets(seed, contract)
        self.assertEqual(target_y, 0.0)
        self.assertEqual(angle_degrees, 1.2)
        self.assertAlmostEqual(tangent_ratio, math.tan(math.radians(1.2)))

        invalid = copy.deepcopy(seed)
        invalid["nominal_injection_angle_degrees"] = 0.0
        with self.assertRaisesRegex(CandidateContractError, "finite positive"):
            _p2_handoff_targets(invalid, contract)

    def test_schema5_native_source_uses_fixed_source_energy_not_turning_energy(self) -> None:
        summary, contract = self._schema5_source_fixture()
        seed, source_energy = _schema5_native_source_state(summary, contract, 4000.0)
        self.assertEqual(source_energy, 5.0)
        self.assertEqual(
            seed["native_spatial_return_materialization"]["turning_pseudopotential_v"],
            4.955863026,
        )

        fly2 = _single_center_source_fly2(
            mass_th=100.0,
            charge_state=-2,
            source_slow_energy_per_charge_v=source_energy,
            focus_y_mm=-55.0,
            release_z_mm=50.0,
        )
        self.assertIn("ke = 10,", fly2)
        self.assertIn("charge = -2,", fly2)
        self.assertIn("direction = vector(0, 1, 0),", fly2)
        self.assertNotIn("4.955863026", fly2)

    def test_fixed_mirror_stripe_authority_selects_near_five_ev_source(self) -> None:
        _, contract = self._schema5_source_fixture()
        axial = 4372.010347796059
        slow = 4.961131691875478
        target_k = 25.5
        biases = [-25.223218746120438, 50.18222992863684]
        voltages = [0.0, -4799.0, 3811.0, 4998.0, 7931.0]
        materialized = {
            "axial_energy_per_charge_v": axial,
            "source_slow_energy_per_charge_v": slow,
            "stripe_biases_v": list(biases),
        }
        seed = {
            "selected_axial_energy_per_charge_v": axial,
            "selected_exact_K_slow_energy_per_charge_v": slow,
            "target_drift_period_ratio": target_k,
            "predicted_continuous_oscillation_count": target_k,
            "nominal_injection_angle_degrees": math.degrees(math.atan(math.sqrt(slow / axial))),
            "stripe_biases_v": list(biases),
            "native_spatial_return_materialization": materialized,
        }
        stripe = {
            "schema_version": 3,
            "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
            "status": "fixed_grid_native_mirror_exact_K_slow_energy_and_spatial_return_inverse_complete",
            "selected_seed": seed,
        }
        mirror = {
            "schema_version": 1,
            "role": "mrtof_mirror_turn_fixed_grid_validation",
            "status": "success",
        }
        authority = {
            "schema_version": 1,
            "role": "mrtof_fixed_mirror_stripe_downstream_operating_authority",
            "status": "success",
            "axial_energy_per_charge_v": axial,
            "slow_energy_per_charge_v": slow,
            "target_period_ratio": target_k,
            "predicted_period_ratio": target_k,
            "mirror_voltages_v": list(voltages),
            "stripe_biases_v": list(biases),
        }
        selected = _fixed_mirror_stripe_source_state(
            authority, mirror, stripe, contract,
        )
        self.assertIs(selected[0], seed)
        self.assertEqual(selected[1:], (slow, axial, voltages, target_k))
        invalid = copy.deepcopy(authority)
        invalid["slow_energy_per_charge_v"] = 5.0
        with self.assertRaisesRegex(CandidateContractError, "differs from its source summary"):
            _fixed_mirror_stripe_source_state(invalid, mirror, stripe, contract)

    def test_schema5_native_source_accepts_selected_exact_k_energy_within_search_envelope(self) -> None:
        summary, contract = self._schema5_source_fixture()
        selected = 4198.824969860909
        summary["selected_exact_k_operating_point"]["axial_energy_per_charge_v"] = selected
        summary["selected_seed"]["native_spatial_return_materialization"][
            "axial_energy_per_charge_v"
        ] = selected
        _, source_energy = _schema5_native_source_state(summary, contract, selected)
        self.assertEqual(source_energy, 5.0)

        with self.assertRaisesRegex(CandidateContractError, "outside the contract search envelope"):
            _schema5_native_source_state(summary, contract, 4500.0000001)

    def test_single_center_source_state_uses_energy_mass_charge_and_direction(self) -> None:
        trial = {
            **self._single_center_source_fields(),
            "source_position_project_mm": [0.0, -55.0, 50.0],
            "particle_mass_th": 524.0,
            "charge_state": 2,
        }
        state, published = _single_center_source_state(trial)
        self.assertEqual(state.position_mm, (0.0, -55.0, 50.0))
        self.assertAlmostEqual(published["kinetic_energy_ev"], 10.0)
        self.assertAlmostEqual(published["kinetic_energy_per_charge_v"], 5.0)
        self.assertEqual(published["direction_project"], [0.0, 1.0, 0.0])
        self.assertGreater(state.velocity_mm_per_us[1], 0.0)
        self.assertNotEqual(state.velocity_mm_per_us, (0.0, 1.0, 0.0))
        for missing in (
            "source_slow_kinetic_energy_per_charge_v",
            "source_direction_project",
            "particle_mass_th",
            "charge_state",
        ):
            invalid = dict(trial)
            del invalid[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(CandidateContractError):
                    _single_center_source_state(invalid)
        with self.assertRaisesRegex(CandidateContractError, "Fly2 \+project-y"):
            _single_center_source_state({
                **trial,
                "source_direction_project": [0.0, 0.0, -1.0],
            })

    def test_schema5_native_source_rejects_missing_or_inconsistent_identity(self) -> None:
        cases = []
        summary, contract = self._schema5_source_fixture()
        summary["schema_version"] = 4
        cases.append((summary, contract, "schema-5"))

        summary, contract = self._schema5_source_fixture()
        materialized = summary["selected_seed"]["native_spatial_return_materialization"]
        del materialized["source_slow_energy_per_charge_v"]
        cases.append((summary, contract, "source slow energy"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"][
            "source_slow_energy_per_charge_v"
        ] = 6.0
        cases.append((summary, contract, "fixed source contract"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"][
            "axial_energy_per_charge_v"
        ] = 3999.0
        cases.append((summary, contract, "selected energies differ"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"]["shape_root"] = {
            "geometry_input_identity_source": "canonical_json_sha256:other-shape",
            "kappa_1": 1.48896973866,
        }
        cases.append((summary, contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        summary["native_stripe_spatial_shape_root"][
            "geometry_input_identity_source"
        ] = "canonical_json_sha256:jointly-forged-shape"
        summary["selected_seed"]["native_spatial_return_materialization"]["shape_root"][
            "geometry_input_identity_source"
        ] = "canonical_json_sha256:jointly-forged-shape"
        cases.append((summary, contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        changed_contract = copy.deepcopy(contract)
        changed_contract["dual_stripe"]["theory_profile"]["set_1"]["curve"][1][1] = 3.25
        cases.append((summary, changed_contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"][
            "stripe_biases_v"
        ][0] += 0.1
        cases.append((summary, contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        del contract["prism_transport"]["energy_partition"]
        cases.append((summary, contract, "energy authorities"))

        for invalid_summary, invalid_contract, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(CandidateContractError, message):
                    _schema5_native_source_state(
                        invalid_summary, invalid_contract, 4000.0,
                    )

    def test_frozen_accelerator_schedule_requires_clock_and_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            schedule = {
                "schema_version": 1,
                "role": "mrtof_accelerator_global_pulse_schedule",
                "status": "frozen",
                "mode": "fixed_global_time",
                "time_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
                "pulse_off_time_us": 1.867,
                "source": {
                    "center_run_id": "run",
                    "run_manifest_sha256": "a",
                    "trial_receipt_sha256": "b",
                    "observation_sha256": "c",
                    "source_fly2_sha256": "d",
                    "accelerator_receipt_sha256": "e",
                    "source_particle_count": 1,
                },
                "after_state": {
                    "accelerator_electrode_ids": list(range(1, 10)),
                    "voltage_v": 0.0,
                },
            }
            path.write_text(json.dumps(schedule), encoding="utf-8")
            self.assertEqual(
                _load_frozen_accelerator_pulse_schedule(path)["pulse_off_time_us"],
                1.867,
            )
            schedule["source"].pop("source_fly2_sha256")
            path.write_text(json.dumps(schedule), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "source identity"):
                _load_frozen_accelerator_pulse_schedule(path)

    def test_complete_bunch_schedule_identity_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            schedule = {
                "schema_version": 2,
                "role": "mrtof_accelerator_global_pulse_schedule",
                "status": "frozen",
                "mode": "fixed_global_time",
                "time_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
                "pulse_off_time_us": 1.9,
                "source_cohort": {"particle_states_sha256": "a" * 64},
                "solver_problem_identity": {"canonical_sha256": "b" * 64},
                "safe_exit_definition": {"event_count": 100},
                "after_state": {
                    "accelerator_electrode_ids": list(range(1, 10)),
                    "voltage_v": 0.0,
                },
            }
            path.write_text(json.dumps(schedule), encoding="utf-8")
            self.assertEqual(
                _load_frozen_accelerator_pulse_schedule(path)["schema_version"], 2
            )
            del schedule["solver_problem_identity"]
            path.write_text(json.dumps(schedule), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "bunch pulse schedule"):
                _load_frozen_accelerator_pulse_schedule(path)

    def test_single_center_exit_event_freezes_only_a_diagnostic_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "center"
            results = run / "results"
            simion = run / "simion"
            results.mkdir(parents=True)
            simion.mkdir()
            trial_path = results / "two_prism_trial_materialization.json"
            observation_path = results / "two_prism_trial_observation.json"
            fly2_path = simion / "downstream_trial_source.input.fly2"
            trial_path.write_text(json.dumps({
                "source_particle_count": 1,
                "source_time_of_birth_us": 0.0,
                "source_clock_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
                "accelerator_pulse": {"mode": "initial_exit_triggered_single_center"},
                "inputs": {"accelerator_receipt_sha256": "accelerator-sha"},
            }), encoding="utf-8")
            observation_path.write_text(json.dumps({
                "accelerator_pulse_diagnostic": {
                    "mode": "initial_exit_triggered_single_center",
                    "pulse_off_event_count": 1,
                    "pulse_off_event": {
                        "t_us": 1.867, "from_instance": 3, "to_instance": 1,
                        "x_mm": 0.0, "y_mm": -55.0, "z_mm": -5.7,
                    },
                },
            }), encoding="utf-8")
            fly2_path.write_text("particles {}\n", encoding="utf-8")

            def record(path: Path) -> dict[str, object]:
                return {
                    "path": str(path.resolve()), "exists": True,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            manifest_path = run / "run_manifest.json"
            manifest_path.write_text(json.dumps({
                "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "finite_3d_two_prism_voltage_trial",
                "status": "success",
                "run_id": "center-run",
                "inputs": {"frozen_source_fly2": record(fly2_path)},
                "outputs": [record(trial_path), record(observation_path)],
            }), encoding="utf-8")
            schedule = freeze_single_center_pulse_schedule(
                center_run_path=run, output_path=run / "schedule.json",
            )
            self.assertEqual(schedule["pulse_off_time_us"], 1.867)
            self.assertEqual(
                schedule["qualification"], "single_center_diagnostic__not_a_bunch_schedule"
            )
            self.assertIsNone(schedule["derivation"]["bunch_safe_exit_envelope"])

    def test_static_return_requires_unique_ordered_negative_z_detector_hit(self) -> None:
        kinds = (
            "drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn",
        )
        events = [
            {"kind": kind, "ion": 1, "fractional_k": 24.99, "t_us": float(index),
             "z_mm": 280.0 if kind == "return_positive_mirror_turn" else 0.0,
             "vz_mm_us": (1.0 if kind in ("return_p2_entry", "return_p2_pass")
                            else 0.0)}
            for index, kind in enumerate(kinds, 1)
        ] + [
            {"kind": "detector", "ion": 1, "direction_z": -1, "z_mm": 95.0, "t_us": 7.0},
            {"kind": "splat", "ion": 1, "code": 1, "t_us": 7.0},
            {"kind": "terminal", "ion": 1, "splat": 1, "t_us": 7.0},
        ]
        result = _static_return_diagnostic(events, 25)
        self.assertEqual(result["status"], "detector_hit")
        self.assertTrue(result["event_contract_ok"])
        self.assertAlmostEqual(result["fractional_k_minus_target"], -0.01)
        events.insert(1, {"kind": "drift_phase_candidate", "ion": 1, "k": 26, "t_us": 1.5})
        self.assertTrue(_static_return_diagnostic(events, 25)["event_contract_ok"])
        next(event for event in events if event["kind"] == "return_p2_pass")["t_us"] = 0.5
        self.assertIn("static_return_events_out_of_order",
                      _static_return_diagnostic(events, 25)["errors"])

    def test_static_return_rejects_accelerator_reentry(self) -> None:
        kinds = (
            "drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn",
        )
        events = [
            {"kind": kind, "ion": 1, "fractional_k": 25.0, "t_us": float(index),
             "z_mm": 280.0 if kind == "return_positive_mirror_turn" else 0.0,
             "vz_mm_us": (1.0 if kind in ("return_p2_entry", "return_p2_pass")
                            else 0.0)}
            for index, kind in enumerate(kinds, 1)
        ] + [
            {"kind": "accelerator_reentry", "ion": 1, "t_us": 6.5},
            {"kind": "detector", "ion": 1, "direction_z": -1, "z_mm": 95.0, "t_us": 7.0},
            {"kind": "splat", "ion": 1, "code": 1, "t_us": 7.0},
            {"kind": "terminal", "ion": 1, "splat": 1, "t_us": 7.0},
        ]
        result = _static_return_diagnostic(events, 25)
        self.assertFalse(result["event_contract_ok"])
        self.assertIn("accelerator_reentry_after_safe_exit_forbidden", result["errors"])

    def test_static_return_rejects_legacy_return_through_p1(self) -> None:
        kinds = (
            "drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn",
        )
        events = [
            {"kind": kind, "ion": 1, "fractional_k": 25.5, "t_us": float(index),
             "z_mm": 280.0 if kind == "return_positive_mirror_turn" else 0.0,
             "vz_mm_us": (1.0 if kind in ("return_p2_entry", "return_p2_pass")
                            else 0.0)}
            for index, kind in enumerate(kinds, 1)
        ] + [
            {"kind": "return_p1_pass", "ion": 1, "t_us": 6.0,
             "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
             "vx_mm_us": 0.0, "vy_mm_us": -1.0, "vz_mm_us": -1.0},
            {"kind": "detector", "ion": 1, "direction_z": -1,
             "z_mm": 95.0, "t_us": 7.0},
            {"kind": "splat", "ion": 1, "code": 1, "t_us": 7.0},
            {"kind": "terminal", "ion": 1, "splat": 1, "t_us": 7.0},
        ]
        result = _static_return_diagnostic(events, 25.5)
        self.assertFalse(result["event_contract_ok"])
        self.assertIn(
            "return_p1_forbidden__p1_is_injection_only", result["errors"]
        )

    def test_code_four_is_programmatic_topology_rejection_not_collision(self) -> None:
        events = parse_events(
            "MRTOF_EVENT splat ion=1 code=4 "
            "termination_kind=programmatic_topology_rejection "
            "physical_collision=0 reason=return_central_phase_direction_mismatch "
            "t_us=20 x_mm=0 y_mm=0 z_mm=159.88 turns=49 central_crossings=49\n"
            "MRTOF_EVENT terminal ion=1 splat=4 t_us=20 x_mm=0 y_mm=0 "
            "z_mm=159.88 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=47 "
            "turns=49 central_crossings=49\n"
        )
        diagnostic = _termination_diagnostic(events)
        self.assertEqual(diagnostic["kind"], "programmatic_topology_rejection")
        self.assertFalse(diagnostic["physical_collision"])
        self.assertTrue(diagnostic["explicit_semantics"])
        self.assertEqual(
            diagnostic["reason"], "return_central_phase_direction_mismatch"
        )

    def test_switched_trial_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
                "prism_switch": {"enabled": True},
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "forbids all P1/P2"):
                analyze_trial(log_path=log, trial_receipt_path=receipt,
                              output_path=root / "observation.json")

    def test_switch_event_in_static_log_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "prism_switch": None,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text(
                "MRTOF_EVENT prism_voltage_switch ion=1 electrode=17 "
                "t_us=10 from_v=-179 to_v=-140\n", encoding="utf-8",
            )
            with self.assertRaisesRegex(CandidateContractError, "forbidden P1/P2"):
                analyze_trial(log_path=log, trial_receipt_path=receipt,
                              output_path=root / "observation.json")

    def test_single_center_accelerator_pulse_requires_one_initial_exit_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "source_position_project_mm": [0.0, -55.0, -60.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "flight_scope": "complete_three_dimensional_static_return",
                "prism_switch": None,
                "accelerator_pulse": {
                    "mode": "initial_exit_triggered_single_center",
                    "qualification": "single_center_only",
                },
                "accelerator_instance": 3,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "exactly one pulse-off"):
                analyze_trial(log_path=log, trial_receipt_path=receipt,
                              output_path=root / "missing.json")
            log.write_text(
                "MRTOF_EVENT accelerator_pulse_off ion=1 t_us=1.86 "
                "from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=-5.7\n",
                encoding="utf-8",
            )
            result = analyze_trial(log_path=log, trial_receipt_path=receipt,
                                   output_path=root / "observed.json")
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["pulse_off_event_count"], 1
            )

    def test_fixed_global_accelerator_pulse_requires_the_frozen_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [10.0, -10.0],
                "source_position_project_mm": [0.0, -55.0, 50.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "flight_scope": "complete_three_dimensional_static_return",
                "accelerator_pulse": {
                    "mode": "fixed_global_time",
                    "pulse_off_time_us": 1.86736875912,
                    "qualification": "frozen_global_time_single_center_diagnostic__bunch_qualification_pending",
                },
            }), encoding="utf-8")
            log = root / "flight.log"
            event = (
                "MRTOF_EVENT accelerator_global_pulse_applied ion=1 "
                "t_us=1.86736875912 scheduled_t_us=1.86736875912 instance=4 "
                "x_mm=0 y_mm=-55 z_mm=-5.7 trigger=fixed_global_time\n"
            )
            log.write_text(event, encoding="utf-8")
            result = analyze_trial(
                log_path=log, trial_receipt_path=receipt,
                output_path=root / "observed.json",
            )
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["mode"], "fixed_global_time"
            )
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["fixed_global_pulse_validation"]["particle_count"],
                1,
            )
            log.write_text(event.replace("1.86736875912 ", "1.88 ", 1), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "common pulse boundary"):
                analyze_trial(
                    log_path=log, trial_receipt_path=receipt,
                    output_path=root / "mismatch.json",
                )

    def test_fixed_global_accelerator_pulse_requires_one_event_per_particle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [10.0, -10.0],
                "source_position_project_mm": [0.0, -55.0, 50.0],
                **self._single_center_source_fields(),
                "source_particle_count": 2,
                "source_cohort": {"role": "test_selection"},
                "source_expected_particle_ids": [1, 2],
                "selected_axial_energy_per_charge_v": 4000.0,
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "flight_scope": "complete_three_dimensional_static_return",
                "accelerator_pulse": {
                    "mode": "fixed_global_time",
                    "pulse_off_time_us": 1.82574136731,
                    "qualification": "complete_bunch_safe_exit_schedule__numerical_convergence_pending",
                },
            }), encoding="utf-8")
            event = (
                "MRTOF_EVENT accelerator_global_pulse_applied ion={ion} "
                "t_us=1.82574136731 scheduled_t_us=1.82574136731 instance=4 "
                "x_mm=0 y_mm=-52.8 z_mm=-5.8 trigger=fixed_global_time\n"
            )
            log = root / "flight.log"
            log.write_text(event.format(ion=1) + event.format(ion=2), encoding="utf-8")
            result = analyze_trial(
                log_path=log, trial_receipt_path=receipt,
                output_path=root / "observed.json",
            )
            validation = result["accelerator_pulse_diagnostic"]["fixed_global_pulse_validation"]
            self.assertEqual(validation["particle_count"], 2)
            self.assertEqual(validation["event_count"], 2)
            log.write_text(event.format(ion=1), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "particle 2 must have exactly one"):
                analyze_trial(
                    log_path=log, trial_receipt_path=receipt,
                    output_path=root / "missing.json",
                )

    def test_bunch_analysis_preserves_a_contiguous_global_id_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [177.0, -179.0],
                "source_particle_count": 2,
                "source_cohort": {"role": "frozen_selection"},
                "source_expected_particle_ids": [97, 98],
                "source_selection": {"particle_id_min": 97, "particle_id_max": 98},
                "selected_axial_energy_per_charge_v": 4000.0,
                "particle_mass_th": 100.0,
                "target_drift_period_ratio": 25.5,
                "accelerator_pulse": {"mode": "static"},
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("status,Fly completed. 2 splats\n", encoding="utf-8")
            cohort = {
                "event_integrity_passed": True,
                "particle_terminal_count": 2,
                "splat_code_histogram": {"1": 1, "-1": 1},
                "all_losses_retained": True,
                "detection_rate": 0.5,
                "target_k_fraction": 0.5,
                "overtone_histogram": {"25": 2},
                "detector_tof_us": [100.0],
                "detector_tof_fwhm_us": None,
                "mass_resolution_t_over_2fwhm": None,
            }
            safe_exits = [
                {"kind": "accelerator_safe_exit", "ion": ion} for ion in (97, 98)
            ]
            with patch.object(two_prism_simion_trial, "parse_events", return_value=safe_exits), \
                    patch.object(two_prism_simion_trial, "summarize_events", return_value=cohort) as summarize:
                result = analyze_trial(
                    log_path=log, trial_receipt_path=receipt,
                    output_path=root / "observation.json",
                )
            self.assertEqual(result["status"], "bunch_observed")
            self.assertTrue(result["cohort_analysis"]["accelerator_safe_exit_complete"])
            self.assertEqual(result["cohort_analysis"]["detection_rate"], 0.5)
            self.assertEqual(result["qualification"], "candidate_bunch_selection_diagnostic__not_formal")
            self.assertEqual(summarize.call_args.kwargs["expected_particle_ids"], (97, 98))
            self.assertEqual(summarize.call_args.args[2], 2)

    def test_one_particle_frozen_selection_uses_bunch_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [177.0, -179.0],
                "source_particle_count": 1,
                "source_cohort": {"role": "frozen_selection"},
                "source_expected_particle_ids": [1],
                "source_selection": {"particle_id_min": 1, "particle_id_max": 1},
                "selected_axial_energy_per_charge_v": 4000.0,
                "particle_mass_th": 524.0,
                "target_drift_period_ratio": 25.5,
                "accelerator_pulse": {"mode": "static"},
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
            cohort = {
                "event_integrity_passed": True,
                "particle_terminal_count": 1,
                "splat_code_histogram": {"1": 1},
                "all_losses_retained": True,
            }
            safe_exit = [{"kind": "accelerator_safe_exit", "ion": 1}]
            with patch.object(two_prism_simion_trial, "parse_events", return_value=safe_exit), \
                    patch.object(two_prism_simion_trial, "summarize_events", return_value=cohort) as summarize:
                result = analyze_trial(
                    log_path=log,
                    trial_receipt_path=receipt,
                    output_path=root / "observation.json",
                )
            self.assertEqual(result["status"], "bunch_observed")
            self.assertIsNone(result["source_release_state"])
            summarize.assert_called_once()
            self.assertEqual(summarize.call_args.kwargs["expected_particle_ids"], (1,))

    def test_complete_trial_reports_L_and_fractional_K_residuals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=-2",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=258.75 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=19 fractional_k=19.014 phase_crossing_t_us=20 phase_crossing_y_mm=0.5 phase_time_residual_us=0.4 phase_period_us=30 t_us=20.4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-2",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=21 x_mm=0 y_mm=-1 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-2 turns=38 central_crossings=38",
            ]) + "\n", encoding="utf-8")
            output = root / "observation.json"
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=output,
            )
            self.assertEqual(result["status"], "full_drift_observed", result)
            self.assertEqual(result["residuals"]["P1_P2_positive_mirror_turn_y_mm"], 0.0)
            self.assertEqual(
                result["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"], 0.0
            )
            self.assertEqual(
                result["p2_low_field_reference_state"]["velocity_mm_per_us"],
                (0.0, 1.0, 2.0),
            )
            self.assertAlmostEqual(result["residuals"]["Stripe_slow_turn_y_minus_L_mm"], -81.25)
            self.assertAlmostEqual(result["residuals"]["Stripe_fractional_K_minus_target"], -6.486)
            self.assertAlmostEqual(
                result["residuals"]["Stripe_preceding_phase_y_minus_origin_mm"], 0.5
            )
            self.assertNotIn("Stripe_target_phase_y_minus_origin_mm", result["residuals"])

    def test_coordinate_return_before_target_phase_is_reported_without_fabricating_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [190.6, -191.94],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=338 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25 fractional_k=25 t_us=20 x_mm=0 y_mm=0 z_mm=101 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=21 x_mm=0 y_mm=-0.15 z_mm=97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40 turns=50 central_crossings=50",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertEqual(result["status"], "full_drift_observed", result)
            self.assertEqual(result["fractional_k"], 25.0)
            self.assertEqual(result["target_phase_y_mm"], None)
            self.assertEqual(
                result["return_topology"], "coordinate_return_before_target_phase"
            )
            self.assertEqual(result["residuals"]["Stripe_fractional_K_minus_target"], -0.5)
            self.assertNotIn("Stripe_target_phase_y_minus_origin_mm", result["residuals"])

    def test_coordinate_return_preserves_later_observed_target_phase_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [190.6, -191.94],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=340.2 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25 fractional_k=25.4 phase_crossing_t_us=100 phase_crossing_y_mm=6 phase_time_residual_us=12 phase_period_us=30 t_us=112 x_mm=0 y_mm=0 z_mm=-160 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40",
                "MRTOF_EVENT target_k_phase_sample ion=1 k=25.5 half_cycles=51 t_us=115 x_mm=0 y_mm=-4.5 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_return ion=1 k=25.5 half_cycles=51 slow_coordinate_residual_mm=-4.5 t_us=115 x_mm=0 y_mm=-4.5 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=120 x_mm=0 y_mm=-53 z_mm=97 vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40 turns=51 central_crossings=51",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertEqual(result["return_topology"], "coordinate_return_before_target_phase")
            self.assertEqual(result["target_phase_y_mm"], -4.5)
            self.assertEqual(
                result["residuals"]["Stripe_target_phase_y_minus_origin_mm"], -4.5
            )

    def test_old_coordinate_return_log_recovers_continuous_k_from_same_side_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [190.6, -191.94],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=338 z_mm=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=24 half_cycles=48 t_us=70 x_mm=0 y_mm=20 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=24.5 half_cycles=49 t_us=85 x_mm=0 y_mm=15 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=25 half_cycles=50 t_us=100 x_mm=0 y_mm=6 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25 fractional_k=25 t_us=109 x_mm=0 y_mm=0 z_mm=101 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=110 x_mm=0 y_mm=-0.15 z_mm=97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40 turns=50 central_crossings=50",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertAlmostEqual(result["fractional_k"], 25.3)
            self.assertIsNone(result["target_phase_y_mm"])
            self.assertEqual(result["preceding_phase_y_mm"], 6.0)
            self.assertEqual(
                result["return_topology"], "coordinate_return_before_target_phase"
            )
            self.assertAlmostEqual(
                result["residuals"]["Stripe_preceding_phase_y_minus_origin_mm"], 6.0
            )
            self.assertNotIn("Stripe_target_phase_y_minus_origin_mm", result["residuals"])

    def test_exact_target_k_phase_return_is_full_drift_and_reports_static_detector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
                "prism_switch": None,
            }), encoding="utf-8")
            return_p2 = "x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=1"
            detector_state = "x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-1"
            target_turn = "x_mm=0 y_mm=0 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0"
            positive_turn = "x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0"
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT accelerator_safe_exit ion=1 t_us=0.5 from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=40 vx_mm_us=0 vy_mm_us=0.043 vz_mm_us=-39",
                "MRTOF_EVENT prism_entry ion=1 n=1 t_us=0.75 x_mm=0 y_mm=-45 z_mm=-90 vx_mm_us=0 vy_mm_us=0.05 vz_mm_us=-38",
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=-2",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=340 z_mm=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=25.5 half_cycles=51 t_us=20 " + target_turn,
                "MRTOF_EVENT target_k_phase_sample ion=1 k=25.5 half_cycles=51 t_us=20 " + target_turn,
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25.5 fractional_k=25.5 "
                "phase_crossing_t_us=20 phase_crossing_y_mm=0 phase_time_residual_us=0 "
                "phase_period_us=1 t_us=20 " + target_turn,
                "MRTOF_EVENT drift_phase_return ion=1 k=25.5 half_cycles=51 t_us=20 " + target_turn,
                "MRTOF_EVENT target_k ion=1 k=25.5 half_cycles=51 t_us=20 x_mm=0 y_mm=0 z_mm=0",
                "MRTOF_EVENT return_p2_entry ion=1 t_us=21 " + return_p2,
                "MRTOF_EVENT return_p2_pass ion=1 t_us=22 " + return_p2,
                "MRTOF_EVENT return_positive_mirror_turn ion=1 t_us=23 " + positive_turn,
                "MRTOF_EVENT detector_plane ion=1 direction_z=-1 t_us=26 " + detector_state,
                "MRTOF_EVENT detector ion=1 direction_z=-1 t_us=26 x_mm=0 y_mm=-50 z_mm=95",
                "MRTOF_EVENT splat ion=1 code=1 t_us=26 x_mm=0 y_mm=-50 z_mm=95 turns=50 central_crossings=50",
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=26 x_mm=0 y_mm=-50 z_mm=95 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-1 turns=50 central_crossings=50",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertEqual(result["status"], "full_drift_observed", result)
            self.assertEqual(result["fractional_k"], 25.5)
            self.assertEqual(result["return_topology"], "exact_target_k_phase_return")
            self.assertEqual(result["residuals"]["Stripe_fractional_K_minus_target"], 0.0)
            self.assertEqual(result["residuals"]["Stripe_target_phase_y_minus_origin_mm"], 0.0)
            source = result["source_release_state"]
            self.assertAlmostEqual(source["kinetic_energy_per_charge_v"], 5.0)
            self.assertEqual(source["direction_project"], [0.0, 1.0, 0.0])
            self.assertNotEqual(source["velocity_mm_per_us"], [0.0, 1.0, 0.0])
            safe_exit = result["accelerator_safe_exit_observation"]
            self.assertEqual(safe_exit["status"], "observed")
            self.assertEqual(
                safe_exit["p1_ordering"], "verified_safe_exit_before_P1_entry"
            )
            self.assertEqual(safe_exit["state"]["velocity_mm_per_us"], [0.0, 0.043, -39.0])
            self.assertEqual(safe_exit["input_log"]["sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
            self.assertEqual(
                safe_exit["trial_identity"]["sha256"], hashlib.sha256(receipt.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                result["static_return_diagnostic"]["status"], "detector_hit",
                result["static_return_diagnostic"],
            )
            self.assertEqual(result["extraction_diagnostic"]["status"], "detector_hit")

    def test_complete_trial_fails_closed_without_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=-2",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=5 x_mm=0 y_mm=1 z_mm=0 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2 turns=0 central_crossings=0",
            ]) + "\n", encoding="utf-8")
            result = analyze_trial(
                log_path=log,
                trial_receipt_path=receipt,
                output_path=root / "observation.json",
            )
            self.assertEqual(
                result["status"],
                "p2_low_field_and_positive_mirror_turn_incomplete",
                result,
            )
            self.assertIn("low-field", result["incomplete_reason"])
            self.assertNotIn(
                "Stripe_fractional_K_minus_target", result.get("residuals", {})
            )
            self.assertEqual(
                result["accelerator_safe_exit_observation"]["status"], "not_observed"
            )

    def test_accelerator_safe_exit_rejects_duplicates_nonfinite_and_wrong_direction(self) -> None:
        trial = {
            "particle_mass_th": 524.0,
            "charge_state": 1,
            "source_time_of_birth_us": 0.0,
        }
        base = {
            "kind": "accelerator_safe_exit", "ion": 1, "t_us": 0.5,
            "from_instance": 3, "to_instance": 1,
            "x_mm": 0.0, "y_mm": -55.0, "z_mm": 40.0,
            "vx_mm_us": 0.0, "vy_mm_us": 0.04, "vz_mm_us": -39.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "flight.log"
            receipt = root / "trial.json"
            log.write_text("event bytes\n", encoding="utf-8")
            receipt.write_text("{}\n", encoding="utf-8")
            duplicate = _accelerator_safe_exit_observation(
                [base, dict(base)], trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(duplicate["status"], "invalid")
            self.assertIsNone(duplicate["state"])
            nonfinite_event = dict(base, x_mm=float("nan"))
            nonfinite = _accelerator_safe_exit_observation(
                [nonfinite_event], trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(nonfinite["status"], "invalid")
            self.assertIsNone(nonfinite["state"])
            wrong_direction = _accelerator_safe_exit_observation(
                [dict(base, vz_mm_us=39.0)], trial,
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(wrong_direction["status"], "invalid")
            self.assertIn(
                "accelerator_safe_exit_must_travel_toward_negative_project_z",
                wrong_direction["errors"],
            )
            invalid_instance = _accelerator_safe_exit_observation(
                [dict(base, from_instance=1)], trial,
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(invalid_instance["status"], "invalid")
            pass_only = _accelerator_safe_exit_observation(
                [base, {
                    "kind": "prism_pass", "ion": 1, "n": 1, "t_us": 0.8,
                    "x_mm": 0.0, "y_mm": -40.0, "z_mm": -101.0,
                    "vx_mm_us": 0.0, "vy_mm_us": 0.05, "vz_mm_us": -38.0,
                }],
                trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(pass_only["status"], "observed")
            self.assertEqual(
                pass_only["p1_ordering"],
                "before_P1_pass_only__P1_entry_not_observed",
            )
            native_exit = _accelerator_safe_exit_observation(
                [dict(base, from_instance=3, to_instance=2)],
                {**trial, "accelerator_instance": 3},
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(native_exit["status"], "observed")
            self.assertEqual(native_exit["state"]["from_instance"], 3)
            pass_before_exit = _accelerator_safe_exit_observation(
                [{
                    "kind": "prism_pass", "ion": 1, "n": 1, "t_us": 0.4,
                    "x_mm": 0.0, "y_mm": -40.0, "z_mm": -101.0,
                    "vx_mm_us": 0.0, "vy_mm_us": 0.05, "vz_mm_us": -38.0,
                }, base],
                trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(pass_before_exit["status"], "invalid")
            self.assertIn(
                "accelerator_safe_exit_does_not_precede_P1_pass",
                pass_before_exit["errors"],
            )
            before_release = _accelerator_safe_exit_observation(
                [base], {**trial, "source_time_of_birth_us": 0.6},
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(before_release["status"], "invalid")
            self.assertIn(
                "accelerator_safe_exit_cannot_precede_source_release",
                before_release["errors"],
            )
            wrong_order = _accelerator_safe_exit_observation(
                [base, {
                    "kind": "prism_entry", "ion": 1, "n": 1, "t_us": 0.4,
                    "x_mm": 0.0, "y_mm": -45.0, "z_mm": -90.0,
                    "vx_mm_us": 0.0, "vy_mm_us": 0.05, "vz_mm_us": -38.0,
                }],
                trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(wrong_order["status"], "invalid")
            self.assertIn("accelerator_safe_exit_does_not_precede_P1", wrong_order["errors"])


if __name__ == "__main__":
    unittest.main()
