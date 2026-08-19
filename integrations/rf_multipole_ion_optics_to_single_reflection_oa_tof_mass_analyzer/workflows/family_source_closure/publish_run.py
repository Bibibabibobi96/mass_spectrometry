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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import record_path, verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    publish_manifest,
    write_pending_json,
)


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


def _single_flight_run_stem(
    resolved: dict[str, Any], *, pulse_timing_internal_stage: str = "",
) -> str:
    try:
        raw_gap_mm = resolved["connector"]["length_mm"]
        if isinstance(raw_gap_mm, bool):
            raise ValueError
        gap_mm = Decimal(str(raw_gap_mm))
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise ContractError("resolved connector length is missing") from exc
    if not gap_mm.is_finite() or gap_mm < 0:
        raise ContractError("resolved connector length is invalid")
    gap_label = format(gap_mm, "f")
    if "." in gap_label:
        gap_label = gap_label.rstrip("0").rstrip(".")
    gap_label = gap_label.replace(".", "p")
    if not gap_label:
        gap_label = "0"
    role = (
        "rf-oatof-pulse-screen"
        if pulse_timing_internal_stage == "pulse_timing_discovery"
        else "rf-oatof-single-flight"
    )
    return f"__sim__simion__{role}-gap{gap_label}__n"


N1_RECEIPT_SCHEMA = "rf_oatof_three_zone_n1_solver_authorization_receipt.schema.json"
N1_RECEIPT_NAME = "three_zone_n1_solver_authorization_receipt.json"
VERIFIED_PULSE_RECEIPT_NAME = "verified_pulse_timing_receipt.json"
PULSE_TRANSITION_NAME = "pulse_timing_transition.json"
PULSE_PUBLICATION_REPLAY_MODE = "verified_pulse_timing_publication_replay"
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


def _verified_stage_record(
    manifest: dict[str, Any],
    *,
    collection: str,
    name: str,
    run_dir: Path,
) -> Path:
    records = manifest.get(collection)
    if collection == "inputs":
        record = records.get(name) if isinstance(records, dict) else None
    else:
        matches = [
            item for item in records or []
            if isinstance(item, dict) and Path(str(item.get("path", ""))).name == name
        ]
        record = matches[0] if len(matches) == 1 else None
    if not isinstance(record, dict):
        raise ContractError(f"pulse screening {collection}.{name} is missing")
    try:
        verify_record(f"pulse screening {collection}.{name}", record, base_dir=run_dir)
        path = record_path(record, base_dir=run_dir).resolve()
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(
            f"pulse screening {collection}.{name} identity differs"
        ) from exc
    if not path.is_relative_to(run_dir.resolve()):
        raise ContractError(f"pulse screening {collection}.{name} is nonlocal")
    return path


