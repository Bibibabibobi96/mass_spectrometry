from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    CandidateContractError,
    endpoint_regularized_kappa,
    invert_nominal_psi_g_response,
)


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


if __name__ == "__main__":
    unittest.main()
