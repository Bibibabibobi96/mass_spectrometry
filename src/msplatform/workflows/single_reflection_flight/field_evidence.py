"""Read frozen field controls and declared observation context for SFI phases."""
from __future__ import annotations
import json
import re
import stat
from pathlib import Path
from functools import partial
from msplatform.io.manifest_records import record_path,verify_record as _verify_record
from msplatform.execution.retention import classify_file
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key,validate_pa_family_cache_generation
from msplatform.backends.simion.field_identity import frontend_field_identity,working_point_member_id,_member_projection
from msplatform.backends.simion.tracking_program import (validate_native_field_observation,
 STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,STANDALONE_DYNAMIC_FIELD_BANK_ROLE,STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION)
from msplatform.backends.simion.frontend import native_frontend_instances
verify_record=partial(_verify_record,retention_classifier=classify_file)
def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _field_observation(preparation: dict, source: list[dict], provenance: dict,
                       geometry: dict, fields: dict, flight: dict, phase: str) -> dict | None:
    """Load only the opt-in, already frozen validation input; never modify controls."""
    record = preparation['input_records'].get('validation_contract')
    if record is None:
        return None
    document = _read(_small_record(record,'native field observation validation contract'))
    if 'native_field_observation' not in document:
        return None
    request = _read(_small_record(preparation['input_records']['request'],'native field observation request'))
    if type(request.get('schema_version')) is not int or request['schema_version'] != 10:
        raise ValueError('native field observation is an explicit request10 validation capability')
    instances,_ = native_frontend_instances(geometry['composition_plan'])
    ids = [int(row['particle_id']) for row in source]
    spec = validate_native_field_observation(document['native_field_observation'],particle_ids=ids,
        source_instances=instances,domain_ids=list(geometry['numerical_domains']),
        clock_epoch_id=provenance['clock_epoch_id'],flight=flight)
    if spec['source_instance_id'] != request['source']['instance_id'] or spec['source_instance_id'] != provenance['source_instance_id']:
        raise ValueError('native field observation requires the actual frozen RF particle-source instance')
    records = dict(validation_contract=record,request=preparation['input_records']['request'],
        source=preparation['outputs']['projected_source'],geometry=preparation['outputs']['frontend_geometry'],
        field_design=preparation['outputs']['frontend_field_design'])
    return dict(specification=spec,evidence_context=dict(phase=phase,clock_epoch_id=provenance['clock_epoch_id'],
        mother_particle_ids=ids,input_records=records,field_records=fields,
        provider_inputs=geometry['backend_electrode_bindings']['provider_inputs']))


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


def validate_frozen_generation_metadata(plan: dict, generation: Path) -> dict:
    """Use common metadata validation; never hash a published PA here."""
    manifest = validate_pa_family_cache_generation(generation, expected_cache_key=plan['cache_key'],
        expected_filenames=plan['filenames'], verify_payload=False)
    if (generation.resolve().name != manifest['generation_sha256'] or generation.parent.name != 'generations'
            or generation.parent.parent.name != plan['cache_key'] or manifest['identity'] != plan['identity']):
        raise ValueError('frozen frontend field source generation identity differs')
    inventory = {row['name']: row for row in manifest['files']}
    for expected in plan['frozen_field_source']['working_points']:
        actual = inventory.get(Path(expected['path']).name)
        if (actual is None or actual['bytes'] != expected['bytes']
                or actual['sha256'].upper() != expected['sha256'].upper()):
            raise ValueError('frozen frontend field source member differs')
    return manifest
