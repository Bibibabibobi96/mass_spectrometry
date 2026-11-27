"""Execute explicitly bound COMSOL world samples through SIMION collision owners."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from msplatform import assembly, components
from msplatform.io.file_identity import canonical_json_sha256
from msplatform.results.artifacts import open_artifact


def _reference(value: Any, label: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"reference", "snapshot"}:
        raise ValueError(label + " requires one frozen explicit manifest reference")
    ref = value["reference"]
    if not isinstance(ref, Mapping) or set(ref) != {"manifest", "product_id"}:
        raise ValueError(label + " manifest reference differs")
    snapshot = value["snapshot"]
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"sha256", "bytes_base64"}:
        raise ValueError(label + " snapshot differs")
    try:
        payload = base64.b64decode(snapshot["bytes_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(label + " snapshot bytes differ") from exc
    digest = hashlib.sha256(payload).hexdigest().upper()
    record = ref["manifest"]
    if (not isinstance(record, Mapping) or record.get("bytes") != len(payload)
            or str(record.get("sha256", "")).upper() != digest or str(snapshot["sha256"]).upper() != digest):
        raise ValueError(label + " frozen manifest identity differs")
    return copy.deepcopy(dict(ref))


def _read(artifact, key):
    return json.loads(artifact.data_path(key).read_text(encoding="utf-8-sig"))


def _stored_reference(artifact, key, product_id):
    record = dict(artifact.data_records[key], path=str(artifact.data_path(key)))
    return {"manifest": record, "product_id": product_id}


def compile_scalar_inputs(recipe: dict) -> dict:
    """Check explicit scientific, sampled-grid and collision-source authorities.

    Reads published inputs; does not run a solver, create files or infer grids.
    A consuming owner must protect these source references before using them.
    """
    from msplatform.backends.comsol.assembly_field_export import validate_grid, _validate_field_solution_source
    from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
    from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
    from msplatform.backends.simion.artifacts import CompiledPreparedModel
    from msplatform.backends.simion.model import compile_prepared_model, model_geometry, require_prepared_model
    from msplatform.backends.simion.scalar_sample_binding import preflight_scalar_representation
    from msplatform.recipes.native import release_requests

    if (not isinstance(recipe, dict) or recipe.get("schema_version") != 2
            or recipe.get("particle_tracer") != "simion" or recipe.get("field_assembly_strategy") != "sampled_joint_field"
            or recipe.get("particle_field_coupling") != "external_given_field"):
        raise ValueError("scalar bridge requires the explicit native COMSOL-to-SIMION strategy")
    source = recipe.get("field_source")
    if not isinstance(source, Mapping) or set(source) != {"kind", "reference", "collision_reference", "sampling"} or source["kind"] != "comsol_native":
        raise ValueError("scalar bridge requires COMSOL source, collision reference and explicit sampling")
    background_ref = _reference(source["reference"], "COMSOL field")
    collision_ref = _reference(source["collision_reference"], "SIMION collision field")
    if background_ref["product_id"] != "background":
        raise ValueError("COMSOL reference must select its actual background workpoint")
    background = open_artifact(background_ref, expected_kind="field_solution")
    on_ref = {"manifest": copy.deepcopy(background_ref["manifest"]), "product_id": "on"}
    on = open_artifact(on_ref, expected_kind="field_solution")
    if any(product.metadata.get("scope") != "co_resident_stationary_workpoint" or
           product.metadata.get("co_resident_workpoint") != name for product,name in ((background,"background"),(on,"on"))):
        raise ValueError("COMSOL requires the same co-resident OFF and ON basis")
    solutions = {"off": _validate_field_solution_source(background), "on": _validate_field_solution_source(on)}
    prepared = open_artifact(_stored_reference(background, "prepared_manifest", "model"), expected_kind="prepared_model")
    if (prepared.metadata.get("backend") != "comsol" or prepared.metadata.get("scope") != "assembly_electrostatic_unsolved"
            or prepared.metadata.get("native_reopen_verified") is not True):
        raise ValueError("COMSOL field prepared-model provenance differs")
    geometry_ref = _stored_reference(prepared, "geometry_manifest", "geometry")
    geometry = open_artifact(geometry_ref, expected_kind="geometry_artifact")
    if (geometry.metadata.get("backend") != "comsol" or geometry.metadata.get("scope") != "geometry_only"
            or geometry.metadata.get("native_reopen_verified") is not True):
        raise ValueError("COMSOL geometry provenance differs")
    study = recipe["study"]["document"]
    parts = {name: components.resolve_component(request) for name, request in study["component_requests"].items()}
    instrument = assembly.assemble(study["recipe"], parts)
    snapshot = {"composition_plan": instrument.composition_plan, "components_resolved": instrument.components_resolved,
                "components_source": instrument.components_source}
    geometry_settings = study["numerics"]["geometry"]
    if set(geometry_settings) != {"outer_box_mm", "geometry_validation"}:
        raise ValueError("COMSOL study requires its explicit world box and geometry validation")
    projection = project_assembly_geometry(snapshot, outer_box_mm=geometry_settings["outer_box_mm"])
    if _read(geometry, "projection") != projection or _read(background, "projection") != projection or _read(on, "projection") != projection:
        raise ValueError("frozen study and COMSOL geometry projections differ")
    physics = study["physics"]
    if physics.get("field_model") != "external_electrostatic_linear" or physics.get("boundary_policy") != "comsol_finite_exterior_potential":
        raise ValueError("scalar bridge requires the declared COMSOL finite-exterior physical model")
    field_settings = study["numerics"]["fields"]
    if set(field_settings) != {"relative_permittivity", "exterior", "mesh"}:
        raise ValueError("COMSOL field operator is incomplete")
    pulse = study["drive"]["pulse"]
    if set(pulse) != {"mode", "time_us", "width_us"} or pulse["mode"] != "timed":
        raise ValueError("scalar bridge requires the explicit timed pulse")
    rows = {"off": [], "on": []}
    for instance, groups in study["drive"]["groups"].items():
        for group, value in groups.items():
            if value.get("kind") == "static" and set(value) == {"kind", "voltage_v"}:
                off = on_voltage = value["voltage_v"]
            elif value.get("kind") == "pulse" and set(value) == {"kind", "off_voltage_v", "on_voltage_v"}:
                off, on_voltage = value["off_voltage_v"], value["on_voltage_v"]
            else:
                raise ValueError("scalar bridge supports explicit static and pulsed groups only")
            for name, voltage in (("off",off),("on",on_voltage)):
                rows[name].append(dict(instance_id=instance,electrode_group_id=group,voltage_v=voltage))
    for name, product in (("off",background),("on",on)):
        expected = validate_request(projection, dict(group_voltages=rows[name], **copy.deepcopy(field_settings), study={"kind":"stationary"}))
        if _read(product,"request") != expected:
            raise ValueError("COMSOL saved workpoint differs from frozen study: " + name)
    collision = open_artifact(collision_ref, expected_kind="field_bundle")
    if (collision.metadata.get("backend") != "simion" or collision.metadata.get("field_status") != "available"
            or collision.metadata.get("source_status") != "not_requested"):
        raise ValueError("collision reference requires a published source-free SIMION field bundle")
    model = CompiledPreparedModel(collision.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    doc = require_prepared_model(model)
    native_geometry = doc["geometry"]["frontend_geometry"]
    if (native_geometry.get("role") != "simion_split_oa_tof_geometry"
            or native_geometry["composition_plan"] != instrument.composition_plan
            or doc["components_resolved"] != instrument.components_resolved):
        raise ValueError("collision source assembly differs from frozen study")
    if (collision.metadata.get("model_identity_sha256") != doc["model_identity_sha256"]
            or collision.metadata.get("clock") != doc["drive"]["clock"]
            or doc["drive"]["groups"] != study["drive"]["groups"]
            or doc["drive"]["pulse"] != pulse
            or doc["drive"]["clock"]["phase_reference_instrument_time_us"] != study["drive"]["clock"]["phase_reference_instrument_time_us"]):
        raise ValueError("collision source drive, pulse or clock differs from frozen study")
    if doc["physics"].get("pulse_voltage_policy_id") != physics.get("pulse_voltage_policy_id"):
        raise ValueError("collision source pulse voltage policy differs from frozen study")
    rebuilt = compile_prepared_model(model_geometry(model), doc["components_resolved"], drive=doc["drive"], physics=doc["physics"])
    if rebuilt.document != doc:
        raise ValueError("collision source model differs from its actual compiled inputs")
    for release in release_requests(study["release"]):
        actual = doc["drive"]["clock"]
        if release["clock"] != {"clock_epoch_id": actual["clock_epoch_id"], "authority_sha256": actual["authority_sha256"]}:
            raise ValueError("original birth clock differs from collision model")
    sampling = source["sampling"]
    if not isinstance(sampling, Mapping) or set(sampling) != {"world", "windows"} or not isinstance(sampling["windows"], list):
        raise ValueError("scalar sampling requires explicit world and windows")
    grid_keys = {"frame_id", "origin_mm", "pitch_mm", "dimensions", "block_points"}
    if not isinstance(sampling["world"], Mapping) or set(sampling["world"]) != grid_keys:
        raise ValueError("world sampling requires explicit frame, origin, pitch, dimensions and block size")
    grids = {"world": copy.deepcopy(dict(sampling["world"]))}
    windows = []
    for window in sampling["windows"]:
        if (not isinstance(window, Mapping) or set(window) != {"name", "grid", "active_box_mm"}
                or not isinstance(window["name"], str) or re.fullmatch(r"[a-z][a-z0-9_]{0,39}", window["name"]) is None
                or window["name"] == "world" or window["name"] in grids
                or not isinstance(window["grid"], Mapping) or set(window["grid"]) != grid_keys):
            raise ValueError("scalar sampling windows require unique name, explicit grid and active box")
        grids[window["name"]] = copy.deepcopy(dict(window["grid"]))
        windows.append(copy.deepcopy(dict(window)))
    for name, grid in grids.items():
        for state in ("off", "on"):
            tagged = dict(grid, **{k: solutions[state][k] for k in ("study_tag", "solution_tag", "dataset_tag")})
            checked = validate_grid(tagged, projection, solutions[state])
            if name == "world" and (checked["origin_mm"] != projection["outer_box_mm"]["min"] or
                                     checked["maximum_mm"] != projection["outer_box_mm"]["max"]):
                raise ValueError("scalar world grid must cover exactly the complete COMSOL outer box")
    preflight_scalar_representation(projection, grids["world"], windows, allow_partial_sheets=True)
    return dict(instrument=instrument, background=background, on=on, prepared=prepared, geometry=geometry, collision=collision,
                solutions=solutions, grids=grids, windows=windows, projection=projection,
                collision_model_identity=doc["model_identity_sha256"])



def _reference_identity(reference: Mapping[str, Any]) -> dict:
    """Use an owner's sealed content identity, never its machine-specific path."""
    return {"manifest_sha256": reference["manifest"]["sha256"].upper(), "product_id": reference["product_id"]}


