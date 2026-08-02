"""Validate, materialize, and serially dispatch an oa-TOF Candidate campaign."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import load_json, sha256, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_proposal,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[2]
DEFAULT_CAMPAIGN = PROJECT_ROOT / "config" / "experiment_campaign.json"
DEFAULT_ARTIFACT_ROOT = (
    WORKSPACE_ROOT
    / "artifacts"
    / "projects"
    / "single_reflection_oa_tof_mass_analyzer"
)
PROFILE_ID = "validated_structural_candidate"
ENTRYPOINT = "workflows/design_candidate/run_candidate.py"
PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _canonical_sha(document: Any) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _project_file(record: dict[str, str], label: str) -> Path:
    relative = Path(record["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path must be project-relative")
    path = (PROJECT_ROOT / relative).resolve()
    if PROJECT_ROOT not in path.parents or not path.is_file():
        raise ValueError(f"{label} path is absent or escapes the oa-TOF project")
    if sha256(path) != record["sha256"]:
        raise ValueError(f"{label} SHA-256 differs from the campaign authority")
    return path


def _profile(document: dict[str, Any]) -> dict[str, Any]:
    path = _project_file(
        document["execution_profile"]["authority"], "execution profile"
    )
    profiles = load_json(path)["profiles"]
    matches = [
        item
        for item in profiles
        if item.get("profile_id") == document["execution_profile"]["profile_id"]
    ]
    if len(matches) != 1:
        raise ValueError("campaign execution profile must resolve exactly once")
    profile = matches[0]
    run_steps = [item for item in profile["steps"] if item.get("kind") == "run"]
    if (
        profile["profile_id"] != PROFILE_ID
        or profile.get("mode") != "design_candidate"
        or profile.get("required_bindings") != ["particle_source_seed"]
        or len(run_steps) != 1
        or run_steps[0].get("entrypoint") != ENTRYPOINT
    ):
        raise ValueError("campaign does not resolve the canonical structural Candidate entry")
    return profile


def _authority_documents(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for name, record in document["authorities"].items():
        resolved[name] = load_json(_project_file(record, name))
    return resolved


def _axis_map(
    document: dict[str, Any],
    profile: dict[str, Any],
    authorities: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    axes = document["allowed_variation_axes"]
    axis_ids = [item["axis_id"] for item in axes]
    variable_ids = [item["variable_id"] for item in axes]
    if len(axis_ids) != len(set(axis_ids)) or len(variable_ids) != len(set(variable_ids)):
        raise ValueError("campaign variation axes must have unique axis and variable IDs")
    if set(variable_ids) - set(profile["supported_design_variables"]):
        raise ValueError("campaign axis is absent from execution-profile runtime coverage")
    catalog = {
        item["variable_id"]: item
        for item in authorities["design_variable_catalog"]["variables"]
    }
    envelope_limits = {
        item["variable_id"]: item
        for item in authorities["optimization_envelope"]["design_variable_limits"]
    }
    result: dict[str, dict[str, Any]] = {}
    for axis in axes:
        definition = catalog.get(axis["variable_id"])
        if (
            definition is None
            or definition.get("compile_status") != "candidate_contract"
            or definition.get("unit") != axis["unit"]
        ):
            raise ValueError(f"campaign axis is not compiler-governed: {axis['axis_id']}")
        limit = envelope_limits.get(axis["variable_id"])
        if (
            limit is None
            or limit["unit"] != axis["unit"]
            or limit["minimum"] > limit["reference_value"]
            or limit["reference_value"] > limit["maximum"]
            or limit["minimum"] < definition["minimum"]
            or limit["maximum"] > definition["maximum"]
        ):
            raise ValueError(
                f"campaign axis lacks a valid narrow optimization envelope: {axis['axis_id']}"
            )
        result[axis["axis_id"]] = {
            **axis,
            "definition": definition,
            "envelope": limit,
        }
    return result


def _request_contract(
    document: dict[str, Any],
    axes: dict[str, dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    path = _project_file(document["base_request"], "base request")
    request = load_json(path)
    validate_schema(request, "design_request.schema.json")
    target = request["target"]
    if (
        target.get("preferred_project_id") != PROJECT_ID
        or target.get("mode") != "design_candidate"
        or request.get("evidence_level") != "candidate"
    ):
        raise ValueError("campaign base request is not an oa-TOF design Candidate request")
    if request["design_variables"] != [item["variable_id"] for item in axes.values()]:
        raise ValueError("base request design variables must equal campaign axes in order")
    points = request["operating_points"]
    if (
        len(points) != 1
        or float(points[0]["mass"]["value"]) != 524.0
        or points[0]["mass"]["unit"] != "Da"
        or points[0]["charge_state"] != 1
    ):
        raise ValueError("structural campaign must keep the fixed 524 Da, +1 operating point")
    return path, request


def _authorization_blockers(
    document: dict[str, Any],
    request: dict[str, Any],
    authorities: dict[str, dict[str, Any]],
    axes: dict[str, dict[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    if document["status"] != "authorized":
        blockers.append("campaign status is not authorized")
    if not document["execution_authorized"]:
        blockers.append("execution_authorized is false")
    if not document["preregistered_before_run"]:
        blockers.append("campaign is not preregistered")
    if request["status"] != "approved" or request["approval"] is None:
        blockers.append("base request is not approved")
    validated = set(
        authorities["science_profile"]
        .get("current_validated_extent", {})
        .get("nonzero_design_variables", [])
    )
    variables = {item["variable_id"] for item in axes.values()}
    if variables - validated:
        blockers.append(
            "science profile does not authorize every nonzero campaign variable"
        )
    if document["resource_budget"]["automatic_retry_count"] != 0:
        blockers.append("automatic retry must remain zero")
    if document["resource_budget"]["commercial_solver_parallelism"] != 1:
        blockers.append("commercial solver parallelism must remain one")
    return blockers


def validate_campaign(
    campaign_path: Path = DEFAULT_CAMPAIGN,
    *,
    require_authorized: bool = False,
) -> dict[str, Any]:
    path = campaign_path.resolve(strict=True)
    config_root = (PROJECT_ROOT / "config").resolve()
    if config_root not in path.parents:
        raise ValueError("campaign path must remain under the oa-TOF config directory")
    document = load_json(path)
    validate_schema(document, "oatof_experiment_campaign.schema.json")
    if document["execution_authorized"] != (document["status"] == "authorized"):
        raise ValueError("campaign status and execution_authorized disagree")
    profile = _profile(document)
    authorities = _authority_documents(document)
    axes = _axis_map(document, profile, authorities)
    request_path, request = _request_contract(document, axes)

    experiments = document["experiments"]
    sequences = [item["sequence"] for item in experiments]
    if sequences != list(range(1, len(experiments) + 1)):
        raise ValueError("campaign sequence must be contiguous and match table order")
    experiment_ids = [item["experiment_id"] for item in experiments]
    run_ids = [item["authorized_run_id"] for item in experiments]
    if len(experiment_ids) != len(set(experiment_ids)):
        raise ValueError("campaign experiment IDs must be unique")
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("campaign run IDs must be unique")
    for experiment in experiments:
        identity = validate_run_id(experiment["authorized_run_id"])
        if identity["retry"] is not None:
            raise ValueError("campaign run IDs must not encode an automatic retry")
        values = experiment["variation_values"]
        if [item["axis_id"] for item in values] != list(axes):
            raise ValueError(
                f"{experiment['experiment_id']} values must cover the allowed axes in order"
            )
        for value in values:
            axis = axes[value["axis_id"]]
            definition = axis["definition"]
            envelope = axis["envelope"]
            number = value["value"]
            if (
                value["unit"] != axis["unit"]
                or not math.isfinite(number)
                or not definition["minimum"] <= number <= definition["maximum"]
                or not envelope["minimum"] <= number <= envelope["maximum"]
                or (
                    definition["kind"] == "integer"
                    and not float(number).is_integer()
                )
            ):
                raise ValueError(
                    f"{experiment['experiment_id']} has an invalid value for {value['axis_id']}"
                )

    blockers = _authorization_blockers(document, request, authorities, axes)
    if require_authorized and blockers:
        raise ValueError("campaign execution is not authorized: " + "; ".join(blockers))
    return {
        "path": path,
        "sha256": sha256(path),
        "document": document,
        "profile": profile,
        "authorities": authorities,
        "axes": axes,
        "request_path": request_path,
        "request": request,
        "authorization_blockers": blockers,
    }


def _experiment_status(
    experiment: dict[str, Any],
    campaign_id: str,
    campaign_sha256: str,
    artifact_root: Path,
) -> dict[str, Any]:
    run_root = artifact_root / "runs" / experiment["authorized_run_id"]
    record = {
        "sequence": experiment["sequence"],
        "experiment_id": experiment["experiment_id"],
        "candidate_run_id": experiment["authorized_run_id"],
        "status": "NOT_STARTED",
        "ended": False,
    }
    if not run_root.exists():
        return record
    try:
        config = load_json(run_root / "run_config.json")
        summary = load_json(run_root / "summary.json")
        manifest = load_json(run_root / "run_manifest.json")
        binding = config.get("campaign_binding", {})
        manifest_binding = manifest.get("campaign_binding", {})
        identity_valid = (
            config.get("run_id") == experiment["authorized_run_id"]
            and manifest.get("run_id") == experiment["authorized_run_id"]
            and config.get("project") == PROJECT_ID
            and manifest.get("project") == PROJECT_ID
            and binding == manifest_binding
            and binding.get("campaign_id") == campaign_id
            and binding.get("campaign_sha256") == campaign_sha256
            and binding.get("experiment_id") == experiment["experiment_id"]
        )
        terminal = manifest.get("lifecycle_state") == "terminal"
        success = (
            identity_valid
            and terminal
            and summary.get("status") == "success"
            and manifest.get("status") == "success"
        )
        record["status"] = "SUCCESS" if success else "FAILED_OR_INVALID"
        record["ended"] = bool(terminal)
        if not success:
            record["reason"] = (
                "child evidence is failed, non-terminal, incomplete, or not bound "
                "to the current campaign table"
            )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        record["status"] = "FAILED_OR_INVALID"
        record["reason"] = "child run directory exists without complete readable evidence"
    return record


def campaign_status(
    campaign_path: Path = DEFAULT_CAMPAIGN,
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> dict[str, Any]:
    resolved = validate_campaign(campaign_path)
    document = resolved["document"]
    return {
        "schema_version": 1,
        "role": "oatof_experiment_campaign_status",
        "campaign_id": document["campaign_id"],
        "campaign_sha256": resolved["sha256"],
        "status": document["status"],
        "execution_authorized": not resolved["authorization_blockers"],
        "authorization_blockers": resolved["authorization_blockers"],
        "allowed_variation_axes": document["allowed_variation_axes"],
        "experiment_count": len(document["experiments"]),
        "commercial_solver_parallelism": 1,
        "automatic_retry_count": 0,
        "mass_spectrum_internal_species_are_campaign_rows": False,
        "experiments": [
            _experiment_status(
                experiment,
                document["campaign_id"],
                resolved["sha256"],
                artifact_root.resolve(),
            )
            for experiment in document["experiments"]
        ],
    }


def _materialize_rows(
    resolved: dict[str, Any],
    root: Path,
    selected_ids: set[str],
) -> list[dict[str, Any]]:
    document = resolved["document"]
    base_request = resolved["request"]
    rows: list[dict[str, Any]] = []
    for experiment in document["experiments"]:
        if experiment["experiment_id"] not in selected_ids:
            continue
        row_root = root / experiment["experiment_id"]
        row_root.mkdir(parents=True, exist_ok=False)
        request = copy.deepcopy(base_request)
        request["request_id"] = (
            f"{base_request['request_id']}_{experiment['experiment_id']}"
        )
        request_path = row_root / "design_request.json"
        _write_json(request_path, request)
        proposal = {
            "schema_version": 1,
            "role": "design_candidate_proposal",
            "candidate_id": (
                f"{document['campaign_id']}_{experiment['experiment_id']}"
            ),
            "project_id": PROJECT_ID,
            "request": {
                "path": "design_request.json",
                "sha256": sha256(request_path),
            },
            "values": [
                {
                    "variable": resolved["axes"][value["axis_id"]]["variable_id"],
                    "value": value["value"],
                    "unit": value["unit"],
                }
                for value in experiment["variation_values"]
            ],
        }
        proposal_path = row_root / "candidate_proposal.json"
        _write_json(proposal_path, proposal)
        _, diff, _ = compile_proposal(proposal_path)
        proposed = {
            item["variable"]
            for item in diff["changed_variables"]
            if item["change_origin"] == "proposed"
        }
        unexpected = [
            item
            for item in diff["changed_variables"]
            if item["change_origin"] != "proposed"
            or item["variable"]
            not in {axis["variable_id"] for axis in resolved["axes"].values()}
        ]
        if unexpected or proposed - {
            axis["variable_id"] for axis in resolved["axes"].values()
        }:
            raise ValueError(
                f"{experiment['experiment_id']} compiler diff escapes allowed variation axes"
            )
        rows.append(
            {
                "experiment": experiment,
                "request_path": request_path,
                "proposal_path": proposal_path,
                "compiler_diff_sha256": _canonical_sha(diff),
            }
        )
    return rows


def preflight_campaign(
    campaign_path: Path,
    campaign_run_id: str,
    *,
    experiment_id: str | None = None,
    run_all: bool = False,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> dict[str, Any]:
    if (experiment_id is None) == (not run_all):
        raise ValueError("select exactly one experiment_id or run_all")
    validate_run_id(campaign_run_id)
    resolved = validate_campaign(campaign_path, require_authorized=True)
    document = resolved["document"]
    available = {item["experiment_id"] for item in document["experiments"]}
    selected_ids = available if run_all else {str(experiment_id)}
    if not selected_ids <= available:
        raise ValueError("selected experiment_id is absent from the campaign")
    artifact_root = artifact_root.resolve()
    campaign_run_root = artifact_root / "runs" / campaign_run_id
    if campaign_run_root.exists():
        raise FileExistsError(f"campaign run already exists: {campaign_run_root}")
    for experiment in document["experiments"]:
        if (
            experiment["experiment_id"] in selected_ids
            and (artifact_root / "runs" / experiment["authorized_run_id"]).exists()
        ):
            raise FileExistsError(
                f"candidate run already exists: {experiment['authorized_run_id']}"
            )
    scratch = artifact_root / "scratch" / f"{campaign_run_id}__campaign-preflight"
    if scratch.exists():
        raise FileExistsError(f"campaign preflight already exists: {scratch}")
    all_rows = _materialize_rows(resolved, scratch / "rows", available)
    rows = [
        row
        for row in all_rows
        if row["experiment"]["experiment_id"] in selected_ids
    ]
    if [row["experiment"]["experiment_id"] for row in rows] != [
        item["experiment_id"]
        for item in document["experiments"]
        if item["experiment_id"] in selected_ids
    ]:
        raise ValueError("campaign row materialization changed declared order")
    return {
        "resolved": resolved,
        "campaign_run_id": campaign_run_id,
        "artifact_root": artifact_root,
        "campaign_run_root": campaign_run_root,
        "scratch": scratch,
        "rows": rows,
    }


def _record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def execute_campaign(
    campaign_path: Path,
    campaign_run_id: str,
    *,
    experiment_id: str | None = None,
    run_all: bool = False,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    candidate_executor: Callable[..., tuple[Path, dict[str, Any]]],
) -> tuple[Path, dict[str, Any]]:
    """Preflight every selected row, then call the existing Candidate entry serially."""
    prepared = preflight_campaign(
        campaign_path,
        campaign_run_id,
        experiment_id=experiment_id,
        run_all=run_all,
        artifact_root=artifact_root,
    )
    resolved = prepared["resolved"]
    run_root = prepared["campaign_run_root"]
    inputs = run_root / "inputs"
    rows_root = inputs / "rows"
    receipts_root = run_root / "experiment_receipts"
    run_root.mkdir(parents=True, exist_ok=False)
    inputs.mkdir()
    receipts_root.mkdir()
    frozen_table = inputs / "experiment_campaign.json"
    shutil.copy2(resolved["path"], frozen_table)
    shutil.copytree(prepared["scratch"] / "rows", rows_root)
    config = {
        "schema_version": 1,
        "role": "oatof_experiment_campaign_run_config",
        "run_id": campaign_run_id,
        "project": PROJECT_ID,
        "mode": "experiment_campaign",
        "campaign_id": resolved["document"]["campaign_id"],
        "campaign_sha256": sha256(frozen_table),
        "selection": "all" if run_all else experiment_id,
        "commercial_solver_parallelism": 1,
        "automatic_retry_count": 0,
        "started_at_utc": _utc_now(),
    }
    _write_json(run_root / "run_config.json", config)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "role": "oatof_experiment_campaign_summary",
        "status": "running",
        "campaign_id": config["campaign_id"],
        "rows": [],
        "recorded_at_utc": _utc_now(),
    }
    _write_json(run_root / "summary.json", summary)
    _write_json(
        run_root / "run_manifest.json",
        {
            "schema_version": 1,
            "role": "simulation_run_manifest",
            "run_id": campaign_run_id,
            "project": PROJECT_ID,
            "mode": "experiment_campaign",
            "status": "interrupted",
            "lifecycle_state": "provisional",
            "run_config": _record(run_root / "run_config.json", run_root),
            "inputs": {"campaign": _record(frozen_table, run_root)},
            "outputs": [_record(run_root / "summary.json", run_root)],
            "formal_eligible": False,
            "promotion_authorized": False,
            "recorded_at_utc": _utc_now(),
        },
    )

    failure = False
    for index, prepared_row in enumerate(prepared["rows"]):
        experiment = prepared_row["experiment"]
        if failure:
            summary["rows"].append(
                {
                    "experiment_id": experiment["experiment_id"],
                    "status": "not_started_due_to_prior_failure",
                }
            )
            continue
        row_root = rows_root / experiment["experiment_id"]
        request_path = row_root / "design_request.json"
        selection = {
            "schema_version": 1,
            "role": "oatof_campaign_selection",
            "campaign_id": config["campaign_id"],
            "campaign_sha256": sha256(frozen_table),
            "campaign_run_id": campaign_run_id,
            "row_sha256": _canonical_sha(experiment),
            "sequence": experiment["sequence"],
            "experiment_id": experiment["experiment_id"],
            "candidate_run_id": experiment["authorized_run_id"],
            "particle_source_seed": resolved["document"]["fixed_runtime_bindings"][
                "particle_source_seed"
            ],
            "allowed_variation_axes": resolved["document"]["allowed_variation_axes"],
            "request": {"path": str(request_path), "sha256": sha256(request_path)},
            "proposal": {
                "path": str(row_root / "candidate_proposal.json"),
                "sha256": sha256(row_root / "candidate_proposal.json"),
            },
            "resource_budget": resolved["document"]["resource_budget"],
        }
        selection_path = row_root / "campaign_selection.json"
        _write_json(selection_path, selection)
        try:
            child_root, child_summary = candidate_executor(
                request_path,
                experiment["authorized_run_id"],
                particle_source_seed=selection["particle_source_seed"],
                artifact_project_root=prepared["artifact_root"],
                campaign_table=frozen_table,
                campaign_selection=selection_path,
            )
            child_manifest = child_root / "run_manifest.json"
            if (
                child_summary.get("status") != "success"
                or not child_manifest.is_file()
                or load_json(child_manifest).get("status") != "success"
            ):
                raise RuntimeError("candidate child did not produce successful bound evidence")
            receipt = {
                "schema_version": 1,
                "role": "oatof_campaign_experiment_receipt",
                "campaign_id": config["campaign_id"],
                "experiment_id": experiment["experiment_id"],
                "status": "success",
                "selection_sha256": sha256(selection_path),
                "child_run_id": experiment["authorized_run_id"],
                "child_summary": _record(child_root / "summary.json", prepared["artifact_root"]),
                "child_manifest": _record(child_manifest, prepared["artifact_root"]),
                "recorded_at_utc": _utc_now(),
            }
        except Exception as exc:
            failure = True
            receipt = {
                "schema_version": 1,
                "role": "oatof_campaign_experiment_receipt",
                "campaign_id": config["campaign_id"],
                "experiment_id": experiment["experiment_id"],
                "status": "failed",
                "selection_sha256": sha256(selection_path),
                "child_run_id": experiment["authorized_run_id"],
                "error": str(exc),
                "recorded_at_utc": _utc_now(),
            }
        receipt_path = receipts_root / f"{experiment['experiment_id']}.json"
        _write_json(receipt_path, receipt)
        summary["rows"].append(
            {
                "experiment_id": experiment["experiment_id"],
                "status": receipt["status"],
                "receipt": _record(receipt_path, run_root),
            }
        )

    summary["status"] = "failed" if failure else "success"
    summary["recorded_at_utc"] = _utc_now()
    _write_json(run_root / "summary.json", summary)
    manifest = {
        "schema_version": 1,
        "role": "simulation_run_manifest",
        "run_id": campaign_run_id,
        "project": PROJECT_ID,
        "mode": "experiment_campaign",
        "status": summary["status"],
        "lifecycle_state": "terminal",
        "run_config": _record(run_root / "run_config.json", run_root),
        "inputs": {"campaign": _record(frozen_table, run_root)},
        "outputs": [
            _record(path, run_root)
            for path in sorted(receipts_root.glob("*.json"))
        ]
        + [_record(run_root / "summary.json", run_root)],
        "formal_eligible": False,
        "promotion_authorized": False,
        "recorded_at_utc": _utc_now(),
    }
    _write_json(run_root / "run_manifest.json", manifest)
    return run_root, summary


def read_campaign_receipt(
    campaign_run_id: str,
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> dict[str, Any]:
    validate_run_id(campaign_run_id)
    root = artifact_root.resolve() / "runs" / campaign_run_id
    summary = load_json(root / "summary.json")
    manifest = load_json(root / "run_manifest.json")
    if (
        summary.get("role") != "oatof_experiment_campaign_summary"
        or manifest.get("run_id") != campaign_run_id
        or manifest.get("mode") != "experiment_campaign"
    ):
        raise ValueError("run is not an oa-TOF experiment campaign receipt")
    return {"run_root": str(root), "summary": summary, "manifest": manifest}
