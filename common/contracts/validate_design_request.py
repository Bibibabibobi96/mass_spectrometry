"""Validate a design request against the project capability registry."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from machine_contracts import ContractError, REPO_ROOT, load_json, validate_schema


MATURITY = {"prototype": 0, "static": 1, "candidate": 2, "formal": 3}
EVIDENCE = {"plan": 0, "static": 1, "candidate": 2, "formal": 3}
FORMAL_OUTPUTS = {"comsol_model", "simion_model", "cad"}


def _result(status: str, request: dict[str, Any] | None, messages: list[str],
            project: dict[str, Any] | None = None,
            capability: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "request_id": request.get("request_id") if request else None,
        "selected_project_id": project.get("project_id") if project else None,
        "selected_capability_id": capability.get("capability_id") if capability else None,
        "messages": messages,
    }


def _constraint_conflicts(constraints: list[dict[str, Any]]) -> list[str]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in constraints:
        groups.setdefault((item["parameter"], item["unit"]), []).append(item)
    conflicts = []
    for (parameter, unit), items in groups.items():
        lower = [(i["value"], i["operator"] == ">") for i in items if i["operator"] in (">=", ">", "=")]
        upper = [(i["value"], i["operator"] == "<") for i in items if i["operator"] in ("<=", "<", "=")]
        if lower and upper:
            low_value, low_open = max(lower)
            high_value, high_open = min(upper)
            if low_value > high_value or (low_value == high_value and (low_open or high_open)):
                conflicts.append(f"Contradictory bounds for {parameter} [{unit}]")
    return conflicts


def validate_request(request: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_schema(request, "design_request.schema.json")
    except ContractError as exc:
        return _result("NEEDS_CLARIFICATION", request, [str(exc)])

    if request["status"] == "retired":
        return _result("UNSUPPORTED", request, ["Retired requests cannot be planned"])
    if request["status"] == "approved" and request["approval"] is None:
        return _result("NEEDS_CLARIFICATION", request, ["Approved request requires approval metadata"])
    if request["approval"] is not None:
        try:
            date.fromisoformat(request["approval"]["approved_on"])
        except ValueError:
            return _result("NEEDS_CLARIFICATION", request, ["approval.approved_on must be an ISO calendar date"])
    if request["status"] != "approved" and request["evidence_level"] == "formal":
        return _result("NEEDS_CLARIFICATION", request, ["Formal evidence requires an approved request"])

    objective_errors = []
    for objective in request["objectives"]:
        operator, value = objective["operator"], objective["value"]
        if operator in (">=", "<=", "target") and value is None:
            objective_errors.append(f"Objective {objective['metric']} requires a numeric value")
        if operator in ("maximize", "minimize") and value is not None:
            objective_errors.append(f"Objective {objective['metric']} must omit a numeric value for {operator}")
        if operator == "target" and objective["tolerance"] is None:
            objective_errors.append(f"Target objective {objective['metric']} requires a tolerance")
    if objective_errors:
        return _result("NEEDS_CLARIFICATION", request, objective_errors)

    conflicts = _constraint_conflicts(request["constraints"])
    if conflicts:
        return _result("NEEDS_CLARIFICATION", request, conflicts)

    target = request["target"]
    family_projects = [p for p in registry["projects"] if p["family_id"] == target["family_id"]]
    if not family_projects:
        return _result("UNSUPPORTED", request, [f"Unknown design family: {target['family_id']}"])

    preferred = target["preferred_project_id"]
    if preferred:
        matches = [p for p in registry["projects"] if p["project_id"] == preferred]
        if not matches:
            return _result("NEEDS_NEW_PROJECT", request, [f"Preferred project does not exist: {preferred}"])
        project = matches[0]
        if project["family_id"] != target["family_id"]:
            return _result("NEEDS_CLARIFICATION", request, ["Preferred project belongs to another design family"])
        candidates = [project]
    else:
        candidates = family_projects

    selections = []
    for project in candidates:
        for capability in project["capabilities"]:
            if capability["function"] == target["function"]:
                selections.append((project, capability))
    if not selections:
        return _result("NEEDS_NEW_PROJECT", request, [f"No project implements function: {target['function']}"])
    selections.sort(key=lambda item: (MATURITY[item[1]["status"]], item[0]["project_id"]), reverse=True)
    project, capability = selections[0]

    mode = target["mode"]
    if mode is not None and mode not in capability["modes"]:
        return _result("NEEDS_PROJECT_COMPLETION", request, [f"Mode is not implemented: {mode}"], project, capability)

    missing_metrics = sorted({o["metric"] for o in request["objectives"]} - set(capability["metrics"]))
    missing_variables = sorted(set(request["design_variables"]) - set(capability["design_variables"]))
    messages = []
    if missing_metrics:
        messages.append("Unsupported metrics: " + ", ".join(missing_metrics))
    if missing_variables:
        messages.append("Unsupported design variables: " + ", ".join(missing_variables))
    required_rank = EVIDENCE[request["evidence_level"]]
    if MATURITY[capability["status"]] < required_rank:
        messages.append(f"Capability maturity {capability['status']} is below requested {request['evidence_level']}")
    if request["evidence_level"] == "formal":
        unavailable = sorted(set(request["required_outputs"]) & FORMAL_OUTPUTS - set(project["formal_assets"]["types"]))
        if unavailable:
            messages.append("Formal asset types unavailable: " + ", ".join(unavailable))
    if messages:
        return _result("NEEDS_PROJECT_COMPLETION", request, messages, project, capability)
    return _result("READY", request, ["Request is structurally and semantically ready"], project, capability)


def validate_path(request_path: Path, registry_path: Path) -> dict[str, Any]:
    try:
        request = load_json(request_path)
        registry = load_json(registry_path)
        validate_schema(registry, "project_registry.schema.json")
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        return _result("NEEDS_CLARIFICATION", None, [str(exc)])
    return validate_request(request, registry)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "config" / "project_registry.json")
    args = parser.parse_args()
    result = validate_path(args.request, args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
