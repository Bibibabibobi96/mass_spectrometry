"""Prepare a zero-gap real multipole exit handoff in the receiver's native frame.

This workflow consumes sealed small records, never PA payloads. It does not fly,
propagate across a gap, clip particles to the receiver bore, or qualify fringe
field truncation. The managed public caller owns run lifecycle and code freezing.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
from typing import Any

from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.contracts.particle_state import write_component_particle_state_csv
from msplatform.contracts.machine_contracts import validate_schema
from msplatform.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from msplatform.contracts.rigid_transform import RigidTransform, relative_transform
from msplatform.contracts.clock import ClockIdentity, age_us, seconds_to_microseconds
from msplatform.assembly.handoff import HandoffClock, HandoffMother, HandoffSelection, prepare_handoff_states
from msplatform.io.manifest_records import record_path, verify_record as _verify_record
from functools import partial
from msplatform.io.manifest_records import file_record as _file_record
from msplatform.execution.retention import classify_file

file_record = partial(_file_record, retention_classifier=classify_file)
verify_record = partial(_verify_record, retention_classifier=classify_file)
from msplatform.io.manifest_records import require_completed_terminal_publication
from msplatform.assembly.resolve_assembly import derive_assembly_scope
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
from msplatform.backends.simion.rf_observations import validate_exit_observations
from msplatform.backends.simion.rf_assembly_interface import build_legacy_assembly_interface
from msplatform.components.dual_pressure_rectilinear_ion_processor.assembly_interface import resolve_assembly_interface
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
from msplatform.backends.simion.ip_handoff import FATE_COLUMNS
from msplatform.backends.simion.transport_result import load_transport_producer_result

SCHEMA = Path(__file__).with_name("request.schema.json")
FRAME = "dual_pressure_ion_processor_local_v1"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def load_request(path: Path) -> dict[str, Any]:
    """Resolve the three transported record paths against the author request."""
    path = path.resolve()
    request = _read(path)
    validate_schema(request, SCHEMA)
    for record in (request["source"]["manifest"], request["receiver"]["manifest"], request["composition_plan"]):
        record["path"] = str(record_path(record, base_dir=path.parent))
    return request


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _producer(selection: dict, base: Path) -> tuple[Path, dict]:
    record = selection["manifest"]
    verify_record("selected producer manifest", record, base_dir=base)
    path = record_path(record, base_dir=base)
    require_completed_terminal_publication(path)
    manifest = _read(path)
    if (manifest.get("status") not in {"success", "failed"} or manifest.get("run_id") != selection["run_id"]
            or manifest.get("project") != selection["project_id"]):
        raise ValueError("producer must be terminal and match the explicit project/run identity")
    verify_record("producer run_config", manifest["run_config"], base_dir=path.parent)
    config = _read(record_path(manifest["run_config"], base_dir=path.parent))
    if any(config.get(key) != selection[expected] for key, expected in
           (("run_id", "run_id"), ("project", "project_id"))):
        raise ValueError("producer run_config differs from selected project/run identity")
    return path.parent, manifest


def _consume(run: Path, manifest: dict, relative: str) -> Path:
    """Verify only a uniquely declared record actually consumed by this preparation."""
    path = (run / relative).resolve()
    matches = [record for record in [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
               if record_path(record, base_dir=run) == path]
    if len(matches) != 1:
        raise ValueError("producer must declare exactly one consumed record: " + relative)
    verify_record("multipole/IP consumed " + relative, matches[0], base_dir=run)
    return path


def _layout(plan: dict, source: dict, receiver_projection: dict) -> tuple[RigidTransform, dict]:
    recipe = plan['recipe']
    selected=plan['scope']['instance_ids']
    upstream_ids=[key for key in selected if plan['components'][key]['project_id']==source['project_id']]
    receiver_ids=[key for key in selected if plan['components'][key]['project_id']=='dual_pressure_rectilinear_ion_processor']
    if len(selected)!=2 or len(upstream_ids)!=1 or len(receiver_ids)!=1 or upstream_ids==receiver_ids:
        raise ValueError(f'multipole/IP state handoff supports exactly one selected real multipole and IP; selected={selected}')
    upstream_id,receiver_id=upstream_ids[0],receiver_ids[0]
    receiver=resolve_assembly_interface(receiver_projection,
        geometry_profile_id=plan['components'][receiver_id]['geometry_profile_id'])
    if plan['components'][upstream_id]!=source or plan['components'][receiver_id]!=receiver:
        raise ValueError('selected multipole/IP provider interface differs from the frozen parent composition plan')
    edges=[edge for edge in recipe['connections'] if edge['connection_id'] in plan['scope']['connection_ids']]
    if len(edges)!=1:
        raise ValueError('selected multipole/IP scope requires one mechanical_exit to guide_inlet connection')
    edge=edges[0]
    upstream, downstream = edge["upstream"], edge["downstream"]
    if (upstream["instance_id"] != upstream_id or downstream['instance_id'] != receiver_id
            or upstream["port_id"] != "mechanical_exit" or downstream["port_id"] != "guide_inlet"
            or edge["gap_mm"] != 0 or edge["coupling_mode"] != "state_handoff"):
        raise ValueError("only direct zero-gap mechanical_exit to guide_inlet state_handoff is implemented")
    poses = {item["instance_id"]: RigidTransform.from_contract(item["transform"])
             for item in recipe["instances"]}
    if recipe["integration_id"] != "instrument_assembly":
        raise ValueError("multipole/IP requires the instrument assembly owner")
    # The solver consumes IP-local states; the frozen parent keeps its own poses.
    return relative_transform(poses[upstream_id], poses[receiver_id]), edge


def _canonical_rows(events: list[dict], source: dict, pose: RigidTransform,
                    request: dict, clock: dict, connection: dict) -> list[dict]:
    rows = []
    for event in events:
        if event["event"] != "mechanical_exit":
            continue
        pid = int(event["particle_id"])
        original = source[pid]
        position = (float(event["transverse_x_mm"]), float(event["transverse_y_mm"]), float(event["axial_z_mm"]))
        velocity = (float(event["velocity_x_m_s"]), float(event["velocity_y_m_s"]), float(event["velocity_axial_m_s"]))
        mass, charge = float(original["mass_amu"]), int(original["charge_state"])
        birth, arrival = seconds_to_microseconds(float(original["birth_time_s"])), float(event["time_us"])
        row = dict(particle_id=pid, parent_particle_id=None, generation=0,
            species_id=request["species_id"], particle_weight=request["particle_weight"],
            source_component_id=connection["upstream"]["instance_id"],
            target_component_id=connection["downstream"]["instance_id"], state_event="mechanical_exit",
            frame_id=pose.from_frame_id, clock_epoch_id=clock["clock_epoch_id"], instrument_time_us=arrival,
            lineage_age_us=age_us(arrival, birth_time_us=birth), particle_age_us=age_us(arrival, birth_time_us=birth),
            last_component_elapsed_time_us=age_us(arrival, birth_time_us=birth),
            lineage_birth_time_us=birth, particle_birth_time_us=birth,
            mass_amu=mass, charge_state=charge, mass_to_charge_Th=mass_to_charge_th(mass, charge),
            kinetic_energy_eV=kinetic_energy_ev(mass, *velocity), phase_reference_id=None, phase_rad=None)
        row.update({f"position_{axis}_mm": value for axis, value in zip("xyz", position, strict=True)})
        row.update({f"velocity_{axis}_m_s": value for axis, value in zip("xyz", velocity, strict=True)})
        rows.append(row)
    identity = ClockIdentity(clock["clock_epoch_id"], clock["authority"]["sha256"])
    # This workflow explicitly inherits the verified producer authority unchanged;
    # the receiver's current epoch-zero schedule restriction is checked outside.
    mother = HandoffMother(records={pid: dict(species_id=request["species_id"],
        mass_amu=float(original["mass_amu"]), charge_state=int(original["charge_state"]),
        particle_weight=request["particle_weight"],
        particle_birth_time_us=seconds_to_microseconds(float(original["birth_time_s"])),
        source_record=dict(original)) for pid, original in source.items()},
        fates=tuple(dict(event, particle_id=int(event["particle_id"])) for event in events if event["event"] == "terminal"))
    result = prepare_handoff_states(rows, transform=pose, clock=HandoffClock(identity, identity),
        selection=HandoffSelection("plane_crossing", tuple(sorted(row["particle_id"] for row in rows))), mother=mother)
    return list(result.rows)


def prepare(request_path: Path, run: Path) -> dict[str, Any]:
    """Write a small frozen IP admission package into a new managed run.

    ``run/inputs`` must already exist; lifecycle creation/publication belongs to
    the public wrapper. All source, geometry and observation validation precedes
    output creation. Existing preparation outputs are never overwritten.
    """
    request_path, run = request_path.resolve(), run.resolve()
    request = load_request(request_path)
    source_run, source_manifest = _producer(request["source"], request_path.parent)
    receiver_run, receiver_manifest = _producer(request["receiver"], request_path.parent)
    if receiver_manifest["status"] != "success":
        raise ValueError("receiver geometry must retain its successful provider publication")
    producer_result = load_transport_producer_result(source_manifest, source_run)
    names = ["multipole_resolved_design", "particle_source", "mechanical_exit_interface",
             "mechanical_exit_observation", "clock_authority", "instrument_epoch"]
    paths = {name: _consume(source_run, source_manifest,
                           "inputs/" + name + (".csv" if name == "particle_source" else ".json")) for name in names}
    case = request["source"]["case_id"]
    states = _consume(source_run, source_manifest, f"results/mechanical_exit_states__{case}.csv")
    census_path = _consume(source_run, source_manifest, f"results/mechanical_exit_census__{case}.json")
    resolved = _read(paths["multipole_resolved_design"])
    if resolved["identity"]["project_id"] != request["source"]["project_id"]:
        raise ValueError("multipole resolved project differs from selected producer")
    interface = _read(paths["mechanical_exit_interface"])
    if interface["schema_version"] in (1, 2):
        expected = build_legacy_assembly_interface(resolved,
            geometry_profile_id=interface["geometry_profile_id"], schema_version=interface["schema_version"])
    else:
        expected = build_assembly_interface(resolved, geometry_profile_id=interface["geometry_profile_id"])
    if interface != expected:
        raise ValueError("mechanical exit interface differs from its real resolved geometry")
    observation = _read(paths["mechanical_exit_observation"])
    port = interface["ports"]["mechanical_exit"]
    aperture = port["cross_section"].get("radius_mm")
    if (observation.get("role") != "multipole_mechanical_exit_observation"
            or observation["frame_id"] != interface["local_frame_id"]
            or observation["mechanical_exit_z_mm"] != port["center_mm"][2]
            or observation["aperture_radius_mm"] != aperture):
        raise ValueError("observations must use the actual mechanical exit frame/plane/bore")
    census = validate_exit_observations(states, paths["particle_source"], observation)
    if census != _read(census_path):
        raise ValueError("published mechanical-exit census differs from actual native records")
    model_path = _consume(receiver_run, receiver_manifest, "inputs/resolved_model.json")
    model = _read(model_path)
    inputs=run/'inputs'
    if not inputs.is_dir():
        raise ValueError('managed run inputs directory must exist')
    parent_path=inputs/'parent_composition_plan.json'
    if parent_path.exists():
        raise ValueError('refuse to overwrite frozen parent composition plan')
    shutil.copyfile(record_path(request['composition_plan'],base_dir=request_path.parent),parent_path)
    verify_record('parent composition plan',{**request['composition_plan'],'path':str(parent_path)})
    plan=derive_assembly_scope(_read(parent_path),local_scope=request.get('local_scope'))
    pose, connection = _layout(plan, interface, native_projection(model["baseline"], model["numerics"]))
    clock = _read(paths["clock_authority"])
    validate_clock_authority(paths["clock_authority"], source_run)
    if clock["authority"]["path"] != "inputs/instrument_epoch.json":
        raise ValueError("multipole epoch authority must retain its frozen inputs/instrument_epoch.json path")
    if _read(paths["instrument_epoch"])[clock["authority"]["field"]] != 0:
        raise ValueError("IP native schedule requires the inherited instrument epoch zero")
    source = {int(row["particle_id"]): row for row in _rows(paths["particle_source"])}
    events = _rows(states)
    rows = _canonical_rows(events, source, pose, request, clock, connection)
    inputs, output = run / "inputs", run / "results/multipole_ip"
    if not inputs.is_dir():
        raise ValueError("managed run inputs directory must exist")
    if any((inputs / name).exists() for name in ("clock_authority.json", "instrument_epoch.json")):
        raise ValueError("refuse to overwrite frozen clock inputs")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("clock_authority", "instrument_epoch"):
        shutil.copyfile(paths[name], inputs / (name + ".json"))
    _write(output / "composition_plan.json", plan)
    _write(output / "mother_census.json", census)
    with (output / "mother_fates.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FATE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for event in events:
            if event["event"] == "terminal":
                original = source[int(event["particle_id"])]
                writer.writerow(dict(particle_id=event["particle_id"], particle_birth_time_us=float(original["birth_time_s"])*1e6,
                    mass_amu=original["mass_amu"], charge_state=original["charge_state"],
                    terminal_instrument_time_us=event["time_us"], terminal_reason=event["terminal_reason"],
                    particle_weight=request["particle_weight"]))
    state_path = output / "source_states.csv"
    if rows:
        write_component_particle_state_csv(state_path, rows)
    package = dict(schema_version=1, role="ip_injected_source", frame_id=FRAME,
        target_component_id=connection["downstream"]["instance_id"],
        producer_case_id=case, clock_authority=file_record(inputs / "clock_authority.json"),
        producer_manifest=dict(request["source"]["manifest"],
            path=str(record_path(request["source"]["manifest"], base_dir=request_path.parent))),
        source_states=file_record(state_path) if rows else None,
        mother_census=file_record(output / "mother_census.json"), mother_fates=file_record(output / "mother_fates.csv"))
    _write(output / "ip_injected_source.json", package)
    receipt = dict(schema_version=1, role="multipole_ip_preparation", status="success",
        execution_scope="prepare_only_no_solver", source=request["source"], receiver=request["receiver"],
        mother_count=census["mother_count"], exit_count=len(rows), producer_result=producer_result,
        injected_source=file_record(output / "ip_injected_source.json"), receiver_model=file_record(model_path),
        composition_plan=file_record(parent_path),
        qualification="real exit state mapping only; independent fields and entrance truncation unqualified; no IP flight")
    _write(output / "preparation_receipt.json", receipt)
    return receipt


def _prepare_managed(session, *, request: dict, author_record: dict) -> dict:
    """Run the existing preparation in the sole owner's new package."""
    from msplatform.execution.recorded_file_removal import write_json_atomic
    run = session.artifact_run_dir
    request_path = session.declare_file(run / "inputs/multipole_ip_request.json", "required_evidence")
    verify_record("author multipole/IP request", author_record)
    session.add_input("author_request", author_record)
    write_json_atomic(request_path, request)
    session.add_input("request", file_record(request_path, "required_evidence"))
    for name in ("source", "receiver"):
        original = request[name]["manifest"]
        verify_record(name + " manifest", original)
        session.add_input(name + "_manifest", file_record(Path(original["path"]), "required_evidence"))
    receipt = prepare(request_path, run)
    for name in ("clock_authority", "instrument_epoch", "parent_composition_plan"):
        session.add_input(name, file_record(run / "inputs" / (name + ".json"), "required_evidence"))
    output = run / "results/multipole_ip"
    outputs = []
    for name in ("composition_plan.json", "mother_census.json", "mother_fates.csv", "source_states.csv",
                 "ip_injected_source.json", "preparation_receipt.json"):
        path = output / name
        if name == "source_states.csv" and receipt["exit_count"] == 0:
            continue
        if not path.is_file():
            raise ValueError("Multipole/IP preparation output is missing: " + name)
        session.declare_file(path, "required_evidence")
        outputs.append(str(path))
    verify_record("unchanged author multipole/IP request", author_record)
    return dict(status="success", summary=receipt, output_paths=outputs, required_output_paths=outputs,
                retention_preserve_paths=[], manifest_extra_fields={})


