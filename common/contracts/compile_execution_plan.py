"""Compile a solver-neutral design plan into a non-executing command preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from artifact_naming import validate_run_id
from machine_contracts import REPO_ROOT, load_json, sha256, validate_schema


class PreserveMissing(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _operating_point_key(point: dict[str, Any]) -> tuple[float, str, int]:
    return (float(point["mass"]["value"]), point["mass"]["unit"], int(point["charge_state"]))


def compile_execution(
    plan_path: Path,
    registry_path: Path,
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    bindings = bindings or {}
    plan_path = plan_path.resolve()
    registry_path = registry_path.resolve()
    plan = load_json(plan_path)
    registry = load_json(registry_path)
    validate_schema(registry, "project_registry.schema.json")
    if plan.get("role") != "solver_neutral_design_plan":
        raise ValueError("input is not a solver-neutral design plan")
    if plan["provenance"]["request"]["sha256"] != sha256(Path(plan["provenance"]["request"]["path"])):
        raise ValueError("design request changed after planning; regenerate the design plan")
    if plan["provenance"]["project_registry"]["sha256"] != sha256(registry_path):
        raise ValueError("project registry changed after planning; regenerate the design plan")

    project = next((item for item in registry["projects"] if item["project_id"] == plan["project_id"]), None)
    if project is None:
        raise ValueError(f"planned project is absent from registry: {plan['project_id']}")
    project_root = REPO_ROOT / "projects" / project["project_id"]
    execution_relative = project["contracts"]["execution"]
    if execution_relative is None:
        return {
            "schema_version": 1, "role": "execution_dry_run", "status": "NEEDS_IMPLEMENTATION",
            "safe_to_execute": False, "project_id": project["project_id"], "profile_id": None,
            "blockers": ["Project has no execution profile contract"], "commands": []
        }
    execution_path = project_root / execution_relative
    execution = load_json(execution_path)
    validate_schema(execution, "execution_profiles.schema.json")
    profile = next((item for item in execution["profiles"] if
                    item["capability_id"] == plan["capability_id"] and item["mode"] == plan["mode"]), None)
    if profile is None:
        return {
            "schema_version": 1, "role": "execution_dry_run", "status": "NEEDS_IMPLEMENTATION",
            "safe_to_execute": False, "project_id": project["project_id"], "profile_id": None,
            "blockers": [f"No execution profile for {plan['capability_id']}/{plan['mode']}"], "commands": []
        }

    implementation_blockers = []
    if plan["requested_evidence_level"] not in profile["evidence_levels"]:
        implementation_blockers.append(f"Evidence level is not supported: {plan['requested_evidence_level']}")
    supported_points = {_operating_point_key(point) for point in profile["supported_operating_points"]}
    missing_points = [_operating_point_key(point) for point in plan["operating_points"] if _operating_point_key(point) not in supported_points]
    if missing_points:
        implementation_blockers.append("Unsupported operating points: " + ", ".join(f"{m:g} {u}, z={z}" for m, u, z in missing_points))
    missing_variables = sorted(set(plan["design_variables"]) - set(profile["supported_design_variables"]))
    if missing_variables:
        implementation_blockers.append("Runner cannot consume design variables: " + ", ".join(missing_variables))
    requested_constraints = {item["parameter"] for item in plan["constraints"]}
    missing_constraints = sorted(requested_constraints - set(profile["supported_constraints"]))
    if missing_constraints:
        implementation_blockers.append("Runner cannot enforce constraints: " + ", ".join(missing_constraints))
    missing_outputs = sorted(set(plan["required_outputs"]) - set(profile["deliverable_outputs"]))
    if missing_outputs:
        implementation_blockers.append("Runner cannot deliver outputs: " + ", ".join(missing_outputs))
    missing_bindings = sorted(set(profile["required_bindings"]) - set(bindings))

    stamp = validate_run_id(plan["run_id"])["stamp"]
    context: dict[str, str] = {"timestamp": stamp or "", "python_exe": str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")}
    context.update(bindings)
    for step in profile["steps"]:
        if step["run_id_template"]:
            generated = step["run_id_template"].format_map(PreserveMissing(context))
            validate_run_id(generated)
            context[f"{step['step_id']}_run_id"] = generated

    commands = []
    for step in profile["steps"]:
        entrypoint = (project_root / step["entrypoint"]).resolve()
        arguments = [value.format_map(PreserveMissing(context)) for value in step["arguments"]]
        launcher = ["powershell.exe", "-NoProfile", "-File"] if step["shell"] == "powershell" else [context["python_exe"]]
        commands.append({
            "step_id": step["step_id"], "kind": step["kind"], "shell": step["shell"],
            "entrypoint": str(entrypoint), "argv": launcher + [str(entrypoint)] + arguments,
            "run_id": context.get(f"{step['step_id']}_run_id"),
        })

    blockers = implementation_blockers.copy()
    if missing_bindings:
        blockers.append("Missing runtime bindings: " + ", ".join(missing_bindings))
    if plan["request_status"] != "approved":
        blockers.append(f"Request status is {plan['request_status']}; solver execution requires approved")
    if implementation_blockers:
        status = "NEEDS_IMPLEMENTATION"
    elif missing_bindings:
        status = "NEEDS_RUNTIME_INPUTS"
    elif plan["request_status"] != "approved":
        status = "AWAITING_APPROVAL"
    else:
        status = "EXECUTION_READY"
    return {
        "schema_version": 1,
        "role": "execution_dry_run",
        "status": status,
        "safe_to_execute": status == "EXECUTION_READY",
        "project_id": project["project_id"],
        "capability_id": plan["capability_id"],
        "mode": plan["mode"],
        "profile_id": profile["profile_id"],
        "execution_contract": {"path": str(execution_path), "sha256": sha256(execution_path)},
        "blockers": blockers,
        "limitations": profile["limitations"],
        "commands": commands,
    }


def parse_bindings(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"binding must be KEY=VALUE: {value}")
        key, item = value.split("=", 1)
        if not key or not item or key in result:
            raise ValueError(f"invalid or duplicate binding: {value}")
        result[key] = item
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_plan", type=Path)
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "config" / "project_registry.json")
    parser.add_argument("--bind", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = compile_execution(args.design_plan, args.registry, parse_bindings(args.bind))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
