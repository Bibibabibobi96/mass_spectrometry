"""Prepare the four/five-slot workbench from explicit frozen inputs; never Fly.

The public caller owns the run, downstream producer-manifest projection and
PA read guards. This module checks the small published records and returns the
exact PA records to protect before invoking the IOB builder. It never searches
for a Formal/latest asset, copies a PA family, or transforms source rows again.
"""
from __future__ import annotations

import csv
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import stat
from typing import Any

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from common.simion.pa_family_cache import canonical_pa_family_cache_key, canonical_json_sha256
from common.simion.particle_batching import batch_plan_from_dispatch
from integrations.runtime.build_single_flight_program import (
    build_successor_program, validate_native_flight,
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
)
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS, render_restart_fly2, lua_value as _lua_value
from integrations.runtime.single_flight_frontend import instance_design_record, native_frontend_instances
from integrations.workflows.single_reflection_flight.field_plan import (
    frontend_field_identity, validate_frozen_generation_metadata, working_point_member_id, _member_projection,
)

_SOURCES = {
    "analyzer_component_source": "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_analyzer_component.lua",
    "pulse_hook_source": "integrations/runtime/single_flight_pulse_hook.lua",
    "frontend_hook_source": "integrations/runtime/single_flight_frontend_hook.lua",
    "rf_drive_kernel_source": "common/multipole/simion_rf_drive.lua",
    "voltage_waveforms_source": "common/simion/voltage_waveforms.lua",
}
_SLOTS = {"flight_tube": 1, "reflectron": 2, "accelerator": 3, "detector": 4}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _small_record(record: dict, label: str) -> Path:
    verify_record(label, record)
    return record_path(record)


def _pa_record(record: dict, base: Path, label: str) -> dict:
    """Reuse the publisher identity; the caller holds the public PA guard."""
    path = record_path(record)
    if (not path.is_relative_to(base.resolve()) or not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or not re.fullmatch(r"[A-Fa-f0-9]{64}", str(record.get("sha256", "")))):
        raise ValueError(f"{label}: published PA path/size/identity differs: {path}")
    return {**record, "path": str(path)}


def _frontend_fields(receipt_path: Path, design: dict) -> tuple[dict, dict]:
    """Bind published ordinary PA members by stable physical member identity."""
    stage = _read(receipt_path)
    if (stage.get("schema_version") != 3 or stage.get("role") != "single_reflection_frontend_working_fields"
            or stage.get("status") != "success" or design.get("schema_version") != 3):
        raise ValueError("completed current frontend domain field-stage receipt is required")
    points = design["working_points"]
    kinds = [point["kind"] for point in points]
    members = [working_point_member_id(point) for point in points]
    expected_kinds = ['carrier_off', *[kind for kind in kinds if kind == 'rf_reference'],
                      *(['pulse_delta'] if 'pulse_delta' in kinds else [])]
    if kinds != expected_kinds or len(members) != len(set(members)):
        raise ValueError("frontend requires ordered unique carrier/RF/pulse working members")
    requires_rf = "rf_reference" in kinds
    if (requires_rf and stage.get("rf_reference_voltage_v") != design["rf_reference_voltage_v"]) or (
            not requires_rf and ("rf_reference_voltage_v" in stage or "rf_reference_voltage_v" in design)):
        raise ValueError("frontend receipt RF reference differs from the actual field design")
    names = [domain["domain_id"] for domain in design["domains"]]
    if names not in (["parent"], ["parent", "entrance_refinement"]) or [d["domain_id"] for d in stage["domains"]] != names:
        raise ValueError("frontend field receipt numerical domains differ from the design")
    fields, rows, parent_fields = {}, [], {}
    for index, domain in enumerate(stage["domains"], 1):
        name = domain["domain_id"]
        records = domain["working_points"]
        if [working_point_member_id(record) for record in records] != members:
            raise ValueError("frontend domain requires ordered published working members")
        prefix = "frontend" if name == "parent" else "frontend_entrance_refinement"
        by_member = {}
        for point, record in zip(points, records, strict=True):
            member = working_point_member_id(point)
            identity = _read(_small_record(record["cache_identity_record"], name + " " + member + " identity"))
            expected = frontend_field_identity(design, name, member_id=member,
                parent_fields=parent_fields if name != "parent" else None)
            if record["source_schema_version"] == 2:
                candidates = [value for value in identity["working_points"] if value["kind"] == point["kind"]
                    and value["electrode_voltages_v"] == expected["working_points"][0]["electrode_voltages_v"]]
                if len(candidates) != 1:
                    raise ValueError("historical source member is ambiguous")
                projection = _member_projection(identity, candidates[0], member_id=member)
            elif record["source_schema_version"] == 3:
                projection = identity
            else:
                raise ValueError("unsupported field member source schema")
            if (any(projection.get(key) != value for key, value in expected.items())
                    or canonical_pa_family_cache_key(identity) != record["cache_key"]):
                raise ValueError("frontend field member differs from the prepared domain/parent/GEM")
            generation = Path(record["generation_directory"]).resolve()
            filename = f"{prefix}.{member}.pa"
            validate_frozen_generation_metadata(dict(identity=identity, cache_key=record["cache_key"],
                filenames=record["cache_filenames"], frozen_field_source=dict(working_points=[record])), generation)
            if record_path(record) != generation / filename:
                raise ValueError("frontend working member must reference its canonical common generation")
            row_record = _pa_record(record, generation, name + " " + member)
            if row_record.get("read_only") is not True or Path(row_record["path"]).stat().st_mode & stat.S_IWRITE:
                raise ValueError("frontend working point is not a read-only standalone PA")
            audit = _read(_small_record(record["audit_record"], "field member audit"))
            if audit.get("status") != "pass":
                raise ValueError("field member lacks a successful native audit")
            by_member[member] = row_record
            if name == "parent":
                parent_fields[member] = dict(cache_key=record["cache_key"], record=record)
        rf_members = [member for member, point in zip(members, points, strict=True) if point["kind"] == "rf_reference"]
        row = dict(role="coarse_frontend" if name == "parent" else name, instance_index=index,
                   carrier_pa_basename=Path(by_member["carrier_off"]["path"]).name)
        if "pulse_delta" in by_member:
            row['pulse_delta_pa_basename'] = Path(by_member['pulse_delta']['path']).name
        if rf_members:
            row.update(rf_differential_pa_basenames=[Path(by_member[member]["path"]).name for member in rf_members],
                       rf_reference_voltage_v=design["rf_reference_voltage_v"])
        rows.append(row)
        fields[name] = by_member
    bank = _read(_small_record(stage["field_bank_record"], "frontend field bank"))
    expected_bank = dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
        runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION, dynamic_roles=rows)
    if bank != expected_bank:
        raise ValueError("frontend bank differs from its published field records")
    for row in rows:
        row.update(role="accelerator_main" if row["role"] == "coarse_frontend" else "entrance_refinement",
                   instance_index=3 if row["instance_index"] == 1 else 5)
    return fields, expected_bank


