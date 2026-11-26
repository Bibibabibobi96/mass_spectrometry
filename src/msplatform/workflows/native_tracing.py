"""Frozen public recipes orchestrate existing native owners and SI result readers.

The legacy execution owner retains ownership of PA/MPH payloads. ArtifactStore
owns only small verified references, canonical scientific data and run evidence.
"""
from __future__ import annotations

import base64
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from typing import Any

from msplatform import assembly, components
from msplatform.io.file_identity import canonical_json_sha256, file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.recipes import SimulationRecipe, validate_recipe
from msplatform.results.particle_data import read_particle_data, summarize_particle_data, write_particle_data
from msplatform.results.model import TraceResult
from msplatform.storage import ArtifactStore


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def _executable_records(paths):
    # Installed executables are implementation evidence, not owned PA/MPH
    # payloads. Declare that role even above the shared large-file I/O tier.
    return {name: {key: value for key, value in file_record(Path(path), "required_evidence").items()
                   if key in {"bytes", "sha256"}} for name, path in paths.items()}


def _assembly(recipe: dict):
    study = recipe["study"]["document"]
    resolved = {name: components.resolve_component(request) for name, request in study["component_requests"].items()}
    return assembly.assemble(study["recipe"], resolved)


def _realizations(release):
    from msplatform.ion_release import sample_release
    if release["role"] == "canonical_mass_scan_request":
        from .mass_scan import prepare_mass_scan
        return prepare_mass_scan(release)
    return [sample_release(release)]


def _flight_request(recipe, instrument, particles):
    study = recipe["study"]["document"]
    tof = next(name for name, component in instrument.components.items() if component.provider_id == "single_reflection_tof")
    observations = {"plane_observations": [{"schema_version": 2, "observation_id": "detector", "source_instance_id": tof,
                     "surface_id": "detector_active_face", "max_records": len(particles.rows)}],
                    "observation_times_us": recipe["recording"]["observation_times_us"]}
    propagation = {"schema_version": 1, "scope": "continuous_assembly", "stop": None,
                   "consumed_plane_events": [], "end_policy": study["numerics"]["tracing"]["end_policy"]}
    return propagation, observations


