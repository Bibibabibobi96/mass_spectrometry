from __future__ import annotations

import json
import tempfile
from pathlib import Path
from common.contracts.machine_contracts import load_json, sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import start_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import compile_proposal, write_candidate
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import prepare_candidate_run

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PROJECT_ROOT.parents[1]



class CandidateFixtures:
    """Shared preparation only: no TestCase base and no test methods."""
    @staticmethod
    def managed_completion_fixture(exit_code=0):
        return {"schema_version": 1, "role": "repository_managed_python_completion",
            "ownership_confirmed": True, "worker_exit_confirmed": True, "launcher_exit_confirmed": True,
            "stdout_drained": True, "stderr_drained": True, "exit_code": exit_code,
            "worker_process_id": 123, "worker_started_at_utc_ticks": 456}


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
