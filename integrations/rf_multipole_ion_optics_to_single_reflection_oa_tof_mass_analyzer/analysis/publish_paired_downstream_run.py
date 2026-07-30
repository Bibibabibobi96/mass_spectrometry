"""Publish one compact diagnostic-only paired downstream analysis run."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.paired_downstream_analysis import (
    INTEGRATION_ID,
    REQUEST_ROLE,
    analyze_request,
)


PARENT_MODE = "multipole_family_source_closure_n100"
TERMINAL_MODE = "rf_to_oatof_analyzer_transport_n100"
OUTPUT_MODE = "multipole_family_paired_downstream_analysis_n100"
PROFILE_COUNT = 3
SOLVERS = ("comsol", "simion")
ANALYZER_RELATIVE_PATH = (
    "integrations/"
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/paired_downstream_analysis.py"
)
PUBLISHER_RELATIVE_PATH = (
    "integrations/"
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/publish_paired_downstream_run.py"
)
PREREGISTRATION_RELATIVE_PATH = (
    "integrations/"
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "config/family_source_closure_preregistration.json"
)


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _verify_record(label: str, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ContractError(f"{label} record is missing")
    try:
        verify_record(label, record)
    except (AssertionError, KeyError, TypeError) as error:
        raise ContractError(f"{label} record identity failed: {error}") from error
    return record


def _record_path(label: str, record: Any) -> Path:
    verified = _verify_record(label, record)
    path = Path(str(verified["path"])).resolve()
    if not path.is_file():
        raise ContractError(f"{label} path is missing: {path}")
    return path


def _record_for_path(records: Any, path: Path, label: str) -> dict[str, Any]:
    iterable = records.values() if isinstance(records, Mapping) else records
    if not isinstance(iterable, (list, tuple, type({}.values()))):
        raise ContractError(f"{label} records are invalid")
    matches = [
        record
        for record in iterable
        if isinstance(record, dict)
        and Path(str(record.get("path", ""))).resolve() == path.resolve()
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} is not bound exactly once")
    return _verify_record(label, matches[0])


def _output_named(manifest: Mapping[str, Any], name: str, label: str) -> Path:
    records = manifest.get("outputs")
    if not isinstance(records, list):
        raise ContractError(f"{label} outputs are invalid")
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and Path(str(record.get("path", ""))).name == name
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} output {name} is not bound exactly once")
    return _record_path(f"{label} output {name}", matches[0])


def _portable(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise ContractError(f"path is outside workspace: {path}") from error


def _declared_reference(
    raw: Any,
    root: Path,
    label: str,
) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
        raise ContractError(f"{label} reference fields differ")
    path = Path(str(raw["path"]))
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    sha256 = raw["sha256"]
    if not path.is_file() or not isinstance(sha256, str):
        raise ContractError(f"{label} reference is invalid")
    if file_sha256(path) != sha256:
        raise ContractError(f"{label} SHA-256 differs")
    return {"path": str(path), "sha256": sha256}


def _manifest_reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def _resolve_workspace_path(raw: Any, workspace_root: Path) -> Path:
    path = Path(str(raw))
    return path.resolve() if path.is_absolute() else (workspace_root / path).resolve()


def _parent_run(
    *,
    workspace_root: Path,
    runs_root: Path,
    profile_id: str,
    solver: str,
    parent_run_id: str,
) -> tuple[dict[str, Any], Path]:
    try:
        validate_run_id(parent_run_id)
    except ValueError as error:
        raise ContractError(f"{profile_id}.{solver} parent run_id is invalid") from error
    parent_root = (runs_root / parent_run_id).resolve()
    if parent_root.parent != runs_root or not parent_root.is_dir():
        raise ContractError(f"{profile_id}.{solver} parent run is missing")
    manifest_path = parent_root / "run_manifest.json"
    manifest = _load(manifest_path, f"{profile_id}.{solver} parent manifest")
    expected = {
        "schema_version": 2,
        "role": "simulation_run_manifest",
        "run_id": parent_run_id,
        "project": INTEGRATION_ID,
        "mode": PARENT_MODE,
        "status": "success",
    }
    if any(manifest.get(name) != value for name, value in expected.items()):
        raise ContractError(f"{profile_id}.{solver} parent manifest differs")
    run_config_path = _record_path(
        f"{profile_id}.{solver} parent run_config", manifest.get("run_config")
    )
    if run_config_path.parent != parent_root:
        raise ContractError(f"{profile_id}.{solver} parent run_config is nonlocal")
    run_config = _load(
        run_config_path, f"{profile_id}.{solver} parent run_config"
    )
    if any(
        run_config.get(name) != value
        for name, value in {
            "schema_version": 2,
            "run_id": parent_run_id,
            "project": INTEGRATION_ID,
            "mode": PARENT_MODE,
            "connection_profile_id": profile_id,
            "source_branch_id": solver,
            "formal_gate_passed": False,
        }.items()
    ):
        raise ContractError(f"{profile_id}.{solver} parent run_config differs")
    source_identity = run_config.get("source_particle_identity")
    if (
        not isinstance(source_identity, dict)
        or source_identity.get("source_branch_id") != solver
        or source_identity.get("solver_id") != solver
    ):
        raise ContractError(f"{profile_id}.{solver} parent source identity differs")
    stages = run_config.get("stage_runs")
    if not isinstance(stages, list):
        raise ContractError(f"{profile_id}.{solver} parent stage_runs are invalid")
    analyzer = [
        stage
        for stage in stages
        if isinstance(stage, dict) and stage.get("phase") == "analyzer_transport"
    ]
    if len(analyzer) != 1:
        raise ContractError(
            f"{profile_id}.{solver} parent must bind one analyzer stage"
        )
    stage = analyzer[0]
    stage_path = Path(str(stage.get("path", "")))
    stage_root = (
        stage_path.resolve()
        if stage_path.is_absolute()
        else (workspace_root / stage_path).resolve()
    )
    terminal_manifest_path = stage_root / "run_manifest.json"
    if not terminal_manifest_path.is_file():
        raise ContractError(
            f"{profile_id}.{solver} analyzer terminal manifest is missing"
        )
    terminal_manifest = _load(
        terminal_manifest_path,
        f"{profile_id}.{solver} terminal manifest",
    )
    if (
        stage.get("run_id") != stage_root.name
        or terminal_manifest.get("run_id") != stage.get("run_id")
        or stage.get("manifest_sha256") != file_sha256(terminal_manifest_path)
    ):
        raise ContractError(f"{profile_id}.{solver} analyzer stage identity differs")
    terminal_record = _record_for_path(
        manifest.get("inputs"),
        terminal_manifest_path,
        f"{profile_id}.{solver} terminal manifest",
    )
    inputs = run_config.get("inputs")
    if (
        not isinstance(inputs, dict)
        or _resolve_workspace_path(
            inputs.get("analyzer_transport_manifest", ""), workspace_root
        )
        != terminal_manifest_path
        or terminal_record.get("sha256") != stage.get("manifest_sha256")
    ):
        raise ContractError(
            f"{profile_id}.{solver} parent terminal binding differs"
        )
    return run_config, terminal_manifest_path


def _terminal_branch(
    *,
    repo_root: Path,
    workspace_root: Path,
    profile_id: str,
    solver: str,
    parent_config: Mapping[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    manifest = _load(manifest_path, f"{profile_id}.{solver} terminal manifest")
    if any(
        manifest.get(name) != value
        for name, value in {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "status": "success",
            "mode": TERMINAL_MODE,
        }.items()
    ):
        raise ContractError(f"{profile_id}.{solver} terminal manifest differs")
    run_config_path = _record_path(
        f"{profile_id}.{solver} terminal run_config", manifest.get("run_config")
    )
    if run_config_path.parent != manifest_path.parent:
        raise ContractError(f"{profile_id}.{solver} terminal run_config is nonlocal")
    run_config = _load(
        run_config_path, f"{profile_id}.{solver} terminal run_config"
    )
    if any(
        run_config.get(name) != manifest.get(name)
        for name in ("run_id", "project", "mode")
    ):
        raise ContractError(f"{profile_id}.{solver} terminal run identity differs")
    terminal_particle_count = run_config.get("parameters", {}).get(
        "particle_count"
    )
    if (
        run_config.get("parameters", {}).get("source_branch_id") != solver
        or not isinstance(terminal_particle_count, int)
        or isinstance(terminal_particle_count, bool)
        or terminal_particle_count < 1
        or run_config.get("upstream_source_identity")
        != parent_config.get("source_particle_identity")
    ):
        raise ContractError(f"{profile_id}.{solver} terminal source differs")
    inputs = run_config.get("inputs")
    if not isinstance(inputs, dict):
        raise ContractError(f"{profile_id}.{solver} terminal inputs are invalid")

    def input_path(config_name: str) -> Path:
        path = _resolve_workspace_path(inputs.get(config_name, ""), workspace_root)
        _record_for_path(
            manifest.get("inputs"),
            path,
            f"{profile_id}.{solver} terminal input {config_name}",
        )
        return path

    canonical = input_path("canonical")
    row_map = input_path("row_map")
    runtime_path = input_path("runtime_binding")
    resolved_path = input_path("resolved_connection")
    runtime = _load(runtime_path, f"{profile_id}.{solver} runtime binding")
    if (
        runtime.get("role") != "rf_multipole_oatof_runtime_binding"
        or runtime.get("integration_id") != INTEGRATION_ID
        or runtime.get("connection_profile_id") != profile_id
        or runtime.get("upstream_project_id") != manifest.get("project")
    ):
        raise ContractError(f"{profile_id}.{solver} runtime binding differs")
    source_contract = _declared_reference(
        runtime.get("contracts", {}).get("source_contract"),
        repo_root,
        f"{profile_id}.{solver} source contract",
    )
    contract = _load(
        Path(source_contract["path"]),
        f"{profile_id}.{solver} source contract",
    )
    branch = contract.get("source_branches", {}).get(solver)
    if not isinstance(branch, dict) or branch.get("solver_id") != solver:
        raise ContractError(f"{profile_id}.{solver} source branch differs")
    source = branch.get("source")
    if not isinstance(source, dict):
        raise ContractError(f"{profile_id}.{solver} source record is missing")
    source_manifest = _declared_reference(
        source.get("manifest"),
        workspace_root,
        f"{profile_id}.{solver} original source manifest",
    )
    source_state = _declared_reference(
        source.get("state"),
        workspace_root,
        f"{profile_id}.{solver} original source state",
    )
    source_input = _declared_reference(
        source.get("particle_source"),
        workspace_root,
        f"{profile_id}.{solver} mother source",
    )
    return {
        "manifest": _manifest_reference(manifest_path),
        "canonical_local_exit": _manifest_reference(canonical),
        "row_map": _manifest_reference(row_map),
        "downstream_particles": _manifest_reference(
            _output_named(
                manifest,
                "simion_downstream_particles.csv",
                f"{profile_id}.{solver}",
            )
        ),
        "metrics": _manifest_reference(
            _output_named(
                manifest,
                "analyzer_transport_metrics.json",
                f"{profile_id}.{solver}",
            )
        ),
        "summary": _manifest_reference(
            _output_named(manifest, "summary.json", f"{profile_id}.{solver}")
        ),
        "resolved_connection": _manifest_reference(resolved_path),
        "runtime_binding": _manifest_reference(runtime_path),
        "source_manifest": source_manifest,
        "source_state": source_state,
        "source_input": source_input,
    }


def _validate_preregistration(
    preregistration: Mapping[str, Any],
    profile_ids: Sequence[str],
) -> None:
    profiles = preregistration.get("profiles")
    if (
        preregistration.get("schema_version") != 1
        or preregistration.get("role")
        != "integration_family_source_closure_preregistration"
        or preregistration.get("integration_id") != INTEGRATION_ID
        or preregistration.get("preregistered_before_run") is not True
        or preregistration.get("execution_status") != "NOT_RUN"
        or not isinstance(profiles, list)
        or len(profiles) != PROFILE_COUNT
    ):
        raise ContractError("family source-closure preregistration differs")
    by_id = {
        item.get("connection_profile_id"): item
        for item in profiles
        if isinstance(item, dict)
    }
    if set(by_id) != set(profile_ids):
        raise ContractError("paired profiles differ from preregistration")
    for profile_id in profile_ids:
        profile = by_id[profile_id]
        if (
            profile.get("particle_count") != 100
            or profile.get("source_branch_ids") != ["comsol", "simion"]
            or profile.get("run_status") != "NOT_RUN"
        ):
            raise ContractError(f"preregistered profile differs: {profile_id}")


def _write_pending_json(path: Path, value: Mapping[str, Any]) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, path)


def _publish_manifest(
    *,
    repo_root: Path,
    run_config: Path,
    manifest_path: Path,
    status: str,
    outputs: Sequence[Path],
) -> None:
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config),
        "--manifest",
        str(manifest_path),
        "--status",
        status,
        "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            f"paired {status} manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    manifest = _load(manifest_path, f"paired {status} manifest")
    run_config_value = _load(run_config, "paired run_config")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != status
        or manifest.get("run_id") != run_config_value.get("run_id")
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("mode") != OUTPUT_MODE
        or manifest.get("formal_eligible") is not False
    ):
        raise ContractError(f"paired {status} manifest identity differs")
    _verify_record(f"paired {status} manifest run_config", manifest.get("run_config"))
    for output in outputs:
        _record_for_path(
            manifest.get("outputs"), output, f"paired {status} output {output.name}"
        )
    verify_command = [
        sys.executable,
        "-m",
        "common.contracts.verify_run_manifest",
        str(manifest_path),
        "--require-status",
        status,
        "--require-local-run-config",
        "--require-run-id",
        str(run_config_value["run_id"]),
        "--require-project",
        INTEGRATION_ID,
        "--require-mode",
        OUTPUT_MODE,
    ]
    verified = subprocess.run(
        verify_command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if verified.returncode != 0:
        raise ContractError(
            f"paired {status} manifest verification failed: "
            + (verified.stdout + verified.stderr).strip()
        )


def _restore_interrupted(
    *,
    summary_path: Path,
    manifest_path: Path,
    manifest_pending: Path,
    interrupted_summary_bytes: bytes,
    interrupted_manifest_bytes: bytes,
) -> None:
    summary_pending = summary_path.with_name(f".{summary_path.name}.pending")
    summary_pending.write_bytes(interrupted_summary_bytes)
    os.replace(summary_pending, summary_path)
    manifest_pending.write_bytes(interrupted_manifest_bytes)
    os.replace(manifest_pending, manifest_path)


def _terminalize_failure(
    *,
    repo_root: Path,
    run_config_path: Path,
    summary_path: Path,
    result_path: Path,
    manifest_path: Path,
    manifest_pending: Path,
    failed_summary: Mapping[str, Any],
    interrupted_summary_bytes: bytes,
    interrupted_manifest_bytes: bytes,
) -> None:
    try:
        _write_pending_json(summary_path, failed_summary)
        outputs = (
            (result_path, summary_path)
            if result_path.is_file()
            else (summary_path,)
        )
        _publish_manifest(
            repo_root=repo_root,
            run_config=run_config_path,
            manifest_path=manifest_pending,
            status="failed",
            outputs=outputs,
        )
        os.replace(manifest_pending, manifest_path)
    except (KeyboardInterrupt, SystemExit):
        _restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            interrupted_summary_bytes=interrupted_summary_bytes,
            interrupted_manifest_bytes=interrupted_manifest_bytes,
        )
        raise
    except Exception:
        _restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            interrupted_summary_bytes=interrupted_summary_bytes,
            interrupted_manifest_bytes=interrupted_manifest_bytes,
        )


def publish_paired_downstream_run(
    *,
    repo_root: Path,
    run_id: str,
    pairs: Sequence[tuple[str, str, str]],
) -> Path:
    """Preflight three paired parents, analyze them, and publish one compact run."""
    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent
    try:
        validate_run_id(run_id)
    except ValueError as error:
        raise ContractError("paired analysis run_id is invalid") from error
    if len(pairs) != PROFILE_COUNT:
        raise ContractError("paired analysis requires exactly three --pair values")
    profile_ids = sorted(profile for profile, _, _ in pairs)
    if len(set(profile_ids)) != PROFILE_COUNT:
        raise ContractError("paired analysis profile IDs must be unique")
    parent_ids = [
        parent_id
        for _, comsol_parent, simion_parent in pairs
        for parent_id in (comsol_parent, simion_parent)
    ]
    if len(set(parent_ids)) != 2 * PROFILE_COUNT:
        raise ContractError("paired analysis parent run IDs must be unique")

    preregistration_path = repo_root / PREREGISTRATION_RELATIVE_PATH
    preregistration = _load(
        preregistration_path, "family source-closure preregistration"
    )
    _validate_preregistration(preregistration, profile_ids)
    requirements_lock = repo_root / "requirements-lock.txt"
    analyzer_implementation = repo_root / ANALYZER_RELATIVE_PATH
    publisher_implementation = repo_root / PUBLISHER_RELATIVE_PATH
    for path, label in (
        (requirements_lock, "requirements lock"),
        (analyzer_implementation, "paired analyzer implementation"),
        (publisher_implementation, "paired publisher implementation"),
    ):
        if not path.is_file():
            raise ContractError(f"{label} is missing: {path}")

    runs_root = (
        workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    ).resolve()
    request: dict[str, Any] = {
        "schema_version": 1,
        "role": REQUEST_ROLE,
        "integration_id": INTEGRATION_ID,
        "candidates": [],
    }
    parent_run_ids: dict[str, dict[str, str]] = {}
    parent_manifests: dict[str, Path] = {}
    terminal_manifests: dict[str, Path] = {}
    for profile_id, comsol_parent, simion_parent in sorted(pairs):
        candidate: dict[str, Any] = {"candidate_id": profile_id}
        parent_run_ids[profile_id] = {
            "comsol": comsol_parent,
            "simion": simion_parent,
        }
        for solver, parent_run_id in zip(
            SOLVERS, (comsol_parent, simion_parent), strict=True
        ):
            parent_config, terminal_manifest = _parent_run(
                workspace_root=workspace_root,
                runs_root=runs_root,
                profile_id=profile_id,
                solver=solver,
                parent_run_id=parent_run_id,
            )
            key = f"{profile_id}_{solver}"
            parent_manifests[key] = (
                runs_root / parent_run_id / "run_manifest.json"
            )
            terminal_manifests[key] = terminal_manifest
            candidate[solver] = _terminal_branch(
                repo_root=repo_root,
                workspace_root=workspace_root,
                profile_id=profile_id,
                solver=solver,
                parent_config=parent_config,
                manifest_path=terminal_manifest,
            )
        request["candidates"].append(candidate)

    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root or run_dir.exists():
        raise ContractError("paired analysis output run already exists or is invalid")
    request_path = run_dir / "inputs" / "paired_analysis_request.json"
    result_path = run_dir / "results" / "paired_downstream_analysis.json"
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    run_inputs = {
        "family_source_closure_preregistration": _portable(
            preregistration_path, workspace_root
        ),
        "paired_analysis_request": _portable(request_path, workspace_root),
        **{
            f"{key}_parent_manifest": _portable(path, workspace_root)
            for key, path in sorted(parent_manifests.items())
        },
        **{
            f"{key}_terminal_manifest": _portable(path, workspace_root)
            for key, path in sorted(terminal_manifests.items())
        },
        "paired_analysis_implementation": _portable(
            analyzer_implementation, workspace_root
        ),
        "publisher_implementation": _portable(
            publisher_implementation, workspace_root
        ),
        "requirements_lock": _portable(requirements_lock, workspace_root),
    }
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": OUTPUT_MODE,
        "project_root": str(workspace_root),
        "inputs": run_inputs,
        "parameters": {
            "particle_count": 100,
            "profile_ids": profile_ids,
            "source_branch_ids": ["comsol", "simion"],
            "parent_run_ids": parent_run_ids,
            "acceptance_thresholds_applied": False,
            "qualification_decision_made": False,
        },
        "artifact_retention": {
            "policy_version": 1,
            "class": "compact",
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    summary_base = {
        "schema_version": 1,
        "role": "integration_family_source_closure_paired_analysis_summary",
        "candidate_count": PROFILE_COUNT,
        "profile_ids": profile_ids,
        "parent_run_ids": parent_run_ids,
        "acceptance_thresholds_applied": False,
        "qualification_decision_made": False,
        "formal_gate_passed": False,
    }
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_pending_json(request_path, request)
    _write_pending_json(run_config_path, run_config)
    interrupted_summary = {
        **summary_base,
        "status": "interrupted",
        "analysis_status": "NOT_RUN",
        "shared_mother_source_sha256": None,
        "pareto_front_candidate_ids": [],
        "result": None,
    }
    _write_pending_json(summary_path, interrupted_summary)
    manifest_pending = manifest_path.with_name(".run_manifest.json.pending")
    _publish_manifest(
        repo_root=repo_root,
        run_config=run_config_path,
        manifest_path=manifest_pending,
        status="interrupted",
        outputs=(summary_path,),
    )
    os.replace(manifest_pending, manifest_path)
    interrupted_summary_bytes = summary_path.read_bytes()
    interrupted_manifest_bytes = manifest_path.read_bytes()

    failure_stage = "paired_analysis"
    try:
        result = analyze_request(request, workspace_root)
        if (
            result.get("status") != "INCONCLUSIVE_DIAGNOSTIC_ONLY"
            or result.get("acceptance_thresholds_applied") is not False
            or result.get("qualification_decision_made") is not False
            or len(result.get("candidates", [])) != PROFILE_COUNT
        ):
            raise ContractError(
                "paired analyzer returned an unauthorized result scope"
            )
        mother_hashes = {
            lineage["source_input_sha256"]
            for candidate in result["candidates"]
            for lineage in candidate["source_lineage"].values()
        }
        if len(mother_hashes) != 1:
            raise ContractError(
                "six paired branches do not share one mother source"
            )
        shared_mother_sha256 = mother_hashes.pop()
        summary = {
            **summary_base,
            "status": "success",
            "analysis_status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "shared_mother_source_sha256": shared_mother_sha256,
            "pareto_front_candidate_ids": result[
                "pareto_front_candidate_ids"
            ],
            "result": "results/paired_downstream_analysis.json",
        }
        failure_stage = "result_publication"
        _write_pending_json(result_path, result)
        _write_pending_json(summary_path, summary)
        failure_stage = "success_manifest_publication"
        _publish_manifest(
            repo_root=repo_root,
            run_config=run_config_path,
            manifest_path=manifest_pending,
            status="success",
            outputs=(result_path, summary_path),
        )
        failure_stage = "success_manifest_commit"
        os.replace(manifest_pending, manifest_path)
        return manifest_path
    except (KeyboardInterrupt, SystemExit):
        _restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            interrupted_summary_bytes=interrupted_summary_bytes,
            interrupted_manifest_bytes=interrupted_manifest_bytes,
        )
        raise
    except Exception as error:
        failed_summary = {
            **summary_base,
            "status": "failed",
            "analysis_status": (
                "INCONCLUSIVE_DIAGNOSTIC_ONLY"
                if result_path.is_file()
                else "FAILED"
            ),
            "shared_mother_source_sha256": None,
            "pareto_front_candidate_ids": [],
            "result": (
                "results/paired_downstream_analysis.json"
                if result_path.is_file()
                else None
            ),
            "failure_stage": failure_stage,
            "reason": str(error),
            "error_type": type(error).__name__,
        }
        _terminalize_failure(
            repo_root=repo_root,
            run_config_path=run_config_path,
            summary_path=summary_path,
            result_path=result_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            failed_summary=failed_summary,
            interrupted_summary_bytes=interrupted_summary_bytes,
            interrupted_manifest_bytes=interrupted_manifest_bytes,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--pair",
        action="append",
        nargs=3,
        metavar=("PROFILE", "COMSOL_PARENT", "SIMION_PARENT"),
        required=True,
    )
    args = parser.parse_args()
    if len(args.pair) != PROFILE_COUNT:
        parser.error("--pair must be supplied exactly three times")
    manifest = publish_paired_downstream_run(
        repo_root=args.repo_root,
        run_id=args.run_id,
        pairs=[tuple(item) for item in args.pair],
    )
    print(
        "PAIRED_DOWNSTREAM_RUN=PASS "
        f"STATUS=INCONCLUSIVE_DIAGNOSTIC_ONLY MANIFEST={manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
