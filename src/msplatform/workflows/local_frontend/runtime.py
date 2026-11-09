"""Materialize scheduler-owned local frontend flights without launching SIMION.

The public workflow owns lifecycle and process execution. This boundary only
freezes explicit phase inputs, partitions an already projected source, and
reuses the existing Program and FLY2 assemblers. PA payloads are never copied
or rehashed: the completed same-owner field stage supplies verified identities.
"""
from __future__ import annotations

from msplatform.backends.simion.tracking_program import validate_program_trajectory_quality


import argparse
import csv
import io
import json
import math
from pathlib import Path
import stat
from typing import Any

from msplatform.io.file_identity import canonical_json_sha256, file_sha256
from msplatform.execution.retention import file_record, verify_record
from msplatform.backends.simion.particle_batching import batch_plan_from_dispatch
from msplatform.backends.simion.tracking_program import (
    build_local_frontend_program, _resolve_standalone_dynamic_field_bank,
)
from msplatform.backends.simion.source import GLOBAL_COLUMNS, render_restart_fly2, lua_value
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.execution.resources import resource_path
from msplatform.backends.simion import tracking_program
from msplatform.workflows.local_frontend.prepare import SOURCE_CLOCK


PHASES = ("discovery", "extraction")
_PROGRAM_SOURCES = {
    "rf_drive_kernel_source": "rf_drive.lua",
    "voltage_waveforms_source": "voltage_waveforms.lua",
    "pulse_hook_source": "single_flight_pulse_hook.lua",
    "frontend_hook_source": "single_flight_frontend_hook.lua",
}


