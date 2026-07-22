"""Materialize and finalize one isolated oa-TOF candidate run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import load_json, sha256


FORMAL_BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
TERMINAL_STATUSES = {"success", "failed", "interrupted"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _file_record(path: Path, recorded_path: Path | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(recorded_path or path), "exists": path.is_file()}
    if path.is_file():
        record.update(bytes=path.stat().st_size, sha256=_hash_file(path))
    return record


def _rewrite_paths(value: Any, old_root: Path, new_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_paths(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_paths(item, old_root, new_root) for item in value]
    if isinstance(value, str):
        try:
            relative = Path(value).resolve().relative_to(old_root.resolve())
        except (OSError, ValueError):
            return value
        return str(new_root / relative)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _output_files(run_root: Path) -> list[Path]:
    excluded = {run_root / "run_config.json", run_root / "run_manifest.json"}
    return sorted(
        path for path in run_root.rglob("*")
        if path.is_file() and path not in excluded and not path.is_relative_to(run_root / "inputs")
    )


def _write_manifest(run_root: Path, status: str, recorded_root: Path | None = None) -> dict[str, Any]:
    recorded_root = recorded_root or run_root
    config_path = run_root / "run_config.json"
    config = load_json(config_path)
    inputs = {}
    for key, value in config.get("inputs", {}).items():
        if not isinstance(value, str):
            continue
        recorded_path = Path(value)
        try:
            actual_path = run_root / recorded_path.resolve().relative_to(recorded_root.resolve())
        except ValueError:
            actual_path = recorded_path
        inputs[key] = _file_record(actual_path, recorded_path)
    outputs = []
    for path in _output_files(run_root):
        outputs.append(_file_record(path, recorded_root / path.relative_to(run_root)))
    manifest = {
        "schema_version": 1,
        "role": "simulation_run_manifest",
        "run_id": config["run_id"],
        "project": "oa_tof",
        "mode": "design_candidate",
        "status": status,
        "recorded_at_utc": _utc_now(),
        "run_config": _file_record(config_path, recorded_root / "run_config.json"),
        "inputs": inputs,
        "outputs": outputs,
        "formal_eligible": False,
        "promotion_authorized": False,
    }
    _write_json(run_root / "run_manifest.json", manifest)
    return manifest


def _summary(status: str, stage_results: list[dict[str, Any]], failure_stage: str | None = None) -> dict[str, Any]:
    if status == "success":
        if not stage_results or any(item.get("status") != "success" for item in stage_results):
            raise ValueError("success requires every declared candidate stage to be successful")
        decision = "candidate_accepted_not_promoted"
    elif status == "failed":
        decision = "candidate_rejected"
    else:
        decision = "no_candidate_decision"
    return {
        "schema_version": 1,
        "role": "oa_tof_candidate_run_summary",
        "status": status,
        "candidate_decision": decision,
        "acceptance_scope": "structural_build_and_contract" if status == "success" else None,
        "performance_claim_allowed": False,
        "failure_stage": failure_stage,
        "stages": stage_results,
        "formal_modified": False,
        "promotion_authorized": False,
        "safe_to_promote": False,
        "recorded_at_utc": _utc_now(),
    }


def start_candidate_run(plan_path: Path) -> Path:
    plan_path = plan_path.resolve()
    plan = load_json(plan_path)
    if plan.get("role") != "oa_tof_candidate_run_plan":
        raise ValueError("input is not an oa-TOF candidate run plan")
    run_id = plan["run_id"]
    validate_run_id(run_id)
    planning_root = Path(plan["planning_root"]).resolve()
    run_root = Path(plan["run_root"]).resolve()
    if plan_path != planning_root / "candidate_workflow_plan.json":
        raise ValueError("candidate plan is not located at its declared planning root")
    if run_root.parent.name != "runs" or run_root.name != run_id:
        raise ValueError("candidate run root does not match runs/<run_id>")
    if run_root.exists():
        raise FileExistsError(f"candidate run already exists: {run_root}")
    if plan["formal_root"].get("mutation_allowed") or plan["promotion"].get("included"):
        raise ValueError("candidate plan requests forbidden formal mutation or promotion")
    if plan["formal_baseline_sha256_at_planning"].lower() != sha256(FORMAL_BASELINE_PATH).lower():
        raise ValueError("formal baseline changed after candidate planning; regenerate the plan")
    config_template = load_json(planning_root / "run_config.template.json")
    for key, value in config_template.get("inputs", {}).items():
        expected = config_template.get("input_sha256", {}).get(key, "")
        if not expected or sha256(Path(value)).lower() != expected.lower():
            raise ValueError(f"planned candidate input changed before run start: {key}")
    consumption = load_json(planning_root / "inputs" / "prepared_consumers" / "candidate_consumption_plan.json")
    contract_record = consumption.get("candidate_contract", {})
    consumer_contract_path = Path(contract_record.get("path", ""))
    if (not consumer_contract_path.is_file() or
            sha256(consumer_contract_path).lower() != contract_record.get("sha256", "").lower()):
        raise ValueError("prepared candidate consumer contract changed before run start")
    for key, record in consumption.get("consumers", {}).get("simion", {}).get("generated", {}).items():
        generated_path = Path(record.get("path", ""))
        if not generated_path.is_file() or sha256(generated_path).lower() != record.get("sha256", "").lower():
            raise ValueError(f"prepared SIMION candidate text changed before run start: {key}")

    staging = planning_root / "materialized_run"
    if staging.exists():
        raise FileExistsError(f"candidate materialization staging already exists: {staging}")
    staging.mkdir()
    for name in ("inputs", "comsol", "simion", "cad", "results", "logs"):
        (staging / name).mkdir()
    shutil.copytree(planning_root / "inputs", staging / "inputs", dirs_exist_ok=True)

    runtime_plan = _rewrite_paths(plan, planning_root, run_root)
    runtime_plan["status"] = "RUNNING"
    runtime_plan["started_at_utc"] = _utc_now()
    _write_json(staging / "candidate_workflow_plan.json", runtime_plan)

    run_config = _rewrite_paths(config_template, planning_root, run_root)
    run_config["started_at_utc"] = runtime_plan["started_at_utc"]
    _write_json(staging / "run_config.json", run_config)

    consumption_path = staging / "inputs" / "prepared_consumers" / "candidate_consumption_plan.json"
    if consumption_path.is_file():
        _write_json(consumption_path, _rewrite_paths(load_json(consumption_path), planning_root, run_root))

    provisional = _summary(
        "interrupted",
        [{"stage_id": "orchestration", "status": "interrupted"}],
        "orchestration_not_completed",
    )
    _write_json(staging / "summary.json", provisional)
    _write_manifest(staging, "interrupted", run_root)
    run_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, run_root)
    return run_root


def finalize_candidate_run(
    run_root: Path,
    status: str,
    stage_results: list[dict[str, Any]],
    failure_stage: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_root = run_root.resolve()
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"unsupported candidate terminal status: {status}")
    config = load_json(run_root / "run_config.json")
    if run_root.name != config.get("run_id"):
        raise ValueError("run folder and run_config run_id differ")
    runtime_plan = load_json(run_root / "candidate_workflow_plan.json")
    expected_stages = [item["stage_id"] for item in runtime_plan["stages"]]
    actual_stages = [item.get("stage_id") for item in stage_results]
    if actual_stages != expected_stages:
        raise ValueError("stage results must cover every workflow stage in declared order")
    if status != "success" and not failure_stage:
        raise ValueError("failed or interrupted candidate runs require failure_stage")
    summary = _summary(status, stage_results, failure_stage)
    _write_json(run_root / "summary.json", summary)
    manifest = _write_manifest(run_root, status)
    return summary, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("plan", type=Path)
    finish = subparsers.add_parser("finalize")
    finish.add_argument("run_root", type=Path)
    finish.add_argument("--status", required=True, choices=sorted(TERMINAL_STATUSES))
    finish.add_argument("--stages", required=True, type=Path)
    finish.add_argument("--failure-stage")
    args = parser.parse_args()
    if args.command == "start":
        print(f"CANDIDATE_RUN_START=PASS RUN_ROOT={start_candidate_run(args.plan)}")
    else:
        stages = load_json(args.stages)
        summary, _ = finalize_candidate_run(args.run_root, args.status, stages, args.failure_stage)
        print(f"CANDIDATE_RUN_FINALIZE=PASS STATUS={summary['status']}")


if __name__ == "__main__":
    main()