def _publish_detector_blind_pulse_selection(
    *,
    repo_root: Path,
    workspace_root: Path,
    parent_run_dir: Path,
    stage: dict[str, Any],
    resolved_connection_path: Path,
    resolved_source_path: Path,
    resolved_population_path: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    from ...analysis.select_real_field_pulse_time import select_and_write

    child_dir = (workspace_root / stage["path"]).resolve()
    child_manifest_path = child_dir / "run_manifest.json"
    if file_sha256(child_manifest_path) != stage.get("manifest_sha256"):
        raise ContractError("pulse screening child manifest identity differs")
    child_manifest = _load(child_manifest_path)
    inputs = {
        name: _verified_stage_record(
            child_manifest, collection="inputs", name=name, run_dir=child_dir
        )
        for name in (
            "configuration",
            "resolved_connection",
            "resolved_source_contract",
            "resolved_population_contract",
            "oatof_resolved_geometry",
            "pulse_schedule",
            "mother_particle_source",
            "pre_pulse_time_series_contract",
        )
    }
    state_table = _verified_stage_record(
        child_manifest,
        collection="outputs",
        name="pre_pulse_time_series_states.csv",
        run_dir=child_dir,
    )
    screening_receipt = _verified_stage_record(
        child_manifest,
        collection="outputs",
        name="pre_pulse_time_series_screening_receipt.json",
        run_dir=child_dir,
    )
    parent_identities = {
        "resolved_connection": resolved_connection_path,
        "resolved_source_contract": resolved_source_path,
        "resolved_population_contract": resolved_population_path,
    }
    if any(
        file_sha256(inputs[name]) != file_sha256(path)
        for name, path in parent_identities.items()
    ):
        raise ContractError("pulse screening child and parent identities differ")
    selector_source = (
        repo_root
        / "integrations"
        / INTEGRATION_ID
        / "analysis"
        / "select_real_field_pulse_time.py"
    )
    candidate_table = (
        parent_run_dir / "results" / "detector_blind_pulse_timing_candidates.csv"
    )
    candidate_receipt = (
        parent_run_dir
        / "results"
        / "detector_blind_pulse_timing_candidate_receipt.json"
    )
    receipt = select_and_write(
        state_table_path=state_table,
        screening_contract_path=inputs["pre_pulse_time_series_contract"],
        screening_receipt_path=screening_receipt,
        resolved_population_path=resolved_population_path,
        population_table_path=inputs["mother_particle_source"],
        resolved_source_path=resolved_source_path,
        resolved_connection_path=resolved_connection_path,
        screening_manifest_path=child_manifest_path,
        selector_source_path=selector_source,
        geometry_path=inputs["oatof_resolved_geometry"],
        single_flight_configuration_path=inputs["configuration"],
        ballistic_schedule_path=inputs["pulse_schedule"],
        candidate_table_path=candidate_table,
        receipt_path=candidate_receipt,
    )
    return candidate_table, candidate_receipt, receipt


def _publish_pulse_timing_transition(
    *, workspace_root: Path, parent_run_dir: Path, stage: dict[str, Any],
    candidate_receipt_path: Path, candidate_receipt: dict[str, Any],
) -> Path:
    """Publish the manifest-ready handoff from discovery to confirmation."""

    child_manifest_path = (
        workspace_root / stage["path"] / "run_manifest.json"
    ).resolve()
    transition = {
        "schema_version": 1,
        "role": "rf_oatof_pulse_timing_transition",
        "status": "candidate_selected_confirmation_required",
        "discovery_run_id": parent_run_dir.name,
        "content_key": candidate_receipt["content_key"],
        "candidate_selection_receipt": _file_binding(
            candidate_receipt_path, workspace_root
        ),
        "screening_child_manifest": _file_binding(
            child_manifest_path, workspace_root
        ),
    }
    validate_schema(transition, "rf_oatof_pulse_timing_transition.schema.json")
    path = parent_run_dir / "results" / PULSE_TRANSITION_NAME
    path.write_text(json.dumps(transition, indent=2) + "\n", encoding="utf-8")
    return path


def _pulse_confirmation_census_is_physical(census: dict[str, Any]) -> bool:
    """Validate snapshot and crossing-event censuses without conflating them."""

    names = (
        "launched", "multipole_handoff", "pre_pulse_state",
        "accelerator_grid1_forward", "accelerator_intermediate2_forward",
        "local_accelerator_exit", "detector_crossing",
    )
    counts = {name: census.get(name) for name in names}
    return (
        all(isinstance(value, int) for value in counts.values())
        and counts["launched"] >= counts["multipole_handoff"]
        and counts["launched"] >= counts["pre_pulse_state"]
        and counts["launched"] >= counts["accelerator_grid1_forward"]
        and counts["accelerator_grid1_forward"]
        >= counts["accelerator_intermediate2_forward"]
        and counts["accelerator_intermediate2_forward"]
        >= counts["local_accelerator_exit"]
        and counts["local_accelerator_exit"] >= counts["detector_crossing"] > 0
    )


def _publish_verified_pulse_receipt(
    *, workspace_root: Path, parent_run_dir: Path, stage: dict[str, Any],
) -> tuple[Path, dict[str, Any]] | None:
    """Publish functional reuse authority after one successful pulse-on flight."""

    child_dir = (workspace_root / stage["path"]).resolve()
    child_manifest_path = child_dir / "run_manifest.json"
    if file_sha256(child_manifest_path) != stage.get("manifest_sha256"):
        raise ContractError("pulse confirmation child manifest identity differs")
    child_manifest = _load(child_manifest_path)
    if not isinstance(child_manifest.get("inputs"), dict) or (
        "pulse_schedule" not in child_manifest["inputs"]
    ):
        return None
    schedule_path = _verified_stage_record(
        child_manifest, collection="inputs", name="pulse_schedule", run_dir=child_dir
    )
    schedule = _load(schedule_path)
    authority = schedule.get("execution_authority")
    if not isinstance(authority, dict):
        return None
    if authority.get("mode") != "detector_blind_candidate_confirmation_v1":
        raise ContractError("pulse confirmation schedule authority mode differs")
    summary_path = _verified_stage_record(
        child_manifest, collection="outputs", name="summary.json", run_dir=child_dir
    )
    child_summary = _load(summary_path)
    selected_time_us = float(schedule["pulse_effective_time_us"])
    census = child_summary.get("census", {})
    names = (
        "launched", "multipole_handoff", "pre_pulse_state",
        "accelerator_grid1_forward", "accelerator_intermediate2_forward",
        "local_accelerator_exit", "detector_crossing",
    )
    if (
        child_summary.get("role") != "rf_oatof_simion_single_flight_summary"
        or child_summary.get("status") != "success"
        or not math.isclose(
            float(child_summary.get("pulse_effective_time_us")), selected_time_us,
            rel_tol=0.0, abs_tol=1e-9,
        )
        or not _pulse_confirmation_census_is_physical(census)
    ):
        raise ContractError("pulse confirmation flight evidence differs")

    def authority_path(name: str) -> Path:
        record = authority[name]
        path = (workspace_root / record["path"]).resolve()
        if (
            not path.is_relative_to(workspace_root.resolve())
            or not path.is_file()
            or file_sha256(path) != record["sha256"]
        ):
            raise ContractError(f"pulse confirmation {name} identity differs")
        return path

    candidate_parent = authority_path("candidate_parent_manifest")
    candidate_receipt = authority_path("candidate_selection_receipt")
    if "pilot_verified_receipt" in authority:
        authority_path("pilot_verified_receipt")
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_verified_pulse_timing_receipt",
        "status": "success",
        "qualification": "FUNCTIONAL_ONLY",
        "decision": "PASS_FOR_IDENTICAL_IDENTITY_REUSE",
        "reusable_verified_pulse": True,
        "content_key": authority["content_key"],
        "selected_time_us": selected_time_us,
        "candidate_authority": {
            "parent_manifest": _file_binding(candidate_parent, workspace_root),
            "selection_receipt": _file_binding(candidate_receipt, workspace_root),
            "selection_preregistered": authority["selection_preregistered"],
        },
        "verification_authority": {
            "child_manifest": _file_binding(child_manifest_path, workspace_root),
            "pulse_schedule": _file_binding(schedule_path, workspace_root),
            "summary": _file_binding(summary_path, workspace_root),
        },
        "census": {name: census[name] for name in names},
        "claim_limit": "IDENTICAL_IDENTITY_FUNCTIONAL_REUSE_ONLY",
    }
    validate_schema(receipt, "rf_oatof_verified_pulse_timing_receipt.schema.json")
    path = parent_run_dir / "results" / VERIFIED_PULSE_RECEIPT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path, receipt


