from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.machine_contracts import load_json, sha256
from common.contracts.verify_artifact_layout import verify_project
from projects.oa_tof.analysis.candidate_run_lifecycle import finalize_candidate_run, start_candidate_run
from projects.oa_tof.analysis.candidate_source_closure import (
    PYTHON_BOUND_SOURCES,
    RELATIVE_PATHS,
    verify_candidate_source_closure,
)
from projects.oa_tof.analysis.compile_candidate_design import EnvelopeReviewRequired, compile_proposal, write_candidate
from projects.oa_tof.workflows.design_candidate.prepare_candidate_consumers import prepare, verify_routing_coverage
from projects.oa_tof.analysis.prepare_candidate_run import (
    _registered_candidate_template,
    prepare_candidate_run,
    validate_workflow,
)
from projects.oa_tof.analysis.prepare_formal_promotion import prepare as prepare_promotion
from projects.oa_tof.workflows.design_candidate.run_bound_candidate_workflow import validate_bound_candidate
from projects.oa_tof.workflows.design_candidate.run_candidate_workflow import (
    CandidateWorkflowError,
    CandidateWorkflowInterrupted,
    CandidateWorkflowTimedOut,
    StageTimedOut,
    _powershell,
    execute_stage,
    run_candidate_workflow,
)


