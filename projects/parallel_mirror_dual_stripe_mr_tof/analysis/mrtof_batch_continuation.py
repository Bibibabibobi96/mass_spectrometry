"""MR-TOF adapter for the repository SIMION whole-batch continuation protocol."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.simion.native_completion import parse_fly_completed_line
from common.simion.batch_continuation import (
    WholeUnitReplayUnit,
    build_whole_unit_replay_plan,
)


TERMINAL_PATTERN = re.compile(r"^MRTOF_EVENT terminal ion=(?P<ion>\d+) .+$")
# Small direct execution inputs that determine the already-materialized flight.
# Upstream geometry, voltage, source, and pulse identities are already sealed
# inside ``trial_materialization``; repeating them here would add no recovery
# information.  PA payloads stay behind their existing identity manifests.
REQUIRED_INPUT_ROLES = (
    "resolved_iob_pose",
    "operating_point_lua",
    "frozen_source_fly2",
    "iob_builder",
    "iob_seed",
    "native_corridor_priority_contract",
    "flight_program",
    "voltage_waveforms",
    "mirror_cycle_counter",
    "voltage_map",
    "flight_launcher",
    "native_corridor_bank_cache_manifest",
    "native_system_runtime_bundle",
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
                    declared = _load_object(path,"batch scientific output declaration").get("scientific_event_output")
                except ContractError:
                    declared = None
                if declared is not None:
                    for key in ("events_path","trajectory_path"):
                        if not declared.get(key): continue
                        data=Path(declared[key]).resolve()
                        candidates=[item for item in parent["outputs"] if isinstance(item,dict) and record_path(item,base_dir=run)==data]
                        if len(candidates)==1 and data.is_file():
                            files.add(data)
            if batch_pattern.search(path.name) and path.is_file():
                if run_for(path) != run:
                    raise ContractError("continuation local output belongs to another run")
                files.add(path)
    manifests = {str(run / "run_manifest.json"): file_sha256(run / "run_manifest.json") for run in sorted(runs)}
    return {"run_directories": sorted(map(str, runs)), "files": sorted(map(str, files)), "manifests": manifests}


def _configured_path(config: Mapping[str, Any], role: str) -> Path:
    value = (config.get("inputs") or {}).get(role)
    if not isinstance(value, str) or not value:
        raise ContractError(f"MR-TOF continuation input is missing: {role}")
    path = Path(value).resolve()
    if not path.is_file():
        raise ContractError(f"MR-TOF continuation input is missing: {role}")
    return path


def _trial_execution_identity(trial: dict[str, Any], config: Mapping[str, Any],
                              hashes: Mapping[str, str]) -> dict[str, Any]:
    """Separate only named, independently bound run-local transport locators."""
    if (trial.get("schema_version") != 1 or trial.get("role") != "mrtof_finite_3d_two_prism_voltage_trial"
            or trial.get("status") != "materialized"):
        raise ContractError("MR-TOF scientific trial identity is invalid")
    for key in ("source_particle_count", "source_expected_particle_ids", "source_time_of_birth_us",
                "source_clock_basis", "source_cohort", "resolved_iob_pose", "trajectory_profile", "inputs"):
        if key not in trial:
            raise ContractError(f"MR-TOF scientific trial identity is missing: {key}")
    identity = copy.deepcopy(trial)
    science = identity.get("scientific_event_output")
    if science is not None:
        if not isinstance(science,dict): raise ContractError("scientific output locator is invalid")
        point_parent=_configured_path(config,"operating_point_lua").parent
        for key in ("events_path","trajectory_path","csv_writer_path"):
            if science.get(key) is not None and Path(science[key]).resolve().parent!=point_parent:
                raise ContractError("scientific output locator escaped the private materialization root")
        locator=identity.pop("scientific_event_locator")
        if Path(locator["path"]).resolve()!=_configured_path(config,"scientific_event_locator"):
            raise ContractError("scientific output locator provenance differs")
        verify_record("scientific output locator",locator)
        identity["scientific_event_output"]={key:value for key,value in science.items() if key not in {"events_path","trajectory_path","csv_writer_path"}}
    priority = identity.get("native_corridor_priority_contract")
    if not isinstance(priority, dict):
        raise ContractError("MR-TOF priority contract record is missing")
    records = [("native_corridor_priority_contract", priority)]
    if science is not None: records.append(("scientific_csv_writer",identity["scientific_csv_writer"]))
    binding = identity.get("field_binding")
    if isinstance(binding, dict):
        role = "static_field_binding"
        if Path(binding.get("path", "")).resolve() != _configured_path(config, role):
            raise ContractError("MR-TOF static field transport binding differs")
        binding.pop("path")
    else:
        cache = identity["inputs"].get("native_corridor_cache_manifest")
        if not isinstance(cache, dict):
            raise ContractError("MR-TOF native cache contract record is missing")
        records.append(("native_corridor_bank_cache_manifest", cache))
    for role, record in records:
        path = _configured_path(config, role)
        if (Path(record.get("path", "")).resolve() != path
                or record.get("bytes") != path.stat().st_size
                or str(record.get("sha256", "")).upper() != hashes[role]):
            raise ContractError(f"MR-TOF transport binding differs: {role}")
        record.pop("path")
    return identity


def _complete_oa_batch(log: Path, count: int, scientific_event_output=None) -> bool:
    """Recognize the existing OA native terminal grammar, without hashing PA."""
    if not log.is_file():
        return False
    terminals, completions, sentinels, last_line = [], [], 0, ""
    if scientific_event_output is None:
        with log.open(encoding="utf-8-sig") as stream:
            for raw in stream:
                line = raw.rstrip("\r\n")
                if line:
                    last_line = line
                if line.startswith("MRTOF_EVENT terminal "):
                    match = TERMINAL_PATTERN.fullmatch(line)
                    if match is None:
                        raise ContractError("MR-TOF native terminal record is malformed")
                    terminals.append(int(match["ion"]))
                completion = parse_fly_completed_line(line)
                if completion is not None:
                    completions.append(completion.splats)
                if line.startswith("IOB_FLIGHT: PASS iob="):
                    sentinels += 1
    else:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import read_scientific_events
        def observe(raw):
            nonlocal sentinels, last_line
            line = raw.rstrip("\r\n")
            if line:
                last_line = line
            if line.startswith("IOB_FLIGHT: PASS iob="):
                sentinels += 1
        try:
            events, finished, _ = read_scientific_events(
                log, scientific_event_output=scientific_event_output,
                native_log_observer=observe)
        except (OSError, ValueError, KeyError, TypeError):
            return False
        completions = [item.splats for item in finished]
        terminals = [int(row["ion"]) for row in events if row["kind"] == "terminal"]
    if not last_line.startswith("IOB_FLIGHT: PASS iob="):
        return False
    if sorted(terminals) != list(range(1, count+1)) or completions != [count] or sentinels != 1:
        raise ContractError("MR-TOF native batch terminal identity differs")
    return True


def _bound_scientific_output(declaration,manifest,run):
    if not isinstance(declaration,dict) or not declaration.get("events_path"): return None
    result=dict(declaration)
    records=[*manifest.get("inputs",{}).values(),*manifest.get("outputs",[])]
    for key,record_key in (("events_path","events_record"),("trajectory_path","trajectory_record")):
        if not declaration.get(key): continue
        path=Path(declaration[key]).resolve()
        matches=[record for record in records if isinstance(record,dict) and record.get("path") and record_path(record,base_dir=run)==path]
        if len(matches)!=1 or not path.is_file(): return None
        result[record_key]=dict(matches[0],path=str(path))
    return result


def _owner_exit_complete(path: Path, index: int) -> bool:
    if not path.is_file():
        return False
    try:
        record = _load_object(path, "SIMION batch owner exit")
    except ContractError:
        return False
    return (record.get("schema_version") == 1 and record.get("role") == "simion_batch_owner_exit"
            and type(record.get("batch_index")) is int and record["batch_index"] == index
            and record.get("completed") is True and type(record.get("exit_code")) is int
            and record["exit_code"] == 0)


def _recover_observed_formal_plan(*, parent: Path, manifest: Mapping[str, Any],
                                  provisional: dict[str, Any], dispatch_record: dict[str, str],
                                  output_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Replan a stopped first interval only from sealed owner and measurement facts."""
    from common.simion.particle_batching import batch_plan_from_dispatch
    from common.simion.resource_scheduler import plan_recovered_formal_followup

    if manifest.get("status") not in {"failed", "interrupted"}:
        raise ContractError("formal recovery requires a terminal failed or interrupted predecessor")
    batches = provisional.get("batches")
    if not isinstance(batches, list) or len(batches) != 1 or batches[0].get("index") != 1:
        raise ContractError("formal recovery requires exactly one original batch interval")
    first = batches[0]
    def sealed_output(path: Path) -> dict[str, Any]:
        records = [record for record in manifest.get("outputs", []) if isinstance(record, dict)
                   and record_path(record, base_dir=parent) == path.resolve()]
        if len(records) != 1:
            raise ContractError(f"formal recovery output is not uniquely bound: {path.name}")
        verify_record("formal recovery output", records[0], base_dir=parent)
        return records[0]
    exit_path = parent / "results/batches/batch_001/owner_exit.json"
    usage_path = parent / "logs/simion_batch_resource_usage.json"
    exit_record = sealed_output(exit_path)
    if not _owner_exit_complete(exit_path, 1):
        raise ContractError("formal recovery first batch did not exit successfully")
    usage_record = sealed_output(usage_path) if usage_path.exists() else None
    observation = (_load_object(usage_path, "formal resource usage").get("first_formal_observation")
                   if usage_record is not None else None)
    if observation is not None and not isinstance(observation, dict):
        raise ContractError("formal recovery resource observation is invalid")
    if observation is not None and any(observation.get(key) is None for key in (
            "peak_managed_memory_bytes", "process_cpu_percent", "background_cpu_percent")):
        # Older receipts may contain only working-set telemetry. Do not
        # substitute it for the managed-memory observation.
        observation = None
    dispatch = _load_object(Path(dispatch_record["path"]), "formal provisional dispatch")
    dispatch_batches = dispatch.get("waves", [{}])[0].get("batches")
    if not isinstance(dispatch_batches, list) or not dispatch_batches or dispatch_batches[0] != first:
        raise ContractError("formal provisional dispatch and batch plan differ")
    completion = {"natural_exit": True, "exit_code": 0, "count": first.get("count"),
                  "source_row_range": [first.get("particle_id_min"), first.get("particle_id_max")],
                  "resource_observation": ({"peak_bytes": observation.get("peak_managed_memory_bytes"),
                      "process_cpu_percent": observation.get("process_cpu_percent"),
                      "background_cpu_percent": observation.get("background_cpu_percent")} if observation is not None else None)}
    try:
        kind = dispatch.get("estimation", {}).get("kind")
        if kind == "observed_formal_batch":
            # Replanning may have committed its full dispatch before the batch
            # plan writer failed.  Reuse only that bound complete dispatch;
            # its first interval must be the original provisional interval.
            estimation = dispatch["estimation"]
            if (dispatch["waves"][0].get("coverage") != "complete_population"
                    or type(estimation.get("observed_peak_bytes")) is not int
                    or estimation["observed_peak_bytes"] < 1
                    or dispatch["waves"][0].get("batch_count") != len(dispatch_batches)):
                raise ContractError("completed observed dispatch is invalid")
            recovered = dispatch
        else:
            if dispatch_batches != batches:
                raise ContractError("formal provisional dispatch and batch plan differ")
            recovered = plan_recovered_formal_followup(dispatch, completion)
        full_plan = batch_plan_from_dispatch(recovered)
    except (ValueError, KeyError, TypeError) as exc:
        raise ContractError("formal resource observation cannot safely replan") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path, dispatch_path = output_dir / "recovered_batch_plan.json", output_dir / "recovered_dispatch_plan.json"
    plan_path.write_text(json.dumps(full_plan, indent=2) + "\n", encoding="utf-8")
    dispatch_path.write_text(json.dumps(recovered, indent=2) + "\n", encoding="utf-8")
    provenance = {"predecessor_dispatch": dispatch_record, "exit": exit_record, "resource_usage": usage_record}
    return full_plan, file_record(plan_path), {"dispatch": file_record(dispatch_path), "provenance": provenance}