def preflight_native(recipe: dict, *, context=None) -> dict:
    """Check scientific compilation independently of host availability/native evidence."""
    recipe = validate_recipe(recipe)
    if recipe["schema_version"] != 2:
        raise ValueError("native preflight requires a native resolved recipe")
    selected = (recipe["field_source"]["kind"], recipe["particle_tracer"], recipe["field_assembly_strategy"])
    if selected not in {("simion_native", "simion", "native_domain_composition"),
                        ("comsol_native", "comsol", "joint_solve"),
                        ("comsol_native", "simion", "sampled_joint_field")}:
        raise ValueError("native public execution is not yet implemented for this field/tracer/assembly combination")
    instrument = _assembly(recipe)
    providers = [value.provider_id for value in instrument.components.values()]
    if (providers.count("orthogonal_accelerator") != 1 or providers.count("single_reflection_tof") != 1
            or any(name not in {"orthogonal_accelerator", "single_reflection_tof", "rf_multipole"} for name in providers)
            or providers.count("rf_multipole") > 1):
        raise ValueError("native execution requires independent OA and downstream TOF, optionally one upstream RF")
    if selected[0] == "comsol_native":
        scalar = selected[1] == "simion"
        if scalar:
            from .scalar_tracing import compile_scalar_inputs
            admission = compile_scalar_inputs(recipe)
            if context is not None:
                root = (context.workspace / "artifacts").resolve()
                if any(root not in admission[name].manifest_location.resolve().parents
                       for name in ("background", "on", "prepared", "geometry", "collision")):
                    raise ValueError("scalar source owners must belong to the explicit execution workspace artifact root")
        else:
            from .comsol_tracing import compile_comsol_inputs
            for particles in _realizations(recipe["study"]["document"]["release"]):
                compile_comsol_inputs(recipe, instrument, particles)
        available = None if context is None else (
            context.python_executable.is_file() and context.powershell_executable.is_file()
            and all(name in context.tools and context.tools[name].is_file() for name in ("comsol", "comsol_launcher"))
            and "matlab_root" in context.tools and (context.tools["matlab_root"] / "bin/matlab.exe").is_file())
        if scalar and available is not None:
            available = available and "simion" in context.tools and context.tools["simion"].is_file()
        return {"field_source": selected[0], "particle_tracer": selected[1], "field_assembly_strategy": selected[2],
                "implemented": True, "host_available": available, "native_verified": False,
                "verification_scope": "scientific_compilation_only", "assembly_id": recipe["assembly"]["assembly_id"],
                "limitations": (["explicit frozen OFF/ON source and collision carrier; no Compute or Refine fallback",
                                  "sample support and numerical accuracy require actual native qualification"] if scalar else
                                ["one common birth time and species per native batch; no RF",
                                "finite exterior potential differs from the SIMION Neumann boundary",
                                "actual native fields and particle tracing remain separately qualified"])}
    from msplatform.backends import simion
    from msplatform.backends.simion.model import compile_prepared_model
    from msplatform.backends.simion.field_execution import plan_fields_execution
    study = recipe["study"]["document"]
    compiled = simion.compile_geometry(instrument, numerics=study["numerics"]["geometry"])
    drive = copy.deepcopy(study["drive"])
    authority = json.loads(base64.b64decode(recipe["resource_snapshots"]["instrument_clock_authority_v1.json"]["bytes_base64"]))
    drive.pop("clock_authority")
    drive["clock"].update(clock_epoch_id=authority["clock_epoch_id"], authority_sha256=authority["authority"]["sha256"])
    model = compile_prepared_model(compiled, instrument.components_resolved, drive=drive, physics=study["physics"])
    # Pure field validation uses the same planner as real execution; it creates
    # no run, native file or resource grant.
    plan_fields_execution(model, numerics=study["numerics"]["fields"])
    from msplatform.backends.simion.tracking_execution import plan_tracking_execution
    # Materialize only the already-frozen small clock inputs for the existing
    # planner's file-record contract; no native process or run is created.
    with tempfile.TemporaryDirectory(prefix="msplatform-preflight-") as directory:
        root = Path(directory)
        for name, snapshot in recipe["resource_snapshots"].items():
            (root / name).write_bytes(base64.b64decode(snapshot["bytes_base64"]))
        clocks = {"clock_authority": file_record(root / "instrument_clock_authority_v1.json"),
                  "instrument_epoch": file_record(root / "instrument_epoch_v1.json")}
        for particles in _realizations(study["release"]):
            propagation, observations = _flight_request(recipe, instrument, particles)
            plan_tracking_execution(model, particles=particles.to_dict(), clock_records=clocks,
                propagation=propagation, observations=observations, numerics=study["numerics"]["tracing"]["simion"])
    available = None if context is None else all(
        Path(path).is_file() for path in (context.python_executable, context.powershell_executable,
                                         context.tools.get("simion", Path("missing-simion"))))
    return {"field_source": selected[0], "particle_tracer": selected[1], "field_assembly_strategy": selected[2],
            "implemented": True, "host_available": available, "native_verified": False,
            "verification_scope": "scientific_compilation_only", "assembly_id": recipe["assembly"]["assembly_id"],
            "limitations": ["prescribed electric field; no collisions or self consistency",
                            "native PA domain composition is not a monolithic joint electrostatic solve",
                            "native qualification requires a recorded actual run"]}


def _complete_trajectory(artifact) -> bool:
    if artifact.kind != "trajectory_result":
        return True
    data = read_particle_data(artifact.data_path("particle_data_execution_json").parent)
    return data["execution_status"] == "succeeded" and data["data_integrity"].get("status") == "complete"


def _native_reference(store, stack, key, produce, *, kind, raw_root, claims, calls):
    """Verify a tiny cached reference against its real owner before reuse."""
    cached = stack.enter_context(store.claim_key(key))
    from msplatform.execution.native_source_guard import guard_native_source
    if cached is not None:
        asset_id, path = cached
        try:
            reference = json.loads((path / "reference.json").read_text(encoding="utf-8"))
            artifact = stack.enter_context(guard_native_source(reference, expected_kind=kind,
                                                               expected_artifact_root=raw_root))
            if not _complete_trajectory(artifact):
                artifact = None
        except (ValueError, OSError, KeyError):
            artifact = None
        if artifact is not None:
            token, _ = stack.enter_context(store.claim_token(asset_id))
            claims.append(token)
            return artifact, {"asset_id": asset_id, "task_key": key, "reused": True}
    calls.append(key)
    artifact = produce()
    artifact = stack.enter_context(guard_native_source(artifact.reference, expected_kind=kind,
                                                       expected_artifact_root=raw_root))
    if not _complete_trajectory(artifact):
        return artifact, {"asset_id": None, "task_key": key, "reused": False,
                          "cache_status": "ineligible_incomplete_or_failed"}
    work = store.new_work()
    _write(work / "reference.json", artifact.reference)
    asset_id, _ = stack.enter_context(store.put_asset_claimed("native_reference", key, work, retention="cache"))
    token, _ = stack.enter_context(store.claim_token(asset_id))
    claims.append(token)
    return artifact, {"asset_id": asset_id, "task_key": key, "reused": False}