def _load_initial_state(path: Path) -> tuple[list[float], list[int], list[list[float]]]:
    """Load canonical clocks, retained row IDs and velocities in mm/us.

    A restart can reindex its SIMION rows while preserving the mother-cohort
    identity in the separate row map.  The state-file ID is therefore only
    validated locally; the row map is the authority for source IDs.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    id_column = "particle_id" if "particle_id" in rows[0] else "simulation_particle_id"
    actual_ids = [int(row[id_column]) for row in rows]
    if any(value <= 0 for value in actual_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ValueError("single-flight initial-state particle IDs must be unique and positive")
    values = [float(row["instrument_time_us"]) for row in rows]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("single-flight birth times must be non-negative")
    velocities = [[float(row[f"velocity_{axis}_m_s"]) / 1000.0 for axis in "xyz"] for row in rows]
    if any(not math.isfinite(value) for velocity in velocities for value in velocity):
        raise ValueError("single-flight initial velocities must be finite")
    return values, actual_ids, velocities



def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_bytes_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to change frozen runtime input: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_once(path: Path, text: str) -> None:
    _write_bytes_once(path, text.encode("utf-8"))


def _json_once(path: Path, value: Any) -> None:
    _write_once(path, json.dumps(value, indent=2, allow_nan=False)+"\n")


def _owner(run: Path, phase: str) -> Path:
    run = Path(run).resolve(strict=True)
    if phase not in PHASES:
        raise ValueError("local phase must be discovery or extraction")
    manifest = run/"run_manifest.json"
    if manifest.exists() and _load(manifest).get("status") != "checkpoint":
        raise ValueError("cannot materialize a terminal/sealed owner")
    return run


def _phase(run: Path, phase: str, pulse: float, times: list[float]) -> dict:
    if isinstance(pulse, bool) or not isinstance(pulse, (int, float)) or not math.isfinite(pulse) or pulse < 0:
        raise ValueError("pulse_time_us must be finite and nonnegative")
    if not isinstance(times, list) or not times or any(
        isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in times
    ) or times != sorted(set(times)):
        raise ValueError("shared times must be explicit, unique, increasing and nonnegative")
    value = dict(schema_version=1, role="rf_oatof_local_frontend_runtime_phase", phase=phase,
                 pulse_time_us=float(pulse), shared_times_us=[float(t) for t in times])
    _json_once(run/"inputs"/f"local_runtime__{phase}.json", value)
    return value


def _phase_input(run: Path, phase: str) -> dict:
    value = _load(run/"inputs"/f"local_runtime__{phase}.json")
    if set(value) != {"schema_version", "role", "phase", "pulse_time_us", "shared_times_us"} or (
        value.get("schema_version") != 1 or value.get("role") != "rf_oatof_local_frontend_runtime_phase" or value.get("phase") != phase
    ):
        raise ValueError("unsupported local runtime phase contract")
    return _phase(run, phase, value["pulse_time_us"], value["shared_times_us"])


def _fields(run: Path) -> dict:
    stage_path = run/"inputs/local_frontend_field_stage_receipt.json"
    stage = _load(stage_path)
    if stage.get("schema_version") != 1 or stage.get("role") != "rf_oatof_local_frontend_field_stage" or stage.get("status") != "success":
        raise ValueError("a completed local frontend field stage is required")
    records = stage["working_points"]
    kinds = [row["kind"] for row in records]
    if len(kinds) != 3 or set(kinds) != {"carrier_off", "rf_differential_unit", "pulse_delta"}:
        raise ValueError("field stage must contain exactly three named working points")
    by_kind = {}
    for record in records:
        path = Path(record["path"]).resolve(strict=True)
        if (not path.is_relative_to(run) or path.suffix.lower() != ".pa" or not path.is_file()
                or record.get("read_only") is not True or path.stat().st_mode & stat.S_IWRITE
                or path.stat().st_size != record["bytes"]
                or not isinstance(record.get("sha256"), str) or len(record["sha256"]) != 64):
            raise ValueError("same-owner verified ordinary field identity/stat/read-only differs")
        by_kind[record["kind"]] = dict(record)
    if len({Path(row["path"]).resolve().parent for row in records}) != 1:
        raise ValueError("carrier and both response sidecars must share one directory")
    bank_path = Path(stage["field_bank_path"]).resolve(strict=True)
    bank_record = stage["field_bank_record"]
    if (Path(bank_record["path"]).resolve() != bank_path or not bank_path.is_relative_to(run)
            or bank_path.stat().st_size != bank_record["bytes"] or file_sha256(bank_path) != bank_record["sha256"]):
        raise ValueError("field bank small-file identity differs")
    bank = _load(bank_path)
    role = _resolve_standalone_dynamic_field_bank(bank, {"coarse_frontend": 1})[0]
    for kind, key in (("carrier_off", "carrier_pa_basename"), ("pulse_delta", "pulse_delta_pa_basename")):
        if role[key] != Path(by_kind[kind]["path"]).name:
            raise ValueError("field bank basename differs from verified field record")
    if (role["rf_differential_pa_basenames"] != [Path(by_kind["rf_differential_unit"]["path"]).name]
            or role["rf_reference_voltage_v"] != 1.0):
        raise ValueError("local RF response must bind the verified per-volt field")
    return dict(records=by_kind, bank=bank, receipt=file_record(stage_path),
                bank_record=dict(bank_record),
                identity_validation="reuse_successful_same_owner_field_stage_SHA__stat_and_read_only_rechecked")


def response_field_paths(records: dict) -> dict:
    """Bind the local core's verified RF/pulse records for native loading."""
    return {"coarse_frontend": {
        "rf_differential_pa_paths": [Path(records["rf_differential_unit"]["path"]).as_posix()],
        "pulse_delta_pa_path": Path(records["pulse_delta"]["path"]).as_posix(),
    }}