def _legacy_prepared_success(manifest_path: Path, expected_count: int, *, trusted_repo_root: Path | None = None) -> Path | None:
    """Use an existing owner's sealed aggregate success, never an inferred per-batch exit."""
    try:
        manifest = _load_object(manifest_path, "legacy prepared manifest")
        if manifest.get("status") != "success":
            return None
        config_record = manifest["run_config"]
        verify_record("legacy run configuration", config_record)
        config = _load_object(record_path(config_record), "legacy run configuration")
        if config.get("project") != "instrument_assembly" or config.get("mode") != "prepared_joint":
            return None
        role = "prepared_joint_integrations_workflows_prepared_joint_execute_ps1"
        owner_record = manifest["inputs"][role]
        verify_record("legacy prepared owner", owner_record)
        # This published owner version was reviewed: its success path checks
        # every native exit. Compare the complete small frozen source bytes,
        # not fragments that cannot establish its control flow.
        published = subprocess.run(
            ["git", "show", "af158d22c53e5ff85a32e9984f4d9b2bb009777b:integrations/workflows/prepared_joint/execute.ps1"],
            cwd=(trusted_repo_root.resolve() if trusted_repo_root is not None else Path(__file__).resolve().parents[3]),
            capture_output=True, check=True, timeout=30,
        ).stdout
        if record_path(owner_record).read_bytes() != published:
            return None
        candidates = [record for record in manifest["outputs"]
                      if Path(record.get("path", "")).name == "simion_batch_resource_usage.json"]
        if len(candidates) != 1:
            return None
        verify_record("legacy process usage", candidates[0])
        usage_path = record_path(candidates[0])
        usage = _load_object(usage_path, "legacy process usage")
        if (usage.get("status") != "completed" or usage.get("execution_wave", {}).get("process_count") != expected_count):
            return None
        return usage_path
    except (ContractError, AssertionError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def build_continuation_plan(
    *, predecessor_run_dir: Path, current_run_config: Path, output_dir: Path,
) -> dict[str, Any]:
    """Reuse independent whole OA batches after comparing frozen science inputs.

    The predecessor trial keeps its original manifest seal; the new run's
    materialization can have its own transport paths. No PA is required here.
    """
    predecessor_run_dir, output_dir = predecessor_run_dir.resolve(), output_dir.resolve()
    if output_dir == predecessor_run_dir or predecessor_run_dir in output_dir.parents:
        raise ContractError("MR-TOF replay output lies inside its predecessor")
    if (output_dir / "simion_whole_unit_replay_plan.json").exists():
        raise ContractError("MR-TOF replay output already exists")
    parent = _load_object(predecessor_run_dir / "run_config.json", "MR-TOF predecessor configuration")
    manifest = _load_object(predecessor_run_dir / "run_manifest.json", "MR-TOF predecessor manifest")
    parent_inputs = parent.get("inputs") or {}
    current = _load_object(current_run_config, "current MR-TOF run configuration")
    trial_path = _configured_path(current, "trial_materialization")
    trial = _load_object(trial_path, "current MR-TOF trial materialization")
    parent_record = _bound_parent_input(parent_inputs=parent_inputs, manifest=manifest, role="trial_materialization")
    previous_trial = _load_object(Path(parent_record["path"]), "MR-TOF predecessor trial")
    count = trial.get("source_particle_count")
    if type(count) is not int or count < 2 or len(trial.get("source_expected_particle_ids", [])) != count:
        raise ContractError("MR-TOF batch continuation requires the complete N>1 cohort")
    for config in (parent, current):
        parameters = config.get("parameters") or {}
        if (parameters.get("execution_mode") != "mrtof_native_corridor_bunch"
                or parameters.get("particle_count") != count or parameters.get("launched_particle_count") != count):
            raise ContractError("MR-TOF continuation execution mode or cohort differs")
    roles = REQUIRED_INPUT_ROLES
    if (trial.get("field_binding") or {}).get("mode") in {"comsol_static_scalar_v", "native_static_pa"}:
        roles = roles[:-2] + ("static_field_binding", "scalar_field_adapter")
    if "scientific_csv_writer" in current.get("inputs",{}) or "scientific_csv_writer" in parent_inputs:
        roles=(*roles,"scientific_csv_writer")
    hashes = {}
    for role in roles:
        record = _bound_parent_input(parent_inputs=parent_inputs, manifest=manifest, role=role)
        current_path = _configured_path(current, role)
        if file_sha256(current_path).upper() != record["sha256"]:
            raise ContractError(f"MR-TOF frozen cohort identity differs: {role}")
        hashes[role] = record["sha256"]
    if (_trial_execution_identity(previous_trial, parent, hashes)
            != _trial_execution_identity(trial, current, hashes)):
        raise ContractError("MR-TOF frozen scientific identity differs")
    plan_record = _bound_parent_input(parent_inputs=parent_inputs, manifest=manifest, role="simion_execution_batch_plan")
    plan = _load_object(Path(plan_record["path"]), "MR-TOF predecessor final batch plan")
    recovered_formal = None
    if plan.get("coverage") == "initial_formal_batch_only":
        old_dispatch = _bound_parent_input(parent_inputs=parent_inputs, manifest=manifest,
                                           role="simion_repository_dispatch_plan")
        plan, plan_record, recovered_formal = _recover_observed_formal_plan(
            parent=predecessor_run_dir, manifest=manifest, provisional=plan,
            dispatch_record=old_dispatch, output_dir=output_dir)
    batches = plan.get("batches")
    if plan.get("role") != "simion_single_wave_particle_batch_plan" or not isinstance(batches, list) or not batches:
        raise ContractError("MR-TOF predecessor batch plan differs")
    units, normalized, expected_first = [], [], 1
    for index, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict):
            raise ContractError("MR-TOF predecessor batch entry is invalid")
        first, last, size = (batch.get(key) for key in ("particle_id_min", "particle_id_max", "count"))
        if (batch.get("index") != index or any(type(value) is not int for value in (first, last, size))
                or first != expected_first or size < 1 or last-first+1 != size):
            raise ContractError("MR-TOF predecessor batch interval differs")
        expected_first = last+1
        log = predecessor_run_dir / "logs" / f"native_two_prism_flight__batch{index:02d}.log"
        owner_exit = predecessor_run_dir / "results" / "batches" / f"batch_{index:03d}" / "owner_exit.json"
        role = f"reused_batch_{index:03d}_log"
        if role in parent_inputs:
            record = manifest.get("inputs", {}).get(role)
            inherited = Path(parent_inputs[role]).resolve()
            if not isinstance(record, dict) or Path(record.get("path", "")).resolve() != inherited:
                raise ContractError("MR-TOF inherited batch log is not manifest-bound")
            if log.is_file() and log.stat().st_size:
                raise ContractError("MR-TOF batch has both reused and newly written evidence")
            log = inherited
            exit_role = f"reused_batch_{index:03d}_owner_exit"
            if exit_role in parent_inputs:
                owner_exit = Path(_bound_parent_input(parent_inputs=parent_inputs, manifest=manifest, role=exit_role)["path"])
        exit_complete = _owner_exit_complete(owner_exit,index)
        science = _load_object(owner_exit,"SIMION batch owner exit").get("scientific_event_output") if exit_complete else None
        declared_science=science
        if science is not None: science=_bound_scientific_output(science,manifest,predecessor_run_dir)
        extra=tuple(Path(science[key]) for key in ("events_path","trajectory_path") if science and science.get(key))
        complete = exit_complete and (declared_science is None or science is not None) and _complete_oa_batch(log, size, science)
        units.append(WholeUnitReplayUnit(key=f"batch-{index:03d}", terminal_outputs=(log, owner_exit,*extra), is_complete=complete))
        normalized.append(dict(index=index, particle_id_min=first, particle_id_max=last, count=size, offset=first-1, scientific_event_output=science))
    if expected_first != count+1:
        raise ContractError("MR-TOF predecessor batches do not cover the frozen cohort")
    result = build_whole_unit_replay_plan(predecessor_run_dir=predecessor_run_dir, output_dir=output_dir, units=units)
    result.update(batch_plan=plan_record, frozen_inputs=hashes,
        frozen_trial_authority=parent_record,
        current_materialization=dict(path=str(trial_path), sha256=file_sha256(trial_path).upper()),
        batches=[dict(batch, action=unit["action"], terminal_outputs=unit["terminal_outputs"])
                 for batch, unit in zip(normalized, result["units"], strict=True)])
    if recovered_formal is not None:
        result["recovered_formal_dispatch"] = recovered_formal["dispatch"]
        result["recovered_formal_provenance"] = recovered_formal["provenance"]
    result["completed_particle_count"] = sum(batch["count"] for batch in result["batches"] if batch["action"] == "reuse")
    result["replay_particle_count"] = count-result["completed_particle_count"]
    (output_dir / "simion_whole_unit_replay_plan.json").write_text(json.dumps(result, indent=2)+"\n",
                                                                encoding="utf-8", newline="\n")
    return result


