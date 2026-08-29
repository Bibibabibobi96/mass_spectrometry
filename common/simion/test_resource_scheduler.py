import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.simion.resource_scheduler import (
    MAXIMUM_MEMORY_DANGER_TERMINATION_ATTEMPTS,
    MAXIMUM_MEMORY_RECOVERY_ATTEMPTS,
    MEMORY_RECOVERY_STABLE_SECONDS,
    RESOURCE_IDENTITY_KEYS,
    format_dispatch_decision_event,
    plan_adaptive_followup,
    plan_runtime_dispatch,
    plan_simion_case_dispatch,
    plan_simion_dispatch,
)


GIB = 1024**3


class ResourceSchedulerTests(unittest.TestCase):
    @staticmethod
    def request(particle_count: int = 5000, **extra: object) -> dict[str, object]:
        value: dict[str, object] = {
            "solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
            "particle_count": particle_count, "independent_particles": True,
            "trajectory_quality": 8,
        }
        value.update(extra)
        return value

    @staticmethod
    def profile(peak: int = 1_000, cpu: float = 8.0) -> dict[str, object]:
        identity = {
            key: ResourceSchedulerTests.request().get(key)
            for key in RESOURCE_IDENTITY_KEYS
        }
        return {
            "resource_identity": identity,
            "per_batch_peak_working_set_bytes": peak,
            "per_batch_cpu_percent": cpu,
        }

    def test_unknown_n5000_starts_one_retained_n500_formal_batch(self) -> None:
        plan = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000, logical_processors=16,
        )
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")
        self.assertEqual(plan["estimation"]["observation_seconds"], 45)
        self.assertTrue(plan["estimation"]["first_batch_result_retained"])
        self.assertEqual(
            plan["estimation"]["terminal_action"],
            "observe_first_formal_batch_for_45_seconds_then_replan_remaining_particles",
        )
        self.assertEqual(plan["waves"][0]["batches"][0]["count"], 500)
        self.assertEqual(plan["waves"][0]["coverage"], "initial_formal_batch_only")
        self.assertEqual(
            format_dispatch_decision_event(plan),
            "SIMION_RESOURCE_EVENT=DISPATCH_DECISION MEASUREMENT=FIRST_FORMAL_BATCH "
            "PARTICLES=5000 BATCHES=1 MAX_CONCURRENCY=1 CPU_CAPACITY=1 "
            "MEMORY_CAPACITY=1 AVAILABLE_MEMORY=0.00GiB MEMORY_RESERVE=1.00GiB "
            "OBSERVATION_SECONDS=45",
        )

    def test_formal_observation_batch_is_one_tenth_of_large_population(self) -> None:
        plan = plan_simion_dispatch(
            self.request(particle_count=20_000), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000, logical_processors=16,
        )
        self.assertEqual(plan["waves"][0]["batches"][0]["count"], 2_000)
        self.assertNotIn("simion_max_ions_per_process", plan["limits"])

    def test_independent_work_items_observe_one_unsplittable_first_job(self) -> None:
        request = {
            "solver": "SIMION", "field_kind": "electrostatic",
            "work_item_count": 21, "independent_work_items": True,
            "case_input_sha256": "A" * 64,
        }
        initial = plan_simion_dispatch(
            request, [], available_memory_bytes=10 * GIB,
            total_physical_memory_bytes=20 * GIB,
        )
        self.assertEqual(initial["dispatch_unit"], "independent_work_items")
        self.assertEqual(initial["waves"][0]["batches"][0]["count"], 1)
        self.assertEqual(initial["waves"][0]["batches"][0]["work_item_id_min"], 1)
        self.assertIn("WORK_ITEMS=21", format_dispatch_decision_event(initial))
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8,
            available_memory_bytes=10 * GIB,
            total_physical_memory_bytes=20 * GIB,
            first_batch_completed=False,
        )
        self.assertEqual(final["work_item_count"], 21)
        self.assertEqual(final["dispatch_unit"], "independent_work_items")

    def test_public_plan_requires_45_second_stability_and_two_recovery_trials(self) -> None:
        plan = plan_simion_dispatch(
            self.request(), [self.profile()], available_memory_bytes=6 * GIB,
            total_physical_memory_bytes=10 * GIB,
        )
        self.assertEqual(
            plan["limits"]["memory_recovery_stable_seconds"],
            MEMORY_RECOVERY_STABLE_SECONDS,
        )
        self.assertEqual(
            plan["limits"]["maximum_memory_recovery_attempts"],
            MAXIMUM_MEMORY_RECOVERY_ATTEMPTS,
        )
        self.assertEqual(
            plan["limits"]["maximum_memory_danger_termination_attempts"],
            MAXIMUM_MEMORY_DANGER_TERMINATION_ATTEMPTS,
        )

    def test_running_first_batch_balances_total_work_across_lanes(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8, background_cpu_percent=5,
            available_memory_bytes=int(5.5 * GIB), total_physical_memory_bytes=10 * GIB,
            first_batch_completed=False,
        )
        self.assertEqual(final["limits"]["maximum_concurrency"], 5)
        counts = [item["count"] for item in final["waves"][0]["batches"]]
        self.assertEqual(counts, [500, 1_000, 1_000, 1_000, 1_000, 500])
        self.assertEqual(final["waves"][0]["batch_count"], 6)
        self.assertEqual(sum(counts), 5_000)
        self.assertEqual(counts[0] + counts[-1], counts[1])
        self.assertEqual(final["estimation"]["memory_safety_factor"], 1.10)
        self.assertTrue(final["estimation"]["retained_first_batch_counts_toward_concurrency"])

    def test_adaptive_followup_does_not_freeze_background_cpu_into_lane_count(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=100 * GIB,
            total_physical_memory_bytes=128 * GIB,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8, background_cpu_percent=80,
            available_memory_bytes=100 * GIB, total_physical_memory_bytes=128 * GIB,
            first_batch_completed=False,
        )
        self.assertEqual(final["limits"]["cpu_capacity"], 10)
        self.assertEqual(final["limits"]["maximum_concurrency"], 10)

    def test_completed_first_batch_keeps_balanced_lane_remainder(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8, background_cpu_percent=5,
            available_memory_bytes=int(5.5 * GIB), total_physical_memory_bytes=10 * GIB,
            first_batch_completed=True,
        )
        self.assertEqual(final["limits"]["maximum_concurrency"], 4)
        self.assertFalse(final["estimation"]["retained_first_batch_counts_toward_concurrency"])
        self.assertEqual(
            [item["count"] for item in final["waves"][0]["batches"]],
            [500, 1_250, 1_250, 1_250, 750],
        )
        self.assertEqual(final["waves"][0]["batches"][1]["particle_id_min"], 501)

    def test_live_formal_first_adds_its_lane_to_r04_observed_capacity(self) -> None:
        """Regression for the r04 under-count: free RAM is post-first-batch."""
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=1,
            total_physical_memory_bytes=1,
        )
        final = plan_adaptive_followup(
            initial,
            int(8.103 * 1024**3),
            observed_cpu_percent=8,
            background_cpu_percent=5,
            available_memory_bytes=int(27.359 * 1024**3),
            total_physical_memory_bytes=int(47.924 * 1024**3),
            first_batch_completed=False,
        )
        # Two further 1.10x peak budgets fit after the 1 GiB reserve.  The formal
        # first batch already consumes the third, retained lane.
        self.assertEqual(final["limits"]["memory_capacity"], 3)
        self.assertEqual(final["limits"]["maximum_concurrency"], 3)

    def test_live_formal_first_does_not_invent_an_extra_lane_when_none_fits(self) -> None:
        """The retained first lane is not evidence that one sibling fits."""
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=1,
            total_physical_memory_bytes=1,
        )
        final = plan_adaptive_followup(
            initial,
            int(36.86 * GIB),
            observed_cpu_percent=10,
            available_memory_bytes=int(3.42 * GIB),
            total_physical_memory_bytes=int(47.92 * GIB),
            first_batch_completed=False,
        )
        self.assertEqual(final["limits"]["memory_capacity"], 1)
        self.assertEqual(final["limits"]["maximum_concurrency"], 1)
        self.assertEqual(
            [item["count"] for item in final["waves"][0]["batches"]],
            [500, 4_500],
        )

    def test_two_lanes_retain_first_then_balance_one_remainder(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=10, background_cpu_percent=0,
            available_memory_bytes=int(2.2 * GIB), total_physical_memory_bytes=10 * GIB,
        )
        self.assertEqual(final["limits"]["maximum_concurrency"], 2)
        self.assertEqual(
            [item["count"] for item in final["waves"][0]["batches"]],
            [500, 2_500, 2_000],
        )

    def test_known_profile_uses_one_even_batch_per_allowed_lane(self) -> None:
        plan = plan_simion_dispatch(
            self.request(), [self.profile(peak=GIB)], available_memory_bytes=6 * GIB,
            total_physical_memory_bytes=10 * GIB, background_cpu_percent=5,
        )
        self.assertEqual(plan["estimation"]["kind"], "exact_resource_profile")
        self.assertTrue(plan["estimation"]["observation_wait_skipped"])
        self.assertEqual(plan["limits"]["maximum_concurrency"], 4)
        self.assertEqual(plan["waves"][0]["batch_count"], 4)
        self.assertEqual([item["count"] for item in plan["waves"][0]["batches"]], [1_250, 1_250, 1_250, 1_250])
        event = format_dispatch_decision_event(plan)
        self.assertIn("MEASUREMENT=EXACT_HISTORICAL_PROFILE", event)
        self.assertIn("BATCHES=4", event)
        self.assertIn("PROCESS_MEMORY_BUDGET=1.10GiB", event)

    def test_profile_requires_exact_numerical_identity(self) -> None:
        plan = plan_simion_dispatch(
            self.request(trajectory_quality=17), [self.profile()],
            available_memory_bytes=10_000, total_physical_memory_bytes=20_000,
        )
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")

    def test_project_resource_controls_are_rejected(self) -> None:
        for key in (
            "maximum_parallel_batches", "reserve_available_memory_bytes",
            "unknown_per_batch_reservation_bytes", "cpu_cores_per_batch",
            "reserve_cpu_cores", "memory_safety_numerator",
            "memory_safety_denominator", "maximum_process_tree_working_set_bytes",
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "retired"):
                plan_simion_dispatch(
                    self.request(**{key: 1}), [], available_memory_bytes=10_000,
                    total_physical_memory_bytes=20_000,
                )

    def test_runtime_replans_known_profile_from_current_memory(self) -> None:
        prepared = plan_simion_dispatch(
            self.request(), [self.profile(peak=GIB)], available_memory_bytes=3 * GIB,
            total_physical_memory_bytes=10 * GIB,
        )
        runtime = plan_runtime_dispatch(
            prepared, available_memory_bytes=6 * GIB,
            total_physical_memory_bytes=10 * GIB,
        )
        self.assertGreater(runtime["limits"]["maximum_concurrency"], prepared["limits"]["maximum_concurrency"])

    def test_case_unknown_identity_runs_one_formal_case(self) -> None:
        plan = plan_simion_case_dispatch(
            [
                {"case_id": "a", "resource_identity": {"case_input_sha256": "A" * 64}},
                {"case_id": "b", "resource_identity": {"case_input_sha256": "B" * 64}},
            ],
            {"solver": "SIMION", "field_kind": "electrostatic"}, [],
            available_memory_bytes=10_000, total_physical_memory_bytes=20_000,
        )
        self.assertEqual(plan["waves"][0]["cases"], [{"case_id": "a"}])

    def test_known_cases_are_packed_once_within_memory(self) -> None:
        cases = [
            {"case_id": "a", "resource_identity": {"case_input_sha256": "A" * 64}},
            {"case_id": "b", "resource_identity": {"case_input_sha256": "B" * 64}},
        ]
        profiles = []
        for case in cases:
            identity = {
                key: {
                    "solver": "SIMION", "field_kind": "electrostatic",
                    **case["resource_identity"],
                }.get(key)
                for key in RESOURCE_IDENTITY_KEYS
            }
            profiles.append({
                "resource_identity": identity,
                "per_batch_peak_working_set_bytes": GIB,
            })
        plan = plan_simion_case_dispatch(
            cases, {"solver": "SIMION", "field_kind": "electrostatic"}, profiles,
            available_memory_bytes=int(4.5 * GIB), total_physical_memory_bytes=10 * GIB,
        )
        self.assertEqual([item["case_id"] for item in plan["waves"][0]["cases"]], ["a", "b"])
        self.assertEqual(plan["limits"]["maximum_concurrency"], 2)

    def test_cli_finalizes_formal_first_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, output_path = root / "request.json", root / "plan.json"
            request_path.write_text(json.dumps(self.request()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, "-m", "common.simion.resource_scheduler",
                    "--request", str(request_path), "--output", str(output_path),
                    "--available-memory-bytes", str(int(5.5 * GIB)),
                    "--total-physical-memory-bytes", str(10 * GIB),
                    "--observed-formal-peak-bytes", str(GIB),
                    "--observed-formal-cpu-percent", "8",
                    "--observed-background-cpu-percent", "5",
                ], cwd=Path(__file__).resolve().parents[2], capture_output=True,
                text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SIMION_RESOURCE_EVENT=DISPATCH_DECISION", result.stdout)
            self.assertIn("MEASUREMENT=OBSERVED_FORMAL_BATCH", result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["waves"][0]["batch_count"], 6)
            self.assertEqual(
                [item["count"] for item in plan["waves"][0]["batches"]],
                [500, 1_000, 1_000, 1_000, 1_000, 500],
            )


if __name__ == "__main__":
    unittest.main()
