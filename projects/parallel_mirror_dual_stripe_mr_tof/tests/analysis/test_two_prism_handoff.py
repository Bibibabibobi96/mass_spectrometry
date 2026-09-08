from __future__ import annotations

import copy
import json
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


class TwoPrismHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project = Path(__file__).resolve().parents[2]
        cls.contract = json.loads(
            (project / "config" / "simion_candidate_two_zone.json").read_text(encoding="utf-8")
        )

    def test_current_contract_uses_event_derived_turn_origin(self) -> None:
        audit = audit_two_prism_voltage_definition(self.contract)
        self.assertEqual(audit["status"], "two_physical_targets_declared__finite_3d_jacobian_pending")
        self.assertEqual(audit["unknown_count"], 2)
        self.assertEqual(len(audit["independent_target_conditions_before_finite_3d_jacobian"]), 2)
        self.assertIsNone(audit["independent_voltage_constraint_rank_before_finite_3d_jacobian"])
        self.assertIsNone(audit["nullity_before_finite_3d_jacobian"])
        self.assertIn("full_column_rank", audit["publication_gate"])
        self.assertEqual(
            audit["p2_exit_mechanical_acceptance"]["project_z_open_interval_mm"],
            [-40.0, 40.0],
        )
        self.assertIn("drift-origin turn", audit["p2_exit_mechanical_acceptance"]["semantics"])

    def test_missing_derived_phase_authority_fails_closed(self) -> None:
        contract = copy.deepcopy(self.contract)
        del contract["prism_transport"]["two_prism_injection_l0"]["drift_phase_origin_authority"]
        with self.assertRaises(CandidateContractError):
            audit_two_prism_voltage_definition(contract)

    def test_fixed_cad_z_cannot_replace_derived_turn(self) -> None:
        contract = copy.deepcopy(self.contract)
        phase = contract["prism_transport"]["two_prism_injection_l0"]["drift_phase_origin_authority"]
        phase["target_project_z_mm"] = -281.9
        with self.assertRaises(CandidateContractError):
            audit_two_prism_voltage_definition(contract)

    def test_exact_state_has_two_zero_independent_components(self) -> None:
        state = _state((0.0, 0.0, 40.0), (0.0, 2.0, 0.0))
        observation = TwoPrismTransportObservation(state, state, state, True)
        slow_energy = 0.5 * 524.0 * 1.66053906660e-27 * (2000.0 ** 2) / 1.602176634e-19
        residuals = prism_handoff_residuals(
            observation,
            target_turn_y_mm=0.0,
            target_slow_kinetic_energy_per_charge_v=slow_energy,
            particle_mass_th=524.0,
            charge_state=1,
        )
        self.assertEqual(len(residuals), 2)
        self.assertTrue(all(value == 0.0 for _name, value in residuals))

    def test_turn_position_and_slow_energy_components_remain_separate(self) -> None:
        source = _state((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
        actual = _state((0.0, 2.0, 30.0), (0.0, 2.0, 0.0))
        observation = TwoPrismTransportObservation(source, source, actual, True)
        residuals = dict(prism_handoff_residuals(
            observation,
            target_turn_y_mm=0.0,
            target_slow_kinetic_energy_per_charge_v=0.0 + 1e-9,
            particle_mass_th=524.0,
            charge_state=1,
        ))
        self.assertEqual(residuals["P1_P2_phase_origin_turn_y_mm"], 2.0)
        self.assertGreater(residuals["P1_P2_slow_kinetic_energy_per_charge_v"], 0.0)

    def test_collision_and_zero_velocity_fail_closed(self) -> None:
        state = _state((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
        with self.assertRaises(CandidateContractError):
            TwoPrismTransportObservation(state, state, state, False)
        with self.assertRaises(CandidateContractError):
            _state((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_simion_event_receipt_uses_first_post_P2_positive_mirror_turn(self) -> None:
        source = _state((0.0, -55.0, 0.0), (0.0, 0.0, -1.0))
        events = [
            {"kind": "prism_pass", "ion": 1, "n": 1, "t_us": 1.0,
             "x_mm": 0.0, "y_mm": -50.0, "z_mm": -101.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -2.0},
            {"kind": "pre_injection_mirror_turn", "ion": 1, "t_us": 2.0,
             "x_mm": 0.0, "y_mm": -35.0, "z_mm": -280.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 0.0},
            {"kind": "prism_pass", "ion": 1, "n": 2, "t_us": 3.0,
             "x_mm": 0.0, "y_mm": -10.0, "z_mm": 97.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 2.0},
            {"kind": "drift_phase_origin", "ion": 1, "t_us": 4.0, "x_mm": 0.0, "y_mm": 0.0, "z_mm": 280.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 0.0},
            {"kind": "terminal", "ion": 1, "splat": 1},
        ]
        observation = observation_from_simion_events(events, source)
        self.assertEqual(observation.drift_phase_origin.position_mm[1], 0.0)
        self.assertGreater(observation.drift_phase_origin.position_mm[2], 0.0)
        collision = [*events[:-1], {"kind": "terminal", "ion": 1, "splat": -1}]
        with self.assertRaises(CandidateContractError):
            observation_from_simion_events(collision, source)


if __name__ == "__main__":
    unittest.main()