_PREPARED_IDENTITY_KEYS = (
    "expected_particle_ids", "mother_particle_count", "launched_particle_count",
    "solver_epoch_instrument_time_us", "numerics", "parent_preparation", "field_binding",
    "trajectory_contract", "source_mode", "prism_voltages_v", "stripe_biases_v",
    "flight_program", "source_runtime", "voltage_waveforms",
)


def _prepared_identity(path: Path) -> dict[str, Any]:
    value = _load_object(path, "prepared-joint trial")
    identity = {key: value.get(key) for key in _PREPARED_IDENTITY_KEYS}
    # A recovery freezes the same scientific inputs into its own run directory.
    # Paths therefore change, while each file record's byte identity must not.
    for key in ("parent_preparation", "field_binding", "trajectory_contract",
                "flight_program", "source_runtime", "voltage_waveforms"):
        record = identity[key]
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ContractError(f"prepared-joint scientific identity is invalid: {key}")
        identity[key] = {"sha256": record["sha256"].upper()}
    if "scientific_event_writer" in value:
        record=value["scientific_event_writer"]
        if not isinstance(record,dict) or not isinstance(record.get("sha256"),str):
            raise ContractError("prepared-joint scientific writer identity is invalid")
        identity["scientific_event_writer"]={"sha256":record["sha256"].upper()}
    return identity