def _context(run: Path, *, field_provider=None) -> dict:
    inputs = run/"inputs"
    source = inputs/"release_global.csv"
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != GLOBAL_COLUMNS:
            raise ValueError("projected source columns differ")
        rows = list(reader)
    identity = _load(inputs/"source_identity.json")
    if not rows or len(rows) != identity["particle_count"] or [int(row["particle_id"]) for row in rows] != list(range(1, len(rows)+1)):
        raise ValueError("runtime requires the complete ordered original source population")
    for row in rows:
        if not all(math.isfinite(float(row[key])) for key in GLOBAL_COLUMNS) or float(row["instrument_time_us"]) < 0:
            raise ValueError("source has non-finite states or negative birth clocks")
    if identity["native_clock_projection"] != SOURCE_CLOCK:
        raise ValueError("source clock projection differs")
    replay_requested = _load(inputs/"request.json")["verify_saved_workbench_replay"]
    if type(replay_requested) is not bool:
        raise ValueError("frozen verify_saved_workbench_replay must be a boolean")
    numerics = _load(inputs/"numerics.json")
    validate_program_trajectory_quality(numerics["trajectory_quality"])
    fields = (field_provider or _fields)(run)
    materializer = Path(__file__).resolve()
    paths = {key: native_resource_path(name) for key, name in _PROGRAM_SOURCES.items()}
    paths.update(program_assembler=Path(tracking_program.__file__).resolve(), materializer=materializer,
                 native_path_source=resource_path("native_run_path.lua"))
    code_records = {key: file_record(path) for key, path in paths.items()}
    sources = {key: paths[key].read_text(encoding="utf-8-sig") for key in _PROGRAM_SOURCES}
    sources["native_path_source"] = paths["native_path_source"].read_text(encoding="utf-8")
    horizon = max(float(row["instrument_time_us"]) for row in rows) + numerics["maximum_flight_us"]
    seed = file_record(structural_seed_path(1))
    return dict(rows=rows, verify_saved_workbench_replay=replay_requested, flight_horizon_us=horizon, iob_seed=seed,
                guide=_load(inputs/"guide_contract.json"), frontend=_load(inputs/"frontend_contract.json"),
                numerics=numerics, fields=fields, sources=sources, code_records=code_records,
                source_record=file_record(source), source_identity_record=file_record(inputs/"source_identity.json"))


def prepare_dispatch_request(run: Path, phase: str, *, context: dict | None = None,
                             workload_topology_id: str = "local_frontend_one_carrier_two_readonly_responses_v1",
                             phase_input: dict | None = None, output_path: Path | None = None) -> dict[str, Any]:
    """Write a public scheduler request bound to fields, source, code and clock."""
    run = _owner(run, phase)
    phase_input = _phase_input(run, phase) if phase_input is None else phase_input
    context = _context(run) if context is None else context
    identity = dict(phase=phase_input, fields=context["fields"]["records"], source=context["source_record"],
                    source_identity=context["source_identity_record"], code=context["code_records"],
                    numerics=context["numerics"], frontend=context["frontend"])
    request = dict(solver="SIMION", field_kind="rf", particle_count=len(context["rows"]), independent_particles=True,
                   trajectory_quality=context["numerics"]["trajectory_quality"],
                   rf_steps_per_period=context["numerics"]["rf_steps_per_period"],
                   frontend_cell_mm_xyz=context["numerics"]["cell_mm_xyz"],
                   workload_topology_id=workload_topology_id,
                   field_loading_policy_id=context["fields"]["bank"]["runtime_representation"],
                   case_input_sha256=canonical_json_sha256(identity))
    path = run/"inputs"/f"{phase}_dispatch_request.json" if output_path is None else output_path
    _json_once(path, request)
    return dict(dispatch_request_path=str(path), particle_count=request["particle_count"], request=request)


