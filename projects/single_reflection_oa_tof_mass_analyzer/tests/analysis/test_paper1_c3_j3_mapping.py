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
    compile_c3_j3_variant_candidate,
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
        candidate = {
            "schema_version": 1, "role": "oatof_three_zone_simion_candidate_resolved",
            "project_id": "single_reflection_oa_tof_mass_analyzer", "qualification": "CANDIDATE_ONLY",
            "compiler_mode": "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
            "campaign": {"campaign_id": "three_zone_solver_free_funnel_v2", "file": {"path": str(CAMPAIGN), "bytes": CAMPAIGN.stat().st_size, "sha256": file_sha256(CAMPAIGN)}},
            "t5_evidence": {"stage_id": "T5", "status": "success", "conclusion": "PRIMARY_THEORY_ONLY_SUPPORTED", "plan_sha256": "A" * 64, "receipt": {"path": str(CAMPAIGN), "bytes": CAMPAIGN.stat().st_size, "sha256": file_sha256(CAMPAIGN)}, "report": {"path": str(CAMPAIGN), "bytes": CAMPAIGN.stat().st_size, "sha256": file_sha256(CAMPAIGN)}, "frozen_primary_row_id": "frozen_primary", "frozen_branch_root": {"policy": "scaled_parameter_distance_unique_nearest", "reference_fixture_id": "anchor", "accepted_index": 0, "cluster_index": 0, "coordinates": [0.0, 0.0, 0.0], "distance_to_branch_reference": 0.0, "inner": {"eta": -1.0, "u_r1_v": 1600.0, "f_r2_v_per_mm": 10.0}}},
            "source_identity": {"authority": "campaign.frozen_source", "campaign_id": "three_zone_solver_free_funnel_v2", "campaign_sha256": file_sha256(CAMPAIGN), "frozen_source": {"mass_to_charge_th": 100.0, "charge_sign": 1, "center_x_mm": 1.5, "center_velocity_m_per_s": 0.0, "velocity_slope_m_per_s_per_mm": 1.0, "nominal_energy_per_charge_v": 2000.0}},
            "identities": {"topology_id": "three_zone_accelerator_ideal_v1", "geometry_id": "three_zone_focus_origin_planes_v1", "field_id": "three_zone_piecewise_uniform_ideal_field_v1"},
            "claim_limit": "test", **family["variants"][2],
        }
        candidate.pop("scale_h")
        candidate.pop("inner_controls")
        candidate.pop("requires_pa_rebuild")
        candidate_path = Path(self.temp.name) / "candidate.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        checked = compile_c2_j3_physical_control_family(campaign_path=CAMPAIGN, c2_result_path=self.path, source_id="S1", candidate_path=candidate_path)
        self.assertEqual(checked["base_candidate"]["sha256"], file_sha256(candidate_path))
        family_path = Path(self.temp.name) / "family.json"
        family_path.write_text(json.dumps(checked), encoding="utf-8")
        variant = compile_c3_j3_variant_candidate(base_candidate_path=candidate_path, physical_family_path=family_path, scale_h=1.0)
        self.assertEqual(variant["compiler_mode"], "C3_J3_EXACT_LOCAL_DIRECTION_V1")
        self.assertEqual(variant["c3_j3_evidence"]["scale_h"], 1.0)

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
