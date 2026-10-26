"""Freeze providers and prepare geometry, complete source and native field inputs.

The managed caller owns run creation and publication. This boundary creates no
solved fields, pulse schedule, particle selection or simulation qualification.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import shutil

from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.machine_contracts import validate_schema
from common.contracts.rigid_transform import RigidTransform, relative_transform
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.integration.resolve_assembly import derive_assembly_scope
from common.multipole.particle_source_preflight import load_validated_source
from common.ion_release.cylinder import CANONICAL_COLUMNS
from common.ion_release.release import materialize_release, validate_release_spec
from integrations.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
    binary64_serialization_close,
    published_producer_input,
    require_producer_manifest_binding,
    select_timed_pre_pulse_states,
    transform_source_rows,
)
from integrations.runtime.build_single_flight_program import validate_native_flight
from integrations.runtime.single_flight_frontend import native_frontend_instances
from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
from integrations.workflows.single_reflection_flight.fields import prepare_field_design
from integrations.workflows.single_reflection_flight.pulse import _capture_bounds

SCHEMA = Path(__file__).with_name("schema.json")
ROLE = "instrument_assembly_single_reflection_preparation_request"
FROZEN_NAMES = {
    "composition_plan": "composition_plan.json",
    "downstream_fields": "downstream_field_source_receipt.json",
    "downstream_fields_manifest": "downstream_field_source_manifest.json",
    "downstream_fields_command_plan": "downstream_field_source_command_plan.json",
    "frontend_fields": "frontend_field_source_receipt.json",
    "frontend_fields_manifest": "frontend_field_source_manifest.json",
    "frontend_fields_parent_identity": "frontend_field_source_parent_identity.json",
    "frontend_fields_entrance_refinement_identity": "frontend_field_source_entrance_refinement_identity.json",
    "particle_source": "particle_source.csv",
    "metadata": "particle_source_metadata.json",
    "release_spec": "particle_source_release_spec.json",
    "release_receipt": "particle_source_release_receipt.json",
    "pre_pulse_collection": "pre_pulse_collection.json",
    "pulse_decision": "pre_pulse_decision.json",
    "producer_manifest": "pre_pulse_producer_manifest.json",
    "pre_pulse_source_geometry": "pre_pulse_source_geometry.json",
    "pre_pulse_source_states": "pre_pulse_source_states.csv",
    "pre_pulse_source_provenance": "pre_pulse_source_provenance.json",
    "clock_authority": "clock_authority.json",
    "instrument_epoch": "instrument_epoch.json",
    "continuation_parent_manifest": "continuation_parent_manifest.json",
}
OUTPUT_NAMES = (
    "frontend_geometry.json",
    "projected_source.csv",
    "source_provenance.json",
    "frontend_field_design.json",
)
GEM_NAMES = {"parent": "frontend.gem", "entrance_refinement": "frontend_entrance_refinement.gem"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _require_field_source_binding(records: list[dict], source: Path, identity: dict, producer: Path) -> None:
    matches = [record for record in records if record_path(record, base_dir=producer) == source]
    if (len(matches) != 1 or matches[0].get("bytes") != identity["bytes"]
            or str(matches[0].get("sha256", "")).upper() != identity["sha256"].upper()):
        raise ValueError(f"field source is not uniquely identity-bound by its producer manifest: {source}")


def _source_identity_path(records: list[dict], identity: dict, producer: Path) -> Path:
    """Find the receipt producer's frozen scientific input by its bound identity."""
    owner_inputs = (producer / "inputs").resolve()
    matches = []
    for record in records:
        if (record.get("bytes") != identity.get("bytes")
                or str(record.get("sha256", "")).upper() != str(identity.get("sha256", "")).upper()):
            continue
        path = record_path(record, base_dir=producer)
        if path.is_relative_to(owner_inputs):
            matches.append(path)
    if len(matches) != 1:
        raise ValueError("frontend field identity is not uniquely bound by its receipt producer manifest")
    return matches[0]


