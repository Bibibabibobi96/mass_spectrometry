"""Publish one lightweight parent run for a family source-closure chain."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import record_path, verify_record


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
STAGES = {
    "pre_pulse_interface_transport": {
        "run_stem": "__sim__comsol__rf-oatof-pre-pulse-interface-gap0__n",
        "mode": "rf_to_oatof_pre_pulse_interface_transport",
    },
    "pulse_capture": {
        "run_stem": "__sim__comsol__rf-oatof-pulse-capture-gap0__n",
        "mode": "rf_to_oatof_pulse_capture",
    },
    "analyzer_transport": {
        "run_stem": "__sim__cross__rf-oatof-analyzer-transport-gap0__n",
        "mode": "rf_to_oatof_analyzer_transport",
    },
}
SINGLE_FLIGHT_STAGES = {
    "single_flight_transport": {
        "run_stem": "__sim__simion__rf-oatof-single-flight-gap0__n",
        "mode": "rf_to_oatof_simion_single_flight",
    }
}
STAGES_BY_STRATEGY = {
    "staged_three_stage": STAGES,
    "simion_single_flight": SINGLE_FLIGHT_STAGES,
}
ALL_STAGE_CONTRACTS = {**STAGES, **SINGLE_FLIGHT_STAGES}
N1_RECEIPT_SCHEMA = "rf_oatof_three_zone_n1_solver_authorization_receipt.schema.json"
N1_RECEIPT_NAME = "three_zone_n1_solver_authorization_receipt.json"
N1_REQUIRED_EVENTS = (
    "source_release",
    "pre_pulse_state",
    "accelerator_grid1_forward",
    "accelerator_intermediate2_forward",
    "local_accelerator_exit",
    "reflectron_entrance_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)


def _retry_suffix(run_id: str) -> str:
    match = re.search(r"(__r\d{2})$", run_id)
    return match.group(1) if match else ""


def stage_project_id(execution_strategy: str, upstream_project_id: str) -> str:
    if execution_strategy == "simion_single_flight":
        return INTEGRATION_ID
    if execution_strategy == "staged_three_stage":
        return upstream_project_id
    raise ContractError(f"unsupported family execution strategy: {execution_strategy}")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _portable(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"path is outside the workspace: {path}") from exc


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _file_binding(path: Path, workspace_root: Path) -> dict[str, Any]:
    return {
        "path": _portable(path, workspace_root),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _verified_manifest_record(
    manifest: dict[str, Any], collection: str, name: str, run_dir: Path
) -> tuple[dict[str, Any], Path]:
    records = manifest.get(collection)
    if not isinstance(records, dict) or name not in records:
        raise ContractError(f"N=1 child manifest {collection}.{name} is missing")
    record = records[name]
    try:
        verify_record(f"N=1 child {collection}.{name}", record, base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(f"N=1 child manifest {collection}.{name} identity differs") from exc
    return record, record_path(record, base_dir=run_dir)


def _n1_gate_pair(campaign: dict[str, Any], experiment_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    experiments = campaign.get("experiments")
    if not isinstance(experiments, list):
        return None
    matches = [row for row in experiments if row.get("experiment_id") == experiment_id]
    if len(matches) != 1:
        return None
    producer = matches[0]
    gate = producer.get("three_zone_solver_gate")
    if not isinstance(gate, dict) or gate.get("stage") != "n1_smoke_producer":
        return None
    gate_id = gate.get("gate_id")
    consumers = [
        row
        for row in experiments
        if isinstance(row.get("three_zone_solver_gate"), dict)
        and row["three_zone_solver_gate"].get("gate_id") == gate_id
        and row["three_zone_solver_gate"].get("stage") == "n100_solver_authorized_consumer"
        and row["three_zone_solver_gate"].get("predecessor_experiment_id") == experiment_id
    ]
    if len(consumers) != 1:
        raise ContractError("N=1 solver gate must bind exactly one N=100 successor")
    successor = consumers[0]
    if successor.get("single_flight_population", {}).get("execution_population", {}).get("particle_count") != 100:
        raise ContractError("N=1 solver gate successor must freeze N=100")
    return producer, successor


def _n1_gate_assessment(summary: dict[str, Any], checkpoint_path: Path) -> tuple[int, dict[str, int], list[str]]:
    failures: list[str] = []
    census = summary.get("census")
    if (
        summary.get("role") != "rf_oatof_simion_single_flight_summary"
        or summary.get("status") != "success"
        or summary.get("formal_gate_passed") is not False
        or not isinstance(census, dict)
    ):
        failures.append("SUMMARY_IDENTITY")
        census = {}
    if census.get("launched") != 1:
        failures.append("PARTICLE_CENSUS")
    with checkpoint_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    particle_ids: set[int] = set()
    for row in rows:
        try:
            particle_ids.add(int(row["particle_id"]))
        except (KeyError, TypeError, ValueError):
            failures.append("PARTICLE_IDENTITY")
            break
    if len(particle_ids) != 1:
        failures.append("PARTICLE_IDENTITY")
    particle_id = next(iter(particle_ids), 1)
    event_rows = {event: [row for row in rows if row.get("event") == event] for event in N1_REQUIRED_EVENTS}
    for event, selected in event_rows.items():
        if not selected:
            failures.append("MISSING_EVENT")
        elif len(selected) > 1:
            failures.append("DUPLICATE_EVENT")
        if census.get(event) != len(selected):
            failures.append("PARTICLE_CENSUS")
    ordered_rows = [event_rows[event][0] for event in N1_REQUIRED_EVENTS if len(event_rows[event]) == 1]
    position_fields = (
        "instrument_time_us",
        "x_mm",
        "y_mm",
        "z_mm",
    )
    velocity_fields = (
        "vx_mm_per_us",
        "vy_mm_per_us",
        "vz_mm_per_us",
    )
    try:
        times = [float(row["instrument_time_us"]) for row in ordered_rows]
        if any(
            not math.isfinite(float(row[field]))
            for row in ordered_rows
            for field in position_fields
        ) or any(
            not math.isfinite(float(row[field]))
            for row in ordered_rows
            if row["event"] != "detector_crossing"
            for field in velocity_fields
        ):
            failures.append("NONFINITE_STATE")
        if len(ordered_rows) != len(N1_REQUIRED_EVENTS) or any(left > right for left, right in zip(times, times[1:])):
            failures.append("EVENT_ORDER")
    except (KeyError, TypeError, ValueError):
        failures.append("NONFINITE_STATE")
    detector = event_rows["detector_crossing"]
    if len(detector) != 1 or detector[0].get("survival_status") != "detected":
        failures.append("DETECTOR_STATUS")
    try:
        launched = int(census.get("launched", 0))
    except (TypeError, ValueError):
        launched = 0
    receipt_census = {
        "launched": launched,
        **{event: int(census.get(event, 0)) for event in N1_REQUIRED_EVENTS[2:]},
    }
    return particle_id, receipt_census, list(dict.fromkeys(failures))


def _publish_n1_solver_authorization_receipt(
    *,
    campaign: dict[str, Any],
    campaign_path: Path,
    producer: dict[str, Any],
    successor: dict[str, Any],
    integration_run_id: str,
    stage: dict[str, str],
    workspace_root: Path,
    parent_run_dir: Path,
    source_identity: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    stage_dir = workspace_root / stage["path"]
    manifest_path = stage_dir / "run_manifest.json"
    manifest = _load(manifest_path)
    expected_manifest_identity = {
        "role": "simulation_run_manifest",
        "run_id": stage["run_id"],
        "project": INTEGRATION_ID,
        "mode": SINGLE_FLIGHT_STAGES["single_flight_transport"]["mode"],
        "status": "success",
    }
    if any(manifest.get(name) != value for name, value in expected_manifest_identity.items()):
        raise ContractError("N=1 child manifest identity/status differs")
    if manifest.get("formal_eligible") is not False:
        raise ContractError("N=1 child manifest must remain non-Formal")
    for name, record in manifest.get("inputs", {}).items():
        try:
            verify_record(f"N=1 child input {name}", record, base_dir=stage_dir)
        except (AssertionError, KeyError, TypeError) as exc:
            raise ContractError("N=1 child manifest input identity differs") from exc
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        try:
            verify_record(f"N=1 child output {index}", record, base_dir=stage_dir)
        except (AssertionError, KeyError, TypeError) as exc:
            raise ContractError("N=1 child manifest output identity differs") from exc
    _, summary_path = _verified_manifest_record(manifest, "inputs", "resolved_population_contract", stage_dir)
    population = _load(summary_path)
    if population.get("execution_population", {}).get("particle_count") != 1:
        raise ContractError("N=1 producer must freeze exactly one particle")
    output_records = manifest.get("outputs", [])
    named_outputs = {
        Path(str(record.get("path", ""))).name: record for record in output_records if isinstance(record, dict)
    }
    if set(named_outputs).issuperset({"summary.json", "single_flight_particle_checkpoints.csv"}) is False:
        raise ContractError("N=1 child summary or checkpoints output is missing")
    summary_record = named_outputs["summary.json"]
    checkpoint_record = named_outputs["single_flight_particle_checkpoints.csv"]
    for label, record in (
        ("summary", summary_record),
        ("checkpoints", checkpoint_record),
    ):
        try:
            verify_record(f"N=1 child {label}", record, base_dir=stage_dir)
        except (AssertionError, KeyError, TypeError) as exc:
            raise ContractError(f"N=1 child {label} identity differs") from exc
    summary_path = record_path(summary_record, base_dir=stage_dir)
    checkpoint_path = record_path(checkpoint_record, base_dir=stage_dir)
    summary = _load(summary_path)
    particle_id, census, failures = _n1_gate_assessment(summary, checkpoint_path)
    stage_config = _load(stage_dir / "run_config.json")
    parameters = stage_config.get("parameters", {})
    required_identities = {
        "candidate_sha256": parameters.get("three_zone_candidate_sha256"),
        "layout_profile_id": parameters.get("layout_profile_id"),
        "architecture_generation_id": parameters.get("architecture_generation_id"),
        "topology_id": parameters.get("three_zone_topology_id"),
        "geometry_id": parameters.get("three_zone_geometry_id"),
        "frontend_electrode_topology_id": parameters.get("three_zone_frontend_electrode_topology_id"),
        "accelerator_field_profile_id": parameters.get("accelerator_field_profile_id"),
        "field_id": parameters.get("three_zone_field_id"),
        "resolved_region_field_semantic_sha256": parameters.get("resolved_region_field_semantic_sha256"),
        "source_identity_sha256": _canonical_sha256(source_identity),
    }
    if any(not isinstance(value, str) or not value for value in required_identities.values()):
        raise ContractError("N=1 child three-zone identity bundle is incomplete")
    decision = "PASS" if not failures else "FAIL"
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_three_zone_n1_solver_authorization_receipt",
        "gate_id": producer["three_zone_solver_gate"]["gate_id"],
        "decision": decision,
        "authorization_status": ("N100_SOLVER_AUTHORIZED" if decision == "PASS" else "N100_SOLVER_NOT_AUTHORIZED"),
        "campaign": {
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": repository_text_sha256(campaign_path),
        },
        "producer": {
            "experiment_id": producer["experiment_id"],
            "experiment_row_sha256": _canonical_sha256(producer),
            "integration_run_id": integration_run_id,
            "transport_run_id": stage["run_id"],
            "transport_manifest": _file_binding(manifest_path, workspace_root),
        },
        "authorized_successor": {
            "experiment_id": successor["experiment_id"],
            "experiment_row_sha256": _canonical_sha256(successor),
            "particle_count": 100,
        },
        "identities": required_identities,
        "evidence": {
            "summary": _file_binding(summary_path, workspace_root),
            "checkpoints": _file_binding(checkpoint_path, workspace_root),
            "particle_id": particle_id,
            "census": census,
            "required_event_sequence": list(N1_REQUIRED_EVENTS),
        },
        "failure_codes": failures,
        "claim_limit": (
            "N=1 solver-path authorization for the hash-bound N=100 successor only; "
            "no resolution, transmission, engineering-qualification, or Formal claim."
        ),
        "formal_gate_passed": False,
    }
    validate_schema(receipt, N1_RECEIPT_SCHEMA)
    output = parent_run_dir / "results" / N1_RECEIPT_NAME
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return output, receipt


def _verify_stage(
    *,
    run_path: Path,
    run_id: str,
    project_id: str,
    mode: str,
    workspace_root: Path,
) -> dict[str, str]:
    manifest_path = run_path / "run_manifest.json"
    manifest = _load(manifest_path)
    expected = {
        "role": "simulation_run_manifest",
        "run_id": run_id,
        "project": project_id,
        "mode": mode,
        "status": "success",
    }
    if any(manifest.get(name) != value for name, value in expected.items()):
        raise ContractError(f"family stage identity/status differs: {run_id}")
    try:
        verify_record("run_config", manifest["run_config"])
    except (AssertionError, KeyError) as exc:
        raise ContractError(f"family stage run_config is invalid: {run_id}") from exc
    if Path(manifest["run_config"]["path"]).resolve().parent != run_path:
        raise ContractError(f"family stage run_config is nonlocal: {run_id}")
    return {
        "phase": next(phase for phase, contract in ALL_STAGE_CONTRACTS.items() if contract["mode"] == mode),
        "run_id": run_id,
        "path": _portable(run_path, workspace_root),
        "manifest_sha256": file_sha256(manifest_path),
    }


def _verify_stage_chain_identity(
    *,
    stage: dict[str, str],
    workspace_root: Path,
    receipt: dict[str, Any],
    expected_source_field: str,
    expected_runtime_binding_sha256: str,
) -> None:
    run_config = _load(workspace_root / stage["path"] / "run_config.json")
    profile_id = receipt["connection_profile_id"]
    source_branch_id = receipt["source_branch_id"]
    source_identity = receipt["source_identity"]
    stage_source_identity = run_config.get(expected_source_field)
    if (
        stage_source_identity != source_identity
        or run_config.get("parameters", {}).get("connection_profile_id") != profile_id
        or run_config.get("parameters", {}).get("source_branch_id") != source_branch_id
    ):
        raise ContractError(f"family stage source/profile identity differs: {stage['phase']}")
    inputs = run_config.get("inputs", {})
    runtime_path = Path(inputs.get("runtime_binding", ""))
    resolved_path = Path(inputs.get("resolved_connection", ""))
    if (
        not runtime_path.is_file()
        or file_sha256(runtime_path) != expected_runtime_binding_sha256
        or not resolved_path.is_file()
        or file_sha256(resolved_path) != receipt["resolved_connection_sha256"]
    ):
        raise ContractError(f"family stage runtime/resolved identity differs: {stage['phase']}")
    if stage["phase"] == "single_flight_transport":
        population_path = Path(inputs.get("resolved_population_contract", ""))
        if (
            not population_path.is_file()
            or file_sha256(population_path) != receipt["resolved_population_contract_sha256"]
        ):
            raise ContractError("single-flight stage population authority differs")


def _resolved_connection_lineage(*, source_contract: dict[str, Any], source_branch_id: str) -> dict[str, Any]:
    """Resolve the non-authoritative upstream connection lineage."""

    if source_contract.get("authority_scope") != "connection_lineage_only":
        raise ContractError("staged source contract is not connection-lineage-only")
    branch = source_contract.get("source_branches", {}).get(source_branch_id)
    if not isinstance(branch, dict) or not isinstance(branch.get("source"), dict):
        raise ContractError("staged source contract connection lineage is missing")
    source = branch["source"]
    try:
        identity = {
            "source_branch_id": source_branch_id,
            "solver_id": branch["solver_id"],
            "run_id": source["run_id"],
            "project_id": branch["recorded_project_id"],
            "manifest_sha256": source["manifest"]["sha256"],
            "event_sha256": source["state"]["sha256"],
            "particle_source_sha256": source["particle_source"]["sha256"],
            "metadata_sha256": source["metadata"]["sha256"],
        }
    except (KeyError, TypeError) as exc:
        raise ContractError("staged source contract connection lineage is incomplete") from exc
    return {
        "authority_scope": "connection_lineage_only",
        "identity": identity,
    }


def publish_family_source_closure_run(
    *,
    repo_root: Path,
    workspace_root: Path,
    integration_run_dir: Path,
    receipt_path: Path,
    resolved_path: Path,
    plan_path: Path,
    budget_path: Path,
) -> Path:
    run_dir = integration_run_dir.resolve()
    run_id = run_dir.name
    validate_run_id(run_id)
    if not run_id.startswith(run_id[:15] + "__"):
        raise ContractError("family parent run ID has no canonical timestamp")
    receipt = _load(receipt_path)
    resolved = _load(resolved_path)
    plan = _load(plan_path)
    budget = _load(budget_path)
    execution_strategy = receipt.get("execution_strategy")
    if execution_strategy is None:
        raise ContractError("family parent execution strategy is missing")
    if execution_strategy not in STAGES_BY_STRATEGY:
        raise ContractError("family parent execution strategy is invalid")
    stage_contracts = STAGES_BY_STRATEGY[execution_strategy]
    if (
        receipt.get("role") != "integration_family_source_closure_execution_receipt"
        or receipt.get("integration_run_id") != run_id
        or receipt.get("execution_status") != "completed_pending_paired_analysis"
        or plan.get("integration_id") != INTEGRATION_ID
        or resolved.get("integration_id") != INTEGRATION_ID
    ):
        raise ContractError("family parent receipt or integration identity differs")
    campaign_keys = (
        "campaign_id",
        "experiment_id",
        "experiment_row_sha256",
        "launched_particle_count",
        "particle_count",
        "policy_id",
        "retention_class",
    )
    if any(key not in receipt or key not in budget for key in campaign_keys):
        raise ContractError("family parent campaign identity is missing")
    profile_id = receipt["connection_profile_id"]
    source_branch_id = receipt["source_branch_id"]
    if (
        plan["selection"]["connection_profile_id"] != profile_id
        or resolved["selection"]["connection_profile_id"] != profile_id
        or budget["connection_profile_id"] != profile_id
        or budget["source_identity"] != receipt["source_identity"]
        or budget["execution_strategy"] != execution_strategy
        or budget["source_identity"]["source_branch_id"] != source_branch_id
        or any(budget[key] != receipt[key] for key in campaign_keys)
        or receipt.get("campaign_sha256") is None
        or receipt.get("campaign_path") is None
    ):
        raise ContractError("family parent campaign, profile or source identity differs")
    launched_particle_count = receipt["launched_particle_count"]
    particle_count = receipt["particle_count"]
    if (
        not isinstance(launched_particle_count, int)
        or not isinstance(particle_count, int)
        or particle_count < 1
        or launched_particle_count < particle_count
    ):
        raise ContractError("family parent particle census is invalid")
    campaign_path = (repo_root / receipt["campaign_path"]).resolve()
    resolved_source_contract_path = (
        receipt_path.parent / receipt.get("resolved_source_contract_filename", "")
    ).resolve()
    upstream_resolved_design_path = (
        receipt_path.parent / receipt.get("upstream_resolved_design_filename", "")
    ).resolve()
    resolved_population_contract_path = (
        receipt_path.parent / receipt.get("resolved_population_contract_filename", "")
    ).resolve()
    if (
        not campaign_path.is_relative_to(repo_root.resolve())
        or not campaign_path.is_file()
        or repository_text_sha256(campaign_path) != receipt["campaign_sha256"]
        or resolved_source_contract_path.parent != receipt_path.parent.resolve()
        or not resolved_source_contract_path.is_file()
        or file_sha256(resolved_source_contract_path) != receipt.get("resolved_source_contract_sha256")
        or upstream_resolved_design_path.parent != receipt_path.parent.resolve()
        or not upstream_resolved_design_path.is_file()
        or file_sha256(upstream_resolved_design_path) != receipt.get("upstream_resolved_design_sha256")
    ):
        raise ContractError("family parent frozen campaign inputs differ")
    campaign = _load(campaign_path)
    n1_gate_pair = _n1_gate_pair(campaign, str(receipt["experiment_id"]))
    population = None
    if execution_strategy == "simion_single_flight":
        if (
            resolved_population_contract_path.parent != receipt_path.parent.resolve()
            or not resolved_population_contract_path.is_file()
            or file_sha256(resolved_population_contract_path) != receipt.get("resolved_population_contract_sha256")
        ):
            raise ContractError("family parent resolved population authority differs")
        population = _load(resolved_population_contract_path)
        if (
            population.get("role") != "rf_oatof_resolved_population_contract"
            or population.get("campaign_id") != receipt["campaign_id"]
            or population.get("experiment_id") != receipt["experiment_id"]
            or population.get("experiment_row_sha256") != receipt["experiment_row_sha256"]
            or population.get("execution_population", {}).get("particle_count") != launched_particle_count
        ):
            raise ContractError("family parent population contract identity differs")
    staged_single_flight = (
        execution_strategy == "simion_single_flight" and population.get("source_release_mode") == "staged_grid2_restart"
    )
    connection_lineage = None
    if staged_single_flight:
        source_contract = _load(resolved_source_contract_path)
        connection_lineage = _resolved_connection_lineage(
            source_contract=source_contract,
            source_branch_id=source_branch_id,
        )
        if receipt.get("connection_lineage") != connection_lineage:
            raise ContractError("staged parent connection lineage differs")
    upstream_project_id = resolved["selection"]["upstream_project_id"]
    stage_run_ids = receipt.get("stage_run_ids")
    stage_runtime_binding_sha256s = receipt.get("stage_runtime_binding_sha256s")
    if (
        not isinstance(stage_run_ids, dict)
        or set(stage_run_ids) != set(stage_contracts)
        or not isinstance(stage_runtime_binding_sha256s, dict)
        or set(stage_runtime_binding_sha256s) != set(stage_contracts)
    ):
        raise ContractError("family receipt stage identities are incomplete")
    for phase in stage_contracts:
        validate_run_id(stage_run_ids[phase])
        expected_run_id = run_id[:15] + stage_contracts[phase]["run_stem"] + str(particle_count) + _retry_suffix(run_id)
        binding_hash = stage_runtime_binding_sha256s[phase]
        if (
            stage_run_ids[phase] != expected_run_id
            or not isinstance(binding_hash, str)
            or len(binding_hash) != 64
            or any(character not in "0123456789ABCDEF" for character in binding_hash)
        ):
            raise ContractError(f"family receipt stage runtime-binding SHA is invalid: {phase}")
    stage_owner = stage_project_id(execution_strategy, upstream_project_id)
    stage_root = workspace_root / "artifacts" / "projects" / stage_owner / "runs"
    stages = []
    for phase, contract in stage_contracts.items():
        stage_run_id = stage_run_ids[phase]
        stages.append(
            _verify_stage(
                run_path=stage_root / stage_run_id,
                run_id=stage_run_id,
                project_id=stage_owner,
                mode=contract["mode"],
                workspace_root=workspace_root,
            )
        )

    first_stage_config = _load(workspace_root / stages[0]["path"] / "run_config.json")
    first_source_field = (
        "source_identity"
        if staged_single_flight
        else ("source_particle_identity" if execution_strategy == "staged_three_stage" else "upstream_source_identity")
    )
    pre_pulse_source = first_stage_config.get(first_source_field)
    if pre_pulse_source != receipt["source_identity"]:
        raise ContractError("family first stage and parent source identities differ")
    if staged_single_flight:
        if (
            first_stage_config.get("connection_lineage") != connection_lineage
            or "upstream_source_identity" in first_stage_config
        ):
            raise ContractError("staged first-stage connection lineage differs")
    _verify_stage_chain_identity(
        stage=stages[0],
        workspace_root=workspace_root,
        receipt=receipt,
        expected_source_field=first_source_field,
        expected_runtime_binding_sha256=stage_runtime_binding_sha256s[stages[0]["phase"]],
    )
    for stage in stages[1:]:
        _verify_stage_chain_identity(
            stage=stage,
            workspace_root=workspace_root,
            receipt=receipt,
            expected_source_field="upstream_source_identity",
            expected_runtime_binding_sha256=stage_runtime_binding_sha256s[stage["phase"]],
        )

    analyzer_summary = _load(workspace_root / stages[-1]["path"] / "summary.json")
    n1_authorization_path = None
    n1_authorization = None
    if n1_gate_pair is not None:
        if execution_strategy != "simion_single_flight" or particle_count != 1:
            raise ContractError("N=1 solver gate requires one-particle single flight")
        n1_authorization_path, n1_authorization = _publish_n1_solver_authorization_receipt(
            campaign=campaign,
            campaign_path=campaign_path,
            producer=n1_gate_pair[0],
            successor=n1_gate_pair[1],
            integration_run_id=run_id,
            stage=stages[-1],
            workspace_root=workspace_root,
            parent_run_dir=run_dir,
            source_identity=receipt["source_identity"],
        )
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": "multipole_family_source_closure",
        "project_root": str(workspace_root),
        "inputs": {
            "campaign": _portable(campaign_path, workspace_root),
            "execution_receipt": _portable(receipt_path, workspace_root),
            "resolved_connection": _portable(resolved_path, workspace_root),
            "composition_plan": _portable(plan_path, workspace_root),
            "resolved_source_contract": _portable(resolved_source_contract_path, workspace_root),
            "upstream_resolved_design": _portable(upstream_resolved_design_path, workspace_root),
            "resolved_engineering_budget": _portable(budget_path, workspace_root),
            **{f"{stage['phase']}_manifest": (stage["path"] + "/run_manifest.json") for stage in stages},
        },
        "connection_profile_id": profile_id,
        "campaign_path": receipt["campaign_path"],
        "campaign_sha256": receipt["campaign_sha256"],
        "campaign_id": receipt["campaign_id"],
        "experiment_id": receipt["experiment_id"],
        "experiment_row_sha256": receipt["experiment_row_sha256"],
        "source_branch_id": source_branch_id,
        "execution_strategy": execution_strategy,
        "launched_particle_count": launched_particle_count,
        "particle_count": particle_count,
        "policy_id": receipt["policy_id"],
        **(
            {
                "source_identity": receipt["source_identity"],
                "connection_lineage": connection_lineage,
            }
            if staged_single_flight
            else {"source_particle_identity": receipt["source_identity"]}
        ),
        "stage_runtime_binding_sha256s": stage_runtime_binding_sha256s,
        "stage_runs": stages,
        "artifact_retention": {
            "policy_version": 1,
            "class": receipt["retention_class"],
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "integration_family_source_closure_summary",
        "status": "success",
        "connection_profile_id": profile_id,
        "campaign_id": receipt["campaign_id"],
        "experiment_id": receipt["experiment_id"],
        "experiment_row_sha256": receipt["experiment_row_sha256"],
        "source_branch_id": source_branch_id,
        "launched_particle_count": launched_particle_count,
        "particle_count": particle_count,
        "policy_id": receipt["policy_id"],
        "execution_strategy": execution_strategy,
        "stage_runs_verified": len(stages),
        "census": analyzer_summary.get("census"),
        "claim_status": "FUNCTIONAL_SCREEN_ONLY",
        "paired_analysis_status": "NOT_RUN",
        **(
            {
                "three_zone_solver_authorization": {
                    "decision": n1_authorization["decision"],
                    "authorization_status": n1_authorization["authorization_status"],
                    "receipt": "results/" + N1_RECEIPT_NAME,
                    "receipt_sha256": file_sha256(n1_authorization_path),
                }
            }
            if n1_authorization_path is not None
            else {}
        ),
        "formal_gate_passed": False,
    }
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    run_config_path.write_text(
        json.dumps(run_config, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path = run_dir / "run_manifest.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.write_run_manifest",
            "--run-config",
            str(run_config_path),
            "--manifest",
            str(manifest_path),
            "--status",
            "success",
            "--software",
            f"Python {sys.version_info.major}.{sys.version_info.minor}",
            "--output",
            str(summary_path),
            *(["--output", str(n1_authorization_path)] if n1_authorization_path is not None else []),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            "family parent manifest publication failed: " + (completed.stdout + completed.stderr).strip()
        )
    from .assess_full_domain_width_numerics import (
        is_full_domain_width_numerics_campaign,
        publish_completed_assessment,
    )

    if is_full_domain_width_numerics_campaign(campaign):
        final_experiment = max(campaign["experiments"], key=lambda row: row["sequence"])["experiment_id"]
        if receipt["experiment_id"] == final_experiment:
            publish_completed_assessment(
                repo_root=repo_root,
                workspace_root=workspace_root,
                campaign_path=campaign_path,
            )
    return manifest_path


def publish_family_source_closure_failure(
    *,
    repo_root: Path,
    workspace_root: Path,
    integration_run_dir: Path,
    resolved_path: Path,
    plan_path: Path,
    budget_path: Path,
    terminal_status: str,
    reason: str,
) -> Path:
    """Terminalize a prepared parent run when its governed child chain fails."""

    if terminal_status not in {"failed", "interrupted"}:
        raise ContractError("failure publication requires failed or interrupted")
    run_dir = integration_run_dir.resolve()
    run_id = run_dir.name
    validate_run_id(run_id)
    resolved = _load(resolved_path)
    plan = _load(plan_path)
    budget = _load(budget_path)
    profile_id = plan.get("selection", {}).get("connection_profile_id")
    if (
        resolved.get("integration_id") != INTEGRATION_ID
        or plan.get("integration_id") != INTEGRATION_ID
        or resolved.get("selection", {}).get("connection_profile_id") != profile_id
        or budget.get("connection_profile_id") != profile_id
    ):
        raise ContractError("failed parent prepared identities differ")
    frozen_names = (
        "composition_plan.json",
        "resolved_connection.json",
        "resolved_engineering_budget.json",
        "resolved_source_contract.json",
        "upstream_resolved_design.json",
        "resolved_oatof_geometry.json",
        "resolved_single_flight_pulse_schedule.json",
        "resolved_population_contract.json",
    )
    frozen_inputs = {
        name.removesuffix(".json"): _portable(run_dir / name, workspace_root)
        for name in frozen_names
        if (run_dir / name).is_file()
    }
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": "multipole_family_source_closure",
        "project_root": str(workspace_root.resolve()),
        "inputs": frozen_inputs,
        "connection_profile_id": profile_id,
        "campaign_id": budget.get("campaign_id"),
        "experiment_id": budget.get("experiment_id"),
        "experiment_row_sha256": budget.get("experiment_row_sha256"),
        "execution_strategy": budget.get("execution_strategy"),
        "launched_particle_count": budget.get("launched_particle_count"),
        "particle_count": budget.get("particle_count"),
        "artifact_retention": {
            "policy_version": 1,
            "class": budget.get("retention_class", "compact"),
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "integration_family_source_closure_summary",
        "status": terminal_status,
        "reason": reason,
        "failure_stage": "governed_child_execution_or_publication",
        "threshold_result_eligible": False,
        "connection_profile_id": profile_id,
        "campaign_id": budget.get("campaign_id"),
        "experiment_id": budget.get("experiment_id"),
        "execution_strategy": budget.get("execution_strategy"),
        "formal_gate_passed": False,
    }
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    run_config_path.write_text(json.dumps(run_config, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    manifest_path = run_dir / "run_manifest.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.write_run_manifest",
            "--run-config",
            str(run_config_path),
            "--manifest",
            str(manifest_path),
            "--status",
            terminal_status,
            "--software",
            f"Python {sys.version_info.major}.{sys.version_info.minor}",
            "--output",
            str(summary_path),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            "failed family parent manifest publication failed: " + (completed.stdout + completed.stderr).strip()
        )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--integration-run-dir", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--resolved-connection", required=True, type=Path)
    parser.add_argument("--composition-plan", required=True, type=Path)
    parser.add_argument(
        "--resolved-engineering-budget",
        required=True,
        type=Path,
    )
    parser.add_argument("--terminal-status", choices=("failed", "interrupted"))
    parser.add_argument("--failure-reason")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.failure_reason is not None:
        if args.terminal_status is None or args.receipt is not None:
            parser.error("failure publication requires status and forbids receipt")
        manifest = publish_family_source_closure_failure(
            repo_root=repo_root,
            workspace_root=repo_root.parent,
            integration_run_dir=args.integration_run_dir.resolve(),
            resolved_path=args.resolved_connection.resolve(),
            plan_path=args.composition_plan.resolve(),
            budget_path=args.resolved_engineering_budget.resolve(),
            terminal_status=args.terminal_status,
            reason=args.failure_reason,
        )
    else:
        if args.receipt is None or args.terminal_status is not None:
            parser.error("success publication requires receipt only")
        manifest = publish_family_source_closure_run(
            repo_root=repo_root,
            workspace_root=repo_root.parent,
            integration_run_dir=args.integration_run_dir.resolve(),
            receipt_path=args.receipt.resolve(),
            resolved_path=args.resolved_connection.resolve(),
            plan_path=args.composition_plan.resolve(),
            budget_path=args.resolved_engineering_budget.resolve(),
        )
    print(f"FAMILY_SOURCE_CLOSURE_PUBLICATION=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