def _downstream_fields(record: dict, oatof_record: dict, manifest_record: dict | None = None) -> tuple[dict, dict, list[dict]]:
    receipt = _read(_small_record(record, "downstream field publication"))
    if (receipt.get("schema_version") != 1
            or receipt.get("role") != "single_reflection_downstream_field_preparation"
            or receipt.get("status") != "success"
            or receipt.get("native_family_origin") != "generated_in_producer_run"):
        raise ValueError("a published downstream field preparation receipt is required")
    provider = receipt["oatof_resolved_record"]
    if any(str(provider[key]).upper() != str(oatof_record[key]).upper() for key in ("bytes", "sha256")):
        raise ValueError("downstream fields differ from the frozen final oaTOF provider")
    producer = Path(receipt["run_directory"]).absolute()
    output_records: list[dict] = []
    if manifest_record is None:
        if not record_path(record).is_relative_to(producer.resolve()):
            raise ValueError("downstream receipt is outside its producer run")
    else:
        manifest = _read(_small_record(manifest_record, "downstream source manifest"))
        source_path = Path(manifest_record.get("source_path", "")).absolute()
        canonical_producer = source_path.parent
        transport_producer = producer
        if manifest.get("role") != "simulation_run_manifest":
            raise ValueError("downstream source manifest does not identify its producer")
        producer = canonical_producer
        output_records = list(manifest.get("outputs", []))

    def published(record: dict, label: str) -> dict:
        if manifest_record is None:
            return _pa_record(record, producer, label)
        # Old receipts may retain an execution-alias spelling.  Resolve only
        # through the frozen terminal manifest, never by scanning a producer.
        source_path = record_path(record)
        if not source_path.is_relative_to(transport_producer.resolve()):
            raise ValueError(f"{label}: published PA is outside the receipt transport root")
        expected_path = producer / source_path.relative_to(transport_producer.resolve())
        matches = [candidate for candidate in output_records
                   if Path(candidate.get("path", "")).absolute() == expected_path.absolute()
                   and all(candidate.get(key) == record.get(key) for key in ("bytes", "sha256"))]
        if len(matches) != 1:
            raise ValueError(f"{label}: source manifest does not uniquely publish this PA")
        candidate = matches[0]
        path = record_path(candidate)
        return _pa_record({**record, "path": str(path)}, producer, label)
    assets = receipt["assets"]
    if len(assets) != 3 or {r["role"] for r in assets} != {"flight_tube", "reflectron", "detector"}:
        raise ValueError("downstream publication must bind exactly three physical roles")
    rows, carriers, guards = [], {}, []
    for asset in assets:
        role = asset["role"]
        carrier = published(asset["carrier_record"], role)
        carriers[role] = carrier
        row = dict(role=role, instance_index=_SLOTS[role], representation=asset["representation"],
                   carrier_pa_basename=Path(carrier["path"]).name)
        if role in {"flight_tube", "detector"}:
            family = [published(r, role) for r in asset["family_records"]]
            matches = [r for r in family if r["path"] == carrier["path"]]
            if (len({r["path"] for r in family}) != len(family) or len(matches) != 1
                    or any(matches[0][key] != carrier[key] for key in ("bytes", "sha256"))):
                raise ValueError(f"{role}: native family duplicates or omits its carrier")
            if any(Path(r["path"]).parent != Path(carrier["path"]).parent for r in family):
                raise ValueError(f"{role}: native family companions must share the carrier directory")
            row["family_members"] = [Path(r["path"]).name for r in family]
            guards.extend(family)
        else:
            if asset["family_records"]:
                raise ValueError("reflectron runtime publication must contain only its voltageized standalone PA")
            guards.append(carrier)
        rows.append(row)
    contract = dict(schema_version=1, role="single_reflection_downstream_static_assets",
        runtime_representation="run_private_native_surface_and_standalone_static_v1",
        receipt={key: record[key] for key in ("path", "bytes", "sha256")}, static_roles=rows)
    return carriers, contract, guards


