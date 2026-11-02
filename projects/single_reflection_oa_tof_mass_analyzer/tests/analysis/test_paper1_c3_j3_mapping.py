"""Tests for the exact C2-J3 to physical-control bridge."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from msplatform.contracts.machine_contracts import validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis import paper1_c3_j3_publish as publisher
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c3_j3_mapping import (
    compile_c2_j3_physical_control_family,
    compile_c3_j3_variant_candidate,
)


ROOT = Path(__file__).resolve().parents[4]
CAMPAIGN = ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/experiments/three_zone_solver_free_funnel_v2.json"


def _write_base_candidate(directory: Path, campaign_path: Path, family: dict) -> Path:
    """Materialize the same exact zero-point input for mapping and publication."""
    candidate = {
        "schema_version": 1, "role": "oatof_three_zone_simion_candidate_resolved",
        "project_id": "single_reflection_oa_tof_mass_analyzer", "qualification": "CANDIDATE_ONLY",
        "compiler_mode": "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
        "campaign": {"campaign_id": "three_zone_solver_free_funnel_v2", "file": {"path": str(campaign_path), "bytes": campaign_path.stat().st_size, "sha256": file_sha256(campaign_path)}},
        "t5_evidence": {"stage_id": "T5", "status": "success", "conclusion": "PRIMARY_THEORY_ONLY_SUPPORTED", "plan_sha256": "A" * 64, "receipt": {"path": str(campaign_path), "bytes": campaign_path.stat().st_size, "sha256": file_sha256(campaign_path)}, "report": {"path": str(campaign_path), "bytes": campaign_path.stat().st_size, "sha256": file_sha256(campaign_path)}, "frozen_primary_row_id": "frozen_primary", "frozen_branch_root": {"policy": "scaled_parameter_distance_unique_nearest", "reference_fixture_id": "anchor", "accepted_index": 0, "cluster_index": 0, "coordinates": [0.0, 0.0, 0.0], "distance_to_branch_reference": 0.0, "inner": {"eta": -1.0, "u_r1_v": 1600.0, "f_r2_v_per_mm": 10.0}}},
        "source_identity": {"authority": "campaign.frozen_source", "campaign_id": "three_zone_solver_free_funnel_v2", "campaign_sha256": file_sha256(campaign_path), "frozen_source": {"mass_to_charge_th": 100.0, "charge_sign": 1, "center_x_mm": 1.5, "center_velocity_m_per_s": 0.0, "velocity_slope_m_per_s_per_mm": 1.0, "nominal_energy_per_charge_v": 2000.0}},
        "identities": {"topology_id": "three_zone_accelerator_ideal_v1", "geometry_id": "three_zone_focus_origin_planes_v1", "field_id": "three_zone_piecewise_uniform_ideal_field_v1"},
        "claim_limit": "test", **family["variants"][2],
    }
    candidate.pop("scale_h")
    candidate.pop("inner_controls")
    candidate.pop("requires_pa_rebuild")
    candidate_path = directory / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    return candidate_path


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

    def publication_inputs(self) -> tuple[Path, Path, Path, Path]:
        workspace = Path(self.temp.name)
        parent = workspace / "parent"
        parent.mkdir()
        campaign = parent / "campaign.json"
        campaign.write_bytes(CAMPAIGN.read_bytes())
        family = compile_c2_j3_physical_control_family(
            campaign_path=campaign, c2_result_path=self.path, source_id="S1")
        candidate = _write_base_candidate(parent, campaign, family)
        code_root = workspace / "simulation_repo"
        for relative in ("projects/single_reflection_oa_tof_mass_analyzer/analysis/paper1_c3_j3_publish.py",
                         "projects/single_reflection_oa_tof_mass_analyzer/analysis/paper1_c3_j3_mapping.py"):
            copied = code_root / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, copied)
        copied_publisher = code_root / Path(publisher.__file__).relative_to(ROOT)
        return campaign, candidate, code_root, copied_publisher

    def test_publication_freezes_installed_schema_for_all_five_candidates(self) -> None:
        campaign, candidate, code_root, copied_publisher = self.publication_inputs()
        workspace = Path(self.temp.name)
        schema_source = publisher.SCHEMA_DIR / "oatof_three_zone_simion_candidate_resolved.schema.json"
        self.assertFalse(schema_source.resolve().is_relative_to(workspace.resolve()))
        parents = {path: path.read_bytes() for path in (campaign, candidate, self.path)}
        run = workspace / "artifacts/projects" / publisher.PROJECT_ID / "runs/20261102_190000__build__python__c3-installed-schema"
        with (mock.patch.object(publisher, "__file__", str(copied_publisher)),
              mock.patch.object(publisher, "REPOSITORY_ROOT", code_root),
              mock.patch.dict(os.environ, {"PYTHONPATH": str(ROOT)})):
            summary = publisher.publish_c3_j3_candidates(
                campaign_path=campaign, c2_result_path=self.path, source_id="S1",
                base_candidate_path=candidate, run_dir=run, workspace_root=workspace)
        config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        schema_relative = f"inputs/schemas/{schema_source.name}"
        self.assertEqual(config["inputs"]["candidate_schema"], schema_relative)
        schema_record = manifest["inputs"]["candidate_schema"]
        self.assertEqual(schema_record["path"], schema_relative)
        self.assertEqual(record_path(schema_record, base_dir=run), run / schema_relative)
        self.assertEqual((run / schema_relative).read_bytes(), schema_source.read_bytes())
        self.assertEqual(schema_record["bytes"], schema_source.stat().st_size)
        self.assertEqual(schema_record["sha256"], file_sha256(schema_source))
        self.assertFalse(manifest["formal_eligible"])
        self.assertFalse(summary["formal_gate_passed"])
        self.assertEqual(summary["qualification"], "CANDIDATE_ONLY")
        self.assertEqual(set(summary["candidates"]), {"-2", "-1", "0", "1", "2"})
        family_path = run / summary["physical_family"]["path"]
        family = json.loads(family_path.read_text(encoding="utf-8"))
        self.assertEqual([row["scale_h"] for row in family["variants"]], [-2., -1., 0., 1., 2.])
        for scale in publisher.SCALES:
            with self.subTest(scale=scale):
                item = summary["candidates"][str(scale)]
                output = run / item["path"]
                value = json.loads(output.read_text(encoding="utf-8"))
                validate_schema(value, schema_source.name)
                expected = compile_c3_j3_variant_candidate(
                    base_candidate_path=candidate, physical_family_path=family_path, scale_h=float(scale))
                expected["c3_j3_evidence"]["physical_family"] = {
                    "path": family_path.relative_to(workspace).as_posix(),
                    "bytes": family_path.stat().st_size, "sha256": file_sha256(family_path)}
                self.assertEqual(value, expected)
                self.assertEqual(item["bytes"], output.stat().st_size)
                self.assertEqual(item["sha256"], file_sha256(output))
        for label, record in manifest["inputs"].items():
            verify_record(label, record, base_dir=run)
        for record in manifest["outputs"]:
            verify_record("candidate output", record, base_dir=run)
        self.assertEqual(parents, {path: path.read_bytes() for path in parents})
        self.assertEqual(list(run.parent.glob(".*")), [])
        with self.assertRaises(FileExistsError):
            publisher.publish_c3_j3_candidates(
                campaign_path=campaign, c2_result_path=self.path, source_id="S1",
                base_candidate_path=candidate, run_dir=run, workspace_root=workspace)

    def test_publication_failure_cleans_staging_and_keeps_project_sources_local(self) -> None:
        campaign, candidate, code_root, copied_publisher = self.publication_inputs()
        workspace = Path(self.temp.name)
        run = workspace / "artifacts/projects" / publisher.PROJECT_ID / "runs/20261102_190001__build__python__c3-publication-failure"
        parents = {path: path.read_bytes() for path in (campaign, candidate, self.path)}
        arguments = dict(campaign_path=campaign, c2_result_path=self.path, source_id="S1",
                         base_candidate_path=candidate, run_dir=run, workspace_root=workspace)
        with self.assertRaisesRegex(ValueError, "publisher_source must be inside"):
            publisher.publish_c3_j3_candidates(**arguments)
        self.assertFalse(run.exists())
        with (mock.patch.object(publisher, "__file__", str(copied_publisher)),
              mock.patch.object(publisher, "REPOSITORY_ROOT", code_root),
              mock.patch.object(publisher, "_publish_manifest", side_effect=RuntimeError("publication fault")),
              self.assertRaisesRegex(RuntimeError, "publication fault")):
            publisher.publish_c3_j3_candidates(**arguments)
        self.assertFalse(run.exists())
        self.assertEqual(list(run.parent.glob(".*")), [])
        self.assertEqual(parents, {path: path.read_bytes() for path in parents})

    def test_compiles_each_physical_point_from_raw_j3_controls(self) -> None:
        family = compile_c2_j3_physical_control_family(campaign_path=CAMPAIGN, c2_result_path=self.path, source_id="S1")
        self.assertEqual([item["scale_h"] for item in family["variants"]], [-2.0, -1.0, 0.0, 1.0, 2.0])
        self.assertEqual(family["variants"][2]["inner_controls"]["eta"], -1.0391326394747527)
        self.assertTrue(all(item["requires_pa_rebuild"] for item in family["variants"]))
        self.assertEqual(family["campaign"]["sha256"], file_sha256(CAMPAIGN))
        candidate_path = _write_base_candidate(Path(self.temp.name), CAMPAIGN, family)
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
