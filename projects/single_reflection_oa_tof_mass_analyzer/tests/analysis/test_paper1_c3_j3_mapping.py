"""Tests for the exact C2-J3 to physical-control bridge."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c3_j3_mapping import (
    compile_c2_j3_physical_control_family,
)


ROOT = Path(__file__).resolve().parents[4]
CAMPAIGN = ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/experiments/three_zone_solver_free_funnel_v2.json"


class Paper1C3J3MappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "c2.json"
        zero = [1701.7426470171715, 9.880402594968652, -1.0391326394747527]
        delta = [0.24444052496, 0.00003669741, -0.00000646281]
        directions = {
            name: {"controls": [base + sign * step for base, step in zip(zero, delta, strict=True)]}
            for name, sign in (("improve", 1.0), ("zero", 0.0), ("worsen", -1.0))
        }
        self.result = {"stage_id": "C2_J3", "conclusion": "PASS_CONTINUE", "metrics": {"claim_target": "j3_local_direction", "rows": [{"architecture": "three_zone", "source_id": "S1", "directions": directions}]}}
        self.path.write_text(json.dumps(self.result), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_compiles_each_physical_point_from_raw_j3_controls(self) -> None:
        family = compile_c2_j3_physical_control_family(campaign_path=CAMPAIGN, c2_result_path=self.path, source_id="S1")
        self.assertEqual([item["scale_h"] for item in family["variants"]], [-2.0, -1.0, 0.0, 1.0, 2.0])
        self.assertEqual(family["variants"][2]["inner_controls"]["eta"], -1.0391326394747527)
        self.assertTrue(all(item["requires_pa_rebuild"] for item in family["variants"]))
        self.assertEqual(family["campaign"]["sha256"], file_sha256(CAMPAIGN))
        candidate = {"role": "oatof_three_zone_simion_candidate_resolved", **family["variants"][2]}
        candidate.pop("scale_h")
        candidate.pop("inner_controls")
        candidate.pop("requires_pa_rebuild")
        candidate_path = Path(self.temp.name) / "candidate.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        checked = compile_c2_j3_physical_control_family(campaign_path=CAMPAIGN, c2_result_path=self.path, source_id="S1", candidate_path=candidate_path)
        self.assertEqual(checked["base_candidate"]["sha256"], file_sha256(candidate_path))

    def test_rejects_asymmetric_direction(self) -> None:
        self.result["metrics"]["rows"][0]["directions"]["worsen"]["controls"][0] -= 0.1
        self.path.write_text(json.dumps(self.result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "symmetric"):
            compile_c2_j3_physical_control_family(campaign_path=CAMPAIGN, c2_result_path=self.path, source_id="S1")

    def test_cli_writes_machine_readable_family(self) -> None:
        output = Path(self.temp.name) / "physical_family.json"
        completed = subprocess.run(
            [sys.executable, "-m", "projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c3_j3_mapping", "--campaign", str(CAMPAIGN), "--c2-j3-result", str(self.path), "--source-id", "S1", "--output", str(output)],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["source_id"], "S1")


if __name__ == "__main__":
    unittest.main()
