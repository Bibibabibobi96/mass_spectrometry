"""Fail-closed checks for the local-replacement center-flight summary."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_center_result import analyze


HANDOFFS = (
    ("handoff_negative_central_to_bridge__z_plane", "negative_central_to_bridge", "z_min", -72),
    ("handoff_positive_central_to_bridge__z_plane", "positive_central_to_bridge", "z_max", 72),
    ("handoff_negative_bridge_to_mirror__z_plane", "negative_bridge_to_mirror", "z_min", -131),
    ("handoff_positive_bridge_to_mirror__z_plane", "positive_bridge_to_mirror", "z_max", 131),
)


def fixture_log(instances: tuple[int, ...]) -> str:
    lines = []
    for index, instance in enumerate(instances):
        lines.append(
            "MRTOF_EVENT instance_transition ion=1 t_us={0} instance={1} "
            "x_mm=0 y_mm=0 z_mm={2}".format(index + 1, instance, (instance - 4) * 70)
        )
    for index, (name, region, face, z_mm) in enumerate(HANDOFFS):
        lines.append(
            "MRTOF_EVENT patch_interface ion=1 name={0} region={1} face={2} n=1 "
            "direction=1 t_us={3} x_mm=0 y_mm=0 z_mm={4} "
            "vx_mm_us=0 vy_mm_us=1 vz_mm_us=20".format(name, region, face, index + 20, z_mm)
        )
    lines.extend((
        "MRTOF_EVENT target_k_phase_sample ion=1 k=25 t_us=100 x_mm=0 y_mm=0 z_mm=0 "
        "vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
        "MRTOF_EVENT target_k ion=1 k=25 t_us=101 x_mm=0 y_mm=0 z_mm=0",
        "MRTOF_EVENT terminal ion=1 splat=-1 t_us=102 turns=50 x_mm=0 y_mm=0 z_mm=0 "
        "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=50",
        "status,Fly completed. 1 splats, 1 seconds",
    ))
    return "\n".join(lines) + "\n"


class AnalyzerLocalCenterResultTest(unittest.TestCase):
    def run_fixture(self, instances: tuple[int, ...]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "flight.log"
            materialization = root / "materialization.json"
            log.write_text(fixture_log(instances), encoding="utf-8")
            materialization.write_text(json.dumps({"target_oscillation_count": 25}), encoding="utf-8")
            return analyze(log, materialization)

    def test_all_five_local_regions_and_four_handoffs_pass(self):
        result = self.run_fixture((4, 5, 6, 5, 4, 3, 2))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["errors"], [])

    def test_missing_local_region_fails_closed(self):
        result = self.run_fixture((4, 5, 6, 5, 4, 3))
        self.assertEqual(result["status"], "failed")
        self.assertIn("not_all_local_replacement_regions_exercised", result["errors"])

    def test_instance_zero_fails_closed(self):
        result = self.run_fixture((4, 5, 6, 5, 4, 3, 2, 0))
        self.assertEqual(result["status"], "failed")
        self.assertIn("trajectory_left_all_declared_pa_instances", result["errors"])


if __name__ == "__main__":
    unittest.main()
