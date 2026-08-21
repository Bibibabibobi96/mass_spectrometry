import unittest

from common.simion.resource_scheduler import plan_adaptive_followup, plan_simion_dispatch


class ResourceSchedulerTests(unittest.TestCase):
    def test_known_rf_profile_uses_memory_and_cpu_caps(self) -> None:
        request = {
            "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 160,
            "particle_count": 5000, "independent_particles": True,
            "maximum_parallel_batches": 8, "reserve_available_memory_bytes": 4,
            "cpu_cores_per_batch": 2, "reserve_cpu_cores": 2,
        }
        profile = {"resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 160}, "per_batch_peak_working_set_bytes": 10}
        plan = plan_simion_dispatch(request, [profile], available_memory_bytes=35, logical_processors=10)
        self.assertEqual(plan["waves"][0]["batch_count"], 2)
        self.assertEqual([batch["count"] for batch in plan["waves"][0]["batches"]], [2500, 2500])
        self.assertEqual(plan["estimation"]["kind"], "nearest_resource_profile")

    def test_unknown_electrostatic_request_bootstraps_then_adapts(self) -> None:
        request = {
            "solver": "SIMION", "field_kind": "electrostatic", "particle_count": 1000,
            "independent_particles": True, "maximum_parallel_batches": 4,
            "reserve_available_memory_bytes": 10, "unknown_per_batch_reservation_bytes": 20,
            "cpu_cores_per_batch": 2, "reserve_cpu_cores": 4,
        }
        bootstrap = plan_simion_dispatch(request, [], available_memory_bytes=100, logical_processors=8)
        self.assertEqual(bootstrap["waves"][0]["kind"], "bootstrap")
        followup = plan_adaptive_followup(bootstrap, 20)
        self.assertEqual(followup["estimation"]["kind"], "observed_bootstrap_peak")
        self.assertEqual(followup["waves"][0]["batch_count"], 2)
        self.assertEqual(followup["limits"]["cpu_cores_per_batch"], 2)

    def test_parallel_request_requires_independent_particles(self) -> None:
        with self.assertRaisesRegex(ValueError, "independent_particles"):
            plan_simion_dispatch({
                "solver": "SIMION", "field_kind": "electrostatic", "particle_count": 2,
                "maximum_parallel_batches": 2, "unknown_per_batch_reservation_bytes": 1,
            }, [], available_memory_bytes=10, logical_processors=2)