def run_loaded_recipe(loaded: SimulationRecipe, *, context, artifact_root,
                      high_water_bytes=None, low_water_bytes=None, safety_bytes=0,
                      reserve_bytes=0, source_revision=None, cancelled=None) -> dict:
    """Run one already-read author input through native owners without rereading it."""
    if context is None:
        raise ValueError("native execution requires an explicit ExecutionContext")
    if cancelled is not None:
        raise ValueError("native callback cancellation is not implemented; managed owner cancellation applies")
    recipe = loaded.to_dict()
    report = preflight_native(recipe, context=context)
    if not report["host_available"]:
        raise ValueError("selected native execution tools are unavailable")
    if source_revision is not None:
        import re
        if not re.fullmatch(r"[0-9a-fA-F]{40}", source_revision):
            raise ValueError("source_revision must be an explicit full repository SHA")
    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("native scientific outputs require an explicit positive reserve_bytes budget")
    store = ArtifactStore(artifact_root, high_water_bytes=high_water_bytes,
                          low_water_bytes=low_water_bytes, safety_bytes=safety_bytes)
    # The raw native owner and this Store must never govern the same payload.
    raw_root = (context.workspace / "artifacts").resolve()
    if store.root == raw_root or raw_root in store.root.parents or store.root in raw_root.parents:
        raise ValueError("native ArtifactStore and existing native owner roots must be disjoint")
    run_id, work = store.begin_run()
    (work / "author.toml").write_bytes(loaded.source_bytes)
    _write(work / "resolved.json", recipe)
    _write(work / "preflight.json", report)
    with store.run_writer(run_id):
        try:
            with store.reserve(reserve_bytes) as reservation:
                store.mark_running(run_id)
                _execute(store, recipe, context, run_id, work, reservation, source_revision)
        except BaseException as error:
            status = store.run_status(run_id)["execution_status"]
            if status == "queued":
                store.set_queued_reason(run_id, str(error))
            elif status == "running":
                store.finish_run(run_id, "cancelled" if isinstance(error, KeyboardInterrupt) else "failed", reason=str(error))
            raise
    from .reference_tracing import inspect_results
    return {"run_id": run_id, "artifact_root": str(store.root), **inspect_results(run_id, artifact_root=store.root)}


