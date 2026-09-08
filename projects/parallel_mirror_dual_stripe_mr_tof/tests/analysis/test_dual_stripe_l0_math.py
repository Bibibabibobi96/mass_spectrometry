from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    CandidateContractError,
    analyze_dual_stripe_l0,
    derive_manufactured_basis_voltage_seed,
    endpoint_regularized_kappa,
    endpoint_regularized_kappa_at_turn,
    endpoint_regularized_tau_g,
    identify_fixed_cad_component_shapes,
    invert_nominal_psi_g_response,
    kappa_derivative_at_turn,
    paper_dimensionless_condition_residuals,
    tau_g_derivative_at_turn,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_width_evaluator,
    dual_stripe_width_at_y_mm,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_operating_seed import (
    _bias_pair_is_nondegenerate,
    _compare_fixed_profile_to_dimensionless_target,
    _complete_consistency_start_grid,
    _complete_residual_acceptance_receipt,
    _select_diverse_refinement_starts,
    _seed_profile,
    _solve_dimensionless_paper_target,
    _stripe_search_domain,
    attach_fixed_geometry_parameter_authority,
    audit_exact_paper_component_emulation_by_static_stripes,
    build_parameter_authority_from_managed_seed,
)
from common.contracts.file_identity import file_sha256


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class DualStripeL0MathTest(unittest.TestCase):
    def test_complete_residual_acceptance_waits_for_user_authority(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        receipt = _complete_residual_acceptance_receipt(contract, {"r1": 0.0, "r2": 1.0})
        self.assertEqual(receipt["status"], "pending_user_authority")
        self.assertFalse(receipt["passed"])
        self.assertIsNone(receipt["residuals"]["r1"]["absolute_tolerance"])

    def test_active_complete_residual_acceptance_requires_exact_named_mapping(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        authority = contract["dual_stripe_l0"]["complete_consistency_residual_acceptance"]
        authority["status"] = "active"
        authority["absolute_tolerances_by_residual"] = {"r1": 0.1, "r2": 0.2}
        receipt = _complete_residual_acceptance_receipt(contract, {"r1": 0.05, "r2": 0.3})
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt["passed"])
        self.assertTrue(receipt["residuals"]["r1"]["passed"])
        self.assertFalse(receipt["residuals"]["r2"]["passed"])
        authority["absolute_tolerances_by_residual"] = {"r1": 0.1}
        with self.assertRaises(CandidateContractError):
            _complete_residual_acceptance_receipt(contract, {"r1": 0.05, "r2": 0.0})

    def test_complete_consistency_starts_vary_only_the_two_biases(self) -> None:
        profile = {
            "normalized_start_fractions": [-0.5, 0.25, 0.5],
        }
        starts = _complete_consistency_start_grid(profile, 4000.0)
        self.assertEqual(len(starts), 6)
        self.assertTrue(all(start.shape == (2,) for start in starts))
        self.assertIn((-2000.0, 1000.0), [tuple(start) for start in starts])

    def test_complete_search_domain_does_not_consume_historical_prism_energy(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        del contract["prism_transport"]["energy_partition"]
        search_end, sample_count = _stripe_search_domain(contract, _seed_profile(contract))
        self.assertAlmostEqual(search_end, -390.0 / 1.1)
        self.assertGreater(sample_count, 0)

    def test_complete_refinement_selection_keeps_anchor_and_spreads_coordinates(self) -> None:
        screened = [
            (1.0, np.asarray([0.0, 0.0, 0.0])),
            (1.1, np.asarray([0.1, 0.0, 0.0])),
            (1.2, np.asarray([0.0, 0.1, 0.0])),
            (1.3, np.asarray([1.0, 1.0, 1.0])),
            (1.4, np.asarray([-1.0, -1.0, -1.0])),
            (1.5, np.asarray([0.5, -0.5, 0.5])),
            (9.0, np.asarray([100.0, 100.0, 100.0])),
        ]
        selected = _select_diverse_refinement_starts(screened, 3, (1.0, 1.0, 1.0), 2)
        self.assertEqual(selected[0][0], 1.0)
        self.assertEqual({item[0] for item in selected}, {1.0, 1.3, 1.4})
        self.assertTrue(all(item[0] < 9.0 for item in selected))

    def test_contract_separates_paper_relations_from_instance_values(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        authority = contract["theory_parameter_authority"]
        self.assertEqual(authority["governing_relations"], "identical_to_the_paper_model")
        self.assertIn("drift_length_L", authority["instance_specific_values"])
        self.assertIn("mirror_owned_axial_width_W", authority["instance_specific_values"])
        self.assertIn("polynomial_and_linear_coefficients", authority["instance_specific_values"])
        profile = _seed_profile(contract)
        self.assertEqual(
            profile["status"],
            "paper_theory__instance_specific_K_and_spatial_return_seed",
        )

    def test_seed_rejects_effectively_single_stripe_root_without_setting_voltage_scale(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        profile = _seed_profile(contract)
        self.assertFalse(_bias_pair_is_nondegenerate(np.asarray([-0.253, 156.09]), profile, 4000.0))
        self.assertTrue(_bias_pair_is_nondegenerate(np.asarray([-44.25, 120.11]), profile, 4000.0))

    def test_response_inverse_reconstructs_psi_and_g(self) -> None:
        first, second = invert_nominal_psi_g_response(0.8, -0.1, 1.2, 0.9)
        self.assertAlmostEqual(first + second, 0.8)
        self.assertAlmostEqual(1.2 * first + 0.9 * second, -0.1)

    def test_response_inverse_rejects_singular_basis(self) -> None:
        with self.assertRaises(CandidateContractError):
            invert_nominal_psi_g_response(1.0, 1.0, 1.0, 1.0)

    def test_component_basis_assignment_is_structured_and_fails_closed(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        assignment = contract["dual_stripe"]["theory_profile"]["component_basis_assignment"]
        self.assertEqual(assignment["set_1"], "user_confirmed_scaled_original_psi_s_high_order_basis")
        self.assertEqual(assignment["set_2"], "user_confirmed_scaled_original_psi_m_linear_basis")
        self.assertTrue(assignment["termwise_original_paper_geometry_basis_identification"])
        self.assertEqual(
            analyze_dual_stripe_l0(contract, (-40.0, 60.0))["model"],
            "dual_stripe_nominal_response_l0",
        )
        assignment["set_2"] = "unqualified"
        with self.assertRaisesRegex(CandidateContractError, "qualified theory-CAD mapping"):
            analyze_dual_stripe_l0(contract, (-40.0, 60.0))

    def test_endpoint_regularization_recovers_linear_reference_integral(self) -> None:
        self.assertAlmostEqual(endpoint_regularized_kappa(lambda eta: eta), 2.0, places=8)

    def test_kappa_derivative_keeps_one_fixed_profile_normalization(self) -> None:
        self.assertAlmostEqual(endpoint_regularized_kappa_at_turn(lambda eta: eta, 1.21), 2.2, places=8)
        self.assertAlmostEqual(
            kappa_derivative_at_turn(lambda eta: eta, 1.0, step=1e-3),
            1.0,
            places=5,
        )

    def test_endpoint_regularization_rejects_non_turning_profile(self) -> None:
        with self.assertRaises(CandidateContractError):
            endpoint_regularized_kappa(lambda eta: 1.0)

    def test_tau_g_regularization_and_derivative_preserve_the_turning_endpoint(self) -> None:
        self.assertAlmostEqual(endpoint_regularized_tau_g(lambda eta: eta, lambda _eta: 1.0, 1.0), 2.0, places=8)
        self.assertAlmostEqual(
            tau_g_derivative_at_turn(lambda eta: eta, lambda _eta: 1.0, 1.0, step=1e-3),
            1.0,
            places=5,
        )

    def test_paper_printed_coefficients_regress_kappa_and_the_time_platform_operator(self) -> None:
        # These rounded published values are an operator regression only.  They
        # are not active-instance coefficients or acceptance tolerances.
        coefficients = (0.83999, 0.75160, -7.52535, 14.0242, -9.17661, 2.08613)

        def psi(eta: float) -> float:
            return coefficients[0] * eta + sum(
                coefficients[power] * eta**power for power in range(1, 6)
            )

        def g(eta: float) -> float:
            return sum(coefficients[power] * eta**power for power in range(1, 6)) - coefficients[0] * eta

        self.assertAlmostEqual(endpoint_regularized_kappa_at_turn(psi, 1.0), 1.48923, places=5)
        self.assertLess(abs(kappa_derivative_at_turn(psi, 1.0, step=1e-3)), 1e-4)
        self.assertTrue(all(
            abs(tau_g_derivative_at_turn(psi, g, node, step=1e-3)) < 3e-4
            for node in (0.9, 0.95, 1.05, 1.1)
        ))

    def test_six_condition_evaluator_uses_named_project_nodes(self) -> None:
        residuals = paper_dimensionless_condition_residuals(
            (0.83999, 0.75160, -7.52535, 14.0242, -9.17661, 2.08613),
            eta_turn_nodes=(0.9, 0.95, 1.05, 1.1),
            kappa_derivative_step=0.002,
            tau_derivative_step=0.001,
        )
        self.assertEqual(
            [name for name, _value in residuals],
            [
                "nominal_turn_normalization",
                "spatial_return_kappa_prime",
                "time_platform_tau_g_prime_eta_0.9",
                "time_platform_tau_g_prime_eta_0.95",
                "time_platform_tau_g_prime_eta_1.05",
                "time_platform_tau_g_prime_eta_1.1",
            ],
        )
        self.assertLess(np.linalg.norm([value for _name, value in residuals]), 4e-4)

    def test_dimensionless_target_is_solved_not_copied_from_printed_coefficients(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        result = _solve_dimensionless_paper_target(contract)
        selected = result["selected_root"]
        reference = contract["dual_stripe_l0"]["dimensionless_paper_target"][
            "published_printed_reference_c0_to_c5"
        ]
        self.assertEqual(result["status"], "six_paper_conditions_solved_for_project_nodes")
        self.assertLess(selected["residual_norm_2"], 1e-7)
        self.assertNotEqual(selected["coefficients_c0_to_c5"], reference)
        self.assertEqual(len(result["reproducible_seed_sha256"]), 64)
        coefficients = selected["coefficients_c0_to_c5"]
        self.assertAlmostEqual(
            selected["psi_coefficients_by_power"][0], coefficients[0] + coefficients[1]
        )
        self.assertAlmostEqual(
            selected["g_coefficients_by_power"][0], coefficients[1] - coefficients[0]
        )

    def test_fixed_profile_comparison_exposes_the_linear_response_shortfall(self) -> None:
        consistency = {"best_iterate": {"dimensionless_psi_g_polynomial_fit": {
            "psi_coefficients_by_power": [3.0, -5.0, 4.0, -1.0, 0.1],
            "g_coefficients_by_power": [3.1, -4.9, 3.9, -0.9, 0.09],
        }}}
        target = {"selected_root": {
            "coefficients_c0_to_c5": [0.8, 0.7, -7.0, 14.0, -9.0, 2.0],
            "psi_coefficients_by_power": [1.5, -7.0, 14.0, -9.0, 2.0],
            "g_coefficients_by_power": [-0.1, -7.0, 14.0, -9.0, 2.0],
        }}
        _compare_fixed_profile_to_dimensionless_target(consistency, target)
        comparison = consistency["best_iterate"]["dimensionless_target_comparison"]
        self.assertAlmostEqual(comparison["actual_equivalent_c0_from_linear_psi_g"], -0.05)
        self.assertAlmostEqual(comparison["target_c0"], 0.8)
        self.assertGreater(comparison["scaled_psi_g_coefficient_difference_norm_2"], 1.0)

    def test_static_two_stripes_cannot_exactly_emulate_paper_component_signs(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        target = _solve_dimensionless_paper_target(contract)
        audit = audit_exact_paper_component_emulation_by_static_stripes(target)
        self.assertTrue(audit["optimizer_independent"])
        self.assertEqual(audit["required_response_factors"]["set_1_high_order_h"], 1.0)
        self.assertEqual(audit["required_response_factors"]["set_2_linear_h"], -1.0)
        self.assertEqual(
            audit["status"],
            "not_equivalent_to_exact_original_paper_component_decomposition",
        )
        self.assertFalse(audit["gates_active_fixed_hardware_operating_state"])

    def test_fixed_geometry_authority_withholds_incompatible_angle_and_energies(self) -> None:
        report = {"complete_fixed_hardware_root_family": [{
            "mirror_root_index": 0,
            "complete_fixed_hardware_search": {"best_iterate": {
                "determination": {"status": "locally_incompatible"},
                "nominal_injection_angle_degrees": 1.2,
                "derived_drift_kinetic_energy_per_charge_v": 2.0,
                "derived_fast_reflection_energy_per_charge_v": 3998.0,
            }},
        }]}
        authority = attach_fixed_geometry_parameter_authority(report)[
            "fixed_geometry_parameter_authority"
        ]
        self.assertEqual(authority["geometry_alone"]["status"], "underdetermined")
        self.assertFalse(authority["operating_state_publication_gate"]["passed"])
        self.assertIsNone(authority["operating_state_publication_gate"]["published_operating_state"])
        self.assertIn(
            "nominal_injection_angle_degrees",
            authority["branch_states"][0]["diagnostic_only_outputs"],
        )

    def test_fixed_geometry_authority_opens_only_for_compatible_full_rank_branch(self) -> None:
        report = {"complete_fixed_hardware_root_family": [{
            "mirror_root_index": 1,
            "complete_fixed_hardware_search": {"best_iterate": {
                "determination": {"status": "overdetermined_consistent"},
                "residual_acceptance": {"passed": True},
            }},
        }]}
        authority = attach_fixed_geometry_parameter_authority(report)[
            "fixed_geometry_parameter_authority"
        ]
        self.assertTrue(authority["operating_state_publication_gate"]["passed"])
        self.assertEqual(authority["operating_state_publication_gate"]["publishable_mirror_root_indices"], [1])
        self.assertEqual(authority["branch_states"][0]["diagnostic_only_outputs"], [])

    def test_reference_component_non_equivalence_does_not_override_active_hardware(self) -> None:
        report = {
            "exact_paper_component_emulation_audit": {
                "status": "not_equivalent_to_exact_original_paper_component_decomposition",
                "gates_active_fixed_hardware_operating_state": False,
            },
            "complete_fixed_hardware_root_family": [{
                "mirror_root_index": 1,
                "complete_fixed_hardware_search": {"best_iterate": {
                    "determination": {"status": "overdetermined_consistent"},
                    "residual_acceptance": {"passed": True},
                }},
            }],
        }
        gate = attach_fixed_geometry_parameter_authority(report)[
            "fixed_geometry_parameter_authority"
        ]["operating_state_publication_gate"]
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["status"], "passed")

    def test_full_rank_without_residual_acceptance_cannot_publish(self) -> None:
        report = {"complete_fixed_hardware_root_family": [{
            "mirror_root_index": 1,
            "complete_fixed_hardware_search": {"best_iterate": {
                "determination": {"status": "overdetermined_consistent"},
            }},
        }]}
        authority = attach_fixed_geometry_parameter_authority(report)[
            "fixed_geometry_parameter_authority"
        ]
        self.assertFalse(authority["operating_state_publication_gate"]["passed"])
        self.assertEqual(
            authority["operating_state_publication_gate"]["status"],
            "failed_no_residual_accepted_full_rank_branch",
        )
        self.assertFalse(authority["branch_states"][0]["residual_acceptance_passed"])
        self.assertEqual(
            authority["branch_states"][0]["residual_acceptance_status"], "unavailable",
        )

    def test_parameter_authority_reports_pending_user_residual_tolerances(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        report = {"complete_fixed_hardware_root_family": [{
            "mirror_root_index": 1,
            "complete_fixed_hardware_search": {"best_iterate": {
                "determination": {"status": "overdetermined_consistent"},
                "raw_residuals": {"target_oscillation_count": 0.0},
            }},
        }]}
        authority = attach_fixed_geometry_parameter_authority(report, contract)[
            "fixed_geometry_parameter_authority"
        ]
        self.assertEqual(
            authority["branch_states"][0]["residual_acceptance_status"],
            "pending_user_authority",
        )
        self.assertFalse(authority["operating_state_publication_gate"]["passed"])

    def test_managed_seed_authority_verifies_and_derives_without_rerunning_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_config = root / "run_config.json"
            summary = root / "summary.json"
            contract = root / "simion_candidate_two_zone.json"
            run_config.write_text("{}\n", encoding="utf-8")
            contract.write_text(CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
            summary.write_text(json.dumps({
                "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
                "dimensionless_paper_target": {"selected_root": {
                    "coefficients_c0_to_c5": [0.8, 0.7, -7.0, 14.0, -9.0, 2.0],
                    "psi_coefficients_by_power": [1.5, -7.0, 14.0, -9.0, 2.0],
                    "g_coefficients_by_power": [-0.1, -7.0, 14.0, -9.0, 2.0],
                }},
                "complete_fixed_hardware_root_family": [{
                    "mirror_root_index": 0,
                    "complete_fixed_hardware_search": {"best_iterate": {
                        "determination": {"status": "locally_incompatible"},
                    }},
                }],
            }) + "\n", encoding="utf-8")

            def record(path: Path) -> dict[str, object]:
                return {
                    "path": str(path),
                    "exists": True,
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }

            manifest = root / "run_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 2,
                "run_id": "managed-seed",
                "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "dual_stripe_paper_theory_instance_seed",
                "status": "success",
                "run_config": record(run_config),
                "inputs": {"downstream_contract": record(contract)},
                "outputs": [record(summary)],
            }) + "\n", encoding="utf-8")
            result = build_parameter_authority_from_managed_seed(manifest)
            self.assertEqual(result["source_operating_seed_run_id"], "managed-seed")
            self.assertFalse(
                result["fixed_geometry_parameter_authority"]
                ["operating_state_publication_gate"]["passed"]
            )
            self.assertEqual(
                result["fixed_geometry_parameter_authority"]
                ["operating_state_publication_gate"]["status"],
                "failed_no_residual_accepted_full_rank_branch",
            )
            self.assertEqual(
                result["two_prism_voltage_definition"]["status"],
                "structurally_underdetermined_missing_fast_phase",
            )
            bound = result["fixed_geometry_parameter_authority"]["geometry_alone"][
                "derived_feasibility_bound"
            ]
            self.assertAlmostEqual(bound["maximum_abs_drift_length_L_mm"], 390.0 / 1.1)
            self.assertEqual(
                bound["derivation"],
                "manufactured-design |L| <= active_length/max(eta_turn_nodes)",
            )
            self.assertEqual(bound["manufactured_design_abs_drift_length_L_mm"], 340.0)
            summary.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "integrity failed"):
                build_parameter_authority_from_managed_seed(manifest)

    def test_compiled_native_width_matches_the_reference_accessor(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        for set_name in ("set_1", "set_2"):
            compiled = compile_dual_stripe_width_evaluator(contract, set_name)
            for y_mm in (-390.0, -350.0, -200.0, -1.0, 0.0):
                self.assertAlmostEqual(
                    compiled(y_mm),
                    dual_stripe_width_at_y_mm(contract, set_name, y_mm),
                    places=11,
                )

    def test_fixed_cad_shapes_fit_structure_and_consume_manufactured_L(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        result = identify_fixed_cad_component_shapes(contract)
        fits = result["sampling_convergence"]
        self.assertEqual([item["sampling_multiplier"] for item in fits], [1, 2, 4])
        self.assertNotIn("drift_length_L_mm", fits[-1])
        self.assertEqual(
            result["drift_length_identifiability"]["status"],
            "fixed_by_manufactured_design_contract",
        )
        self.assertLess(fits[-1]["set_1_rms_residual_mm"], 0.002)
        self.assertLess(fits[-1]["set_2_rms_residual_mm"], 0.0004)
        self.assertEqual(result["time_platform_node_span"]["status"], "covered_by_manufactured_L_span_check")
        self.assertIn("voltage_inverse_ready", result["status"])
        identity = result["theory_identity"]
        self.assertEqual(identity["status"], "user_confirmed_original_geometry_bases__voltage_inverse_ready")
        self.assertIn("drift length L", identity["instance_specific_outputs"])
        self.assertNotIn("original_target_exact_response_compatibility", result)

    def test_manufactured_basis_inverse_derives_nominal_biases_and_reports_K_residual(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        coefficients = contract["dual_stripe_l0"]["dimensionless_paper_target"][
            "published_printed_reference_c0_to_c5"
        ]
        result = derive_manufactured_basis_voltage_seed(
            contract,
            mirror_axial_width_w_mm=586.9393396818346,
            basis_coefficients_c0_to_c5=coefficients,
        )
        self.assertAlmostEqual(result["nominal_kappa_1"], 1.4892272348, places=9)
        self.assertAlmostEqual(result["derived_drift_kinetic_energy_per_charge_v"], 5.0)
        self.assertAlmostEqual(result["derived_fast_reflection_energy_per_charge_v"], 4000.0)
        self.assertAlmostEqual(result["stripe_biases_v"][0], -50.68774291, places=6)
        self.assertAlmostEqual(result["stripe_biases_v"][1], 100.39148140, places=6)
        self.assertAlmostEqual(result["predicted_continuous_oscillation_count"], 24.41534840, places=7)
        exact_k = result["nominal_center_exact_K_design_equation"]
        self.assertEqual(exact_k["equation"], "T_D(theta_0)/T_0=K")
        self.assertEqual(exact_k["target_K"], 25)
        self.assertAlmostEqual(exact_k["residual"], -0.58465160, places=7)
        self.assertEqual(exact_k["status"], "unsatisfied_by_current_analytic_inputs")
        topology = result["nominal_center_oscillation_topology"]
        self.assertEqual(topology["nearest_integer_K"], 24)
        self.assertEqual(topology["target_K_interval_lower_exclusive"], 24.5)
        self.assertEqual(topology["target_K_interval_upper_exclusive"], 25.5)
        self.assertAlmostEqual(topology["signed_minimum_boundary_margin"], -0.08465160, places=7)
        self.assertFalse(topology["target_K_interval_passed"])
        self.assertAlmostEqual(result["mirror_axial_width_required_for_exact_K_mm"], 573.21313868, places=7)
        self.assertEqual(
            result["definition_classification"]["status"],
            "current_mirror_root_fails_center_exact_K_and_target_topology",
        )
        self.assertLess(max(abs(value) for value in result["shape_scale_reconstruction_residual_mm"]), 1e-10)

    def test_manufactured_basis_inverse_fails_closed_on_energy_partition_mismatch(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["prism_transport"]["energy_partition"]["total_kinetic_energy_ev"] = 4000
        with self.assertRaisesRegex(CandidateContractError, "equal drift energy plus"):
            derive_manufactured_basis_voltage_seed(
                contract,
                mirror_axial_width_w_mm=586.9393396818346,
                basis_coefficients_c0_to_c5=(0.83999, 0.75160, -7.52535, 14.0242, -9.17661, 2.08613),
            )


if __name__ == "__main__":
    unittest.main()
