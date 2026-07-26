"""Materialize and stage a prepared oa-TOF Formal vNext run without promotion.

The module owns only lifecycle orchestration.  Solver work is injected through
``stage_executor`` so its order and failure behavior can be tested without
COMSOL, SIMION, or SolidWorks.  The default executor deliberately refuses to
launch commercial software; a future approved executor must be supplied as a
separate implementation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import load_json, sha256
from projects.oa_tof.analysis.candidate_source_closure import verify_candidate_source_closure


StageExecutor = Callable[[dict[str, Any], Path], dict[str, Any]]
STAGE_ORDER = (
    "freeze_n1000_particle_table",
    "comsol_n1000_gui_reopen",
    "simion_n1000_gui_runtime",
    "cad_solidworks_2022_sync",
    "cross_solver_particle_analysis",
    "gui_cad_reopen",
    "promotion_transaction_preflight",
)
FORBIDDEN_SEGMENTS = frozenset({"formal", "archive", "history"})


class FormalVnextExecutionError(RuntimeError):
    """A staged vNext run failed after its isolated run record was materialized."""

    def __init__(self, message: str, run_root: Path):
        super().__init__(message)
        self.run_root = run_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if any(part.lower() in FORBIDDEN_SEGMENTS for part in resolved.parts):
        raise ValueError(f"{label} must not reference Formal, archive, or history: {resolved}")
    return resolved


def _file_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def _verify_record(record: dict[str, Any], label: str) -> Path:
    path = Path(record.get("path", "")).resolve()
    expected = str(record.get("sha256", ""))
    if not path.is_file() or not expected or sha256(path).lower() != expected.lower():
        raise ValueError(f"Formal vNext frozen input changed or is missing: {label}")
    return _assert_nonformal_path(path, label)


def _validate_plan(plan_path: Path) -> tuple[dict[str, Any], Path, Path]:
    plan_path = plan_path.resolve()
    plan = load_json(plan_path)
    if plan.get("role") != "oa_tof_formal_vnext_plan" or plan.get("status") != "prepared_not_executed":
        raise ValueError("input is not a prepared oa-TOF Formal vNext plan")
    if plan_path.name != "formal_vnext_plan.json" or plan_path.parent.parent.name != "scratch":
        raise ValueError("Formal vNext plan must remain under artifacts scratch")
    run_root = Path(plan.get("planned_run_root", "")).resolve()
    validate_run_id(str(plan.get("run_id", "")))
    if run_root.parent.name != "runs" or run_root.name != plan["run_id"]:
        raise ValueError("Formal vNext target must be artifacts/runs/<run-id>")
    if run_root.exists():
        raise FileExistsError(f"Formal vNext target run already exists: {run_root}")
    if plan.get("formal_asset_read_allowed") or plan.get("formal_asset_mutation_allowed"):
        raise ValueError("Formal vNext staging must not read or mutate Formal assets")
    promotion = plan.get("promotion", {})
    if promotion.get("included") or promotion.get("authorized"):
        raise ValueError("promotion must remain a separate explicit post-vNext transaction")
    if tuple(stage.get("stage_id") for stage in plan.get("stages", [])) != STAGE_ORDER:
        raise ValueError("Formal vNext stages are incomplete or out of order")
    if plan.get("run_instance", {}).get("particle_count") != 1000:
        raise ValueError("Formal vNext requires the N=1000 statistical tier")
    for label, record in plan.get("inputs", {}).items():
        _verify_record(record, f"input:{label}")
    source = plan.get("candidate_source", {})
    for label in ("run_manifest", "summary"):
        _verify_record(source.get(label, {}), f"candidate:{label}")
    for label, record in source.get("evidence", {}).items():
        _verify_record(record, f"candidate-evidence:{label}")
    closure = plan.get("execution_source_closure", {})
    verify_candidate_source_closure(closure)
    return plan, plan_path.parent, run_root


def _summary(status: str, stage_results: list[dict[str, Any]], failure_stage: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "role": "oa_tof_formal_vnext_run_summary",
        "status": status,
        "formal_vnext_decision": "revalidated_not_promoted" if status == "success" else "no_formal_decision",
        "failure_stage": failure_stage,
        "stages": stage_results,
        "formal_modified": False,
        "promotion_authorized": False,
        "recorded_at_utc": _utc_now(),
    }


def _manifest(run_root: Path, status: str) -> dict[str, Any]:
    config = load_json(run_root / "run_config.json")
    outputs = [
        _file_record(path)
        for path in sorted(run_root.rglob("*"))
        if path.is_file() and not _inside(path, run_root / "inputs") and path.name != "run_manifest.json"
    ]
    result = {
        "schema_version": 1,
        "role": "simulation_run_manifest",
        "run_id": config["run_id"],
        "project": "oa_tof",
        "mode": "formal_vnext_revalidation",
        "status": status,
        "run_config": _file_record(run_root / "run_config.json"),
        "inputs": config["inputs"],
        "outputs": outputs,
        "formal_eligible": False,
        "promotion_authorized": False,
        "recorded_at_utc": _utc_now(),
    }
    _write_json(run_root / "run_manifest.json", result)
    return result


def _materialize(plan: dict[str, Any], planning_root: Path, run_root: Path) -> None:
    staging = planning_root / "materialized_formal_vnext_run"
    if staging.exists():
        raise FileExistsError(f"Formal vNext staging already exists: {staging}")
    staging.mkdir()
    for name in ("inputs", "comsol", "simion", "cad", "results", "logs"):
        (staging / name).mkdir()
    shutil.copytree(planning_root / "inputs", staging / "inputs", dirs_exist_ok=True)
    runtime_plan = {**plan, "status": "running", "started_at_utc": _utc_now()}
    _write_json(staging / "formal_vnext_plan.json", runtime_plan)
    config = {
        "schema_version": 1,
        "role": "oa_tof_formal_vnext_run_config",
        "project": "oa_tof",
        "mode": "formal_vnext_revalidation",
        "run_id": plan["run_id"],
        "run_instance": plan["run_instance"],
        "inputs": plan["inputs"],
        "candidate_source": plan["candidate_source"],
        "formal_gate_passed": False,
        "promotion_authorized": False,
        "formal_asset_read_allowed": False,
        "formal_asset_mutation_allowed": False,
    }
    _write_json(staging / "run_config.json", config)
    _write_json(staging / "summary.json", _summary("interrupted", [], "staging_not_completed"))
    _manifest(staging, "interrupted")
    run_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, run_root)


def _default_stage_executor(stage: dict[str, Any], run_root: Path) -> dict[str, Any]:
    del stage, run_root
    raise RuntimeError("Formal vNext commercial execution is intentionally not implemented by this lifecycle runner")


def _stage_result(stage_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("formal_modified") or evidence.get("promotion_authorized"):
        raise ValueError("Formal vNext stage attempted forbidden Formal mutation or promotion")
    return {"stage_id": stage_id, "status": "success", "evidence": evidence}


def run_formal_vnext(plan_path: Path, stage_executor: StageExecutor = _default_stage_executor) -> tuple[Path, dict[str, Any]]:
    """Materialize one isolated vNext run and execute injected stages in fixed order."""
    plan, planning_root, run_root = _validate_plan(plan_path)
    _materialize(plan, planning_root, run_root)
    results: list[dict[str, Any]] = []
    current = "orchestration"
    try:
        for stage in plan["stages"]:
            current = stage["stage_id"]
            evidence = stage_executor(stage, run_root)
            if not isinstance(evidence, dict):
                raise ValueError(f"Formal vNext stage returned non-record evidence: {current}")
            results.append(_stage_result(current, evidence))
        summary = _summary("success", results, None)
        _write_json(run_root / "summary.json", summary)
        _manifest(run_root, "success")
        return run_root, summary
    except Exception as exc:
        results.append({"stage_id": current, "status": "failed", "error": str(exc)})
        _write_json(run_root / "summary.json", _summary("failed", results, current))
        _manifest(run_root, "failed")
        raise FormalVnextExecutionError(str(exc), run_root) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        run_root, summary = run_formal_vnext(args.plan)
    except FormalVnextExecutionError as exc:
        print(f"FORMAL_VNEXT_RUN=FAIL RUN_ROOT={exc.run_root} ERROR={exc}")
        raise SystemExit(1) from exc
    print(f"FORMAL_VNEXT_RUN=PASS RUN_ROOT={run_root} DECISION={summary['formal_vnext_decision']}")


if __name__ == "__main__":
    main()
