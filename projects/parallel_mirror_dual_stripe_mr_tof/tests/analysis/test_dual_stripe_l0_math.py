from __future__ import annotations

import json
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    CandidateContractError,
    endpoint_regularized_kappa,
    endpoint_regularized_tau_g,
    identify_fixed_cad_component_shapes,
    invert_nominal_psi_g_response,
    tau_g_derivative_at_turn,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_width_evaluator,
    dual_stripe_width_at_y_mm,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class DualStripeL0MathTest(unittest.TestCase):
    def test_response_inverse_reconstructs_psi_and_g(self) -> None:
        first, second = invert_nominal_psi_g_response(0.8, -0.1, 1.2, 0.9)
        self.assertAlmostEqual(first + second, 0.8)
        self.assertAlmostEqual(1.2 * first + 0.9 * second, -0.1)

    def test_response_inverse_rejects_singular_basis(self) -> None:
        with self.assertRaises(CandidateContractError):
            invert_nominal_psi_g_response(1.0, 1.0, 1.0, 1.0)

    def test_endpoint_regularization_recovers_linear_reference_integral(self) -> None:
        self.assertAlmostEqual(endpoint_regularized_kappa(lambda eta: eta), 2.0, places=8)

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
