"""Materialize scheduler-owned local frontend flights without launching SIMION.

The public workflow owns lifecycle and process execution. This boundary only
freezes explicit phase inputs, partitions an already projected source, and
reuses the existing Program and FLY2 assemblers. PA payloads are never copied
or rehashed: the completed same-owner field stage supplies verified identities.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import stat
from typing import Any

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.contracts.write_run_manifest import file_record
from common.simion.particle_batching import batch_plan_from_dispatch
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    build_local_frontend_program, load_initial_state,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import GLOBAL_COLUMNS, render_restart_fly2
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.local_frontend.prepare import SOURCE_CLOCK


PHASES = ("discovery", "extraction")
_INTEGRATION = "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
_PROGRAM_SOURCES = {
    "rf_drive_kernel_source": "common/multipole/simion_rf_drive.lua",
    "pulse_hook_source": _INTEGRATION+"/runtime/single_flight_pulse_hook.lua",
    "frontend_hook_source": _INTEGRATION+"/runtime/single_flight_frontend_hook.lua",
}


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
    roles = bank["dynamic_roles"]
    if len(roles) != 1 or roles[0]["role"] != "coarse_frontend" or roles[0]["instance_index"] != 1:
        raise ValueError("local flight requires exactly one carrier role")
    for kind, key in (("carrier_off", "carrier_pa_basename"), ("rf_differential_unit", "rf_differential_pa_basename"), ("pulse_delta", "pulse_delta_pa_basename")):
        if roles[0][key] != Path(by_kind[kind]["path"]).name:
            raise ValueError("field bank basename differs from verified field record")
    return dict(records=by_kind, bank=bank, receipt=file_record(stage_path),
                identity_validation="reuse_successful_same_owner_field_stage_SHA__stat_and_read_only_rechecked")


def _shared_iob_seed(run: Path, repo: Path) -> dict:
    """Freeze the official one-slot seed and its sole placeholder once per run.

    The seed README requires both files together. Keeping them outside the
    deep code snapshot avoids the demonstrated SIMION2020 companion-path limit.
    These are source fixtures, never copies of a physical working field.
    """
    source_root = repo/"common/simion/assets/iob_instance_seeds"
    destination = run/"simion/iob_seed"
    identities = {}
    for name, key in (("1_instance_seed.iob", "seed"), ("iob_seed_placeholder_01.pa0", "placeholder")):
        source, frozen = source_root/name, destination/name
        _write_bytes_once(frozen, source.read_bytes())
        identities[key] = dict(source=file_record(source), frozen=file_record(frozen),
                               frozen_path_utf16_units=len(str(frozen).encode("utf-16-le"))//2)
        if identities[key]["source"]["sha256"] != identities[key]["frozen"]["sha256"]:
            raise ValueError("official IOB seed source and frozen bytes differ")
    _json_once(run/"inputs/local_iob_seed.json", identities)
    return identities


def _context(run: Path) -> dict:
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
    if _load(inputs/"source_clock.json") != SOURCE_CLOCK:
        raise ValueError("source clock projection differs")
    numerics = _load(inputs/"numerics.json")
    if type(numerics["trajectory_quality"]) is not int or not 1 <= numerics["trajectory_quality"] <= 500:
        raise ValueError("trajectory quality must be explicit positive integer")
    fields = _fields(run)
    repo = Path(__file__).resolve().parents[4]
    code_records, sources = {}, {}
    paths = {**_PROGRAM_SOURCES, "program_assembler": _INTEGRATION+"/runtime/build_single_flight_program.py", "materializer": str(Path(__file__).relative_to(repo))}
    for key, relative in paths.items():
        original = repo/relative
        frozen = inputs/"local_program_sources"/Path(relative).name
        _write_once(frozen, original.read_text(encoding="utf-8-sig"))
        code_records[key] = file_record(frozen)
        if key in _PROGRAM_SOURCES:
            sources[key] = frozen.read_text(encoding="utf-8")
    horizon = max(float(row["instrument_time_us"]) for row in rows) + numerics["maximum_flight_us"]
    return dict(rows=rows, flight_horizon_us=horizon, iob_seed=_shared_iob_seed(run, repo),
                guide=_load(inputs/"guide_contract.json"), frontend=_load(inputs/"frontend_contract.json"),
                numerics=numerics, fields=fields, sources=sources, code_records=code_records,
                source_record=file_record(source), source_identity_record=file_record(inputs/"source_identity.json"))


def prepare_dispatch_request(run: Path, phase: str) -> dict[str, Any]:
    """Write a public scheduler request bound to fields, source, code and clock."""
    run = _owner(run, phase)
    phase_input, context = _phase_input(run, phase), _context(run)
    identity = dict(phase=phase_input, fields=context["fields"]["records"], source=context["source_record"],
                    source_identity=context["source_identity_record"], code=context["code_records"],
                    numerics=context["numerics"], frontend=context["frontend"])
    request = dict(solver="SIMION", field_kind="rf", particle_count=len(context["rows"]), independent_particles=True,
                   trajectory_quality=context["numerics"]["trajectory_quality"],
                   rf_steps_per_period=context["numerics"]["rf_steps_per_period"],
                   frontend_cell_mm_xyz=context["numerics"]["cell_mm_xyz"],
                   workload_topology_id="local_frontend_one_carrier_two_readonly_responses_v1",
                   field_loading_policy_id=context["fields"]["bank"]["runtime_representation"],
                   case_input_sha256=canonical_json_sha256(identity))
    path = run/"inputs"/f"{phase}_dispatch_request.json"
    _json_once(path, request)
    return dict(dispatch_request_path=str(path), particle_count=request["particle_count"], request=request)


def _iob_builder() -> str:
    # Same documented SIMION instance replacement/save sequence as the existing
    # integration builders, applied to the official one-slot source fixture.
    return """local seed=assert(arg[1],'one-instance seed required')
