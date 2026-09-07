from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    TwoPrismTransportObservation,
    observation_from_simion_events,
    stripe_handoff_residuals,
)


def _state(position, velocity) -> ProjectPhaseSpaceState:
    return ProjectPhaseSpaceState(tuple(position), tuple(velocity))


class TwoPrismHandoffTest(unittest.TestCase):
    def test_exact_state_has_five_zero_independent_components(self) -> None:
        state = _state((0.0, -20.0, -40.0), (0.0, -2.0, -10.0))
        observation = TwoPrismTransportObservation(state, state, state, state, True)
        residuals = stripe_handoff_residuals(observation, state.position_mm, state.unit_direction_project)
        self.assertEqual(len(residuals), 5)
        self.assertTrue(all(value == 0.0 for _name, value in residuals))

    def test_position_and_two_direction_components_remain_separate(self) -> None:
        source = _state((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
        actual = _state((1.0, 2.0, 3.0), (1.0, 0.0, -1.0))
        observation = TwoPrismTransportObservation(source, source, source, actual, True)
        residuals = dict(stripe_handoff_residuals(observation, (0.0, 0.0, 0.0), (0.0, 0.0, -1.0)))
        self.assertEqual(residuals["P1_P2_to_Stripe_position_x_mm"], 1.0)
        self.assertEqual(residuals["P1_P2_to_Stripe_position_y_mm"], 2.0)
        self.assertEqual(residuals["P1_P2_to_Stripe_position_z_mm"], 3.0)
        self.assertGreater(
            abs(residuals["P1_P2_to_Stripe_direction_tangent_1"])
            + abs(residuals["P1_P2_to_Stripe_direction_tangent_2"]),
            0.0,
        )

    def test_collision_and_zero_velocity_fail_closed(self) -> None:
        state = _state((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
        with self.assertRaises(CandidateContractError):
            TwoPrismTransportObservation(state, state, state, state, False)
        with self.assertRaises(CandidateContractError):
            _state((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_simion_event_receipt_uses_p2_y0_exit_without_an_internal_plane(self) -> None:
        source = _state((0.0, 55.0, 0.0), (0.0, 0.0, -1.0))
        events = [
            {"kind": "p1_plane", "ion": 1, "x_mm": 0.0, "y_mm": 50.0, "z_mm": -101.0,
             "vx_mm_us": 0.0, "vy_mm_us": -1.0, "vz_mm_us": -2.0},
            {"kind": "p2_to_stripe", "ion": 1, "x_mm": 0.0, "y_mm": 0.0, "z_mm": -10.0,
             "vx_mm_us": 0.0, "vy_mm_us": -1.0, "vz_mm_us": -2.0},
            {"kind": "terminal", "ion": 1, "splat": 1},
        ]
        observation = observation_from_simion_events(events, source)
        self.assertEqual(observation.prism_2, observation.stripe_entrance)
        self.assertEqual(observation.stripe_entrance.position_mm[1], 0.0)
        collision = [*events[:-1], {"kind": "terminal", "ion": 1, "splat": -1}]
        with self.assertRaises(CandidateContractError):
            observation_from_simion_events(collision, source)


if __name__ == "__main__":
    unittest.main()
