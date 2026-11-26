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
from msplatform.io.file_identity import canonical_json_sha256
from msplatform.ion_release.release import validate_release_spec
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
        if not isinstance(native, dict) or not required <= native.keys() or native.keys() - required - {"rf_steps_per_period"}:
            raise ValueError("SIMION tracing needs explicit step and quality")
        _positive(native["maximum_step_us"], "maximum_step_us")
        if type(native["trajectory_quality"]) is not int or not -500 <= native["trajectory_quality"] <= 500:
            raise ValueError("SIMION trajectory_quality must be an integer from -500 to 500")
        if "rf_steps_per_period" in native and (type(native["rf_steps_per_period"]) is not int or native["rf_steps_per_period"] <= 0):
            raise ValueError("rf_steps_per_period must be a positive integer")
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
    _keys(data, {"schema_version", "name", "component_requests", "recipe", "drive", "physics", "release",
                 "numerics", "cad_export", "claim_limit", "model_input_sources"}, "study")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported study version")
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
    for key in ("pulse", "clock", "clock_authority"):
        if not isinstance(data["drive"].get(key), dict) or not data["drive"][key]:
            raise ValueError(f"study drive requires {key}")
    if data["drive"]["pulse"].get("mode") not in {"timed", "held_off", "discover"}:
        raise ValueError("unsupported study pulse mode")
    phase = data["drive"]["clock"].get("phase_reference_instrument_time_us")
    if type(phase) not in (int, float) or not math.isfinite(phase):
        raise ValueError("study drive needs a finite experiment clock reference")
    if not all(key in data["physics"] for key in ("field_model", "boundary_policy", "pulse_voltage_policy_id")):
        raise ValueError("study physics is missing its field, boundary or pulse policy")
    if any(not isinstance(data["physics"][key], str) or not data["physics"][key]
           for key in ("field_model", "boundary_policy", "pulse_voltage_policy_id")):
        raise ValueError("study physics policies must be explicit strings")
    if not {"representation", "write_pcurves", "precision_mode"} <= data["cad_export"].keys():
        raise ValueError("study CAD export settings are incomplete")
    requests = release_requests(data["release"])
    for release in requests:
        _validate_birth_request(release)
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


def _validate_birth_request(release: dict) -> None:
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


def _resource_snapshots(study: dict) -> dict:
    clock = study["drive"].get("clock_authority")
    if clock != {"example_resource": "instrument_clock_authority_v1.json"}:
        raise ValueError("native study requires the supported package clock authority resource")
    root = files("msplatform.examples")
    return {name: _snapshot(root.joinpath(name).read_bytes()) for name in
            ("instrument_clock_authority_v1.json", "instrument_epoch_v1.json")}


def _validate_resources(study: dict, resources: dict) -> None:
    _keys(resources, {"instrument_clock_authority_v1.json", "instrument_epoch_v1.json"}, "resources")
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
    from .reference import assembly_name
    resolved = {key: components.resolve_component(request) for key, request in study["component_requests"].items()}
    order = _sequence(study["recipe"], resolved)
    assembled = assembly.assemble(study["recipe"], resolved)
    physical = {"instances": study["recipe"]["instances"], "connections": study["recipe"]["connections"],
                "containments": study["recipe"].get("containments", []),
                "frame_id": study["recipe"]["assembly_frame_id"], "components": assembled.components_resolved}
    return {"name_version": 1, "name": assembly_name([resolved[key].provider_id for key in order]),
            "assembly_id": canonical_json_sha256(physical), "composition_plan": assembled.composition_plan,
            "components_resolved": assembled.components_resolved, "components_source": assembled.components_source}


def _options(raw: dict, *, resolved: bool = False) -> None:
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 2:
        raise ValueError("unsupported native recipe version")
    if not isinstance(raw["label"], str) or not raw["label"].strip():
        raise ValueError("label must be nonempty")
    if raw["constants_version"] != CONSTANTS["version"]:
        raise ValueError("native constants must explicitly select the supported frozen dataset")
    if raw["gas_environment"] != {"status": "vacuum"}:
        raise ValueError("native tracing currently requires explicit collision-free vacuum")
    source = raw["field_source"]
    if not isinstance(source, dict) or set(source) not in ({"kind"}, {"kind", "reference"},
            {"kind", "reference", "collision_reference", "sampling"}):
        raise ValueError("field_source requires kind and an optional explicit field reference")
    if "reference" in source:
        if source["kind"] != "comsol_native":
            raise ValueError("field references are supported only for COMSOL native fields")
        if resolved:
            from .native_assets import validate_field_reference
            validate_field_reference(source["reference"])
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
    _keys(raw["recording"], {"mode", "observation_times_us"}, "recording")
    times = raw["recording"]["observation_times_us"]
    if (raw["recording"]["mode"] != "observation_times" or not isinstance(times, list) or not times
            or any(type(t) not in (int, float, Decimal) or not math.isfinite(t) for t in times)
            or any(float(a) >= float(b) for a, b in zip(times, times[1:]))):
        raise ValueError("recording requires finite strictly increasing instrument observation times in us")


def _build(raw: dict, study_snapshot: dict, resources: dict) -> dict:
    _options(raw, resolved=True)
    document = _json(_decode(study_snapshot))
    _study(document, raw["particle_tracer"])
    _validate_resources(document, resources)
    compiled = _assembly(document)
    result = {key: copy.deepcopy(raw[key]) for key in ("schema_version", "label", "field_source", "particle_tracer", "field_assembly_strategy", "particle_field_coupling", "recording")}
    result.update(constants_version=raw["constants_version"], gas_environment={"status": "vacuum"},
                  constants=dict(CONSTANTS), gas_data=GasEnvironment("vacuum").to_dict())
    result["recording"]["observation_times_us"] = [float(t) for t in result["recording"]["observation_times_us"]]
    result.update(study={"document": document, "snapshot": copy.deepcopy(study_snapshot)},
                  resource_snapshots=copy.deepcopy(resources), assembly=compiled)
    identity = {key: value for key, value in result.items() if key not in {"label", "study", "resource_snapshots"}}
    if "reference" in result["field_source"]:
        from .native_assets import field_reference_identity
        identity["field_source"] = {"kind": result["field_source"]["kind"],
                                    "reference": field_reference_identity(result["field_source"]["reference"])}
        if "collision_reference" in result["field_source"]:
            from .native_assets import collision_reference_identity
            identity["field_source"].update(
                collision_reference=collision_reference_identity(result["field_source"]["collision_reference"]),
                sampling=copy.deepcopy(result["field_source"]["sampling"]))
    identity["study_document"] = document
    identity["resources"] = {name: record["sha256"] for name, record in resources.items()}
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
    return _build(frozen, snapshot, _resource_snapshots(document))


def validate_native(resolved: Mapping[str, Any]) -> dict:
    """Recompile only frozen bytes and reject tampering or changed provider output."""
    data = copy.deepcopy(dict(resolved))
    _keys(data, {"schema_version", "label", "study", "field_source", "particle_tracer", "field_assembly_strategy", "particle_field_coupling", "recording", "resource_snapshots", "assembly", "recipe_id", "constants_version", "gas_environment", "constants", "gas_data"}, "resolved native recipe")
    _keys(data["study"], {"document", "snapshot"}, "resolved study")
    expected = _build(data, data["study"]["snapshot"], data["resource_snapshots"])
    if data != expected:
        raise ValueError("resolved native recipe differs from frozen inputs or identity")
    return expected