def _read_field_source_manifest(producer: Path, *, statuses: set[str] | None = None,
                                stopped_receipt: dict | None = None) -> dict:
    """Validate a managed source run without scanning its output payloads."""
    manifest_path = producer / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("field source requires its managed producer run manifest")
    require_completed_terminal_publication(manifest_path)
    manifest = _read(manifest_path)
    allowed = {"success", "failed", "interrupted", "superseded"} if statuses is None else statuses
    if (manifest.get("schema_version") != 2 or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("status") not in allowed):
        raise ValueError("field source producer must have a terminal current run manifest")
    config_record = manifest.get("run_config", {})
    if manifest["status"] == "checkpoint" and stopped_receipt is not None:
        if (not isinstance(stopped_receipt, dict) or stopped_receipt.get("schema_version") != 1
                or stopped_receipt.get("role") != "run_capacity_lifecycle_receipt"
                or stopped_receipt.get("action") != "seal_stopped_payload"
                or stopped_receipt.get("status") != "ready" or stopped_receipt.get("run_status") != "checkpoint"
                or Path(str(stopped_receipt.get("run_directory", ""))).resolve() != producer.resolve()):
            raise ValueError("field continuation requires its public stopped checkpoint receipt")
        # Initialization manifests precede code/input freezing. Only the public
        # stopped receipt binds the final config; it grants no completed output.
        config_record = stopped_receipt.get("run_config", {})
    if (not config_record.get("path")
            or record_path(config_record, base_dir=producer) != producer / "run_config.json"):
        raise ValueError("field source producer manifest must bind its local run_config")
    verify_record("field source producer run_config", config_record, base_dir=producer)
    config = _read(producer / "run_config.json")
    if (config.get("schema_version") != 2 or config.get("project") != "instrument_assembly"
            or any(config.get(key) != manifest.get(key) for key in ("run_id", "project", "mode"))
            or manifest.get("run_id") != producer.name):
        raise ValueError("field source producer managed run identity differs")
    return manifest


def _freeze_field_source_manifest(producer: Path, destination: Path, producer_manifests: dict) -> tuple[dict, dict]:
    """Freeze one producer once within this preparation, without scanning its files."""
    if producer in producer_manifests:
        return producer_manifests[producer]
    manifest_path = producer / "run_manifest.json"
    manifest = _read_field_source_manifest(producer)
    shutil.copyfile(manifest_path, destination)
    producer_manifests[producer] = manifest, {**file_record(destination), "source_path": str(manifest_path)}
    return producer_manifests[producer]


def _freeze_frontend_source(source: Path, paths: dict[str, Path], identity: dict, producer_manifests: dict) -> dict:
    """Bind the already verified small field receipt to its terminal producer."""
    receipt = _read(paths["frontend_fields"])
    if (receipt.get("schema_version") not in (2, 3)
            or receipt.get("role") != "single_reflection_frontend_working_fields"
            or receipt.get("status") != "success"):
        raise ValueError("frontend_fields requires a successful current field-stage receipt")
    receipt_producer = source.parent.parent
    if source.parent.name != "inputs":
        raise ValueError("frontend_fields requires its managed producer inputs receipt")
    # The explicit receipt producer owns its scientific provenance. Historical
    # asset_owner fields do not grant authority over common PA generations.
    producer = receipt_producer
    manifest, manifest_record = _freeze_field_source_manifest(producer, paths["frontend_fields_manifest"], producer_manifests)
    records = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
    _require_field_source_binding(records, source, identity, producer)
    result = {"frontend_fields_manifest": manifest_record}
    domains = receipt.get("domains", [])
    if [domain["domain_id"] for domain in domains] not in (["parent"], ["parent", "entrance_refinement"]):
        raise ValueError("frontend_fields requires parent and optional entrance_refinement domains")
    for domain in domains:
        identities = [(None, domain)] if receipt['schema_version'] == 2 else [
            (row.get('working_point_id') or row['kind'], row) for row in domain['working_points']]
        for member, row in identities:
            record = row['cache_identity_record']
            original = _source_identity_path(records, record, producer)
            _require_field_source_binding(records, original, record, producer)
            suffix = domain['domain_id'] + ('' if member is None else '_' + member)
            key = 'frontend_fields_' + suffix + '_identity'
            target = paths['frontend_fields'].parent / ('frontend_field_source_' + suffix + '_identity.json')
            shutil.copyfile(original, target)
            verify_record(key, {**record, 'path': str(target)})
            result[key] = {**record, 'path': str(target), 'exists': True, 'source_path': str(original)}
    return result


