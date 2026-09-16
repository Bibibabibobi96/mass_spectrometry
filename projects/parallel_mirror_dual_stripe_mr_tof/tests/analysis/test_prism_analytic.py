from __future__ import annotations

import copy
import math
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_analytic import (
    PrismAnalyticError,
    contract_nominal_stripe_injection_angle_deg,
    derive_two_prism_hard_boundary_seed,
    hard_boundary_bias_correction_v,
    hard_boundary_bias_for_face_order_and_target_direction_v,
    hard_boundary_bias_v,
    hard_boundary_exit_angle_deg,
    nominal_stripe_injection_angle_deg,
    trace_triangular_hard_boundary_prism,
)


class PrismAnalyticTest(unittest.TestCase):
    @staticmethod
    def _right_angle_trace():
        energy = 4000.0
        alpha_degrees = 4.0
        beta_degrees = 1.8
        incidence = math.radians(45.0 + alpha_degrees)
        direction = (-math.sin(incidence), math.cos(incidence))
        entry = (0.2, 0.0)
        origin = (entry[0] - direction[0], entry[1] - direction[1])
        trace = trace_triangular_hard_boundary_prism(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            origin,
            direction,
            energy,
            hard_boundary_bias_v(energy, alpha_degrees, beta_degrees),
            charge_sign=1,
        )
        return trace, direction, beta_degrees

    def test_exact_bias_and_inverse_agree_on_the_small_angle_branch(self) -> None:
        bias = hard_boundary_bias_v(4000, 4.0, 1.8)
        self.assertAlmostEqual(bias, -152.76516286150414)
        self.assertAlmostEqual(hard_boundary_exit_angle_deg(4000, 4.0, bias), 1.8)

    def test_exact_fixed_entry_angle_bias_correction_matches_two_biases(self) -> None:
        energy = 4375.882431176572
        alpha = 4.0
        actual_beta = 3.1
        target_beta = 1.9371245839921358
        correction = hard_boundary_bias_correction_v(
            energy, actual_beta, target_beta,
        )
        self.assertAlmostEqual(
            hard_boundary_bias_v(energy, alpha, actual_beta) + correction,
            hard_boundary_bias_v(energy, alpha, target_beta),
            places=11,
        )
        self.assertLess(correction, 0.0)

    def test_bias_correction_rejects_nonpositive_energy(self) -> None:
        with self.assertRaises(PrismAnalyticError):
            hard_boundary_bias_correction_v(0.0, 3.0, 2.0)

    def test_face_order_target_direction_solve_recovers_known_bias(self) -> None:
        actual, incident, _beta = self._right_angle_trace()
        recovered = hard_boundary_bias_for_face_order_and_target_direction_v(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            incident,
            actual.resulting_unit_direction_yz,
            actual.incident_kinetic_energy_per_charge_v,
            entry_edge_index=actual.entry_edge_index,
            exit_edge_index=actual.exit_edge_index,
            charge_sign=1,
        )
        self.assertAlmostEqual(recovered, actual.prism_bias_v, places=11)

    def test_face_order_target_direction_solve_is_charge_covariant(self) -> None:
        actual, incident, _beta = self._right_angle_trace()
        recovered = hard_boundary_bias_for_face_order_and_target_direction_v(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            incident,
            actual.resulting_unit_direction_yz,
            actual.incident_kinetic_energy_per_charge_v,
            entry_edge_index=actual.entry_edge_index,
            exit_edge_index=actual.exit_edge_index,
            charge_sign=-1,
        )
        self.assertAlmostEqual(recovered, -actual.prism_bias_v, places=11)

    def test_face_order_target_direction_rejects_wrong_exit_direction(self) -> None:
        actual, incident, _beta = self._right_angle_trace()
        with self.assertRaisesRegex(PrismAnalyticError, "does not leave"):
            hard_boundary_bias_for_face_order_and_target_direction_v(
                [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                incident,
                tuple(-value for value in actual.resulting_unit_direction_yz),
                actual.incident_kinetic_energy_per_charge_v,
                entry_edge_index=actual.entry_edge_index,
                exit_edge_index=actual.exit_edge_index,
                charge_sign=1,
            )

    def test_triangular_trace_regresses_existing_ninety_degree_law(self) -> None:
        trace, _incident, beta_degrees = self._right_angle_trace()
        self.assertEqual(trace.status, "transmitted")
        self.assertEqual(trace.entry_edge_index, 0)
        self.assertEqual(trace.exit_edge_index, 2)
        exit_normal = (-1.0, 0.0)
        exit_incidence = math.degrees(math.acos(sum(
            value * normal for value, normal in zip(trace.resulting_unit_direction_yz, exit_normal)
        )))
        self.assertAlmostEqual(45.0 - exit_incidence, beta_degrees, places=11)
        self.assertAlmostEqual(trace.resulting_kinetic_energy_per_charge_v, 4000.0)
        self.assertAlmostEqual(trace.hamiltonian_residual_per_charge_v, 0.0)
        entry_tangent_before = math.sqrt(trace.incident_kinetic_energy_per_charge_v) * trace.incident_unit_direction_yz[0]
        entry_tangent_after = math.sqrt(trace.inside_kinetic_energy_per_charge_v) * trace.inside_unit_direction_yz[0]
        self.assertAlmostEqual(entry_tangent_before, entry_tangent_after, places=12)
        exit_tangent_before = -math.sqrt(trace.inside_kinetic_energy_per_charge_v) * trace.inside_unit_direction_yz[1]
        exit_tangent_after = -math.sqrt(trace.resulting_kinetic_energy_per_charge_v) * trace.resulting_unit_direction_yz[1]
        self.assertAlmostEqual(exit_tangent_before, exit_tangent_after, places=12)

    def test_triangular_trace_is_rotation_translation_covariant(self) -> None:
        trace, incident, _beta = self._right_angle_trace()
        angle = math.radians(37.0)
        cosine, sine = math.cos(angle), math.sin(angle)

        def rotate(vector):
            return (cosine * vector[0] - sine * vector[1], sine * vector[0] + cosine * vector[1])

        def transform(point):
            rotated = rotate(point)
            return rotated[0] + 12.5, rotated[1] - 8.0

        entry = (0.2, 0.0)
        origin = (entry[0] - incident[0], entry[1] - incident[1])
        moved = trace_triangular_hard_boundary_prism(
            [transform(point) for point in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))],
            transform(origin),
            rotate(incident),
            4000.0,
            trace.prism_bias_v,
            charge_sign=1,
        )
        for actual, expected in zip(moved.entry_point_yz_mm, transform(trace.entry_point_yz_mm)):
            self.assertAlmostEqual(actual, expected, places=12)
        for actual, expected in zip(moved.exit_point_yz_mm, transform(trace.exit_point_yz_mm)):
            self.assertAlmostEqual(actual, expected, places=12)
        for actual, expected in zip(moved.resulting_unit_direction_yz, rotate(trace.resulting_unit_direction_yz)):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_triangular_trace_is_reciprocal(self) -> None:
        forward, incident, _beta = self._right_angle_trace()
        reverse_direction = tuple(-value for value in forward.resulting_unit_direction_yz)
        reverse_origin = tuple(
            point + 1.0e-6 * direction
            for point, direction in zip(forward.exit_point_yz_mm, forward.resulting_unit_direction_yz)
        )
        reverse = trace_triangular_hard_boundary_prism(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            reverse_origin,
            reverse_direction,
            4000.0,
            forward.prism_bias_v,
            charge_sign=1,
        )
        self.assertEqual(reverse.status, "transmitted")
        self.assertEqual((reverse.entry_edge_index, reverse.exit_edge_index), (2, 0))
        for actual, expected in zip(reverse.exit_point_yz_mm, forward.entry_point_yz_mm):
            self.assertAlmostEqual(actual, expected, places=12)
        for actual, expected in zip(reverse.resulting_unit_direction_yz, (-incident[0], -incident[1])):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertAlmostEqual(reverse.hamiltonian_residual_per_charge_v, 0.0)

    def test_triangular_trace_applies_signed_potential_energy(self) -> None:
        positive, incident, _beta = self._right_angle_trace()
        entry = (0.2, 0.0)
        origin = tuple(point - direction for point, direction in zip(entry, incident))
        negative = trace_triangular_hard_boundary_prism(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            origin,
            incident,
            4000.0,
            -positive.prism_bias_v,
            charge_sign=-1,
        )
        self.assertEqual(negative.status, "transmitted")
        self.assertEqual(negative.inside_kinetic_energy_per_charge_v, positive.inside_kinetic_energy_per_charge_v)
        for actual, expected in zip(negative.resulting_unit_direction_yz, positive.resulting_unit_direction_yz):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_triangular_trace_reports_nontransmission_at_either_boundary(self) -> None:
        entry_direction = (math.sqrt(0.9), math.sqrt(0.1))
        entry_point = (0.2, 0.0)
        entry_origin = tuple(point - direction for point, direction in zip(entry_point, entry_direction))
        reflected = trace_triangular_hard_boundary_prism(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            entry_origin,
            entry_direction,
            10.0,
            5.0,
            charge_sign=1,
        )
        self.assertEqual(reflected.status, "reflected_at_entry")
        self.assertIsNone(reflected.exit_point_yz_mm)
        self.assertAlmostEqual(reflected.resulting_unit_direction_yz[0], entry_direction[0])
        self.assertAlmostEqual(reflected.resulting_unit_direction_yz[1], -entry_direction[1])

        internal_direction = (-0.9, math.sqrt(1.0 - 0.9**2))
        internal_entry = (0.1, 0.0)
        internal_origin = tuple(point - direction for point, direction in zip(internal_entry, internal_direction))
        trapped = trace_triangular_hard_boundary_prism(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            internal_origin,
            internal_direction,
            10.0,
            -20.0,
            charge_sign=1,
        )
        self.assertEqual(trapped.status, "internally_reflected_at_first_exit")
        self.assertEqual(trapped.exit_edge_index, 2)
        self.assertAlmostEqual(trapped.hamiltonian_residual_per_charge_v, 0.0)

    def test_triangular_trace_rejects_vertex_tangent_and_invalid_charge(self) -> None:
        triangle = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        with self.assertRaisesRegex(PrismAnalyticError, "vertex|simultaneously"):
            trace_triangular_hard_boundary_prism(
                triangle, (0.5, -1.0), (-0.5, 1.0), 10.0, 0.0, charge_sign=1,
            )
        with self.assertRaisesRegex(PrismAnalyticError, "collinear"):
            trace_triangular_hard_boundary_prism(
                triangle, (-1.0, 0.0), (1.0, 0.0), 10.0, 0.0, charge_sign=1,
            )
        with self.assertRaisesRegex(PrismAnalyticError, "charge_sign"):
            trace_triangular_hard_boundary_prism(triangle, (0.2, -1.0), (0.0, 1.0), 10.0, 0.0, charge_sign=0)

    def test_triangular_trace_rejects_degenerate_nonfinite_and_inside_origins(self) -> None:
        triangle = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        with self.assertRaisesRegex(PrismAnalyticError, "degenerate"):
            trace_triangular_hard_boundary_prism(
                [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)],
                (0.2, -1.0), (0.0, 1.0), 10.0, 0.0, charge_sign=1,
            )
        for energy, bias in ((math.nan, 0.0), (10.0, math.inf)):
            with self.subTest(energy=energy, bias=bias), self.assertRaises(PrismAnalyticError):
                trace_triangular_hard_boundary_prism(
                    triangle, (0.2, -1.0), (0.0, 1.0), energy, bias, charge_sign=1,
                )
        with self.assertRaises(PrismAnalyticError):
            trace_triangular_hard_boundary_prism(
                [(0.0, 0.0), (math.inf, 0.0), (0.0, 1.0)],
                (0.2, -1.0), (0.0, 1.0), 10.0, 0.0, charge_sign=1,
            )
        with self.assertRaisesRegex(PrismAnalyticError, "leaves the selected entry face"):
            trace_triangular_hard_boundary_prism(
                triangle, (0.2, 0.2), (1.0, 0.0), 10.0, 0.0, charge_sign=1,
            )

    def test_nominal_stripe_angle_uses_axial_w_tangent_not_legacy_sine(self) -> None:
        ratio = 1.48923 * 335.0 / (25 * 641.0)
        angle = nominal_stripe_injection_angle_deg(1.48923, 335.0, 641.0, 25)
        self.assertAlmostEqual(angle, math.degrees(math.atan(ratio)), places=12)
        self.assertNotAlmostEqual(angle, math.degrees(math.asin(ratio)), places=5)
        with self.assertRaises(PrismAnalyticError):
            nominal_stripe_injection_angle_deg(1.0, 335.0, 641.0, 0)
        large_ratio = 100.0 * 335.0 / (25 * 641.0)
        self.assertAlmostEqual(
            nominal_stripe_injection_angle_deg(100.0, 335.0, 641.0, 25),
            math.degrees(math.atan(large_ratio)),
        )

    def test_contract_angle_requires_completed_project_l0_receipts(self) -> None:
        phase = {"target_drift_period_ratio": 25.5,
                 "fast_path_symmetry": "opposite_mirror_turn__z_reflected_nonoverlapping"}
        pending = {"nominal": phase, "dual_stripe_l0": {"status": "joint_inputs_pending"}}
        with self.assertRaises(PrismAnalyticError):
            contract_nominal_stripe_injection_angle_deg(pending)
        complete = {
            "nominal": phase,
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
        self.assertAlmostEqual(
            contract_nominal_stripe_injection_angle_deg(complete),
            math.degrees(math.atan(1.48923 * 335.0 / (25.5 * 641.0))),
        )

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
