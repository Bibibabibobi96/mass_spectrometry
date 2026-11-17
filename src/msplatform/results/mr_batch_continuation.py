"""Read-only projection of sealed MR-TOF batch-continuation evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import record_path, require_completed_terminal_publication, verify_record

REQUIRED_INPUT_ROLES = (
    "resolved_iob_pose", "operating_point_lua", "frozen_source_fly2", "iob_builder", "iob_seed",
    "native_corridor_priority_contract", "flight_program", "voltage_waveforms", "mirror_cycle_counter",
    "voltage_map", "flight_launcher", "native_corridor_bank_cache_manifest", "native_system_runtime_bundle",
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def continuation_protection_projection(predecessor_run_dir: Path) -> dict[str, Any]:
    """Project manifest-bound run and batch paths for capacity and read guards.

    This does not hash batch payloads: the consumer verifies them after it
    has acquired the returned guards and rechecked this projection.
    """
    predecessor = predecessor_run_dir.resolve(strict=True)
    if predecessor.parent.name != "runs" or predecessor.parent.parent.parent.name != "projects":
        raise ContractError("continuation predecessor is outside the artifact project runs")
    projects_root = predecessor.parent.parent.parent
    runs: set[Path] = set()
    files: set[Path] = set()
    loaded: dict[Path, dict[str, Any]] = {}
    configs: dict[Path, dict[str, Any]] = {}

    def run_for(path: Path) -> Path:
        try:
            parts = path.resolve().relative_to(projects_root).parts
        except ValueError as exc:
            raise ContractError("continuation evidence is outside artifact projects") from exc
        if len(parts) < 4 or parts[1] != "runs":
            raise ContractError("continuation evidence is outside a project run")
        return projects_root / parts[0] / "runs" / parts[2]

    def load_run(run: Path) -> dict[str, Any]:
        run = run.resolve(strict=True)
        if run in loaded:
            return loaded[run]
        manifest_path, config_path = run / "run_manifest.json", run / "run_config.json"
        require_completed_terminal_publication(manifest_path)
        manifest = _load_object(manifest_path, "continuation protection manifest")
        if (manifest.get("role") != "simulation_run_manifest"
                or manifest.get("status") not in {"success", "failed", "interrupted"}
                or manifest.get("run_id") != run.name):
            raise ContractError("continuation protection requires a terminal owner run")
        record = manifest.get("run_config")
        if not isinstance(record, dict) or record_path(record, base_dir=run) != config_path:
            raise ContractError("continuation protection run configuration is unbound")
        verify_record("continuation protection run configuration", record, base_dir=run)
        config = _load_object(config_path, "continuation protection run configuration")
        if any(manifest.get(key) != config.get(key) for key in ("run_id", "project", "mode")):
            raise ContractError("continuation protection owner identity differs")
        if not isinstance(manifest.get("inputs"), dict) or not isinstance(manifest.get("outputs"), list):
            raise ContractError("continuation protection manifest inventory is invalid")
        loaded[run] = manifest
        configs[run] = config
        runs.add(run)
        files.update((manifest_path, config_path))
        return manifest

    batch_pattern = re.compile(r"(?:native_two_prism_flight__batch\d+\.log|joint_flight_batch_\d+\.log|owner_exit\.json|batch_receipt\.json|joint\.fly2|simion_batch_resource_usage\.json)$")
    pending, processed = [(predecessor, frozenset())], set()
    while pending:
        run, lineage = pending.pop()
        if run in lineage:
            raise ContractError("continuation ancestry contains a cycle")
        if run in processed:
            continue
        processed.add(run)
        next_lineage = lineage | {run}
        parent = load_run(run)
        planner_roles = set(REQUIRED_INPUT_ROLES) | {
            "trial_materialization", "prepared_joint_trial", "simion_execution_batch_plan",
            "simion_dispatch_request", "simion_resource_profiles", "simion_repository_dispatch_plan",
            "static_field_binding", "scalar_field_adapter", "observation_contract", "scientific_csv_writer", "scientific_event_locator",
        }
        for role in planner_roles:
            record = parent["inputs"].get(role)
            if isinstance(record, dict) and record.get("exists") and record.get("path"):
                path = record_path(record, base_dir=run)
                if not path.is_file():
                    raise ContractError(f"continuation planner input is missing: {role}")
                files.add(path)
        trial_record = parent["inputs"].get("prepared_joint_trial")
        if isinstance(trial_record, dict) and trial_record.get("exists"):
            verify_record("continuation prepared trial", trial_record, base_dir=run)
            trial = _load_object(record_path(trial_record, base_dir=run), "continuation prepared trial")
            for role in ("voltage_waveforms", "trajectory_contract"):
                record = trial.get(role)
                if isinstance(record, dict) and record.get("path"):
                    path = record_path(record, base_dir=run)
                    if not path.is_file():
                        raise ContractError(f"continuation prepared trial input is missing: {role}")
                    files.add(path)
        for role, record in parent["inputs"].items():
            if not re.fullmatch(r"reused_batch_\d+_(?:log|receipt|fly2|owner_exit|owner_manifest|scientific_events|scientific_trajectory)", role):
                continue
            if not isinstance(record, dict) or not record.get("exists") or not isinstance(record.get("sha256"), str):
                raise ContractError(f"continuation borrowed input is unbound: {role}")
            if not isinstance(configs[run].get("inputs", {}).get(role), str):
                raise ContractError(f"continuation borrowed input is absent from run configuration: {role}")
            path = record_path(record, base_dir=run)
            owner = run_for(path)
            source = load_run(owner)
            if owner != run:
                pending.append((owner, next_lineage))
            if role.endswith("_owner_manifest"):
                if path != owner / "run_manifest.json":
                    raise ContractError("continuation borrowed owner manifest differs")
                verify_record("continuation borrowed owner manifest", record, base_dir=run)
            else:
                candidates = list(source["inputs"].values()) + source["outputs"]
                matches = [item for item in candidates if isinstance(item, dict) and item.get("path")
                           and record_path(item, base_dir=owner) == path
                           and str(item.get("sha256", "")).upper() == str(record["sha256"]).upper()]
                if not matches or not path.is_file():
                    raise ContractError(f"continuation borrowed input is not bound by its source: {role}")
            files.add(path)
        for role in ("continuation_parent_manifest", "simion_whole_unit_replay_plan"):
            record = parent["inputs"].get(role)
            if record is None:
                continue
            verify_record("continuation ancestry " + role, record, base_dir=run)
            path = record_path(record, base_dir=run)
            files.add(path)
            if role == "continuation_parent_manifest":
                prior_path = path
            else:
                plan = _load_object(path, "continuation replay plan")
                prior_path = Path(plan["predecessor"]["run_dir"]).resolve() / "run_manifest.json"
                if file_sha256(prior_path) != str(plan["predecessor"]["manifest_sha256"]).upper():
                    raise ContractError("continuation replay plan predecessor differs")
            owner = run_for(prior_path)
            if prior_path != owner / "run_manifest.json" or owner == run:
                raise ContractError("continuation predecessor manifest is invalid")
            pending.append((owner, next_lineage))
        for record in parent["outputs"]:
            if not isinstance(record, dict) or not record.get("path"):
                continue
            path = record_path(record, base_dir=run)
            if path.name in {"owner_exit.json", "batch_receipt.json"} and path.is_file():
                try:
                    declared = _load_object(path, "batch scientific output declaration").get("scientific_event_output")
                except ContractError:
                    declared = None
                if declared is not None:
                    for key in ("events_path", "trajectory_path"):
                        if not declared.get(key):
                            continue
                        data = Path(declared[key]).resolve()
                        candidates = [item for item in parent["outputs"] if isinstance(item, dict) and record_path(item, base_dir=run) == data]
                        if len(candidates) == 1 and data.is_file():
                            files.add(data)
            if batch_pattern.search(path.name) and path.is_file():
                if run_for(path) != run:
                    raise ContractError("continuation local output belongs to another run")
                files.add(path)
    manifests = {str(run / "run_manifest.json"): file_sha256(run / "run_manifest.json") for run in sorted(runs)}
    return {"run_directories": sorted(map(str, runs)), "files": sorted(map(str, files)), "manifests": manifests}