def _freeze_downstream_source(source: Path, paths: dict[str, Path], identity: dict, producer_manifests: dict) -> dict:
    """Freeze a published native downstream source and its exact command plan."""
    if (source.name != "downstream_field_preparation.json" or source.parent.name != "downstream_fields"
            or source.parent.parent.name != "simion"):
        raise ValueError("downstream_fields requires its canonical producer/simion/downstream_fields publication")
    receipt = _read(paths["downstream_fields"])
    if (receipt.get("schema_version") != 1
            or receipt.get("role") != "single_reflection_downstream_field_preparation"
            or receipt.get("status") != "success"):
        raise ValueError("downstream_fields requires a successful current downstream publication")
    producer = source.parents[2]
    manifest, manifest_record = _freeze_field_source_manifest(producer, paths["downstream_fields_manifest"], producer_manifests)
    # These are published outputs; the owner's inputs may also contain an
    # identical retained record, which does not make its output ambiguous.
    records = manifest.get("outputs", [])
    _require_field_source_binding(records, source, identity, producer)
    original = source.with_name("command_plan.json")
    record = receipt["command_plan_record"]
    _require_field_source_binding(records, original, record, producer)
    destination = paths["downstream_fields_command_plan"]
    shutil.copyfile(original, destination)
    verify_record("downstream_fields_command_plan", {**record, "path": str(destination)})
    return dict(downstream_fields_manifest=manifest_record, downstream_fields_command_plan={
        **record, "path": str(destination), "exists": True, "source_path": str(original)})


