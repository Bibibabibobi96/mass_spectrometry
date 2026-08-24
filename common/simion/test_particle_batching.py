import unittest
import json
import tempfile
from pathlib import Path

from common.simion.particle_batching import (
    merge_rebased_particle_csvs,
    merge_simion_summaries,
    plan_single_wave_batches,
)


class ParticleBatchingTests(unittest.TestCase):
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