def prepare_managed(request_path: Path, *, context, run_id: str | None = None) -> dict:
    """Publish real-exit state preparation without an IP simulation or new owner.

    Machine deployment and the preparation engineering policy are explicit.
    The historical 16 MiB commitment is a selectable engineering profile value,
    never a science restriction or a second machine ledger.
    """
    from datetime import datetime
    from uuid import uuid4
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    request_path = Path(request_path).resolve(strict=True)
    author_record = file_record(request_path, "required_evidence")
    request = load_request(request_path)
    verify_record("author multipole/IP request", author_record)
    stage, budget = read_stage_policy(context, "prepare_multipole_ip", required_roles=("required_evidence",))
    if stage.get("runtime", {}):
        raise ValueError("Multipole/IP preparation has no runtime overrides")
    return run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="multipole_ip_preparation", software=["Python 3.11"]),
        run_id=run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "__analysis__python__multipole-ip-" + uuid4().hex[:12],
        payload=dict(action="prepare_multipole_ip", request=request, stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"], commitment_inputs=[budget],
        source_references=[dict(manifest_record=request[name]["manifest"],
            protected_paths=[str(Path(request[name]["manifest"]["path"]).parent)]) for name in ("source", "receiver")],
        retention=stage["artifact_retention"], expected_operation_ids=(), operation_dependencies={},
        action=partial(_prepare_managed, request=request, author_record=author_record),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        completion_api=no_particle_batch_completion_api)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run", type=Path, help="Existing managed run; preparation only, no owner publication")
    target.add_argument("--environment", type=Path, help="Explicit saved machine deployment")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.run is not None:
        if args.workspace is not None or args.profile is not None or args.run_id is not None:
            parser.error("--run does not accept managed deployment/run options")
        result = prepare(args.request, args.run)
    else:
        if args.workspace is None or args.profile is None:
            parser.error("--environment requires --workspace and --profile")
        from msplatform.execution.context import load_environment
        result = prepare_managed(args.request, context=load_environment(args.environment,
            workspace=args.workspace, profile=args.profile), run_id=args.run_id)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