def prepare(request_path: Path, run: Path) -> dict:
    """Freeze and consume one explicit request in an existing managed run.

    Request paths resolve relative to its original file. All subsequent
    consumers use returned input_records, never the external author paths.
    Existing frozen inputs and preparation outputs are never overwritten.
    """
    request_path, run = request_path.resolve(), run.absolute()
    inputs = run / "inputs"
    if not inputs.is_dir():
        raise ValueError("managed run/inputs must exist before preparation")
    frozen_request = inputs / "request.json"
    if frozen_request.exists():
        raise ValueError("preparation request already exists")
    shutil.copyfile(request_path, frozen_request)
    request = _read(frozen_request)
    validate_schema(request, SCHEMA)
    source = request["source"]
    source_keys = (
        ("particle_source", "metadata") if source["kind"] == "recorded_birth"
        else ("release_spec",) if source["kind"] == "release_spec"
        else ("pre_pulse_collection", "producer_manifest", *(
            ("pulse_decision",) if "pulse_decision" in source else ()))
    )
    parent_path = inputs / FROZEN_NAMES["composition_plan"]
    if parent_path.exists():
        raise ValueError("composition plan already exists")
    shutil.copyfile(record_path(request["composition_plan"], base_dir=request_path.parent), parent_path)
    verify_record("composition_plan", {**request["composition_plan"], "path": str(parent_path)})
    parent = _read(parent_path)
    plan = derive_assembly_scope(parent, local_scope=request.get("local_scope"))
    multipole_ids, oatof_id = native_frontend_instances(plan)
    instances = request["providers"]["instances"]
    if set(instances) != set(plan["scope"]["instance_ids"]):
        raise ValueError("provider instances must name exactly the selected assembly scope")
    if "geometry" not in instances[oatof_id] or any("geometry" in instances[instance_id] for instance_id in multipole_ids):
        raise ValueError("only the selected oaTOF provider requires an explicit accelerator geometry variant")
    selected = {
        **{key: request["providers"][key] for key in ("frontend_fields", "downstream_fields") if key in request["providers"]},
        **{"instance_design__" + key: value["resolved_design"] for key, value in instances.items()},
        **{key: source[key] for key in (*source_keys, "clock_authority", "instrument_epoch")},
    }
    paths = {key: inputs / name for key, name in FROZEN_NAMES.items()}
    paths.update({"instance_design__" + key: inputs / "components" / key / "resolved_design.json" for key in instances})
    if any(path.exists() for key, path in paths.items() if key != "composition_plan") or any(
            (inputs / name).exists() for name in (*OUTPUT_NAMES, *GEM_NAMES.values())):
        raise ValueError("preparation inputs or outputs already exist")
    # Copy closed external inputs once; verify the actual frozen bytes below.
    # In particular, do not hash the CSV before the public source loader does.
    for key, identity in selected.items():
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(record_path(identity, base_dir=request_path.parent), paths[key])
    continuation = request.get("continuation")
    continuation_inputs = {}
    if continuation is not None:
        parent_record = continuation["predecessor_run_manifest"]
        parent_manifest = record_path(parent_record, base_dir=request_path.parent)
        if parent_manifest.name != "run_manifest.json":
            raise ValueError("continuation requires its managed parent run_manifest.json")
        stopped = None
        if "frontend_field_transactions" in continuation:
            record = continuation["stopped_receipt"]
            original = record_path(record, base_dir=request_path.parent)
            destination = inputs / "continuation_stopped_receipt.json"
            shutil.copyfile(original, destination)
            frozen = {**record, "path": str(destination), "exists": True, "source_path": str(original)}
            verify_record("continuation_stopped_receipt", frozen)
            continuation_inputs["continuation_stopped_receipt"] = frozen
            stopped = _read(destination)
        parent = _read_field_source_manifest(parent_manifest.parent, statuses={"failed", "interrupted", "checkpoint"},
                                             stopped_receipt=stopped)
        if parent.get("mode") != "single_reflection_fly":
            raise ValueError("continuation parent must be a single-reflection Fly run")
        if ("frontend_field_transactions" not in continuation
                and not {"frontend_fields", "downstream_fields"} <= request["providers"].keys()):
            raise ValueError("continuation requires explicit published frontend_fields and downstream_fields")
        shutil.copyfile(parent_manifest, paths["continuation_parent_manifest"])
        verify_record("continuation parent manifest", {**parent_record, "path": str(paths["continuation_parent_manifest"])})
    for key in selected.keys() - {"particle_source", "instrument_epoch"}:
        verify_record(key, {**selected[key], "path": str(paths[key])})
    field_sources = {}
    producer_manifests = {}
    for key, freeze in (("frontend_fields", _freeze_frontend_source), ("downstream_fields", _freeze_downstream_source)):
        if key in selected:
            source_path = record_path(selected[key], base_dir=request_path.parent)
            field_sources[key] = {**selected[key], "path": str(paths[key]), "exists": True, "source_path": str(source_path)}
            field_sources.update(freeze(source_path, paths, selected[key], producer_manifests))
    selected["composition_plan"] = request["composition_plan"]
    multipoles = {instance_id: _read(paths["instance_design__" + instance_id]) for instance_id in multipole_ids}
    oatof = _read(paths["instance_design__" + oatof_id])
    if (
        oatof.get("role") != "oa_tof_resolved_contract_do_not_edit"
        or not {
            "geometry_mm",
            "coordinate_convention",
            "simion_geometry_build",
            "simion_detector_marker",
            "particle_source",
        }
        <= oatof.keys()
    ):
        raise ValueError("oaTOF provider must be its complete final resolved design")
    release_spec = None
    restart_selection = None
    restart_source_geometry = None
    if source["kind"] == "release_spec":
        release_spec = _read(paths["release_spec"])
        validate_release_spec(release_spec)
        if "frame_id" not in release_spec:
            raise ValueError("release source requires a canonical local frame_id")
        if release_spec["particle_count"] != release_spec["mother_particle_count"]:
            raise ValueError("release source must contain its complete mother population")
        source_frame = release_spec["frame_id"]
    elif source["kind"] == "recorded_birth":
        source_frame = source["frame_id"]
    else:
        original_collection = record_path(source["pre_pulse_collection"], base_dir=request_path.parent)
        original_decision = (record_path(source["pulse_decision"], base_dir=request_path.parent)
                             if "pulse_decision" in source else None)
        producer = _read(paths["producer_manifest"])
        collection = _read(paths["pre_pulse_collection"])
        decision = _read(paths["pulse_decision"]) if original_decision is not None else None
        geometry_record = collection.get("geometry_record")
        source_record = collection.get("source_record")
        if not isinstance(geometry_record, dict) or not isinstance(source_record, dict):
            raise ValueError("pre-pulse collection lacks its resolved geometry or source record")
        published_geometry = published_producer_input(producer, geometry_record)
        published_source = published_producer_input(producer, source_record)
        original_geometry = record_path(published_geometry)
        original_source_states = record_path(published_source)
        provenance_records = [record for record in producer.get("inputs", {}).values()
                              if isinstance(record, dict) and record.get("path")
                              and Path(record["path"]).name == "source_provenance.json"]
        if len(provenance_records) != 1:
            raise ValueError("pre-pulse producer must bind exactly one source provenance record")
        producer_provenance_record = provenance_records[0]
        original_source_provenance = record_path(producer_provenance_record)
        require_producer_manifest_binding(
            producer,
            geometry_path=original_geometry,
            geometry_record=published_geometry,
            collection_path=original_collection,
            collection_record=source["pre_pulse_collection"],
            pulse_decision_path=original_decision,
            pulse_decision_record=source.get("pulse_decision"),
            required_input_records={original_source_states: published_source,
                                    original_source_provenance: producer_provenance_record},
        )
        shutil.copyfile(original_geometry, paths["pre_pulse_source_geometry"])
        shutil.copyfile(original_source_states, paths["pre_pulse_source_states"])
        shutil.copyfile(original_source_provenance, paths["pre_pulse_source_provenance"])
        verify_record("pre_pulse frozen source geometry", {**geometry_record, "path": str(paths["pre_pulse_source_geometry"])})
        verify_record("pre_pulse frozen source states", {**source_record, "path": str(paths["pre_pulse_source_states"])})
        verify_record("pre_pulse frozen source provenance", {**producer_provenance_record,
                      "path": str(paths["pre_pulse_source_provenance"])})
        restart_selection = select_timed_pre_pulse_states(collection, decision)
        decision_inputs = decision.get("input_records") if decision is not None else None
        collection_request = collection.get("request_record")
        collection_geometry = collection.get("geometry_record")
        if decision is not None and (not isinstance(decision_inputs, dict) or not isinstance(collection_request, dict)
                or not isinstance(collection_geometry, dict)
                or decision_inputs.get("request") != collection_request
                or decision_inputs.get("frontend_geometry") != collection_geometry):
            raise ValueError("producer pulse decision is not bound to the timed collection request/geometry")
        restart_source_geometry = _read(paths["pre_pulse_source_geometry"])
        producer_provenance = _read(paths["pre_pulse_source_provenance"])
        source_frame = producer_provenance.get("target_frame_id")
        if (producer_provenance.get("role") != "single_reflection_source_provenance"
                or source_frame != source["frame_id"]
                or producer_provenance.get("clock_epoch_id") != collection.get("clock_epoch_id")):
            raise ValueError("pre-pulse request frame or clock differs from the producer source provenance")
    clock = _read(paths["clock_authority"])
    if clock["authority"]["path"] != "inputs/instrument_epoch.json":
        raise ValueError("clock authority must reference inputs/instrument_epoch.json")
    clock_receipt = validate_clock_authority(paths["clock_authority"], run)
    epoch_record = selected["instrument_epoch"]
    if (
        paths["instrument_epoch"].stat().st_size != epoch_record["bytes"]
        or clock_receipt["authority_sha256"] != epoch_record["sha256"].upper()
    ):
        raise ValueError("instrument epoch identity differs from author record")
    epoch = _read(paths["instrument_epoch"])["instrument_time_us"]
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
        raise ValueError("canonical instrument epoch must be finite")
    variant = instances[oatof_id]["geometry"]["accelerator_variant"]
    gems, geometry = compile_frontend_geometry(multipoles, oatof, composition_plan=plan,
        numerical_domains=request["numerics"]["frontend_domains"],
        accelerator_variant=variant,
        electrode_bindings={key: value["electrode_bindings"] for key, value in instances.items()})
    plan = geometry["composition_plan"]
    if (
        source["instance_id"] not in plan["scope"]["instance_ids"]
        or (source["kind"] != "recorded_pre_pulse_state"
            and plan["components"][source["instance_id"]]["local_frame_id"] != source_frame)
    ):
        raise ValueError("source instance/local frame differs from the selected provider scope")
    if (source["kind"] == "recorded_birth"
            and source["instance_id"] not in multipole_ids):
        raise ValueError("recorded birth source must belong to the actual multipole upstream instance")
    poses = {item["instance_id"]: RigidTransform.from_contract(item["transform"])
             for item in plan["recipe"]["instances"]}
    transform = relative_transform(poses[source["instance_id"]], poses[oatof_id])
    if source["kind"] == "recorded_pre_pulse_state":
        source_plan = restart_source_geometry["composition_plan"]
        source_component = source_plan.get("components", {}).get(source["instance_id"])
        current_component = plan["components"][source["instance_id"]]
        # Bind only the actual OA source instance.  A later parent recipe may
        # add unrelated components; those are not a source-identity change.
        if (not isinstance(source_component, dict)
                or source_component.get("project_id") != current_component.get("project_id")
                or source_component.get("local_frame_id") != current_component.get("local_frame_id")
                or source_frame != geometry["native_frame_id"]
                or source_frame != current_component.get("local_frame_id")):
            raise ValueError("pre-pulse producer OA instance or recorded native frame differs")
        bounds = _capture_bounds(geometry)
        for row in restart_selection["selected_rows"]:
            if (any(not math.isfinite(float(row[key])) for key in (
                    "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "kinetic_energy_eV"))
                    or any(not bounds[axis]["minimum_mm"] < float(row[f"{axis}_mm"]) < bounds[axis]["maximum_mm"]
                           for axis in "xyz")):
                raise ValueError("recorded pre-pulse state is outside the current OA first gap or nonfinite")
    field_design = prepare_field_design(
        multipoles,
        oatof,
        geometry,
        variant_id=variant,
        pulse_voltage_policy_id=request["pulse_voltage_policy_id"],
        flight=request.get("flight"),
        **request["numerics"],
    )
    reuse_members = request["providers"].get("frontend_field_reuse_members")
    if reuse_members is not None:
        if "frontend_fields" not in request["providers"]:
            raise ValueError("frontend_field_reuse_members requires an explicit frontend_fields provider")
        actual_members = {
            point.get("working_point_id", point["kind"])
            for point in field_design["working_points"]
        }
        if (not isinstance(reuse_members, list) or not reuse_members
                or any(not isinstance(member, str) for member in reuse_members)
                or len(set(reuse_members)) != len(reuse_members)
                or not set(reuse_members) <= actual_members):
            raise ValueError("frontend_field_reuse_members must be a nonempty subset of current working members")
    if continuation is not None and "frontend_field_transactions" in continuation:
        domains = {domain["domain_id"] for domain in field_design["domains"]}
        members = {point.get("working_point_id", point["kind"]) for point in field_design["working_points"]}
        reused = (set(reuse_members if reuse_members is not None else members)
                  if "frontend_fields" in request["providers"] else set())
        seen = set()
        for entry in continuation["frontend_field_transactions"]:
            route = (entry["domain_id"], entry["member_id"])
            if (route in seen or route[0] not in domains or route[1] not in members
                    or route[1] in reused):
                raise ValueError("frontend field continuation route is duplicate, unsupported or explicitly reused")
            seen.add(route)
        selections = [
            (f"continuation_field_transaction_{index:03d}", entry["transaction_record"])
            for index, entry in enumerate(continuation["frontend_field_transactions"], 1)
        ]
        for name, record in selections:
            original = record_path(record, base_dir=request_path.parent)
            destination = inputs / (name + ".json")
            shutil.copyfile(original, destination)
            frozen = {**record, "path": str(destination), "exists": True, "source_path": str(original)}
            verify_record(name, frozen)
            continuation_inputs[name] = frozen
    if "flight" in request:
        validate_native_flight(request["flight"], allow_discovery=True, requires_rf=any(
            point["kind"] == "rf_reference" for point in field_design["working_points"]))
    input_records = {key: {**identity, "path": str(paths[key]), "exists": True} for key, identity in selected.items()}
    input_records.update(continuation_inputs)
    if continuation is not None:
        input_records["continuation_parent_manifest"] = {
            **continuation["predecessor_run_manifest"], "path": str(paths["continuation_parent_manifest"]),
            "exists": True, "source_path": str(parent_manifest),
        }
    input_records["request"] = file_record(frozen_request)
    if source["kind"] == "recorded_pre_pulse_state":
        input_records["pre_pulse_source_geometry"] = {
            **collection["geometry_record"], "path": str(paths["pre_pulse_source_geometry"]), "exists": True,
            "source_path": str(original_geometry),
        }
        input_records["pre_pulse_source_states"] = {
            **collection["source_record"], "path": str(paths["pre_pulse_source_states"]), "exists": True,
            "source_path": str(original_source_states),
        }
        input_records["pre_pulse_source_provenance"] = {
            **producer_provenance_record, "path": str(paths["pre_pulse_source_provenance"]), "exists": True,
            "source_path": str(original_source_provenance),
        }
    input_records.update(field_sources)
    derived_source = {}
    computed_metadata = None
    if source["kind"] == "recorded_birth":
        computed_metadata, rows = load_validated_source(paths["particle_source"], multipoles[source["instance_id"]])
        source_record = selected["particle_source"]
        if (
            paths["particle_source"].stat().st_size != source_record["bytes"]
            or computed_metadata["source_sha256"] != source_record["sha256"].upper()
        ):
            raise ValueError("particle source identity differs from author record")
        if _read(paths["metadata"]) != computed_metadata:
            raise ValueError("source metadata differs from the validated complete original source")
    elif source["kind"] == "release_spec":
        # All pure source/frame/clock/geometry checks precede generation. The
        # public materializer owns CSV serialization and its identity receipt.
        materialization = materialize_release(
            release_spec, paths["particle_source"], paths["release_receipt"], spec_record=input_records["release_spec"]
        )
        with paths["particle_source"].open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
                raise ValueError("materialized source columns differ from the canonical release contract")
            rows = list(reader)
        if len(rows) != materialization["particle_count"]:
            raise ValueError("materialized source count differs from its complete mother receipt")
        derived_source = {
            "particle_source": {key: materialization["state_table"][key] for key in ("path", "bytes", "sha256")},
            "release_receipt": file_record(paths["release_receipt"]),
        }
    else:
        assert restart_selection is not None
        rows = restart_selection["selected_rows"]
        with paths["pre_pulse_source_states"].open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != tuple(GLOBAL_COLUMNS):
                raise ValueError("pre-pulse producer source columns differ from the canonical source contract")
            original_rows = list(reader)
        source_rows = {int(row["particle_id"]): row for row in original_rows}
        if (len(source_rows) != len(original_rows)
                or set(source_rows) != set(restart_selection["mother_particle_ids"])):
            raise ValueError("pre-pulse producer source population differs from its mother record")
        if any(not binary64_serialization_close(float(source_rows[particle_id]["instrument_time_us"]), float(birth))
               for particle_id, birth in restart_selection["original_birth_times_us"].items()):
            raise ValueError("pre-pulse producer source birth clock differs from its canonical collection")
        projected = [
            {
                "particle_id": str(row["particle_id"]),
                "instrument_time_us": format(float(row["instrument_time_us"]), ".17g"),
                "mass_amu": source_rows[int(row["particle_id"])]["mass_amu"],
                "charge_state": source_rows[int(row["particle_id"])]["charge_state"],
                **{f"position_{axis}_mm": format(float(row[f"{axis}_mm"]), ".17g") for axis in "xyz"},
                **{f"velocity_{axis}_m_s": format(1000.0 * float(row[f"v{axis}_mm_per_us"]), ".17g") for axis in "xyz"},
                "kinetic_energy_eV": format(float(row["kinetic_energy_eV"]), ".17g"),
            }
            for row in rows
        ]
    if source["kind"] != "recorded_pre_pulse_state":
        projected = transform_source_rows(rows, transform)
    restart_provenance = {}
    if source["kind"] == "recorded_pre_pulse_state":
        assert restart_selection is not None
        if restart_selection["clock_epoch_id"] != clock_receipt["clock_epoch_id"]:
            raise ValueError("pre-pulse producer clock epoch differs from this request")
        restart_provenance = dict(
            continued_particle_ids=restart_selection["selected_particle_ids"],
            continued_particle_count=len(restart_selection["selected_particle_ids"]),
            original_mother_particle_ids=restart_selection["mother_particle_ids"],
            original_mother_particle_count=len(restart_selection["mother_particle_ids"]),
            uncontinued_mother_particle_ids=sorted(set(restart_selection["mother_particle_ids"]) - set(restart_selection["selected_particle_ids"])),
            restart_state_time_us=restart_selection["pulse_time_us"],
            original_birth_times_us={str(key): value for key, value in restart_selection["original_birth_times_us"].items()},
            selection_basis=restart_selection["selection_basis"],
        )
    provenance = dict(
        schema_version=1, role="single_reflection_source_provenance", stage="geometry_preparation_only",
        source_kind=source["kind"], source_instance_id=source["instance_id"],
        source_frame_id=source_frame, target_frame_id=transform.to_frame_id,
        transform=(None if source["kind"] == "recorded_pre_pulse_state" else transform.to_contract()),
        particle_count=len(rows),
        population_policy=("recorded_pre_pulse_continuation_no_resampling_no_reindex"
            if source["kind"] == "recorded_pre_pulse_state" else
            "complete_original_source_no_selection_no_resampling" if source["kind"] == "recorded_birth" else
            "complete_release_spec_mother_generated_once_no_selection"),
        clock_epoch_id=clock_receipt["clock_epoch_id"], instrument_epoch_us=epoch,
        state_time_semantics=("recorded_pre_pulse_state_time_us_no_epoch_shift"
            if source["kind"] == "recorded_pre_pulse_state" else "original_birth_time_s_times_1e6_no_epoch_shift"),
        source_metadata=computed_metadata, derived_source=derived_source, input_records=input_records,
        **restart_provenance,
    )
    gem_records = {}
    for domain in field_design["domains"]:
        domain_id = domain["domain_id"]
        path = inputs / GEM_NAMES[domain_id]
        path.write_text(gems[domain_id], encoding="utf-8", newline="\n")
        record = file_record(path)
        domain["gem_sha256"] = record["sha256"]
        gem_records[path.stem] = record
    _write(inputs / "frontend_field_design.json", field_design)
    _write(inputs / "frontend_geometry.json", geometry)
    with (inputs / "projected_source.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(projected)
    _write(inputs / "source_provenance.json", provenance)
    return dict(
        schema_version=1,
        role="single_reflection_geometry_preparation",
        stage="geometry_preparation_only",
        particle_count=len(rows),
        input_records=input_records,
        outputs={
            **{
                Path(name).stem: file_record(inputs / name)
                for name in OUTPUT_NAMES
            },
            **gem_records,
            **derived_source,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.request, args.run)
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