def _instance_rows(geometry: dict, metadata: dict, carriers: dict) -> list[dict]:
    downstream = {"flight_tube" if r["role"] == "flight_tube_shield" else r["role"]: r
                  for r in geometry["downstream_pa_instances"]}
    result = []
    slots = dict(_SLOTS)
    if "entrance_refinement" in geometry["numerical_domains"]:
        slots["entrance_refinement"] = 5
    for role, index in slots.items():
        if role in {"accelerator", "entrance_refinement"}:
            domain = geometry["numerical_domains"]["parent" if role == "accelerator" else role]
            grid = dict(domain["dimensions"])
            grid.update({f"d{a}_mm": domain["cell_mm_xyz"][a] for a in "xyz"})
            placement = dict(**{f"{a}_mm": domain["instance_origin_mm"][a] for a in "xyz"},
                             az_deg=0., el_deg=0., rt_deg=0., scale=1.)
        else:
            row = downstream[role]
            if row["workbench_index"] != index or row["priority_number"] != index:
                raise ValueError(f"provider {role} slot/priority differs from the four-domain workbench")
            grid = {key: row[key] for key in ("nx", "ny", "nz")}
            n = row["grid_numerics"]
            pitches = ([n["cell_xy_mm"], n["cell_xy_mm"], n["cell_z_mm"]] if role == "detector"
                       else [n["cell_axial_mm"], n["cell_radial_mm"], n["cell_radial_mm"]])
            grid.update(dict(zip(("dx_mm", "dy_mm", "dz_mm"), pitches, strict=True)))
            placement = metadata["provider_placements"][role]
        result.append(dict(role=role, instance_index=index, priority_number=index,
                           path=Path(carriers[role]["path"]).as_posix(), grid=grid,
                           placement=placement))
    return result


def native_priority_occupancy_probes(geometry: dict, design: dict, *,
                                    terminal_observations: list[dict] | None = None) -> list[dict]:
    """Freeze declared native point checks; terminal neighborhoods are observations.

    Every field sample retains its source integer-node electrode check. Node
    positions are observations in continuous collision space; physical metal
    must support an adjacent full cell, while ideal sheets need no volume.
    Exact numerical faces retain world-query observations without asserting boundary instance choice;
    these checks do not qualify boundary-field continuity or dynamic fields.
    """
    if design.get("surface") != "none":
        raise ValueError("adjacent electrode-node cell checks require surface=none")
    domains = {row["domain_id"]: row for row in design["domains"]}
    parent, fine = domains["parent"], domains.get("entrance_refinement")

    def selected(point):
        return 5 if fine and all(fine["bounds_mm"][axis + "_min"] < value <
                                 fine["bounds_mm"][axis + "_max"]
                                 for axis, value in zip("xyz", point, strict=True)) else 3

    probes = []
    for domain in domains.values():
        for sample in domain["physical_samples"]:
            point = [domain["instance_origin_mm"][axis] + domain["cell_mm_xyz"][axis] * gu
                     for axis, gu in zip("xyz", sample["gu"], strict=True)]
            on_boundary = any(gu in (0, domain["dimensions"]["n" + axis] - 1)
                              for axis, gu in zip("xyz", sample["gu"], strict=True)) or any(
                all(other["bounds_mm"][axis + "_min"] <= value <= other["bounds_mm"][axis + "_max"]
                    for axis, value in zip("xyz", point, strict=True)) and
                any(value in (other["bounds_mm"][axis + "_min"], other["bounds_mm"][axis + "_max"])
                    for axis, value in zip("xyz", point, strict=True)) for other in domains.values())
            probe = dict(label=domain["domain_id"] + ":" + sample["label"], point_mm=point,
                expected_node_electrode=True,
                basis=dict(kind="resolved_physical_sample", domain_id=domain["domain_id"],
                           sample_label=sample["label"], sample_kind=sample["kind"],
                           electrode_id=sample["electrode_id"], gu=sample["gu"],
                           world_query_scope="numerical_boundary_observation" if on_boundary else "source_node_location_observation"))
            if sample["kind"] != "ideal_sheet":
                probe["expected_adjacent_metal_cell"] = True
            if not on_boundary:
                probe["expected_instance"] = selected(point)
            probes.append(probe)
    accelerator = geometry["accelerator_projection"]
    if accelerator.get("numerical_port_width_mm", 0) > 0 and accelerator.get("numerical_port_height_mm", 0) > 0:
        point = [accelerator["negative_x_face_mm"] + accelerator["shield_wall_mm"] / 2,
                 accelerator["port_center_y_mm"], accelerator["port_center_z_mm"]]
        probes.append(dict(label="provider_side_opening_center", point_mm=point,
            expected_instance=selected(point), basis=dict(kind="provider_side_opening_center",
                occupancy="observe_only_no_independent_point_in_metal_classifier")))
    if fine:
        anchor = [(fine["bounds_mm"][axis + "_min"] + fine["bounds_mm"][axis + "_max"]) / 2
                  for axis in "xyz"]
        for index, axis in enumerate("xyz"):
            for side, sign in (("min", -1), ("max", 1)):
                edge = fine["bounds_mm"][axis + "_" + side]
                gap = sign * (parent["bounds_mm"][axis + "_" + side] - edge)
                if gap <= 0:
                    continue
                for location, displacement, instance in (
                        ("inside", -sign * fine["cell_mm_xyz"][axis], 5),
                        ("outside", sign * min(parent["cell_mm_xyz"][axis], gap / 2), 3)):
                    point = list(anchor)
                    point[index] = edge + displacement
                    probes.append(dict(label=f"fine_{axis}_{side}_{location}", point_mm=point,
                        expected_instance=instance, basis=dict(kind="declared_numerical_domain_transition",
                            axis=axis, side=side, location=location, boundary_mm=edge,
                            displacement_mm=displacement, occupancy="observe_only")))
    for terminal in terminal_observations or ():
        instance = int(terminal["instance"])
        if instance not in (3, 5) or (instance == 5 and fine is None):
            raise ValueError("terminal neighborhoods require the declared parent or fine Cartesian domain")
        domain = fine if instance == 5 else parent
        center = [terminal[axis + "_mm"] for axis in "xyz"]
        offsets = [("center", [0., 0., 0.])]
        for index, axis in enumerate("xyz"):
            for sign in (-1, 1):
                offset = [0., 0., 0.]
                offset[index] = sign * domain["cell_mm_xyz"][axis]
                offsets.append((axis + ("_minus_cell" if sign < 0 else "_plus_cell"), offset))
        for name, offset in offsets:
            probes.append(dict(label=f"terminal_{terminal['particle_id']}_{name}",
                point_mm=[value + delta for value, delta in zip(center, offset, strict=True)],
                basis=dict(kind="observed_native_terminal_neighborhood", particle_id=terminal["particle_id"],
                    recorded_instance=instance, instrument_time_us=terminal["instrument_time_us"],
                    offset_mm=offset, occupancy="observe_only_no_physical_object_attribution")))
    return probes


