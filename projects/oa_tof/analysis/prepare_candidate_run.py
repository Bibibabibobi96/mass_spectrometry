"""Freeze an isolated oa-TOF candidate run and compile its ordered workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
COMMON_CONTRACTS = REPO_ROOT / "common" / "contracts"
if str(COMMON_CONTRACTS) not in sys.path:
    sys.path.insert(0, str(COMMON_CONTRACTS))

from artifact_naming import validate_run_id, validate_task_id
from machine_contracts import load_json, sha256
from prepare_candidate_consumers import prepare as prepare_consumers


WORKFLOW_PATH = PROJECT_ROOT / "config" / "candidate_workflow.json"
FORMAL_BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
FORMAL_RESOLVED_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"


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


def prepare_candidate_run(
    candidate_baseline: Path,
    candidate_resolved: Path,
    candidate_diff: Path,
    run_id: str,
    artifact_project_root: Path | None = None,
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

    sources = [candidate_baseline.resolve(), candidate_resolved.resolve(), candidate_diff.resolve()]
    if any(not path.is_file() for path in sources):
        raise FileNotFoundError("candidate baseline, resolved contract, and diff must all exist")
    if any(_inside(path, formal_root) for path in sources):
        raise ValueError("candidate inputs must not be sourced from formal artifacts")
    if sources[0] == FORMAL_BASELINE_PATH.resolve() or sources[1] == FORMAL_RESOLVED_PATH.resolve():
        raise ValueError("candidate run requires isolated candidate contracts, not the formal project contracts")
    resolved_source = load_json(sources[1])
    if resolved_source.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("candidate resolved contract has an unsupported role")
    if resolved_source.get("inputs", {}).get("baseline_sha256", "").lower() != sha256(sources[0]).lower():
        raise ValueError("candidate baseline and resolved contract hashes do not match")

    planning_root.mkdir(parents=True)
    inputs_dir = planning_root / "inputs"
    inputs_dir.mkdir()
    frozen = {}
    for source, name in zip(sources, ("candidate_baseline.json", "candidate_resolved_geometry.json", "candidate_diff.json")):
        target = inputs_dir / name
        shutil.copy2(source, target)
        frozen[name] = target

    prepared_dir = inputs_dir / "prepared_consumers"
    consumption = prepare_consumers(frozen["candidate_resolved_geometry.json"], prepared_dir, run_root)
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
        "planning_root": str(planning_root),
        "run_root": str(run_root),
        "formal_root": {"path": str(formal_root), "mutation_allowed": False},
        "formal_baseline_sha256_at_planning": sha256(FORMAL_BASELINE_PATH),
        "candidate_inputs": {
            key: {"path": str(path), "sha256": sha256(path)} for key, path in frozen.items()
        },
        "stages": [
            {
                "stage_id": "static_inputs", "status": "prepared_except_particle_table",
                "prepared_outputs": [str(prepared_dir / "candidate_consumption_plan.json")],
                "pending_output": str(candidate_ion),
                "entrypoint": str(PROJECT_ROOT / "simion" / "workbench" / "generate_comsol_consistent_ions.ps1"),
                "arguments": {
                    "N": 100, "MassAmu": target["mass_amu"], "Charge": 1,
                    "EnergyMeanEv": target["initial_energy_mean_ev"],
                    "EnergyStdEv": target["initial_energy_sigma_ev"],
                    "HalfWidthXmm": source["size_x_mm"] / 2, "HalfWidthYmm": source["size_y_mm"] / 2,
                    "HalfWidthZmm": source["size_z_mm"] / 2, "CenterXmm": source["center_x_mm"],
                    "CenterYmm": source["center_y_mm"], "CenterZmm": source["center_z_mm"],
                    "Seed": source["seed"], "Output": str(candidate_ion),
                },
            },
            {
                "stage_id": "comsol_candidate", "status": "not_run",
                "contract_path": str(frozen["candidate_resolved_geometry.json"]),
                "model_path": str(comsol_model), "report_path": str(report_dir / "comsol_build.txt"),
                "entrypoint": str(REPO_ROOT / "common" / "comsol" / "run_comsol_r2025b.ps1"),
                "task_script": str(PROJECT_ROOT / "tests" / "comsol" / "run_candidate_contract_build.m"),
                "environment": {
                    "OATOF_CANDIDATE_CONTRACT_PATH": str(frozen["candidate_resolved_geometry.json"]),
                    "OATOF_CANDIDATE_MODEL_PATH": str(comsol_model),
                    "OATOF_CANDIDATE_ION_PATH": str(candidate_ion),
                    "OATOF_RUNTIME_DIR": str(run_root / "comsol"),
                },
            },
            {
                "stage_id": "simion_candidate", "status": "not_run",
                "contract_path": str(frozen["candidate_resolved_geometry.json"]),
                "baseline_path": str(frozen["candidate_baseline.json"]),
                "text_dir": str(prepared_dir / "simion"), "output_dir": str(run_root / "simion"),
                "entrypoint": str(PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1"),
                "candidate_mode_required": True,
            },
            {
                "stage_id": "cad_candidate", "status": "blocked_until_comsol_success",
                "model_path": str(comsol_model), "output_dir": str(run_root / "cad"),
                "entrypoint": str(REPO_ROOT / "common" / "comsol" / "run_comsol_r2025b.ps1"),
                "task_script": str(PROJECT_ROOT / "tests" / "cad" / "run_candidate_cad_sync.m"),
            },
            {
                "stage_id": "cross_solver_acceptance", "status": "needs_integrated_candidate_runner",
                "output_dir": str(run_root / "results"),
            },
        ],
        "promotion": {
            "included": False, "automatic": False, "safe_to_promote": False,
            "required_separate_decision": True,
        },
        "limitations": [
            "This preparation step does not launch COMSOL, SIMION, or SolidWorks.",
            "Runtime stages must update summary and manifest evidence before acceptance.",
            "Acceptance never mutates baseline or formal assets; promotion is a separate approved workflow."
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
        "schema_version": 1, "role": "oa_tof_candidate_run_config", "run_id": run_id,
        "project": "oa_tof", "mode": "design_candidate", "project_root": str(PROJECT_ROOT),
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
    args = parser.parse_args()
    result = prepare_candidate_run(
        args.candidate_baseline, args.candidate_resolved, args.candidate_diff, args.run_id
    )
    print(f"CANDIDATE_RUN_PREPARE={result['status']} PLAN_ROOT={result['planning_root']} RUN_ROOT={result['run_root']}")


if __name__ == "__main__":
    main()