local output=assert(arg[2],'output IOB required')
local field=assert(arg[3],'ordinary carrier PA required')
local x,y,z=assert(tonumber(arg[4])),assert(tonumber(arg[5])),assert(tonumber(arg[6]))
local stem=assert(output:match('^(.*)%.iob$'),'output must end in .iob')
local companions={}
for _,ext in ipairs({'.lua','.fly2'}) do
  local f=assert(io.open(stem..ext,'rb'));companions[ext]=f:read('*a');f:close()
end
simion.command('"'..seed..'"')
assert(#simion.wb.instances==1,'exactly one actual carrier slot required')
local item=simion.wb.instances[1]
item.pa.filename=field;item.pa:load();item:_debug_update_size()
item.x,item.y,item.z=x,y,z
item.az,item.el,item.rt,item.scale=0,0,0,1
if item.pa.nz==1 then item.nz_use=0 end
simion.wb:load_particles(stem..'.fly2')
simion.wb:save(output)
-- wb:save also writes associated files. Retain the exact frozen Program/source,
-- rather than any particle/program definition loaded with the seed.
for _,ext in ipairs({'.lua','.fly2'}) do
  local f=assert(io.open(stem..ext,'wb'));assert(f:write(companions[ext]));f:close()
end
assert(#simion.wb.instances==1,'carrier instance count changed')
print('LOCAL_FRONTEND_IOB=PASS INSTANCES=1')
"""


def _case(run: Path, phase: str, name: str, rows: list[dict], context: dict, phase_input: dict) -> dict:
    directory = run/"simion"/phase/name
    source_path = directory/"source_global.csv"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _write_once(source_path, stream.getvalue())
    births, ids, velocities = load_initial_state(source_path)
    numerical = context["numerics"]
    # A positive explicit pulse covers the complete declared birth+age horizon.
    width = context["flight_horizon_us"]
    program = build_local_frontend_program(context["guide"], context["frontend"], birth_times_us=births,
        particle_ids=ids, initial_velocities_mm_per_us=velocities, pulse_time_us=phase_input["pulse_time_us"],
        pulse_width_us=width, maximum_flight_us=numerical["maximum_flight_us"], maximum_step_us=numerical["maximum_step_us"],
        shared_times_us=phase_input["shared_times_us"], trajectory_cadence_us=numerical["trajectory_sample_interval_us"],
        standalone_dynamic_field_bank=context["fields"]["bank"], rf_steps_per_period=numerical["rf_steps_per_period"],
        trajectory_quality=numerical["trajectory_quality"],
        **context["sources"])
    for filename, text in (("local.lua", program), ("local.fly2", render_restart_fly2(rows)), ("build_iob.lua", _iob_builder())):
        _write_once(directory/filename, text)
    origin = context["frontend"]["instance_origin_mm"]
    carrier = Path(context["fields"]["records"]["carrier_off"]["path"])
    # Loading the seed changes SIMION's working directory. Absolute published
    # paths keep carrier sidecars and the output in their declared owner.
    carrier_reference = carrier.as_posix()
    seed = Path(context["iob_seed"]["seed"]["frozen"]["path"])
    logs = run/"logs"/phase
    logs.mkdir(parents=True, exist_ok=True)
    # Match run_single_flight's SIMION ion-list preallocation minimum. The
    # external FLY2 still contains only this batch's exact physical population.
    result = dict(case_id=name, frame_id=context["frontend"]["frame_id"], count=len(rows), expected_particle_ids=ids,
                  simion_particle_id_offset=0, merge_offset=0, working_directory=str(directory),
                  environment={"OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET": "0"},
                  iob_path=str(directory/"local.iob"), program_path=str(directory/"local.lua"), particle_input=str(directory/"local.fly2"),
                  stdout=str(logs/(name+".stdout.log")), stderr=str(logs/(name+".stderr.log")),
                  iob_builder_arguments=["--nogui", "--noprompt", "lua", "build_iob.lua", str(seed), str(directory/"local.iob"), carrier_reference,
                                         *[format(float(origin[a]), ".17g") for a in "xyz"]],
                  fly_arguments=["--default-num-particles", str(max(100, len(rows))), "--nogui", "--noprompt", "fly", "--trajectory-quality",
                                 str(numerical["trajectory_quality"]), "--retain-trajectories", "0", "--particles", "local.fly2", "--programs", "1", "local.iob"],
                  pulse_width_us=width, pulse_width_derivation="max_complete_source_birth_us_plus_maximum_particle_age_us",
                  carrier_reference=carrier_reference, seed_record=context["iob_seed"]["seed"]["frozen"],
                  seed_placeholder_record=context["iob_seed"]["placeholder"]["frozen"],
                  source_record=file_record(source_path), fly2_record=file_record(directory/"local.fly2"), program_record=file_record(directory/"local.lua"))
    _json_once(directory/"case_metadata.json", result)
    return result


def materialize_batches(run: Path, phase: str, batch_plan: dict[str, Any], pulse_time_us: float, shared_times_us: list[float]) -> dict[str, Any]:
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
    context = _context(run)
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
        cases.append({"index": batch["index"], **_case(run, phase, name, rows, context, phase_input)})
    gui = _case(run, phase, "gui_full_population", context["rows"], context, phase_input)
    digest = canonical_json_sha256(batch_plan)
    receipt_path = run/"results"/f"{phase}_batches_{digest[:16]}.json"
    receipt = dict(schema_version=1, role="rf_oatof_local_frontend_batch_materialization", phase=phase, frame_id=context["frontend"]["frame_id"],
                   source_count=count, complete_source_particle_ids=list(range(1, count+1)), coverage=coverage,
                   scheduled_particle_ids=seen, pending_particle_ids=sorted(set(range(1, count+1))-set(seen)),
                   batch_plan_sha256=digest, field_records=context["fields"]["records"], field_stage_record=context["fields"]["receipt"],
                   field_validation=context["fields"]["identity_validation"], batches=cases, gui_case=gui,
                   default_load_iob=gui["iob_path"], gui_fly_performed=False,
                   saved_default_replay_verification="pending", receipt_path=str(receipt_path))
    _json_once(receipt_path, receipt)
    return receipt


def main() -> int:
    """Internal public-workflow actions; lifecycle/process execution stays in execute.ps1."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare-dispatch", "materialize-batches"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--pulse-time-us", type=float, required=True)
    parser.add_argument("--shared-times-json", type=Path, required=True)
    parser.add_argument("--batch-plan", type=Path)
    args = parser.parse_args()
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