def resolve_phase_flight(author_flight: dict, *, phase: str, decision: dict | None = None,
                         requires_rf: bool = True) -> dict[str, Any]:
    """Derive the one actual native control from the frozen author's explicit plan."""
    author = validate_native_flight(author_flight, requires_rf=requires_rf, allow_discovery=True)
    if phase not in {"discovery", "full_instrument"}:
        raise ValueError("native flight phase must be discovery or full_instrument")
    if author["pulse"]["mode"] != "discover":
        if phase != "full_instrument" or decision is not None:
            raise ValueError("only an author discovery plan can derive flight phases or a decision")
        return validate_native_flight(author, requires_rf=requires_rf)
    actual = {key: value for key, value in author.items() if key != "pulse"}
    if phase == "discovery":
        if decision is not None:
            raise ValueError("discovery cannot consume a pulse decision")
        actual.update(pulse={"mode": "held_off"}, observation_times_us=list(author["pulse"]["candidate_times_us"]))
    else:
        if (not isinstance(decision, dict) or decision.get("schema_version") != 2
                or decision.get("role") != "single_reflection_actual_occupancy_pulse_decision"
                or decision.get("status") != "success"
                or decision.get("selection_uses_future_terminal_outcome") is not False
                or decision.get("candidate_times_us") != author["pulse"]["candidate_times_us"]
                or decision.get("pulse_width_us") != author["pulse"]["width_us"]):
            raise ValueError("timed discovery successor requires a successful matching actual-occupancy decision")
        time = decision.get("actual_pulse_time_us")
        selection = decision.get("selection", {})
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or time not in author["pulse"]["candidate_times_us"]
                or selection.get("status") != "selected" or selection.get("selected_time_us") != time):
            raise ValueError("pulse decision must select one declared actual candidate")
        actual["pulse"] = {"mode": "timed", "time_us": time, "width_us": author["pulse"]["width_us"]}
    return validate_native_flight(actual, requires_rf=requires_rf)


def _prepare_context(preparation: dict, field_receipt_path: Path,
                          downstream_receipt_record: dict, run: Path, *,
                          snapshot_root: Path, flight: dict, phase: str = "full_instrument",
                          pulse_decision_record: dict | None = None) -> dict[str, Any]:
    """Verify one phase into a shared in-memory case context; never materialize PA bytes.

    The caller must verify an external producer's successful sealed manifest
    projection before supplying downstream_receipt_record, then protect every
    returned pa_guard_record before executing iob_builder_arguments. PA bytes
    are not read here. The explicit flight clock/durations are frozen once;
    outputs remain not Fly-ready until native workbench and flight validation.
    """
    run, snapshot_root = run.absolute(), snapshot_root.absolute()
    config = _read(run / "run_config.json")
    manifest = run / "run_manifest.json"
    if config.get("project") != "instrument_assembly" or (manifest.exists() and _read(manifest).get("status") != "checkpoint"):
        raise ValueError("workbench preparation requires a live instrument_assembly run")
    if preparation.get("schema_version") != 1 or preparation.get("role") != "single_reflection_geometry_preparation":
        raise ValueError("current single-reflection preparation receipt is required")
    if phase not in {"discovery", "full_instrument"}:
        raise ValueError("unknown native workbench phase")
    records = {k: preparation["outputs"][k] for k in
               ("frontend_geometry", "frontend_field_design", "projected_source", "source_provenance")}
    geometry_path = _small_record(records['frontend_geometry'], 'frontend_geometry')
    geometry = _read(geometry_path)
    multipole_ids, oatof_id = native_frontend_instances(geometry['composition_plan'])
    for instance_id in geometry['composition_plan']['scope']['instance_ids']:
        records['instance_design__' + instance_id] = instance_design_record(preparation, instance_id)
    paths = {'frontend_geometry': geometry_path,
             **{key: _small_record(record, key) for key, record in records.items() if key != 'frontend_geometry'}}
    run_root = run.resolve()
    if (any(not path.is_relative_to(run_root) for path in paths.values())
            or not field_receipt_path.resolve().is_relative_to(run_root)):
        raise ValueError("prepared inputs and frontend field receipt must belong to this run")
    multipoles_by_instance = {instance_id: _read(paths['instance_design__' + instance_id]) for instance_id in multipole_ids}
    oatof = _read(paths['instance_design__' + oatof_id])
    design, provenance = (_read(paths[k]) for k in ("frontend_field_design", "source_provenance"))
    decision = None
    if pulse_decision_record is not None:
        decision = _read(_small_record(pulse_decision_record, "actual occupancy pulse decision"))
        decision_inputs = decision.get("input_records", {})
        for key, expected in (("request", preparation["input_records"]["request"]),
                              ("frontend_geometry", records["frontend_geometry"])):
            actual = decision_inputs.get(key)
            if not isinstance(actual, dict) or any(actual.get(k) != expected.get(k) for k in ("path", "bytes", "sha256")):
                raise ValueError(f"pulse decision {key} differs from this frozen preparation")
        collection_path = _small_record(decision_inputs.get("collection", {}), "discovery collection")
        collection = _read(collection_path)
        if collection.get("phase") != "discovery" or collection.get("native_complete") is not True:
            raise ValueError("pulse decision must bind a complete actual discovery collection")
        for key, expected in (("request_record", preparation["input_records"]["request"]),
                              ("geometry_record", records["frontend_geometry"]),
                              ("field_design_record", records["frontend_field_design"]),
                              ("source_record", records["projected_source"])):
            actual = collection.get(key)
            if not isinstance(actual, dict) or any(actual.get(k) != expected.get(k) for k in ("path", "bytes", "sha256")):
                raise ValueError(f"discovery collection {key} differs from this frozen preparation")
        if (collection.get("clock_epoch_id") != provenance["clock_epoch_id"]
                or collection.get("flight") != resolve_phase_flight(flight, phase="discovery", requires_rf=any(
                    point["kind"] == "rf_reference" for point in design["working_points"]))):
            raise ValueError("discovery collection flight or clock differs")
        records["pulse_decision"] = pulse_decision_record
    flight = resolve_phase_flight(flight, phase=phase, decision=decision, requires_rf=any(
        point["kind"] == "rf_reference" for point in design["working_points"]))
    with paths["projected_source"].open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(GLOBAL_COLUMNS):
            raise ValueError("projected source columns differ")
        source = list(reader)
    ids = [int(row["particle_id"]) for row in source]
    restart_source = provenance.get("source_kind") == "recorded_pre_pulse_state"
    expected_ids = (provenance.get("continued_particle_ids") if restart_source
                    else list(range(1, preparation["particle_count"] + 1)))
    if (not isinstance(expected_ids, list) or ids != expected_ids
            or len(source) != provenance["particle_count"]
            or provenance["target_frame_id"] != geometry["native_frame_id"]):
        raise ValueError("projected source IDs/count/frame differ from its frozen source provenance")
    if restart_source and (provenance.get("continued_particle_count") != len(ids)
            or not set(ids) <= set(provenance.get("original_mother_particle_ids", []))):
        raise ValueError("recorded pre-pulse continuation ledger differs from projected source")
    if any(not math.isfinite(float(value)) for row in source for value in row.values()):
        raise ValueError("projected source contains non-finite states")
    fields, dynamic = _frontend_fields(field_receipt_path, design)
    carriers, static, guards = _downstream_fields(
        downstream_receipt_record, instance_design_record(preparation, oatof_id),
        preparation["input_records"].get("downstream_fields_manifest"))
    carriers["accelerator"] = fields["parent"]["carrier_off"]
    if "entrance_refinement" in fields:
        carriers["entrance_refinement"] = fields["entrance_refinement"]["carrier_off"]
    return dict(run=str(run), snapshot_root=str(snapshot_root), phase=phase, records=records,
        multipoles_by_instance=multipoles_by_instance, oatof=oatof, geometry=geometry, design=design, provenance=provenance,
        flight=flight, source=source, fields=fields, dynamic=dynamic, carriers=carriers, static=static,
        guards=guards, field_receipt_path=str(field_receipt_path),
        downstream_receipt_record=downstream_receipt_record, restart_source=restart_source)


