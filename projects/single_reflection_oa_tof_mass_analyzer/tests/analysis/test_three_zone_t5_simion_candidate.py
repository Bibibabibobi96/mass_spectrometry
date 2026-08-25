"""Contract tests for the frozen T5-to-SIMION Candidate compiler."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    OuterGeometry,
    derive_three_zone_state,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    three_zone_t5_simion_candidate as candidate_compiler,
)


compile_t5_simion_candidate = candidate_compiler.compile_t5_simion_candidate
publish_t5_simion_candidate = candidate_compiler.publish_t5_simion_candidate


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CANONICAL_CAMPAIGN = (
    REPOSITORY_ROOT
    / "projects"
    / "single_reflection_oa_tof_mass_analyzer"
    / "config"
    / "experiments"
    / "three_zone_solver_free_funnel_v2.json"
)


def _write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


class ThreeZoneT5SimionCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.campaign_path = self.root / "campaign.json"
        self.report_path = self.root / "stage_report.json"
        self.receipt_path = self.root / "stage_receipt.json"
        self.campaign = json.loads(CANONICAL_CAMPAIGN.read_text(encoding="utf-8"))
        for record in self.campaign["authorities"].values():
            authority = REPOSITORY_ROOT / record["path"]
            record["bytes"] = authority.stat().st_size
            record["sha256"] = file_sha256(authority)
        _write_json(self.campaign_path, self.campaign)

        outer = dict(self.campaign["fixtures"]["low_contrast_anchor"]["outer"])
        inner = dict(self.campaign["fixtures"]["low_contrast_anchor"]["inner"])
        source_record = self.campaign["frozen_source"]
        source = AffineSource.from_velocity(
            mass_to_charge_th=source_record["mass_to_charge_th"],
            center_x_mm=source_record["center_x_mm"],
            center_velocity_m_per_s=source_record["center_velocity_m_per_s"],
            velocity_slope_m_per_s_per_mm=source_record[
                "velocity_slope_m_per_s_per_mm"
            ],
        )
        geometry = OuterGeometry(
            zone1_length_mm=outer["d1_mm"],
            downstream_length_mm=outer["l23_mm"],
            split_fraction=outer["lambda"],
            zone1_voltage_drop_v=outer["delta_v1_v"],
            nominal_energy_per_charge_v=source_record[
                "nominal_energy_per_charge_v"
            ],
        )
        state = derive_three_zone_state(source, geometry, inner["eta"])
        post_root = {"workflow_post_root_passed": True}
        branch = {
            "accepted_index": 0,
            "cluster_index": 2,
            "coordinates": [0.8508713235085858, 0.475, -0.4513],
            "distance_to_branch_reference": 0.0,
            "inner": inner,
            "jacobian_condition": 2.0,
            "post_root_audit": post_root,
        }
        primary = {
            "row_id": "frozen_primary",
            "row_status": "accepted_unique_root",
            "outer": outer,
            "inner": inner,
            "workflow_accepted_root_count": 1,
            "accelerator_field_contrast": max(
                state.field_ratio_2_over_3, 1.0 / state.field_ratio_2_over_3
            ),
            "branch_selection_audit": {
                "policy": "scaled_parameter_distance_unique_nearest",
                "performance_used": False,
                "reference_fixture_id": self.campaign["root_policy"][
                    "three_zone_branch_reference_fixture_id"
                ],
                "accepted_root_summaries": [branch],
                "chosen_accepted_index": 0,
                "machine_safe_tie": False,
            },
            "post_root_audit": post_root,
        }
        conclusion = "PRIMARY_THEORY_ONLY_SUPPORTED"
        claim_limit = self.campaign["claim_limit"]
        self.report = {
            "schema_version": 1,
            "role": "oatof_three_zone_stage_report",
            "campaign_id": self.campaign["campaign_id"],
            "stage_id": "T5",
            "plan_sha256": "A" * 64,
            "status": "success",
            "scientific_assessment": conclusion,
            "engineering_compatibility_annotation": (
                "REAL_FIELD_AND_MANUFACTURING_NOT_ASSESSED"
            ),
            "row_census": {
                "planned": 4,
                "completed": 4,
                "failed": 0,
                "not_started": 0,
            },
            "results": {"rows": [primary]},
            "allowed_claim": "Solver-free T5 theory confirmation only.",
            "claim_limit": claim_limit,
        }
        _write_json(self.report_path, self.report)
        self.receipt = {
            "schema_version": 1,
            "role": "oatof_three_zone_stage_receipt",
            "campaign_id": self.campaign["campaign_id"],
            "campaign_sha256": file_sha256(self.campaign_path),
            "stage_id": "T5",
            "plan_sha256": "A" * 64,
            "status": "success",
            "conclusion": conclusion,
            "next_stage_authorized": False,
            "assessment_design_status": (
                "POST_PILOT_STAGE_GATED_OPTIMIZATION_THEN_FROZEN_CONFIRMATION"
            ),
            "solver_execution_performed": False,
            "performance_metrics_read": True,
            "completed_rows": 4,
            "planned_rows": 4,
            "selected_outer_points": [outer],
            "frozen_primary": outer,
            "best_feasible_two_zone": dict(
                self.campaign["fixtures"]["current_exact_baseline"]["outer"]
            ),
            "report": {
                "path": str(self.report_path.resolve()),
                "bytes": self.report_path.stat().st_size,
                "sha256": file_sha256(self.report_path),
            },
            "recorded_at_utc": "2026-08-17T00:00:00+00:00",
            "claim_limit": claim_limit,
        }
        _write_json(self.receipt_path, self.receipt)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _rewrite_report_binding(self) -> None:
        _write_json(self.report_path, self.report)
        self.receipt["report"]["bytes"] = self.report_path.stat().st_size
        self.receipt["report"]["sha256"] = file_sha256(self.report_path)
        _write_json(self.receipt_path, self.receipt)

    def test_compiles_exact_frozen_candidate_and_consumer_mapping(self) -> None:
        resolved = compile_t5_simion_candidate(
            self.campaign_path, self.receipt_path
        )
        topology = resolved["accelerator_topology"]
        self.assertEqual(topology["topology_id"], "three_zone_accelerator_ideal_v1")
        self.assertEqual(
            set(topology["planes_global_z_mm"]),
            {"repeller", "intermediate1", "intermediate2", "exit"},
        )
        self.assertEqual(
            set(topology["potentials_v"]),
            {"repeller", "intermediate1", "intermediate2", "exit"},
        )
        planes = topology["planes_global_z_mm"]
        lengths = resolved["accelerator_physics"]["lengths_mm"]
        self.assertAlmostEqual(
            planes["intermediate1"] - planes["repeller"], lengths["d1"]
        )
        self.assertAlmostEqual(
            planes["intermediate2"] - planes["intermediate1"], lengths["d2"]
        )
        self.assertAlmostEqual(
            planes["exit"] - planes["intermediate2"], lengths["d3"]
        )
        self.assertEqual(
            planes["exit"],
            -resolved["accelerator_physics"]["focus_drift_after_exit_mm"],
        )
        self.assertEqual(resolved["qualification"], "CANDIDATE_ONLY")
        self.assertEqual(
            resolved["t5_evidence"]["frozen_branch_root"]["inner"],
            self.report["results"]["rows"][0]["inner"],
        )

    def test_rejects_report_content_changed_after_receipt(self) -> None:
        self.report["allowed_claim"] = "tampered after receipt"
        _write_json(self.report_path, self.report)
        with self.assertRaisesRegex(ValueError, "byte count|SHA-256"):
            compile_t5_simion_candidate(self.campaign_path, self.receipt_path)

    def test_rejects_failed_or_deferred_conclusion(self) -> None:
        self.receipt["conclusion"] = "PRIMARY_CONFIRMATION_FAILED"
        self.report["scientific_assessment"] = "PRIMARY_CONFIRMATION_FAILED"
        self._rewrite_report_binding()
        with self.assertRaisesRegex(ValueError, "does not support"):
            compile_t5_simion_candidate(self.campaign_path, self.receipt_path)

    def test_rejects_duplicate_frozen_primary_rows(self) -> None:
        primary = self.report["results"]["rows"][0]
        self.report["results"]["rows"].append(copy.deepcopy(primary))
        self._rewrite_report_binding()
        with self.assertRaisesRegex(ValueError, "exactly one frozen_primary"):
            compile_t5_simion_candidate(self.campaign_path, self.receipt_path)

    def test_rejects_performance_selected_or_tied_branch(self) -> None:
        audit = self.report["results"]["rows"][0]["branch_selection_audit"]
        audit["performance_used"] = True
        self._rewrite_report_binding()
        with self.assertRaisesRegex(ValueError, "never use performance"):
            compile_t5_simion_candidate(self.campaign_path, self.receipt_path)

        audit["performance_used"] = False
        audit["machine_safe_tie"] = True
        self._rewrite_report_binding()
        with self.assertRaisesRegex(ValueError, "tied or not proven unique"):
            compile_t5_simion_candidate(self.campaign_path, self.receipt_path)

    def test_rejects_receipt_primary_different_from_report_row(self) -> None:
        self.receipt["frozen_primary"]["d1_mm"] += 0.25
        _write_json(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            compile_t5_simion_candidate(self.campaign_path, self.receipt_path)

    def test_optional_canonical_t5_artifact(self) -> None:
        receipt_value = os.environ.get("OATOF_THREE_ZONE_T5_RECEIPT")
        if not receipt_value:
            self.skipTest("OATOF_THREE_ZONE_T5_RECEIPT is not configured")
        resolved = compile_t5_simion_candidate(
            CANONICAL_CAMPAIGN, Path(receipt_value)
        )
        self.assertEqual(resolved["qualification"], "CANDIDATE_ONLY")

    def test_publishes_portable_canonical_artifact_run_atomically(self) -> None:
        run_id = "20260817_170000__build__python__three-zone-t5-candidate"
        run_dir = (
            self.root
            / "artifacts"
            / "projects"
            / "single_reflection_oa_tof_mass_analyzer"
            / "runs"
            / run_id
        )
        code_root = self.root / "simulation_repo"
        code_inputs = {
            "COMPILER_SOURCE": candidate_compiler.COMPILER_SOURCE,
            "THEORY_CORE_SOURCE": candidate_compiler.THEORY_CORE_SOURCE,
            "EXPERIMENT_CORE_SOURCE": candidate_compiler.EXPERIMENT_CORE_SOURCE,
            "OUTPUT_SCHEMA_SOURCE": candidate_compiler.OUTPUT_SCHEMA_SOURCE,
        }
        relocated_code = {}
        for attribute, source in code_inputs.items():
            destination = code_root / source.relative_to(REPOSITORY_ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            relocated_code[attribute] = destination
        with mock.patch.multiple(candidate_compiler, **relocated_code):
            summary = publish_t5_simion_candidate(
                self.campaign_path,
                self.receipt_path,
                run_dir,
                workspace_root=self.root,
            )
        candidate_path = (
            run_dir / "results" / "three_zone_t5_simion_candidate_resolved.json"
        )
        self.assertEqual(
            set(path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*")),
            {
                "results",
                "results/three_zone_t5_simion_candidate_resolved.json",
                "run_config.json",
                "summary.json",
                "run_manifest.json",
            },
        )
        self.assertFalse(summary["formal_gate_passed"])
        self.assertEqual(summary["candidate"]["sha256"], file_sha256(candidate_path))
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        for record in (
            candidate["campaign"]["file"],
            candidate["t5_evidence"]["receipt"],
            candidate["t5_evidence"]["report"],
        ):
            self.assertFalse(Path(record["path"]).is_absolute())
        run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
        self.assertFalse(run_config["formal_gate_passed"])
        self.assertNotIn("project_root", run_config)
        self.assertTrue(
            all(not Path(value).is_absolute() for value in run_config["inputs"].values())
        )
        expected_code_inputs = {
            "candidate_compiler_source": relocated_code["COMPILER_SOURCE"],
            "three_zone_ideal_theory_source": relocated_code["THEORY_CORE_SOURCE"],
            "three_zone_theory_experiment_source": relocated_code[
                "EXPERIMENT_CORE_SOURCE"
            ],
            "candidate_output_schema": relocated_code["OUTPUT_SCHEMA_SOURCE"],
        }
        self.assertEqual(
            set(expected_code_inputs),
            set(run_config["inputs"]) - {"campaign", "t5_receipt", "t5_report"},
        )
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        records = [
            manifest["run_config"],
            *manifest["inputs"].values(),
            *manifest["outputs"],
        ]
        self.assertTrue(all(not Path(record["path"]).is_absolute() for record in records))
        self.assertFalse(manifest["formal_eligible"])
        for name, source in expected_code_inputs.items():
            self.assertEqual(manifest["inputs"][name]["sha256"], file_sha256(source))
        verified = subprocess.run(
            [
                sys.executable,
                "-m",
                "common.contracts.verify_run_manifest",
                str(run_dir / "run_manifest.json"),
                "--require-status",
                "success",
                "--require-local-run-config",
                "--require-run-id",
                run_id,
                "--require-project",
                "single_reflection_oa_tof_mass_analyzer",
                "--require-mode",
                "three_zone_t5_simion_candidate_compile",
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        with self.assertRaises(FileExistsError):
            publish_t5_simion_candidate(
                self.campaign_path,
                self.receipt_path,
                run_dir,
                workspace_root=self.root,
            )

    def test_publish_rejects_noncanonical_or_invalid_run_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical workspace artifact root"):
            publish_t5_simion_candidate(
                self.campaign_path,
                self.receipt_path,
                self.root / "20260817_170000__build__python__three-zone-t5-candidate",
                workspace_root=self.root,
            )
        invalid_run = (
            self.root
            / "artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/not-a-run"
        )
        with self.assertRaisesRegex(ValueError, "run_id"):
            publish_t5_simion_candidate(
                self.campaign_path,
                self.receipt_path,
                invalid_run,
                workspace_root=self.root,
            )
        self.assertFalse(invalid_run.exists())


if __name__ == "__main__":
    unittest.main()
