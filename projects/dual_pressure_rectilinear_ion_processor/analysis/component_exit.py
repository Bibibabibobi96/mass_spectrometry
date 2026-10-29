"""Export recorded IP stops to the public component-state contract, without flight.

The producer's observation plane is not a physical connector or a field-free
port. Energies and full velocities remain those of the frozen source run.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from common.analysis.particle_census import partition_cohort
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.contracts.solver_review_retirement import verify_retirement
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import (
    to_local_position, to_project_position, to_project_vector, transform_from_config,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import frozen_release_states, load_injected_source

PROJECT = "dual_pressure_rectilinear_ion_processor"
EVENT_VALUES = ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _finite(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("particle state must be finite")
    return result


def _integer(value: object) -> int:
    number = _finite(value)
    if not number.is_integer():
        raise ValueError("particle identity and charge must be integral")
    return int(number)


def _same(actual: float, expected: float) -> bool:
    # Frozen SIMION events serialize with 15 significant digits.
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _bound_records(run: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]
    bound: dict[str, dict[str, Any]] = {}
    for record in records:
        path = record_path(record, base_dir=run)
        if run not in path.parents:
            continue
        name = path.relative_to(run).as_posix()
        if name in bound and any(bound[name][key] != record[key] for key in ("bytes", "sha256")):
            raise ValueError(f"conflicting manifest identity: {name}")
        bound[name] = record
    return bound


def load_component_source(run: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate one sealed IP run and return its summary, inputs and lifecycle."""
    require_completed_terminal_publication(run / "run_manifest.json")
    manifest = _json(run / "run_manifest.json")
    if manifest.get("status") not in {"success", "failed"} or manifest.get("project") != PROJECT or manifest.get("run_id") != run.name:
        raise ValueError("source run identity/status differs")
    records = _bound_records(run, manifest)
    model = _json(run/"inputs/resolved_model.json")
    injected = "injected_source" in model
    empty = injected and model["source"]["particle_count"] == 0
    continued = (run / "inputs/simion_whole_unit_replay_plan.json").is_file()
    partial = (run / "inputs/partial_batch_replay/simion_whole_unit_replay_plan.json").is_file()
    native_names = ("simion/events.csv", "results/batch_merge_receipt.json", "results/simion_batch_resource_usage.json")
    consumed = ("run_config.json", "summary.json", "inputs/resolved_model.json", "inputs/clock_authority.json",
                "inputs/instrument_epoch.json") + (() if empty else
                (("inputs/simion_whole_unit_replay_plan.json",) if continued else native_names)) + (
                ("inputs/injected_source.json", "inputs/upstream_mother_census.json", "inputs/upstream_mother_fates.csv")
                if empty else
                ("inputs/injected_source.json", "inputs/injected_states.csv", "inputs/upstream_mother_census.json", "inputs/upstream_mother_fates.csv")
                if injected else ("inputs/source.json", "inputs/release.csv", "inputs/release_receipt.json"))
    if partial:
        consumed += ("inputs/partial_batch_replay/simion_whole_unit_replay_plan.json", "inputs/partial_batch_replay/batch_plan.json", "inputs/partial_batch_replay/field_source.json")
    for name in consumed:
        if name not in records:
            raise ValueError(f"consumed file is not manifest-bound: {name}")
        verify_record(name, records[name], base_dir=run)
    config, summary = _json(run / "run_config.json"), _json(run / "summary.json")
    if (config.get("run_id") != run.name or config.get("project") != PROJECT
            or config.get("mode") != manifest.get("mode")
            or summary.get("role") != "ion_processor_functional_summary"
            or summary.get("status") != manifest["status"]):
        raise ValueError("source run config/summary identity differs")
    checks = summary.get("checks")
    if empty:
        if (summary.get("status") != "success" or summary.get("functional_status") != "upstream_empty"
                or summary.get("solver_executed") is not False or summary.get("actual_particle_count") != 0
                or summary.get("qualification") != "empty_upstream_admission__no_IP_flight"):
            raise ValueError("empty admission does not prove a no-flight terminal result")
    elif (not isinstance(checks, dict) or not checks or any(type(value) is not bool for value in checks.values())
            or summary["status"] != ("success" if all(checks.values()) else "failed")
            or not isinstance(summary.get("functional_status"), str) or not summary["functional_status"]
            or not isinstance(summary.get("qualification"), str) or not summary["qualification"]):
        raise ValueError("source lacks its measured functional acceptance result")
    retirement = run / "solver_review_retirement_receipt.json"
    lifecycle = verify_retirement(run) if retirement.exists() else {
        "status": "PASS", "role": "consumed_manifest_projection", "native_fields_consumed": False,
    }
    # The same immutable-source projection was just verified; retain its identity
    # with an absolute path for downstream receipt consumers.
    inputs = {name: dict(path=str(run / name), exists=True, bytes=records[name]["bytes"],
                         sha256=str(records[name]["sha256"]).upper()) for name in consumed}
    if partial:
        from projects.dual_pressure_rectilinear_ion_processor.analysis.batching import continuation_protection_paths
        continuation_protection_paths(run)
        plan = _json(run / "inputs/partial_batch_replay/simion_whole_unit_replay_plan.json")
        parent_manifest = Path(plan["predecessor"]["run_dir"]).resolve()/"run_manifest.json"
        record = manifest.get("inputs", {}).get("partial_predecessor_manifest")
        if (not record or record_path(record, base_dir=run) != parent_manifest
                or str(record.get("sha256", "")).upper() != str(plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("partial predecessor is not bound to replay plan")
        verify_record("partial predecessor", record, base_dir=run)
        require_completed_terminal_publication(parent_manifest)
        inputs["partial_predecessor_manifest"] = dict(record)
    if continued and not empty:
        from projects.dual_pressure_rectilinear_ion_processor.analysis.batching import continuation_ancestry
        ancestry = continuation_ancestry(run)
        plan = _json(run / "inputs/simion_whole_unit_replay_plan.json")
        parent = Path(plan["predecessor"]["run_dir"]).resolve()
        if parent != ancestry[-1]:
            raise ValueError("continued source ancestry origin differs")
        manifest_path = parent / "run_manifest.json"
        predecessor_record = (manifest.get("inputs", {}).get("continuation_origin_manifest")
                              or manifest.get("inputs", {}).get("continuation_predecessor_manifest"))
        if (not isinstance(predecessor_record, dict)
                or record_path(predecessor_record, base_dir=run) != manifest_path
                or str(predecessor_record.get("sha256", "")).upper() != str(plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("continuation predecessor manifest is not bound to frozen plan")
        verify_record("continuation predecessor manifest", predecessor_record, base_dir=run)
        require_completed_terminal_publication(manifest_path)
        parent_records = _bound_records(parent, _json(manifest_path))
        outputs = {Path(item["path"]).resolve(): item["sha256"].upper() for item in plan["units"][0]["terminal_outputs"]}
        for name in native_names:
            if name not in parent_records:
                raise ValueError(f"continued source is not predecessor-manifest-bound: {name}")
            record = parent_records[name]
            path = (parent / name).resolve()
            if outputs.get(path) != str(record["sha256"]).upper():
                raise ValueError(f"continued source differs from frozen plan: {name}")
            verify_record("continued " + name, record, base_dir=parent)
            inputs[name] = dict(path=str(path), exists=True, bytes=record["bytes"], sha256=str(record["sha256"]).upper())
        inputs["continuation_predecessor_manifest"] = dict(predecessor_record)
    inputs["run_manifest.json"] = file_record(run / "run_manifest.json")
    if retirement.exists():
        inputs[retirement.name] = file_record(retirement)
    return summary, inputs, lifecycle


def _export_empty_admission(run: Path, output: Path, model: dict[str, Any], summary: dict[str, Any],
                            inputs: dict[str, Any], lifecycle: dict[str, Any], source_id: str,
                            target_id: str) -> dict[str, Any]:
    admission = load_injected_source(run / "inputs/injected_source.json")
    upstream = admission["census"]
    if (admission["rows"] or upstream["exit_count"] != 0 or summary.get("upstream_census") != upstream
            or summary.get("mother_particle_count") != upstream["mother_count"]):
        raise ValueError("empty admission mother census differs from the published result")
    census = []
    for particle_id in upstream["mother_particle_ids"]:
        fate = admission["mother_fates"][particle_id]
        birth, time = fate["particle_birth_time_us"], fate["terminal_instrument_time_us"]
        census.append(dict(particle_id=particle_id, transfer_status="not_transferred", terminal_reason=fate["terminal_reason"],
                           instrument_time_us=time, particle_birth_time_us=birth, particle_age_us=time-birth,
                           particle_weight=fate.get("particle_weight", "")))
    output.mkdir(parents=True, exist_ok=False)
    census_path = output / "source_census.csv"
    with census_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(census[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(census)
    frame = transform_from_config(model).to_frame_id
    center = to_project_position(model, [model["baseline"]["geometry"]["lp_center_mm"], model["baseline"]["geometry"]["extraction_end_y_mm"], 0])
    receipt = dict(schema_version=2, role="ion_processor_component_exit_export", status="zero_exit",
        source_run_id=run.name, source_project=PROJECT, source_run=str(run), inputs=inputs,
        source_instance_id=source_id, target_instance_id=target_id,
        producer_result=dict(source_scientific_status=summary["status"], checks={},
                             functional_status=summary["functional_status"], qualification=summary["qualification"]),
        outputs=dict(component_states=None, mother_census=file_record(census_path)),
        counts=dict(source=len(census), transferred=0, not_transferred=len(census)),
        transferred_particle_ids=[], not_transferred_particle_ids=[row["particle_id"] for row in census],
        frame_id=frame, clock_epoch_id=admission["clock"]["clock_epoch_id"],
        units=dict(position="mm", velocity="m/s", time="us", energy="eV", mass="u"),
        clock_semantics="inherited_upstream_absolute_time_no_IP_flight",
        observation_surface=dict(center_mm=list(center), normal=list(to_project_vector(model, [0, 1, 0])),
                                 semantics="recorded_stop_plane_not_physical_port"),
        adapter_semantics=dict(species_id="preserved_in_upstream_fates", particle_weight="preserved_when_known",
                               lineage="root_source_no_reactions", phase="absent_no_transfer_phase_reference"),
        validation=None, lifecycle_verification=lifecycle)
    (output / "component_exit_receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return receipt


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _validate_events(events: list[dict[str, str]], releases: dict[int, dict[str, str]],
                     model: dict[str, Any], epoch: float) -> dict[int, dict[str, dict[str, str]]]:
    grouped: dict[int, dict[str, dict[str, str]]] = {}
    previous: dict[int, float] = {}
    for event in events:
        particle_id = _integer(event["particle_id"])
        if particle_id not in releases:
            raise ValueError("event particle is absent from source cohort")
        values = [_finite(event[key]) for key in EVENT_VALUES]
        time = values[0]
        if time < previous.get(particle_id, -math.inf):
            raise ValueError("nonmonotonic event clock")
        previous[particle_id] = time
        stages = grouped.setdefault(particle_id, {})
        if "terminal" in stages:
            raise ValueError("event follows terminal stop")
        if event["event"] in stages:
            raise ValueError("duplicate particle event")
        if event["event"] not in {"source", "hp_enter", "capture", "transfer", "pre_extraction", "extraction_exit", "terminal"}:
            raise ValueError("unknown source event")
        stages[event["event"]] = event
    if set(grouped) != set(releases):
        raise ValueError("source/event cohort differs")
    for particle_id, release in releases.items():
        stages = grouped[particle_id]
        if "source" not in stages or "terminal" not in stages:
            raise ValueError("missing source/terminal event")
        if stages["source"]["reason"] != "none":
            raise ValueError("source event has a terminal reason")
        birth = _finite(release["birth_time_s"]) * 1e6
        mass, charge = _finite(release["mass_amu"]), _integer(release["charge_state"])
        if mass <= 0 or charge == 0 or particle_id <= 0:
            raise ValueError("invalid source species/identity")
        if mass != model["source"]["species"]["mass_amu"] or charge != model["source"]["species"]["charge_state"]:
            raise ValueError("release species differs from frozen source")
        arrival = _finite(release["arrival_time_us"]) if "injected_source" in model else birth
        expected = [arrival, *to_project_position(model, [_finite(release[f"{axis}_mm"]) for axis in "xyz"]),
                    *(value / 1000 for value in to_project_vector(model, [_finite(release[f"v{axis}_m_s"]) for axis in "xyz"]))]
        if not all(_same(_finite(stages["source"][key]), value) for key, value in zip(EVENT_VALUES, expected)):
            raise ValueError("source event differs from release identity")
        if any(_finite(event["t_us"]) < birth for event in stages.values()):
            raise ValueError("negative particle age")
        terminal = stages["terminal"]
        if terminal["reason"] == "none":
            raise ValueError("terminal reason is absent")
        if "extraction_exit" in stages:
            exit_state = stages["extraction_exit"]
            if terminal["reason"] != "acceptance_surface" or exit_state["reason"] != "acceptance_surface" or any(exit_state[key] != terminal[key] for key in EVENT_VALUES):
                raise ValueError("extraction/terminal state differs")
            local = to_local_position(model, [_finite(exit_state[f"{axis}_mm"]) for axis in "xyz"])
            if not _same(local[1], model["baseline"]["geometry"]["extraction_end_y_mm"]) or _finite(exit_state["vz_mm_us"]) >= 0:
                raise ValueError("exit plane/direction differs")
            if _finite(exit_state["t_us"]) < model["native_timing"]["primary_quench_us"]:
                raise ValueError("exit precedes extraction clock")
        elif terminal["reason"] == "acceptance_surface":
            raise ValueError("acceptance terminal lacks extraction event")
        if not math.isfinite(epoch + _finite(terminal["t_us"])):
            raise ValueError("instrument time overflows")
    return grouped


def export_component_exit(source_run: Path, output_directory: Path, *,
                          source_instance_id: str, target_instance_id: str) -> dict[str, Any]:
    """Export immutable recorded states and full mother census; return receipt.

    Reads complete manifest-bound IP data, retaining its acceptance result
    (including failed thresholds and governed retired-field runs).
    Writes only a new output directory and refuses overwrite. Invalid
    identity, clocks, closure, species, or stop states raise before publication.
    Caller binds explicit assembly instances; producer project provenance stays separate.
    Coordinates stay in the producer frame, mm; velocities convert mm/us to m/s;
    absolute time is authority epoch plus solver elapsed time exactly once.
    """
    if (not isinstance(source_instance_id, str) or not source_instance_id
            or not isinstance(target_instance_id, str) or not target_instance_id
            or source_instance_id == target_instance_id):
        raise ValueError("distinct explicit source and target instance identities required")
    run, output = Path(source_run).resolve(), Path(output_directory).resolve()
    if output.exists():
        raise FileExistsError(f"component export destination already exists: {output}")
    if run == output or run in output.parents:
        raise ValueError("component export must not modify its frozen source run")
    summary, inputs, lifecycle = load_component_source(run)
    model = _json(run / "inputs/resolved_model.json")
    injected = "injected_source" in model
    if injected and model["source"]["particle_count"] == 0:
        return _export_empty_admission(run, output, model, summary, inputs, lifecycle, source_instance_id, target_instance_id)
    source = model["source"] if injected else _json(run / "inputs/source.json")
    if not injected:
        release_receipt = _json(run / "inputs/release_receipt.json")
        if source != model["source"] or release_receipt.get("release_spec") != source or release_receipt.get("status") != "materialized":
            raise ValueError("frozen source/resolved/release receipt differ")
        for name, key in (("release.csv", "state_table"), ("source.json", "source_spec")):
            record = release_receipt[key]
            if record_path(record, base_dir=run) != run / "inputs" / name:
                raise ValueError("release receipt path identity differs")
            verified = inputs["inputs/" + name]
            if record.get("bytes") != verified["bytes"] or str(record.get("sha256", "")).upper() != verified["sha256"]:
                raise ValueError("release receipt content identity differs")
    clock = _json(run / "inputs/clock_authority.json")
    validate_clock_authority(run / "inputs/clock_authority.json", run)
    epoch = _finite(_json(run / "inputs/instrument_epoch.json")["instrument_time_us"])
    if clock["authority"]["path"].replace("\\", "/") != "inputs/instrument_epoch.json" or epoch != model["baseline"]["clock"]["epoch_us"]:
        raise ValueError("instrument epoch authority differs")
    raw_release = frozen_release_states(run, model) if injected else _read_csv(run / "inputs/release.csv")
    releases = {_integer(row["particle_id"]): row for row in raw_release}
    if not releases or len(releases) != len(raw_release) or len(releases) != source["particle_count"] or len(releases) != summary["actual_particle_count"] or (not injected and len(releases) != release_receipt["particle_count"]):
        raise ValueError("source cohort count/identity differs")
    native = _json(Path(inputs["results/simion_batch_resource_usage.json"]["path"]))
    merge = _json(Path(inputs["results/batch_merge_receipt.json"]["path"]))
    partial_plan_path = run / "inputs/partial_batch_replay/simion_whole_unit_replay_plan.json"
    partial_plan = _json(partial_plan_path) if partial_plan_path.is_file() else None
    reused_count = partial_plan["reusable_unit_count"] if partial_plan else 0
    # The public observer never promotes a failed native process to completed.
    # Acceptance thresholds are separate from these execution/cohort receipts.
    if (native.get("schema_version") != 2 or native.get("role") != "multipole_resource_usage"
            or native.get("status") != "completed" or native.get("failure_class") is not None
            or native.get("limit_name") is not None
            or merge.get("schema_version") != 1 or merge.get("role") != "ion_processor_batch_merge"
            or merge.get("all_ids_closed") is not True
            or merge.get("particle_count") != len(releases)
            or type(merge.get("batch_count")) is not int or merge["batch_count"] <= 0
            or native.get("execution_wave", {}).get("reused_batch_count", 0) != reused_count
            or native.get("execution_wave", {}).get("process_count", 0) + reused_count != merge["batch_count"]
            or merge.get("rng_policy") != model["numerics"]["collision_rng_policy"]):
        raise ValueError("source native execution or batch merge is incomplete")
    grouped = _validate_events(_read_csv(Path(inputs["simion/events.csv"]["path"])), releases, model, epoch)
    frame = transform_from_config(model).to_frame_id
    normal = list(to_project_vector(model, [0, 1, 0]))
    if summary["frame_id"] != frame or normal != [0, 0, -1]:
        raise ValueError("summary frame differs")
    identity = summary["identity_validation"]
    if identity["status"] != "PASS" or identity["particles"] != len(releases):
        raise ValueError("source identity validation differs")
    rows, census = [], []
    transferred = sorted(particle_id for particle_id, stages in grouped.items() if "extraction_exit" in stages)
    for particle_id, release in sorted(releases.items()):
        terminal = grouped[particle_id]["terminal"]
        birth = epoch + _finite(release["birth_time_s"]) * 1e6
        time = epoch + _finite(terminal["t_us"])
        census.append(dict(particle_id=particle_id, transfer_status="transferred" if particle_id in transferred else "not_transferred", terminal_reason=terminal["reason"], instrument_time_us=time, particle_birth_time_us=birth, particle_age_us=time-birth,
                           particle_weight=release["particle_weight"] if injected else 1))
        if particle_id not in transferred:
            continue
        mass, charge = _finite(release["mass_amu"]), _integer(release["charge_state"])
        velocity = [_finite(terminal[f"v{axis}_mm_us"]) * 1000 for axis in "xyz"]
        species_id = (release["species_id"] if injected else
                      f"ion_m{mass:.17g}_q{charge}".replace(".", "_").replace("+", "p").replace("-", "n"))
        row = dict(particle_id=particle_id, parent_particle_id="", generation=0, species_id=species_id,
                   particle_weight=release["particle_weight"] if injected else 1,
                   source_component_id=source_instance_id, target_component_id=target_instance_id,
                   state_event="extraction_exit", frame_id=frame, clock_epoch_id=clock["clock_epoch_id"],
                   instrument_time_us=time, lineage_age_us=time-birth, particle_age_us=time-birth,
                   last_component_elapsed_time_us=time-(_finite(release["arrival_time_us"]) if injected else birth), lineage_birth_time_us=birth,
                   particle_birth_time_us=birth, mass_to_charge_Th=mass_to_charge_th(mass, charge),
                   mass_amu=mass, charge_state=charge, kinetic_energy_eV=kinetic_energy_ev(mass, *velocity),
                   phase_reference_id="", phase_rad="")
        row.update({f"position_{axis}_mm": _finite(terminal[f"{axis}_mm"]) for axis in "xyz"})
        row.update({f"velocity_{axis}_m_s": value for axis, value in zip("xyz", velocity)})
        rows.append(row)
    reasons = dict(Counter(item["terminal_reason"] for item in census))
    if reasons != summary["terminal_reasons"] or len(rows) != summary["metrics"]["extraction_exit"]["count"]:
        raise ValueError("summary terminal/extraction census differs")
    if injected:
        for fate in _read_csv(run/"inputs/upstream_mother_fates.csv"):
            particle_id = _integer(fate["particle_id"])
            if particle_id in releases:
                continue
            birth, time = _finite(fate["particle_birth_time_us"]), _finite(fate["terminal_instrument_time_us"])
            census.append(dict(particle_id=particle_id, transfer_status="not_transferred", terminal_reason=fate["terminal_reason"],
                instrument_time_us=time, particle_birth_time_us=birth, particle_age_us=time-birth,
                particle_weight=fate.get("particle_weight", "")))
        census.sort(key=lambda row: row["particle_id"])
        upstream = _json(run/"inputs/upstream_mother_census.json")
        if [row["particle_id"] for row in census] != sorted(upstream["mother_particle_ids"]):
            raise ValueError("IP export does not close the original upstream mother cohort")
    partition_cohort([row["particle_id"] for row in census],
                     [(row["particle_id"], row["transfer_status"]) for row in census],
                     categories=("transferred", "not_transferred"), relative_weights=None)
    output.mkdir(parents=True, exist_ok=False)
    state_path, census_path = output / "component_particle_state.csv", output / "source_census.csv"
    validation = write_component_particle_state_csv(state_path, rows) if rows else None
    with census_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(census[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(census)
    center = to_project_position(model, [model["baseline"]["geometry"]["lp_center_mm"], model["baseline"]["geometry"]["extraction_end_y_mm"], 0])
    receipt = dict(schema_version=2, role="ion_processor_component_exit_export", status="prepared" if rows else "zero_exit",
                   source_run_id=run.name, source_project=PROJECT, source_run=str(run), inputs=inputs,
                   source_instance_id=source_instance_id, target_instance_id=target_instance_id,
                   producer_result=dict(source_scientific_status=summary["status"], checks=dict(summary["checks"]),
                                        functional_status=summary["functional_status"], qualification=summary["qualification"]),
                   outputs=dict(component_states=file_record(state_path) if rows else None, mother_census=file_record(census_path)),
                   counts=dict(source=len(census), transferred=len(rows), not_transferred=len(census)-len(rows)),
                   transferred_particle_ids=transferred, not_transferred_particle_ids=sorted({row["particle_id"] for row in census}-set(transferred)),
                   frame_id=frame, clock_epoch_id=clock["clock_epoch_id"],
                   units=dict(position="mm", velocity="m/s", time="us", energy="eV", mass="u"),
                   clock_semantics="instrument_epoch_plus_recorded_solver_elapsed_once; ages_from_per_id_release_birth",
                   observation_surface=dict(center_mm=list(center), normal=normal, semantics="recorded_stop_plane_not_physical_port"),
                   adapter_semantics=dict(species_id="preserved_from_injected_state" if injected else "derived_from_per_id_release_mass_and_charge",
                       particle_weight=("preserved_per_id_relative_weight_from_frozen_injected_states_not_physical_bunch_charge"
                                        if injected else "unit_independent_test_particle_count_not_physical_bunch_charge"),
                       lineage="root_source_no_reactions", phase="absent_no_transfer_phase_reference"),
                   validation=validation, lifecycle_verification=lifecycle)
    (output / "component_exit_receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt
