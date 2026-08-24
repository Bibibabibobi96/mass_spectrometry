from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.machine_contracts import load_json, sha256
from common.contracts.verify_artifact_layout import verify_project
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import finalize_candidate_run, start_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
    PYTHON_BOUND_SOURCES,
    RELATIVE_PATHS,
    verify_candidate_source_closure,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import EnvelopeReviewRequired, compile_proposal, write_candidate
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers import prepare, verify_routing_coverage
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import (
    _registered_candidate_template,
    prepare_candidate_run,
    validate_workflow,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_formal_promotion import prepare as prepare_promotion
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate as candidate_entry
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import (
    CandidateWorkflowError,
    CandidateWorkflowInterrupted,
    CandidateWorkflowTimedOut,
    StageTimedOut,
    _powershell,
    _run_command,
    _stage_source_paths,
    _verify_frozen_cad_python,
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
            "project": "single_reflection_oa_tof_mass_analyzer",
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

    def test_candidate_runtime_preflight_validates_registered_source_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = (
                root_path
                / "artifacts"
                / "projects"
                / "single_reflection_oa_tof_mass_analyzer"
            )
            registration = self.registered_template_run(artifact_root)
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                preflight = candidate_entry.validate_candidate_runtime(artifact_root)
                self.assertTrue(preflight["template"].samefile(registration))
                source_iob = Path(preflight["registration"]["source_iob"])
                source_iob.write_bytes(b"mutated-after-registration")
                with self.assertRaisesRegex(ValueError, "SHA-256 changed"):
                    candidate_entry.validate_candidate_runtime(artifact_root)

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
                "project_id": "single_reflection_oa_tof_mass_analyzer",
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

    def test_candidate_resolved_publication_is_independent_of_scratch_path(self):
        request = self.base_request()
        request["constraints"] = []
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            request_path = root_path / "design_request.json"
            proposal_path = root_path / "candidate_proposal.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            proposal_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "design_candidate_proposal",
                        "candidate_id": "stable_resolved_identity",
                        "project_id": "single_reflection_oa_tof_mass_analyzer",
                        "request": {
                            "path": str(request_path),
                            "sha256": sha256(request_path),
                        },
                        "values": [],
                    }
                ),
                encoding="utf-8",
            )
            first = write_candidate(proposal_path, root_path / "run_a" / "contracts")[1]
            second = write_candidate(proposal_path, root_path / "run_b" / "contracts")[1]
            self.assertEqual(first.read_bytes(), second.read_bytes())
            inputs = load_json(first)["inputs"]
            self.assertEqual(
                inputs["baseline"], "run_input:candidate_baseline.json"
            )
            self.assertEqual(
                inputs["solver_numerics"],
                "run_input:candidate_solver_numerics.json",
            )
            self.assertNotIn(str(root_path.resolve()), first.read_text(encoding="utf-8"))

    def test_flight_compaction_requires_internal_reoptimization(self):
        request = self.base_request()
        request["design_variables"] = ["flight_length"]
        with self.assertRaisesRegex(ValueError, "stage-2 ring gap"):
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

    def test_shared_shield_radius_contains_offset_detector(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = [
            "reflectron_bore_radius",
            "reflectron_ring_outer_radius",
            "reflectron_shield_inner_radius",
        ]
        with self.assertRaisesRegex(
            ValueError, "shared flight-tube/reflectron shield inner radius"
        ):
            self.compile(
                request,
                [
                    {"variable": "reflectron_bore_radius", "value": 25.0, "unit": "mm"},
                    {"variable": "reflectron_ring_outer_radius", "value": 60.0, "unit": "mm"},
                    {"variable": "reflectron_shield_inner_radius", "value": 88.0, "unit": "mm"},
                ],
            )

    def test_shared_shield_radius_accepts_exact_transverse_envelope(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = [
            "reflectron_bore_radius",
            "reflectron_ring_outer_radius",
            "reflectron_shield_inner_radius",
        ]
        candidate, _, _ = self.compile(
            request,
            [
                {"variable": "reflectron_bore_radius", "value": 25.0, "unit": "mm"},
                {"variable": "reflectron_ring_outer_radius", "value": 60.0, "unit": "mm"},
                {"variable": "reflectron_shield_inner_radius", "value": 88.8, "unit": "mm"},
            ],
        )
        self.assertEqual(candidate["geometry_mm"]["flight_tube_r"], 88.8)

    def test_larger_tof_requests_envelope_review_instead_of_being_impossible(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["flight_length"]
        with self.assertRaisesRegex(EnvelopeReviewRequired, "NEEDS_ENVELOPE_REVIEW"):
            self.compile(request, [{"variable": "flight_length", "value": 700.0, "unit": "mm"}])

    def test_midgrid_voltage_outside_narrow_envelope_requires_review(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["reflectron_midgrid_voltage"]
        with self.assertRaisesRegex(EnvelopeReviewRequired, "NEEDS_ENVELOPE_REVIEW"):
            self.compile(
                request,
                [{"variable": "reflectron_midgrid_voltage", "value": 1599.0, "unit": "V"}],
            )

    def test_candidate_generates_nonformal_simion_text_from_frozen_contract(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "prepared"
            plan = prepare(
                PROJECT_ROOT / "config" / "resolved_geometry.json",
                output,
                particle_source_seed=20260713,
            )
            resolved = (output / "simion" / "oatof_resolved.lua").read_text(encoding="utf-8")
            fly2 = (output / "simion" / "oatof_ideal_grounded.fly2").read_text(encoding="utf-8")
            frozen = json.loads(
                (PROJECT_ROOT / "config" / "resolved_geometry.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(frozen["inputs"]["solver_numerics_sha256"], resolved)
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
            plan = prepare(
                contract_path,
                root_path / "prepared",
                particle_source_seed=20260713,
            )
            program = Path(plan["consumers"]["simion"]["generated"]["program"]["path"])
            self.assertIn("adjustable accelerator_ring_width_mm=6.0", program.read_text(encoding="utf-8"))
            self.assertEqual(plan["candidate_contract"]["path"], str(contract_path.resolve()))
            self.assertEqual(
                plan["consumers"]["comsol"]["arguments"]["ContractPath"], str(contract_path.resolve())
            )

    def test_comsol_contract_is_the_only_reflectron_voltage_source(self):
        source = (PROJECT_ROOT / "comsol" / "oatof_build_model_core.m").read_text(
            encoding="utf-8"
        )
        self.assertIn("requires a resolved contract path", source)
        self.assertIn("reflectron_midgrid_voltage_v = voltageV.midgrid", source)
        self.assertIn("reflectron_backplate_voltage_v = voltageV.backplate", source)
        self.assertIn("d2_mm = geometryMm.L_stage2", source)
        self.assertNotIn("if ~isempty(contract_path)", source)
        self.assertNotIn("Legacy positional", source)

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

    def test_solidworks_bridge_uses_module_context_for_frozen_code_root(self):
        bridge = REPO_ROOT / "common" / "solidworks" / "import_step_to_solidworks.m"
        source = bridge.read_text(encoding="utf-8")
        self.assertIn(
            "codeRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))))",
            source,
        )
        self.assertIn("codeRoot = resolve_code_root()", source)
        self.assertIn("setenv('PYTHONPATH'", source)
        self.assertIn("setenv('PYTHONDONTWRITEBYTECODE', '1')", source)
        self.assertIn("-B -m common.solidworks.import_step_to_solidworks", source)
        self.assertIn("cleanupPythonPath", source)
        self.assertIn("cleanupBytecodePolicy", source)

        with tempfile.TemporaryDirectory() as root:
            code_root = Path(root) / "frozen_code"
            solidworks = code_root / "common" / "solidworks"
            solidworks.mkdir(parents=True)
            for name in ("import_step_to_solidworks.py", "installation.py"):
                shutil.copy2(REPO_ROOT / "common" / "solidworks" / name, solidworks / name)
            (code_root / "pythoncom.py").write_text("", encoding="utf-8")
            win32com = code_root / "win32com"
            win32com.mkdir()
            (win32com / "__init__.py").write_text("", encoding="utf-8")
            (win32com / "client.py").write_text("", encoding="utf-8")
            working_directory = Path(root) / "outside_frozen_code"
            working_directory.mkdir()
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(code_root)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "common.solidworks.import_step_to_solidworks",
                    "--help",
                ],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--manifest", result.stdout)
            self.assertFalse(any(code_root.rglob("__pycache__")))
            self.assertFalse(any(code_root.rglob("*.pyc")))

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
                str(
                    (
                        root_path
                        / "formal"
                        / "comsol"
                        / "single_reflection_oa_tof_mass_analyzer__model.mph"
                    ).resolve()
                ),
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
            "project_id": "single_reflection_oa_tof_mass_analyzer",
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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            run_id = "20260720_120000__build__cross__design-candidate__zero-change"
            plan = prepare_candidate_run(
                *inputs, run_id, artifact_root, particle_source_seed=20260713
            )
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
            self.assertEqual(plan["status"], "NEEDS_RUNTIME_INPUTS")
            self.assertFalse(plan["promotion"]["included"])
            self.assertFalse(plan["promotion"]["automatic"])
            self.assertFalse(plan["promotion"]["safe_to_promote"])
            self.assertEqual(plan["stages"][-1]["stage_id"], "structural_acceptance")
            self.assertEqual(plan["stages"][-1]["status"], "blocked")
            simion_stage = next(
                stage for stage in plan["stages"]
                if stage["stage_id"] == "simion_candidate"
            )
            self.assertEqual(
                simion_stage["status"],
                "blocked_requires_explicit_nonformal_template",
            )
            serialized = json.dumps(plan)
            self.assertNotIn("NEEDS_CROSS_SOLVER_RUNNER", serialized)
            self.assertNotIn("needs_integrated_candidate_runner", serialized)
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
            self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1", source_ids)
            self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_iob.lua", source_ids)
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
                prepare_candidate_run(
                    *inputs, run_id, artifact_root, particle_source_seed=20260713
                )

    def test_candidate_seed_is_required_at_each_preparation_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            with self.assertRaisesRegex(ValueError, "explicit integer particle source seed"):
                prepare_candidate_run(
                    *inputs,
                    "20260727_165900__test__cross__missing-seed",
                    root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer",
                )
            with self.assertRaisesRegex(ValueError, "explicit particle source seed"):
                prepare(
                    PROJECT_ROOT / "config" / "resolved_geometry.json",
                    root_path / "prepared",
                )

    def test_candidate_comsol_adapter_uses_contract_and_run_config_authorities(self):
        source = (
            PROJECT_ROOT
            / "workflows"
            / "design_candidate"
            / "run_candidate_contract_build.m"
        ).read_text(encoding="utf-8")
        self.assertIn("OATOF_CANDIDATE_RUN_CONFIG_PATH", source)
        self.assertIn("runConfig.run_instance.particle_count", source)
        self.assertIn("runConfig.inputs.candidate_particle_table", source)
        for forbidden in (
            "MassAmu=",
            "FineTimestepNs=",
            "AcceleratorMeshHmaxMm=",
            "DriftTimestepNs=",
            "SolverMode=",
            "FieldMode=",
        ):
            self.assertNotIn(forbidden, source)

    def test_stage_source_identity_does_not_invalidate_upstream_for_cad_only_change(self):
        closure = {
            "sources": [
                {
                    "source_id": "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_model_core.m",
                    "bytes": 1,
                    "sha256": "A" * 64,
                },
                {
                    "source_id": "projects/single_reflection_oa_tof_mass_analyzer/cad/export_oatof_cad_step.m",
                    "bytes": 1,
                    "sha256": "B" * 64,
                },
                {
                    "source_id": "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py",
                    "bytes": 1,
                    "sha256": "C" * 64,
                },
            ]
        }
        closure["code_root"] = str(PROJECT_ROOT.parents[1])
        comsol = {
            path.relative_to(PROJECT_ROOT.parents[1]).as_posix()
            for path in _stage_source_paths(closure, "comsol_candidate")
        }
        simion = {
            path.relative_to(PROJECT_ROOT.parents[1]).as_posix()
            for path in _stage_source_paths(closure, "simion_candidate")
        }
        cad = {
            path.relative_to(PROJECT_ROOT.parents[1]).as_posix()
            for path in _stage_source_paths(closure, "cad_candidate")
        }
        cad_source = "projects/single_reflection_oa_tof_mass_analyzer/cad/export_oatof_cad_step.m"
        self.assertNotIn(cad_source, comsol)
        self.assertNotIn(cad_source, simion)
        self.assertIn(cad_source, cad)

    def test_single_candidate_entry_compiles_one_fixed_plan_without_commercial_tools(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(
                artifact_root,
                "20260727_102100__build__simion__candidate-layout-template-workspace",
            )
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                plan_path = candidate_entry.prepare_execution(
                    source / "design_request.json",
                    "20260727_171000__test__cross__single-entry-dry-run",
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                )
                second_plan_path = candidate_entry.prepare_execution(
                    source / "design_request.json",
                    "20260727_171001__test__cross__single-entry-dry-run",
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                )
            plan = load_json(plan_path)
            second_plan = load_json(second_plan_path)
            self.assertEqual(
                [stage["stage_id"] for stage in plan["stages"]],
                [
                    "static_inputs",
                    "comsol_candidate",
                    "simion_candidate",
                    "cad_candidate",
                    "structural_acceptance",
                ],
            )
            for name in (
                "candidate_baseline.json",
                "candidate_resolved_geometry.json",
                "candidate_solver_numerics.json",
                "candidate_diff.json",
            ):
                self.assertEqual(
                    plan["candidate_inputs"][name]["sha256"],
                    second_plan["candidate_inputs"][name]["sha256"],
                )
            self.assertFalse(Path(plan["run_root"]).exists())

    def test_campaign_table_and_selection_are_frozen_into_child_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact_root = (
                root_path
                / "artifacts"
                / "projects"
                / "single_reflection_oa_tof_mass_analyzer"
            )
            registration = self.registered_template_run(
                artifact_root,
                "20260727_102100__build__simion__candidate-layout-template-workspace",
            )
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            run_id = "20260731_232000__test__cross__campaign-child"
            campaign = root_path / "experiment_campaign.json"
            campaign.write_text(
                json.dumps({"campaign_id": "fixture_campaign"}), encoding="utf-8"
            )
            selection = root_path / "campaign_selection.json"
            selection.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "oatof_campaign_selection",
                        "campaign_id": "fixture_campaign",
                        "campaign_run_id": "20260731_231900__test__cross__campaign-parent",
                        "experiment_id": "fixture_row",
                        "candidate_run_id": run_id,
                        "particle_source_seed": 20260720,
                        "campaign_sha256": sha256(campaign),
                        "request": {
                            "path": str(source / "design_request.json"),
                            "sha256": sha256(source / "design_request.json"),
                        },
                        "proposal": {
                            "path": str(source / "candidate_proposal.json"),
                            "sha256": sha256(source / "candidate_proposal.json"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                plan_path = candidate_entry.prepare_execution(
                    source / "design_request.json",
                    run_id,
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                    campaign_table=campaign,
                    campaign_selection=selection,
                )
            plan = load_json(plan_path)
            self.assertEqual(plan["campaign_binding"]["experiment_id"], "fixture_row")
            self.assertIn("experiment_campaign", plan["candidate_inputs"])
            self.assertIn("campaign_selection", plan["candidate_inputs"])
            child_root = start_candidate_run(plan_path)
            manifest = load_json(child_root / "run_manifest.json")
            self.assertEqual(
                manifest["campaign_binding"]["campaign_sha256"], sha256(campaign)
            )
            self.assertEqual(
                manifest["inputs"]["campaign_selection"]["sha256"],
                plan["campaign_binding"]["selection_sha256"],
            )

    def test_candidate_template_requires_successful_registered_template_build_run(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(artifact_root)
            candidate_inputs = root_path / "candidate_inputs"
            candidate_inputs.mkdir()
            inputs = self.candidate_run_inputs(candidate_inputs)
            plan = prepare_candidate_run(
                *inputs,
                "20260726_121000__build__cross__design-candidate__zero-change",
                artifact_root,
                particle_source_seed=20260713,
                simion_template_run=registration,
            )
            self.assertEqual(plan["status"], "EXECUTION_READY")
            stage = next(item for item in plan["stages"] if item["stage_id"] == "simion_candidate")
            self.assertEqual(stage["status"], "ready")
            acceptance = next(
                item for item in plan["stages"]
                if item["stage_id"] == "structural_acceptance"
            )
            self.assertEqual(acceptance["status"], "ready")
            self.assertEqual(stage["template_input"]["role"], "oa_tof_candidate_simion_layout_template")
            self.assertTrue(Path(stage["template_input"]["files"]["iob"]["path"]).is_file())
            self.assertTrue(Path(stage["template_input"]["files"]["con"]["path"]).is_file())

    def test_candidate_workflow_rejects_missing_template_before_run_start(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            source = root_path / "candidate_inputs"
            source.mkdir()
            plan = prepare_candidate_run(
                *self.candidate_run_inputs(source),
                "20260726_121001__build__cross__design-candidate__missing-template",
                artifact_root,
                particle_source_seed=20260713,
            )
            plan_path = Path(plan["planning_root"]) / "candidate_workflow_plan.json"
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow.start_candidate_run"
            ) as start:
                with self.assertRaisesRegex(
                    ValueError, "not execution-ready: NEEDS_RUNTIME_INPUTS"
                ):
                    run_candidate_workflow(plan_path, "unused")
            start.assert_not_called()
            self.assertFalse(Path(plan["run_root"]).exists())

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
            artifact_root = Path(root) / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            formal = artifact_root / "formal" / "inputs"
            formal.mkdir(parents=True)
            inputs = self.candidate_run_inputs(formal)
            with self.assertRaisesRegex(ValueError, "must not be sourced from formal"):
                prepare_candidate_run(
                    *inputs, "20260720_120001__build__cross__design-candidate__formal-source",
                    artifact_root, particle_source_seed=20260713,
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
                    root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer",
                    particle_source_seed=20260713,
                )

    def materialize_candidate_run(self, root_path, stamp="20260720_130000"):
        artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
        artifact_root.mkdir(parents=True)
        (artifact_root / "00_README.txt").write_text("test artifact root", encoding="utf-8")
        source = root_path / "source"
        source.mkdir()
        inputs = self.candidate_run_inputs(source)
        run_id = f"{stamp}__build__cross__design-candidate__lifecycle"
        plan = prepare_candidate_run(
            *inputs, run_id, artifact_root, particle_source_seed=20260713
        )
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
                    root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer",
                    particle_source_seed=20260713,
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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            source = root_path / "source"
            source.mkdir()
            inputs = self.candidate_run_inputs(source)
            plan = prepare_candidate_run(
                *inputs, "20260720_130003__build__cross__design-candidate__tamper",
                artifact_root, particle_source_seed=20260713,
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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            source = root_path / "source"
            source.mkdir()
            inputs = self.candidate_run_inputs(source)
            plan = prepare_candidate_run(
                *inputs, "20260720_130004__build__cross__design-candidate__text-tamper",
                artifact_root, particle_source_seed=20260713,
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
                artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
                source = root_path / "source"
                source.mkdir()
                plan = prepare_candidate_run(
                    *self.candidate_run_inputs(source),
                    f"20260720_13001{index}__build__cross__design-candidate__source-{case}",
                    artifact_root,
                    particle_source_seed=20260713,
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
        artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
        artifact_root.mkdir(parents=True)
        (artifact_root / "00_README.txt").write_text("test artifact root", encoding="utf-8")
        source = root_path / "source"
        source.mkdir()
        inputs = self.candidate_run_inputs(source)
        plan = prepare_candidate_run(
            *inputs, f"{stamp}__build__cross__design-candidate__integrated",
            artifact_root, particle_source_seed=20260713,
        )
        return artifact_root, Path(plan["planning_root"]) / "candidate_workflow_plan.json"

    def test_integrated_runner_success_closes_one_root_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.native_workflow_plan(
                Path(root), "20260720_140000"
            )
            observed = []

            def fake_executor(stage, plan, _simion):
                observed.append(stage["stage_id"])
                if stage["stage_id"] == "static_inputs":
                    particle = Path(stage["pending_output"])
                    particle.write_text("particle\n", encoding="utf-8")
                evidence_path = Path(plan["run_root"]) / "results" / f"{stage['stage_id']}.txt"
                evidence_path.write_text("STATUS=PASS\n", encoding="utf-8")
                evidence = {"report": str(evidence_path)}
                if stage["stage_id"] == "comsol_candidate":
                    model = Path(plan["run_root"]) / "comsol" / "candidate.mph"
                    model.write_text("candidate model\n", encoding="utf-8")
                    evidence["model"] = str(model)
                return evidence

            run_root, summary = run_candidate_workflow(
                plan_path, sys.executable, stage_executor=fake_executor
            )
            expected = ["static_inputs", "comsol_candidate", "simion_candidate", "cad_candidate", "structural_acceptance"]
            self.assertEqual(observed, expected)
            self.assertEqual([item["stage_id"] for item in summary["stages"]], expected)
            self.assertEqual(summary["acceptance_scope"], "structural_build_and_contract")
            self.assertFalse(summary["performance_claim_allowed"])
            self.assertEqual(verify_project(artifact_root), (2, 0))
            self.assertEqual(load_json(run_root / "run_manifest.json")["status"], "success")

    def test_integrated_runner_terminal_faults_close_remaining_stages(self):
        cases = (("failed", "simion_candidate", CandidateWorkflowError, "20260720_140001"),
                 ("interrupted", "cad_candidate", CandidateWorkflowInterrupted, "20260720_140002"),
                 ("timeout", "comsol_candidate", CandidateWorkflowTimedOut, "20260720_140003"))
        for outcome, stop_stage, exception_type, stamp in cases:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as root:
                artifact_root, plan_path = self.native_workflow_plan(
                    Path(root), stamp
                )

                def fake_executor(stage, plan, _simion):
                    if stage["stage_id"] == stop_stage:
                        if outcome == "interrupted":
                            raise KeyboardInterrupt("test interruption")
                        if outcome == "timeout":
                            raise StageTimedOut("test timeout")
                        raise RuntimeError("test failure")
                    if stage["stage_id"] == "static_inputs":
                        Path(stage["pending_output"]).write_text(
                            "particle\n", encoding="utf-8"
                        )
                    evidence_path = (
                        Path(plan["run_root"])
                        / "results"
                        / f"{stage['stage_id']}.txt"
                    )
                    evidence_path.write_text("STATUS=PASS\n", encoding="utf-8")
                    evidence = {"report": str(evidence_path)}
                    if stage["stage_id"] == "comsol_candidate":
                        model = Path(plan["run_root"]) / "comsol" / "candidate.mph"
                        model.write_text("candidate model\n", encoding="utf-8")
                        evidence["model"] = str(model)
                    return evidence

                with self.assertRaises(exception_type) as caught:
                    run_candidate_workflow(
                        plan_path, sys.executable, stage_executor=fake_executor
                    )
                run_root = caught.exception.run_root
                summary = load_json(run_root / "summary.json")
                expected_status = "failed" if outcome == "timeout" else outcome
                self.assertEqual(summary["status"], expected_status)
                self.assertEqual(summary["failure_stage"], stop_stage)
                statuses = {item["stage_id"]: item["status"] for item in summary["stages"]}
                self.assertEqual(statuses[stop_stage], expected_status)
                if outcome == "timeout":
                    failed_stage = next(
                        item for item in summary["stages"]
                        if item["stage_id"] == stop_stage
                    )
                    self.assertEqual(failed_stage["failure_class"], "timeout")
                later = False
                for item in summary["stages"]:
                    if later:
                        self.assertEqual(item["status"], "blocked")
                    later = later or item["stage_id"] == stop_stage
                self.assertEqual(verify_project(artifact_root), (2, 0))

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
                "stage_id": "structural_acceptance", "output_dir": str(run_root / "results"),
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
            "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_n100_transport.ps1",
            "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1",
            "projects/single_reflection_oa_tof_mass_analyzer/analysis/solver_diagnostics.py",
        }
        self.assertTrue(required.issubset(set(RELATIVE_PATHS)))
        self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1", PYTHON_BOUND_SOURCES)

    def test_functional_solver_test_runners_use_short_lived_execution_aliases(self):
        for relative in (
            "tests/comsol/run_n100_candidate_functional.ps1",
            "tests/simion/run_n100_source_build_and_track.ps1",
        ):
            runner = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("-UseShortExecutionPath", runner, relative)
            self.assertIn(
                "Remove-RunPackageExecutionAlias -Package $package",
                runner,
                relative,
            )

    def test_simion_candidate_requires_explicit_nonformal_frozen_template_before_builder(self):
        with tempfile.TemporaryDirectory() as root:
            run_root = Path(root)
            stage = {"stage_id": "simion_candidate", "status": "blocked_requires_explicit_nonformal_template"}
            with mock.patch("projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command") as command:
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
            with self.assertRaisesRegex(RuntimeError, "must not reference a Formal, archive, or history path"):
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
            PROJECT_ROOT / "workflows" / "formal_reference" / "verify_geometry_contract.ps1",
            PROJECT_ROOT / "workflows" / "mass_spectrum_candidate" / "run_mass_spectrum_candidate.ps1",
            PROJECT_ROOT / "tests" / "simion" / "run_n100_source_build_and_track.ps1",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            preflight = text.index("Assert-OaTofFormalAssetsReadable")
            first_asset = min(index for index in (text.find("formal\\"), text.find("New-Item -ItemType Directory")) if index >= 0)
            self.assertLess(preflight, first_asset, script.name)

        formal_cli = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "run_formal_validation.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("-Phase Verify", formal_cli)
        validate_branch = formal_cli[formal_cli.index("$candidateRoot =") :]
        self.assertNotIn("Assert-OaTofFormalAssetsReadable", validate_branch)

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
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            artifact_root.mkdir(parents=True)
            template_run = self.registered_template_run(artifact_root)
            source = root_path / "candidate_inputs"
            source.mkdir()
            plan = prepare_candidate_run(
                *self.candidate_run_inputs(source),
                "20260727_110000__build__cross__design-candidate__frozen-builder-root",
                artifact_root,
                particle_source_seed=20260713,
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
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command",
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
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._verify_frozen_cad_python",
                return_value=plan["execution_source_closure"]["runtime"]["python_executable"],
            ), mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command",
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

    def test_cad_python_preflight_blocks_comsol_before_commercial_launcher(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.prepared_workflow_plan(Path(root), "20260727_131000")
            plan = load_json(plan_path)
            stage = next(item for item in plan["stages"] if item["stage_id"] == "comsol_candidate")
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._verify_frozen_cad_python",
                side_effect=RuntimeError("candidate CAD Python runtime preflight failed"),
            ), mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command"
            ) as commercial_launcher:
                with self.assertRaisesRegex(RuntimeError, "CAD Python runtime preflight failed"):
                    execute_stage(stage, plan, "unused")
            commercial_launcher.assert_not_called()
            self.assertTrue(artifact_root.is_dir())

    def test_cad_python_preflight_reports_missing_pywin32(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            runtime = root_path / "python.exe"
            runtime.write_bytes(b"frozen runtime")
            closure = {"runtime": {"python_executable": str(runtime)}}
            failed = subprocess.CompletedProcess(
                [str(runtime), "-c", "unused"], 1, stdout="", stderr="ModuleNotFoundError: pythoncom"
            )
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow.subprocess.run",
                return_value=failed,
            ) as command:
                with self.assertRaisesRegex(RuntimeError, "cannot import pythoncom and win32com.client"):
                    _verify_frozen_cad_python(closure, root_path / "preflight.log")
            self.assertEqual(command.call_args.args[0][0], str(runtime.resolve()))
            self.assertIn("pythoncom", (root_path / "preflight.log").read_text(encoding="utf-8"))

    def test_command_runner_merges_environment_without_name_error(self):
        with tempfile.TemporaryDirectory() as root:
            log_path = Path(root) / "command.log"
            completed = subprocess.CompletedProcess(["unused"], 0)
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow.subprocess.run",
                return_value=completed,
            ) as command:
                _run_command(["unused"], log_path, {"OATOF_TEST_ENVIRONMENT": "present"})
            self.assertEqual(command.call_args.kwargs["env"]["OATOF_TEST_ENVIRONMENT"], "present")

    def native_workflow_plan(self, root_path, stamp, *, particle_source_seed=20260720):
        artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / "00_README.txt").write_text(
            "test artifact root", encoding="utf-8"
        )
        registration = artifact_root / "runs" / "20260726_120000__build__simion__candidate-layout-template"
        if not registration.exists():
            registration = self.registered_template_run(artifact_root)
        source = root_path / "source_native"
        source.mkdir(exist_ok=True)
        plan = prepare_candidate_run(
            *self.candidate_run_inputs(source),
            f"{stamp}__test__cross__native-receipts",
            artifact_root,
            particle_source_seed=particle_source_seed,
            simion_template_run=registration,
        )
        return artifact_root, Path(plan["planning_root"]) / "candidate_workflow_plan.json"

    @staticmethod
    def native_fake_executor(observed, *, fail_stage=None, tamper_closure=False):
        def execute(stage, plan, _simion):
            stage_id = stage["stage_id"]
            observed.append(stage_id)
            run_root = Path(plan["run_root"])
            if fail_stage == stage_id:
                raise RuntimeError(f"injected {stage_id} failure")
            if stage_id == "static_inputs":
                path = Path(stage["pending_output"])
                seed = plan["run_instance"]["particle_source_seed"]
                path.write_text(f"particle:{seed}\n", encoding="utf-8")
                return {"particle_table": str(path)}
            names = {
                "comsol_candidate": ("model", "build_report", "sync_report"),
                "simion_candidate": (
                    "iob",
                    "ion_n100",
                    "stage_summary",
                    "runtime_report",
                    "transport_summary",
                    "particle_csv",
                    "transport_diagnostics",
                ),
                "cad_candidate": ("report", "cad_report"),
                "structural_acceptance": ("acceptance",),
            }[stage_id]
            evidence = {}
            for name in names:
                path = run_root / "results" / f"{stage_id}_{name}.dat"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{stage_id}:{name}\n", encoding="utf-8")
                evidence[name] = str(path)
            if tamper_closure and stage_id in {
                "structural_acceptance",
            }:
                closure = plan["execution_source_closure"]
                code_root = Path(closure["code_root"])
                target = code_root / closure["sources"][0]["source_id"]
                target.write_text(
                    target.read_text(encoding="utf-8") + "\n% tampered\n",
                    encoding="utf-8",
                )
            return evidence

        return execute

    def test_bootstrap_writes_three_manifest_bound_stage_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170000"
            )
            observed = []
            run_root, summary = run_candidate_workflow(
                plan_path,
                sys.executable,
                stage_executor=self.native_fake_executor(observed),
            )
            self.assertEqual(summary["status"], "success")
            self.assertEqual(
                [path.stem for path in sorted((run_root / "stage_receipts").glob("*.json"))],
                list(("cad_candidate", "comsol_candidate", "simion_candidate")),
            )
            manifest = load_json(run_root / "run_manifest.json")
            manifest_paths = {
                Path(record["path"]).resolve()
                for record in manifest["outputs"]
            }
            for stage_id in ("comsol_candidate", "simion_candidate", "cad_candidate"):
                self.assertIn(
                    (run_root / "stage_receipts" / f"{stage_id}.json").resolve(),
                    manifest_paths,
                )
            self.assertNotIn(
                "stage_reuse_provenance",
                load_json(run_root / "run_config.json")["inputs"],
            )
            self.assertEqual(verify_project(artifact_root), (2, 0))

    def test_native_failed_parent_reuses_prefix_and_runs_only_cad_after_static(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root, parent_plan = self.native_workflow_plan(
                root_path, "20260727_170100"
            )
            with self.assertRaises(CandidateWorkflowError) as caught:
                run_candidate_workflow(
                    parent_plan,
                    sys.executable,
                    stage_executor=self.native_fake_executor(
                        [], fail_stage="cad_candidate"
                    ),
                )
            parent = caught.exception.run_root
            self.assertEqual(load_json(parent / "summary.json")["status"], "failed")

            _, child_plan = self.native_workflow_plan(
                root_path, "20260727_170200"
            )
            observed = []
            run_root, summary = run_candidate_workflow(
                child_plan,
                sys.executable,
                stage_executor=self.native_fake_executor(observed),
                reuse_parent=parent,
                reuse_through="simion_candidate",
            )
            self.assertEqual(
                observed,
                ["static_inputs", "cad_candidate", "structural_acceptance"],
            )
            statuses = {item["stage_id"]: item for item in summary["stages"]}
            self.assertEqual(statuses["comsol_candidate"]["execution"], "reused")
            self.assertEqual(statuses["simion_candidate"]["execution"], "reused")
            self.assertEqual(statuses["cad_candidate"]["execution"], "executed")
            self.assertTrue(
                (run_root / "inputs" / "stage_reuse_provenance.json").is_file()
            )

    def test_native_reuse_tamper_fails_before_any_commercial_stage(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            _, parent_plan = self.native_workflow_plan(
                root_path, "20260727_170300"
            )
            parent, _ = run_candidate_workflow(
                parent_plan,
                sys.executable,
                stage_executor=self.native_fake_executor([]),
            )
            _, child_plan = self.native_workflow_plan(
                root_path, "20260727_170400"
            )
            observed = []

            def changed_static(stage, plan, simion):
                evidence = self.native_fake_executor(observed)(stage, plan, simion)
                if stage["stage_id"] == "static_inputs":
                    Path(evidence["particle_table"]).write_text(
                        "changed particle\n", encoding="utf-8"
                    )
                return evidence

            with self.assertRaises(CandidateWorkflowError) as caught:
                run_candidate_workflow(
                    child_plan,
                    sys.executable,
                    stage_executor=changed_static,
                    reuse_parent=parent,
                    reuse_through="simion_candidate",
                )
            self.assertEqual(observed, ["static_inputs"])
            self.assertEqual(
                load_json(caught.exception.run_root / "summary.json")["status"],
                "failed",
            )

    def test_entry_reuse_is_run_id_independent_but_seed_sensitive(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(
                artifact_root,
                "20260727_102100__build__simion__candidate-layout-template-workspace",
            )
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            request = source / "design_request.json"
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                parent, _ = candidate_entry.execute_request(
                    request,
                    "20260727_170410__test__cross__entry-reuse-parent",
                    simion_executable=Path(sys.executable),
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                    stage_executor=self.native_fake_executor([]),
                )
                same_seed_observed = []
                same_seed_child, _ = candidate_entry.execute_request(
                    request,
                    "20260727_170420__test__cross__entry-reuse-same-seed",
                    simion_executable=Path(sys.executable),
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                    reuse_parent=parent,
                    reuse_through="simion_candidate",
                    stage_executor=self.native_fake_executor(same_seed_observed),
                )
                different_seed_observed = []
                with self.assertRaises(CandidateWorkflowError) as caught:
                    candidate_entry.execute_request(
                        request,
                        "20260727_170430__test__cross__entry-reuse-different-seed",
                        simion_executable=Path(sys.executable),
                        particle_source_seed=20260721,
                        artifact_project_root=artifact_root,
                        reuse_parent=parent,
                        reuse_through="simion_candidate",
                        stage_executor=self.native_fake_executor(
                            different_seed_observed
                        ),
                    )
            self.assertEqual(
                same_seed_observed,
                ["static_inputs", "cad_candidate", "structural_acceptance"],
            )
            self.assertEqual(different_seed_observed, ["static_inputs"])
            self.assertIn("input", str(caught.exception))
            self.assertIn("changed", str(caught.exception))
            parent_config = load_json(parent / "run_config.json")
            same_seed_config = load_json(same_seed_child / "run_config.json")
            different_seed_config = load_json(
                caught.exception.run_root / "run_config.json"
            )
            resolved_name = "candidate_resolved_geometry.json"
            self.assertEqual(
                parent_config["input_sha256"][resolved_name],
                same_seed_config["input_sha256"][resolved_name],
            )
            self.assertEqual(
                parent_config["input_sha256"][resolved_name],
                different_seed_config["input_sha256"][resolved_name],
            )
            self.assertNotEqual(
                parent_config["input_sha256"]["candidate_particle_table"],
                different_seed_config["input_sha256"]["candidate_particle_table"],
            )

    def test_native_closure_failure_still_writes_failed_triple(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170500"
            )
            with self.assertRaises(CandidateWorkflowError) as caught:
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=self.native_fake_executor(
                        [], tamper_closure=True
                    ),
                )
            run_root = caught.exception.run_root
            self.assertEqual(load_json(run_root / "summary.json")["status"], "failed")
            self.assertEqual(load_json(run_root / "run_manifest.json")["status"], "failed")
            self.assertEqual(verify_project(artifact_root), (2, 0))

    def test_native_cad_rejects_mph_tamper_after_context_before_launch(self):
        with tempfile.TemporaryDirectory() as root:
            _, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170600"
            )
            observed = []
            base = self.native_fake_executor(observed)

            def tamper_after_context(stage, plan, simion):
                evidence = base(stage, plan, simion)
                if stage["stage_id"] == "simion_candidate":
                    model = (
                        Path(plan["run_root"])
                        / "results"
                        / "comsol_candidate_model.dat"
                    )
                    model.write_text("tampered model\n", encoding="utf-8")
                return evidence

            with self.assertRaisesRegex(
                CandidateWorkflowError,
                "Candidate MPH differs from its frozen identity",
            ):
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=tamper_after_context,
                )
            self.assertEqual(
                observed,
                ["static_inputs", "comsol_candidate", "simion_candidate"],
            )

    def test_native_rejects_raw_input_tamper_after_context_before_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            _, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170700"
            )
            observed = []
            base = self.native_fake_executor(observed)

            def tamper_input(stage, plan, simion):
                evidence = base(stage, plan, simion)
                if stage["stage_id"] == "comsol_candidate":
                    baseline = Path(
                        plan["candidate_inputs"]["candidate_baseline.json"]["path"]
                    )
                    baseline.write_text(
                        baseline.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8",
                    )
                return evidence

            with self.assertRaisesRegex(
                CandidateWorkflowError,
                "frozen candidate run input changed",
            ):
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=tamper_input,
                )
            self.assertEqual(observed, ["static_inputs", "comsol_candidate"])

    def test_native_rechecks_candidate_mph_after_cad_executor(self):
        with tempfile.TemporaryDirectory() as root:
            _, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170800"
            )
            observed = []
            base = self.native_fake_executor(observed)

            def mutate_during_cad(stage, plan, simion):
                evidence = base(stage, plan, simion)
                if stage["stage_id"] == "cad_candidate":
                    Path(stage["model_path"]).write_text(
                        "CAD modified its input\n", encoding="utf-8"
                    )
                return evidence

            with self.assertRaisesRegex(
                CandidateWorkflowError,
                "Candidate MPH differs from its frozen identity",
            ):
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=mutate_during_cad,
                )
            self.assertEqual(
                observed,
                [
                    "static_inputs",
                    "comsol_candidate",
                    "simion_candidate",
                    "cad_candidate",
                ],
            )


if __name__ == "__main__":
    unittest.main()
