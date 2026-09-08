from __future__ import annotations

import copy
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_analytic import (
    PrismAnalyticError,
    contract_nominal_stripe_injection_angle_deg,
    derive_two_prism_hard_boundary_seed,
    hard_boundary_bias_v,
    hard_boundary_exit_angle_deg,
    nominal_stripe_injection_angle_deg,
)


class PrismAnalyticTest(unittest.TestCase):
    def test_exact_bias_and_inverse_agree_on_the_small_angle_branch(self) -> None:
        bias = hard_boundary_bias_v(4000, 4.0, 1.8)
        self.assertAlmostEqual(bias, -152.76516286150414)
        self.assertAlmostEqual(hard_boundary_exit_angle_deg(4000, 4.0, bias), 1.8)

    def test_nominal_stripe_angle_uses_declared_l0_values_not_a_project_default(self) -> None:
        self.assertAlmostEqual(
            nominal_stripe_injection_angle_deg(1.48923, 335.0, 641.0, 25),
            1.784,
            places=3,
        )
        with self.assertRaises(PrismAnalyticError):
            nominal_stripe_injection_angle_deg(1.0, 335.0, 641.0, 0)
        with self.assertRaises(PrismAnalyticError):
            nominal_stripe_injection_angle_deg(100.0, 335.0, 641.0, 25)

    def test_contract_angle_requires_completed_project_l0_receipts(self) -> None:
        pending = {"nominal": {"target_oscillation_count": 25}, "dual_stripe_l0": {"status": "joint_inputs_pending"}}
        with self.assertRaises(PrismAnalyticError):
            contract_nominal_stripe_injection_angle_deg(pending)
        complete = {
            "nominal": {"target_oscillation_count": 25},
            "dual_stripe_l0": {
                "status": "joint_l0_l1_candidate",
                "nominal_kappa_1": 1.48923,
                "drift_length_L_mm": 335.0,
                "axial_width_W_mm": 641.0,
                "source_receipts": {
                    "joint_action_period_l1_sha256": "a", "psi_kappa_integral_sha256": "b", "joint_residual_report_sha256": "c",
                },
            },
        }
        self.assertAlmostEqual(contract_nominal_stripe_injection_angle_deg(complete), 1.784, places=3)

    def test_two_prism_seed_uses_ordered_geometric_handoffs(self) -> None:
        contract = {"prism_transport": {"two_prism_injection_l0": {
            "status": "geometry_constrained_hard_boundary_l0",
            "path_topology": "direct_p1_to_p2_without_intervening_mirror",
            "prism_1_electrode_id": 16,
            "prism_2_electrode_id": 17,
            "total_kinetic_energy_ev": 4000,
            "prism_1_local_reference_axis_yz": [0, -1],
            "prism_1_positive_rotation": "clockwise_yz",
            "prism_2_local_reference_axis_yz": [-1, -10],
            "prism_2_positive_rotation": "clockwise_yz",
            "source_focus_reference_yz_mm": [55, 0],
            "prism_1_effective_plane_yz_mm": [55, -10],
            "prism_2_effective_plane_yz_mm": [54, -20],
            "stripe_entrance_reference_yz_mm": [51, -40],
        }}}
        result = derive_two_prism_hard_boundary_seed(contract)
        self.assertEqual(result.prism_1_entry_angle_degrees, 0.0)
        self.assertGreater(result.prism_1_exit_angle_degrees, 0.0)
        self.assertEqual(result.prism_2_entry_angle_degrees, 0.0)
        self.assertGreater(result.prism_2_exit_angle_degrees, 0.0)
        self.assertNotEqual(result.prism_1_bias_v, 0.0)
        self.assertNotEqual(result.prism_2_bias_v, 0.0)

    def test_rejects_missing_or_nonforward_phase_space_contract(self) -> None:
        absent = {"prism_transport": {}}
        with self.assertRaises(PrismAnalyticError):
            derive_two_prism_hard_boundary_seed(absent)
        contract = {"prism_transport": {"two_prism_injection_l0": {
            "status": "geometry_constrained_hard_boundary_l0",
            "path_topology": "direct_p1_to_p2_without_intervening_mirror",
            "prism_1_electrode_id": 16,
            "prism_2_electrode_id": 17,
            "total_kinetic_energy_ev": 4000,
            "prism_1_local_reference_axis_yz": [0, -1],
            "prism_1_positive_rotation": "clockwise_yz",
            "prism_2_local_reference_axis_yz": [-1, -10],
            "prism_2_positive_rotation": "clockwise_yz",
            "source_focus_reference_yz_mm": [55, 0],
            "prism_1_effective_plane_yz_mm": [55, -10],
            "prism_2_effective_plane_yz_mm": [54, -20],
            "stripe_entrance_reference_yz_mm": [51, -40],
        }}}
        bad = copy.deepcopy(contract)
        bad["prism_transport"]["two_prism_injection_l0"]["prism_2_positive_rotation"] = "unknown"
        with self.assertRaises(PrismAnalyticError):
            derive_two_prism_hard_boundary_seed(bad)

    def test_rejects_manufactured_pre_reflection_path(self) -> None:
        contract = {"prism_transport": {"two_prism_injection_l0": {
            "status": "geometry_constrained_hard_boundary_l0",
            "path_topology": "negative_mirror_pre_reflection_between_p1_and_p2",
            "prism_1_electrode_id": 16,
            "prism_2_electrode_id": 17,
            "total_kinetic_energy_ev": 4005,
        }}}
        with self.assertRaisesRegex(PrismAnalyticError, "no-intervening-mirror"):
            derive_two_prism_hard_boundary_seed(contract)


if __name__ == "__main__":
    unittest.main()
