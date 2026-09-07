from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    CandidateContractError,
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
    _seed_profile,
    _solve_dimensionless_paper_target,
    attach_fixed_geometry_parameter_authority,
    build_parameter_authority_from_managed_seed,
)
from common.contracts.file_identity import file_sha256


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class DualStripeL0MathTest(unittest.TestCase):
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
            }},
        }]}
        authority = attach_fixed_geometry_parameter_authority(report)[
            "fixed_geometry_parameter_authority"
        ]
        self.assertTrue(authority["operating_state_publication_gate"]["passed"])
        self.assertEqual(authority["operating_state_publication_gate"]["publishable_mirror_root_indices"], [1])
        self.assertEqual(authority["branch_states"][0]["diagnostic_only_outputs"], [])

    def test_managed_seed_authority_verifies_and_derives_without_rerunning_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_config = root / "run_config.json"
            summary = root / "summary.json"
            run_config.write_text("{}\n", encoding="utf-8")
            summary.write_text(json.dumps({
                "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
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
                "inputs": {},
                "outputs": [record(summary)],
            }) + "\n", encoding="utf-8")
            result = build_parameter_authority_from_managed_seed(manifest)
            self.assertEqual(result["source_operating_seed_run_id"], "managed-seed")
            self.assertFalse(
                result["fixed_geometry_parameter_authority"]
                ["operating_state_publication_gate"]["passed"]
            )
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

    def test_fixed_cad_shapes_fit_structure_without_inventing_L(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        result = identify_fixed_cad_component_shapes(contract)
        fits = result["sampling_convergence"]
        self.assertEqual([item["sampling_multiplier"] for item in fits], [1, 2, 4])
        self.assertNotIn("drift_length_L_mm", fits[-1])
        self.assertEqual(
            result["drift_length_identifiability"]["status"],
            "underdetermined_from_shape_structure_alone",
        )
        self.assertLess(fits[-1]["set_1_rms_residual_mm"], 0.002)
        self.assertLess(fits[-1]["set_2_rms_residual_mm"], 0.0004)
        self.assertEqual(result["time_platform_node_span"]["status"], "pending_independently_closed_L")
        self.assertIn("voltage_solution", result["status"])
        identity = result["theory_identity"]
        self.assertEqual(identity["status"], "paper_relations_preserved__instance_values_pending")
        self.assertIn("drift length L", identity["instance_specific_outputs"])
        self.assertNotIn("original_target_exact_response_compatibility", result)


if __name__ == "__main__":
    unittest.main()
