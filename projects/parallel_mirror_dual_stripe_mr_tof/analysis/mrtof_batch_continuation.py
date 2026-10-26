"""MR-TOF adapter for the repository SIMION whole-batch continuation protocol."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import record_path, verify_record
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
    priority = identity.get("native_corridor_priority_contract")
    if not isinstance(priority, dict):
        raise ContractError("MR-TOF priority contract record is missing")
    records = [("native_corridor_priority_contract", priority)]
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


def _complete_oa_batch(log: Path, count: int) -> bool:
    """Recognize the existing OA native terminal grammar, without hashing PA."""
    if not log.is_file():
        return False
    terminals, completions, sentinels, last_line = [], [], 0, ""
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
    if not last_line.startswith("IOB_FLIGHT: PASS iob="):
        return False
    if sorted(terminals) != list(range(1, count+1)) or completions != [count] or sentinels != 1:
        raise ContractError("MR-TOF native batch terminal identity differs")
    return True


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
        role = f"reused_batch_{index:03d}_log"
        if role in parent_inputs:
            record = manifest.get("inputs", {}).get(role)
            inherited = Path(parent_inputs[role]).resolve()
            if not isinstance(record, dict) or Path(record.get("path", "")).resolve() != inherited:
                raise ContractError("MR-TOF inherited batch log is not manifest-bound")
            if log.is_file() and log.stat().st_size:
                raise ContractError("MR-TOF batch has both reused and newly written evidence")
            log = inherited
        complete = _complete_oa_batch(log, size)
        units.append(WholeUnitReplayUnit(key=f"batch-{index:03d}", terminal_outputs=(log,), is_complete=complete))
        normalized.append(dict(index=index, particle_id_min=first, particle_id_max=last, count=size, offset=first-1))
    if expected_first != count+1:
        raise ContractError("MR-TOF predecessor batches do not cover the frozen cohort")
    result = build_whole_unit_replay_plan(predecessor_run_dir=predecessor_run_dir, output_dir=output_dir, units=units)
    result.update(batch_plan=plan_record, frozen_inputs=hashes,
        frozen_trial_authority=parent_record,
        current_materialization=dict(path=str(trial_path), sha256=file_sha256(trial_path).upper()),
        batches=[dict(batch, action=unit["action"], terminal_outputs=unit["terminal_outputs"])
                 for batch, unit in zip(normalized, result["units"], strict=True)])
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
    return identity


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
    *, predecessor_run_dir: Path, current_preparation: Path, output_dir: Path,
) -> dict[str, Any]:
    """Build whole-batch replay actions for the measured IP→MR runner.

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
    if _prepared_identity(parent_preparation) != _prepared_identity(current_preparation.resolve()):
        raise ContractError("prepared-joint frozen scientific identity differs")
    plan = _load_object(plan_path, "prepared-joint final batch plan")
    batches = plan.get("batches")
    if plan.get("role") != "simion_single_wave_particle_batch_plan" or not isinstance(batches, list) or not batches:
        raise ContractError("prepared-joint predecessor final batch plan is invalid")
    current = _load_object(current_preparation.resolve(), "current prepared-joint trial")
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import validate_measured_batch_terminal

    units: list[WholeUnitReplayUnit] = []
    for expected_index, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict) or int(batch.get("index", -1)) != expected_index:
            raise ContractError("prepared-joint predecessor batch index differs")
        index = expected_index
        batch_dir = predecessor_run_dir / "results" / "batches" / f"batch_{index:03d}"
        log = predecessor_run_dir / "logs" / f"joint_flight_batch_{index:03d}.log"
        receipt = batch_dir / "batch_receipt.json"
        fly = batch_dir / "joint.fly2"
        inherited = _inherited_reused_terminal_outputs(parent_inputs, index)
        if inherited is not None and not (log.is_file() or receipt.is_file()):
            log, receipt, fly = inherited
        complete = False
        if log.is_file() and receipt.is_file():
            try:
                ids, _, validated_fly = validate_measured_batch_terminal(
                    log_path=log, batch_receipt_path=receipt, preparation=current,
                )
                if validated_fly.resolve() != fly.resolve():
                    raise ContractError("prepared-joint inherited batch FLY2 differs")
                if ids != current["expected_particle_ids"][int(batch["particle_id_min"]) - 1:int(batch["particle_id_max"])]:
                    raise ContractError("prepared-joint batch source rows differ")
                complete = True
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                complete = False
        units.append(WholeUnitReplayUnit(
            key=f"batch-{index:03d}", terminal_outputs=(log, receipt, fly) if complete else (log,),
            is_complete=complete,
        ))
    result = build_whole_unit_replay_plan(
        predecessor_run_dir=predecessor_run_dir, output_dir=output_dir, units=units,
    )
    result["batch_plan"] = plan_record
    result["dispatch_request"] = dispatch_request
    result["resource_profiles"] = resource_profiles
    result["dispatch_plan"] = dispatch_plan
    result["batches"] = [
        {"index": int(batch["index"]), "particle_id_min": int(batch["particle_id_min"]),
         "particle_id_max": int(batch["particle_id_max"]), "count": int(batch["count"]),
         "action": result["units"][index - 1]["action"]}
        for index, batch in enumerate(batches, start=1)
    ]
    (output_dir / "simion_whole_unit_replay_plan.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor-run-dir", required=True, type=Path)
    parser.add_argument("--current-run-config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--prepared-joint-current-preparation", type=Path)
    args = parser.parse_args()
    if args.prepared_joint_current_preparation is None:
        result = build_continuation_plan(predecessor_run_dir=args.predecessor_run_dir,
                                         current_run_config=args.current_run_config, output_dir=args.output_dir)
    else:
        result = build_prepared_joint_whole_unit_plan(predecessor_run_dir=args.predecessor_run_dir,
            current_preparation=args.prepared_joint_current_preparation, output_dir=args.output_dir)
    completed = result["completed_particle_count"] if "completed_particle_count" in result else result["reusable_unit_count"]
    replay = result["replay_particle_count"] if "replay_particle_count" in result else result["replay_unit_count"]
    print(f"MRTOF_BATCH_CONTINUATION=PASS COMPLETED={completed} REPLAY={replay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