def _publish_verified_pulse_cache(
    *, workspace_root: Path, receipt: dict[str, Any],
) -> Path:
    """Publish a deletable content-addressed copy of verified pulse authority."""

    cache_dir = (
        workspace_root
        / "artifacts"
        / "projects"
        / INTEGRATION_ID
        / "cache"
        / "verified_pulse"
        / receipt["content_key"]
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / VERIFIED_PULSE_RECEIPT_NAME
    if path.exists():
        existing = _load(path)
        validate_schema(existing, "rf_oatof_verified_pulse_timing_receipt.schema.json")
        if existing != receipt:
            raise ContractError("verified pulse cache content differs")
        return path
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def publish_verified_pulse_publication_replay(
    *,
    repo_root: Path,
    workspace_root: Path,
    replay_run_dir: Path,
    failed_parent_manifest_path: Path,
    execution_receipt_path: Path,
    resolved_path: Path,
    plan_path: Path,
    budget_path: Path,
) -> Path:
    """Republish verified pulse evidence from an immutable successful child."""

    replay_run_dir = replay_run_dir.resolve()
    run_identity = validate_run_id(replay_run_dir.name)
    if run_identity["activity"] != "analysis" or run_identity["scope"] != "python":
        raise ContractError("pulse publication replay requires an analysis/python run ID")
    if replay_run_dir.exists():
        raise ContractError("pulse publication replay run already exists")

    failed_parent_manifest_path = failed_parent_manifest_path.resolve()
    failed_parent_dir = failed_parent_manifest_path.parent
    execution_receipt_path = execution_receipt_path.resolve()
    resolved_path = resolved_path.resolve()
    plan_path = plan_path.resolve()
    budget_path = budget_path.resolve()
    if any(
        path.parent != failed_parent_dir
        for path in (execution_receipt_path, resolved_path, plan_path, budget_path)
    ):
        raise ContractError("pulse publication replay inputs are not from one parent run")

    failed_manifest = _load(failed_parent_manifest_path)
    receipt = _load(execution_receipt_path)
    if (
        failed_manifest.get("role") != "simulation_run_manifest"
        or failed_manifest.get("project") != INTEGRATION_ID
        or failed_manifest.get("mode") != "multipole_family_source_closure"
        or failed_manifest.get("status") != "failed"
        or receipt.get("role") != "integration_family_source_closure_execution_receipt"
        or receipt.get("integration_run_id") != failed_manifest.get("run_id")
        or receipt.get("execution_strategy") != "simion_single_flight"
        or receipt.get("execution_status") != "completed_pending_paired_analysis"
    ):
        raise ContractError("pulse publication replay parent authority differs")
    try:
        verify_record("failed parent run_config", failed_manifest["run_config"])
        for record in failed_manifest.get("outputs", []):
            verify_record("failed parent output", record)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("pulse publication replay failed parent identity differs") from exc

    parent_inputs = failed_manifest.get("inputs")
    expected_inputs = {
        "resolved_connection": resolved_path,
        "composition_plan": plan_path,
        "resolved_engineering_budget": budget_path,
    }
    if not isinstance(parent_inputs, dict):
        raise ContractError("pulse publication replay parent inputs are missing")
    for name, expected_path in expected_inputs.items():
        record = parent_inputs.get(name)
        try:
            verify_record(name, record)
        except (AssertionError, KeyError, TypeError) as exc:
            raise ContractError(f"pulse publication replay {name} identity differs") from exc
        if record_path(record) != expected_path:
            raise ContractError(f"pulse publication replay {name} path differs")
    prepared_sha = {
        "resolved_connection_sha256": file_sha256(resolved_path),
        "composition_plan_sha256": file_sha256(plan_path),
        "resolved_engineering_budget_sha256": file_sha256(budget_path),
    }
    manifest_sha = {
        f"{name}_sha256": parent_inputs[name]["sha256"]
        for name in expected_inputs
    }
    if any(
        prepared_sha[name] not in {receipt.get(name), manifest_sha[name]}
        for name in prepared_sha
    ):
        raise ContractError("pulse publication replay prepared identity differs")

    stage_run_ids = receipt.get("stage_run_ids")
    stage_binding_sha256s = receipt.get("stage_runtime_binding_sha256s")
    if (
        not isinstance(stage_run_ids, dict)
        or set(stage_run_ids) != {"single_flight_transport"}
        or not isinstance(stage_binding_sha256s, dict)
        or set(stage_binding_sha256s) != {"single_flight_transport"}
    ):
        raise ContractError("pulse publication replay child authority is incomplete")
    child_run_id = stage_run_ids["single_flight_transport"]
    child_dir = (
        workspace_root
        / "artifacts"
        / "projects"
        / INTEGRATION_ID
        / "runs"
        / child_run_id
    )
    stage = _verify_stage(
        run_path=child_dir,
        run_id=child_run_id,
        project_id=INTEGRATION_ID,
        mode=SINGLE_FLIGHT_STAGES["single_flight_transport"]["mode"],
        workspace_root=workspace_root,
    )
    _verify_stage_chain_identity(
        stage=stage,
        workspace_root=workspace_root,
        receipt=receipt,
        expected_source_field="upstream_source_identity",
        expected_runtime_binding_sha256=stage_binding_sha256s["single_flight_transport"],
    )

    replay_run_dir.mkdir(parents=True, exist_ok=False)
    verified_result = _publish_verified_pulse_receipt(
        workspace_root=workspace_root,
        parent_run_dir=replay_run_dir,
        stage=stage,
    )
    if verified_result is None:
        raise ContractError("pulse publication replay child has no confirmation authority")
    verified_path, verified_receipt = verified_result
    run_config = {
        "schema_version": 1,
        "role": "rf_oatof_verified_pulse_publication_replay_run_config",
        "run_id": replay_run_dir.name,
        "project": INTEGRATION_ID,
        "mode": PULSE_PUBLICATION_REPLAY_MODE,
        "project_root": str(workspace_root.resolve()),
        "inputs": {
            "failed_parent_manifest": _portable(failed_parent_manifest_path, workspace_root),
            "source_execution_receipt": _portable(execution_receipt_path, workspace_root),
            "confirmation_child_manifest": _portable(child_dir / "run_manifest.json", workspace_root),
            "publisher_source": _portable(Path(__file__), workspace_root),
        },
        "parameters": {
            "failed_parent_run_id": failed_manifest["run_id"],
            "confirmation_child_run_id": child_run_id,
            "selected_time_us": verified_receipt["selected_time_us"],
            "content_key": verified_receipt["content_key"],
            "solver_rerun": False,
        },
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_verified_pulse_publication_replay_summary",
        "status": "success",
        "qualification": "FUNCTIONAL_ONLY",
        "decision": verified_receipt["decision"],
        "selected_time_us": verified_receipt["selected_time_us"],
        "content_key": verified_receipt["content_key"],
        "confirmation_child_run_id": child_run_id,
        "solver_rerun": False,
        "formal_gate_passed": False,
    }
    run_config_path = replay_run_dir / "run_config.json"
    summary_path = replay_run_dir / "summary.json"
    manifest_path = replay_run_dir / "run_manifest.json"
    write_pending_json(run_config_path, run_config)
    write_pending_json(summary_path, summary)
    publish_manifest(
        repo_root=repo_root,
        run_config=run_config_path,
        manifest_path=manifest_path,
        status="success",
        outputs=(verified_path, summary_path),
        project=INTEGRATION_ID,
        mode=PULSE_PUBLICATION_REPLAY_MODE,
        label="verified pulse publication replay",
    )
    _publish_verified_pulse_cache(
        workspace_root=workspace_root,
        receipt=verified_receipt,
    )
    return manifest_path


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
    plan_arguments = {}
    for raw in plan.get("execution_steps", [{}])[0].get("arguments", []):
        if isinstance(raw, str) and "=" in raw:
            name, value = raw.split("=", 1)
            plan_arguments[name] = value
    pulse_timing_internal_stage = plan_arguments.get("pulse_timing_internal_stage")
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
        run_stem = (
            _single_flight_run_stem(
                resolved,
                pulse_timing_internal_stage=pulse_timing_internal_stage,
            )
            if phase == "single_flight_transport"
            else stage_contracts[phase]["run_stem"]
        )
        expected_run_id = run_id[:15] + run_stem + str(particle_count) + _retry_suffix(run_id)
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
    pulse_candidate_table_path = None
    pulse_candidate_receipt_path = None
    pulse_candidate_receipt = None
    pulse_transition_path = None
    if (
        campaign.get("pre_pulse_time_series_screening") is not None
        or pulse_timing_internal_stage == "pulse_timing_discovery"
    ):
        if execution_strategy != "simion_single_flight":
            raise ContractError("pulse screening requires single-flight execution")
        (
            pulse_candidate_table_path,
            pulse_candidate_receipt_path,
            pulse_candidate_receipt,
        ) = _publish_detector_blind_pulse_selection(
            repo_root=repo_root,
            workspace_root=workspace_root,
            parent_run_dir=run_dir,
            stage=stages[-1],
            resolved_connection_path=resolved_path,
            resolved_source_path=resolved_source_contract_path,
            resolved_population_path=resolved_population_contract_path,
        )
        if pulse_timing_internal_stage == "pulse_timing_discovery":
            pulse_transition_path = _publish_pulse_timing_transition(
                workspace_root=workspace_root,
                parent_run_dir=run_dir,
                stage=stages[-1],
                candidate_receipt_path=pulse_candidate_receipt_path,
                candidate_receipt=pulse_candidate_receipt,
            )
    verified_pulse_path = None
    verified_pulse = None
    if execution_strategy == "simion_single_flight":
        verified_result = _publish_verified_pulse_receipt(
            workspace_root=workspace_root,
            parent_run_dir=run_dir,
            stage=stages[-1],
        )
        if verified_result is not None:
            verified_pulse_path, verified_pulse = verified_result
            _publish_verified_pulse_cache(
                workspace_root=workspace_root,
                receipt=verified_pulse,
            )
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
            **(
                {
                    "pulse_timing_selector_source": _portable(
                        repo_root
                        / "integrations"
                        / INTEGRATION_ID
                        / "analysis"
                        / "select_real_field_pulse_time.py",
                        workspace_root,
                    )
                }
                if pulse_candidate_receipt is not None
                else {}
            ),
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
                "detector_blind_pulse_timing_candidate": {
                    "qualification": "candidate_selection",
                    "selection_preregistered": pulse_candidate_receipt[
                        "selection_preregistered"
                    ],
                    "selected_time_us": pulse_candidate_receipt["selected_time_us"],
                    "candidate_count": len(
                        pulse_candidate_receipt["candidates_ranked"]
                    ),
                    "population_denominator_count": pulse_candidate_receipt[
                        "population_denominator_count"
                    ],
                    "content_key": pulse_candidate_receipt["content_key"],
                    "candidate_table": (
                        "results/detector_blind_pulse_timing_candidates.csv"
                    ),
                    "candidate_table_sha256": file_sha256(
                        pulse_candidate_table_path
                    ),
                    "receipt": (
                        "results/"
                        "detector_blind_pulse_timing_candidate_receipt.json"
                    ),
                    "receipt_sha256": file_sha256(pulse_candidate_receipt_path),
                    "reusable_verified_pulse": False,
                }
            }
            if pulse_candidate_receipt is not None
            else {}
        ),
        **(
            {
                "verified_pulse_timing": {
                    "decision": verified_pulse["decision"],
                    "selected_time_us": verified_pulse["selected_time_us"],
                    "content_key": verified_pulse["content_key"],
                    "receipt": "results/" + VERIFIED_PULSE_RECEIPT_NAME,
                    "receipt_sha256": file_sha256(verified_pulse_path),
                    "reusable_verified_pulse": True,
                }
            }
            if verified_pulse is not None
            else {}
        ),
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
            *(
                ["--output", str(verified_pulse_path)]
                if verified_pulse_path is not None
                else []
            ),
            *(
                [
                    "--output",
                    str(pulse_candidate_table_path),
                    "--output",
                    str(pulse_candidate_receipt_path),
                ]
                if pulse_candidate_receipt is not None
                else []
            ),
            *(
                ["--output", str(pulse_transition_path)]
                if pulse_transition_path is not None
                else []
            ),
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
    parser.add_argument("--publication-replay-source-parent-manifest", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.publication_replay_source_parent_manifest is not None:
        if (
            args.receipt is None
            or args.terminal_status is not None
            or args.failure_reason is not None
        ):
            parser.error("publication replay requires receipt and forbids failure arguments")
        manifest = publish_verified_pulse_publication_replay(
            repo_root=repo_root,
            workspace_root=repo_root.parent,
            replay_run_dir=args.integration_run_dir.resolve(),
            failed_parent_manifest_path=(
                args.publication_replay_source_parent_manifest.resolve()
            ),
            execution_receipt_path=args.receipt.resolve(),
            resolved_path=args.resolved_connection.resolve(),
            plan_path=args.composition_plan.resolve(),
            budget_path=args.resolved_engineering_budget.resolve(),
        )
    elif args.failure_reason is not None:
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