def _execute(store, recipe, context, run_id, work, reservation, source_revision):
    from msplatform.backends import simion
    from msplatform.execution.native_artifact_controls import protect_native_controls
    study = recipe["study"]["document"]
    instrument = _assembly(recipe)
    resources = work / "frozen_resources"
    resources.mkdir()
    for name, snapshot in recipe["resource_snapshots"].items():
        (resources / name).write_bytes(base64.b64decode(snapshot["bytes_base64"]))
    drive = copy.deepcopy(study["drive"])
    drive["clock_authority"] = {"contract": file_record(resources / "instrument_clock_authority_v1.json"),
                                 "data_root": str(resources)}
    comsol = recipe["field_source"]["kind"] == "comsol_native"
    scalar = comsol and recipe["particle_tracer"] == "simion"
    if comsol:
        from msplatform.backends import comsol as backend_module
        compiled = None
        tool_paths = {"comsol": context.tools["comsol"], "matlab": context.tools["matlab_root"] / "bin/matlab.exe",
                      "launcher": context.tools["comsol_launcher"]}
    else:
        backend_module = simion
        compiled = simion.compile_geometry(instrument, numerics=study["numerics"]["geometry"])
        tool_paths = {"simion": context.tools["simion"]}
    package = Path(__file__).parents[1]
    shared_sources = canonical_json_sha256({path.relative_to(package).as_posix(): file_sha256(path)
        for directory in ("assembly", "components", "contracts", "physics", "results", "ion_release", "fields", "io")
        for path in sorted((package / directory).rglob("*.py")) if path.is_file()})
    def identity(module, paths):
        backend = Path(module.__file__).parent
        return {
        "shared_sources": shared_sources,
        "backend_sources": canonical_json_sha256({path.relative_to(backend).as_posix(): file_sha256(path)
            for path in sorted(backend.rglob("*")) if path.is_file() and path.suffix in {
                ".py", ".m", ".lua", ".gem", ".json", ".ps1", ".iob", ".pa0", ".fly2"}}),
        "native_executable": _executable_records(paths)}
    backend_identity = identity(backend_module, tool_paths)
    implementation = {"workflow": file_sha256(__file__), **backend_identity}
    if scalar:
        # COMSOL export/support also consume SIMION scalar-payload code; both
        # owners must change identity when that shared implementation changes.
        simion_identity = identity(simion, {"simion": context.tools["simion"]})
        backend_identity["scalar_payload_sources"] = simion_identity["backend_sources"]
        bridge_source = file_sha256(Path(__file__).with_name("scalar_tracing.py"))
        backend_identity["bridge_source"] = bridge_source
        simion_identity["bridge_source"] = bridge_source
        implementation = {"workflow": file_sha256(__file__),
                          "comsol": backend_identity,
                          "simion": simion_identity}
    calls, receipts, control_ids = [], {}, []
    with ExitStack() as stack:
        snapshot = store.new_work()
        _write(snapshot / "input.json", recipe)
        input_id, _ = stack.enter_context(store.put_asset_claimed("native_input", recipe["recipe_id"], snapshot, retention="cache"))
        token, _ = stack.enter_context(store.claim_token(input_id))
        control_ids.append(token)

        def invoke(action):
            with protect_native_controls(store, run_id=run_id, claim_ids=tuple(control_ids),
                                         reservation_ids=(reservation,), work_directory=work):
                return action()

        field_implementation = {key: value for key, value in implementation.items() if key != "workflow"}
        if not comsol:
            geometry_key = canonical_json_sha256({"stage": "geometry", "compiled": compiled.__dict__, "implementation": field_implementation})
            geometry, receipts["geometry"] = _native_reference(store, stack, geometry_key,
                lambda: invoke(lambda: simion.build_geometry(compiled, context=context)), kind="geometry_artifact", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls)
            _write(work / "native_stages.json", receipts)
            model_key = canonical_json_sha256({"stage": "model", "geometry": geometry_key, "drive": study["drive"],
                "clock_resources": {name: record["sha256"] for name, record in recipe["resource_snapshots"].items()},
                "physics": study["physics"], "implementation": field_implementation})
            model, receipts["model"] = _native_reference(store, stack, model_key,
                lambda: invoke(lambda: simion.prepare_model(geometry, drive=drive, physics=study["physics"], context=context)), kind="prepared_model", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls)
            _write(work / "native_stages.json", receipts)
            field_key = canonical_json_sha256({"stage": "field", "model": model_key, "numerics": study["numerics"]["fields"], "implementation": field_implementation})
            field, receipts["field"] = _native_reference(store, stack, field_key,
                lambda: invoke(lambda: simion.solve_fields(model, numerics=study["numerics"]["fields"], context=context)), kind="field_bundle", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls)
            _write(work / "native_stages.json", receipts)
        from .mass_scan import merge_mass_scan, analyze_mass_scan
        batches, common, stage_memo = [], None, {}
        for ordinal, particles in enumerate(_realizations(study["release"])):
            if comsol:
                if scalar:
                    from .scalar_tracing import run_scalar_stages as run_stages
                else:
                    from .comsol_tracing import run_comsol_stages as run_stages
                def stage_cache(name, key, kind, produce):
                    cache_id = (key, kind)
                    if cache_id in stage_memo:
                        artifact, receipt = stage_memo[cache_id]
                        receipt = {**receipt, "reused": True, "reuse_scope": "current_run"}
                        receipts[f"batch_{ordinal}_{name}"] = receipt
                        _write(work / "native_stages.json", receipts)
                        return artifact, receipt
                    result = _native_reference(store, stack, key, produce, kind=kind,
                        raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls)
                    stage_memo[cache_id] = result
                    receipts[f"batch_{ordinal}_{name}"] = result[1]
                    _write(work / "native_stages.json", receipts)
                    return result
                trajectory, batch_receipts = run_stages(recipe, instrument, particles, context=context,
                    invoke=invoke, stage_cache=stage_cache, implementation=field_implementation,
                    epoch_record=file_record(resources / "instrument_epoch_v1.json"))
                receipts.update({f"batch_{ordinal}_{name}": receipt for name, receipt in batch_receipts.items()})
            else:
                propagation, observations = _flight_request(recipe, instrument, particles)
                trace_key = canonical_json_sha256({"stage": "trace", "field": field_key, "particles": particles.to_dict(),
                    "propagation": propagation, "observations": observations,
                    "numerics": study["numerics"]["tracing"]["simion"], "implementation": implementation})
                trajectory, receipts["trace_" + str(ordinal)] = _native_reference(store, stack, trace_key,
                    lambda: invoke(lambda: simion.track(field, particles, propagation=propagation, observations=observations,
                        numerics=study["numerics"]["tracing"]["simion"], context=context)), kind="trajectory_result",
                    raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls)
            data = read_particle_data(trajectory.data_path("particle_data_execution_json").parent)
            if scalar:
                from msplatform.backends.simion.model import require_prepared_model
                from msplatform.backends.simion.artifacts import CompiledPreparedModel
                from .scalar_tracing import compile_scalar_inputs
                collision = compile_scalar_inputs(recipe)["collision"]
                collision_model = CompiledPreparedModel(collision.data_path("compiled_model").read_text(encoding="utf-8-sig"))
                expected_frame = require_prepared_model(collision_model)["geometry"]["frontend_geometry"]["native_frame_id"]
            else:
                expected_frame = study["recipe"]["assembly_frame_id"] if comsol else compiled.frontend_geometry["native_frame_id"]
            if data["metadata"]["frame_id"] != expected_frame:
                raise ValueError("native batch result has a different frame")
            expected_clock = {"basis": "experiment_relative", "unit": "s", **particles.to_dict()["clock"]}
            if data["metadata"]["clock"] != expected_clock:
                raise ValueError("native batch result has a different experiment clock")
            if common is not None and common != data["metadata"]:
                raise ValueError("native species batches disagree on frame, clock or lineage basis")
            common = data["metadata"]
            batches.append(data)
            _write(work / "native_stages.json", receipts)
        results = [TraceResult(**{key: batch[key] for key in ("initial_states", "terminal_states", "events", "trajectories", "execution_status", "data_integrity")})
                   for batch in batches]
        if all(result.execution_status == "succeeded" and result.data_integrity.get("status") == "complete" for result in results):
            merged = merge_mass_scan(results)
        else:
            from .reference_tracing import _merged
            merged = _merged(batches)
        write_particle_data(work, merged, metadata={"schema_version": 2, **common})
        data = read_particle_data(work)
        if data["execution_status"] == "succeeded" and data["data_integrity"].get("status") == "complete":
            _write(work / "analysis.json", analyze_mass_scan(data))
        else:
            _write(work / "analysis.json", {"status": "not_applicable", "reason": "incomplete_or_failed_tracking"})
        summary = summarize_particle_data(data)
        _write(work / "summary.json", summary)
        from .native_evidence import summarize_native_workers
        worker_evidence = summarize_native_workers(work)
        # Publication moves this work tree. Keep its sealed evidence locations
        # relative to the published run, rather than pointing at vanished work.
        for control in worker_evidence["controls"]:
            for record in control["records"].values():
                record["path"] = Path(record["path"]).relative_to(work).as_posix()
        _write(work / "native_worker_evidence.json", worker_evidence)
        _write(work / "provenance.json", {"schema_version": 1, "execution_owner": "native_tracing",
            "author_sha256": file_sha256(work / "author.toml"), "recipe_id": recipe["recipe_id"],
            "repository_source": {"sha": source_revision, "status": "declared" if source_revision else "unavailable"},
            "stages": receipts, "stage_productions": calls,
            "raw_asset_owner": "existing_native_execution_owner", "implementation": implementation})
        store.publish_run(work, run_id=run_id, execution_status=data["execution_status"],
                          provenance_assets=[input_id, *(receipt["asset_id"] for receipt in receipts.values() if receipt["asset_id"])])