def _same_prepared_flight(parent: Path, current: Path) -> tuple[bool, dict[str, Any] | None]:
    """Compare frozen Fly inputs; only the explicitly analysis-only peak block may differ."""
    previous, selected = _prepared_identity(parent), _prepared_identity(current)
    old_contract, new_contract = previous.pop("trajectory_contract"), selected.pop("trajectory_contract")
    if previous != selected:
        return False, None
    if old_contract == new_contract:
        return True, None
    records = [_load_object(path, "prepared-joint trial")["trajectory_contract"] for path in (parent, current)]
    contracts = []
    for label, record in zip(("predecessor", "current"), records, strict=True):
        try:
            verify_record(f"{label} frozen trajectory contract", record)
            contracts.append(_load_object(record_path(record), f"{label} trajectory contract"))
        except (AssertionError, OSError, ValueError, KeyError, TypeError) as exc:
            raise ContractError(f"prepared-joint {label} trajectory contract is invalid") from exc
    old_peak, new_peak = (contract.get("peak_analysis") for contract in contracts)
    if (not isinstance(old_peak, dict) or not isinstance(new_peak, dict)
            or old_peak.get("method_id") not in ("common_gaussian_kde_time_v1", "common_gaussian_kde_time_v2")):
        raise ContractError("prepared-joint peak analysis provenance is invalid")
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_analysis import validate_measured_peak_analysis_contract
    try:
        validate_measured_peak_analysis_contract(new_peak, record_path(records[1]).parent)
    except (AssertionError, OSError, ValueError, KeyError, TypeError) as exc:
        raise ContractError("prepared-joint current peak analysis contract is invalid") from exc
    for contract in contracts:
        contract.pop("peak_analysis", None)
    return contracts[0] == contracts[1], {"predecessor": records[0], "current": records[1],
                                        "excluded_analysis_field": "peak_analysis"}


