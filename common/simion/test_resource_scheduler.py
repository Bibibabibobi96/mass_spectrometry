import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.simion.resource_scheduler import (
    CPU_DEMAND_SAFETY_FACTOR,
    MAXIMUM_MEMORY_DANGER_TERMINATION_ATTEMPTS,
    MAXIMUM_MEMORY_RECOVERY_ATTEMPTS,
    MEMORY_RECOVERY_STABLE_SECONDS,
    RESOURCE_IDENTITY_KEYS,
    format_dispatch_decision_event,
    plan_adaptive_followup,
    plan_recovered_formal_followup,
    prepare_fixed_partition_dispatch,
    calibrate_recovered_missing_plan,
    plan_runtime_dispatch,
    plan_simion_case_dispatch,
    plan_simion_dispatch,
)


GIB = 1024**3


class ResourceSchedulerTests(unittest.TestCase):
    def test_fixed_recovery_matches_profiles_to_original_missing_units_not_new_partition(self) -> None:
        fixed = dict(role="simion_single_wave_particle_batch_plan", coverage="complete_population",
            particle_count=5000, batches=[
                dict(index=1, count=500, particle_id_min=1, particle_id_max=500, simion_particle_id_offset=0),
                dict(index=2, count=2500, particle_id_min=501, particle_id_max=3000, simion_particle_id_offset=500),
                dict(index=3, count=2000, particle_id_min=3001, particle_id_max=5000, simion_particle_id_offset=3000)])
        profile = self.profile(peak=GIB, cpu=80, observed_batch_work_units=2500)
        initial = plan_simion_dispatch(self.request(), [profile], available_memory_bytes=2*GIB,
            total_physical_memory_bytes=20*GIB, logical_processors=8)
        self.assertEqual(initial["estimation"]["kind"], "formal_first_batch_observation")
        before = json.loads(json.dumps((initial, fixed, profile)))
        ready = prepare_fixed_partition_dispatch(initial, fixed, [2, 3], profiles=[profile])
        self.assertEqual(ready["estimation"]["kind"], "exact_resource_profile")
        self.assertEqual(ready["estimation"]["observed_batch_work_units"], 2500)
        self.assertNotIn("recovered_missing_observation", ready["estimation"])
        self.assertEqual(ready["limits"]["maximum_concurrency"], 1)
        self.assertEqual(ready["particle_count"], 5000)
        self.assertEqual(ready["waves"][0]["particle_count"], 5000)
        self.assertEqual(ready["waves"][0]["batches"], fixed["batches"])
        self.assertEqual(json.loads(json.dumps((initial, fixed, profile))), before)
        wrong_identity = {**profile, "resource_identity": {**profile["resource_identity"], "rf_steps_per_period": 41}}
        for invalid in ({**profile, "observed_batch_work_units": 2000}, wrong_identity):
            observe = prepare_fixed_partition_dispatch(initial, fixed, [2, 3], profiles=[invalid])
            self.assertEqual(observe["estimation"]["kind"], "formal_first_batch_observation")
            self.assertEqual(observe["estimation"]["observed_missing_batch_index"], 2)
            self.assertEqual(observe["waves"][0]["batches"], fixed["batches"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, document in (("dispatch", initial), ("fixed", fixed), ("profiles", [profile])):
                (root/f"{name}.json").write_text(json.dumps(document), encoding="utf-8")
            completed = subprocess.run([sys.executable, "-m", "common.simion.resource_scheduler",
                "--prepare-fixed-recovery-plan", str(root/"dispatch.json"), "--fixed-batch-plan", str(root/"fixed.json"),
                "--profiles", str(root/"profiles.json"), "--replay-batch-index", "2", "--replay-batch-index", "3",
                "--output", str(root/"dispatch.json")], cwd=Path(__file__).resolve().parents[2],
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            self.assertEqual(json.loads((root/"dispatch.json").read_text(encoding="utf-8")), ready)

    def test_fixed_recovery_counts_live_observation_in_memory_and_cpu_capacity(self) -> None:
        initial = plan_simion_dispatch(self.request(), [], available_memory_bytes=10*GIB,
            total_physical_memory_bytes=20*GIB, logical_processors=8)
        fixed = dict(role="simion_single_wave_particle_batch_plan", coverage="complete_population",
            particle_count=5000, batches=[
                dict(index=1, count=500, particle_id_min=1, particle_id_max=500, simion_particle_id_offset=0),
                dict(index=2, count=2500, particle_id_min=501, particle_id_max=3000, simion_particle_id_offset=500),
                dict(index=3, count=2000, particle_id_min=3001, particle_id_max=5000, simion_particle_id_offset=3000)])
        plan = prepare_fixed_partition_dispatch(initial, fixed, [2, 3])
        before = json.loads(json.dumps(plan))
        # The live observation already occupies one lane. Free memory is
        # sampled after that worker's allocation; CPU remains whole-host.
        for completed, free, cpu, memory_lanes, cpu_lanes, lanes in (
            (False, 2*GIB, 20, 3, 4, 3),
            (True, 2*GIB, 20, 2, 4, 2),
            (False, GIB//2, 20, 1, 4, 1),
            (False, 10*GIB, 80, 11, 1, 1),
        ):
            with self.subTest(completed=completed, free=free, cpu=cpu):
                calibrated = calibrate_recovered_missing_plan(plan, GIB,
                    observed_cpu_percent=cpu, background_cpu_percent=0,
                    available_memory_bytes=free, total_physical_memory_bytes=20*GIB,
                    observed_completed=completed)
                self.assertEqual(calibrated["limits"]["memory_capacity"], memory_lanes)
                self.assertEqual(calibrated["limits"]["cpu_capacity"], cpu_lanes)
                self.assertEqual(calibrated["limits"]["maximum_concurrency"], lanes)
                self.assertEqual(calibrated["estimation"]["retained_first_batch_counts_toward_concurrency"], not completed)
                self.assertEqual(calibrated["waves"][0]["batches"], fixed["batches"])
                self.assertEqual(plan, before)
        for cpu, lanes in ((20, 2), (80, 1)):
            with self.subTest(covering_profile_cpu=cpu):
                profiled = plan_simion_dispatch(self.request(),
                    [self.profile(peak=GIB, cpu=cpu, observed_batch_work_units=2500)],
                    available_memory_bytes=2*GIB, total_physical_memory_bytes=20*GIB,
                    logical_processors=8)
                ready = prepare_fixed_partition_dispatch(profiled, fixed, [2, 3],
                    profiles=[self.profile(peak=GIB, cpu=cpu, observed_batch_work_units=2500)])
                self.assertEqual(ready["estimation"]["kind"], "exact_resource_profile")
                self.assertNotIn("recovered_missing_observation", ready["estimation"])
                self.assertEqual(ready["limits"]["maximum_concurrency"], lanes)
                self.assertEqual(ready["waves"][0]["batches"], fixed["batches"])

    def test_fixed_recovery_5000_population_uses_original_larger_missing_batch(self) -> None:
        initial = plan_simion_dispatch(self.request(), [], available_memory_bytes=10*GIB,
            total_physical_memory_bytes=20*GIB, logical_processors=8)
        counts = [500, 715, 715, 714, 714, 714, 714, 214]
        batches = []
        first = 1
        for index, count in enumerate(counts, 1):
            batches.append(dict(index=index, count=count, particle_id_min=first,
                particle_id_max=first+count-1, simion_particle_id_offset=first-1))
            first += count
        fixed = dict(role="simion_single_wave_particle_batch_plan", coverage="complete_population",
                     particle_count=5000, batches=batches)
        plan = prepare_fixed_partition_dispatch(initial, fixed, [2, 4, 8])
        self.assertEqual(plan["estimation"]["observed_missing_batch_index"], 2)
        self.assertEqual(plan["limits"]["maximum_concurrency"], 1)
        for completed in (False, True):
            calibrated = calibrate_recovered_missing_plan(plan, GIB,
                observed_cpu_percent=8, background_cpu_percent=0,
                available_memory_bytes=10*GIB, total_physical_memory_bytes=20*GIB,
                observed_completed=completed)
            self.assertEqual(calibrated["waves"][0]["batches"], batches)
            self.assertGreater(calibrated["limits"]["maximum_concurrency"], 1)
            self.assertLessEqual(calibrated["limits"]["maximum_concurrency"],
                                 calibrated["limits"]["cpu_capacity"])
        constrained = calibrate_recovered_missing_plan(plan, 9*GIB,
            observed_cpu_percent=80, background_cpu_percent=0,
            available_memory_bytes=GIB, total_physical_memory_bytes=20*GIB,
            observed_completed=False)
        self.assertEqual(constrained["limits"]["maximum_concurrency"], 1)
        self.assertEqual(constrained["waves"][0]["batches"], batches)

    def test_fixed_partition_calibrates_largest_missing_unit_and_keeps_all_intervals(self) -> None:
        initial = plan_simion_dispatch(self.request(), [], available_memory_bytes=10*GIB,
            total_physical_memory_bytes=20*GIB, logical_processors=8)
        batches = [dict(index=i, particle_id_min=low, particle_id_max=high, count=high-low+1,
                        simion_particle_id_offset=low-1) for i, (low, high) in enumerate(((1,500),(501,2500),(2501,5000)),1)]
        fixed = dict(role="simion_single_wave_particle_batch_plan", coverage="complete_population",
                     particle_count=5000, batches=batches)
        pending = [2, 3]
        plan = prepare_fixed_partition_dispatch(initial, fixed, pending)
        self.assertEqual(plan["estimation"]["observed_missing_batch_index"], 3)
        self.assertEqual(plan["waves"][0]["batches"], batches)
        calibrated = calibrate_recovered_missing_plan(plan, GIB, observed_cpu_percent=8, background_cpu_percent=0,
            available_memory_bytes=10*GIB, total_physical_memory_bytes=20*GIB, observed_completed=False)
        self.assertEqual(calibrated["waves"][0]["batches"], batches)
        self.assertEqual(calibrated["estimation"]["observed_missing_batch_index"], 3)
        self.assertGreaterEqual(calibrated["estimation"]["per_process_memory_budget_bytes"], GIB)
        self.assertGreater(calibrated["limits"]["maximum_concurrency"], 1)
        self.assertLessEqual(calibrated["limits"]["maximum_concurrency"],
                             calibrated["limits"]["memory_capacity"])
        reuse = prepare_fixed_partition_dispatch(calibrated, fixed, [2])
        self.assertEqual(reuse["estimation"]["kind"], "observed_formal_batch")
        self.assertEqual(reuse["limits"], calibrated["limits"])
        too_small = json.loads(json.dumps(calibrated))
        too_small["estimation"]["observed_missing_batch_index"] = 1
        reprobe = prepare_fixed_partition_dispatch(too_small, fixed, [2])
        self.assertEqual(reprobe["estimation"]["kind"], "formal_first_batch_observation")
        self.assertEqual(reprobe["estimation"]["observed_missing_batch_index"], 2)
        self.assertEqual(reprobe["waves"][0]["batches"], batches)
        self.assertEqual(reprobe["limits"]["maximum_concurrency"], 1)
        exact = plan_simion_dispatch(self.request(), [self.profile()],
            available_memory_bytes=10*GIB, total_physical_memory_bytes=20*GIB,
            logical_processors=8)
        exact["estimation"]["observed_batch_work_units"] = 500
        reprobe = prepare_fixed_partition_dispatch(exact, fixed, [2, 3])
        self.assertEqual(reprobe["estimation"]["kind"], "formal_first_batch_observation")
        self.assertNotIn("observed_peak_bytes", reprobe["estimation"])
        self.assertEqual(reprobe["estimation"]["observed_missing_batch_index"], 3)
        recalibrated = calibrate_recovered_missing_plan(reprobe, GIB,
            observed_cpu_percent=8, background_cpu_percent=0,
            available_memory_bytes=10*GIB, total_physical_memory_bytes=20*GIB,
            observed_completed=False)
        self.assertEqual(recalibrated["waves"][0]["batches"], batches)
        self.assertEqual(recalibrated["estimation"]["observed_missing_batch_index"], 3)
        self.assertGreater(recalibrated["limits"]["maximum_concurrency"], 1)
        exact["estimation"]["observed_batch_work_units"] = True
        with self.assertRaisesRegex(ValueError, "work-unit count is invalid"):
            prepare_fixed_partition_dispatch(exact, fixed, [2])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dispatch = root/"dispatch.json"; partition = root/"batch.json"
            dispatch.write_text(json.dumps(initial), encoding="utf-8")
            partition.write_text(json.dumps(fixed), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "common.simion.resource_scheduler",
                "--prepare-fixed-recovery-plan", str(dispatch), "--fixed-batch-plan", str(partition),
                "--replay-batch-index", "2", "--replay-batch-index", "3", "--output", str(dispatch)],
                cwd=Path(__file__).resolve().parents[2], timeout=30, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(json.loads(dispatch.read_text())["estimation"]["observed_missing_batch_index"], 3)
        plan["estimation"]["observed_missing_batch_index"] = 2
        with self.assertRaisesRegex(ValueError, "cannot cover"):
            calibrate_recovered_missing_plan(plan, GIB, observed_cpu_percent=8, background_cpu_percent=0,
                available_memory_bytes=10*GIB, total_physical_memory_bytes=20*GIB, observed_completed=False)

    def test_recovered_formal_followup_preserves_observed_first_interval(self) -> None:
        initial=plan_simion_dispatch(self.request(),[],available_memory_bytes=10*GIB,
            total_physical_memory_bytes=20*GIB,logical_processors=8)
        first=initial['waves'][0]['batches'][0]
        completion=dict(natural_exit=True,exit_code=0,count=first['count'],
            source_row_range=[first['particle_id_min'],first['particle_id_max']],
            resource_observation=dict(peak_bytes=GIB,process_cpu_percent=8,background_cpu_percent=0))
        final=plan_recovered_formal_followup(initial,completion)
        self.assertEqual(final['waves'][0]['batches'][0],first)
        self.assertEqual(final['waves'][0]['coverage'],'complete_population')
        fallback=plan_recovered_formal_followup(initial,{**completion,'resource_observation':None})
        self.assertTrue(fallback['estimation']['recovered_missing_observation'])
        self.assertEqual(fallback['waves'][0]['batches'][0],first)
        self.assertEqual(sum(b['count'] for b in fallback['waves'][0]['batches']),5000)
        self.assertGreater(len(fallback['waves'][0]['batches']),2)
        self.assertTrue(all(b['count']<=first['count'] for b in fallback['waves'][0]['batches'][1:]))
        calibrated=calibrate_recovered_missing_plan(fallback,GIB,observed_cpu_percent=8,background_cpu_percent=0,
            available_memory_bytes=10*GIB,total_physical_memory_bytes=20*GIB,observed_completed=False)
        self.assertEqual(calibrated['waves'][0]['batches'],fallback['waves'][0]['batches'])
        self.assertGreater(calibrated['limits']['maximum_concurrency'],1)
        self.assertEqual(calibrated['estimation']['observed_peak_bytes'],GIB)
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'fallback.json';output=Path(directory)/'calibrated.json'
            source.write_text(json.dumps(fallback),encoding='utf-8')
            result=subprocess.run([sys.executable,'-m','common.simion.resource_scheduler',
                '--recovered-missing-plan',str(source),'--output',str(output),
                '--observed-formal-peak-bytes',str(GIB),'--observed-formal-cpu-percent','8',
                '--observed-background-cpu-percent','0','--available-memory-bytes',str(10*GIB),
                '--total-physical-memory-bytes',str(20*GIB)],cwd=Path(__file__).resolve().parents[2],
                timeout=30,capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(output.read_text())['waves'][0]['batches'],fallback['waves'][0]['batches'])
        for bad in ({**completion,'exit_code':1},{**completion,'source_row_range':[2,first['particle_id_max']]},
                    {**completion,'resource_observation':'invented'}):
            with self.assertRaises(ValueError):
                plan_recovered_formal_followup(initial,bad)

    def test_physical_danger_limits_are_frozen_from_shared_host_policy(self) -> None:
        policy = json.loads(Path(__file__).resolve().parents[1].joinpath("host_resource_policy.json").read_text())
        plan = plan_simion_dispatch(self.request(), [], available_memory_bytes=10 * GIB,
                                   total_physical_memory_bytes=20 * GIB, logical_processors=4)
        for name in ("memory_critical_reserve_bytes", "memory_critical_seconds"):
            self.assertEqual(plan["limits"][name], policy[name])

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
    def profile(
        peak: int = 1_000,
        cpu: float = 8.0,
        observed_batch_work_units: int = 5_000,
    ) -> dict[str, object]:
        identity = {
            key: ResourceSchedulerTests.request().get(key)
            for key in RESOURCE_IDENTITY_KEYS
        }
        return {
            "resource_identity": identity,
            "per_batch_peak_working_set_bytes": peak,
            "per_batch_cpu_percent": cpu,
            "observed_batch_work_units": observed_batch_work_units,
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
            "MEMORY_CAPACITY=1 AVAILABLE_MEMORY=0.00GiB MEMORY_RESERVE=0.00GiB "
            "OBSERVATION_SECONDS=45 CPU_BUDGET_PERCENT=6.5625 CPU_DEMAND_FACTOR=1.05",
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
            logical_processors=16,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8, background_cpu_percent=5,
            available_memory_bytes=int(4.5 * GIB), total_physical_memory_bytes=10 * GIB,
            first_batch_completed=False,
        )
        self.assertEqual(final["limits"]["maximum_concurrency"], 5)
        counts = [item["count"] for item in final["waves"][0]["batches"]]
        self.assertEqual(counts, [500, 1_000, 1_000, 1_000, 1_000, 500])
        self.assertEqual(final["waves"][0]["batch_count"], 6)
        self.assertEqual(sum(counts), 5_000)
        self.assertEqual(counts[0] + counts[-1], counts[1])
        self.assertEqual(final["estimation"]["memory_safety_factor"], 1.0)
        self.assertTrue(final["estimation"]["retained_first_batch_counts_toward_concurrency"])

    def test_running_first_batch_credits_head_start_when_work_is_indivisible(self) -> None:
        initial = plan_simion_dispatch(
            self.request(particle_count=100), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000,
            logical_processors=16,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=10,
            available_memory_bytes=int(5.5 * GIB), total_physical_memory_bytes=10 * GIB,
            first_batch_completed=False,
        )
        self.assertEqual(final["limits"]["maximum_concurrency"], 6)
        counts = [item["count"] for item in final["waves"][0]["batches"]]
        self.assertEqual(counts, [10, 17, 17, 17, 17, 16, 6])
        self.assertEqual(sum(counts), 100)
        self.assertEqual(counts[0] + counts[-1], 16)

    def test_adaptive_followup_does_not_freeze_background_cpu_into_lane_count(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=100 * GIB,
            total_physical_memory_bytes=128 * GIB, logical_processors=16,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8, background_cpu_percent=80,
            available_memory_bytes=100 * GIB, total_physical_memory_bytes=128 * GIB,
            first_batch_completed=False,
        )
        self.assertEqual(final["limits"]["cpu_capacity"], 11)
        self.assertEqual(final["limits"]["maximum_concurrency"], 11)

    def test_cpu_floor_tracks_one_logical_processor_and_keeps_measured_cost(self) -> None:
        for cores, observed, expected_floor, expected_capacity in (
            (16, 6.2, 6.25, 14),
            (4, 6.2, 25.0, 3),
            (16, 25.0, 6.25, 3),
        ):
            with self.subTest(logical_processors=cores, observed_cpu=observed):
                initial = plan_simion_dispatch(
                    self.request(100), [], available_memory_bytes=100 * GIB,
                    total_physical_memory_bytes=128 * GIB, logical_processors=cores,
                )
                known = plan_simion_dispatch(
                    self.request(100), [self.profile(peak=GIB, cpu=observed)],
                    available_memory_bytes=100 * GIB,
                    total_physical_memory_bytes=128 * GIB, logical_processors=cores,
                )
                for completed in (True, False):
                    adaptive = plan_adaptive_followup(
                        initial, GIB, observed_cpu_percent=observed,
                        available_memory_bytes=100 * GIB,
                        total_physical_memory_bytes=128 * GIB,
                        first_batch_completed=completed,
                    )
                    for plan in (known, adaptive):
                        self.assertEqual(plan["limits"]["minimum_process_cpu_percent"], expected_floor)
                        self.assertEqual(plan["limits"]["cpu_capacity"], expected_capacity)
                        self.assertEqual(plan["limits"]["maximum_concurrency"], expected_capacity)
                        self.assertEqual(plan["estimation"]["per_process_cpu_percent"], max(expected_floor, observed))
                        batches = plan["waves"][0]["batches"]
                        self.assertEqual(sum(batch["count"] for batch in batches), 100)
                        self.assertEqual(batches[0]["particle_id_min"], 1)
                        self.assertEqual(batches[-1]["particle_id_max"], 100)

    def test_cpu_floor_change_preserves_memory_constraint(self) -> None:
        plan = plan_simion_dispatch(
            self.request(100), [self.profile(peak=3 * GIB, cpu=6.2)],
            available_memory_bytes=8 * GIB,
            total_physical_memory_bytes=48 * GIB, logical_processors=16,
        )
        self.assertEqual(plan["limits"]["cpu_capacity"], 14)
        self.assertEqual(plan["limits"]["memory_capacity"], 2)
        self.assertEqual(plan["limits"]["maximum_concurrency"], 2)

    def test_case_dispatch_publishes_the_same_host_cpu_floor(self) -> None:
        for cores, capacity in ((16, 14), (4, 3)):
            with self.subTest(logical_processors=cores):
                plan = plan_simion_case_dispatch(
                    [{"case_id": f"case{index}", "resource_identity": {}} for index in range(20)],
                    self.request(1), [self.profile(peak=GIB, cpu=6.2)],
                    available_memory_bytes=100 * GIB,
                    total_physical_memory_bytes=128 * GIB, logical_processors=cores,
                )
                self.assertEqual(plan["limits"]["maximum_concurrency"], capacity)
                self.assertEqual(plan["limits"]["minimum_process_cpu_percent"], 100.0 / cores)
                self.assertEqual(len(plan["waves"][0]["cases"]), capacity)

    def test_cpu_relative_margin_retains_raw_measurement_and_floor(self) -> None:
        for observed, cores, expected in ((1., 128, 1.05), (6.25, 16, 6.5625), (0., 16, 6.5625)):
            with self.subTest(observed=observed, cores=cores):
                initial = plan_simion_dispatch(self.request(100), [], available_memory_bytes=100*GIB,
                                              total_physical_memory_bytes=128*GIB, logical_processors=cores)
                known = plan_simion_dispatch(self.request(100), [self.profile(peak=GIB, cpu=observed)],
                                            available_memory_bytes=100*GIB, total_physical_memory_bytes=128*GIB,
                                            logical_processors=cores)
                adaptive = plan_adaptive_followup(initial, GIB, observed_cpu_percent=observed,
                                                  available_memory_bytes=100*GIB, total_physical_memory_bytes=128*GIB)
                for plan in (known, adaptive):
                    self.assertEqual(plan["estimation"]["observed_process_cpu_percent"], observed)
                    self.assertAlmostEqual(plan["estimation"]["per_process_cpu_budget_percent"], expected)
                    self.assertEqual(plan["estimation"]["cpu_demand_safety_factor"], CPU_DEMAND_SAFETY_FACTOR)
                    self.assertAlmostEqual(plan["limits"]["minimum_process_cpu_budget_percent"], 100/cores*1.05)
                    event = format_dispatch_decision_event(plan)
                    self.assertIn(f"CPU_BUDGET_PERCENT={expected}", event)
                    self.assertIn("CPU_DEMAND_FACTOR=1.05", event)

    def test_repeated_runtime_replanning_never_inflates_cpu_twice(self) -> None:
        plan = plan_simion_dispatch(self.request(100), [self.profile(peak=GIB, cpu=6.25)],
                                    available_memory_bytes=100*GIB, total_physical_memory_bytes=128*GIB,
                                    logical_processors=16)
        for _ in range(3):
            self.assertEqual(plan["limits"]["maximum_concurrency"], 14)
            self.assertEqual(plan["estimation"]["per_process_cpu_percent"], 6.25)
            self.assertEqual(plan["estimation"]["per_process_cpu_budget_percent"], 6.5625)
            plan = plan_runtime_dispatch(plan, available_memory_bytes=100*GIB,
                                         total_physical_memory_bytes=128*GIB, logical_processors=16)

    def test_work_item_and_case_selection_consume_effective_cpu_budget_once(self) -> None:
        request = self.request(100)
        request.pop("particle_count")
        request.pop("independent_particles")
        request.update(work_item_count=100, independent_work_items=True)
        plan = plan_simion_dispatch(request, [self.profile(peak=GIB, cpu=6.25)],
                                    available_memory_bytes=100*GIB, total_physical_memory_bytes=128*GIB,
                                    logical_processors=16)
        self.assertEqual(plan["dispatch_unit"], "independent_work_items")
        self.assertEqual(plan["limits"]["maximum_concurrency"], 14)
        self.assertEqual(sum(batch["count"] for batch in plan["waves"][0]["batches"]), 100)
        cases = plan_simion_case_dispatch([dict(case_id=f"case{i}", resource_identity={}) for i in range(20)],
                                          self.request(1), [self.profile(peak=GIB, cpu=6.25)],
                                          available_memory_bytes=100*GIB, total_physical_memory_bytes=128*GIB,
                                          logical_processors=16)
        self.assertEqual(len(cases["waves"][0]["cases"]), 14)
        self.assertTrue(all(c["per_process_cpu_budget_percent"] == 6.5625 for c in cases["waves"][0]["cases"]))

    def test_explicit_invalid_processor_count_fails_before_planning(self) -> None:
        for cores in (0, -1, True, 1.5):
            with self.subTest(logical_processors=cores), self.assertRaisesRegex(ValueError, "logical_processors"):
                plan_simion_dispatch(
                    self.request(), [], available_memory_bytes=GIB,
                    total_physical_memory_bytes=2 * GIB, logical_processors=cores,
                )

    def test_temporary_memory_pressure_keeps_work_until_live_admission(self) -> None:
        plan = plan_simion_dispatch(
            self.request(), [self.profile(peak=GIB)],
            available_memory_bytes=GIB // 2, total_physical_memory_bytes=8 * GIB,
        )
        self.assertEqual(plan["limits"]["maximum_concurrency"], 1)
        self.assertEqual(plan["admission"]["status"], "memory_warning")
        self.assertEqual(plan["admission"]["current_capacity"], 0)
        self.assertEqual(sum(b["count"] for b in plan["waves"][0]["batches"]), 5000)
        recovered = plan_runtime_dispatch(
            plan, available_memory_bytes=6 * GIB, total_physical_memory_bytes=8 * GIB,
        )
        self.assertEqual(recovered["admission"]["status"], "ready")
        self.assertGreater(recovered["admission"]["current_capacity"], 0)

    def test_known_peak_exceeding_total_memory_warns_without_veto(self) -> None:
        plan = plan_simion_dispatch(
            self.request(), [self.profile(peak=40 * GIB)],
            available_memory_bytes=27 * GIB, total_physical_memory_bytes=32 * GIB,
        )
        self.assertEqual(plan["limits"]["maximum_concurrency"], 1)
        self.assertEqual(plan["limits"]["memory_policy"], "warn_single_worker")
        self.assertEqual(plan["limits"]["memory_admission_reserve_bytes"], 0)
        self.assertEqual(plan["admission"]["status"], "memory_warning")
        self.assertTrue(plan["admission"]["single_worker_start_allowed"])
        self.assertEqual(plan["estimation"]["per_process_memory_budget_bytes"], 40 * GIB)
        self.assertEqual(sum(b["count"] for b in plan["waves"][0]["batches"]), 5000)

    def test_live_first_lane_is_retained_while_no_sibling_fits(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=8 * GIB,
            total_physical_memory_bytes=8 * GIB,
        )
        plan = plan_adaptive_followup(
            initial, GIB, available_memory_bytes=GIB // 2,
            total_physical_memory_bytes=8 * GIB, first_batch_completed=False,
        )
        self.assertEqual(plan["limits"]["maximum_concurrency"], 1)
        self.assertEqual(plan["admission"]["current_capacity"], 0)
        self.assertEqual(plan["admission"]["status"], "memory_warning")
        self.assertEqual(sum(b["count"] for b in plan["waves"][0]["batches"]), 5000)

    def test_case_memory_pressure_preserves_pending_case(self) -> None:
        plan = plan_simion_case_dispatch(
            [{"case_id": "pending", "resource_identity": {}}],
            self.request(particle_count=1), [self.profile(peak=GIB)],
            available_memory_bytes=GIB // 2, total_physical_memory_bytes=8 * GIB,
        )
        self.assertEqual(plan["admission"]["current_capacity"], 0)
        self.assertEqual(plan["admission"]["status"], "memory_warning")
        self.assertEqual(plan["waves"][0]["cases"][0]["case_id"], "pending")

    def test_live_formal_cpu_capacity_includes_existing_worker(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=100 * GIB,
            total_physical_memory_bytes=128 * GIB,
            logical_processors=16,
        )
        for completed in (False, True):
            with self.subTest(first_completed=completed):
                final = plan_adaptive_followup(
                    initial, GIB, observed_cpu_percent=20,
                    available_memory_bytes=100 * GIB,
                    total_physical_memory_bytes=128 * GIB,
                    first_batch_completed=completed,
                )
                self.assertEqual(final["limits"]["maximum_concurrency"], 4)
                self.assertLessEqual(
                    final["limits"]["maximum_concurrency"] * 20,
                    final["limits"]["cpu_admission_percent"],
                )
                batches = final["waves"][0]["batches"]
                self.assertEqual(sum(batch["count"] for batch in batches), 5000)
                self.assertEqual(batches[0]["particle_id_min"], 1)
                self.assertEqual(batches[-1]["particle_id_max"], 5000)

    def test_completed_first_batch_keeps_balanced_lane_remainder(self) -> None:
        initial = plan_simion_dispatch(
            self.request(), [], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000,
            logical_processors=16,
        )
        final = plan_adaptive_followup(
            initial, GIB, observed_cpu_percent=8, background_cpu_percent=5,
            available_memory_bytes=int(4.5 * GIB), total_physical_memory_bytes=10 * GIB,
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
            logical_processors=16,
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
        # Three further uninflated peak budgets fit in current free RAM. The
        # formal first batch already consumes the fourth, retained lane.
        self.assertEqual(final["limits"]["memory_capacity"], 4)
        self.assertEqual(final["limits"]["maximum_concurrency"], 4)

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
            available_memory_bytes=int(1.2 * GIB), total_physical_memory_bytes=10 * GIB,
        )
        self.assertEqual(final["limits"]["maximum_concurrency"], 2)
        self.assertEqual(
            [item["count"] for item in final["waves"][0]["batches"]],
            [500, 2_500, 2_000],
        )

    def test_known_profile_uses_one_even_batch_per_allowed_lane(self) -> None:
        plan = plan_simion_dispatch(
            self.request(), [self.profile(peak=GIB)], available_memory_bytes=4 * GIB,
            total_physical_memory_bytes=10 * GIB, background_cpu_percent=5,
            logical_processors=16,
        )
        self.assertEqual(plan["estimation"]["kind"], "exact_resource_profile")
        self.assertTrue(plan["estimation"]["observation_wait_skipped"])
        self.assertEqual(plan["limits"]["maximum_concurrency"], 4)
        self.assertEqual(plan["waves"][0]["batch_count"], 4)
        self.assertEqual([item["count"] for item in plan["waves"][0]["batches"]], [1_250, 1_250, 1_250, 1_250])
        event = format_dispatch_decision_event(plan)
        self.assertIn("MEASUREMENT=EXACT_HISTORICAL_PROFILE", event)
        self.assertIn("BATCHES=4", event)
        self.assertIn("PROCESS_MEMORY_BUDGET=1.00GiB", event)

    def test_smaller_observed_batch_profile_cannot_schedule_larger_batches(self) -> None:
        plan = plan_simion_dispatch(
            self.request(),
            # The profile is valid for the retained N=500 probe, but not for
            # the N=1,250 lanes that its measured peak would otherwise admit.
            [self.profile(peak=GIB, observed_batch_work_units=500)],
            available_memory_bytes=6 * GIB,
            total_physical_memory_bytes=10 * GIB,
        )
        self.assertEqual(
            plan["estimation"]["kind"], "formal_first_batch_observation"
        )
        self.assertEqual(plan["waves"][0]["batches"][0]["count"], 500)

    def test_profile_requires_exact_numerical_identity(self) -> None:
        plan = plan_simion_dispatch(
            self.request(trajectory_quality=17), [self.profile()],
            available_memory_bytes=10_000, total_physical_memory_bytes=20_000,
        )
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")

    def test_profile_requires_exact_workbench_topology(self) -> None:
        plan = plan_simion_dispatch(
            self.request(workload_topology_id="pre_pulse_minimal_3_instance_iob_v1"),
            [self.profile()], available_memory_bytes=10_000,
            total_physical_memory_bytes=20_000,
        )
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")

    def test_profile_requires_same_field_loading_policy(self) -> None:
        request = self.request(field_loading_policy_id="dynamic_subset_v1")
        profile = self.profile(peak=GIB)
        unmatched = plan_simion_dispatch(request, [profile])
        self.assertEqual(
            unmatched["estimation"]["kind"], "formal_first_batch_observation"
        )
        profile["resource_identity"]["field_loading_policy_id"] = "dynamic_subset_v1"
        matched = plan_simion_dispatch(request, [profile])
        self.assertEqual(matched["estimation"]["kind"], "exact_resource_profile")
        runtime = plan_runtime_dispatch(matched)
        self.assertEqual(runtime["estimation"]["kind"], "exact_resource_profile")
        self.assertEqual(
            runtime["resource_identity"]["field_loading_policy_id"], "dynamic_subset_v1"
        )

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
            logical_processors=16,
        )
        runtime = plan_runtime_dispatch(
            prepared, available_memory_bytes=6 * GIB,
            total_physical_memory_bytes=10 * GIB,
            logical_processors=16,
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
                "observed_batch_work_units": 1,
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
                    "--available-memory-bytes", str(int(4.5 * GIB)),
                    "--total-physical-memory-bytes", str(10 * GIB),
                    "--logical-processors", "16",
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
