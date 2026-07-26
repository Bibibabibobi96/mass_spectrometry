"""Prepare, but never execute or publish, one oa-TOF Formal vNext run.

Formal vNext begins from a successful isolated Candidate run.  This module
freezes the Candidate's non-Formal evidence into a scratch plan for a future
N=1000 COMSOL/SIMION/CAD execution.  It deliberately has no solver launch,
Formal-asset read, lifecycle mutation, or promotion capability.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id, validate_task_id
from common.contracts.machine_contracts import load_json, sha256
from projects.oa_tof.analysis.candidate_source_closure import verify_candidate_source_closure


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_ARTIFACT_ROOT = WORKSPACE_ROOT / "artifacts" / "projects" / "oa_tof"
REQUIRED_CANDIDATE_INPUTS = (
    "candidate_baseline.json",
    "candidate_resolved_geometry.json",
    "candidate_solver_numerics.json",
)
FORBIDDEN_SOURCE_SEGMENTS = frozenset({"formal", "archive", "history"})


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _assert_nonformal_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if any(part.lower() in FORBIDDEN_SOURCE_SEGMENTS for part in resolved.parts):
        raise ValueError(f"{label} must not reference Formal, archive, or history: {resolved}")
    return resolved


def _record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def _candidate_evidence(candidate_root: Path, summary: dict[str, Any]) -> dict[str, Path]:
    stages = {item.get("stage_id"): item for item in summary.get("stages", [])}
    expected = {
        "comsol_model": ("comsol_candidate", "model"),
        "simion_iob": ("simion_candidate", "iob"),
        "simion_ion_n100": ("simion_candidate", "ion_n100"),
        "simion_transport": ("simion_candidate", "transport_summary"),
        "cad_report": ("cad_candidate", "cad_report"),
        "acceptance": ("cross_solver_acceptance", "acceptance"),
    }
    result: dict[str, Path] = {}
    for label, (stage_id, key) in expected.items():
        stage = stages.get(stage_id, {})
        if stage.get("status") != "success":
            raise ValueError(f"Candidate stage is not successful: {stage_id}")
        path = Path(stage.get("evidence", {}).get(key, ""))
        if not path.is_file() or not _inside(path, candidate_root):
            raise ValueError(f"Candidate evidence is missing or escapes its run: {label}")
        result[label] = _assert_nonformal_path(path, label)
    return result


def _validate_candidate(candidate_root: Path, artifact_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    runs_root = artifact_root / "runs"
    if candidate_root.parent != runs_root:
        raise ValueError("Formal vNext requires a direct artifacts/runs/<candidate-run-id> input")
    _assert_nonformal_path(candidate_root, "candidate run")
    config = load_json(candidate_root / "run_config.json")
    summary = load_json(candidate_root / "summary.json")
    manifest = load_json(candidate_root / "run_manifest.json")
    plan = load_json(candidate_root / "candidate_workflow_plan.json")
    if (
        config.get("role") != "oa_tof_candidate_run_config"
        or config.get("project") != "oa_tof"
        or config.get("mode") != "design_candidate"
        or config.get("formal_gate_passed") is not False
        or config.get("promotion_authorized") is not False
    ):
        raise ValueError("source run is not an isolated oa-TOF Candidate run")
    if (
        summary.get("role") != "oa_tof_candidate_run_summary"
        or summary.get("status") != "success"
        or summary.get("candidate_decision") != "candidate_accepted_not_promoted"
        or summary.get("formal_modified") is not False
        or summary.get("promotion_authorized") is not False
    ):
        raise ValueError("Candidate run is not a successful non-promoted acceptance")
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != "oa_tof"
        or manifest.get("mode") != "design_candidate"
        or manifest.get("formal_eligible") is not False
        or manifest.get("promotion_authorized") is not False
    ):
        raise ValueError("Candidate manifest is not a successful non-Formal record")
    if plan.get("formal_root", {}).get("mutation_allowed") or plan.get("promotion", {}).get("included"):
        raise ValueError("Candidate plan permits a forbidden Formal mutation or promotion")
    verify_candidate_source_closure(plan.get("execution_source_closure", {}))
    evidence = _candidate_evidence(candidate_root, summary)
    acceptance = load_json(evidence["acceptance"])
    if (
        acceptance.get("role") != "oa_tof_candidate_acceptance"
        or acceptance.get("status") != "success"
        or acceptance.get("formal_modified") is not False
        or acceptance.get("promotion_authorized") is not False
    ):
        raise ValueError("Candidate acceptance is not valid vNext preflight evidence")
    return plan, config, evidence


def prepare_formal_vnext(
    candidate_run: Path,
    run_id: str,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> dict[str, Any]:
    """Freeze one successful Candidate as a non-executable Formal vNext plan."""
    identity = validate_run_id(run_id)
    artifact_root = artifact_root.resolve()
    candidate_root = candidate_run.resolve()
    plan, config, evidence = _validate_candidate(candidate_root, artifact_root)
    task_id = f"{identity['stamp']}__cross__formal-vnext-plan-{sha256(candidate_root / 'run_manifest.json')[:8].lower()}"
    validate_task_id(task_id)
    planning_root = artifact_root / "scratch" / task_id
    planned_run_root = artifact_root / "runs" / run_id
    if planning_root.exists() or planned_run_root.exists():
        raise FileExistsError("Formal vNext planning or target run already exists; overwrite is forbidden")

    inputs_root = planning_root / "inputs"
    inputs_root.mkdir(parents=True)
    frozen_inputs: dict[str, dict[str, object]] = {}
    for name in REQUIRED_CANDIDATE_INPUTS:
        source = candidate_root / "inputs" / name
        _assert_nonformal_path(source, name)
        if not source.is_file():
            raise FileNotFoundError(f"Candidate input required for vNext is absent: {name}")
        target = inputs_root / name
        shutil.copy2(source, target)
        frozen_inputs[name] = _record(target)
    for name in ("layout.iob", "layout.con"):
        source = candidate_root / "inputs" / "simion_template" / name
        _assert_nonformal_path(source, f"SIMION template {name}")
        if not source.is_file():
            raise FileNotFoundError(f"Candidate non-Formal SIMION template is absent: {name}")
        target = inputs_root / "simion_template" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        frozen_inputs[f"simion_template_{name}"] = _record(target)
    for name in ("oatof_resolved.lua", "oatof_ideal_grounded.lua", "oatof_ideal_grounded.fly2"):
        source = candidate_root / "inputs" / "prepared_consumers" / "simion" / name
        _assert_nonformal_path(source, f"SIMION text {name}")
        if not source.is_file():
            raise FileNotFoundError(f"Candidate SIMION text is absent: {name}")
        target = inputs_root / "simion_text" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        frozen_inputs[f"simion_text_{name}"] = _record(target)

    source_closure = plan["execution_source_closure"]
    source_code = Path(source_closure["code_root"])
    target_code = inputs_root / "code"
    shutil.copytree(source_code, target_code)
    frozen_closure = {**source_closure, "code_root": str(target_code)}
    verify_candidate_source_closure(frozen_closure)

    run_instance = config.get("run_instance", {})
    seed = run_instance.get("particle_source_seed")
    if not isinstance(seed, int):
        raise ValueError("Candidate run lacks an explicit integer particle-source seed")
    plan_record = {
        "schema_version": 1,
        "role": "oa_tof_formal_vnext_plan",
        "status": "prepared_not_executed",
        "project": "oa_tof",
        "mode": "formal_vnext_revalidation",
        "run_id": run_id,
        "planned_run_root": str(planned_run_root),
        "candidate_source": {
            "run_root": str(candidate_root),
            "run_manifest": _record(candidate_root / "run_manifest.json"),
            "summary": _record(candidate_root / "summary.json"),
            "evidence": {key: _record(path) for key, path in evidence.items()},
        },
        "inputs": frozen_inputs,
        "execution_source_closure": frozen_closure,
        "run_instance": {"particle_source_seed": seed, "particle_count": 1000},
        "formal_asset_read_allowed": False,
        "formal_asset_mutation_allowed": False,
        "promotion": {
            "included": False,
            "authorized": False,
            "required_after_success": [
                "owner_approval",
                "separate_promotion_transaction",
                "atomic_formal_publish",
            ],
        },
        "stages": [
            {"stage_id": "freeze_n1000_particle_table", "status": "not_run", "particles": 1000},
            {"stage_id": "comsol_n1000_gui_reopen", "status": "not_run"},
            {"stage_id": "simion_n1000_gui_runtime", "status": "not_run", "trajectory_quality": 8},
            {"stage_id": "cad_solidworks_2022_sync", "status": "not_run"},
            {"stage_id": "cross_solver_particle_analysis", "status": "not_run", "paired_particle_ids_required": True},
            {"stage_id": "gui_cad_reopen", "status": "not_run"},
            {"stage_id": "promotion_transaction_preflight", "status": "not_run", "promotion_authorized": False},
        ],
        "execution_boundary": "This plan is not a solver run, Formal gate, promotion transaction, or publication.",
    }
    _write_json(planning_root / "formal_vnext_plan.json", plan_record)
    return plan_record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-run", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = prepare_formal_vnext(args.candidate_run, args.run_id)
    print(f"FORMAL_VNEXT_PREPARE=PASS PLAN_ROOT={Path(result['planned_run_root']).parent.parent / 'scratch'}")


if __name__ == "__main__":
    main()
