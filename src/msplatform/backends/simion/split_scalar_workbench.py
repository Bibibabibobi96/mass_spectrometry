"""One explicit five-slot world carrier over an authenticated split scalar basis."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifacts import CompiledPreparedModel
from .model import model_geometry, require_prepared_model

WORLD_SLOTS = {"background": 1, "flight_tube": 2, "reflectron": 3, "accelerator": 4, "detector": 5}
WORLD_REPRESENTATION = "split_scalar_world_with_collision_geometry"


def project_split_scalar_world(model: CompiledPreparedModel, binding: Mapping[str, Any], *,
                               carriers: Mapping[str, Mapping[str, Any]], background_path: Path) -> dict:
    """Project authenticated scalar-grid and original carriers into native slots.

    The caller authenticates the binding and file records against their owners.
    No PA is opened or created here; an explicit native build/reopen is required.
    """
    document = require_prepared_model(model)
    compiled = model_geometry(model, downstream_drive=True)
    geometry = compiled.frontend_geometry
    if geometry.get("role") != "simion_split_oa_tof_geometry":
        raise ValueError("split scalar world requires split OA–TOF geometry")
    if (not isinstance(binding, Mapping) or binding.get("role") != "split_off_on_scalar_binding"
            or binding.get("model_identity_sha256") != document["model_identity_sha256"]
            or binding.get("clock") != document["drive"]["clock"]
            or binding.get("pulse") != document["drive"]["pulse"]):
        raise ValueError("split scalar world binding differs from the authenticated model")
    bases = binding.get("bases")
    if not isinstance(bases, Mapping) or set(bases) != {"off", "on"} or bases["off"].get("grid") != bases["on"].get("grid"):
        raise ValueError("split scalar OFF/ON world grids differ")
    grid = copy.deepcopy(bases["off"]["grid"])
    dims, pitch, origin = (grid.get(key) for key in ("dimensions", "pitch_mm", "origin_mm"))
    if (not all(isinstance(value, list) and len(value) == 3 for value in (dims, pitch, origin))
            or any(type(value) is not int or value < 3 for value in dims)
            or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in pitch)
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in origin)):
        raise ValueError("split scalar world requires a finite complete grid")
    plan = geometry["composition_plan"]
    if grid.get("frame_id") != plan["assembly_frame_id"]:
        raise ValueError("scalar grid and assembly frame differ")
    oa = geometry["oa_instance_id"]
    pose = next(row["transform"] for row in plan["recipe"]["instances"] if row["instance_id"] == oa)
    if pose["rotation"] != [[1,0,0],[0,1,0],[0,0,1]] or pose["translation_mm"] != [0,0,0]:
        raise ValueError("split scalar world currently requires identical assembly and OA native coordinates")
    if not isinstance(carriers, Mapping) or set(carriers) != set(WORLD_SLOTS) - {"background"}:
        raise ValueError("four original collision carrier roles are required")
    background = Path(background_path)
    if not background.is_absolute() or not str(background).isascii() or background.suffix.lower() != ".pa":
        raise ValueError("world background requires a fresh absolute ASCII PA path")
    slots = [dict(role="background", instance_index=1, priority_number=1, path=str(background),
        grid=dict(zip(("nx","ny","nz"),dims,strict=True), **dict(zip(("dx_mm","dy_mm","dz_mm"),pitch,strict=True))),
        placement=dict(x_mm=origin[0],y_mm=origin[1],z_mm=origin[2],az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.))]
    specs = {row["role"]: row for row in compiled.downstream_specs}
    for role in ("flight_tube", "reflectron", "accelerator", "detector"):
        record = carriers[role]
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise ValueError("original collision carrier requires an explicit record")
        path = Path(record["path"])
        if not path.is_absolute() or not str(path).isascii() or type(record.get("bytes")) is not int or record["bytes"] <= 0:
            raise ValueError("original collision carrier identity differs")
        digest = record.get("sha256")
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            raise ValueError("original collision carrier requires SHA-256")
        if role == "accelerator":
            dom = geometry["numerical_domains"]["parent"]
            native_grid = dict(dom["dimensions"], **{f"d{axis}_mm": dom["cell_mm_xyz"][axis] for axis in "xyz"})
            position = dom["instance_origin_mm"]
            place = dict(x_mm=position["x"],y_mm=position["y"],z_mm=position["z"],az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.)
        else:
            spec = specs[role]; row = spec["native_instance"]; variables = spec["template_variables"]
            cells = ([variables["mmgu_xy"],variables["mmgu_xy"],variables["mmgu_z"]] if role=="detector" else
                     [variables["mmgu_axial"],variables["mmgu_radial"],variables["mmgu_radial"]])
            native_grid = dict(**{k:row[k] for k in ("nx","ny","nz")}, **dict(zip(("dx_mm","dy_mm","dz_mm"),cells,strict=True)))
            place = dict(x_mm=row["x_mm"],y_mm=row["y_mm"],z_mm=row["z_mm"],az_deg=row["az_deg"],el_deg=0.,rt_deg=0.,scale=1.)
        slot = WORLD_SLOTS[role]
        slots.append(dict(role=role,instance_index=slot,priority_number=slot,path=str(path),grid=native_grid,placement=place))
    probes = [[origin[k] + index[k]*pitch[k] for k in range(3)]
              for index in ((1,1,1),(dims[0]-2,1,1),(1,dims[1]-2,1),(1,1,dims[2]-2),
                            (dims[0]-2,dims[1]-2,dims[2]-2))]
    return dict(schema_version=1, role="split_scalar_world_projection", frame_id=grid["frame_id"],
        model_identity_sha256=document["model_identity_sha256"], clock=copy.deepcopy(document["drive"]["clock"]),
        grid=grid, slots=slots, role_slots=dict(WORLD_SLOTS), background_probes=probes,
        scalar_binding=copy.deepcopy(dict(binding)), representation=WORLD_REPRESENTATION,
        qualification="not_granted")


def _admit_world(fields, selection):
    """Recheck the real field owner, model, scalar sources and carrier records."""
    import json
    from msplatform.results.artifacts import open_artifact
    from .field_closure import data_record, require_downstream_reuse
    from .grounded_runtime import verified_ground_origin
    from .split_scalar_binding import resolve_split_scalar_basis
    source = open_artifact(fields, expected_kind="field_bundle")
    meta = source.metadata
    if meta.get("backend") != "simion" or meta.get("field_status") != "available" or meta.get("source_status") != "not_requested":
        raise ValueError("split scalar world requires a published source-independent SIMION field bundle")
    verified_ground_origin(source)
    model = CompiledPreparedModel(source.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    document = require_prepared_model(model)
    if meta.get("model_identity_sha256") != document["model_identity_sha256"] or meta.get("clock") != document["drive"]["clock"]:
        raise ValueError("collision field model or clock differs")
    if not isinstance(selection, Mapping) or not {"geometry_artifact", "samples"} <= set(selection) or set(selection) - {"geometry_artifact", "samples", "refinement_windows"}:
        raise ValueError("split world requires explicit COMSOL geometry and OFF/ON samples")
    binding = resolve_split_scalar_basis(model=model, geometry_artifact=selection["geometry_artifact"],
        samples=selection["samples"], refinement_windows=selection.get("refinement_windows"))
    _, downstream = require_downstream_reuse(source, meta["downstream_identity"])
    members = meta["frontend_members"]
    if set(members) != {"parent"} or "carrier_off" not in members["parent"]:
        raise ValueError("split world requires the original single parent carrier")
    carriers = {role: downstream[role]["carrier_record"] for role in ("flight_tube", "reflectron", "detector")}
    carriers["accelerator"] = data_record(source, members["parent"]["carrier_off"]["data_key"])
    design = json.loads(source.data_path("field_design").read_text(encoding="utf-8-sig"))
    bank = json.loads(source.data_path("field_bank").read_text(encoding="utf-8-sig"))
    from .field_bank import field_bank
    if bank != field_bank(design, [row["domain_id"] for row in design["domains"]]):
        raise ValueError("collision source field bank differs from its design")
    return source, model, binding, carriers


def _basis_references(binding):
    """Select only the exact manifest authorities named by the verified basis."""
    result = [(binding["geometry_reference"], "geometry_artifact")]
    for value in binding["bases"].values():
        for level in (value, *value.get("refinement_windows", [])):
            result.append((level["reference"], "scalar_field_samples"))
            result.append((level["field_solution_reference"], "field_solution"))
            if level.get("original_samples_reference") is not None:
                result.append((level["original_samples_reference"], "scalar_field_samples"))
    unique = {}
    for reference, kind in result:
        key = (str(reference["manifest"]["path"]), reference["product_id"], kind)
        if key in unique and unique[key][0] != reference:
            raise ValueError("conflicting scalar source reference")
        unique[key] = (reference, kind)
    return list(unique.values())


def prepare_split_scalar_world(fields, *, scalar_field_basis, context):
    """Publish a verified five-slot collision workbench without Refine or Fly."""
    from contextlib import ExitStack
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.execution.native_source_guard import guard_native_source
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record
    from msplatform.io.file_identity import guarded_file_identity
    from msplatform.results.artifacts import OpenedArtifact, open_artifact
    from . import native_completion
    from .native_plans import plan_split_scalar_world_build
    from .resources import structural_seed_path
    if context is None or "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ValueError("split scalar world requires an explicit available SIMION executable")
    stage, policy = read_stage_policy(context, "prepare_split_scalar_world", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if set(runtime) - {"simion_allow_asynchronous_io"} or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool):
        raise ValueError("split scalar world runtime accepts only explicit asynchronous IO mode")
    reference = fields.reference if isinstance(fields, OpenedArtifact) else copy.deepcopy(fields)
    root = context.workspace / "artifacts"
    with ExitStack() as stack:
        guarded = stack.enter_context(guard_native_source(reference, expected_kind="field_bundle", expected_artifact_root=root))
        if guarded.metadata.get("ground_representation") != "analytic_zero_on_native_geometry":
            raise ValueError("split scalar world requires derived analytic ground")
        origin_reference = guarded.metadata.get("ground_source_reference")
        if not isinstance(origin_reference, Mapping):
            raise ValueError("split scalar world requires its original ground producer")
        stack.enter_context(guard_native_source(origin_reference, expected_kind="field_bundle", expected_artifact_root=root))
        # Scalar product and geometry guards precede scalar admission.  Their
        # own referenced solutions are acquired and rechecked immediately after.
        initial = [(scalar_field_basis["geometry_artifact"], "geometry_artifact")]
        initial += [(value, "scalar_field_samples") for value in scalar_field_basis["samples"].values()]
        for ref, kind in initial:
            ref = ref.reference if isinstance(ref, OpenedArtifact) else ref
            stack.enter_context(guard_native_source(ref, expected_kind=kind, expected_artifact_root=root))
        source, model, binding, carriers = _admit_world(reference, scalar_field_basis)
        request = binding["geometry_execution_request"]
        stack.enter_context(guarded_file_identity(request["path"], expected_bytes=request["bytes"],
                                                   expected_sha256=request["sha256"]))
        refs = _basis_references(binding)
        for ref, kind in refs:
            stack.enter_context(guard_native_source(ref, expected_kind=kind, expected_artifact_root=root))
        source, model, binding, carriers = _admit_world(reference, scalar_field_basis)
        planning = context.execution_root / "split-scalar-world-plan"
        projection = project_split_scalar_world(model, binding, carriers=carriers,
            background_path=planning / "simion/world/background.pa")
        seed = file_record(structural_seed_path(5), "required_evidence")
        plan = plan_split_scalar_world_build(projection, run_directory=planning, seed_record=seed,
            native_path_resource=planning / "inputs/native_sources/native_run_path.lua")
        ids = tuple(row["operation_id"] for row in plan.operations)
        sources = [dict(manifest_record=reference["manifest"]), dict(manifest_record=origin_reference["manifest"])] + [dict(manifest_record=ref["manifest"]) for ref, _ in refs]
        action_record = file_record(Path(execute_split_scalar_world.__code__.co_filename).resolve(), "required_evidence")
        result = run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="fields_only", software=["SIMION"]),
            run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__simion__world-" + uuid4().hex[:12],
            payload=dict(action="prepare_split_scalar_world", fields=source.reference,
                         scalar_field_basis=copy.deepcopy(dict(scalar_field_basis)), stage_policy=stage),
            committed_new_bytes=stage["limits"]["transient_run_directory_bytes"], commitment_inputs=[policy],
            retention=stage["artifact_retention"], expected_operation_ids=ids,
            operation_dependencies={name: [ids[index-1]] for index,name in enumerate(ids) if index},
            action=partial(execute_split_scalar_world, fields_reference=source.reference,
                scalar_field_basis=copy.deepcopy(dict(scalar_field_basis)), limits=stage["limits"],
                allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")), action_record=action_record,
            source_references=sources, use_short_execution_path=True, completion_api=lambda: native_completion)
        return open_artifact({"manifest": result["manifest"], "product_id": "fields"}, expected_kind="field_bundle")


def execute_split_scalar_world(session, *, fields_reference, scalar_field_basis, limits, allow_asynchronous_io=None):
    """Build and cold-reopen one owner-managed background plus collision IOB."""
    import json
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.resources import resource_path
    from msplatform.io.manifest_records import file_record
    from msplatform.results.artifacts import open_artifact
    from .field_closure import data_record
    from .model_execution import _protected_source
    from .native_io import apply_native_io_mode
    from .native_plans import plan_split_scalar_world_build
    from .resources import native_resource_path, structural_seed_path

    source, model, binding, carriers = _admit_world(fields_reference, scalar_field_basis)
    references = [(source.reference, "field_bundle"),
                  (source.metadata["ground_source_reference"], "field_bundle"), *_basis_references(binding)]
    immutable = {}
    for reference, kind in references:
        artifact = open_artifact(reference, expected_kind=kind)
        records = [dict(artifact.data_records[name], path=str(artifact.data_locations[name])) for name in artifact.data_records]
        records.append(dict(reference["manifest"], path=str(artifact.manifest_location)))
        _protected_source(session, reference["manifest"], required_paths=[row["path"] for row in records])
        for row in records:
            key = str(Path(row["path"]).resolve())
            if key in immutable and any(str(immutable[key][k]).upper() != str(row[k]).upper() for k in ("bytes", "sha256")):
                raise ValueError("split world source records conflict")
            immutable[key] = row
    geometry_request = dict(binding["geometry_execution_request"])
    _protected_source(session, binding["geometry_reference"]["manifest"], required_paths=[geometry_request["path"]])
    # All source owner protections are active; repeat the same authoritative admission.
    source, model, binding, carriers = _admit_world(fields_reference, scalar_field_basis)
    request_key = str(Path(geometry_request["path"]).resolve())
    if request_key in immutable and any(str(immutable[request_key][k]).upper() != str(geometry_request[k]).upper() for k in ("bytes", "sha256")):
        raise ValueError("split world geometry request identity conflicts")
    immutable[request_key] = geometry_request
    session.add_inputs(("world_source_" + str(i), row) for i,row in enumerate(immutable.values(), 1))
    root = session.run_dir
    projection = project_split_scalar_world(model, binding, carriers=carriers,
        background_path=root / "simion/world/background.pa")
    seed_source = file_record(structural_seed_path(5), "required_evidence")
    frozen = session.input_dir / "native_sources"
    native_path = frozen / "native_run_path.lua"
    plan = plan_split_scalar_world_build(projection, run_directory=root, seed_record=seed_source,
                                         native_path_resource=native_path,
                                         canonical_run_directory=session.artifact_run_dir)
    if tuple(row["operation_id"] for row in plan.operations) != session.expected_operation_ids:
        raise ValueError("split world operation graph differs")
    def owned(path, role):
        path = Path(path)
        actual = session.canonical_path(path)
        if not actual.is_relative_to(session.artifact_run_dir):
            raise ValueError("split world output escapes the managed owner")
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        session.declare_file(path, role)
        return path
    names = ("create_numerical_background.lua", "reopen_numerical_background.lua", "build_geometry_iob.lua", "iob_core.lua")
    resources = {name: native_resource_path(name) for name in names}
    resources["native_run_path.lua"] = resource_path("native_run_path.lua")
    frozen_records = {}
    for name, path in resources.items():
        destination = owned(frozen / name, "required_evidence")
        original = file_record(path, "required_evidence")
        copied = freeze_file(path, destination, retention_role="required_evidence")
        copied.pop("source_path", None)
        if any(original[k] != copied[k] for k in ("bytes", "sha256")):
            raise ValueError("frozen split world resource differs")
        session.add_input("world_resource_" + name, copied)
        frozen_records[name] = copied
    for path, content in plan.materializations.items():
        target = owned(path, "required_evidence")
        target.write_text(content, encoding="utf-8", newline="\n")
        record = file_record(session.canonical_path(target), "required_evidence")
        session.add_input("world_spec_" + target.name, record)
        immutable[str(session.canonical_path(target))] = record
    for row in plan.input_copies:
        target = owned(row["destination"], "required_evidence")
        copied = freeze_file(Path(row["source_record"]["path"]), target, retention_role="required_evidence")
        copied.pop("source_path", None)
        session.add_input("world_structural_seed", copied)
        immutable[str(session.canonical_path(target))] = copied
    for path in plan.declared_outputs:
        owned(path, "required_evidence" if str(path).endswith(".fly2") else "solver_native_binary")
    immutable.update({str(Path(row["path"]).resolve()): row for row in frozen_records.values()})
    produced = {}
    for index, operation in enumerate(plan.operations, 1):
        args = [str(frozen / Path(value).name) if Path(value).name in resources else value for value in operation["arguments"]]
        argv = apply_native_io_mode([str(session.context.tools["simion"]), *args], allow_asynchronous_io=allow_asynchronous_io)
        session.run_process(operation["operation_id"], executable=session.context.tools["simion"], arguments=argv[1:],
            role="SIMION", stage="prepare", limits=limits, immutable_input_records=list(immutable.values()))
        log = session.canonical_path(session.log_dir / f"operation_{index:04d}.stdout.log")
        if operation["success_marker"].encode("ascii") not in log.read_bytes():
            raise ValueError("split world native completion marker missing: " + operation["operation_id"])
        produced[operation["operation_id"]] = file_record(log, "required_evidence")
        for output in operation["outputs"]:
            actual = session.canonical_path(output)
            record = file_record(actual, "required_evidence" if actual.suffix == ".fly2" else "solver_native_binary")
            immutable[str(actual)] = record
    records = {name: data_record(source, name) for name in source.data_records}
    background = session.canonical_path(root / "simion/world/background.pa")
    iob = session.canonical_path(root / "simion/world/world.iob")
    records["background"] = file_record(background, "solver_native_binary")
    records["workbench"] = file_record(iob, "solver_native_binary")
    records["zero_particle_format_control"] = file_record(iob.with_suffix(".fly2"), "required_evidence")
    for name, record in produced.items():
        records["world_" + name + "_log"] = record
    binding_path = owned(session.input_dir / "world_binding.json", "required_evidence")
    published_projection = copy.deepcopy(projection)
    published_projection["slots"][0]["path"] = str(background)
    published_projection["collision_source_reference"] = source.reference
    binding_path.write_text(json.dumps(published_projection, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    records["world_binding"] = file_record(session.canonical_path(binding_path), "required_evidence")
    session.add_input("world_binding", records["world_binding"])
    metadata = copy.deepcopy(source.metadata)
    metadata.update(field_representation=WORLD_REPRESENTATION, collision_source_reference=source.reference,
                    world_slots=dict(WORLD_SLOTS), world_background_grid=copy.deepcopy(projection["grid"]),
                    background_native_cold_reopen=True, world_iob_cold_reopen_scope="current_owner_run_only",
                    world_iob_relocation_verified=False, background_priority_observed=True,
                    priority_evidence_scope="declared_exposed_background_points_only",
                    field_source="comsol_off_on_scalar_samples", refine_calls=0, fly_calls=0,
                    scientific_qualification="not_granted", scalar_coverage="not_qualified")
    outputs = [str(session.canonical_path(path)) for path in plan.declared_outputs]
    outputs.extend(record["path"] for record in produced.values())
    return dict(status="success", summary=metadata, output_paths=outputs, required_output_paths=outputs,
        retention_preserve_paths=[], manifest_extra_fields={"products": {"fields": dict(schema_version=1,
            kind="field_bundle", status="complete", metadata=metadata, data=records)}})
