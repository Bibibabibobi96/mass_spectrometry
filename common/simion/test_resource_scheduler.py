import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.simion.resource_scheduler import plan_adaptive_followup, plan_simion_dispatch


class ResourceSchedulerTests(unittest.TestCase):
    @staticmethod
    def rf_request(**overrides: object) -> dict[str, object]:
        request: dict[str, object] = {
            "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            "particle_count": 100, "independent_particles": True,
            "maximum_parallel_batches": 8, "unknown_per_batch_reservation_bytes": 10,
            "cpu_cores_per_batch": 1, "reserve_cpu_cores": 0,
        }
        request.update(overrides)
        return request

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

    def test_omitted_parallel_cap_uses_measured_host_capacity(self) -> None:
        request = {
            "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            "particle_count": 100, "independent_particles": True,
            "cpu_cores_per_batch": 2, "reserve_cpu_cores": 2,
        }
        profile = {
            "resource_identity": {
                "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            },
            "per_batch_peak_working_set_bytes": 10,
        }
        plan = plan_simion_dispatch(
            request, [profile], available_memory_bytes=100, logical_processors=10
        )
        self.assertEqual(plan["limits"]["maximum_parallel_batches"], 100)
        self.assertEqual(plan["limits"]["memory_safety_numerator"], 105)
        self.assertEqual(plan["limits"]["memory_safety_denominator"], 100)
        self.assertEqual(plan["waves"][0]["batch_count"], 4)

    def test_omitted_parallel_cap_keeps_unobservable_memory_conservative(self) -> None:
        request = {
            "solver": "SIMION", "field_kind": "electrostatic", "particle_count": 100,
            "independent_particles": True,
        }
        profile = {
            "resource_identity": {"solver": "SIMION", "field_kind": "electrostatic"},
            "per_batch_peak_working_set_bytes": 1,
        }
        with patch(
            "common.simion.resource_scheduler.available_physical_memory_bytes",
            return_value=None,
        ):
            plan = plan_simion_dispatch(request, [profile], logical_processors=16)
        self.assertEqual(plan["waves"][0]["batch_count"], 1)

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

    def test_unknown_bootstrap_can_avoid_an_unverified_memory_estimate(self) -> None:
        request = {
            "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            "particle_count": 1000, "independent_particles": True,
            "maximum_parallel_batches": 8, "reserve_available_memory_bytes": 10,
            "cpu_cores_per_batch": 2, "reserve_cpu_cores": 2,
            "memory_safety_numerator": 105, "memory_safety_denominator": 100,
        }
        bootstrap = plan_simion_dispatch(
            request, [], available_memory_bytes=100, logical_processors=10
        )
        self.assertIsNone(bootstrap["estimation"]["bootstrap_reservation_bytes"])
        self.assertEqual(
            bootstrap["estimation"]["memory_selection_reason"],
            "no_unverified_memory_estimate",
        )
        followup = plan_adaptive_followup(bootstrap, 20)
        self.assertEqual(followup["estimation"]["reserved_peak_bytes"], 21)
        self.assertEqual(followup["waves"][0]["batch_count"], 4)

    def test_parallel_request_requires_independent_particles(self) -> None:
        with self.assertRaisesRegex(ValueError, "independent_particles"):
            plan_simion_dispatch({
                "solver": "SIMION", "field_kind": "electrostatic", "particle_count": 2,
                "maximum_parallel_batches": 2, "unknown_per_batch_reservation_bytes": 1,
            }, [], available_memory_bytes=10, logical_processors=2)

    def test_simulated_known_profile_improves_over_fixed_two_batch_policy(self) -> None:
        """A balanced independent-particle model must use available safe lanes."""
        request = {
            "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            "particle_count": 8000, "independent_particles": True,
            "default_parallel_batches": 2, "maximum_parallel_batches": 8,
            "reserve_available_memory_bytes": 4, "cpu_cores_per_batch": 1,
        }
        profile = {
            "resource_identity": {
                "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            },
            "per_batch_peak_working_set_bytes": 10,
        }
        plan = plan_simion_dispatch(
            request, [profile], available_memory_bytes=52, logical_processors=8,
        )
        selected = plan["waves"][0]["batch_count"]
        self.assertEqual(selected, 4)  # floor((52 - 4) / ceil(10 * 1.05))
        fixed_policy_makespan = 8000 / 2
        adaptive_makespan = max(batch["count"] for batch in plan["waves"][0]["batches"])
        self.assertEqual(adaptive_makespan, 8000 / selected)
        self.assertEqual(fixed_policy_makespan / adaptive_makespan, 2.0)

    def test_simulated_capacity_never_exceeds_memory_or_cpu(self) -> None:
        for available, processors in ((30, 32), (100, 3), (100, 32)):
            with self.subTest(available=available, processors=processors):
                request = {
                    "solver": "SIMION", "field_kind": "electrostatic",
                    "particle_count": 1000, "independent_particles": True,
                    "maximum_parallel_batches": 16, "reserve_available_memory_bytes": 5,
                    "cpu_cores_per_batch": 2, "reserve_cpu_cores": 1,
                }
                profile = {
                    "resource_identity": {"solver": "SIMION", "field_kind": "electrostatic"},
                    "per_batch_peak_working_set_bytes": 10,
                }
                plan = plan_simion_dispatch(
                    request, [profile], available_memory_bytes=available,
                    logical_processors=processors,
                )
                selected = plan["waves"][0]["batch_count"]
                reserved_peak = plan["estimation"]["reserved_peak_bytes"]
                self.assertLessEqual(selected * reserved_peak + 5, available)
                self.assertLessEqual(selected * 2 + 1, processors)

    def test_unrelated_field_profile_is_not_treated_as_history(self) -> None:
        profile = {
            "resource_identity": {"solver": "SIMION", "field_kind": "electrostatic"},
            "per_batch_peak_working_set_bytes": 1,
        }
        plan = plan_simion_dispatch(
            self.rf_request(), [profile], available_memory_bytes=100, logical_processors=8,
        )
        self.assertEqual(plan["estimation"]["kind"], "unknown_resource_profile_bootstrap")
        self.assertEqual(plan["waves"][0]["batch_count"], 1)

    def test_nearest_matching_profile_prefers_larger_peak_on_a_tie(self) -> None:
        profiles = [
            {"resource_identity": {"solver": "SIMION", "field_kind": "rf"}, "per_batch_peak_working_set_bytes": 10},
            {"resource_identity": {"solver": "SIMION", "field_kind": "rf"}, "per_batch_peak_working_set_bytes": 12},
        ]
        plan = plan_simion_dispatch(
            self.rf_request(), profiles, available_memory_bytes=100, logical_processors=8,
        )
        self.assertEqual(plan["estimation"]["observed_peak_bytes"], 12)
        self.assertEqual(plan["estimation"]["kind"], "nearest_resource_profile")

    def test_unknown_bootstrap_fails_closed_when_reservation_does_not_fit(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown SIMION bootstrap"):
            plan_simion_dispatch(
                self.rf_request(reserve_available_memory_bytes=5, unknown_per_batch_reservation_bytes=10),
                [], available_memory_bytes=14, logical_processors=8,
            )

    def test_cpu_reserve_must_leave_room_for_one_complete_batch(self) -> None:
        profile = {
            "resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40},
            "per_batch_peak_working_set_bytes": 1,
        }
        with self.assertRaisesRegex(ValueError, "available CPU cores"):
            plan_simion_dispatch(
                self.rf_request(cpu_cores_per_batch=2, reserve_cpu_cores=3),
                [profile], available_memory_bytes=100, logical_processors=4,
            )

    def test_memory_safety_ceiling_rounds_up_and_bounds_parallelism(self) -> None:
        profile = {
            "resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40},
            "per_batch_peak_working_set_bytes": 10,
        }
        plan = plan_simion_dispatch(
            self.rf_request(memory_safety_numerator=101, memory_safety_denominator=100),
            [profile], available_memory_bytes=21, logical_processors=8,
        )
        self.assertEqual(plan["estimation"]["reserved_peak_bytes"], 11)
        self.assertEqual(plan["waves"][0]["batch_count"], 1)

    def test_missing_host_memory_uses_authorized_default_not_maximum(self) -> None:
        profile = {
            "resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40},
            "per_batch_peak_working_set_bytes": 10,
        }
        with patch(
            "common.simion.resource_scheduler.available_physical_memory_bytes",
            return_value=None,
        ):
            plan = plan_simion_dispatch(
                self.rf_request(default_parallel_batches=3), [profile],
                logical_processors=8,
            )
        self.assertEqual(plan["waves"][0]["batch_count"], 3)
        self.assertEqual(plan["estimation"]["memory_selection_reason"], "host_memory_unavailable_use_authorized_cap")

    def test_particle_count_caps_lanes_and_all_ids_are_contiguous(self) -> None:
        profile = {
            "resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40},
            "per_batch_peak_working_set_bytes": 1,
        }
        plan = plan_simion_dispatch(
            self.rf_request(particle_count=3, maximum_parallel_batches=8),
            [profile], available_memory_bytes=100, logical_processors=16,
        )
        batches = plan["waves"][0]["batches"]
        self.assertEqual(plan["waves"][0]["batch_count"], 3)
        self.assertEqual([(item["particle_id_min"], item["particle_id_max"]) for item in batches], [(1, 1), (2, 2), (3, 3)])

    def test_rf_and_electrostatic_contract_misuse_is_rejected(self) -> None:
        invalid = (
            self.rf_request(rf_steps_per_period=0),
            self.rf_request(rf_steps_per_period=True),
            {**self.rf_request(), "field_kind": "electrostatic", "rf_steps_per_period": 40},
            self.rf_request(solver="COMSOL"),
            self.rf_request(field_kind="magnetic"),
            self.rf_request(default_parallel_batches=9),
        )
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                plan_simion_dispatch(request, [], available_memory_bytes=100, logical_processors=8)

    def test_adaptive_followup_preserves_rf_identity_and_measured_peak(self) -> None:
        bootstrap = plan_simion_dispatch(
            self.rf_request(maximum_parallel_batches=4), [],
            available_memory_bytes=100, logical_processors=8,
        )
        followup = plan_adaptive_followup(bootstrap, 20)
        self.assertEqual(followup["field_kind"], "rf")
        self.assertEqual(followup["resource_identity"]["rf_steps_per_period"], 40)
        self.assertEqual(followup["estimation"]["observed_peak_bytes"], 20)
        self.assertEqual(followup["waves"][0]["batch_count"], 4)

    def test_adaptive_followup_rejects_known_plan_and_invalid_measurement(self) -> None:
        known = plan_simion_dispatch(
            self.rf_request(), [{"resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40}, "per_batch_peak_working_set_bytes": 10}],
            available_memory_bytes=100, logical_processors=8,
        )
        with self.assertRaisesRegex(ValueError, "unknown-profile"):
            plan_adaptive_followup(known, 10)
        bootstrap = plan_simion_dispatch(self.rf_request(), [], available_memory_bytes=100, logical_processors=8)
        for measurement in (0, True, 1.5):
            with self.subTest(measurement=measurement), self.assertRaises(ValueError):
                plan_adaptive_followup(bootstrap, measurement)

    def test_cli_writes_bootstrap_and_observed_followup_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, profiles_path, output_path = root / "request.json", root / "profiles.json", root / "plan.json"
            request_path.write_text(json.dumps(self.rf_request()), encoding="utf-8")
            profiles_path.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "common.simion.resource_scheduler", "--request", str(request_path), "--profiles", str(profiles_path), "--output", str(output_path), "--available-memory-bytes", "100", "--logical-processors", "8", "--observed-bootstrap-peak-bytes", "20"],
                capture_output=True, text=True, check=False, timeout=30,
                cwd=Path(__file__).resolve().parents[2],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SIMION_REPOSITORY_DISPATCH_PLAN=PASS FIELD_KIND=rf", result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["estimation"]["kind"], "observed_bootstrap_peak")
            self.assertEqual(plan["waves"][0]["batch_count"], 4)

    def test_cli_bootstraps_without_a_profile_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, output_path = root / "request.json", root / "plan.json"
            request = self.rf_request()
            request.pop("unknown_per_batch_reservation_bytes")
            request_path.write_text(json.dumps(request), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, "-m", "common.simion.resource_scheduler",
                    "--request", str(request_path), "--output", str(output_path),
                    "--available-memory-bytes", "100", "--logical-processors", "8",
                ],
                capture_output=True, text=True, check=False, timeout=30,
                cwd=Path(__file__).resolve().parents[2],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["estimation"]["kind"], "unknown_resource_profile_bootstrap")
            self.assertIsNone(plan["estimation"]["bootstrap_reservation_bytes"])
