"""Freeze an isolated oa-TOF candidate run and compile its ordered workflow."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
from common.contracts.artifact_naming import validate_run_id, validate_task_id
from common.contracts.machine_contracts import load_json, sha256, validate_schema
from projects.oa_tof.workflows.design_candidate.prepare_candidate_consumers import prepare as prepare_consumers
from projects.oa_tof.analysis.candidate_source_closure import (
    freeze_candidate_source_closure,
    frozen_source_path,
)


WORKFLOW_PATH = PROJECT_ROOT / "config" / "candidate_workflow.json"
FORMAL_BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
FORMAL_RESOLVED_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"
FORMAL_NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"


def validate_workflow(workflow: dict) -> None:
    if workflow.get("role") != "oa_tof_candidate_workflow_contract":
        raise ValueError("unsupported candidate workflow contract")
    stages = workflow.get("stages", [])
    identifiers = [stage["stage_id"] for stage in stages]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("candidate workflow has duplicate stage identifiers")
    seen: set[str] = set()
    for stage in stages:
        missing = set(stage.get("depends_on", [])) - seen
        if missing:
            raise ValueError(f"stage {stage['stage_id']} has forward or missing dependencies: {sorted(missing)}")
        seen.add(stage["stage_id"])
        if not stage.get("failure_stops_workflow"):
            raise ValueError(f"candidate stage must fail closed: {stage['stage_id']}")
    policy = workflow.get("formal_policy", {})
    if not policy.get("formal_is_read_only_during_candidate_run") or policy.get("automatic_promotion"):
        raise ValueError("candidate workflow must keep formal read-only and disable automatic promotion")
    if not workflow.get("promotion_is_not_a_workflow_stage") or "promotion" in seen:
        raise ValueError("promotion must be a separate approved run")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _provenance_path(record: dict, base: Path, label: str) -> Path:
    path = Path(record.get("path", ""))
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    expected = record.get("sha256", "")
    if not path.is_file() or not expected or sha256(path).lower() != expected.lower():
        raise ValueError(f"candidate {label} provenance is missing or changed")
    return path


def _candidate_sources(candidate_baseline: Path, candidate_resolved: Path, candidate_diff: Path) -> dict[str, Path]:
    baseline = candidate_baseline.resolve()
    resolved = candidate_resolved.resolve()
    diff = candidate_diff.resolve()
    report = load_json(diff)
    if report.get("role") != "oa_tof_candidate_contract_diff":
        raise ValueError("candidate diff has an unsupported role")
    provenance = report.get("provenance", {})
    proposal = _provenance_path(provenance.get("proposal", {}), diff.parent, "proposal")
    request = _provenance_path(provenance.get("request", {}), diff.parent, "request")
    proposal_contract = load_json(proposal)
    request_contract = load_json(request)
    numerics = resolved.parent / "candidate_solver_numerics.json"
    if not numerics.is_file():
        raise ValueError("candidate solver numerics contract is missing")
    if resolved_source := load_json(resolved):
        inputs = resolved_source.get("inputs", {})
        if inputs.get("solver_numerics_sha256", "").lower() != sha256(numerics).lower():
            raise ValueError("candidate solver numerics and resolved contract hashes do not match")
    validate_schema(proposal_contract, "candidate_proposal.schema.json")
    validate_schema(request_contract, "design_request.schema.json")
    proposal_request = proposal_contract["request"]
    proposal_request_path = Path(proposal_request["path"])
    if not proposal_request_path.is_absolute():
        proposal_request_path = proposal.parent / proposal_request_path
    if proposal_request_path.resolve() != request or proposal_request["sha256"].lower() != sha256(request).lower():
        raise ValueError("candidate proposal and request provenance do not match")
    if (
        report.get("candidate_id") != proposal_contract["candidate_id"]
        or report.get("request_id") != request_contract["request_id"]
    ):
        raise ValueError("candidate diff identity does not match its proposal/request")
    return {
        "candidate_baseline.json": baseline,
        "candidate_resolved_geometry.json": resolved,
        "candidate_solver_numerics.json": numerics,
        "candidate_diff.json": diff,
        "candidate_proposal.json": proposal,
        "design_request.json": request,
    }


def _registered_candidate_template(template_run: Path, artifact_project_root: Path) -> dict[str, Path]:
    """Return validated sources from one successful non-Formal layout registration."""
    run_root = template_run.resolve()
    runs_root = (artifact_project_root / "runs").resolve()
    if not _inside(run_root, runs_root) or run_root.parent != runs_root:
        raise ValueError("candidate SIMION template must be a direct artifacts/runs registration run")
    paths = {
        "run_config": run_root / "run_config.json",
        "summary": run_root / "summary.json",
        "manifest": run_root / "run_manifest.json",
        "runtime_report": run_root / "simion_layout_runtime_report.txt",
    }
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("candidate SIMION template registration evidence is incomplete")
    config = load_json(paths["run_config"])
    summary = load_json(paths["summary"])
    manifest = load_json(paths["manifest"])
    if (
        config.get("role") != "oa_tof_simion_candidate_layout_template_build"
        or config.get("project") != "oa_tof"
        or config.get("mode") != "candidate_layout_template_build"
        or config.get("run_id") != run_root.name
        or config.get("template_role") != "oa_tof_candidate_simion_layout_template"
    ):
        raise ValueError("candidate SIMION template registration has an unsupported identity")
    if (
        summary.get("role") != "oa_tof_simion_candidate_layout_template_build_summary"
        or summary.get("status") != "success"
        or not summary.get("runtime_structure_verified")
        or summary.get("particle_fly_executed")
        or summary.get("formal_modified")
        or manifest.get("status") != "success"
        or manifest.get("run_id") != run_root.name
    ):
        raise ValueError("candidate SIMION template registration is not a successful structure-only run")
    report = paths["runtime_report"].read_text(encoding="utf-8", errors="replace")
    if not all(token in report for token in ("STATUS=PASS", "INSTANCE_COUNT=4", "TEMPLATE_STRUCTURE_ONLY=true")):
        raise ValueError("candidate SIMION template runtime evidence is incomplete")
    inputs = config.get("inputs", {})
    hashes = config.get("input_sha256", {})
    manifest_inputs = manifest.get("inputs", {})
    result = {"registration_run": run_root, "registration_manifest": paths["manifest"]}
    for label, suffix in (("source_iob", ".iob"), ("source_con", ".con")):
        path = Path(inputs.get(label, "")).resolve()
        expected = str(hashes.get(label, ""))
        recorded = manifest_inputs.get(label, {})
        if (
            not path.is_file()
            or path.suffix.lower() != suffix
            or not expected
            or sha256(path).lower() != expected.lower()
            or str(recorded.get("path", "")) != str(path)
            or str(recorded.get("sha256", "")).lower() != expected.lower()
        ):
            raise ValueError(f"candidate SIMION template registration source changed: {label}")
        if any(segment in path.as_posix().lower().split("/") for segment in ("formal", "archive", "history")):
            raise ValueError("candidate SIMION template registration references a prohibited source path")
        result[label] = path
    if result["source_iob"].with_suffix(".con").name != result["source_con"].name:
        raise ValueError("candidate SIMION template registration bundle basenames do not match")
    return result


def prepare_candidate_run(
    candidate_baseline: Path,
    candidate_resolved: Path,
    candidate_diff: Path,
    run_id: str,
    artifact_project_root: Path | None = None,
    particle_source_seed: int = 20260713,
    simion_template_run: Path | None = None,
) -> dict:
    run_identity = validate_run_id(run_id)
    workflow = load_json(WORKFLOW_PATH)
    validate_workflow(workflow)
    artifact_project_root = (artifact_project_root or WORKSPACE_ROOT / "artifacts" / "projects" / "oa_tof").resolve()
    formal_root = artifact_project_root / "formal"
    run_root = artifact_project_root / "runs" / run_id
    task_id = f"{run_identity['stamp']}__cross__candidate-plan-{sha256(candidate_resolved.resolve())[:8].lower()}"
    validate_task_id(task_id)
    planning_root = artifact_project_root / "scratch" / task_id
    if run_root.exists():
        raise FileExistsError(f"candidate run already exists; overwrite is forbidden: {run_root}")
    if planning_root.exists():
        raise FileExistsError(f"candidate planning task already exists; overwrite is forbidden: {planning_root}")

    if not isinstance(particle_source_seed, int):
        raise ValueError("candidate run requires an explicit integer particle source seed")
    primary_sources = [candidate_baseline.resolve(), candidate_resolved.resolve(), candidate_diff.resolve()]
    if any(not path.is_file() for path in primary_sources):
        raise FileNotFoundError("candidate baseline, resolved contract, and diff must all exist")
    sources = _candidate_sources(candidate_baseline, candidate_resolved, candidate_diff)
    if any(_inside(path, formal_root) for path in sources.values()):
        raise ValueError("candidate inputs must not be sourced from formal artifacts")
    if (
        sources["candidate_baseline.json"] == FORMAL_BASELINE_PATH.resolve()
        or sources["candidate_resolved_geometry.json"] == FORMAL_RESOLVED_PATH.resolve()
        or sources["candidate_solver_numerics.json"] == FORMAL_NUMERICS_PATH.resolve()
    ):
        raise ValueError("candidate run requires isolated candidate contracts, not the formal project contracts")
    template_registration = (
        _registered_candidate_template(simion_template_run, artifact_project_root)
        if simion_template_run is not None
        else None
    )
    resolved_source = load_json(sources["candidate_resolved_geometry.json"])
    if resolved_source.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("candidate resolved contract has an unsupported role")
    if (
        resolved_source.get("inputs", {}).get("baseline_sha256", "").lower()
        != sha256(sources["candidate_baseline.json"]).lower()
    ):
        raise ValueError("candidate baseline and resolved contract hashes do not match")

    planning_root.mkdir(parents=True)
    inputs_dir = planning_root / "inputs"
    inputs_dir.mkdir()
    source_closure = freeze_candidate_source_closure(inputs_dir / "code", artifact_project_root)
    frozen_code_root = Path(source_closure["code_root"])
    frozen = {}
    for name, source in sources.items():
        target = inputs_dir / name
        shutil.copy2(source, target)
        frozen[name] = target
    frozen_template = None
    if template_registration is not None:
        template_dir = inputs_dir / "simion_template"
        template_dir.mkdir()
        frozen_template = {}
        for key, target_name in (("source_iob", "layout.iob"), ("source_con", "layout.con")):
            source = template_registration[key]
            target = template_dir / target_name
            shutil.copy2(source, target)
            frozen[f"candidate_simion_template_{key}"] = target
            frozen_template[key.removeprefix("source_")] = {"path": str(target), "sha256": sha256(target)}

    prepared_dir = inputs_dir / "prepared_consumers"
    consumption = prepare_consumers(frozen["candidate_resolved_geometry.json"], prepared_dir, run_root, particle_source_seed)
    resolved_contract = load_json(frozen["candidate_resolved_geometry.json"])
    source = resolved_contract["particle_source"]
    target = resolved_contract["validation_target"]
    comsol_model = Path(consumption["consumers"]["comsol"]["arguments"]["OutputModelPath"])
    candidate_ion = inputs_dir / "oatof_candidate_N100.ion"
    report_dir = run_root / "logs"
    workflow_plan = {
        "schema_version": 1,
        "role": "oa_tof_candidate_run_plan",
        "status": "NEEDS_CROSS_SOLVER_RUNNER",
        "run_id": run_id,
        "run_instance": {"particle_source_seed": particle_source_seed},
        "planning_root": str(planning_root),
        "run_root": str(run_root),
        "formal_root": {"path": str(formal_root), "mutation_allowed": False},
        "formal_baseline_sha256_at_planning": sha256(FORMAL_BASELINE_PATH),
        "candidate_inputs": {key: {"path": str(path), "sha256": sha256(path)} for key, path in frozen.items()},
        "execution_source_closure": source_closure,
        "stages": [
            {
                "stage_id": "static_inputs",
                "status": "prepared_except_particle_table",
                "prepared_outputs": [str(prepared_dir / "candidate_consumption_plan.json")],
                "pending_output": str(candidate_ion),
                "entrypoint": frozen_source_path(
                    source_closure,
                    "projects/oa_tof/simion/workbench/generate_comsol_consistent_ions.ps1",
                ),
                "arguments": {
                    "N": 100,
                    "MassAmu": target["mass_amu"],
                    "Charge": 1,
                    "EnergyMeanEv": target["initial_energy_mean_ev"],
                    "EnergyStdEv": target["initial_energy_sigma_ev"],
                    "HalfWidthXmm": source["size_x_mm"] / 2,
                    "HalfWidthYmm": source["size_y_mm"] / 2,
                    "HalfWidthZmm": source["size_z_mm"] / 2,
                    "CenterXmm": source["center_x_mm"],
                    "CenterYmm": source["center_y_mm"],
                    "CenterZmm": source["center_z_mm"],
                    "Seed": particle_source_seed,
                    "Output": str(candidate_ion),
                },
            },
            {
                "stage_id": "comsol_candidate",
                "status": "not_run",
                "contract_path": str(frozen["candidate_resolved_geometry.json"]),
                "model_path": str(comsol_model),
                "report_path": str(report_dir / "comsol_build.txt"),
                "entrypoint": frozen_source_path(source_closure, "common/comsol/run_comsol_r2025b.ps1"),
                "task_script": str(frozen_code_root / "projects/oa_tof/workflows/design_candidate/run_candidate_contract_build.m"),
                "environment": {
                    "OATOF_CANDIDATE_CONTRACT_PATH": str(frozen["candidate_resolved_geometry.json"]),
                    "OATOF_CANDIDATE_MODEL_PATH": str(comsol_model),
                    "OATOF_CANDIDATE_ION_PATH": str(candidate_ion),
                    "OATOF_RUNTIME_DIR": str(run_root / "comsol"),
                },
            },
            {
                "stage_id": "simion_candidate",
                "status": "ready" if frozen_template is not None else "blocked_requires_explicit_nonformal_template",
                "contract_path": str(frozen["candidate_resolved_geometry.json"]),
                "baseline_path": str(frozen["candidate_baseline.json"]),
                "text_dir": str(prepared_dir / "simion"),
                "output_dir": str(run_root / "simion"),
                "required_input": "runs/<run_id>/inputs/simion_template/ with role oa_tof_candidate_simion_layout_template and SHA-256 provenance",
                "formal_asset_read_allowed": False,
                **({
                    "template_input": {
                        "role": "oa_tof_candidate_simion_layout_template",
                        "files": frozen_template,
                        "registration_run": str(template_registration["registration_run"]),
                        "registration_manifest_sha256": sha256(template_registration["registration_manifest"]),
                    }
                } if frozen_template is not None and template_registration is not None else {}),
            },
            {
                "stage_id": "cad_candidate",
                "status": "blocked_until_comsol_success",
                "model_path": str(comsol_model),
                "output_dir": str(run_root / "cad"),
                "entrypoint": frozen_source_path(source_closure, "common/comsol/run_comsol_r2025b.ps1"),
                "task_script": str(frozen_code_root / "projects/oa_tof/workflows/design_candidate/run_candidate_cad_sync.m"),
            },
            {
                "stage_id": "cross_solver_acceptance",
                "status": "needs_integrated_candidate_runner",
                "output_dir": str(run_root / "results"),
            },
        ],
        "promotion": {
            "included": False,
            "automatic": False,
            "safe_to_promote": False,
            "required_separate_decision": True,
        },
        "limitations": [
            "This preparation step does not launch COMSOL, SIMION, or SolidWorks.",
            "Runtime stages must update summary and manifest evidence before acceptance.",
            "Acceptance never mutates baseline or formal assets; promotion is a separate approved workflow.",
        ],
    }
    stage_contracts = {stage["stage_id"]: stage for stage in workflow["stages"]}
    for stage in workflow_plan["stages"]:
        contract_stage = stage_contracts[stage["stage_id"]]
        stage["depends_on"] = contract_stage["depends_on"]
        stage["failure_stops_workflow"] = contract_stage["failure_stops_workflow"]
        for key in ("acceptance_scope", "performance_claim_allowed"):
            if key in contract_stage:
                stage[key] = contract_stage[key]
    (planning_root / "candidate_workflow_plan.json").write_text(
        json.dumps(workflow_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run_config = {
        "schema_version": 1,
        "role": "oa_tof_candidate_run_config",
        "run_id": run_id,
        "project": "oa_tof",
        "mode": "design_candidate",
        "run_instance": {"particle_source_seed": particle_source_seed},
        "project_root": str(PROJECT_ROOT),
        "inputs": {key: value["path"] for key, value in workflow_plan["candidate_inputs"].items()},
        "input_sha256": {key: value["sha256"] for key, value in workflow_plan["candidate_inputs"].items()},
        "formal_gate_passed": False,
        "promotion_authorized": False,
    }
    (planning_root / "run_config.template.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return workflow_plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-baseline", required=True, type=Path)
    parser.add_argument("--candidate-resolved", required=True, type=Path)
    parser.add_argument("--candidate-diff", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--particle-source-seed", required=True, type=int)
    parser.add_argument("--simion-template-run", type=Path)
    args = parser.parse_args()
    result = prepare_candidate_run(args.candidate_baseline, args.candidate_resolved, args.candidate_diff, args.run_id, particle_source_seed=args.particle_source_seed, simion_template_run=args.simion_template_run)
    print(f"CANDIDATE_RUN_PREPARE={result['status']} PLAN_ROOT={result['planning_root']} RUN_ROOT={result['run_root']}")


if __name__ == "__main__":
    main()
