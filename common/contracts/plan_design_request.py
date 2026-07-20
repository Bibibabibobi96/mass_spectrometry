"""Turn a READY design request into a traceable, solver-neutral execution plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from artifact_naming import validate_run_id
from machine_contracts import REPO_ROOT, load_json, sha256
from validate_design_request import validate_request


def build_plan(request_path: Path, registry_path: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_run_id(run_id)
    request_path = request_path.resolve()
    registry_path = registry_path.resolve()
    request = load_json(request_path)
    registry = load_json(registry_path)
    selection = validate_request(request, registry)
    if selection["status"] != "READY":
        raise ValueError(f"request is not READY: {selection['status']}: {'; '.join(selection['messages'])}")

    selected_project = next(p for p in registry["projects"] if p["project_id"] == selection["selected_project_id"])
    selected_capability = next(c for c in selected_project["capabilities"] if c["capability_id"] == selection["selected_capability_id"])
    mode = request["target"]["mode"] or (selected_capability["modes"][0] if selected_capability["modes"] else "design")
    provenance = {
        "request": {"path": str(request_path), "sha256": sha256(request_path)},
        "project_registry": {"path": str(registry_path), "sha256": sha256(registry_path)},
    }
    actions = [
        {"order": 1, "action": "freeze_request", "gate": "design_request_validation"},
        {"order": 2, "action": "resolve_project_contracts", "gate": "project_static"},
        {"order": 3, "action": "execute_selected_mode", "gate": request["evidence_level"]},
        {"order": 4, "action": "evaluate_objectives_and_constraints", "gate": "validation_report"},
        {"order": 5, "action": "package_requested_outputs", "gate": "manifest"},
    ]
    plan = {
        "schema_version": 1,
        "role": "solver_neutral_design_plan",
        "run_id": run_id,
        "request_id": request["request_id"],
        "request_status": request["status"],
        "project_id": selected_project["project_id"],
        "capability_id": selected_capability["capability_id"],
        "mode": mode,
        "requested_evidence_level": request["evidence_level"],
        "operating_points": request["operating_points"],
        "objectives": request["objectives"],
        "constraints": request["constraints"],
        "design_variables": request["design_variables"],
        "required_outputs": request["required_outputs"],
        "actions": actions,
        "provenance": provenance,
    }
    run_config = {
        "schema_version": 1,
        "role": "design_request_planning_run_config",
        "run_id": run_id,
        "project": selected_project["project_id"],
        "mode": mode,
        "capability_id": selected_capability["capability_id"],
        "evidence_level": request["evidence_level"],
        "inputs": {
            "design_request": str(request_path),
            "project_registry": str(registry_path),
        },
        "required_outputs": request["required_outputs"],
        "formal_gate_passed": False,
    }
    return plan, run_config


def write_plan(request_path: Path, registry_path: Path, run_id: str, output_dir: Path) -> tuple[Path, Path]:
    plan, run_config = build_plan(request_path, registry_path, run_id)
    output_dir.mkdir(parents=True, exist_ok=False)
    plan_path = output_dir / "design_plan.json"
    config_path = output_dir / "run_config.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps(run_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan_path, config_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "config" / "project_registry.json")
    args = parser.parse_args()
    try:
        plan_path, config_path = write_plan(args.request, args.registry, args.run_id, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"DESIGN_PLAN=PASS PLAN={plan_path.resolve()} RUN_CONFIG={config_path.resolve()}")


if __name__ == "__main__":
    main()