def _case(run: Path, phase: str, name: str, rows: list[dict], context: dict, phase_input: dict, *, program_builder=None) -> dict:
    directory = run/"simion"/phase/name
    source_path = directory/"source_global.csv"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _write_once(source_path, stream.getvalue())
    births, ids, velocities = _load_initial_state(source_path)
    numerical = context["numerics"]
    # A positive explicit pulse covers the complete declared birth+age horizon.
    width = context["flight_horizon_us"]
    program = program_builder(context, phase_input, births, ids, velocities, directory) if program_builder else build_local_frontend_program(context["guide"], context["frontend"], birth_times_us=births,
        particle_ids=ids, initial_velocities_mm_per_us=velocities, pulse_time_us=phase_input["pulse_time_us"],
        pulse_width_us=width, maximum_flight_us=numerical["maximum_flight_us"], maximum_step_us=numerical["maximum_step_us"],
        shared_times_us=phase_input["shared_times_us"], trajectory_cadence_us=numerical["trajectory_sample_interval_us"],
        standalone_dynamic_field_bank=context["fields"]["bank"], rf_steps_per_period=numerical["rf_steps_per_period"],
        standalone_dynamic_field_paths=response_field_paths(context["fields"]["records"]),
        trajectory_quality=numerical["trajectory_quality"],
        **context["sources"])
    for filename, text in (("local.lua", program), ("local.fly2", render_restart_fly2(rows))):
        _write_once(directory/filename, text)
    origin = context["frontend"]["instance_origin_mm"]
    carrier = Path(context["fields"]["records"]["carrier_off"]["path"])
    carrier_reference = carrier.as_posix()
    seed = directory / "seed/1_instance_seed.iob"
    verify_record("installed structural seed", context["iob_seed"])
    _write_bytes_once(seed, Path(context["iob_seed"]["path"]).read_bytes())
    controls = []
    for name in ("build_tracking_iob.lua", "iob_core.lua"):
        target = directory / name
        _write_bytes_once(target, native_resource_path(name).read_bytes())
        controls.append(file_record(target))
    path_helper = directory / "native_run_path.lua"
    _write_bytes_once(path_helper, resource_path("native_run_path.lua").read_bytes())
    controls.append(file_record(path_helper))
    grid = {**context["frontend"]["dimensions"],
            **{f"d{axis}_mm": numerical["cell_mm_xyz"][axis] for axis in "xyz"}}
    spec = dict(schema_version=1, role="local_frontend_tracking_iob", seed_iob=str(seed),
                output_iob=str(directory/"local.iob"),
                bootstrap_paths=[str(seed.parent/"iob_seed_placeholder_01.pa0")],
                instances=[dict(role="local_frontend_carrier", instance_index=1, priority_number=1,
                    path=carrier_reference, grid=grid, rotation=[[1,0,0],[0,1,0],[0,0,1]],
                    placement=dict(**{f"{axis}_mm": origin[axis] for axis in "xyz"},
                                   az_deg=0,el_deg=0,rt_deg=0,scale=1))],
                response_fields=[dict(domain="coarse_frontend",kind=kind,path=record["path"],grid=grid)
                    for kind,record in sorted(context["fields"]["records"].items()) if kind!="carrier_off"])
    spec_path = directory / "build_iob_spec.lua"
    _write_once(spec_path, "return " + lua_value(spec) + "\n")
    if "bank_record" in context["fields"]:
        controls.append(context["fields"]["bank_record"])
    controls += [file_record(spec_path), *context["code_records"].values(),
                 context["source_record"], context["source_identity_record"], context["fields"]["receipt"]]
    logs = run/"logs"/phase
    logs.mkdir(parents=True, exist_ok=True)
    builder = ["--nogui", "--noprompt", "lua", str(directory/"build_tracking_iob.lua"), str(spec_path)]
    result = dict(case_id=name, frame_id=context["frontend"]["frame_id"], count=len(rows), expected_particle_ids=ids,
                  simion_particle_id_offset=0, merge_offset=0, working_directory=str(directory),
                  environment={"OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET": "0"},
                  iob_path=str(directory/"local.iob"), program_path=str(directory/"local.lua"), particle_input=str(directory/"local.fly2"),
                  stdout=str(logs/(name+".stdout.log")), stderr=str(logs/(name+".stderr.log")),
                  iob_builder_arguments=[*builder, "build", str(path_helper)],
                  iob_reopen_arguments=[*builder, "verify", str(path_helper)],
                  iob_validation_module="msplatform.workflows.local_frontend.runtime",
                  generated_paths=[str(directory/"local.iob"), *spec["bootstrap_paths"]],
                  iob_pa_guard_records=list(context["fields"]["records"].values()),
                  fly_arguments=["--default-num-particles", str(max(100, len(rows))), "--nogui", "--noprompt", "fly", "--retain-trajectories", "0", "--particles", "local.fly2", "--programs", "1", "local.iob"],
                  pulse_width_us=width, pulse_width_derivation="max_complete_source_birth_us_plus_maximum_particle_age_us",
                  carrier_reference=carrier_reference, seed_record=file_record(seed), seed_records=[file_record(seed)],
                  source_record=file_record(source_path), fly2_record=file_record(directory/"local.fly2"), program_record=file_record(directory/"local.lua"))
    result["control_records"] = [*controls,result["seed_record"],result["source_record"],result["fly2_record"],result["program_record"]]
    # This is an explicitly declared evidence path, not a completed reopen fact.
    result["iob_reopen_record"] = {"path": str(logs/(name+".reopen.stdout.log"))}
    _json_once(directory/"case_metadata.json", result)
    return result