def iob_pa_copies(context: dict) -> list[dict]:
    """Project only external IOB slots; published field identities remain unchanged."""
    root = Path(context["run"]).resolve()
    copies = []
    for role, record in context["carriers"].items():
        if not record_path(record).is_relative_to(root):
            copies.append(dict(role=role, source_record=record,
                destination=str(Path(context["run"]) / "simion" / "iob_fields" / Path(record["path"]).name)))
    return copies


def compile_case_controls(context: dict, source: list[dict]) -> tuple[str, dict, list[dict]]:
    """Compile actual Program and instance controls without staging native assets."""
    snapshot_root = Path(context["snapshot_root"])
    ids = [int(row["particle_id"]) for row in source]
    metadata: dict[str, Any] = {}
    program = build_successor_program(context["multipoles_by_instance"], context["design"], context["oatof"],
        frontend_geometry=context["geometry"],
        birth_times_us=[float(r["instrument_time_us"]) for r in source], particle_ids=ids,
        initial_velocities_mm_per_us=[[float(r[f"velocity_{a}_m_s"]) / 1000 for a in "xyz"] for r in source],
        flight=context["flight"], standalone_dynamic_field_bank=context["dynamic"],
        standalone_dynamic_field_paths={row["role"]: dict(
            rf_differential_pa_paths=[context["fields"]["parent" if row["role"] == "accelerator_main" else row["role"]][working_point_member_id(point)]["path"]
                for point in context["design"]["working_points"] if point["kind"] == "rf_reference"],
            **({'pulse_delta_pa_path': context['fields']['parent' if row['role'] == 'accelerator_main' else row['role']]['pulse_delta']['path']}
               if row.get('pulse_delta_pa_basename') else {}))
            for row in context["dynamic"]["dynamic_roles"]},
        downstream_static_fields=context["static"],
        build_metadata=metadata, **{key: (snapshot_root / name).read_text(encoding="utf-8-sig") for key, name in _SOURCES.items()})
    return program, metadata, _instance_rows(context["geometry"], metadata, context["carriers"])