class CandidateDesignTests(unittest.TestCase):
    def registered_template_run(self, artifact_root: Path, run_id: str = "20260726_120000__build__simion__candidate-layout-template") -> Path:
        run_root = artifact_root / "runs" / run_id
        source = artifact_root.parent / "user_created_layout"
        source.mkdir(parents=True)
        iob = source / "layout.iob"
        con = source / "layout.con"
        iob.write_bytes(b"user-created-iob")
        con.write_bytes(b"user-created-con")
        run_root.mkdir(parents=True)
        config = {
            "schema_version": 1,
            "role": "oa_tof_simion_candidate_layout_template_build",
            "run_id": run_id,
            "project": "oa_tof",
            "mode": "candidate_layout_template_build",
            "template_role": "oa_tof_candidate_simion_layout_template",
            "inputs": {"source_iob": str(iob), "source_con": str(con)},
            "input_sha256": {"source_iob": sha256(iob), "source_con": sha256(con)},
        }
        summary = {
            "role": "oa_tof_simion_candidate_layout_template_build_summary",
            "status": "success", "runtime_structure_verified": True,
            "particle_fly_executed": False, "formal_modified": False,
        }
        report = "INSTANCE_COUNT=4\nTEMPLATE_STRUCTURE_ONLY=true\nSTATUS=PASS\n"
        (run_root / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        (run_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (run_root / "simion_layout_runtime_report.txt").write_text(report, encoding="utf-8")
        manifest = {
            "status": "success", "run_id": run_id,
            "inputs": {
                key: {"path": value, "sha256": config["input_sha256"][key]}
                for key, value in config["inputs"].items()
            },
        }
        (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run_root

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

    def test_candidate_generates_nonformal_simion_text_from_frozen_contract(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "prepared"
            plan = prepare(PROJECT_ROOT / "config" / "resolved_geometry.json", output)
            resolved = (output / "simion" / "oatof_resolved.lua").read_text(encoding="utf-8")
            fly2 = (output / "simion" / "oatof_ideal_grounded.fly2").read_text(encoding="utf-8")
            self.assertIn(sha256(PROJECT_ROOT / "config" / "formal_solver_numerics.json"), resolved)
            self.assertIn("seed(20260713)", fly2)
            self.assertFalse((output / "simion" / "oatof_ideal_grounded.iob").exists())
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

    def test_comsol_explicit_contract_consumes_reflectron_voltage_overrides(self):
        source = (PROJECT_ROOT / "comsol" / "oatof_build_model_core.m").read_text(
            encoding="utf-8"
        )
        contract_branch = source.split("if ~isempty(contract_path)", 1)[1].split(
            "fprintf('[d1 scan]", 1
        )[0]
        self.assertIn("reflectron_midgrid_voltage_v = voltageV.midgrid", contract_branch)
        self.assertIn("reflectron_backplate_voltage_v = voltageV.backplate", contract_branch)
        self.assertIn("d2_mm = geometryMm.L_stage2", contract_branch)

    def test_solidworks_step_import_binds_clean_part_template_temporarily(self):
        source = (REPO_ROOT / "common" / "solidworks" / "import_step_to_solidworks.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("CLEAN_PART_TEMPLATE", source)
        self.assertIn("SW_DEFAULT_TEMPLATE_PART, str(CLEAN_PART_TEMPLATE)", source)
        self.assertIn("SW_ALWAYS_USE_DEFAULT_TEMPLATES, True", source)
        self.assertIn("SW_DEFAULT_TEMPLATE_PART, original_part_template", source)
        self.assertIn("original_always_use_default_templates", source)
        self.assertIn("step_paths = [path.resolve() for path in step_paths]", source)

    def test_missing_consumer_route_is_rejected(self):
        consumer_contract = load_json(PROJECT_ROOT / "config" / "candidate_consumers.json")
        variable_catalog = load_json(PROJECT_ROOT / "config" / "design_variables.json")
        del consumer_contract["consumers"]["cad"]
        with self.assertRaisesRegex(ValueError, "candidate consumer routing is incomplete"):
            verify_routing_coverage(consumer_contract, variable_catalog)

    def test_formal_promotion_requires_passing_candidate_acceptance(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            candidate = root_path / "candidate.mph"
            candidate.write_bytes(b"candidate")
            acceptance = root_path / "acceptance.json"
            acceptance.write_text(json.dumps({
                "role": "oa_tof_candidate_acceptance",
                "status": "failed",
                "formal_modified": False,
                "promotion_authorized": False,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pre-promotion"):
                prepare_promotion(
                    candidate, acceptance, root_path / "transaction.json",
                    root_path / "formal",
                )

    def test_formal_promotion_authorizes_only_exact_destinations(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            candidate = root_path / "candidate.mph"
            candidate.write_bytes(b"candidate")
            acceptance = root_path / "acceptance.json"
            acceptance.write_text(json.dumps({
                "role": "oa_tof_candidate_acceptance",
                "status": "success",
                "formal_modified": False,
                "promotion_authorized": False,
            }), encoding="utf-8")
            output = root_path / "transaction.json"
            transaction = prepare_promotion(
                candidate, acceptance, output, root_path / "formal",
            )
            self.assertEqual(transaction["status"], "authorized")
            self.assertEqual(
                transaction["destinations"]["comsol_model"],
                str((root_path / "formal" / "comsol" / "oa_tof__model.mph").resolve()),
            )
            self.assertEqual(
                transaction["destinations"]["cad_root"],
                str((root_path / "formal" / "cad").resolve()),
            )

    def candidate_run_inputs(self, root_path):
        baseline = root_path / "candidate_baseline.json"
        resolved = root_path / "candidate_resolved_geometry.json"
        numerics = root_path / "candidate_solver_numerics.json"
        diff = root_path / "candidate_diff.json"
        request = root_path / "design_request.json"
        proposal = root_path / "candidate_proposal.json"
        baseline.write_text((PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8"), encoding="utf-8")
        numerics.write_text((PROJECT_ROOT / "config" / "formal_solver_numerics.json").read_text(encoding="utf-8"), encoding="utf-8")
        resolved_contract = load_json(PROJECT_ROOT / "config" / "resolved_geometry.json")
        resolved_contract["inputs"]["baseline"] = str(baseline.resolve())
        resolved_contract["inputs"]["baseline_sha256"] = sha256(baseline)
        resolved_contract["inputs"]["solver_numerics"] = str(numerics.resolve())
        resolved_contract["inputs"]["solver_numerics_sha256"] = sha256(numerics)
        resolved.write_text(json.dumps(resolved_contract), encoding="utf-8")
        request_contract = self.base_request()
        request_contract["target"]["mode"] = "design_candidate"
        request_contract["operating_points"] = [{"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}]
        request_contract["objectives"] = [
            {"metric": "transmission_fraction", "operator": "maximize", "value": None,
             "unit": "1", "tolerance": None}
        ]
        request_contract["constraints"] = []
        request_contract["design_variables"] = []
        request.write_text(json.dumps(request_contract), encoding="utf-8")
        proposal_contract = {
            "schema_version": 1,
            "role": "design_candidate_proposal",
            "candidate_id": "test_candidate",
            "project_id": "oa_tof",
            "request": {"path": str(request.resolve()), "sha256": sha256(request)},
            "values": [],
        }
        proposal.write_text(json.dumps(proposal_contract), encoding="utf-8")
        diff.write_text(json.dumps({
            "role": "oa_tof_candidate_contract_diff",
            "candidate_id": "test_candidate",
            "request_id": request_contract["request_id"],
            "changed_variables": [],
            "provenance": {
                "proposal": {"path": str(proposal.resolve()), "sha256": sha256(proposal)},
                "request": {"path": str(request.resolve()), "sha256": sha256(request)},
            },
        }), encoding="utf-8")
        return baseline, resolved, diff

    def test_candidate_run_is_isolated_and_never_contains_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            run_id = "20260720_120000__build__cross__design-candidate__zero-change"
            plan = prepare_candidate_run(*inputs, run_id, artifact_root)
            expected_run_root = artifact_root / "runs" / run_id
            run_root = Path(plan["run_root"])
            planning_root = Path(plan["planning_root"])
            # GitHub Windows runners may expose the same temporary directory
            # through long and 8.3 path aliases.  Compare the existing project
            # root by file identity, then verify the not-yet-created suffix.
            self.assertTrue(run_root.parents[1].samefile(artifact_root))
            self.assertEqual(run_root.parent.name, "runs")
            self.assertEqual(run_root.name, run_id)
            self.assertFalse(expected_run_root.exists())
            self.assertTrue(planning_root.parents[1].samefile(artifact_root))
            self.assertEqual(planning_root.parent.name, "scratch")
            self.assertFalse(plan["formal_root"]["mutation_allowed"])
            self.assertFalse(plan["promotion"]["included"])
            self.assertFalse(plan["promotion"]["automatic"])
            self.assertFalse(plan["promotion"]["safe_to_promote"])
            for stage in plan["stages"]:
                for key in ("model_path", "output_dir", "report_path"):
                    if key in stage:
                        Path(stage[key]).resolve().relative_to(run_root.resolve())
            comsol_stage = next(stage for stage in plan["stages"] if stage["stage_id"] == "comsol_candidate")
            self.assertEqual(Path(comsol_stage["environment"]["OATOF_RUNTIME_DIR"]), run_root / "comsol")
            self.assertEqual(
                set(plan["candidate_inputs"]),
                {"candidate_baseline.json", "candidate_resolved_geometry.json", "candidate_solver_numerics.json", "candidate_diff.json",
                 "candidate_proposal.json", "design_request.json"},
            )
            self.assertTrue((planning_root / "run_config.template.json").is_file())
            self.assertTrue((planning_root / "candidate_workflow_plan.json").is_file())
            closure = plan["execution_source_closure"]
            verify_candidate_source_closure(closure)
            source_ids = {item["source_id"] for item in closure["sources"]}
            self.assertEqual(source_ids, set(RELATIVE_PATHS))
            self.assertIn("common/require_powershell7.ps1", source_ids)
            self.assertIn("projects/oa_tof/oatof_lifecycle_preflight.ps1", source_ids)
            self.assertIn("projects/oa_tof/simion/workbench/build_formal_iob.lua", source_ids)
            code_root = Path(closure["code_root"]).resolve()
            for stage in plan["stages"]:
                for key in ("entrypoint", "task_script"):
                    if key in stage:
                        Path(stage[key]).resolve().relative_to(code_root)
            transformed = {
                item["source_id"]
                for item in closure["sources"]
                if "python_runtime_binding" in item["transformations"]
            }
            self.assertEqual(transformed, PYTHON_BOUND_SOURCES)
            live_root = str(REPO_ROOT.resolve()).encode()
            runtime_path = closure["runtime"]["python_executable"].encode()
            for item in closure["sources"]:
                frozen_path = code_root / item["source_id"]
                payload = frozen_path.read_bytes().replace(
                    runtime_path, b"<FROZEN_PYTHON_RUNTIME>"
                )
                self.assertNotIn(live_root, payload)
            with self.assertRaisesRegex(FileExistsError, "overwrite is forbidden"):
                prepare_candidate_run(*inputs, run_id, artifact_root)

    def test_candidate_template_requires_successful_registered_template_build_run(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            registration = self.registered_template_run(artifact_root)
            record = _registered_candidate_template(registration, artifact_root)
            self.assertEqual(record["source_iob"].name, "layout.iob")
            failed = load_json(registration / "summary.json")
            failed["status"] = "failed"
            (registration / "summary.json").write_text(json.dumps(failed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a successful structure-only"):
                _registered_candidate_template(registration, artifact_root)

    def test_candidate_template_accepts_equivalent_noncanonical_manifest_path(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            registration = self.registered_template_run(artifact_root)
            manifest_path = registration / "run_manifest.json"
            manifest = load_json(manifest_path)
            source_iob = Path(manifest["inputs"]["source_iob"]["path"])
            spelling_anchor = source_iob.parent / "equivalent_spelling"
            spelling_anchor.mkdir()
            manifest["inputs"]["source_iob"]["path"] = str(
                spelling_anchor / ".." / source_iob.name
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            record = _registered_candidate_template(registration, artifact_root)
            self.assertEqual(record["source_iob"], source_iob.resolve())

    def test_candidate_template_reports_manifest_hash_mismatch_by_field(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            registration = self.registered_template_run(artifact_root)
            manifest_path = registration / "run_manifest.json"
            manifest = load_json(manifest_path)
            manifest["inputs"]["source_iob"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest SHA-256 differs: source_iob"):
                _registered_candidate_template(registration, artifact_root)

    def test_candidate_prepare_freezes_only_registered_template_sources(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            registration = self.registered_template_run(artifact_root)
            candidate_inputs = root_path / "candidate_inputs"
            candidate_inputs.mkdir()
            inputs = self.candidate_run_inputs(candidate_inputs)
            plan = prepare_candidate_run(
                *inputs,
                "20260726_121000__build__cross__design-candidate__zero-change",
                artifact_root,
                simion_template_run=registration,
            )
            stage = next(item for item in plan["stages"] if item["stage_id"] == "simion_candidate")
            self.assertEqual(stage["status"], "ready")
            self.assertEqual(stage["template_input"]["role"], "oa_tof_candidate_simion_layout_template")
            self.assertTrue(Path(stage["template_input"]["files"]["iob"]["path"]).is_file())
            self.assertTrue(Path(stage["template_input"]["files"]["con"]["path"]).is_file())

    def test_template_registration_is_structure_only_and_rejects_prohibited_sources(self):
        script = (PROJECT_ROOT / "simion" / "workbench" / "register_candidate_layout_template.ps1").read_text(encoding="utf-8")
        for token in (
            "SourceIobPath", "SourceConPath", "oa_tof_simion_candidate_layout_template_build",
            "-TemplateStructureOnly", "formal', 'archive', 'history", "particle_fly_executed = $false",
        ):
            self.assertIn(token, script)
        self.assertNotIn("Copy-Item", script)
        self.assertNotIn(" --nogui fly", script)

    def test_legacy_placeholder_layout_source_is_nonphysical_and_has_fixed_slot_order(self):
        gem = (PROJECT_ROOT / "simion" / "workbench" / "candidate_layout_placeholder.gem").read_text(encoding="utf-8")
        builder = (PROJECT_ROOT / "simion" / "workbench" / "build_candidate_layout_placeholders.ps1").read_text(encoding="utf-8")
        self.assertIn("Non-physical PA", gem)
        self.assertNotIn("2240", gem)
        self.assertNotIn("524", gem)
        self.assertIn("flight_tube_ground.pa0', 'reflectron.pa0', 'accelerator.pa0', 'detector_ground.pa0", builder)
        self.assertIn("physical_model = $false", builder)
        self.assertIn("build_candidate_layout_placeholders.lua", builder)

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
            self.assertEqual(
                set(manifest["inputs"]),
                {"candidate_baseline.json", "candidate_resolved_geometry.json", "candidate_solver_numerics.json", "candidate_diff.json",
                 "candidate_proposal.json", "design_request.json"},
            )
            self.assertEqual(verify_project(artifact_root), (1, 0))

    def test_candidate_proposal_and_request_cannot_change_before_planning(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            proposal = root_path / "candidate_proposal.json"
            proposal.write_text(proposal.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "proposal provenance is missing or changed"):
                prepare_candidate_run(
                    *inputs, "20260720_130005__build__cross__design-candidate__provenance-tamper",
                    root_path / "artifacts" / "projects" / "oa_tof",
                )

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

    def test_prepared_solver_text_cannot_change_before_atomic_run_start(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            source = root_path / "source"
            source.mkdir()
            inputs = self.candidate_run_inputs(source)
            plan = prepare_candidate_run(
                *inputs, "20260720_130004__build__cross__design-candidate__text-tamper", artifact_root
            )
            planning_root = Path(plan["planning_root"])
            program = planning_root / "inputs" / "prepared_consumers" / "simion" / "oatof_ideal_grounded.lua"
            program.write_text(program.read_text(encoding="utf-8") + "-- changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SIMION candidate text changed"):
                start_candidate_run(planning_root / "candidate_workflow_plan.json")
            self.assertFalse(Path(plan["run_root"]).exists())

    def test_frozen_candidate_source_tamper_blocks_start_and_extra_files(self):
        cases = ("modified", "extra")
        for index, case in enumerate(cases):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as root:
                root_path = Path(root)
                artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
                source = root_path / "source"
                source.mkdir()
                plan = prepare_candidate_run(
                    *self.candidate_run_inputs(source),
                    f"20260720_13001{index}__build__cross__design-candidate__source-{case}",
                    artifact_root,
                )
                planning_root = Path(plan["planning_root"])
                code_root = Path(plan["execution_source_closure"]["code_root"])
                if case == "modified":
                    target = code_root / "common" / "require_powershell7.ps1"
                    target.write_text(
                        target.read_text(encoding="utf-8") + "\n# tampered\n",
                        encoding="utf-8",
                    )
                else:
                    (code_root / "undeclared.py").write_text(
                        "raise RuntimeError('undeclared')\n", encoding="utf-8"
                    )
                with self.assertRaisesRegex(
                    ValueError, "frozen candidate source changed|missing or extra"
                ):
                    start_candidate_run(
                        planning_root / "candidate_workflow_plan.json"
                    )
                self.assertFalse(Path(plan["run_root"]).exists())

    def test_frozen_candidate_source_tamper_blocks_stage_and_finalize(self):
        with tempfile.TemporaryDirectory() as root:
            _, run_root, plan = self.materialize_candidate_run(Path(root))
            runtime_plan = load_json(run_root / "candidate_workflow_plan.json")
            code_root = Path(
                runtime_plan["execution_source_closure"]["code_root"]
            )
            target = code_root / "common" / "require_powershell7.ps1"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n# tampered\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "frozen candidate source changed"
            ):
                execute_stage(runtime_plan["stages"][0], runtime_plan, "unused")
            with self.assertRaisesRegex(
                ValueError, "frozen candidate source changed"
            ):
                finalize_candidate_run(
                    run_root, "success", self.stage_results(plan)
                )

    def prepared_workflow_plan(self, root_path, stamp):
        artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
        artifact_root.mkdir(parents=True)
        (artifact_root / "00_README.txt").write_text("test artifact root", encoding="utf-8")
        source = root_path / "source"
        source.mkdir()
        inputs = self.candidate_run_inputs(source)
        plan = prepare_candidate_run(
            *inputs, f"{stamp}__build__cross__design-candidate__integrated", artifact_root
        )
        return artifact_root, Path(plan["planning_root"]) / "candidate_workflow_plan.json"

    def test_integrated_runner_success_closes_one_root_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.prepared_workflow_plan(Path(root), "20260720_140000")
            observed = []

            def fake_executor(stage, plan, _simion):
                observed.append(stage["stage_id"])
                evidence_path = Path(plan["run_root"]) / "results" / f"{stage['stage_id']}.txt"
                evidence_path.write_text("STATUS=PASS\n", encoding="utf-8")
                return {"report": str(evidence_path)}

            run_root, summary = run_candidate_workflow(plan_path, stage_executor=fake_executor)
            expected = ["static_inputs", "comsol_candidate", "simion_candidate", "cad_candidate", "cross_solver_acceptance"]
            self.assertEqual(observed, expected)
            self.assertEqual([item["stage_id"] for item in summary["stages"]], expected)
            self.assertEqual(summary["acceptance_scope"], "structural_build_and_contract")
            self.assertFalse(summary["performance_claim_allowed"])
            self.assertEqual(verify_project(artifact_root), (1, 0))
            self.assertEqual(load_json(run_root / "run_manifest.json")["status"], "success")

    def test_integrated_runner_terminal_faults_close_remaining_stages(self):
        cases = (("failed", "simion_candidate", CandidateWorkflowError, "20260720_140001"),
                 ("interrupted", "cad_candidate", CandidateWorkflowInterrupted, "20260720_140002"),
                 ("timeout", "comsol_candidate", CandidateWorkflowTimedOut, "20260720_140003"))
        for outcome, stop_stage, exception_type, stamp in cases:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as root:
                artifact_root, plan_path = self.prepared_workflow_plan(Path(root), stamp)

                def fake_executor(stage, _plan, _simion):
                    if stage["stage_id"] == stop_stage:
                        if outcome == "interrupted":
                            raise KeyboardInterrupt("test interruption")
                        if outcome == "timeout":
                            raise StageTimedOut("test timeout")
                        raise RuntimeError("test failure")
                    return {"stage": stage["stage_id"]}

                with self.assertRaises(exception_type) as caught:
                    run_candidate_workflow(plan_path, stage_executor=fake_executor)
                run_root = caught.exception.run_root
                summary = load_json(run_root / "summary.json")
                self.assertEqual(summary["status"], outcome)
                self.assertEqual(summary["failure_stage"], stop_stage)
                statuses = {item["stage_id"]: item["status"] for item in summary["stages"]}
                self.assertEqual(statuses[stop_stage], outcome)
                later = False
                for item in summary["stages"]:
                    if later:
                        self.assertEqual(item["status"], "blocked")
                    later = later or item["stage_id"] == stop_stage
                self.assertEqual(verify_project(artifact_root), (1, 0))

    def test_cross_acceptance_requires_identical_candidate_particle_tables(self):
        with tempfile.TemporaryDirectory() as root:
            run_root = Path(root)
            files = {}
            for name in (
                "particle_table", "model", "sync_report", "iob", "ion_n100", "stage_summary",
                "runtime_report", "transport_diagnostics", "cad_report",
            ):
                path = run_root / f"{name}.dat"
                content = "\n".join(["same particle table"] * 100) if name in ("particle_table", "ion_n100") else "evidence"
                path.write_text(content, encoding="utf-8")
                files[name] = str(path)
            particle_csv = run_root / "simion_particles.csv"
            particle_csv.write_text("Ion\n" + "\n".join(str(index) for index in range(1, 101)) + "\n", encoding="utf-8")
            transport_summary = run_root / "simion_transport_summary.json"
            transport_summary.write_text(json.dumps({
                "status": "success", "expected_particle_count": 100, "trajectory_quality": 8,
                "emitted": 100, "crossed": 100, "hit": 100,
                "ion": {"sha256": sha256(Path(files["ion_n100"]))},
                "particle_csv": {"sha256": sha256(particle_csv)},
            }), encoding="utf-8")
            files["particle_csv"] = str(particle_csv)
            files["transport_summary"] = str(transport_summary)
            plan = {
                "run_root": str(run_root),
                "stage_results_so_far": [
                    {"stage_id": "static_inputs", "evidence": {"particle_table": files["particle_table"]}},
                    {"stage_id": "comsol_candidate", "evidence": {"model": files["model"], "sync_report": files["sync_report"]}},
                    {"stage_id": "simion_candidate", "evidence": {
                        "iob": files["iob"], "ion_n100": files["ion_n100"], "stage_summary": files["stage_summary"],
                        "runtime_report": files["runtime_report"], "transport_summary": files["transport_summary"],
                        "particle_csv": files["particle_csv"], "transport_diagnostics": files["transport_diagnostics"],
                    }},
                    {"stage_id": "cad_candidate", "evidence": {"cad_report": files["cad_report"]}},
                ],
            }
            stage = {
                "stage_id": "cross_solver_acceptance", "output_dir": str(run_root / "results"),
                "acceptance_scope": "structural_build_and_contract", "performance_claim_allowed": False,
            }
            evidence = execute_stage(stage, plan, "unused")
            acceptance = load_json(Path(evidence["acceptance"]))
            self.assertEqual(acceptance["scope"], "structural_build_and_contract")
            self.assertTrue(acceptance["shared_particle_table_sha256"])
            self.assertEqual(acceptance["comsol_simion_particle_level_comparison"], "not_run")
            particle_csv.write_text("Ion\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "transport evidence is incomplete or changed"):
                execute_stage(stage, plan, "unused")
            particle_csv.write_text(
                "Ion\n" + "\n".join(str(index) for index in range(1, 101)) + "\n", encoding="utf-8"
            )
            Path(files["ion_n100"]).write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "particle tables differ"):
                execute_stage(stage, plan, "unused")

    def test_candidate_source_closure_freezes_shared_n100_transport_mechanism(self):
        required = {
            "common/comsol/add_comsol_size_feature.m",
            "projects/oa_tof/simion/workbench/run_n100_transport.ps1",
            "projects/oa_tof/simion/workbench/analyze_ideal_field_log.ps1",
            "projects/oa_tof/analysis/solver_diagnostics.py",
        }
        self.assertTrue(required.issubset(set(RELATIVE_PATHS)))
        self.assertIn("projects/oa_tof/simion/workbench/analyze_ideal_field_log.ps1", PYTHON_BOUND_SOURCES)

    def test_source_build_runner_reuses_shared_transport_helper(self):
        runner = (PROJECT_ROOT / "tests" / "simion" / "run_n100_source_build_and_track.ps1").read_text(encoding="utf-8")
        self.assertIn("run_n100_transport.ps1", runner)
        self.assertNotIn("'--nogui', 'fly'", runner)

    def test_simion_candidate_requires_explicit_nonformal_frozen_template_before_builder(self):
        with tempfile.TemporaryDirectory() as root:
            run_root = Path(root)
            stage = {"stage_id": "simion_candidate", "status": "blocked_requires_explicit_nonformal_template"}
            with mock.patch("projects.oa_tof.workflows.design_candidate.run_candidate_workflow._run_command") as command:
                with self.assertRaisesRegex(RuntimeError, "blocked until an explicit non-Formal template"):
                    execute_stage(stage, {"run_root": str(run_root), "execution_source_closure": {}}, "unused")
            command.assert_not_called()

            formal = run_root / "inputs" / "formal" / "layout.iob"
            formal.parent.mkdir(parents=True)
            formal.write_bytes(b"template")
            stage["status"] = "ready"
            stage["template_input"] = {
                "role": "oa_tof_candidate_simion_layout_template",
                "files": {
                    "iob": {"path": str(formal), "sha256": sha256(formal)},
                    "con": {"path": str(formal.with_suffix('.con')), "sha256": "missing"},
                },
            }
            with self.assertRaisesRegex(RuntimeError, "must not reference a Formal path"):
                execute_stage(stage, {"run_root": str(run_root)}, "unused")

            template = run_root / "inputs" / "simion_template" / "layout.iob"
            template.parent.mkdir(parents=True)
            template.write_bytes(b"template")
            template.with_suffix(".con").write_bytes(b"template-con")
            stage["template_input"] = {
                "role": "oa_tof_candidate_simion_layout_template",
                "files": {
                    "iob": {"path": str(template), "sha256": sha256(template)},
                    "con": {"path": str(template.with_suffix('.con')), "sha256": sha256(template.with_suffix('.con'))},
                },
            }
            with self.assertRaisesRegex(ValueError, "invalid candidate source closure"):
                execute_stage(stage, {"run_root": str(run_root), "execution_source_closure": {}}, "unused")

    def test_formal_asset_entrypoints_preflight_before_paths_or_runs(self):
        scripts = [
            PROJECT_ROOT / "workflows" / "formal_reference" / "run_formal_validation.ps1",
            PROJECT_ROOT / "workflows" / "formal_reference" / "verify_geometry_contract.ps1",
            PROJECT_ROOT / "workflows" / "formal_reference" / "run_coupled_baseline_validation.ps1",
            PROJECT_ROOT / "workflows" / "mass_spectrum_candidate" / "run_mass_spectrum_candidate.ps1",
            PROJECT_ROOT / "tests" / "simion" / "run_n100_source_build_and_track.ps1",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            preflight = text.index("Assert-OaTofFormalAssetsReadable")
            first_asset = min(index for index in (text.find("formal\\"), text.find("New-Item -ItemType Directory")) if index >= 0)
            self.assertLess(preflight, first_asset, script.name)

    def test_shared_builder_requires_explicit_seed_and_candidate_template(self):
        builder = (PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1").read_text(encoding="utf-8")
        self.assertIn("ParticleSeed is required", builder)
        self.assertIn("Candidate build requires an explicit frozen non-Formal TemplateIob", builder)
        self.assertIn("Candidate TemplateIob must not reference a Formal path", builder)

    def test_frozen_candidate_builder_receives_runtime_artifact_root(self):
        builder = (PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1").read_text(encoding="utf-8")
        self.assertIn("[string]$ArtifactProjectRoot = ''", builder)
        self.assertIn("$artifactRoot = [IO.Path]::GetFullPath($ArtifactProjectRoot)", builder)
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "oa_tof"
            artifact_root.mkdir(parents=True)
            template_run = self.registered_template_run(artifact_root)
            source = root_path / "candidate_inputs"
            source.mkdir()
            plan = prepare_candidate_run(
                *self.candidate_run_inputs(source),
                "20260727_110000__build__cross__design-candidate__frozen-builder-root",
                artifact_root,
                simion_template_run=template_run,
            )
            run_root = start_candidate_run(Path(plan["planning_root"]) / "candidate_workflow_plan.json")
            runtime_plan = load_json(run_root / "candidate_workflow_plan.json")
            stage = next(item for item in runtime_plan["stages"] if item["stage_id"] == "simion_candidate")
            commands = []

            def stop_after_capturing_command(command, _log_path, _environment=None):
                commands.append(command)
                raise RuntimeError("intentional command capture")

            with mock.patch(
                "projects.oa_tof.workflows.design_candidate.run_candidate_workflow._run_command",
                side_effect=stop_after_capturing_command,
            ):
                with self.assertRaisesRegex(RuntimeError, "intentional command capture"):
                    execute_stage(stage, runtime_plan, "unused")

            command = commands[0]
            frozen_builder = Path(command[5]).resolve()
            frozen_builder.relative_to(run_root / "inputs" / "code")
            root_argument = command.index("-ArtifactProjectRoot") + 1
            self.assertEqual(Path(command[root_argument]).resolve(), artifact_root.resolve())

    def test_shared_builder_negative_contracts_fail_before_output_creation(self):
        builder = PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            contract = root_path / "candidate.json"
            baseline = root_path / "candidate_baseline.json"
            text_dir = root_path / "candidate_text"
            contract.write_text("{}", encoding="utf-8")
            baseline.write_text("{}", encoding="utf-8")
            text_dir.mkdir()
            shared = ["-ContractPath", str(contract), "-CandidateBaselinePath", str(baseline), "-CandidateTextDir", str(text_dir)]
            nonformal_template = root_path / "candidate_template.iob"
            nonformal_template.write_bytes(b"template")
            cases = [
                (shared + ["-TemplateIob", str(nonformal_template)], "ParticleSeed is required"),
                (shared + ["-ParticleSeed", "7"], "Candidate build requires an explicit frozen non-Formal TemplateIob"),
                (shared + ["-ParticleSeed", "7", "-TemplateIob", str(root_path / "formal_template.iob")], "Candidate TemplateIob must not reference a Formal path"),
            ]
            for ordinal, (arguments, expected) in enumerate(cases):
                output = root_path / f"output_{ordinal}"
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-File", str(builder), "-OutputDir", str(output), *arguments],
                    cwd=REPO_ROOT, capture_output=True, timeout=20,
                )
                self.assertNotEqual(result.returncode, 0)
                text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
                self.assertIn(expected, text)
                self.assertFalse(output.exists())

    def test_integrated_runner_uses_powershell_7(self):
        command = _powershell("task.ps1", ["-Value", "test"])
        self.assertEqual(command[0], "pwsh.exe")
        self.assertEqual(command[-3:], ["task.ps1", "-Value", "test"])

    def test_comsol_stage_uses_only_frozen_launcher_and_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root, plan_path = self.prepared_workflow_plan(
                root_path, "20260720_145000"
            )
            plan = load_json(plan_path)
            stage = next(
                item
                for item in plan["stages"]
                if item["stage_id"] == "comsol_candidate"
            )
            observed = []

            def fake_run(command, _log_path, _environment=None):
                observed.append(command)
                report_index = command.index("-ReportPath") + 1
                report = Path(command[report_index])
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text("STATUS=PASS\n", encoding="utf-8")

            with mock.patch(
                "projects.oa_tof.workflows.design_candidate.run_candidate_workflow._run_command",
                side_effect=fake_run,
            ):
                execute_stage(stage, plan, "unused")

            code_root = Path(plan["execution_source_closure"]["code_root"])
            self.assertEqual(len(observed), 2)
            for command in observed:
                Path(command[5]).resolve().relative_to(code_root.resolve())
                task_index = command.index("-TaskScript") + 1
                Path(command[task_index]).resolve().relative_to(
                    code_root.resolve()
                )
            self.assertEqual(
                {Path(command[5]).resolve() for command in observed},
                {
                    (
                        code_root
                        / "common"
                        / "comsol"
                        / "run_comsol_r2025b.ps1"
                    ).resolve()
                },
            )
            self.assertTrue(artifact_root.is_dir())

    def test_bound_runner_requires_same_approved_request_and_run_id(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            _, candidate_plan_path = self.prepared_workflow_plan(root_path, "20260720_150000")
            candidate = load_json(candidate_plan_path)
            request_record = candidate["candidate_inputs"]["design_request.json"]
            request = load_json(Path(request_record["path"]))
            design = {
                "role": "solver_neutral_design_plan",
                "run_id": candidate["run_id"],
                "request_id": request["request_id"],
                "request_status": "approved",
                "project_id": "oa_tof",
                "mode": "design_candidate",
                "provenance": {"request": request_record},
            }
            design_path = root_path / "design_plan.json"
            design_path.write_text(json.dumps(design), encoding="utf-8")
            validate_bound_candidate(design_path, candidate_plan_path)
            design["run_id"] = "20260720_150001__build__cross__design-candidate__mismatch"
            design_path.write_text(json.dumps(design), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "run_id differ"):
                validate_bound_candidate(design_path, candidate_plan_path)

    def test_bound_runner_accepts_only_runtime_covered_requested_variable(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            _, candidate_plan_path = self.prepared_workflow_plan(root_path, "20260720_150010")
            candidate = load_json(candidate_plan_path)
            request_record = candidate["candidate_inputs"]["design_request.json"]
            request_path = Path(request_record["path"])
            request = load_json(request_path)
            request["design_variables"] = ["reflectron_midgrid_voltage"]
            request_path.write_text(json.dumps(request), encoding="utf-8")
            request_record["sha256"] = sha256(request_path)

            diff_record = candidate["candidate_inputs"]["candidate_diff.json"]
            diff_path = Path(diff_record["path"])
            diff = load_json(diff_path)
            diff["changed_variables"] = [{
                "variable": "reflectron_midgrid_voltage",
                "before": 1600.0,
                "after": 1601.0,
                "unit": "V",
                "change_origin": "proposed",
            }]
            diff_path.write_text(json.dumps(diff), encoding="utf-8")
            diff_record["sha256"] = sha256(diff_path)
            candidate_plan_path.write_text(json.dumps(candidate), encoding="utf-8")

            design = {
                "role": "solver_neutral_design_plan",
                "run_id": candidate["run_id"],
                "request_id": request["request_id"],
                "request_status": "approved",
                "project_id": "oa_tof",
                "mode": "design_candidate",
                "provenance": {"request": request_record},
            }
            design_path = root_path / "design_plan.json"
            design_path.write_text(json.dumps(design), encoding="utf-8")
            validate_bound_candidate(design_path, candidate_plan_path)

            diff["changed_variables"][0]["variable"] = "flight_length"
            diff_path.write_text(json.dumps(diff), encoding="utf-8")
            diff_record["sha256"] = sha256(diff_path)
            candidate_plan_path.write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "without runtime coverage"):
                validate_bound_candidate(design_path, candidate_plan_path)


if __name__ == "__main__":
    unittest.main()