def materialize_batches(run: Path, phase: str, batch_plan: dict[str, Any], pulse_time_us: float, shared_times_us: list[float], *,
                        context: dict | None = None, program_builder=None,
                        default_replay_policy: dict | None = None) -> dict[str, Any]:
    """Materialize exact scheduler intervals plus an unflown full-population GUI case.

    Raw Program IDs are already the original IDs. Both merge and native input
    offsets are explicitly zero; scheduler interval offsets are never applied
    again. The retained formal first batch can be rematerialized only byte-identically.
    """
    run = _owner(run, phase)
    phase_input = _phase(run, phase, pulse_time_us, shared_times_us)
    if batch_plan.get("role") == "simion_repository_dispatch_plan":
        batch_plan = batch_plan_from_dispatch(batch_plan)
    if batch_plan.get("schema_version") != 1 or batch_plan.get("role") != "simion_single_wave_particle_batch_plan":
        raise ValueError("materialization requires a public particle batch plan")
    context = _context(run) if context is None else context
    count = len(context["rows"])
    if phase == "discovery" and phase_input["pulse_time_us"] <= context["flight_horizon_us"]:
        raise ValueError("OFF discovery pulse must be after the complete birth plus particle-age horizon")
    if batch_plan.get("particle_count") != count or batch_plan.get("batch_count") != len(batch_plan["batches"]):
        raise ValueError("batch plan population differs from complete source")
    seen, batches = [], []
    for expected, batch in enumerate(batch_plan["batches"], 1):
        low, high = batch["particle_id_min"], batch["particle_id_max"]
        if any(type(v) is not int for v in (low, high, batch["count"], batch["index"], batch["simion_particle_id_offset"])) or (
            batch["index"] != expected or low < 1 or high > count or low > high or batch["count"] != high-low+1
            or batch["simion_particle_id_offset"] != low-1):
            raise ValueError("invalid canonical scheduler interval")
        seen.extend(range(low, high+1))
        batches.append((batch, context["rows"][low-1:high]))
    if not batches or seen != sorted(set(seen)):
        raise ValueError("batch intervals overlap or are unordered")
    coverage = batch_plan.get("coverage", "complete_population")
    if coverage == "complete_population" and seen != list(range(1, count+1)):
        raise ValueError("complete batch plan omits source particles")
    if coverage == "initial_formal_batch_only" and (len(batches) != 1 or seen != list(range(1, len(seen)+1))):
        raise ValueError("formal observation must retain its source prefix")
    if coverage not in {"complete_population", "initial_formal_batch_only"}:
        raise ValueError("unsupported public batch coverage")
    cases = []
    for batch, rows in batches:
        name = f"batch_{batch['index']:04d}__ids_{batch['particle_id_min']:06d}_{batch['particle_id_max']:06d}"
        cases.append({"index": batch["index"], **_case(run, phase, name, rows, context, phase_input, program_builder=program_builder)})
    gui = _case(run, phase, "gui_full_population", context["rows"], context, phase_input, program_builder=program_builder)
    digest = canonical_json_sha256(batch_plan)
    receipt_path = run/"results"/f"{phase}_batches_{digest[:16]}.json"
    receipt = dict(schema_version=1, role="rf_oatof_local_frontend_batch_materialization", phase=phase, frame_id=context["frontend"]["frame_id"],
                   source_count=count, complete_source_particle_ids=list(range(1, count+1)), coverage=coverage,
                   scheduled_particle_ids=seen, pending_particle_ids=sorted(set(range(1, count+1))-set(seen)),
                   batch_plan_sha256=digest, field_records=context["fields"]["records"], field_stage_record=context["fields"]["receipt"],
                   field_validation=context["fields"]["identity_validation"], batches=cases, gui_case=gui,
                   default_load_iob=gui["iob_path"], gui_fly_performed=False,
                   default_replay_policy=default_replay_policy if default_replay_policy is not None else dict(
                       requested=context["verify_saved_workbench_replay"], comparison_policy="deterministic_trajectory_parity", scope="fresh_process" if context["verify_saved_workbench_replay"] else "not_requested", collision_active=False),
                   saved_default_replay_verification=("pending" if context["verify_saved_workbench_replay"] else "not_requested"), receipt_path=str(receipt_path))
    _json_once(receipt_path, receipt)
    return receipt


