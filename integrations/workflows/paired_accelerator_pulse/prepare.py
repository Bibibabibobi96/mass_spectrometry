"""Freeze a recorded OA source and an explicitly selected common-field model.

Preparation reads small published records only. Native model/PA payload guards
belong to the executing owner; no solver or particle propagation occurs here.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.frozen_inputs import freeze_file
from common.contracts.strict_json import load_json_object, require_number
from common.contracts.particle_count_policy import validate_positive_particle_count
from common.contracts.particle_physics import AMU_KG
from common.contracts.verify_run_manifest import record_path
from common.contracts.write_run_manifest import require_completed_terminal_publication
from integrations.analysis.build_comsol_prepulse_replay import build_comsol_prepulse_replay
from integrations.runtime.paired_accelerator_model import load_paired_static_model_source
from integrations.runtime.single_flight_source import (
    published_producer_input,
    require_producer_manifest_binding,
    select_timed_pre_pulse_states,
)


def _freeze(record: dict, destination: Path, base: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    frozen = freeze_file(record_path(record, base_dir=base), destination)
    if any(frozen[key] != record.get(key) for key in ("bytes", "sha256")):
        raise ValueError(f"selected input identity differs: {destination.name}")
    return frozen


def _role_voltages(table: dict, source_binding: dict, target_binding: dict) -> dict:
    """Project the existing actual electrical table without recomputing volts."""
    result = {}
    consumed = set()
    if set(source_binding) != set(target_binding):
        raise ValueError("source and static OA electrode roles differ")
    for role, source_ids in source_binding.items():
        target_ids = target_binding[role]
        if role != "accelerator_ring_ids":
            source_ids, target_ids = [source_ids], [target_ids]
        if len(source_ids) != len(target_ids):
            raise ValueError("source and static OA ring counts differ")
        for source_id, target_id in zip(source_ids, target_ids, strict=True):
            consumed.add(str(source_id))
            result[str(target_id)] = require_number(table[str(source_id)], "electrode voltage")
    if set(table) != consumed or len(result) != len(consumed):
        raise ValueError("actual OA voltage table does not cover its physical electrodes exactly")
    return result


def prepare(request_path: Path, output_dir: Path, *, source_base_dir: Path | None = None) -> dict[str, Any]:
    """Write a frozen backend plan and one Cartesian CSV from recorded states.

    Observation times are absolute instrument microseconds. The pulse and
    species come from the recorded producer, never from new author defaults.
    Missing provenance, unsupported physics or changed byte identities fail.
    """
    request_path = request_path.resolve(strict=True)
    source_base_dir = (source_base_dir or request_path.parent).resolve(strict=True)
    request = load_json_object(request_path)
    if (set(request) != {"schema_version", "role", "static_field_manifest", "source", "observation_times_us", "numerics"}
            or type(request["schema_version"]) is not int or request["schema_version"] != 1
            or request["role"] != "paired_accelerator_pulse_request"):
        raise ValueError("current paired pulse request required")
    source = request["source"]
    required = {"kind", "instance_id", "frame_id", "pre_pulse_collection", "producer_manifest", "clock_authority", "instrument_epoch"}
    if (not isinstance(source, dict) or set(source) not in (required, required | {"pulse_decision"})
            or source["kind"] != "recorded_pre_pulse_state"):
        raise ValueError("explicit recorded_pre_pulse_state source required")
    numerics = request["numerics"]
    if not isinstance(numerics, dict) or set(numerics) != {"maximum_step_us", "relative_tolerance", "absolute_tolerance", "simion_trajectory_quality"}:
        raise ValueError("explicit pulse numerical controls required")
    quality = numerics["simion_trajectory_quality"]
    if type(quality) is not int or not 1 <= quality <= 500:
        raise ValueError("simion_trajectory_quality must be an integer from 1 to 500")
    numerics = {**{key: require_number(value, key, minimum=0.0, strict_minimum=True) for key, value in numerics.items() if key != "simion_trajectory_quality"},
                "simion_trajectory_quality": quality}
    output_dir = output_dir.resolve()
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    records = {"author_request": freeze_file(request_path, inputs / "request.json")}

    static_manifest_path = record_path(request["static_field_manifest"], base_dir=source_base_dir)
    records["static_field_manifest"] = _freeze(request["static_field_manifest"], inputs / "static_manifest.json", source_base_dir)
    static_manifest = load_json_object(Path(records["static_field_manifest"]["path"]))
    own_plan_path = static_manifest_path.parent / "inputs/bvp/paired_accelerator_static_field_plan.json"
    own_plans = [row for row in static_manifest["inputs"].values()
                 if record_path(row, base_dir=static_manifest_path.parent) == own_plan_path.resolve()]
    if len(own_plans) != 1:
        raise ValueError("static producer must bind its own BVP plan")
    records["static_plan"] = _freeze(own_plans[0], inputs / "static_plan.json", static_manifest_path.parent)
    static_plan = load_json_object(Path(records["static_plan"]["path"]))
    static_source = load_paired_static_model_source(static_manifest_path, Path(records["static_field_manifest"]["path"]), expected_plan=static_plan)
    if static_source["source_stage"] != "solved_saved":
        raise ValueError("paired pulse requires an explicitly solved static field")
    instance = static_plan["oatof_instance_id"]
    scope = static_plan["composition_plan"]
    if (scope["scope"]["instance_ids"] != [instance] or source["instance_id"] != instance
            or source["frame_id"] != static_plan["coordinate_frame"]):
        raise ValueError("recorded source instance/frame differs from the OA-only static scope")
    publication_path = static_manifest_path.parent / "results/simion_field_publication.json"
    publications = [row for row in static_manifest["outputs"] if record_path(row) == publication_path.resolve()]
    if len(publications) != 1:
        raise ValueError("static producer must bind its original SIMION publication")
    records["simion_field_publication"] = _freeze(publications[0], inputs / "simion_field_publication.json", static_manifest_path.parent)
    publication = load_json_object(Path(records["simion_field_publication"]["path"]))
    if publication.get("status") != "published" or publication.get("action_required") != "complete":
        raise ValueError("static producer SIMION field is not published")

    producer_path = record_path(source["producer_manifest"], base_dir=source_base_dir)
    require_completed_terminal_publication(producer_path)
    for name in ("producer_manifest", "pre_pulse_collection", *(('pulse_decision',) if 'pulse_decision' in source else ())):
        records[name] = _freeze(source[name], inputs / f"{name}.json", source_base_dir)
    producer = load_json_object(Path(records["producer_manifest"]["path"]))
    collection = load_json_object(Path(records["pre_pulse_collection"]["path"]))
    decision = load_json_object(Path(records["pulse_decision"]["path"])) if "pulse_decision" in source else None
    selection = select_timed_pre_pulse_states(collection, decision)
    if decision is not None and (not isinstance(decision.get("input_records"), dict)
            or decision["input_records"].get("request") != collection.get("request_record")
            or decision["input_records"].get("frontend_geometry") != collection.get("geometry_record")):
        raise ValueError("pulse decision does not bind the recorded collection request/geometry")
    selected_inputs = {name: published_producer_input(producer, collection[f"{name}_record"])
                       for name in ("geometry", "source", "request", "field_design")}
    provenance = [row for row in producer["inputs"].values()
                  if Path(row["path"]).name == "source_provenance.json"]
    if len(provenance) != 1:
        raise ValueError("recorded producer must bind one source provenance")
    selected_inputs["source_provenance"] = provenance[0]
    for name in ("clock_authority", "instrument_epoch"):
        selected_inputs[name] = published_producer_input(producer, source[name])
    require_producer_manifest_binding(producer,
        geometry_path=record_path(selected_inputs["geometry"]), geometry_record=selected_inputs["geometry"],
        collection_path=record_path(source["pre_pulse_collection"], base_dir=source_base_dir),
        collection_record=source["pre_pulse_collection"],
        pulse_decision_path=record_path(source["pulse_decision"], base_dir=source_base_dir) if decision is not None else None,
        pulse_decision_record=source.get("pulse_decision"),
        required_input_records={record_path(row): row for row in selected_inputs.values()})
    for name, record in selected_inputs.items():
        suffix = ".csv" if name == "source" else ".json"
        filename = name if name in ("clock_authority", "instrument_epoch") else "producer_" + name
        records[name] = _freeze(record, inputs / (filename + suffix), producer_path.parent)
    clock = validate_clock_authority(Path(records["clock_authority"]["path"]), output_dir)
    epoch = require_number(load_json_object(Path(records["instrument_epoch"]["path"]))["instrument_time_us"], "instrument epoch")
    provenance = load_json_object(Path(records["source_provenance"]["path"]))
    frontend = load_json_object(Path(records["geometry"]["path"]))
    if (provenance.get("role") != "single_reflection_source_provenance"
            or provenance.get("target_frame_id") != source["frame_id"]
            or provenance.get("clock_epoch_id") != selection["clock_epoch_id"]
            or clock["clock_epoch_id"] != selection["clock_epoch_id"]
            or provenance.get("instrument_epoch_us") != epoch):
        raise ValueError("recorded source frame or unique instrument clock differs")
    bounds = static_plan["numerical_domain"]["pa_bounds_mm"]
    if any(not bounds[f"{axis}_min"] < float(row[f"{axis}_mm"]) < bounds[f"{axis}_max"]
           for row in selection["selected_rows"] for axis in "xyz"):
        raise ValueError("recorded source is outside the static numerical box")
    source_component = frontend["composition_plan"]["components"][instance]
    if any(source_component[key] != scope["components"][instance][key] for key in ("project_id", "local_frame_id")):
        raise ValueError("recorded OA component identity differs")
    parent_request = load_json_object(Path(records["request"]["path"]))
    resolved_record = published_producer_input(producer, parent_request["providers"]["instances"][instance]["resolved_design"])
    records["source_oatof_resolved"] = _freeze(resolved_record, inputs / "source_oatof_resolved.json", producer_path.parent)
    states = load_json_object(Path(records["field_design"]["path"]))["accelerator_voltage_states"]
    source_binding = frontend["electrode_bindings"][instance]
    target_binding = static_plan["native_geometry_compilation"]["electrode_bindings"][instance]
    off = _role_voltages(states["off_voltages_v"], source_binding, target_binding)
    on = _role_voltages(states["operating_voltages_v"], source_binding, target_binding)
    if (states.get("pulse_voltage_policy_id") != "all_accelerator_electrodes_zero_before_pulse_v1"
            or any(value != 0 for value in off.values()) or on != static_plan["static_on_electrode_voltages_v"]):
        raise ValueError("actual OA ON/OFF voltage authority differs from the static field")
    pulse = collection["flight"]["pulse"]
    on_time = require_number(pulse["time_us"], "pulse on time")
    off_time = on_time + require_number(pulse["width_us"], "pulse width", minimum=0.0, strict_minimum=True)
    source_time = selection["pulse_time_us"]
    times = request["observation_times_us"]
    if not isinstance(times, list) or not times:
        raise ValueError("explicit observation times required")
    times = [require_number(value, "observation time") for value in times]
    if (source_time > on_time or not math.isfinite(off_time) or times[0] != source_time
            or any(right <= left for left, right in zip(times, times[1:]))
            or on_time not in times or off_time not in times or times[-1] <= off_time):
        raise ValueError("observation times must preserve source time and both pulse edges")
    species = provenance.get("source_metadata")
    if not isinstance(species, dict) or species.get("particle_count") != len(selection["mother_particle_ids"]):
        raise ValueError("recorded mother species metadata is missing or incomplete")
    mass = require_number(species["mass_amu"], "mass_amu", minimum=0.0, strict_minimum=True)
    if type(species.get("charge_state")) is not int or species["charge_state"] != 1:
        raise ValueError("this native Cartesian release requires charge_state +1")
    metadata = build_comsol_prepulse_replay(Path(records["pre_pulse_collection"]["path"]),
        Path(records["source_oatof_resolved"]["path"]), output_dir / "source.csv", output_dir / "source_metadata.json",
        mass_amu=mass, charge_state=1,
        pulse_decision_path=Path(records["pulse_decision"]["path"]) if decision is not None else None)
    count = validate_positive_particle_count(len(selection["selected_rows"]))
    plan = dict(schema_version=1, role="paired_accelerator_pulse_plan", static_plan=records["static_plan"],
        model=static_source["model"], source_csv=metadata["output"], particle_count=count,
        mass_amu=mass, mass_kg=mass * AMU_KG, charge_state=1, source_time_us=source_time,
        pulse=dict(on_us=on_time, off_us=off_time), observation_times_us=times, numerics=numerics,
        off_electrode_voltages_v=off, clock_epoch_id=clock["clock_epoch_id"], instrument_epoch_us=epoch,
        frame_id=source["frame_id"], source_instance_id=instance,
        original_mother_particle_ids=selection["mother_particle_ids"],
        original_birth_times_us=selection["original_birth_times_us"],
        uncontinued_mother_particle_ids=sorted(set(selection["mother_particle_ids"]) - set(selection["selected_particle_ids"])),
        selected_particle_ids=selection["selected_particle_ids"], selection_basis=selection["selection_basis"],
        input_records=records, static_source=static_source,
        claim="preparation_only_no_native_particle_or_field_equivalence_qualification")
    (output_dir / "paired_accelerator_pulse_plan.json").write_text(json.dumps(plan, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return plan