def _selection_identity(selection: Mapping[str, Any]) -> dict:
    result = {"geometry_artifact": _reference_identity(selection["geometry_artifact"]),
              "samples": {name: _reference_identity(value) for name,value in selection["samples"].items()}}
    if "refinement_windows" in selection:
        result["refinement_windows"] = [{"name": row["name"], "active_box_mm": row["active_box_mm"],
            "samples": {name: _reference_identity(value) for name,value in row["samples"].items()}}
            for row in selection["refinement_windows"]]
    return result

def run_scalar_stages(recipe: dict, instrument: Any, particles: Any, *, context: Any,
                      stage_cache: Any, invoke: Any, implementation: dict, epoch_record: dict,
                      resource_root: Any = None) -> tuple[Any, dict]:
    """Export existing COMSOL workpoints and track original births via one world owner.

    Stage caching and lifetime claims are supplied by the caller's existing
    owner. This function never computes a COMSOL solution or refines a SIMION PA.
    """
    from msplatform.backends import simion
    from msplatform.backends.comsol import assembly_field_export as comsol
    if not isinstance(implementation, Mapping) or set(implementation) != {"comsol", "simion"}:
        raise ValueError("scalar bridge requires separate COMSOL and SIMION implementation identities")
    admission = compile_scalar_inputs(recipe)
    from .native_tracing import _particle_document, _realizations
    release = recipe["study"]["document"]["release"]
    birth = _particle_document(particles)
    expected_births = _realizations(release, resource_root=resource_root)
    if not any(_particle_document(expected) == birth for expected in expected_births):
        raise ValueError("scalar bridge births differ from the frozen study source")
    rows = birth["rows"] if isinstance(particles, Mapping) else particles.rows
    if (instrument.composition_plan != admission["instrument"].composition_plan
            or instrument.components_resolved != admission["instrument"].components_resolved):
        raise ValueError("caller Assembly differs from frozen scalar study")
    receipts = {}
    def claim_source(name, artifact, kind):
        ref = artifact.reference
        key = canonical_json_sha256({"stage": "scalar_explicit_source", "kind": kind,
            "manifest_sha256": ref["manifest"]["sha256"], "product_id": ref["product_id"]})
        selected, receipt = stage_cache(name, key, kind, lambda: open_artifact(ref, expected_kind=kind))
        if selected.reference != ref:
            raise ValueError("protected scalar source differs from the explicitly frozen source")
        receipts[name] = receipt
        return selected
    for name, kind in (("background", "field_solution"), ("on", "field_solution"),
                       ("prepared", "prepared_model"), ("geometry", "geometry_artifact"),
                       ("collision", "field_bundle")):
        claim_source(name, admission[name], kind)
    # Recheck after the existing owner has acquired its source claims. No
    # scientific value is substituted from the cache or execution context.
    current = compile_scalar_inputs(recipe)
    if (current["projection"] != admission["projection"] or current["collision_model_identity"] != admission["collision_model_identity"]
            or any(current[name].reference != admission[name].reference for name in ("background", "on", "prepared", "geometry", "collision"))):
        raise ValueError("scalar authorities changed during source admission")
    tagged = {}
    for state in ("off", "on"):
        tags = {key: current["solutions"][state][key] for key in ("study_tag", "solution_tag", "dataset_tag")}
        tagged[state] = {name: dict(copy.deepcopy(grid), **tags) for name,grid in current["grids"].items()}
    derived = {"off": {}, "on": {}}
    for state, solution in (("off", current["background"]), ("on", current["on"])):
        export_key = canonical_json_sha256({"stage":"comsol_world_scalar_export", "source":_reference_identity(solution.reference),
            "grids":tagged[state], "implementation":implementation["comsol"]})
        def export():
            products = invoke(lambda: comsol.export_world_scalar_grids(solution, grids=tagged[state], context=context))
            return products["world"]
        world_raw, receipt = stage_cache("scalar_export_" + state, export_key, "scalar_field_samples", export)
        receipts["scalar_export_" + state] = receipt
        if world_raw.reference["product_id"] != "samples_world":
            raise ValueError("scalar export did not publish its actual world product")
        for grid_name in current["grids"]:
            if grid_name == "world":
                raw = world_raw
            else:
                ref = {"manifest": copy.deepcopy(world_raw.reference["manifest"]), "product_id":"samples_" + grid_name}
                key = canonical_json_sha256({"stage":"comsol_world_scalar_export_product", "export":export_key, "name":grid_name})
                raw, receipt = stage_cache("scalar_export_" + state + "_" + grid_name, key, "scalar_field_samples",
                    lambda ref=ref: open_artifact(ref, expected_kind="scalar_field_samples"))
                receipts["scalar_export_" + state + "_" + grid_name] = receipt
                if raw.reference != ref:
                    raise ValueError("sample grid product differs from its export owner")
            support_key = canonical_json_sha256({"stage":"comsol_world_scalar_support", "raw":_reference_identity(raw.reference),
                                                  "implementation":implementation["comsol"]})
            support, receipt = stage_cache("scalar_support_" + state + "_" + grid_name, support_key,
                "scalar_field_samples", lambda raw=raw: invoke(lambda: comsol.derive_world_scalar_support(raw, context=context)))
            receipts["scalar_support_" + state + "_" + grid_name] = receipt
            derived[state][grid_name] = support
    selection = {"geometry_artifact": current["geometry"].reference,
        "samples": {state: derived[state]["world"].reference for state in ("off", "on")}}
    if current["windows"]:
        selection["refinement_windows"] = [{"name":window["name"], "active_box_mm":window["active_box_mm"],
            "samples":{state:derived[state][window["name"]].reference for state in ("off","on")}}
            for window in current["windows"]]
    world_key = canonical_json_sha256({"stage":"split_scalar_world", "collision":_reference_identity(current["collision"].reference),
        "selection":_selection_identity(selection), "implementation":implementation["simion"]})
    world, receipt = stage_cache("scalar_world", world_key, "field_bundle",
        lambda: invoke(lambda: simion.prepare_split_scalar_world(current["collision"], scalar_field_basis=selection, context=context)))
    receipts["scalar_world"] = receipt
    if (world.metadata.get("field_representation") != "split_scalar_world_with_collision_geometry"
            or world.metadata.get("field_source") != "comsol_off_on_scalar_samples"
            or world.metadata.get("collision_source_reference") != current["collision"].reference):
        raise ValueError("published scalar world differs from its explicit collision source")
    study = recipe["study"]["document"]
    tof = next(name for name, component in instrument.components.items() if component.provider_id == "single_reflection_tof")
    observations = {"plane_observations":[{"schema_version":2, "observation_id":"detector", "source_instance_id":tof,
        "surface_id":"detector_active_face", "max_records":len(rows)}],
        "observation_times_us":copy.deepcopy(recipe["recording"]["observation_times_us"])}
    if "field_intervention" in recipe["recording"]:
        observations["field_intervention"] = copy.deepcopy(recipe["recording"]["field_intervention"])
    propagation = {"schema_version":1, "scope":"continuous_assembly", "stop":None, "consumed_plane_events":[],
                   "end_policy":copy.deepcopy(study["numerics"]["tracing"]["end_policy"])}
    numerics = copy.deepcopy(study["numerics"]["tracing"]["simion"])
    trace_key = canonical_json_sha256({"stage":"scalar_simion_trace", "world":world_key, "particles":(release if isinstance(particles, Mapping) else birth),
        "propagation":propagation, "observations":observations, "numerics":numerics,
        "epoch_sha256":epoch_record["sha256"], "implementation":implementation["simion"]})
    trajectory, receipt = stage_cache("scalar_trace", trace_key, "trajectory_result",
        lambda: invoke(lambda: simion.track(world, particles, propagation=propagation, observations=observations,
                                            numerics=numerics, context=context, scalar_field_basis=selection)))
    receipts["scalar_trace"] = receipt
    return trajectory, receipts