def verify_case(run: Path, case_path: Path, *, stage: str) -> dict:
    """Check the declared actual controls at existing native stage boundaries."""
    run = Path(run).resolve(strict=True)
    case_path = Path(case_path).resolve(strict=True)
    if not case_path.is_relative_to(run):
        raise ValueError("local case must belong to its original managed owner")
    case = _load(case_path)
    for record in case["control_records"]:
        verify_record("local frontend native input", record)
    for record in case["iob_pa_guard_records"]:
        path = Path(record["path"]).resolve(strict=True)
        if (path.stat().st_size != record["bytes"] or path.stat().st_mode & stat.S_IWRITE
                or record.get("read_only") is not True):
            raise ValueError("local frontend verified PA guard identity/stat/read-only differs")
    identity = case_path.with_name("iob_identity.json")
    if stage == "postbuild":
        # Only called after the existing process owner confirms the build exited.
        _json_once(identity, file_record(Path(case["iob_path"])))
    elif stage != "prebuild":
        verify_record("closed local frontend IOB", _load(identity))
    return dict(status="validated", stage=stage, controls=len(case["control_records"]),
                fields=len(case["iob_pa_guard_records"]))


def main() -> int:
    """Internal public-workflow actions; lifecycle/process execution stays in execute.ps1."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare-dispatch", "materialize-batches", "verify-case"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--pulse-time-us", type=float)
    parser.add_argument("--shared-times-json", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--validation-stage", choices=("prebuild", "postbuild", "postreopen", "preflight"))
    parser.add_argument("--batch-plan", type=Path)
    args = parser.parse_args()
    if args.action == "verify-case":
        if args.case is None or args.validation_stage is None:
            parser.error("verify-case requires --case and --validation-stage")
        print(json.dumps(verify_case(args.run, args.case, stage=args.validation_stage)))
        return 0
    if args.phase is None or args.pulse_time_us is None or args.shared_times_json is None:
        parser.error("runtime materialization requires phase, pulse time and shared times")
    run = _owner(args.run, args.phase)
    times = json.loads(args.shared_times_json.read_text(encoding="utf-8-sig"))
    _phase(run, args.phase, args.pulse_time_us, times)
    if args.action == "prepare-dispatch":
        if args.batch_plan is not None:
            parser.error("prepare-dispatch does not accept a batch plan")
        result = prepare_dispatch_request(run, args.phase)
    else:
        if args.batch_plan is None:
            parser.error("materialize-batches requires --batch-plan")
        result = materialize_batches(run, args.phase, _load(args.batch_plan), args.pulse_time_us, times)
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
