from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    TwoPrismTransportObservation,
    audit_two_prism_voltage_definition,
    observation_from_simion_events,
    prism_handoff_residuals,
)


def _state(position, velocity) -> ProjectPhaseSpaceState:
    return ProjectPhaseSpaceState(tuple(position), tuple(velocity))


def _events() -> list[dict]:
    return [
        {
            "kind": "prism_pass", "ion": 1, "n": 1, "t_us": 1.0,
            "x_mm": 0.0, "y_mm": -50.0, "z_mm": -101.0,
            "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -2.0,
        },
        {
            "kind": "pre_injection_mirror_turn", "ion": 1, "t_us": 2.0,
            "x_mm": 0.0, "y_mm": -35.0, "z_mm": -280.0,
            "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 0.0,
        },
        {
            "kind": "prism_pass", "ion": 1, "n": 2, "t_us": 3.0,
            "x_mm": 0.0, "y_mm": -10.0, "z_mm": 35.0,
            "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 2.0,
        },
        {
            "kind": "p2_low_field_reference", "ion": 1, "t_us": 4.0,
            "x_mm": 0.0, "y_mm": -8.0, "z_mm": 33.0,
            "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 2.0,
        },
        {
            "kind": "pre_origin_positive_mirror_turn", "ion": 1, "t_us": 5.0,
            "x_mm": 0.0, "y_mm": 0.0, "z_mm": 280.0,
            "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 0.0,
        },
        {"kind": "terminal", "ion": 1, "splat": 1},
    ]


class TwoPrismHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project = Path(__file__).resolve().parents[2]
        cls.contract = json.loads(
            (project / "config" / "simion_candidate_two_zone.json").read_text(
                encoding="utf-8"
            )
        )

    def test_current_contract_audits_turn_and_low_field_targets(self) -> None:
        audit = audit_two_prism_voltage_definition(self.contract)
        self.assertEqual(
            audit["status"],
            "two_physical_targets_declared__finite_3d_jacobian_pending",
        )
        self.assertEqual(audit["unknown_count"], 2)
        self.assertEqual(
            audit["handoff_events"],
            [
                "p2_low_field_reference",
                "first_post_P2_positive_mirror_turn",
            ],
        )
        self.assertEqual(audit["target_project_y_mm"], 0.0)
        self.assertIn("Mirror_Stripe", audit["target_tangent_ratio_authority"])
        self.assertIn("diagnostic_only", audit["positive_mirror_turn_z_role"])
        self.assertEqual(
            audit["p2_exit_mechanical_acceptance"]["project_z_open_interval_mm"],
            [-40.0, 40.0],
        )
        self.assertIn(
            "low-field reference",
            audit["p2_exit_mechanical_acceptance"]["semantics"],
        )
        self.assertEqual(
            audit["p2_low_field_reference_section"]["project_z_open_interval_mm"],
            [26.0, 40.0],
        )
        self.assertEqual(
            audit["p2_low_field_reference_section"]["reference_plane_z_mm"],
            33.0,
        )
        self.assertIn(
            "requires_finite_3d",
            audit["p2_low_field_reference_section"]["field_flatness_status"],
        )

    def test_missing_or_nonfinite_function_origin_fails_closed(self) -> None:
        missing = copy.deepcopy(self.contract)
        del missing["dual_stripe_l0"]["theory_function_coordinate_registration"][
            "function_y_zero_project_y_mm"
        ]
        with self.assertRaises(CandidateContractError):
            audit_two_prism_voltage_definition(missing)
        nonfinite = copy.deepcopy(self.contract)
        nonfinite["dual_stripe_l0"]["theory_function_coordinate_registration"][
            "function_y_zero_project_y_mm"
        ] = math.nan
        with self.assertRaises(CandidateContractError):
            audit_two_prism_voltage_definition(nonfinite)

    def test_exact_turn_and_reference_states_have_two_zero_residuals(self) -> None:
        source = _state((0.0, -55.0, 0.0), (0.0, 0.0, -1.0))
        p1 = _state((0.0, -50.0, -101.0), (0.0, 1.0, -2.0))
        reference = _state((0.0, -8.0, 33.0), (0.0, 1.0, 2.0))
        turn = _state((0.0, 0.0, 280.0), (0.0, 1.0, 0.0))
        observation = TwoPrismTransportObservation(source, p1, reference, turn, True)
        residuals = prism_handoff_residuals(
            observation,
            target_positive_mirror_turn_y_mm=0.0,
            target_tangent_ratio_vy_over_vz=0.5,
        )
        self.assertEqual(
            residuals,
            (
                ("P1_P2_positive_mirror_turn_y_mm", 0.0),
                ("P1_P2_P2_shield_low_field_signed_vy_over_vz", 0.0),
            ),
        )

    def test_position_and_signed_direction_residuals_remain_independent(self) -> None:
        source = _state((0.0, -55.0, 0.0), (0.0, 0.0, -1.0))
        p1 = _state((0.0, -50.0, -101.0), (0.0, 1.0, -2.0))
        reference = _state((0.0, -8.0, 33.0), (0.0, 3.0, 2.0))
        turn = _state((0.0, 2.0, 281.0), (0.0, 1.0, 0.0))
        observation = TwoPrismTransportObservation(source, p1, reference, turn, True)
        residuals = dict(prism_handoff_residuals(
            observation,
            target_positive_mirror_turn_y_mm=0.0,
            target_tangent_ratio_vy_over_vz=0.5,
        ))
        self.assertEqual(residuals["P1_P2_positive_mirror_turn_y_mm"], 2.0)
        self.assertEqual(
            residuals["P1_P2_P2_shield_low_field_signed_vy_over_vz"],
            1.0,
        )

    def test_target_tangent_ratio_must_be_positive_and_finite(self) -> None:
        reference = _state((0.0, -8.0, 33.0), (0.0, 1.0, 2.0))
        turn = _state((0.0, 0.0, 280.0), (0.0, 1.0, 0.0))
        observation = TwoPrismTransportObservation(reference, reference, reference, turn, True)
        for value in (0.0, -0.1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(CandidateContractError):
                prism_handoff_residuals(
                    observation,
                    target_positive_mirror_turn_y_mm=0.0,
                    target_tangent_ratio_vy_over_vz=value,
                )

    def test_collision_bad_reference_and_bad_turn_fail_closed(self) -> None:
        source = _state((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
        outbound = _state((0.0, -8.0, 33.0), (0.0, 1.0, 2.0))
        turn = _state((0.0, 0.0, 280.0), (0.0, 1.0, 0.0))
        with self.assertRaises(CandidateContractError):
            TwoPrismTransportObservation(source, source, outbound, turn, False)
        for velocity in ((0.0, -1.0, 2.0), (0.0, 1.0, -2.0)):
            with self.subTest(velocity=velocity), self.assertRaises(CandidateContractError):
                TwoPrismTransportObservation(
                    source,
                    source,
                    _state((0.0, -8.0, 33.0), velocity),
                    turn,
                    True,
                )
        for bad_turn in (
            _state((0.0, 0.0, -280.0), (0.0, 1.0, 0.0)),
            _state((0.0, 0.0, 280.0), (0.0, -1.0, 0.0)),
            _state((0.0, 0.0, 280.0), (0.0, 1.0, 0.1)),
        ):
            with self.assertRaises(CandidateContractError):
                TwoPrismTransportObservation(source, source, outbound, bad_turn, True)

    def test_simion_receipt_keeps_distinct_reference_and_turn_states(self) -> None:
        source = _state((0.0, -55.0, 0.0), (0.0, 0.0, -1.0))
        observation = observation_from_simion_events(_events(), source)
        self.assertEqual(observation.positive_mirror_turn.position_mm[1], 0.0)
        self.assertEqual(
            observation.p2_shield_low_field_reference.velocity_mm_per_us[1:],
            (1.0, 2.0),
        )

    def test_simion_receipt_rejects_bad_sequence_collision_and_missing_state(self) -> None:
        source = _state((0.0, -55.0, 0.0), (0.0, 0.0, -1.0))
        collision = [*_events()[:-1], {"kind": "terminal", "ion": 1, "splat": -1}]
        with self.assertRaises(CandidateContractError):
            observation_from_simion_events(collision, source)

        reordered = copy.deepcopy(_events())
        reordered[3]["t_us"] = 2.5
        with self.assertRaises(CandidateContractError):
            observation_from_simion_events(reordered, source)

        missing_state = copy.deepcopy(_events())
        del missing_state[3]["vy_mm_us"]
        with self.assertRaises(CandidateContractError):
            observation_from_simion_events(missing_state, source)


if __name__ == "__main__":
    unittest.main()
