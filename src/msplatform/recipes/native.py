"""Resolve native study recipes from explicit immutable input snapshots."""
from __future__ import annotations

import base64
import copy
from decimal import Decimal
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
from typing import Any, Mapping

from msplatform import assembly, components
from msplatform.contracts.machine_contracts import validate_schema
from msplatform.contracts.species import validate_species
from msplatform.io.file_identity import canonical_json_sha256
from msplatform.particle_release.release import validate_release_spec
from msplatform.physics import CONSTANTS, GasEnvironment


def _keys(value: Any, required: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"{name} requires exactly {sorted(required)}")


def _snapshot(payload: bytes) -> dict:
    return {"sha256": hashlib.sha256(payload).hexdigest().upper(),
            "bytes_base64": base64.b64encode(payload).decode("ascii")}


def _decode(snapshot: dict) -> bytes:
    _keys(snapshot, {"sha256", "bytes_base64"}, "snapshot")
    try:
        payload = base64.b64decode(snapshot["bytes_base64"], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid snapshot encoding") from error
    if _snapshot(payload) != snapshot:
        raise ValueError("snapshot digest mismatch")
    return payload


def _json(payload: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    value = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("study resource must be a JSON object")
    return value


def _relative_file_record(record: Any, name: str) -> None:
    _keys(record, {"path", "bytes", "sha256"}, name)
    path, size, digest = record["path"], record["bytes"], record["sha256"]
    if (not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
            or type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in digest)):
        raise ValueError(name + " requires a relative path, byte count and SHA-256")


def _positive(value: Any, name: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _tracing_numerics(value: dict, tracer: str) -> None:
    _keys(value, {"end_policy", tracer} | ({"birth_validation"} if tracer == "comsol" else set()), "tracing numerics")
    policy = value["end_policy"]
    if not isinstance(policy, dict) or set(policy) not in ({"maximum_particle_age_us"}, {"absolute_instrument_end_us"}):
        raise ValueError("tracing end_policy must select one explicit time horizon")
    _positive(next(iter(policy.values())), "tracing end time")
    native = value[tracer]
    if tracer == "simion":
        required = {"maximum_step_us", "trajectory_quality"}
        if not isinstance(native, dict) or not required <= native.keys() or native.keys() - required - {"rf_steps_per_period", "grouped", "random_seed"}:
            raise ValueError("SIMION tracing needs explicit step and quality")
        _positive(native["maximum_step_us"], "maximum_step_us")
        if type(native["trajectory_quality"]) is not int or not -500 <= native["trajectory_quality"] <= 500:
            raise ValueError("SIMION trajectory_quality must be an integer from -500 to 500")
        if "rf_steps_per_period" in native and (type(native["rf_steps_per_period"]) is not int or native["rf_steps_per_period"] <= 0):
            raise ValueError("rf_steps_per_period must be a positive integer")
        if "random_seed" in native and (type(native["random_seed"]) is not int or native["random_seed"] < 0):
            raise ValueError("random_seed must be an explicit nonnegative integer")
        if "grouped" in native and (type(native["grouped"]) is not int or native["grouped"] < 0):
            raise ValueError("grouped must be an explicit nonnegative integer")
    else:
        _keys(native, {"maximum_step_us", "relative_tolerance", "absolute_tolerance"}, "COMSOL tracing numerics")
        for key, item in native.items():
            _positive(item, key)
        if native["relative_tolerance"] >= 1:
            raise ValueError("COMSOL relative_tolerance must be less than one")
        _keys(value["birth_validation"], {"position_atol_m", "velocity_atol_m_s"}, "native birth validation")
        for key, item in value["birth_validation"].items():
            _positive(item, key)


def _study(data: dict, tracer: str) -> None:
    keys = {"schema_version", "name", "component_requests", "recipe", "drive", "physics", "release",
            "numerics", "cad_export", "claim_limit", "model_input_sources"}
    if type(data.get("schema_version")) is not int or data["schema_version"] not in (1, 2):
        raise ValueError("unsupported study version")
    if data["schema_version"] == 2:
        keys.add("local_scope")
    _keys(data, keys, "study")
    if data["schema_version"] == 2 and not isinstance(data["local_scope"], dict):
        raise ValueError("study version 2 requires an explicit local scope")
    for name in ("component_requests", "recipe", "drive", "physics", "release", "numerics", "cad_export", "model_input_sources"):
        if not isinstance(data[name], dict) or not data[name]:
            raise ValueError(f"study {name} must be a nonempty object")
    if not isinstance(data["claim_limit"], str) or not data["claim_limit"]:
        raise ValueError("study must state its existing claim limit")
    if not isinstance(data["name"], str) or not data["name"]:
        raise ValueError("study must have an explicit name")
    _keys(data["numerics"], {"geometry", "fields", "tracing"}, "study numerics")
    if not all(isinstance(data["numerics"][key], dict) and data["numerics"][key] for key in ("geometry", "fields")):
        raise ValueError("geometry and field numerical settings are required")
    _tracing_numerics(data["numerics"]["tracing"], tracer)
    for key in ("clock", "clock_authority"):
        if not isinstance(data["drive"].get(key), dict) or not data["drive"][key]:
            raise ValueError(f"study drive requires {key}")
    pulse = data["drive"].get("pulse")
    if pulse is not None and (not isinstance(pulse, dict) or pulse.get("mode") not in {"timed", "held_off", "discover"}):
        raise ValueError("unsupported study pulse mode")
    field_reference_drive(data["drive"])
    phase = data["drive"]["clock"].get("phase_reference_instrument_time_us")
    if type(phase) not in (int, float) or not math.isfinite(phase):
        raise ValueError("study drive needs a finite experiment clock reference")
    required_physics = {"field_model", "boundary_policy"}
    if pulse is not None:
        required_physics.add("pulse_voltage_policy_id")
    if not required_physics <= data["physics"].keys():
        raise ValueError("study physics is missing its explicit field or drive policy")
    if any(not isinstance(data["physics"][key], str) or not data["physics"][key] for key in required_physics):
        raise ValueError("study physics policies must be explicit strings")
    if not {"representation", "write_pcurves", "precision_mode"} <= data["cad_export"].keys():
        raise ValueError("study CAD export settings are incomplete")
    requests = release_requests(data["release"])
    if (("oa_focus_campaign" in data["model_input_sources"])
            != (len(requests) == 1 and requests[0].get("role") == "oa_focus_campaign_birth_request")):
        raise ValueError("OA focus campaign and its sole birth request must be selected together")
    for release in requests:
        _validate_birth_request(release)
        if release["role"] == "oa_focus_campaign_birth_request":
            if tracer != "simion" or "oa_focus_campaign" not in data["model_input_sources"] or len(requests) != 1:
                raise ValueError("OA focus birth requires its one frozen SIMION campaign")
            continue
        if (release["species"] if release["role"] == "canonical_recorded_birth_request" else release["release_spec"]["species"])["species_kind"] == "electron":
            raise ValueError(f"{tracer} native electron tracing is not yet validated")
    if tracer != "simion" and any(release["role"] == "canonical_recorded_birth_request" for release in requests):
        raise ValueError("recorded births currently support the SIMION native tracer only")
    if len(requests) > 1 and any(release["role"] == "canonical_recorded_birth_request" for release in requests):
        raise ValueError("recorded birth mass scans are not yet supported")
    species = [release["species_id"] for release in requests]
    if len(species) != len(set(species)):
        raise ValueError("mass scan species IDs must be unique")
    explicit = [pid for release in requests for pid in (release.get("particle_ids") or [])]
    if len(explicit) != len(set(explicit)):
        raise ValueError("mass scan explicit particle IDs must be globally unique")
    canonical_json_sha256(data)


def release_requests(release: dict) -> list[dict]:
    """Read the one canonical source or its explicit species collection."""
    if release.get("role") == "canonical_mass_scan_request":
        _keys(release, {"schema_version", "role", "species_requests"}, "mass scan")
        if type(release["schema_version"]) is not int or release["schema_version"] != 1:
            raise ValueError("unsupported mass scan version")
        requests = release["species_requests"]
        if not isinstance(requests, list) or not requests or any(not isinstance(row, dict) for row in requests):
            raise ValueError("mass scan needs nonempty species requests")
        return requests
    return [release]


def native_species_registry(study: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive the one SI species registry from the frozen release requests."""
    result = []
    for request in release_requests(study["release"]):
        source = request["species"] if request["role"] == "canonical_recorded_birth_request" else request["release_spec"]["species"]
        charge = source["charge_state"]
        result.append(validate_species({"species_id": request["species_id"],
            "species_kind": source["species_kind"],
            "mass_kg": float(source["mass_amu"]) * CONSTANTS["atomic_mass_constant_kg"],
            "charge_state": charge, "charge_c": charge * CONSTANTS["elementary_charge_c"]}))
    return result


def _validate_birth_request(release: dict) -> None:
    if release.get("role") == "oa_focus_campaign_birth_request":
        _keys(release, {"schema_version", "role", "clock", "instrument_origin_us", "species_id",
                        "source_component_id", "relative_weights"}, "OA focus birth")
        if (type(release["schema_version"]) is not int or release["schema_version"] != 1
                or release["source_component_id"] != "oa" or not isinstance(release["species_id"], str)
                or not release["species_id"] or type(release["instrument_origin_us"]) not in (int, float)
                or not math.isfinite(release["instrument_origin_us"])):
            raise ValueError("OA focus birth requires explicit source, species and finite origin")
        return
    if release.get("role") == "canonical_recorded_birth_request":
        required = {"schema_version", "role", "source_record", "clock", "instrument_origin_us", "species_id",
                    "species", "source_component_id", "frame_id", "relative_weights", "particle_ids"}
        _keys(release, required, "recorded birth")
        if type(release["schema_version"]) is not int or release["schema_version"] != 1:
            raise ValueError("unsupported recorded birth request version")
        record = release["source_record"]
        _relative_file_record(record, "recorded birth source record")
        _keys(release["species"], {"species_kind", "mass_amu", "charge_state"}, "recorded birth species")
        from msplatform.contracts.species import validate_release_species
        validate_release_species(release["species"])
        if any(not isinstance(release[key], str) or not release[key] for key in ("species_id", "source_component_id", "frame_id")):
            raise ValueError("recorded birth identities must be explicit")
        ids = release["particle_ids"]
        if not isinstance(ids, list) or not ids or any(type(pid) is not int or pid <= 0 for pid in ids) or len(set(ids)) != len(ids):
            raise ValueError("recorded birth IDs must uniquely identify the complete mother")
        weights = release["relative_weights"]
        if weights is not None and (not isinstance(weights, dict) or set(weights) != {str(pid) for pid in ids}
                                    or any(type(w) not in (int, float) or not math.isfinite(w) or w <= 0 for w in weights.values())):
            raise ValueError("recorded birth weights must cover the complete mother")
        if type(release["instrument_origin_us"]) not in (int, float) or not math.isfinite(release["instrument_origin_us"]):
            raise ValueError("recorded birth origin must be finite")
        return
    required = {"schema_version", "role", "release_spec", "clock", "instrument_origin_us", "species_id", "source_component_id", "relative_weights"}
    if (not required <= release.keys() or release.keys() - required - {"particle_ids"}
            or type(release["schema_version"]) is not int or release["schema_version"] != 1
            or release["role"] != "canonical_birth_source_request"):
        raise ValueError("study release must be an explicit canonical birth request")
    validate_release_spec(release["release_spec"])
    if not all(isinstance(release[key], str) and release[key] for key in ("species_id", "source_component_id")):
        raise ValueError("study release identities are required")
    origin = release["instrument_origin_us"]
    if type(origin) not in (int, float) or not math.isfinite(origin):
        raise ValueError("study release origin must be finite")
    ids = release.get("particle_ids")
    count = release["release_spec"]["particle_count"]
    if ids is not None and (not isinstance(ids, list) or len(ids) != count
                            or any(type(pid) is not int or pid <= 0 for pid in ids) or len(set(ids)) != count):
        raise ValueError("study release IDs must cover the mother population uniquely")
    weights = release["relative_weights"]
    if weights is not None and (not isinstance(weights, dict)
                                or set(weights) != {str(pid) for pid in (ids if ids is not None else range(1, count + 1))}
                                or any(type(w) not in (int, float) or not math.isfinite(w) or w <= 0 for w in weights.values())):
        raise ValueError("study weights must cover explicit particle IDs with positive values")


from msplatform.contracts.pulse import field_reference_drive

def _resource_snapshots(study: dict, study_path: Path, gas: dict, author_path: Path) -> dict:
    clock = study["drive"].get("clock_authority")
    if clock != {"example_resource": "instrument_clock_authority_v1.json"}:
        raise ValueError("native study requires the supported package clock authority resource")
    root = files("msplatform.examples")
    snapshots = {name: _snapshot(root.joinpath(name).read_bytes()) for name in
                 ("instrument_clock_authority_v1.json", "instrument_epoch_v1.json")}
    provenance = study["model_input_sources"].get("compensation_provenance")
    if provenance is not None:
        _keys(provenance, {"path", "sha256"}, "compensation provenance reference")
        path = provenance["path"]
        digest = provenance["sha256"]
        if (not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in digest)):
            raise ValueError("compensation provenance requires an explicit relative path and SHA-256")
        payload = (study_path.parent / path).read_bytes()
        if hashlib.sha256(payload).hexdigest().upper() != digest.upper():
            raise ValueError("compensation provenance differs from its author identity")
        snapshots["compensation_provenance.json"] = _snapshot(payload)
    focus = study["model_input_sources"].get("oa_focus_campaign")
    if focus is not None:
        _keys(focus, {"path", "sha256"}, "OA focus campaign")
        path = focus["path"]
        if (not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
                or not isinstance(focus["sha256"], str) or len(focus["sha256"]) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in focus["sha256"])):
            raise ValueError("OA focus campaign requires a relative path and SHA-256")
        data = (study_path.parent / path).read_bytes()
        if hashlib.sha256(data).hexdigest().upper() != focus["sha256"].upper():
            raise ValueError("OA focus campaign differs from its author identity")
        snapshots["oa_focus_campaign.json"] = _snapshot(data)
        snapshots["oa_focus_component_contract.json"] = _snapshot(
            files("msplatform.components.orthogonal_accelerator").joinpath("component_contract.json").read_bytes())
    release = study["release"]
    if release.get("role") == "canonical_recorded_birth_request":
        record = release["source_record"]
        payload = (study_path.parent / record["path"]).read_bytes()
        if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest().upper() != record["sha256"].upper():
            raise ValueError("recorded birth source bytes differ from the declared identity")
        snapshots["recorded_birth.csv"] = _snapshot(payload)
    if gas.get("status") == "hs1":
        request_path = author_path.parent / gas["path"]
        payload = request_path.read_bytes()
        if hashlib.sha256(payload).hexdigest().upper() != gas["sha256"].upper():
            raise ValueError("HS1 request snapshot differs from its declared identity")
        request = _json(payload)
        _keys(request, {"bath_domain", "outer_domain", "numerics", "environment_instance_id", "environment_record", "vendor_record"}, "HS1 request")
        snapshots["hs1_request.json"] = _snapshot(payload)
        for name, resource_name in (("environment_record", "hs1_environment.json"), ("vendor_record", "hs1_vendor.lua")):
            record = request[name]
            _relative_file_record(record, name)
            data = (request_path.parent / record["path"]).read_bytes()
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest().upper() != str(record["sha256"]).upper():
                raise ValueError(name + " differs from its declared identity")
            snapshots[resource_name] = _snapshot(data)
    if gas.get("status") == "sds":
        from .dual_cone import freeze_sds_resources
        snapshots["sds"] = freeze_sds_resources(author_path.parent / gas["path"], gas["sha256"])
    return snapshots


def _validate_resources(study: dict, resources: dict, gas: dict) -> None:
    required = {"instrument_clock_authority_v1.json", "instrument_epoch_v1.json"}
    if study["release"].get("role") == "canonical_recorded_birth_request":
        required.add("recorded_birth.csv")
        payload = _decode(resources.get("recorded_birth.csv", {}))
        record = study["release"]["source_record"]
        if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest().upper() != record["sha256"].upper():
            raise ValueError("frozen recorded birth differs from source identity")
    provenance = study["model_input_sources"].get("compensation_provenance")
    if provenance is not None:
        required.add("compensation_provenance.json")
        _keys(provenance, {"path", "sha256"}, "compensation provenance reference")
        payload = _decode(resources.get("compensation_provenance.json", {}))
        if hashlib.sha256(payload).hexdigest().upper() != provenance["sha256"].upper():
            raise ValueError("frozen compensation provenance differs from its author identity")
        value = _json(payload)
        _keys(value, {"schema_version", "role", "original_recipe_id", "original_resolved_recipe", "original_model_identity_sha256",
                      "axis_samples_reference", "original_field_reference", "fit", "instance_id",
                      "resulting_drive_sha256"}, "compensation provenance")
        if (type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["role"] != "reflectron_compensation_provenance"
                or not isinstance(value["resulting_drive_sha256"], str)
                or value["resulting_drive_sha256"].upper() != canonical_json_sha256(study["drive"]).upper()
                or not isinstance(value["instance_id"], str) or not value["instance_id"]
                or not isinstance(value["fit"], dict)):
            raise ValueError("compensation provenance differs from the frozen study drive")
    focus = study["model_input_sources"].get("oa_focus_campaign")
    if focus is not None:
        _keys(focus, {"path", "sha256"}, "OA focus campaign")
        required.update({"oa_focus_campaign.json", "oa_focus_component_contract.json"})
        campaign = _decode(resources.get("oa_focus_campaign.json", {}))
        contract = _decode(resources.get("oa_focus_component_contract.json", {}))
        if (hashlib.sha256(campaign).hexdigest().upper() != str(focus["sha256"]).upper()
                or contract != files("msplatform.components.orthogonal_accelerator").joinpath("component_contract.json").read_bytes()):
            raise ValueError("OA focus frozen campaign or component contract differs")
    if gas.get("status") == "hs1":
        required.update({"hs1_request.json", "hs1_environment.json", "hs1_vendor.lua"})
        request_bytes = _decode(resources.get("hs1_request.json", {}))
        if hashlib.sha256(request_bytes).hexdigest().upper() != gas["sha256"].upper():
            raise ValueError("frozen HS1 request differs from author identity")
        request = _json(request_bytes)
        _keys(request, {"bath_domain", "outer_domain", "numerics", "environment_instance_id", "environment_record", "vendor_record"}, "HS1 request")
        for name, resource_name in (("environment_record", "hs1_environment.json"), ("vendor_record", "hs1_vendor.lua")):
            record = request[name]
            _relative_file_record(record, name)
            data = _decode(resources.get(resource_name, {}))
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest().upper() != str(record["sha256"]).upper():
                raise ValueError("frozen " + name + " differs from source identity")
    if gas.get("status") == "sds":
        from .dual_cone import validate_sds_resources
        required.add("sds")
        validate_sds_resources(resources.get("sds", {}), gas["sha256"])
    _keys(resources, required, "resources")
    if study["drive"].get("clock_authority") != {"example_resource": "instrument_clock_authority_v1.json"}:
        raise ValueError("unsupported clock authority reference")
    authority = _json(_decode(resources["instrument_clock_authority_v1.json"]))
    epoch = _json(_decode(resources["instrument_epoch_v1.json"]))
    validate_schema(authority, "canonical_clock_authority.schema.json")
    identity = authority.get("authority", {})
    if (authority.get("role") != "canonical_clock_authority" or identity.get("path") != "instrument_epoch_v1.json"
            or identity.get("sha256") != resources["instrument_epoch_v1.json"]["sha256"]
            or identity.get("field") != "instrument_time_us" or "instrument_time_us" not in epoch
            or any(release.get("clock", {}).get("authority_sha256") != identity.get("sha256")
                   or release.get("clock", {}).get("clock_epoch_id") != authority.get("clock_epoch_id")
                   for release in release_requests(study["release"]))):
        raise ValueError("study clock and frozen authority/epoch do not agree")


def _sequence(recipe: dict, resolved: dict) -> list[str]:
    instances = recipe["instances"]
    ids = [row["instance_id"] for row in instances]
    if not ids or len(set(ids)) != len(ids) or set(ids) != set(resolved):
        raise ValueError("assembly instances must be unique and match component requests")
    edges = [(edge["upstream"]["instance_id"], edge["downstream"]["instance_id"])
             for edge in recipe["connections"]]
    edges += [(edge["contained_instance_id"], edge["container_instance_id"])
              for edge in recipe.get("containments", [])]
    if len(set(edges)) != len(edges):
        raise ValueError("duplicate assembly relation")
    index = {name: position for position, name in enumerate(ids)}
    graph = {name: set() for name in ids}
    for left, right in edges:
        if left not in index or right not in index or index[left] >= index[right]:
            raise ValueError("assembly relations must follow the declared instance sequence")
        graph[left].add(right)
        graph[right].add(left)
    visited, pending = set(), [ids[0]]
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(graph[current] - visited)
    if len(visited) != len(ids):
        raise ValueError("assembly relation graph is disconnected")
    return ids


def _assembly(study: dict) -> dict:
    from . import assembly_name
    resolved = {key: components.resolve_component(request) for key, request in study["component_requests"].items()}
    order = _sequence(study["recipe"], resolved)
    assembled = assembly.assemble(study["recipe"], resolved, local_scope=study.get("local_scope"))
    physical = {"instances": study["recipe"]["instances"], "connections": study["recipe"]["connections"],
                "containments": study["recipe"].get("containments", []),
                "frame_id": study["recipe"]["assembly_frame_id"], "components": assembled.components_resolved}
    if study.get("local_scope") is not None:
        physical["local_scope"] = assembled.composition_plan["local_scope"]
    return {"name_version": 1, "name": assembly_name([resolved[key].provider_id for key in order if key in assembled.composition_plan["scope"]["instance_ids"]]),
            "assembly_id": canonical_json_sha256(physical), "composition_plan": assembled.composition_plan,
            "components_resolved": assembled.components_resolved, "components_source": assembled.components_source}


def _options(raw: dict, *, resolved: bool = False) -> None:
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 2:
        raise ValueError("unsupported native recipe version")
    if not isinstance(raw["label"], str) or not raw["label"].strip():
        raise ValueError("label must be nonempty")
    if raw["constants_version"] != CONSTANTS["version"]:
        raise ValueError("native constants must explicitly select the supported frozen dataset")
    gas = raw["gas_environment"]
    if gas != {"status": "vacuum"}:
        _keys(gas, {"status", "path", "sha256"}, "gas environment")
        if (gas["status"] not in {"hs1", "sds"} or not isinstance(gas["path"], str) or not gas["path"]
                or Path(gas["path"]).is_absolute() or ".." in Path(gas["path"]).parts
                or not isinstance(gas["sha256"], str) or len(gas["sha256"]) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in gas["sha256"])):
            raise ValueError("gas requires an explicit relative request and SHA-256")
        if raw["particle_tracer"] != "simion":
            raise ValueError("HS1 currently requires the SIMION tracer")
    source = raw["field_source"]
    if not isinstance(source, dict) or set(source) not in ({"kind"}, {"kind", "reference"},
            {"kind", "reference", "collision_reference", "sampling"}):
        raise ValueError("field_source requires kind and an optional explicit field reference")
    if "reference" in source:
        if source["kind"] == "simion_native" and (raw['particle_tracer'] != 'simion'
                or raw['field_assembly_strategy'] not in {'native_domain_composition', 'sampled_joint_field'}):
            raise ValueError('SIMION field references require an explicit supported SIMION field strategy')
        if resolved:
            from .native_assets import validate_collision_reference, validate_field_reference
            (validate_collision_reference if source['kind'] == 'simion_native' else validate_field_reference)(source["reference"])
        else:
            _keys(source["reference"], {"path", "sha256", "product_id"}, "field reference")
    if "collision_reference" in source:
        if raw["particle_tracer"] != "simion" or raw["field_assembly_strategy"] != "sampled_joint_field":
            raise ValueError("collision reference requires the COMSOL-to-SIMION sampled strategy")
        if resolved:
            from .native_assets import validate_collision_reference, normalize_sampling
            validate_collision_reference(source["collision_reference"])
            if normalize_sampling(source["sampling"]) != source["sampling"]:
                raise ValueError("resolved sampling differs from its normalized declaration")
        else:
            _keys(source["collision_reference"], {"path", "sha256", "product_id"}, "collision reference")
    if raw["field_source"]["kind"] not in {"simion_native", "comsol_native"}:
        raise ValueError("unsupported native field source declaration")
    if raw["particle_tracer"] not in {"simion", "comsol"}:
        raise ValueError("unsupported native tracer declaration")
    if (raw["field_assembly_strategy"] not in {"native_domain_composition", "joint_solve", "sampled_joint_field"}
            or raw["particle_field_coupling"] != "external_given_field"):
        raise ValueError("unsupported field assembly or coupling declaration")
    if gas.get("status") == "sds" and (raw["field_source"] != {"kind": "simion_native"}
            or raw["particle_tracer"] != "simion"
            or raw["field_assembly_strategy"] != "native_domain_composition"):
        raise ValueError("SDS currently requires its own SIMION native field producer")
    recording = raw["recording"]
    if isinstance(recording, dict) and recording.get("mode") == "actual_callback_samples":
        _keys(recording, {"mode", "sample_interval_us", "end_time_us"}, "callback recording")
        if gas.get("status") != "sds" or raw["particle_tracer"] != "simion":
            raise ValueError("actual callback recording requires SIMION SDS")
        for name in ("sample_interval_us", "end_time_us"):
            value = recording[name]
            if type(value) not in (int, float, Decimal) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be finite and positive")
        return
    if gas.get("status") == "sds":
        raise ValueError("SDS requires explicit actual callback recording")
    if (not isinstance(recording, dict) or not {"mode", "observation_times_us"} <= recording.keys()
            or recording.keys() - {"mode", "observation_times_us", "plane_observations", "field_intervention", "field_interventions", "oa_focus_field_modes"}
            or ("plane_observations" in recording and not isinstance(recording["plane_observations"], list))):
        raise ValueError("recording requires explicit observation times and optional plane observations")
    if "oa_focus_field_modes" in recording:
        modes = recording["oa_focus_field_modes"]
        if (not isinstance(modes, list) or len(modes) != 4 or any(not isinstance(mode, str) for mode in modes)
                or set(modes) != {"native", "zone1_ideal", "zone2_ideal", "full_ideal"}
                or "field_intervention" in recording or "field_interventions" in recording
                or raw["particle_tracer"] != "simion" or gas.get("status") != "vacuum"):
            raise ValueError("OA focus contrast requires its four distinct explicit field modes in SIMION vacuum")
    if "field_intervention" in recording and "field_interventions" in recording:
        raise ValueError("choose one field intervention or a case collection")
    if "field_intervention" in recording or "field_interventions" in recording:
        from msplatform.contracts.field_intervention import _case
        cases = recording.get("field_interventions", [recording.get("field_intervention")])
        if not isinstance(cases, list) or not cases:
            raise ValueError("field intervention collection must be a nonempty list")
        ids = []
        for case in cases:
            _keys(case, {"id", "selector"}, "field intervention")
            ids.append(_case(case)[0])
        if len(ids) != len(set(ids)):
            raise ValueError("field intervention case IDs must be unique")
        if raw["particle_tracer"] != "simion" or raw["gas_environment"]["status"] != "vacuum":
            raise ValueError("field intervention requires the SIMION vacuum tracer")
    times = recording["observation_times_us"]
    if (raw["recording"]["mode"] != "observation_times" or not isinstance(times, list) or not times
            or any(type(t) not in (int, float, Decimal) or not math.isfinite(t) for t in times)
            or any(float(a) >= float(b) for a, b in zip(times, times[1:]))):
        raise ValueError("recording requires finite strictly increasing instrument observation times in us")


def _resolved_hs1_gas(study: dict, resources: dict) -> dict:
    """Resolve the single selected IP's authored environment through its authority."""
    from msplatform.contracts.ip_schedule import resolve_ip_schedule_authorities
    from msplatform.components.ion_processor.gas_regions import resolve_ip_continuous_environment
    from msplatform.contracts.gas import BoxDomain
    request = _json(_decode(resources["hs1_request.json"]))
    instance = request["environment_instance_id"]
    if (not isinstance(instance, str) or instance not in study["component_requests"]
            or components.resolve_component(study["component_requests"][instance]).provider_id != "ion_processor"):
        raise ValueError("HS1 environment must bind its selected IP instance")
    schedule = resolve_ip_schedule_authorities(study["drive"], {instance})[instance]
    def domain(name):
        bounds = request[name]
        _keys(bounds, {"minimum_mm", "maximum_mm", "lower_closed", "upper_closed"}, "HS1 " + name)
        return BoxDomain(tuple(bounds["minimum_mm"]), tuple(bounds["maximum_mm"]),
                         tuple(bounds["lower_closed"]), tuple(bounds["upper_closed"]))
    author = _json(_decode(resources["hs1_environment.json"]))
    return resolve_ip_continuous_environment(author, schedule["baseline"],
                                             bath_domain=domain("bath_domain"),
                                             outer_domain=domain("outer_domain")).to_dict()


def _build(raw: dict, study_snapshot: dict, resources: dict) -> dict:
    _options(raw, resolved=True)
    document = _json(_decode(study_snapshot))
    _study(document, raw["particle_tracer"])
    if ("oa_focus_field_modes" in raw["recording"]
            and document["release"].get("role") != "oa_focus_campaign_birth_request"):
        raise ValueError("OA focus field modes require the unique original focus campaign birth")
    if (raw["gas_environment"]["status"] != "sds" and raw["particle_tracer"] == "simion"
            and "random_seed" in document["numerics"]["tracing"]["simion"]):
        raise ValueError("random_seed is currently supported only by SDS tracing")
    _validate_resources(document, resources, raw["gas_environment"])
    if document["release"].get("role") == "oa_focus_campaign_birth_request":
        campaign = _json(_decode(resources["oa_focus_campaign.json"]))
        source = document["release"]
        document["release"] = {**source, "role": "canonical_birth_source_request",
                               "release_spec": copy.deepcopy(campaign["release_spec"])}
        _validate_birth_request(document["release"])
        if document["release"]["release_spec"]["species"]["species_kind"] == "electron":
            raise ValueError("SIMION native electron tracing is not yet validated")
    compiled = _assembly(document)
    result = {key: copy.deepcopy(raw[key]) for key in ("schema_version", "label", "field_source", "particle_tracer", "field_assembly_strategy", "particle_field_coupling", "recording")}
    if raw["gas_environment"]["status"] == "vacuum":
        gas_data = GasEnvironment("vacuum").to_dict()
    elif raw["gas_environment"]["status"] == "hs1":
        gas_data = _resolved_hs1_gas(document, resources)
    else:
        from .dual_cone import (project_sds_numerics, resolve_sds_conditions,
                                validate_sds_physics, validate_sds_release)
        validate_sds_release(document["release"])
        project_sds_numerics(document, raw["recording"])
        validate_sds_physics(document)
        conditions = resolve_sds_conditions(document, _json(_decode(resources["sds"]["sds_environment.json"])),
                                            native_species_registry(document))
        gas_data = {"status": "pending_guarded_cfd_admission", "conditions": conditions}
    result.update(constants_version=raw["constants_version"], gas_environment=copy.deepcopy(raw["gas_environment"]),
                  constants=dict(CONSTANTS), gas_data=gas_data)
    if result["recording"]["mode"] == "observation_times":
        result["recording"]["observation_times_us"] = [float(t) for t in result["recording"]["observation_times_us"]]
    else:
        for name in ("sample_interval_us", "end_time_us"):
            result["recording"][name] = float(result["recording"][name])
    result.update(study={"document": document, "snapshot": copy.deepcopy(study_snapshot)},
                  resource_snapshots=copy.deepcopy(resources), assembly=compiled,
                  species=native_species_registry(document))
    identity = {key: value for key, value in result.items() if key not in {"label", "study", "resource_snapshots"}}
    if result["gas_environment"]["status"] == "sds":
        identity["gas_environment"] = {"status": "sds", "sha256": result["gas_environment"]["sha256"].upper()}
    if "reference" in result["field_source"]:
        from .native_assets import collision_reference_identity, field_reference_identity
        identity["field_source"] = {"kind": result["field_source"]["kind"],
                                    "reference": (collision_reference_identity if result['field_source']['kind'] == 'simion_native'
                                                  else field_reference_identity)(result["field_source"]["reference"])}
        if "collision_reference" in result["field_source"]:
            from .native_assets import collision_reference_identity
            identity["field_source"].update(
                collision_reference=collision_reference_identity(result["field_source"]["collision_reference"]),
                sampling=copy.deepcopy(result["field_source"]["sampling"]))
    identity["study_document"] = document
    identity["resources"] = {name: record["sha256"] for name, record in resources.items() if name != "sds"}
    if "sds" in resources:
        identity["resources"]["sds"] = {name: (record["snapshot"]["sha256"] if name == "sds_gas_field"
                                                 else record["sha256"])
                                        for name, record in resources["sds"].items()}
    result["recipe_id"] = canonical_json_sha256(identity)
    return result


def resolve_native(raw: dict, author_path: Path) -> dict:
    """Resolve one file-bound study exactly once; package resources are frozen."""
    _keys(raw, {"schema_version", "label", "study", "field_source", "particle_tracer", "field_assembly_strategy", "particle_field_coupling", "recording", "constants_version", "gas_environment"}, "native recipe")
    _options(raw)
    _keys(raw["study"], {"path", "sha256"}, "study reference")
    reference = raw["study"]
    if not isinstance(reference["path"], str) or not reference["path"] or Path(reference["path"]).is_absolute():
        raise ValueError("study path must be explicit and relative to the author recipe")
    if not isinstance(reference["sha256"], str) or len(reference["sha256"]) != 64:
        raise ValueError("study SHA-256 must be explicit")
    snapshot = _snapshot((author_path.parent / reference["path"]).read_bytes())
    if snapshot["sha256"] != reference["sha256"].upper():
        raise ValueError("study SHA-256 mismatch")
    document = _json(_decode(snapshot))
    _study(document, raw["particle_tracer"])
    from .native_assets import freeze_field_source
    frozen = copy.deepcopy(raw)
    frozen["field_source"] = freeze_field_source(raw["field_source"], author_path)
    return _build(frozen, snapshot, _resource_snapshots(document, author_path.parent / reference["path"], raw["gas_environment"], author_path))


def validate_native(resolved: Mapping[str, Any]) -> dict:
    """Recompile only frozen bytes and reject tampering or changed provider output."""
    data = copy.deepcopy(dict(resolved))
    _keys(data, {"schema_version", "label", "study", "field_source", "particle_tracer", "field_assembly_strategy", "particle_field_coupling", "recording", "resource_snapshots", "assembly", "recipe_id", "constants_version", "gas_environment", "constants", "gas_data", "species"}, "resolved native recipe")
    _keys(data["study"], {"document", "snapshot"}, "resolved study")
    expected = _build(data, data["study"]["snapshot"], data["resource_snapshots"])
    if data != expected:
        raise ValueError("resolved native recipe differs from frozen inputs or identity")
    return expected
