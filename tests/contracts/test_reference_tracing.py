"""Independent analytic oracles and state semantics for reference tracing."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import numpy as np

from msplatform.physics import CONSTANTS, GasEnvironment
from msplatform.tracing import preflight, trace_particles


E_CHARGE = 1.602176634e-19
MASS = 100 * 1.66053906660e-27


def recipe(electric, magnetic, charge_state=1):
    return {"schema_version": 3, "frame_id": "lab", "clock": {"basis": "experiment_relative", "unit": "s"},
            "constants": dict(CONSTANTS),
            "gas_environment": GasEnvironment("vacuum").to_dict(),
            "field_source": {"kind": "uniform", "time_dependence": "static",
                             "electric_field_v_m": electric, "magnetic_field_t": magnetic},
            "particle_tracer": "scipy_dop853",
            "species": [{"species_id": "ion", "species_kind": "ion", "mass_kg": MASS,
                         "charge_state": charge_state, "charge_c": charge_state * E_CHARGE}],
            "initial_states": [{"particle_id": 17, "species_id": "ion", "position_m": [0.01, -0.002, 0.003],
                                "velocity_m_s": [1e4, 1300., 200.], "time_s": 2e-7,
                                "mass_kg": MASS, "charge_state": charge_state,
                                "charge_c": charge_state * E_CHARGE, "weight": 2.,
                                "parent_particle_id": None, "lineage_status": "unavailable_initial_snapshot"}],
            "numerics": {"end_time_s": 3.2e-6, "rtol": 1e-11, "position_atol_m": 1e-12,
                         "velocity_atol_m_s": 1e-7, "max_step_s": 5e-8, "sample_count": 31},
            "surfaces": [], "recording": {"trajectory": "sampled"}}


def oracle(p, times, electric, magnetic):
    """Closed solution for E along x and B along z, including B=0."""
    t = times - p["time_s"]
    x0, v0 = np.array(p["position_m"]), np.array(p["velocity_m_s"])
    acceleration = p["charge_c"] / p["mass_kg"] * np.asarray(electric)
    omega = p["charge_c"] / p["mass_kg"] * magnetic[2]
    if omega == 0:
        return x0 + t[:, None] * v0 + .5 * t[:, None]**2 * acceleration, v0 + t[:, None] * acceleration
    drift = np.array([acceleration[1] / omega, -acceleration[0] / omega, 0.])
    u = v0 - drift
    s, c = np.sin(omega * t), np.cos(omega * t)
    position = np.column_stack((x0[0] + drift[0]*t + (u[0]*s + u[1]*(1-c))/omega,
                                x0[1] + drift[1]*t + (u[1]*s - u[0]*(1-c))/omega,
                                x0[2] + v0[2]*t + .5*acceleration[2]*t*t))
    velocity = np.column_stack((drift[0] + u[0]*c + u[1]*s,
                                drift[1] + u[1]*c - u[0]*s, v0[2] + acceleration[2]*t))
    return position, velocity


class ReferenceTracingTests(unittest.TestCase):
    def test_competing_planes_rejected_and_coincident_observation_retained(self):
        detector = {"surface_id": "detector", "component_id": "cell", "electrode_id": None,
                    "axis": 0, "position_m": .02, "kind": "detector"}
        electrode = {"surface_id": "plate", "component_id": "cell", "electrode_id": "plate",
                     "axis": 0, "position_m": .02, "kind": "electrode"}
        observation = {"surface_id": "observation", "component_id": "cell", "electrode_id": None,
                       "axis": 0, "position_m": .02, "kind": "observation"}
        for order in ([detector, electrode], [electrode, detector]):
            r = recipe([0, 0, 0], [0, 0, 0])
            r["surfaces"] = order
            with self.subTest(order=order[0]["kind"]), self.assertRaisesRegex(ValueError, "coincident terminal"):
                trace_particles(r)
        for order in ([detector, observation], [observation, detector]):
            r = recipe([0, 0, 0], [0, 0, 0])
            r["surfaces"] = order
            result = trace_particles(r)
            self.assertEqual(result.terminal_states[0]["physical_outcome"], "detected")
            self.assertEqual({event["surface_id"] for event in result.events}, {"detector", "observation"})

    def test_analytic_oracles_same_experiment_times(self):
        for e, b, z in [([0, 0, 0], [0, 0, 0], 1), ([2000, 0, 0], [0, 0, 0], 1),
                        ([0, 0, 0], [0, 0, .5], 1), ([2000, 0, 0], [0, 0, .5], -1)]:
            with self.subTest(electric=e, magnetic=b, charge=z):
                r = recipe(e, b, z)
                result = trace_particles(r)
                samples = result.trajectories
                position, velocity = oracle(r["initial_states"][0], samples["time_s"], e, b)
                np.testing.assert_allclose(samples["position_m"], position, atol=2e-12, rtol=0)
                np.testing.assert_allclose(samples["velocity_m_s"], velocity, atol=2e-6, rtol=0)
                self.assertEqual(result.execution_status, "succeeded")
                self.assertEqual(result.terminal_states[0]["stop_reason"], "time_limit")
                self.assertEqual(result.terminal_states[0]["physical_outcome"], "unknown")
                self.assertEqual(samples["particle_id"].dtype, np.int64)
                self.assertEqual(samples["time_s"][0], 2e-7)
                self.assertEqual(result.data_integrity["status"], "complete")

    def test_event_attribution_and_zero_hits(self):
        r = recipe([0, 0, 0], [0, 0, 0])
        r["surfaces"] = [{"surface_id": "grid", "component_id": "tube", "electrode_id": "plate",
                          "axis": 0, "position_m": .02, "kind": "electrode"}]
        result = trace_particles(r)
        terminal = result.terminal_states[0]
        self.assertEqual((terminal["physical_outcome"], terminal["stop_reason"]), ("surface_hit", "normal"))
        self.assertEqual((terminal["component_id"], terminal["electrode_id"], terminal["surface_id"]),
                         ("tube", "plate", "grid"))
        self.assertAlmostEqual(terminal["time_s"], 1.2e-6, delta=1e-15)
        self.assertEqual(len(result.events), 1)
        self.assertEqual((result.events[0]["event_sequence"], result.events[0]["crossing_direction"]), (1, 1))
        r["surfaces"][0].update(position_m=1., kind="detector")
        result = trace_particles(r)
        self.assertEqual(result.events, [])
        self.assertEqual(result.execution_status, "succeeded")
        self.assertEqual(result.terminal_states[0]["stop_reason"], "time_limit")

    def test_repeated_surface_crossings_have_order_and_direction(self):
        r = recipe([0, 0, 0], [0, 0, .5])
        r["numerics"].update(end_time_s=3.5e-5, max_step_s=2e-7)
        r["surfaces"] = [{"surface_id": "plane", "component_id": "cell", "electrode_id": None,
                          "axis": 0, "position_m": .015, "kind": "observation"}]
        events = trace_particles(r).events
        self.assertGreaterEqual(len(events), 4)
        self.assertEqual([e["event_sequence"] for e in events], list(range(1, len(events)+1)))
        self.assertEqual([e["crossing_direction"] for e in events[:4]], [1, -1, 1, -1])
        self.assertEqual([e["time_s"] for e in events], sorted(e["time_s"] for e in events))
        self.assertTrue(all(e["surface_id"] == "plane" and e["particle_id"] == 17 for e in events))

    def test_real_overflow_is_reported_as_numerical_failure(self):
        r = recipe([1e308, 0, 0], [0, 0, 0])
        result = trace_particles(r)
        self.assertEqual(result.execution_status, "failed")
        self.assertEqual(result.terminal_states[0]["stop_reason"], "numerical_failure")
        self.assertEqual(result.terminal_states[0]["physical_outcome"], "unknown")
        self.assertIn("FloatingPointError", result.terminal_states[0]["detail"])
        self.assertEqual(result.data_integrity["missing_terminal_particle_ids"], [17])

    def test_cancel_and_solver_failure_keep_cohort(self):
        r = recipe([0, 0, 0], [0, 0, 0])
        r["initial_states"].append({**r["initial_states"][0], "particle_id": 18})
        cancelled = trace_particles(r, cancelled=lambda: True)
        self.assertEqual(cancelled.execution_status, "cancelled")
        self.assertEqual(cancelled.data_integrity["missing_terminal_particle_ids"], [17, 18])
        self.assertFalse(cancelled.terminal_states[0]["started"])
        self.assertIsNone(cancelled.terminal_states[0]["position_m"])
        with patch("msplatform.tracing.solve_ivp") as solve:
            solve.return_value.success = False
            solve.return_value.message = "step failed"
            failed = trace_particles(r)
        self.assertEqual(failed.execution_status, "failed")
        self.assertEqual([x["stop_reason"] for x in failed.terminal_states], ["numerical_failure"] * 2)
        self.assertEqual(failed.data_integrity["mother_count"], 2)

    def test_invalid_combinations_and_identity_fail_before_integration(self):
        original = recipe([0, 0, 0], [0, 0, 0])
        changes = [lambda r: r["field_source"].update(time_dependence="rf"),
                   lambda r: r["field_source"].update(electric_field_kv_m=[1, 0, 0]),
                   lambda r: r["numerics"].update(time_step_us=1),
                   lambda r: r["clock"].update(unit="us"),
                   lambda r: r["gas_environment"].update(status="gas"),
                   lambda r: r["constants"].update(elementary_charge_c=1e-19),
                   lambda r: r["initial_states"][0].update(lineage_status="root"),
                   lambda r: r["gas_environment"].update(collision_model="hs1"),
                   lambda r: r.update(particle_field_coupling="self_consistent"),
                   lambda r: r.update(transport_mode="segmented"),
                   lambda r: r["initial_states"][0].update(charge_c=0),
                   lambda r: r["initial_states"].append(copy.deepcopy(r["initial_states"][0]))]
        for change in changes:
            r = copy.deepcopy(original)
            change(r)
            with self.assertRaises(ValueError):
                preflight(r)


if __name__ == "__main__":
    unittest.main()