def preview_case_controls(context: dict, source: list[dict], directory: Path) -> dict:
    """Return the exact small controls needed to plan reuse, without IOB staging."""
    program, metadata, rows = compile_case_controls(context, source)
    run = Path(context["run"]).resolve()
    rows = [dict(row) for row in rows]
    for row in rows:
        path = Path(row["path"])
        if path.is_relative_to(run):
            row["path"] = (Path(context["run"]) / path.relative_to(run)).as_posix()
    copies = {copy["role"]: copy for copy in iob_pa_copies(context)}
    for row in rows:
        if row["role"] in copies:
            row["path"] = Path(copies[row["role"]]["destination"]).as_posix()
    response_fields = []
    for domain, fields in context["fields"].items():
        role = "accelerator" if domain == "parent" else domain
        grid = next(row["grid"] for row in rows if row["role"] == role)
        for kind, record in fields.items():
            if kind != "carrier_off":
                response_fields.append(dict(domain=domain, kind=kind, path=Path(record["path"]).as_posix(), grid=grid))
    count = len(rows)
    seed_names = [f"{count}_instance_seed.iob", *(f"iob_seed_placeholder_{index:02d}.pa0" for index in range(1, count + 1))]
    seed = directory / "iob_seed"
    iob = directory / "instrument.iob"
    cache = context.setdefault("_continuation_seed_records", {})
    seed_paths = [Path(context["snapshot_root"]) / "common/simion/assets/iob_instance_seeds" / name for name in seed_names]
    seed_records = []
    for path in seed_paths:
        record = cache.get(path)
        if record is None:
            record = file_record(path)
            cache[path] = record
        seed_records.append(record)
    probes = native_priority_occupancy_probes(context["geometry"], context["design"])
    checked = sum(any(key in row for key in ("expected_instance", "expected_electrode", "expected_node_electrode"))
                  for row in probes)
    return dict(program=program, particles=render_restart_fly2(source), build_metadata=metadata, instance_rows=rows,
        native_priority_occupancy_expected_counts=dict(checked_points=checked, observation_only_points=len(probes) - checked),
        build_spec="return " + _lua_value(dict(schema_version=1, role="single_reflection_iob_build", instances=rows,
            response_fields=response_fields,
            native_priority_occupancy_probes=probes,
            seed_iob=(seed / seed_names[0]).as_posix(), output_iob=iob.as_posix())) + "\n",
        builder_path=str(Path(context["snapshot_root"]) / "integrations/workflows/single_reflection_flight/build_iob.lua"),
        seed_paths=[str(path) for path in seed_paths], seed_records=seed_records)


def preview_batches(run: Path, phase: str, plan: dict, *, context: dict) -> dict:
    """Compile all small batch controls before deciding which IOBs must exist."""
    if plan.get("role") == "simion_repository_dispatch_plan":
        plan = batch_plan_from_dispatch(plan)
    source = context["source"]
    cases = []
    for index, batch in enumerate(plan["batches"], 1):
        low, high = batch["particle_id_min"], batch["particle_id_max"]
        name = f"batch_{index:04d}__rows_{low:06d}_{high:06d}"
        preview = preview_case_controls(context, source[low - 1:high], run / "simion" / phase / name)
        cases.append(dict(case_id=name, index=index, count=high-low+1, source_row_range=[low, high],
            expected_particle_ids=[int(row["particle_id"]) for row in source[low-1:high]], preview=preview))
    return dict(schema_version=1, role="single_reflection_workbench_preparation", phase=phase,
        particle_count=len(source), source_record=context["records"]["projected_source"], source_transform_applied=False,
        clock_epoch_id=context["provenance"]["clock_epoch_id"], flight=context["flight"], batches=cases,
        iob_pa_copies=iob_pa_copies(context),
        pa_guard_records=[*(record for domain in context["fields"].values() for record in domain.values()), *context["guards"]])


def _materialize_case(context: dict, source: list[dict], directory: Path) -> dict:
    phase, records = context["phase"], dict(context["records"])
    provenance, flight = context["provenance"], context["flight"]
    fields, guards = context["fields"], context["guards"]
    downstream_receipt_record = context["downstream_receipt_record"]
    snapshot_root, field_receipt_path = (Path(context[k]) for k in ("snapshot_root", "field_receipt_path"))
    if directory.exists():
        raise ValueError("refusing to overwrite prepared workbench inputs")
    preview = preview_case_controls(context, source, directory)
    program, metadata, rows = preview["program"], preview["build_metadata"], preview["instance_rows"]
    seed_root = snapshot_root / "common/simion/assets/iob_instance_seeds"
    count = len(rows)
    seed_names = [f"{count}_instance_seed.iob", *(f"iob_seed_placeholder_{i:02d}.pa0" for i in range(1, count + 1))]
    for name in seed_names:
        if not (seed_root / name).is_file():
            raise ValueError(f"frozen public IOB seed resource is missing: {name}")
    builder = snapshot_root / "integrations/workflows/single_reflection_flight/build_iob.lua"
    if not builder.is_file():
        raise ValueError("frozen four/five-slot IOB builder is missing")
    directory.mkdir(parents=True)
    seed = directory / "iob_seed"
    seed.mkdir()
    for name in seed_names:
        shutil.copyfile(seed_root / name, seed / name)
    iob = directory / "instrument.iob"
    iob.with_suffix(".lua").write_text(program, encoding="utf-8", newline="\n")
    iob.with_suffix(".fly2").write_text(render_restart_fly2(source), encoding="utf-8", newline="\n")
    spec_path = directory / "iob_build.lua"
    spec_path.write_text(preview["build_spec"], encoding="utf-8", newline="\n")
    scientific_guards = [*(record for domain in fields.values() for record in domain.values()), *guards]
    copies = iob_pa_copies(context)
    return dict(schema_version=1, role="single_reflection_workbench_preparation", phase=phase, flight=flight, particle_count=len(source),
        source_record=records["projected_source"], source_transform_applied=False,
        clock_epoch_id=provenance["clock_epoch_id"], instance_roles={row["role"]: row["instance_index"] for row in rows},
        build_metadata=metadata, inputs=records, downstream_receipt_record=downstream_receipt_record,
        native_priority_occupancy_expected_counts=preview["native_priority_occupancy_expected_counts"],
        iob_pa_copies=copies,
        iob_pa_guard_records=[*scientific_guards,
            *({**copy["source_record"], "path": copy["destination"]} for copy in copies)],
        field_receipt_record=file_record(field_receipt_path), pa_guard_records=[*(record for domain in fields.values() for record in domain.values()), *guards],
        iob_path=str(iob), iob_builder_arguments=["--nogui", "--noprompt", "lua", str(builder), str(spec_path)],
        iob_verify_arguments=["--nogui", "--noprompt", "lua", str(builder), str(spec_path), "verify"],
        outputs={"program": file_record(iob.with_suffix(".lua")), "particles": file_record(iob.with_suffix(".fly2")),
                 "build_spec": file_record(spec_path)}, seed_records=[file_record(seed / name) for name in seed_names],
        native_execution_performed=False, fly_ready=False,
        pending_validation=["native_IOB_reopen", "native_priority_occupancy_points", "real_full_population_flight_validation"])