def _inherited_reused_terminal_outputs(parent_inputs: Mapping[str, Any], index: int) -> tuple[Path, Path, Path] | None:
    """Return one prior run's explicitly manifest-bound whole-batch outputs."""
    prefix = f"reused_batch_{index:03d}_"
    values = [parent_inputs.get(prefix + suffix) for suffix in ("log", "receipt", "fly2")]
    if not any(values):
        return None
    if not all(isinstance(value, str) and value for value in values):
        raise ContractError("prepared-joint inherited batch outputs are incomplete")
    return tuple(Path(value).resolve() for value in values)  # type: ignore[return-value]


def _bound_parent_input(
    *, parent_inputs: Mapping[str, Any], manifest: Mapping[str, Any], role: str,
) -> dict[str, str]:
    """Read one predecessor config input only through its manifest record."""
    value = parent_inputs.get(role)
    records = manifest.get("inputs")
    record = records.get(role) if isinstance(records, dict) else None
    if not isinstance(value, str) or not isinstance(record, dict):
        raise ContractError(f"prepared-joint predecessor lacks frozen input: {role}")
    digest = record.get("sha256")
    if (
        not isinstance(record.get("path"), str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or not record.get("exists")
    ):
        raise ContractError(f"prepared-joint predecessor frozen input differs: {role}")
    # The published role owns the durable location; config paths are transport
    # locators and may name an execution alias retired after publication.
    try:
        verify_record(role, record)
        path = record_path(record)
    except (AssertionError, OSError, ValueError) as exc:
        raise ContractError(f"prepared-joint predecessor frozen input differs: {role}") from exc
    return {"path": str(path), "sha256": digest.upper()}


def build_prepared_joint_whole_unit_plan(
    *, predecessor_run_dir: Path, current_preparation: Path, output_dir: Path, trusted_repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build whole-batch replay actions for the measured IP鈫扢R runner.

    The parent final batch plan fixes the source-row intervals.  We deliberately
    do not call the scheduler here: replay admission happens only after this
    immutable plan selected its missing units.
    """
    predecessor_run_dir = predecessor_run_dir.resolve()
    parent_config = _load_object(predecessor_run_dir / "run_config.json", "prepared-joint predecessor configuration")
    parent_inputs = parent_config.get("inputs") or {}
    if not isinstance(parent_inputs, dict):
        raise ContractError("prepared-joint predecessor inputs are invalid")
    parent_manifest = _load_object(predecessor_run_dir / "run_manifest.json", "prepared-joint predecessor manifest")
    plan_record = _bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest,
                                      role="simion_execution_batch_plan")
    preparation_record = _bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest,
                                             role="prepared_joint_trial")
    dispatch_request = _bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest,
                                           role="simion_dispatch_request")
    resource_profiles = _bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest,
                                            role="simion_resource_profiles")
    dispatch_plan = _bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest,
                                        role="simion_repository_dispatch_plan")
    plan_path = Path(plan_record["path"])
    parent_preparation = Path(preparation_record["path"])
    same_flight, analysis_change = _same_prepared_flight(parent_preparation, current_preparation.resolve())
    if not same_flight:
        raise ContractError("prepared-joint frozen scientific identity differs")
    plan = _load_object(plan_path, "prepared-joint final batch plan")
    recovered_formal = None
    if plan.get("coverage") == "initial_formal_batch_only":
        plan, plan_record, recovered_formal = _recover_observed_formal_plan(
            parent=predecessor_run_dir, manifest=parent_manifest, provisional=plan,
            dispatch_record=dispatch_plan, output_dir=output_dir)
        dispatch_plan = recovered_formal["dispatch"]
    batches = plan.get("batches")
    if plan.get("role") != "simion_single_wave_particle_batch_plan" or not isinstance(batches, list) or not batches:
        raise ContractError("prepared-joint predecessor final batch plan is invalid")
    current = _load_object(current_preparation.resolve(), "current prepared-joint trial")
    expected_first = 1
    for index, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict):
            raise ContractError("prepared-joint predecessor batch interval differs")
        first, last, count = (batch.get(key) for key in ("particle_id_min", "particle_id_max", "count"))
        if (batch.get("index") != index or any(type(value) is not int for value in (first, last, count))
                or first != expected_first or count < 1 or last-first+1 != count):
            raise ContractError("prepared-joint predecessor batch interval differs")
        expected_first = last + 1
    if (plan.get("coverage") == "initial_formal_batch_only"
            or expected_first - 1 != current.get("launched_particle_count")
            or expected_first - 1 != len(current.get("expected_particle_ids", []))):
        raise ContractError("prepared-joint predecessor batch plan does not cover the complete population")
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import validate_measured_batch_terminal

    units: list[WholeUnitReplayUnit] = []
    evidence_kinds: dict[int, str] = {}
    evidence_manifests: dict[int, str] = {}
    parent_manifest_path = predecessor_run_dir / "run_manifest.json"
    legacy_usage = _legacy_prepared_success(parent_manifest_path, len(batches), trusted_repo_root=trusted_repo_root)
    for expected_index, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict) or int(batch.get("index", -1)) != expected_index:
            raise ContractError("prepared-joint predecessor batch index differs")
        index = expected_index
        batch_dir = predecessor_run_dir / "results" / "batches" / f"batch_{index:03d}"
        log = predecessor_run_dir / "logs" / f"joint_flight_batch_{index:03d}.log"
        receipt = batch_dir / "batch_receipt.json"
        fly = batch_dir / "joint.fly2"
        owner_exit = batch_dir / "owner_exit.json"
        inherited = _inherited_reused_terminal_outputs(parent_inputs, index)
        evidence_manifest = parent_manifest_path
        usage = legacy_usage
        if inherited is not None and not (log.is_file() or receipt.is_file()):
            log, receipt, fly = inherited
            exit_role = f"reused_batch_{index:03d}_owner_exit"
            if exit_role in parent_inputs:
                owner_exit = Path(_bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest, role=exit_role)["path"])
            manifest_role = f"reused_batch_{index:03d}_owner_manifest"
            if manifest_role in parent_inputs:
                evidence_manifest = Path(_bound_parent_input(parent_inputs=parent_inputs, manifest=parent_manifest, role=manifest_role)["path"])
                inherited_usage = _legacy_prepared_success(evidence_manifest, len(batches), trusted_repo_root=trusted_repo_root)
                usage = inherited_usage if inherited_usage == owner_exit else None
            else:
                usage = None
        complete = False
        own_exit = _owner_exit_complete(owner_exit, index)
        if inherited is None and owner_exit.exists() and not own_exit:
            # An explicit contradictory or malformed per-batch record must
            # never be overridden by aggregate legacy success.
            usage = None
        if log.is_file() and receipt.is_file() and (own_exit or usage is not None):
            try:
                scientific = _load_object(receipt, "measured batch receipt").get("scientific_event_output")
                if scientific is not None:
                    scientific = _bound_scientific_output(scientific, parent_manifest, predecessor_run_dir)
                    if scientific is None:
                        raise ContractError("prepared-joint scientific output is not manifest-bound")
                ids, _, validated_fly = validate_measured_batch_terminal(
                    log_path=log, batch_receipt_path=receipt, preparation=current,
                    scientific_event_output=scientific,
                )
                if validated_fly.resolve() != fly.resolve():
                    raise ContractError("prepared-joint inherited batch FLY2 differs")
                if ids != current["expected_particle_ids"][int(batch["particle_id_min"]) - 1:int(batch["particle_id_max"])]:
                    raise ContractError("prepared-joint batch source rows differ")
                complete = True
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                complete = False
        if complete:
            evidence_kinds[index] = "batch_owner_exit" if own_exit else "legacy_aggregate_success"
            if not own_exit:
                evidence_manifests[index] = str(evidence_manifest)
        evidence = (owner_exit,) if own_exit else ((usage,) if usage is not None else ())
        scientific = scientific if complete else None
        extra = tuple(Path(scientific[key]) for key in ("events_path","trajectory_path") if scientific and scientific.get(key))
        units.append(WholeUnitReplayUnit(
            key=f"batch-{index:03d}", terminal_outputs=(log, receipt, fly, *evidence, *extra) if complete else (log,),
            is_complete=complete,
        ))
    result = build_whole_unit_replay_plan(
        predecessor_run_dir=predecessor_run_dir, output_dir=output_dir, units=units,
    )
    result["batch_plan"] = plan_record
    result["dispatch_request"] = dispatch_request
    result["resource_profiles"] = resource_profiles
    result["dispatch_plan"] = dispatch_plan
    if recovered_formal is not None:
        result["recovered_formal_provenance"] = recovered_formal["provenance"]
    if analysis_change is not None:
        result["analysis_contract_change"] = analysis_change
    result["batches"] = [
        {"index": int(batch["index"]), "particle_id_min": int(batch["particle_id_min"]),
         "particle_id_max": int(batch["particle_id_max"]), "count": int(batch["count"]),
         "action": result["units"][index - 1]["action"], "exit_evidence_kind": evidence_kinds.get(index),
         "exit_evidence_manifest": evidence_manifests.get(index)}
        for index, batch in enumerate(batches, start=1)
    ]
    (output_dir / "simion_whole_unit_replay_plan.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor-run-dir", required=True, type=Path)
    parser.add_argument("--current-run-config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--protection-projection", action="store_true")
    parser.add_argument("--prepared-joint-current-preparation", type=Path)
    parser.add_argument("--trusted-repo-root", type=Path)
    args = parser.parse_args()
    if args.protection_projection:
        print(json.dumps(continuation_protection_projection(args.predecessor_run_dir)))
        return 0
    if args.current_run_config is None or args.output_dir is None:
        parser.error("--current-run-config and --output-dir are required for replay planning")
    if args.prepared_joint_current_preparation is None:
        result = build_continuation_plan(predecessor_run_dir=args.predecessor_run_dir,
                                         current_run_config=args.current_run_config, output_dir=args.output_dir)
    else:
        result = build_prepared_joint_whole_unit_plan(predecessor_run_dir=args.predecessor_run_dir,
            current_preparation=args.prepared_joint_current_preparation, output_dir=args.output_dir,
            trusted_repo_root=args.trusted_repo_root)
    completed = result["completed_particle_count"] if "completed_particle_count" in result else result["reusable_unit_count"]
    replay = result["replay_particle_count"] if "replay_particle_count" in result else result["replay_unit_count"]
    print(f"MRTOF_BATCH_CONTINUATION=PASS COMPLETED={completed} REPLAY={replay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
