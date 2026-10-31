from __future__ import annotations

import json
import ast
import copy
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock
from common.contracts.machine_contracts import load_json, sha256
from common.contracts import write_run_manifest as terminal_publication
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import start_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import verify_candidate_source_closure
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import compile_proposal, write_candidate
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import prepare_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as candidate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import CandidateWorkflowError, run_candidate_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PROJECT_ROOT.parents[1]

def inline_legacy_candidate_freezer(freeze, *, omit_scientific_source=False):
    """Materialize the known old inline producer as bound inert fixture evidence."""
    def frozen(*args, **kwargs):
        closure = freeze(*args, **kwargs)
        code = Path(closure["code_root"])
        directory = code / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate"
        source_path = directory / "run_candidate_workflow.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        native_witness = Path(__file__).with_name("legacy_candidate_native_owner.py")
        old_native = next(node for node in ast.parse(native_witness.read_text(encoding="utf-8")).body
                          if isinstance(node, ast.FunctionDef) and node.name == "_run_managed_stage_command")
        def function(parsed, name):
            return copy.deepcopy(next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == name))
        execute = function(tree, "execute_stage")
        # Exact legacy dispatch prefix; no old Python is imported or executed.
        prefix = ast.parse('stage_id = stage["stage_id"]\nif stage_id == "simion_candidate" and stage.get("status") == "blocked_requires_explicit_nonformal_template":\n    raise RuntimeError("candidate SIMION stage is blocked until an explicit non-Formal template is frozen")\nclosure = plan.get("execution_source_closure")\nif closure is not None:\n    verify_candidate_source_closure(closure)\nrun_root = Path(plan["run_root"])\nlogs = run_root / "logs"\n').body
        branches = {n.test.comparators[0].value: n for n in execute.body if isinstance(n, ast.If)
                    and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
                    and n.test.left.id == "stage_id" and isinstance(n.test.comparators[0], ast.Constant)}
        extra = []
        transport = ast.parse((directory / "candidate_stage_execution.py").read_text(encoding="utf-8"))
        for name in ("_powershell", "_require_pass_report"):
            extra.append(function(transport, name))
        for kind in ("comsol", "simion", "cad"):
            module = ast.parse((directory / f"candidate_{kind}_stage.py").read_text(encoding="utf-8"))
            stage = function(module, f"execute_{kind}_stage")
            if kind == "simion":
                extra.append(function(module, "_nonformal_template"))
                start = next(i for i,n in enumerate(stage.body) if isinstance(n, ast.Assign)
                             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "template")
            else:
                start = next(i for i,n in enumerate(stage.body) if isinstance(n, ast.If)
                             and ast.unparse(n.test) == "closure is None")
            if kind == "comsol":
                extra.append(function(module, "_report_value"))
            condition = ast.parse(f'if stage_id == "{kind}_candidate":\n    pass').body[0]
            condition.body = stage.body[start:]
            branches[kind + "_candidate"] = condition
        execute.body = prefix + [branches[name] for name in ("static_inputs", "comsol_candidate", "simion_candidate", "cad_candidate", "structural_acceptance")]
        execute.body.append(ast.parse('raise ValueError(f"unsupported candidate workflow stage: {stage_id}")').body[0])
        updated = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name.startswith("_legacy_") or node.name == "_project_legacy_stage_contexts":
                    continue
                if node.name == "execute_stage":
                    node = execute
                if node.name == "_run_managed_stage_command":
                    node = copy.deepcopy(old_native)
                if node.name == "_execute_candidate_stages":
                    for nested in ast.walk(node):
                        for field, value in ast.iter_fields(nested):
                            if isinstance(value, list):
                                setattr(nested, field, [item for item in value if not (
                                    isinstance(item, ast.Assign) and isinstance(item.value, ast.Call)
                                    and isinstance(item.value.func, ast.Name) and item.value.func.id == "_project_legacy_stage_contexts")])
            if isinstance(node, ast.ImportFrom) and "candidate_stage_execution" in (node.module or ""):
                continue
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "STAGE_SOURCE_PREFIXES":
                prefixes = ast.literal_eval(node.value)
                for name, values in prefixes.items():
                    prefixes[name] = tuple(value for value in values if not value.endswith(("candidate_stage_execution.py", f"candidate_{name.split('_')[0]}_stage.py"))) + (
                        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py",)
                node.value = ast.parse(repr(prefixes), mode="eval").body
            updated.append(node)
        tree.body = updated + extra
        source_path.write_text(ast.unparse(ast.fix_missing_locations(tree)) + "\n", encoding="utf-8", newline="\n")
        removed = {"candidate_stage_execution.py", "candidate_comsol_stage.py", "candidate_simion_stage.py", "candidate_cad_stage.py"}
        kept = []
        for record in closure["sources"]:
            path = code / record["source_id"]
            if path.name in removed or (omit_scientific_source and record["source_id"] == "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_model_core.m"):
                path.unlink()
            else:
                record.update(bytes=path.stat().st_size, sha256=sha256(path))
                kept.append(record)
        closure["sources"] = kept
        verify_candidate_source_closure(closure)
        return closure
    return frozen


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


    def legacy_inline_parent(self, root, *, omit_scientific_source=False):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        freeze = preparation.freeze_candidate_source_closure
        with mock.patch.object(preparation, "freeze_candidate_source_closure", side_effect=inline_legacy_candidate_freezer(freeze, omit_scientific_source=omit_scientific_source)):
            _, parent_plan_path = self.native_workflow_plan(root, "20260727_190100")
        original_plan = load_json(parent_plan_path)
        execute = self.native_fake_executor([])
        def parent_executor(stage, plan, executable):
            evidence = execute(stage, plan, executable)
            if stage["stage_id"] == "comsol_candidate":
                for name in ("analysis_request", "analysis_receipt"):
                    path = Path(plan["run_root"]) / "results" / ("inert_" + name + ".dat")
                    path.write_text("inert software witness; not solver output\n", encoding="utf-8")
                    evidence[name] = str(path)
            if stage["stage_id"] == "structural_acceptance":
                owner = Path(plan["run_root"])
                old_code = Path(plan["execution_source_closure"]["code_root"])
                entrypoint = old_code / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py"
                request_path = owner / "inputs/execution_request.json"
                request = {"schema_version": 1, "role": "run_artifact_workflow_request",
                    "package": {"project": "single_reflection_oa_tof_mass_analyzer", "run_id": owner.name,
                        "mode": "design_candidate", "artifact_project_root": str(owner.parent.parent)},
                    "prepared": {"module": "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow",
                        "function": "execute_prepared_run", "import_root": str(old_code), "entrypoint": terminal_publication.file_record(entrypoint)},
                    "payload": {"plan": terminal_publication.file_record(parent_plan_path)}}
                request_path.write_text(json.dumps(request), encoding="utf-8")
                plan["context_sha256"] = sha256(request_path).lower()
                (owner / "candidate_workflow_plan.json").write_text(json.dumps(plan), encoding="utf-8")
                config_path = owner / "run_config.json"
                config = load_json(config_path)
                config.update(schema_version=2, artifact_retention={"policy_version": 1, "class": "solver_review", "reason": "inert legacy projection fixture"})
                config["inputs"]["execution_request"] = str(request_path)
                config["input_sha256"]["execution_request"] = sha256(request_path)
                config_path.write_text(json.dumps(config), encoding="utf-8")
                # Explicit inert transport facts: software proof fixture, not native scientific evidence.
                completion = {"schema_version": 1, "role": "run_artifact_workflow_completion", "run_id": owner.name,
                    "project": "single_reflection_oa_tof_mass_analyzer", "status": "success",
                    "execution_request": terminal_publication.file_record(request_path),
                    "run_config": terminal_publication.file_record(config_path),
                    "summary": {"run_id": owner.name, "status": "success", "stages": [*plan["stage_results_so_far"],
                        {"stage_id": "structural_acceptance", "status": "success", "execution": "executed", "evidence": evidence}]},
                    "output_paths": [str(path) for path in owner.rglob("*") if path.is_file()],
                    "required_output_paths": [value for result in [*plan["stage_results_so_far"], {"evidence": evidence}]
                        for value in result.get("evidence", {}).values()],
                    "retention_preserve_paths": [], "manifest_extra_fields": {"lifecycle_state": "terminal", "promotion_authorized": False,
                        "execution_source_closure": plan["execution_source_closure"]}, "exception": None,
                    "writer_completion": {"operations": [{"operation_id": name + ".fixture",
                        "observation": {"exit_confirmed": True, "returncode": 0}, "resource_release_id": name}
                        for name in ("comsol_build_completion", "comsol_sync_completion", "simion_build_completion", "simion_flight_completion", "cad_completion")],
                        "resource_releases": [{"release_id": name, "completion_receipt": {"host_release": {
                            "inherited": False, "token": name, "result": {"status": "released", "token": name}, "error": None}}}
                            for name in ("comsol_build_completion", "comsol_sync_completion", "simion_build_completion", "simion_flight_completion", "cad_completion")]}}
                (owner / "results/execution_completion.json").write_text(json.dumps(completion), encoding="utf-8")
            return evidence
        old_source = Path(original_plan["execution_source_closure"]["code_root"]) / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py"
        old_prefixes = ast.literal_eval(next(node.value for node in ast.parse(old_source.read_text(encoding="utf-8")).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "STAGE_SOURCE_PREFIXES"))
        with mock.patch.object(candidate_workflow, "STAGE_SOURCE_PREFIXES", old_prefixes):
            parent, _ = run_candidate_workflow(parent_plan_path, sys.executable, stage_executor=parent_executor)
        return parent


    def assert_legacy_rejections(self, scenarios):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self.legacy_inline_parent(root, omit_scientific_source=(scenarios == ("missing_scientific_source",)))
            originals = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
            freeze = preparation.freeze_candidate_source_closure
            # One real prepared source/child suffices for proof-local negative
            # cases; unknown writer keeps the complete public-owner failure path.
            direct = len(scenarios) > 1
            if direct:
                _, direct_plan_path = self.native_workflow_plan(root, "20260727_195000")
                direct_root = start_candidate_run(direct_plan_path)
                direct_plan = load_json(direct_root / "candidate_workflow_plan.json")
                self.native_fake_executor([])(direct_plan["stages"][0], direct_plan, sys.executable)
                contexts = {"comsol_candidate": candidate_workflow._stage_context(
                    direct_root, direct_plan, "comsol_candidate", sys.executable)}
                direct_code = Path(direct_plan["execution_source_closure"]["code_root"])
                scientific_source = direct_code / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_comsol_stage.py"
                scientific_bytes = scientific_source.read_bytes()
                expected_errors = {
                    "missing_request": "legacy source lacks its original frozen execution request",
                    "unbound_completion": "legacy public completion is not uniquely manifest-bound",
                    "pending_journal": "run terminal publication is incomplete",
                    "stage_environment": "legacy actual command/environment plan is not the frozen runtime plan",
                    "scientific_drift": "legacy scientific implementation differs: comsol_candidate",
                    "request_context": "legacy actual dispatch lacks its original execution-request context binding",
                    "incomplete_stage_outputs": "legacy comsol_candidate does not contain the known producer's complete output contract",
                }
            for index, scenario in enumerate(scenarios):
                with self.subTest(scenario=scenario):
                    manifest_path = parent / "run_manifest.json"
                    manifest = load_json(manifest_path)
                    def bind(path):
                        for record in [manifest["run_config"], *manifest.get("inputs", {}).values(), *manifest["outputs"]]:
                            if Path(record["path"]).resolve() == path:
                                record.update(terminal_publication.file_record(path))
                        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    if scenario == "missing_request":
                        path = parent / "run_config.json"
                        config = load_json(path)
                        del config["inputs"]["execution_request"]
                        path.write_text(json.dumps(config), encoding="utf-8")
                        bind(path)
                    elif scenario == "unknown_writer":
                        path = parent / "results/execution_completion.json"
                        completion = load_json(path)
                        completion["writer_completion"]["operations"][0]["observation"]["exit_confirmed"] = False
                        path.write_text(json.dumps(completion), encoding="utf-8")
                        bind(path)
                    elif scenario == "unbound_completion":
                        manifest["outputs"] = [record for record in manifest["outputs"] if Path(record["path"]).name != "execution_completion.json"]
                        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    elif scenario == "pending_journal":
                        (parent / ".run_terminal_publication.json").write_text("{}", encoding="utf-8")
                    elif scenario == "request_context":
                        path = parent / "candidate_workflow_plan.json"
                        old_plan = load_json(path)
                        old_plan["context_sha256"] = "0" * 64
                        path.write_text(json.dumps(old_plan), encoding="utf-8")
                        bind(path)
                    elif scenario == "incomplete_stage_outputs":
                        path = parent / "stage_receipts/comsol_candidate.json"
                        receipt = load_json(path)
                        del receipt["outputs"]["analysis_receipt"]
                        path.write_text(json.dumps(receipt), encoding="utf-8")
                        bind(path)
                    elif scenario == "stage_environment":
                        path = parent / "candidate_workflow_plan.json"
                        old_plan = load_json(path)
                        next(item for item in old_plan["stages"] if item["stage_id"] == "comsol_candidate")["environment"]["OATOF_CANDIDATE_CONTRACT_PATH"] = "unbound scientific input"
                        path.write_text(json.dumps(old_plan), encoding="utf-8")
                        bind(path)
                    changed_parent = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
                    def drifted_freeze(*args, **kwargs):
                        closure = freeze(*args, **kwargs)
                        source_id = "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_comsol_stage.py"
                        path = Path(closure["code_root"]) / source_id
                        path.write_text(path.read_text(encoding="utf-8").replace("run_candidate_contract_build.m", "changed_science.m"), encoding="utf-8", newline="\n")
                        record = next(item for item in closure["sources"] if item["source_id"] == source_id)
                        record.update(bytes=path.stat().st_size, sha256=sha256(path))
                        return closure
                    if direct and scenario != "unknown_writer":
                        if scenario == "scientific_drift":
                            text = scientific_bytes.decode("utf-8")
                            self.assertEqual(text.count("run_candidate_contract_build.m"), 1)
                            scientific_source.write_text(text.replace("run_candidate_contract_build.m", "changed_science.m"),
                                encoding="utf-8", newline="\n")
                        try:
                            with self.assertRaisesRegex(ValueError, expected_errors[scenario]):
                                candidate_workflow._project_legacy_stage_contexts(
                                    parent, direct_root, direct_plan, contexts, {"comsol_candidate"})
                        finally:
                            scientific_source.write_bytes(scientific_bytes)
                            shutil.rmtree(direct_root / "inputs/stage_contexts/legacy_projection", ignore_errors=True)
                    else:
                        with mock.patch.object(preparation, "freeze_candidate_source_closure", side_effect=drifted_freeze if scenario == "scientific_drift" else freeze):
                            _, plan = self.native_workflow_plan(root, f"20260727_19{10+index:02d}00")
                        observed = []
                        with self.assertRaises(CandidateWorkflowError) as failure:
                            run_candidate_workflow(plan, sys.executable, stage_executor=self.native_fake_executor(observed),
                                reuse_parent=parent, reuse_through="comsol_candidate")
                        self.assertEqual(observed, ["static_inputs"])
                        self.assertNotEqual(str(failure.exception), "")
                        if direct:
                            self.assertIn("legacy writer completion is unconfirmed", str(failure.exception))
                    self.assertEqual(changed_parent, {p:p.read_bytes() for p in changed_parent})
                    # Restore only this explicitly synthetic fixture between cases;
                    # production conversion never writes its parent.
                    (parent / ".run_terminal_publication.json").unlink(missing_ok=True)
                    for path, content in originals.items():
                        path.write_bytes(content)