def materialize_workbench(preparation: dict, field_receipt_path: Path, downstream_receipt_record: dict,
                          run: Path, *, snapshot_root: Path, flight: dict, phase: str = "full_instrument",
                          pulse_decision_record: dict | None = None) -> dict:
    """Prepare the unflown complete workbench delivery."""
    context = _prepare_context(preparation, field_receipt_path, downstream_receipt_record, run,
        snapshot_root=snapshot_root, flight=flight, phase=phase, pulse_decision_record=pulse_decision_record)
    return _materialize_case(context, context["source"], run/"simion"/phase)



def prepare_dispatch(preparation: dict, field_receipt_path: Path, downstream_receipt_record: dict,
                     run: Path, *, snapshot_root: Path, flight: dict, phase: str,
                     pulse_decision_record: dict | None = None) -> dict:
    """Validate a phase once; shared scheduling operates on source-row positions."""
    context = _prepare_context(preparation, field_receipt_path, downstream_receipt_record, run,
        snapshot_root=snapshot_root, flight=flight, phase=phase, pulse_decision_record=pulse_decision_record)
    source = context.pop("source")
    rf = any(point["kind"] == "rf_reference" for point in context["design"]["working_points"])
    request = dict(solver="SIMION", field_kind="rf" if rf else "electrostatic",
        particle_count=len(source), independent_particles=True,
        trajectory_quality=context["flight"]["trajectory_quality"],
        workload_topology_id="single_reflection_complete_assembly_shared_fields_v1",
        field_loading_policy_id=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
        case_input_sha256=canonical_json_sha256(dict(inputs=context["records"],
            frontend_fields=file_record(field_receipt_path), downstream=downstream_receipt_record,
            flight=context["flight"])))
    if rf:
        request["rf_steps_per_period"] = context["flight"]["rf_steps_per_period"]
    request_path = run/"inputs"/f"{phase}_dispatch_request.json"
    with request_path.open("x", encoding="utf-8") as stream:
        json.dump(request, stream, allow_nan=False)
    return dict(dispatch_request_path=str(request_path), particle_count=len(source),
        iob_pa_copies=iob_pa_copies(context),
        pa_guard_records=[*(r for domain in context["fields"].values() for r in domain.values()), *context["guards"]])


def materialize_batches(run: Path, phase: str, plan: dict, *, context: dict,
                        materialize_case_ids: set[str] | None = None) -> dict:
    """Slice original rows, optionally staging only common-plan replay batches."""
    source = context["source"]
    if plan.get("role") == "simion_repository_dispatch_plan":
        plan = batch_plan_from_dispatch(plan)
    if (plan.get("role") != "simion_single_wave_particle_batch_plan" or plan.get("particle_count") != len(source)
            or plan.get("batch_count") != len(plan["batches"])):
        raise ValueError("public batch plan differs from the frozen execution cohort")
    seen, cases = [], []
    for index, batch in enumerate(plan["batches"], 1):
        low, high = batch["particle_id_min"], batch["particle_id_max"]
        if (any(type(v) is not int for v in (low, high, batch["count"], batch["index"]))
                or not 1 <= low <= high <= len(source) or batch["count"] != high-low+1 or batch["index"] != index):
            raise ValueError("invalid source-row batch interval")
        seen.extend(range(low, high+1))
        name = f"batch_{index:04d}__rows_{low:06d}_{high:06d}"
        if materialize_case_ids is not None and name not in materialize_case_ids:
            continue
        directory = run/"simion"/phase/name
        receipt_path = directory/"workbench.json"
        ids = [int(row["particle_id"]) for row in source[low-1:high]]
        if receipt_path.exists():
            case = _read(receipt_path)
            if case["source_row_range"] != [low, high] or case["expected_particle_ids"] != ids:
                raise ValueError("observed first batch changed during resource replanning")
        else:
            case = _materialize_case(context, source[low-1:high], directory)
            case.update(case_id=name, index=index, count=high-low+1, expected_particle_ids=ids,
                source_row_range=[low, high], receipt_path=str(receipt_path), merge_offset=0, simion_particle_id_offset=0,
                working_directory=str(directory), environment={},
                fly_arguments=["--nogui", "--noprompt", "fly", "instrument.iob"],
                stdout=str(run/"results"/f"{phase}.{name}.stdout.log"),
                stderr=str(run/"results"/f"{phase}.{name}.stderr.log"))
            with receipt_path.open("x", encoding="utf-8") as stream:
                json.dump(case, stream, allow_nan=False)
        cases.append(case)
    coverage = plan.get("coverage", "complete_population")
    if seen != sorted(set(seen)) or (coverage == "complete_population" and seen != list(range(1,len(source)+1))):
        raise ValueError("batch plan duplicates or omits frozen source rows")
    if coverage not in {"complete_population", "initial_formal_batch_only"}:
        raise ValueError("unsupported source-row coverage")
    if materialize_case_ids is not None and not cases:
        instance_roles = {}
    else:
        instance_roles = cases[0]["instance_roles"]
    return dict(schema_version=1, role="single_reflection_workbench_preparation", phase=phase,
        particle_count=len(source), source_record=context["records"]["projected_source"],
        source_transform_applied=False, clock_epoch_id=context["provenance"]["clock_epoch_id"],
        inputs=context["records"], flight=context["flight"], batches=cases, coverage=coverage,
        pending_particle_ids=[int(source[i-1]["particle_id"]) for i in range(1,len(source)+1) if i not in seen],
        gui_case=None, outputs={}, fly_ready=False, native_execution_performed=False,
        instance_roles=instance_roles, pending_validation=["native_priority_occupancy_points"],
        iob_pa_copies=iob_pa_copies(context) if cases else [],
        pa_guard_records=[*(r for domain in context["fields"].values() for r in domain.values()), *context["guards"]])


