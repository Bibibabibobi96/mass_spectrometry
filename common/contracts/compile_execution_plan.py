"""Compile a solver-neutral design plan into a non-executing command preview."""

from __future__ import annotations

import argparse
import importlib
import json
import hashlib
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.build_project_registry import query_capabilities, validate_runtime_binding
from common.contracts.machine_contracts import REPO_ROOT, load_json, sha256, validate_schema


class PreserveMissing(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _resolved_inputs(profile: dict[str, Any], project_root: Path,
                     bindings: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve actual small fixed definitions and validate declared caller input kinds."""
    unavailable = []
    for key, kind in profile.get("binding_types", {}).items():
        if key not in bindings:
            continue
        value = bindings[key]
        if kind == "file" and not Path(value).is_file():
            unavailable.append(f"{key}: file is missing: {value}")
        elif kind == "directory" and not Path(value).is_dir():
            unavailable.append(f"{key}: directory is missing: {value}")
        elif kind in {"integer", "number"}:
            try:
                parsed = int(value) if kind == "integer" else float(value)
                if not math.isfinite(parsed):
                    raise ValueError()
            except ValueError:
                unavailable.append(f"{key}: expected {kind}")
    resolved = []
    for name, relative in profile.get("fixed_inputs", {}).items():
        path = (project_root/relative).resolve()
        if not path.is_relative_to(project_root.resolve()) or not path.is_file():
            unavailable.append(f"{name}: fixed input is missing or outside its project: {relative}")
            continue
        data = path.read_bytes()
        resolved.append(dict(name=name, relative_path=relative, path=str(path), bytes=len(data),
                             sha256=hashlib.sha256(data).hexdigest().upper(), content=data.decode("utf-8")))
    return resolved, unavailable


def _binding_authorities(profile: dict[str, Any], bindings: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Bind small caller contracts; leave bare payload freezing to its existing owner."""
    records, payloads, definitions = [], [], []
    for key, kind in profile.get("binding_types", {}).items():
        if key not in bindings or kind != "file" or not Path(bindings[key]).is_file():
            continue
        path = Path(bindings[key]).resolve()
        if path.suffix.lower() != ".json":
            payloads.append(key)
            continue
        data = path.read_bytes()
        definitions.append((path.parent, json.loads(data.decode("utf-8-sig"))))
        records.append(dict(name=key, path=str(path), bytes=len(data),
                            sha256=hashlib.sha256(data).hexdigest().upper()))
    def contains_record(value: Any, base: Path, target: Path) -> bool:
        if isinstance(value, dict):
            if (isinstance(value.get("path"), str) and type(value.get("bytes")) is int and value["bytes"] >= 0
                    and isinstance(value.get("sha256"), str) and re.fullmatch(r"[A-Fa-f0-9]{64}", value["sha256"])):
                path = Path(value["path"])
                if (path if path.is_absolute() else base/path).resolve() == target:
                    return True
            return any(contains_record(child, base, target) for child in value.values())
        return isinstance(value, list) and any(contains_record(child, base, target) for child in value)
    unresolved = [key for key in payloads if not any(
        contains_record(value, base, Path(bindings[key]).resolve()) for base, value in definitions)]
    return records, unresolved


def _operating_point_key(point: dict[str, Any]) -> tuple[float, str, int]:
    return (float(point["mass"]["value"]), point["mass"]["unit"], int(point["charge_state"]))


def _resolve_runtime_binding(project: dict[str, Any], profile: dict[str, Any],
                             bindings: dict[str, str], *, request_path: Path) -> dict[str, Any]:
    """Resolve declared project selectors and validate the narrow execution context."""
    entrypoint = validate_runtime_binding(profile, REPO_ROOT / "projects" / project["project_id"])
    if entrypoint is None:
        return {}
    selection_keys = set(profile["runtime_binding"]["required_bindings"])
    if not selection_keys <= set(bindings):
        return {}
    for key in selection_keys:
        if not isinstance(bindings[key], str) or not bindings[key].strip():
            raise ValueError(f"{key} must name a registered runtime selection")
    if all(profile.get("binding_types", {}).get(key) == "file" for key in selection_keys) and any(
            not Path(bindings[key]).is_file() for key in selection_keys):
        return {}
    owners = {
        variant["variant_id"] for variant in project.get("structural_variants", [])
        if profile["capability_id"] in variant["capability_ids"]
    }
    if len(owners) > 1:
        raise ValueError("Execution capability must have at most one declared structural variant")
    module_name = ".".join(entrypoint.relative_to(REPO_ROOT.resolve()).with_suffix("").parts)
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ValueError(f"Cannot import runtime binding entrypoint: {entrypoint}") from error
    if not getattr(module, "__file__", None) or Path(module.__file__).resolve() != entrypoint:
        raise ValueError("Runtime binding module differs from its declared entrypoint")
    resolver = getattr(module, "resolve_execution_binding", None)
    if not callable(resolver):
        raise ValueError("Runtime binding entrypoint must define resolve_execution_binding")
    resolved = resolver(REPO_ROOT, project["project_id"], {key: bindings[key] for key in selection_keys},
                        request_path=request_path)
    if not isinstance(resolved, dict) or set(resolved) - {"resolved_runtime", "operating_points", "input_paths", "preparation_required", "missing_inputs", "tools"} != {
        "project_id", "structural_variant_id", "authorized_run_id",
    }:
        raise ValueError("Runtime binding result fields differ")
    for key in ("project_id",):
        if not isinstance(resolved[key], str) or not resolved[key] or resolved[key] != resolved[key].strip():
            raise ValueError(f"Runtime binding result {key} must be a nonempty trimmed string")
    if resolved["project_id"] != project["project_id"]:
        raise ValueError("Runtime binding result project identity differs")
    actual = resolved["structural_variant_id"]
    if (owners and actual not in owners) or (not owners and actual is not None):
        raise ValueError(f"Runtime structural variant {actual!r} differs from selected capability {sorted(owners)!r}")
    if "tools" in resolved:
        tools = resolved["tools"]
        if (not isinstance(tools, list) or not tools
                or any(not isinstance(tool, str) or not tool for tool in tools)
                or len(set(tools)) != len(tools)
                or not set(tools) <= set(profile["tools"])):
            raise ValueError("Runtime tools must be a nonempty unique subset of the declared profile tools")
    context = {key: resolved[key] for key in ("resolved_runtime", "operating_points", "input_paths", "preparation_required", "missing_inputs", "tools") if key in resolved}
    authorized_run_id = resolved["authorized_run_id"]
    if authorized_run_id is not None:
        if not isinstance(authorized_run_id, str):
            raise ValueError("Runtime binding authorized_run_id must be a string or null")
        validate_run_id(authorized_run_id)
        context["authorized_run_id"] = authorized_run_id
    return context


def compile_execution(
    plan_path: Path,
    registry_path: Path,
    bindings: dict[str, str] | None = None,
    *, purpose: str | None = None, qualification: str | None = None,
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
            "action": "preview", "execution_status": "not_started", "science_status": "not_evaluated",
            "blockers": ["Project has no execution profile contract"], "commands": []
        }
    execution_path = project_root / execution_relative
    execution = load_json(execution_path)
    validate_schema(execution, "execution_profiles.schema.json")
    if execution["project_id"] != project["project_id"]:
        raise ValueError("Execution profile contract project identity differs")
    profile = next((item for item in execution["profiles"] if
                    item["capability_id"] == plan["capability_id"] and item["mode"] == plan["mode"]), None)
    if profile is None:
        return {
            "schema_version": 1, "role": "execution_dry_run", "status": "NEEDS_IMPLEMENTATION",
            "safe_to_execute": False, "project_id": project["project_id"], "profile_id": None,
            "action": "preview", "execution_status": "not_started", "science_status": "not_evaluated",
            "blockers": [f"No execution profile for {plan['capability_id']}/{plan['mode']}"], "commands": []
        }

    # Candidate/Formal express a real qualification intent in existing requests.
    # Plan/static never determine execution actions or native evidence.
    if qualification is None:
        legacy = plan.get("requested_evidence_level")
        qualification = legacy if legacy in {"candidate", "formal"} else "none"
    implementation_blockers = []
    if purpose is not None and purpose != profile["purpose"]:
        implementation_blockers.append(f"Purpose is not supported: {purpose}")
    if qualification not in profile["qualification_support"]:
        implementation_blockers.append(f"Qualification is not supported: {qualification}")
    supported_points = {_operating_point_key(point) for point in profile["supported_operating_points"]}
    missing_points = [_operating_point_key(point) for point in plan["operating_points"] if _operating_point_key(point) not in supported_points]
    if missing_points:
        implementation_blockers.append("Unsupported operating points: " + ", ".join(f"{m:g} {u}, z={z}" for m, u, z in missing_points))
    requested_objectives = {item["metric"] for item in plan["objectives"]}
    missing_objectives = sorted(requested_objectives - set(profile["supported_objectives"]))
    if missing_objectives:
        implementation_blockers.append("Runner cannot evaluate objectives: " + ", ".join(missing_objectives))
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
    if (purpose is not None and purpose != profile["purpose"]) or qualification not in profile["qualification_support"]:
        return dict(schema_version=1, role="execution_dry_run", status="NEEDS_IMPLEMENTATION",
            safe_to_execute=False, project_id=project["project_id"], owner_kind="project",
            owner_id=project["project_id"], profile_id=profile["profile_id"], action="preview",
            purpose=profile["purpose"], requested_action=profile["action"], tools=profile["tools"],
            model=profile["model"], requested_qualification=qualification,
            execution_status="not_started", science_status="not_evaluated",
            blockers=implementation_blockers, limitations=profile["limitations"], commands=[])
    protected_bindings = {
        "timestamp",
        "python_exe",
        "design_plan_path",
        "request_path",
        "run_id",
        "authorized_run_id",
    }
    protected_supplied = sorted(set(bindings) & protected_bindings)
    if protected_supplied:
        raise ValueError(
            "Runtime bindings cannot override plan context: "
            + ", ".join(protected_supplied)
        )
    unexpected_bindings = sorted(set(bindings) - set(profile["required_bindings"]))
    if unexpected_bindings:
        raise ValueError(
            "Unexpected runtime bindings for selected profile: "
            + ", ".join(unexpected_bindings)
        )
    missing_bindings = sorted(set(profile["required_bindings"]) - set(bindings))
    resolved_context = _resolve_runtime_binding(project, profile, bindings,
                                                request_path=Path(plan["provenance"]["request"]["path"]))
    runtime = resolved_context.get("resolved_runtime")
    if runtime is not None and "campaign_path" in bindings and "campaign" in runtime:
        bindings = {**bindings, "campaign_path": runtime["campaign"]["path"]}
    resolved_inputs, unavailable_inputs = _resolved_inputs(profile, project_root, bindings)
    binding_authorities, source_freeze_required = _binding_authorities(profile, bindings)
    unavailable_inputs.extend(resolved_context.pop("missing_inputs", []))
    scientific_preparation_required = resolved_context.pop("preparation_required", [])
    actual_points = resolved_context.pop("operating_points", None)
    if actual_points is not None and {_operating_point_key(point) for point in actual_points} != {
            _operating_point_key(point) for point in plan["operating_points"]}:
        unavailable_inputs.append("Requested operating_points differ from the actual bound release species")
    for source in resolved_context.pop("input_paths", []):
        path = Path(source).resolve()
        if not path.is_file() or path.suffix.lower() != ".json":
            raise ValueError(f"Runtime binding input needs an existing small JSON authority: {path}")
        binding_authorities.append(dict(name="runtime_definition", path=str(path),
                                        bytes=path.stat().st_size, sha256=sha256(path)))

    stamp = validate_run_id(plan["run_id"])["stamp"]
    context: dict[str, str] = {
        "timestamp": stamp or "",
        "python_exe": str(Path(sys.executable).resolve()),
        "design_plan_path": str(plan_path),
        "request_path": str(Path(plan["provenance"]["request"]["path"]).resolve()),
        "run_id": plan["run_id"],
        "resolved_inputs_path": "__COMPILED_INPUTS__",
        "resolved_configuration_directory": "__COMPILED_CONFIGURATION__",
        "resolved_runtime_profile_path": "__COMPILED_RUNTIME__",
    }
    context.update(bindings)
    context.update(resolved_context)
    for step in profile["steps"]:
        if step["run_id_template"]:
            generated = step["run_id_template"].format_map(PreserveMissing(context))
            if re.search(r"\{[A-Za-z_]\w*\}", generated):
                if missing_bindings:
                    continue
                raise ValueError(f"Unresolved execution run ID placeholder in step: {step['step_id']}")
            validate_run_id(generated)
            context[f"{step['step_id']}_run_id"] = generated
            if step["step_id"].endswith("_run"):
                context[f"{step['step_id']}_id"] = generated

    commands = []
    for step in profile["steps"]:
        entrypoint = (project_root / step["entrypoint"]).resolve()
        arguments = [value.format_map(PreserveMissing(context)) for value in step["arguments"]]
        if not missing_bindings and any(re.search(r"\{[A-Za-z_]\w*\}", value) for value in arguments):
            raise ValueError(f"Unresolved execution argument placeholder in step: {step['step_id']}")
        if step["shell"] == "powershell":
            argv = [
                "pwsh.exe", "-NoProfile", "-NonInteractive", "-File",
                str(entrypoint), *arguments,
            ]
        else:
            module = entrypoint.relative_to(REPO_ROOT).with_suffix("").as_posix().replace("/", ".")
            argv = [context["python_exe"], "-m", module, *arguments]
        commands.append({
            "step_id": step["step_id"], "kind": step["kind"], "shell": step["shell"],
            "entrypoint": str(entrypoint), "argv": argv,
            "arguments": arguments,
            "run_id": context.get(f"{step['step_id']}_run_id"),
        })

    blockers = implementation_blockers.copy()
    if missing_bindings:
        blockers.append("Missing runtime bindings: " + ", ".join(missing_bindings))
    blockers.extend(unavailable_inputs)
    blockers.extend(scientific_preparation_required)
    if plan["request_status"] != "approved":
        blockers.append(f"Request status is {plan['request_status']}; solver execution requires approved")
    if implementation_blockers:
        status = "NEEDS_IMPLEMENTATION"
    elif missing_bindings or unavailable_inputs:
        status = "NEEDS_RUNTIME_INPUTS"
    elif scientific_preparation_required:
        status = "NEEDS_SCIENTIFIC_PREPARATION"
    elif source_freeze_required and plan["request_status"] == "approved":
        status = "NEEDS_SOURCE_FREEZE"
    elif plan["request_status"] != "approved":
        status = "AWAITING_APPROVAL"
    else:
        status = "EXECUTION_READY"
    return {
        "schema_version": 1,
        "role": "execution_dry_run",
        "python_executable": str(Path(sys.executable).resolve()),
        "status": status,
        "safe_to_execute": status == "EXECUTION_READY",
        "can_prepare_sources": status == "NEEDS_SOURCE_FREEZE",
        "scientific_preparation_required": scientific_preparation_required,
        "source_freeze_required": source_freeze_required,
        "source_freeze_action": "use --execute for the existing owner preparation; saved-plan execution requires its frozen source authority",
        "binding_authorities": binding_authorities,
        "resolved_bindings": bindings,
        "binding_sources": [str(Path(value).resolve()) for key, value in bindings.items()
                            if profile.get("binding_types", {}).get(key) == "file" and Path(value).is_file()],
        "planning_sources": [dict(path=str(plan_path), bytes=plan_path.stat().st_size, sha256=sha256(plan_path)),
                             dict(path=str(registry_path), bytes=registry_path.stat().st_size,
                                  sha256=plan["provenance"]["project_registry"]["sha256"]),
                             dict(path=str(Path(plan["provenance"]["request"]["path"]).resolve()),
                                  bytes=Path(plan["provenance"]["request"]["path"]).stat().st_size,
                                  sha256=plan["provenance"]["request"]["sha256"])],
        "action": "preview", "execution_status": "not_started", "science_status": "not_evaluated",
        "purpose": profile["purpose"], "requested_action": profile["action"], "tools": resolved_context.get("tools", profile["tools"]),
        "model": profile["model"], "requested_qualification": qualification,
        "legacy_requested_evidence_level": plan.get("requested_evidence_level"),
        "readiness_scope": "declared_profile_inputs__native_admission_and_scientific_acceptance_pending",
        "resolved_inputs": resolved_inputs,
        "resolved_runtime": resolved_context.get("resolved_runtime"),
        "project_id": project["project_id"],
        "owner_kind": "project", "owner_id": project["project_id"],
        "capability_id": plan["capability_id"],
        "mode": plan["mode"],
        "profile_id": profile["profile_id"],
        "execution_contract": {"path": str(execution_path), "sha256": sha256(execution_path)},
        "blockers": blockers,
        "limitations": profile["limitations"],
        "commands": commands,
    }


def compile_integration_execution(owner: str, workflow_id: str, run_id: str,
                                  bindings: dict[str, str], *, purpose: str | None = None,
                                  qualification: str = "none") -> dict[str, Any]:
    """Select one declared assembly owner entry; no component physics is synthesized."""
    validate_run_id(run_id)
    path = REPO_ROOT/"integrations/registry.json"
    document = load_json(path)
    validate_schema(document, "integration_registry.schema.json")
    owners = [item for item in document["integrations"] if item["integration_id"] == owner]
    if len(owners) != 1:
        raise ValueError(f"Unknown integration owner: {owner}")
    workflows = [item for item in owners[0].get("workflows", []) if item["workflow_id"] == workflow_id]
    if len(workflows) != 1:
        raise ValueError(f"Unknown integration workflow: {workflow_id}")
    workflow = workflows[0]
    qualification = qualification or "none"
    if qualification != "none":
        raise ValueError("Assembly propagation does not grant a scientific qualification")
    if purpose is not None and purpose != workflow["purpose"]:
        raise ValueError(f"Purpose is not supported: {purpose}")
    unexpected = sorted(set(bindings)-set(workflow["required_bindings"]))
    if unexpected:
        raise ValueError("Unexpected workflow bindings: " + ", ".join(unexpected))
    missing = sorted(set(workflow["required_bindings"])-set(bindings))
    _, unavailable = _resolved_inputs(workflow, REPO_ROOT, bindings)
    authorities, needs_freeze = _binding_authorities(workflow, bindings)
    for key, kind in workflow["binding_types"].items():
        if kind == "directory" and key in bindings:
            manifest = Path(bindings[key])/"run_manifest.json"
            if not manifest.is_file():
                unavailable.append(f"{key}: parent run manifest is missing: {manifest}")
            else:
                authorities.append(dict(name=key, path=str(manifest.resolve()), bytes=manifest.stat().st_size, sha256=sha256(manifest)))
    status = "NEEDS_RUNTIME_INPUTS" if missing or unavailable else "NEEDS_SOURCE_FREEZE" if needs_freeze else "EXECUTION_READY"
    entry = (REPO_ROOT/workflow["entrypoint"]).resolve()
    if not entry.is_relative_to((REPO_ROOT/owners[0]["root"]).resolve()) or not entry.is_file():
        raise ValueError("Integration entrypoint is outside its owner or missing")
    context = PreserveMissing(run_id=run_id, **bindings)
    arguments = [argument.format_map(context) for argument in workflow["arguments"]]
    return dict(schema_version=1, role="execution_dry_run", python_executable=str(Path(sys.executable).resolve()), status=status,
        safe_to_execute=status == "EXECUTION_READY", can_prepare_sources=status == "NEEDS_SOURCE_FREEZE",
        action="preview", execution_status="not_started", science_status="not_evaluated",
        purpose=workflow["purpose"], requested_action=workflow["action"], tools=workflow["tools"], model=workflow["model"],
        requested_qualification=qualification,
        owner_kind="integration", owner_id=owner, profile_id=workflow_id,
        execution_contract=dict(path=str(path), sha256=sha256(path)),
        binding_authorities=authorities, binding_sources=[str(Path(value).resolve()) for key, value in bindings.items()
            if workflow["binding_types"][key] == "file" and Path(value).is_file()],
        source_freeze_required=needs_freeze, planning_sources=[], resolved_inputs=[], resolved_runtime=None,
        blockers=[*(f"Missing workflow binding: {key}" for key in missing), *unavailable],
        limitations=workflow["limitations"], simulation_paths=workflow["simulation_paths"],
        commands=[dict(step_id=workflow_id, kind="run", shell="powershell", entrypoint=str(entry),
            arguments=arguments, argv=["pwsh", "-NoProfile", "-File", str(entry), *arguments], run_id=run_id)])


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
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_plan", type=Path, nargs="?")
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "config" / "project_registry.json")
    parser.add_argument("--bind", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--list-capabilities", action="store_true")
    parser.add_argument("--owner")
    parser.add_argument("--workflow")
    parser.add_argument("--run-id")
    parser.add_argument("--purpose")
    parser.add_argument("--qualification", choices=("none", "candidate", "formal"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--execute-plan", type=Path)
    args = parser.parse_args()
    try:
        if args.list_capabilities:
            if args.design_plan or args.workflow or args.execute or args.execute_plan or args.bind:
                parser.error("capability query cannot be combined with execution inputs")
            print(json.dumps(query_capabilities(load_json(args.registry), owner=args.owner), ensure_ascii=False, indent=2))
            return
        if args.workflow:
            if not args.owner or not args.run_id or args.design_plan or args.execute_plan:
                parser.error("--workflow requires --owner and --run-id, without a project design plan")
            result = compile_integration_execution(args.owner, args.workflow, args.run_id, parse_bindings(args.bind),
                                                   purpose=args.purpose, qualification=args.qualification)
        elif args.execute_plan:
            if args.design_plan or args.bind or args.execute or args.owner or args.run_id or args.purpose or args.qualification:
                parser.error("--execute-plan consumes the frozen plan; omit design input and bindings")
            result = load_json(args.execute_plan)
        else:
            if args.design_plan is None:
                parser.error("design_plan or --list-capabilities or --execute-plan is required")
            if args.owner or args.run_id:
                parser.error("a project design plan already fixes its owner and run identity")
            result = compile_execution(args.design_plan, args.registry, parse_bindings(args.bind),
                                       purpose=args.purpose, qualification=args.qualification)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    if args.execute or args.execute_plan:
        if not result.get("safe_to_execute") and not(args.execute and result.get("can_prepare_sources")):
            reason = "; ".join(result.get("blockers", []))
            if result.get("source_freeze_required"):
                reason = ("source freeze required for " + ", ".join(result["source_freeze_required"]) +
                          "; use --execute with the original design inputs for owner preparation, "
                          "or provide the existing manifest-bound source authority")
            raise SystemExit("Execution blocked: " + reason)
        with tempfile.TemporaryDirectory(prefix="compiled_execution_") as temporary:
            frozen = Path(temporary)/"execution_plan.json"
            frozen.write_text(rendered, encoding="utf-8")
            environment = dict(os.environ, MASS_SPECTROMETRY_COMPILED_PLAN=str(frozen),
                               MASS_SPECTROMETRY_COMPILED_REPO=str(REPO_ROOT))
            bootstrap = (". (Join-Path $env:MASS_SPECTROMETRY_COMPILED_REPO 'common/contracts/run_artifact_support.ps1'); "
                         "Invoke-CompiledExecutionPlan -PlanPath $env:MASS_SPECTROMETRY_COMPILED_PLAN "
                         "-RepoRoot $env:MASS_SPECTROMETRY_COMPILED_REPO" +
                         (" -PrepareUnfrozenSources" if args.execute and result.get("can_prepare_sources") else ""))
            # The original scientific owner manages resource observation and any explicit hard timeout.
            # Do not impose a second wall-clock kill on a healthy workflow.
            completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", bootstrap],
                                       cwd=REPO_ROOT, env=environment, check=False, timeout=None)
            if completed.returncode:
                raise SystemExit(completed.returncode)
        return
    print(rendered, end="")


if __name__ == "__main__":
    main()
