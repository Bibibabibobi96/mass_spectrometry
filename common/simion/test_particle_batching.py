import unittest
import json
import tempfile
from pathlib import Path

from common.simion.particle_batching import (
    choose_memory_bound_batch_count,
    merge_rebased_particle_csvs,
    merge_simion_summaries,
    plan_single_wave_batches,
    select_nearest_memory_profile,
)


class ParticleBatchingTests(unittest.TestCase):
    def test_memory_bound_choice_uses_available_memory_and_contract_cap(self) -> None:
        decision = choose_memory_bound_batch_count(
            5000, 2, 4, 12 * 1024**3, 1024**3, 40 * 1024**3
        )
        self.assertEqual(decision["selected_batch_count"], 3)
        self.assertEqual(
            decision["selection_reason"],
            "largest_count_within_current_available_memory",
        )

    def test_nearest_memory_profile_prefers_matching_resource_identity(self) -> None:
        target = {"solver": "SIMION", "mode": "single", "time_integration_profile_id": "dt40"}
        selected = select_nearest_memory_profile(target, [
            {"per_batch_peak_working_set_bytes": 11, "resource_identity": {"solver": "SIMION", "mode": "single", "time_integration_profile_id": "dt40"}},
            {"per_batch_peak_working_set_bytes": 99, "resource_identity": {"solver": "SIMION", "mode": "other", "time_integration_profile_id": "dt160"}},
        ])
        self.assertEqual(selected["per_batch_peak_working_set_bytes"], 11)
        self.assertEqual(selected["match_kind"], "estimated_from_nearest_profile")

    def test_memory_bound_choice_fails_closed_when_one_batch_does_not_fit(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot support even one batch"):
            choose_memory_bound_batch_count(
                5000, 2, 4, 12 * 1024**3, 1 * 1024**3, 12 * 1024**3
            )

    def test_balanced_complete_plan(self) -> None:
        plan = plan_single_wave_batches(5000, 5)
        self.assertEqual(plan["dispatch"], "single_wave_parallel")
        self.assertEqual(plan["batches"][0], {
            "index": 1, "count": 1000, "particle_id_min": 1,
            "particle_id_max": 1000, "simion_particle_id_offset": 0,
        })
        self.assertEqual(plan["batches"][-1]["particle_id_max"], 5000)

    def test_remainder_stays_in_one_wave(self) -> None:
        plan = plan_single_wave_batches(1000, 3)
        self.assertEqual([item["count"] for item in plan["batches"]], [334, 333, 333])
        self.assertEqual([item["particle_id_min"] for item in plan["batches"]], [1, 335, 668])

    def test_rejects_invalid_plan(self) -> None:
        for particle_count, batch_count in ((0, 1), (1000, 0), (2, 3)):
            with self.assertRaises(ValueError):
                plan_single_wave_batches(particle_count, batch_count)

    def test_python_merges_rebased_data_and_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, output = root / "first.csv", root / "second.csv", root / "out.csv"
            first.write_text("particle_id,event\n1,source\n2,source\n", encoding="utf-8")
            second.write_text("particle_id,event\n1,source\n2,source\n", encoding="utf-8")
            merge_rebased_particle_csvs([(first, 0), (second, 2)], output)
            self.assertEqual(output.read_text(encoding="utf-8").splitlines()[-1], "4,source")
            plan = plan_single_wave_batches(4, 2)
            summaries = []
            for index in (1, 2):
                path = root / f"summary{index}.json"
                path.write_text(json.dumps({"solver":"SIMION","mode":"m","operating_point":"p","parent_resolved_design_sha256":"A","particles":2,"census_plane_crossings":2,"hits":2,"transmission":1.0}), encoding="utf-8")
                summaries.append(path)
            merged = root / "summary.json"
            merge_simion_summaries(summaries, plan, merged)
            self.assertEqual(json.loads(merged.read_text(encoding="utf-8"))["particles"], 4)