def main() -> int:
    """Internal stage boundary for the single public PowerShell entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("prepare-dispatch", "materialize-batches", "materialize-continuation"))
    parser.add_argument("--batch-plan", type=Path)
    parser.add_argument("--preparation", type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument("--field-receipt", type=Path)
    parser.add_argument("--downstream-publication", type=Path)
    parser.add_argument("--check-flight", action="store_true")
    parser.add_argument("--verify-controls", type=Path)
    parser.add_argument("--phase", choices=("discovery", "full_instrument"), default="full_instrument")
    parser.add_argument("--pulse-decision-record", type=json.loads)
    parser.add_argument("--continuation-phase", choices=("discovery", "baseline", "default_replay"))
    args = parser.parse_args()
    if args.verify_controls is not None:
        workbench = _read(args.verify_controls)
        cases = workbench.get("batches", [workbench])
        result = dict(prepared_controls_unchanged=True)
        for case in cases:
            iob_record = case["outputs"].get("iob")
            if iob_record is not None and record_path(iob_record) != Path(case["iob_path"]).resolve():
                raise ValueError("saved IOB record differs from the workbench path")
            for name, record in case["outputs"].items():
                _small_record(record, name)
            if iob_record is None:
                iob_record = file_record(Path(case["iob_path"]))
            result["iob_record"] = iob_record
        print(json.dumps(result))
        return 0
    preparation = _read(args.preparation)
    request_path = _small_record(preparation["input_records"]["request"], "frozen scientific request")
    flight = _read(request_path).get("flight")
    if args.check_flight:
        design_path = _small_record(preparation["outputs"]["frontend_field_design"], "frozen field design")
        design = _read(design_path)
        flight = validate_native_flight(flight, requires_rf=any(
            point["kind"] == "rf_reference" for point in design["working_points"]), allow_discovery=True)
        print(json.dumps({"flight_validated": True, "requires_discovery": flight["pulse"]["mode"] == "discover"}))
        return 0
    if args.field_receipt is None or args.downstream_publication is None:
        parser.error("materialization requires field-receipt and downstream-publication")
    publication = _read(args.downstream_publication)
    if args.action == "materialize-continuation":
        if args.continuation_phase is None:
            parser.error("materialize-continuation requires --continuation-phase")
        from integrations.workflows.single_reflection_flight.continuation import (
            _parent, _phase_paths, freeze_phase_inputs, materialize_phase_continuation,
            prepare_phase_continuation, _published_case,
        )
        context = _prepare_context(preparation, args.field_receipt, publication["receipt_record"], args.run,
            snapshot_root=args.snapshot_root, flight=flight, phase=args.phase, pulse_decision_record=args.pulse_decision_record)
        parent, _, records, _ = _parent(preparation)
        dispatch_path, _, _ = _phase_paths(parent, args.continuation_phase)
        if dispatch_path.resolve() not in records:
            # Reject a partial or unpublished pair; absence alone means this
            # phase was never started and follows the normal dispatch path.
            freeze_phase_inputs(preparation, args.run, args.continuation_phase)
            print(json.dumps(None))
            return 0
        dispatch = _read(dispatch_path)
        preview = preview_batches(args.run, args.phase, dispatch, context=context)
        if args.continuation_phase == "default_replay":
            planned = prepare_phase_continuation(preparation, preview, args.run, args.continuation_phase)
            result = _read(args.run / "results/single_reflection/workbench_preparation.json")
            result["replay_continuation"] = planned
            parent_workbench = _read(record_path(planned["frozen_inputs"]["workbench_record"]))
            parents = {case["case_id"]: _published_case(case) for case in parent_workbench["batches"]}
            for case, unit in zip(result["batches"], planned["plan"]["units"], strict=True):
                if case["case_id"] != unit["key"]:
                    raise ValueError("default replay case order differs from fixed dispatch")
                if unit["action"] == "reuse":
                    case["replay_continuation_source"] = unit
                    case["replay_stdout"] = parents[case["case_id"]]["replay_stdout"]
                    case["replay_stderr"] = parents[case["case_id"]].get("replay_stderr", "")
        else:
            result = materialize_phase_continuation(preparation, preview, context, args.run, args.continuation_phase)
        print(json.dumps(result, allow_nan=False))
        return 0
    if args.action == "materialize-batches":
        context = _prepare_context(preparation, args.field_receipt, publication["receipt_record"], args.run,
            snapshot_root=args.snapshot_root, flight=flight, phase=args.phase, pulse_decision_record=args.pulse_decision_record)
        print(json.dumps(materialize_batches(args.run,args.phase,_read(args.batch_plan),context=context),allow_nan=False))
        return 0
    builder = prepare_dispatch if args.action == "prepare-dispatch" else materialize_workbench
    result = builder(preparation, args.field_receipt, publication["receipt_record"],
                                  args.run, snapshot_root=args.snapshot_root, flight=flight, phase=args.phase,
                                  pulse_decision_record=args.pulse_decision_record)
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
