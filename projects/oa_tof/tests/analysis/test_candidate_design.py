from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
sys.path.insert(0, str(REPO_ROOT / "common" / "contracts"))

from compile_candidate_design import EnvelopeReviewRequired, compile_proposal, write_candidate
from machine_contracts import load_json, sha256
from prepare_candidate_consumers import prepare, verify_routing_coverage
from prepare_candidate_run import prepare_candidate_run, validate_workflow
from candidate_run_lifecycle import finalize_candidate_run, start_candidate_run
from verify_artifact_layout import verify_project


class CandidateDesignTests(unittest.TestCase):
    def base_request(self):
        request = load_json(REPO_ROOT / "common" / "contracts" / "examples" / "oa_tof_500da_r30000.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        return request

    def compile(self, request, values, write=False):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            request_path = root_path / "request.json"
            proposal_path = root_path / "proposal.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            proposal = {
                "schema_version": 1,
                "role": "design_candidate_proposal",
                "candidate_id": "test_candidate",
                "project_id": "oa_tof",
                "request": {"path": str(request_path), "sha256": sha256(request_path)},
                "values": values,
            }
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            if not write:
                return compile_proposal(proposal_path)
            output = root_path / "candidate"
            paths = write_candidate(proposal_path, output)
            return [load_json(path) for path in paths]

    def test_zero_change_reproduces_formal_baseline_and_resolved_physics(self):
        request = self.base_request()
        request["constraints"] = []
        candidate, report, _ = self.compile(request, [])
        self.assertEqual(candidate, load_json(PROJECT_ROOT / "config" / "baseline.json"))
        self.assertTrue(report["zero_change_reference_reproduction"])
        baseline_out, resolved_out, report_out = self.compile(request, [], write=True)
        formal_resolved = load_json(PROJECT_ROOT / "config" / "resolved_geometry.json")
        self.assertEqual(resolved_out["geometry_mm"], formal_resolved["geometry_mm"])
        self.assertEqual(resolved_out["electrodes_V"], formal_resolved["electrodes_V"])
        self.assertTrue(report_out["zero_change_reference_reproduction"])

    def test_flight_compaction_requires_internal_reoptimization(self):
        request = self.base_request()
        request["design_variables"] = ["flight_length"]
        with self.assertRaisesRegex(ValueError, "stage-2 rings overlap"):
            self.compile(request, [{"variable": "flight_length", "value": 300.0, "unit": "mm"}])

        request["design_variables"] = ["flight_length", "reflectron_ring_thickness"]
        candidate, report, _ = self.compile(
            request,
            [
                {"variable": "flight_length", "value": 300.0, "unit": "mm"},
                {"variable": "reflectron_ring_thickness", "value": 2.5, "unit": "mm"},
            ],
        )
        self.assertEqual(candidate["geometry_mm"]["L_flight"], 300.0)
        self.assertLess(candidate["geometry_mm"]["shield_outer_z_max"], 871.8328)
        self.assertTrue(any(item["variable"] == "flight_length" for item in report["changed_variables"]))

    def test_accelerator_variable_can_grow_bidirectionally(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["accelerator_ring_width"]
        candidate, _, _ = self.compile(
            request, [{"variable": "accelerator_ring_width", "value": 6.0, "unit": "mm"}]
        )
        self.assertEqual(candidate["geometry_mm"]["accelerator_ring_width"], 6.0)

    def test_accelerator_length_and_voltage_rederive_focus_without_tof_envelope_block(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["accelerator_stage2_length", "accelerator_grid1_voltage"]
        with self.assertRaisesRegex(ValueError, "time focus"):
            self.compile(
                request,
                [
                    {"variable": "accelerator_stage2_length", "value": 20.0, "unit": "mm"},
                    {"variable": "accelerator_grid1_voltage", "value": 1700.0, "unit": "V"},
                ],
            )
        candidate, resolved, _ = self.compile(
            request,
            [
                {"variable": "accelerator_stage2_length", "value": 20.0, "unit": "mm"},
                {"variable": "accelerator_grid1_voltage", "value": 1900.0, "unit": "V"},
            ],
            write=True,
        )
        geometry = candidate["geometry_mm"]
        accelerator = candidate["geometry_derivation"]["accelerator"]
        self.assertEqual(geometry["L_accel"], 23.0)
        self.assertAlmostEqual(
            geometry["accelerator_grid2_z"] + accelerator["focus_drift_after_grid2_mm"],
            geometry["accelerator_focus_z"],
        )
        self.assertEqual(resolved["geometry_mm"], geometry)

    def test_noninteger_electrode_count_is_rejected(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["reflectron_stage1_electrode_count"]
        with self.assertRaisesRegex(ValueError, "integer"):
            self.compile(request, [{"variable": "reflectron_stage1_electrode_count", "value": 7.5, "unit": "count"}])

    def test_invalid_radial_order_is_rejected(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["reflectron_bore_radius"]
        with self.assertRaisesRegex(ValueError, "radial order"):
            self.compile(request, [{"variable": "reflectron_bore_radius", "value": 320.0, "unit": "mm"}])

    def test_larger_tof_requests_envelope_review_instead_of_being_impossible(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["flight_length"]
        with self.assertRaisesRegex(EnvelopeReviewRequired, "NEEDS_ENVELOPE_REVIEW"):
            self.compile(request, [{"variable": "flight_length", "value": 700.0, "unit": "mm"}])

    def test_zero_change_candidate_generates_formal_equivalent_simion_text(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "prepared"
            plan = prepare(PROJECT_ROOT / "config" / "resolved_geometry.json", output)
            formal = PROJECT_ROOT / "simion" / "workbench" / "formal"
            self.assertEqual(
                (output / "simion" / "oatof_resolved.lua").read_text(encoding="utf-8"),
                (formal / "oatof_resolved.lua").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (output / "simion" / "oatof_ideal_grounded.lua").read_text(encoding="utf-8"),
                (formal / "oatof_ideal_grounded.lua").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (output / "simion" / "oatof_ideal_grounded.fly2").read_text(encoding="utf-8"),
                (formal / "oatof_ideal_grounded.fly2").read_text(encoding="utf-8"),
            )
            self.assertEqual(plan["status"], "STATIC_INPUTS_READY")
            self.assertEqual(plan["consumers"]["comsol"]["runtime_status"], "not_run")
            self.assertEqual(
                plan["consumers"]["cad"]["arguments"]["modelPath"],
                plan["consumers"]["comsol"]["arguments"]["OutputModelPath"],
            )

    def test_nonzero_candidate_routes_one_contract_to_all_consumers(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            candidate = load_json(PROJECT_ROOT / "config" / "resolved_geometry.json")
            candidate["geometry_mm"]["accelerator_ring_width"] = 6.0
            contract_path = root_path / "candidate_resolved_geometry.json"
            contract_path.write_text(json.dumps(candidate), encoding="utf-8")
            plan = prepare(contract_path, root_path / "prepared")
            program = Path(plan["consumers"]["simion"]["generated"]["program"]["path"])
            self.assertIn("adjustable accelerator_ring_width_mm=6.0", program.read_text(encoding="utf-8"))
            self.assertEqual(plan["candidate_contract"]["path"], str(contract_path.resolve()))
            self.assertEqual(
                plan["consumers"]["comsol"]["arguments"]["ContractPath"], str(contract_path.resolve())
            )

    def test_missing_consumer_route_is_rejected(self):
        consumer_contract = load_json(PROJECT_ROOT / "config" / "candidate_consumers.json")
        variable_catalog = load_json(PROJECT_ROOT / "config" / "design_variables.json")
        del consumer_contract["consumers"]["cad"]
        with self.assertRaisesRegex(ValueError, "candidate consumer routing is incomplete"):
            verify_routing_coverage(consumer_contract, variable_catalog)

    def candidate_run_inputs(self, root_path):
        baseline = root_path / "candidate_baseline.json"
        resolved = root_path / "candidate_resolved_geometry.json"
        diff = root_path / "candidate_diff.json"
        baseline.write_text((PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8"), encoding="utf-8")
        resolved_contract = load_json(PROJECT_ROOT / "config" / "resolved_geometry.json")
        resolved_contract["inputs"]["baseline"] = str(baseline.resolve())
        resolved_contract["inputs"]["baseline_sha256"] = sha256(baseline)
        resolved.write_text(json.dumps(resolved_contract), encoding="utf-8")
        diff.write_text(json.dumps({"role": "oa_tof_candidate_contract_diff", "changed_variables": []}), encoding="utf-8")
        return baseline, resolved, diff

    def test_candidate_run_is_isolated_and_never_contains_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            run_id = "20260720_120000__build__cross__design-candidate__zero-change"
            plan = prepare_candidate_run(*inputs, run_id, artifact_root)
            run_root = artifact_root / "runs" / run_id
            planning_root = Path(plan["planning_root"])
            self.assertEqual(Path(plan["run_root"]), run_root)
            self.assertFalse(run_root.exists())
            planning_root.relative_to(artifact_root / "scratch")
            self.assertFalse(plan["formal_root"]["mutation_allowed"])
            self.assertFalse(plan["promotion"]["included"])
            self.assertFalse(plan["promotion"]["automatic"])
            self.assertFalse(plan["promotion"]["safe_to_promote"])
            for stage in plan["stages"]:
                for key in ("model_path", "output_dir", "report_path"):
                    if key in stage:
                        Path(stage[key]).resolve().relative_to(run_root.resolve())
            self.assertTrue((planning_root / "run_config.template.json").is_file())
            self.assertTrue((planning_root / "candidate_workflow_plan.json").is_file())
            with self.assertRaisesRegex(FileExistsError, "overwrite is forbidden"):
                prepare_candidate_run(*inputs, run_id, artifact_root)

    def test_candidate_inputs_cannot_come_from_formal_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root = Path(root) / "artifacts" / "projects" / "oa_tof"
            formal = artifact_root / "formal" / "inputs"
            formal.mkdir(parents=True)
            inputs = self.candidate_run_inputs(formal)
            with self.assertRaisesRegex(ValueError, "must not be sourced from formal"):
                prepare_candidate_run(
                    *inputs, "20260720_120001__build__cross__design-candidate__formal-source", artifact_root
                )

    def test_workflow_rejects_automatic_promotion(self):
        workflow = load_json(PROJECT_ROOT / "config" / "candidate_workflow.json")
        workflow["formal_policy"]["automatic_promotion"] = True
        with self.assertRaisesRegex(ValueError, "disable automatic promotion"):
            validate_workflow(workflow)

    def test_candidate_baseline_and_resolved_hashes_must_match(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            inputs[0].write_text(inputs[0].read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hashes do not match"):
                prepare_candidate_run(
                    *inputs, "20260720_120002__build__cross__design-candidate__hash-mismatch",
                    root_path / "artifacts" / "projects" / "oa_tof",
                )

    def materialize_candidate_run(self, root_path, stamp="20260720_130000"):
        artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
        artifact_root.mkdir(parents=True)
        (artifact_root / "00_README.txt").write_text("test artifact root", encoding="utf-8")
        source = root_path / "source"
        source.mkdir()
        inputs = self.candidate_run_inputs(source)
        run_id = f"{stamp}__build__cross__design-candidate__lifecycle"
        plan = prepare_candidate_run(*inputs, run_id, artifact_root)
        run_root = start_candidate_run(Path(plan["planning_root"]) / "candidate_workflow_plan.json")
        return artifact_root, run_root, plan

    def stage_results(self, plan, terminal_status="success", terminal_stage=None):
        results = []
        failed_seen = False
        for stage in plan["stages"]:
            stage_id = stage["stage_id"]
            if stage_id == terminal_stage:
                results.append({"stage_id": stage_id, "status": terminal_status})
                failed_seen = True
            elif failed_seen:
                results.append({"stage_id": stage_id, "status": "blocked"})
            else:
                results.append({"stage_id": stage_id, "status": "success"})
        return results

    def test_materialized_run_is_always_layout_complete_and_success_is_not_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, run_root, plan = self.materialize_candidate_run(Path(root))
            initial = load_json(run_root / "summary.json")
            self.assertEqual(initial["status"], "interrupted")
            self.assertEqual(verify_project(artifact_root), (1, 0))
            summary, manifest = finalize_candidate_run(run_root, "success", self.stage_results(plan))
            self.assertEqual(summary["candidate_decision"], "candidate_accepted_not_promoted")
            self.assertFalse(summary["formal_modified"])
            self.assertFalse(summary["safe_to_promote"])
            self.assertFalse(manifest["formal_eligible"])
            self.assertEqual(verify_project(artifact_root), (1, 0))

    def test_failed_and_interrupted_runs_close_with_complete_root_records(self):
        cases = (("failed", "comsol_candidate", "20260720_130001"),
                 ("interrupted", "simion_candidate", "20260720_130002"))
        for status, failure_stage, stamp in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as root:
                artifact_root, run_root, plan = self.materialize_candidate_run(Path(root), stamp)
                stage_status = "failed" if status == "failed" else "interrupted"
                summary, manifest = finalize_candidate_run(
                    run_root, status, self.stage_results(plan, stage_status, failure_stage), failure_stage
                )
                self.assertEqual(summary["status"], status)
                self.assertEqual(manifest["status"], status)
                self.assertTrue((run_root / "run_config.json").is_file())
                self.assertTrue((run_root / "summary.json").is_file())
                self.assertTrue((run_root / "run_manifest.json").is_file())
                self.assertEqual(verify_project(artifact_root), (1, 0))

    def test_planned_inputs_cannot_change_before_atomic_run_start(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            source = root_path / "source"
            source.mkdir()
            inputs = self.candidate_run_inputs(source)
            plan = prepare_candidate_run(
                *inputs, "20260720_130003__build__cross__design-candidate__tamper", artifact_root
            )
            planning_root = Path(plan["planning_root"])
            frozen_baseline = planning_root / "inputs" / "candidate_baseline.json"
            frozen_baseline.write_text(frozen_baseline.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed before run start"):
                start_candidate_run(planning_root / "candidate_workflow_plan.json")
            self.assertFalse(Path(plan["run_root"]).exists())


if __name__ == "__main__":
    unittest.main()
