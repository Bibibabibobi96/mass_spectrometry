"""Public SIMION operations over complete domain objects."""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform.assembly.model import Assembly
from msplatform.contracts.machine_contracts import ContractError
from msplatform.results import artifacts as artifact_reader
from .compiler import CompiledSimionGeometry, compile_geometry as compile_simion_geometry
from .rf_compiler import compile_independent_multipoles
from .oa_compiler import compile_independent_accelerators

if TYPE_CHECKING:
    from msplatform.assembly.handoff import HandoffResult
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.execution.context import ExecutionContext
    from msplatform.ion_release.authoring import ReleaseRealization


def build_geometry(compiled: CompiledSimionGeometry, *, context: ExecutionContext) -> OpenedArtifact:
    """Materialize actual unsolved geometry through the one public execution owner.

    Engineering limits and retention are explicit in context.stage_policy_path.
    Native reopen/relocation qualifications remain separate recorded facts.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.simion.geometry_execution import execute_geometry
    from msplatform.backends.simion.native_plans import plan_geometry_build
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.backends.simion import native_completion
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(compiled, CompiledSimionGeometry):
        raise ContractError("build_geometry requires compiled SIMION geometry")
    if context is None or "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("build_geometry requires an explicit available SIMION executable")
    stage, authority = read_stage_policy(context, "build_geometry", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime
                and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION geometry runtime only accepts explicit boolean simion_allow_asynchronous_io")
    snapshot = CompiledSimionGeometry(**asdict(compiled))
    count = (len(snapshot.frontend_gems) if snapshot.frontend_geometry.get("role") in {"simion_independent_rf_geometry", "simion_independent_oa_geometry", "simion_rf_ip_geometry", "simion_oa_mr_complete_geometry", "simion_ip_mr_complete_geometry", "simion_rf_oa_geometry"}
             else 4 + int("entrance_refinement" in snapshot.frontend_geometry["numerical_domains"]))
    seed = file_record(structural_seed_path(count), "required_evidence")
    # Only derive path-independent action names/relative file lengths here.
    # The owner alone creates the actual run and its existing ASCII projection.
    planning_root = context.execution_root / "geometry-plan"
    plan = plan_geometry_build(snapshot, run_directory=planning_root, seed_record=seed,
        native_path_resource=planning_root / "inputs/native_sources/native_run_path.lua")
    ids = tuple(row["operation_id"] for row in plan.operations)
    source = file_record(Path(execute_geometry.__code__.co_filename).resolve(), "required_evidence")
    result = run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="geometry_only", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__simion__geometry-" + uuid4().hex[:12],
        payload=dict(action="build_geometry", compiled_geometry=asdict(snapshot), stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[authority], retention=stage["artifact_retention"],
        expected_operation_ids=ids,
        operation_dependencies={name: [ids[index-1]] for index, name in enumerate(ids) if index},
        action=partial(execute_geometry, compiled=snapshot, seed_record=seed, limits=stage["limits"],
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
        action_record=source,
        expected_relative_paths=[str(Path(path).relative_to(planning_root)) for path in plan.declared_outputs],
        use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "geometry"}, expected_kind="geometry_artifact")


def prepare_model(geometry: OpenedArtifact | Mapping[str, Any], *, drive: Mapping[str, Any],
                  physics: Mapping[str, Any], context: ExecutionContext) -> OpenedArtifact:
    """Publish a driven, unsolved model from explicit geometry and clock authority.

    Scientific group defaults are expanded from the same providers. The clock
    authority is an explicit versioned example resource or contract record plus
    data_root; it is never discovered from context or a prior run.
    """
    from datetime import datetime
    from functools import partial
    import json
    from uuid import uuid4
    from msplatform.backends.simion.compiler import CompiledSimionGeometry
    from msplatform.backends.simion.model import project_resolved_drive, compile_prepared_model
    from msplatform.backends.simion.model_execution import execute_model
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.backends.simion import native_completion
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.execution.clock_authority import validate_clock_authority
    from msplatform.io.manifest_records import file_record, verify_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(drive, Mapping):
        raise ContractError("model drive must be an explicit mapping")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("prepare_model requires an explicit available SIMION executable")
    source = artifact_reader.open_artifact(geometry.reference if isinstance(geometry, OpenedArtifact) else geometry,
                           expected_kind="geometry_artifact")
    stage, policy_record = read_stage_policy(context, "prepare_model", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION model runtime only accepts explicit boolean simion_allow_asynchronous_io")
    values = json.loads(source.data_path("compiled_geometry").read_text(encoding="utf-8-sig"))
    values["downstream_specs"] = tuple(values["downstream_specs"])
    compiled = CompiledSimionGeometry(**values)
    if compiled.frontend_geometry.get("role") in {"simion_rf_oa_geometry", "simion_ip_mr_complete_geometry"}:
        raise ContractError("joint geometry has no supported prepared model yet")
    joint_oa_mr = compiled.frontend_geometry.get("role") == "simion_oa_mr_complete_geometry"
    joint_ip = compiled.frontend_geometry.get("role") == "simion_rf_ip_geometry"
    independent_rf = compiled.frontend_geometry.get("role") == "simion_independent_rf_geometry"
    independent_oa = compiled.frontend_geometry.get("role") == "simion_independent_oa_geometry"
    independent_component = independent_rf or independent_oa or joint_ip or joint_oa_mr
    required = {"clock", "clock_authority"} | ({"oa_groups", "mr_authority", "pulse"} if joint_oa_mr else set()) | ({"groups"} if independent_oa or joint_ip else set()) | ({"ip_schedule"} if joint_ip else set()) | (set() if independent_component else {"pulse"})
    if (not required <= drive.keys() or set(drive) - required - (set() if joint_oa_mr else {"groups"}) - ({"pulse"} if independent_oa else set())
            or not isinstance(drive["clock"], Mapping)
            or set(drive["clock"]) != {"phase_reference_instrument_time_us"}):
        raise ContractError("model drive requires its actual clock/groups and declared pulse contract")
    authority = drive["clock_authority"]
    if isinstance(authority, Mapping) and set(authority) == {"example_resource"}:
        from importlib.resources import files
        if authority["example_resource"] != "instrument_clock_authority_v1.json":
            raise ContractError("unknown versioned example clock authority")
        data_root = Path(str(files("msplatform.examples")))
        contract_record = file_record(data_root / authority["example_resource"], "required_evidence")
    elif isinstance(authority, Mapping) and set(authority) == {"contract", "data_root"}:
        data_root = Path(authority["data_root"])
        contract_record = dict(authority["contract"])
        if not data_root.is_absolute():
            raise ContractError("clock authority data_root must be explicit and absolute")
    else:
        raise ContractError("clock authority requires example_resource or explicit contract record and data_root")
    verify_record("model clock authority", contract_record)
    contract_path = Path(contract_record["path"])
    validation = validate_clock_authority(contract_path, data_root)
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    epoch_record = file_record((data_root / contract["authority"]["path"]).resolve(), "required_evidence")
    clock_reference = dict(contract=contract_record, authority=epoch_record, data_root=str(data_root))
    if joint_ip:
        epoch = json.loads((data_root / contract["authority"]["path"]).read_text(encoding="utf-8-sig"))
        if type(epoch.get("instrument_time_us")) not in (int, float) or epoch["instrument_time_us"] != 0:
            raise ContractError("RF–IP requires the existing zero instrument epoch")
    selected = compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]
    components = {name: compiled.components_resolved[name] for name in selected}
    clock = dict(clock_epoch_id=validation["clock_epoch_id"], authority_sha256=validation["authority_sha256"],
                 **dict(drive["clock"]))
    if joint_oa_mr:
        expanded = dict(oa_groups=copy.deepcopy(drive["oa_groups"]),
            mr_authority=copy.deepcopy(drive["mr_authority"]), pulse=copy.deepcopy(drive["pulse"]), clock=clock)
    elif joint_ip:
        expanded = dict(groups=copy.deepcopy(drive["groups"]), clock=clock,
            ip_schedule=copy.deepcopy(drive["ip_schedule"]))
    elif independent_oa:
        expanded = dict(groups=copy.deepcopy(drive["groups"]), clock=clock,
            **({"pulse": copy.deepcopy(drive["pulse"])} if "pulse" in drive else {}))
    else:
        expanded = project_resolved_drive(compiled, components, clock=clock,
            **({} if independent_rf else dict(pulse=drive["pulse"])))
    if "groups" in drive:
        expanded["groups"] = copy.deepcopy(drive["groups"])
    model = compile_prepared_model(compiled, components, drive=expanded, physics=physics)
    seed = file_record(structural_seed_path(len(compiled.frontend_gems) if independent_component else 4 + int(
        "entrance_refinement" in compiled.frontend_geometry["numerical_domains"])), "required_evidence")
    ids = ("materialize_geometry", "build_model", "verify_model")
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="prepared_model", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__simion__model-" + uuid4().hex[:12],
        payload=dict(action="prepare_model", geometry=source.reference, model=model.document,
                     clock_authority=clock_reference, stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record, contract_record, epoch_record], retention=stage["artifact_retention"],
        expected_operation_ids=ids,
        operation_dependencies={name: [ids[index-1]] for index, name in enumerate(ids) if index},
        action=partial(execute_model, model=model, geometry_reference=source.reference, seed_record=seed,
            limits=stage["limits"], clock_authority_reference=clock_reference,
            materialize_geometry=partial(materialize_payloads, limits=stage["limits"]),
            materializer_record=file_record(Path(materialize_payloads.__code__.co_filename).resolve(), "required_evidence"),
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
        action_record=file_record(Path(execute_model.__code__.co_filename).resolve(), "required_evidence"),
        source_references=[{"manifest_record": source.reference["manifest"]}],
        use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "model"}, expected_kind="prepared_model")


def solve_fields(model: OpenedArtifact | Mapping[str, Any], *, numerics: Mapping[str, Any],
                 context: ExecutionContext,
                 reuse_fields: OpenedArtifact | Mapping[str, Any] | None = None) -> OpenedArtifact:
    """Explicitly solve an unsolved model, without source sampling or flight.

    Optional reuse names one published field product, never a latest lookup.
    The backend validates the actual spatial operator before reusing downstream
    data; the new field product retains the current model's drive and clock.
    """
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.simion.field_closure import load_field_model
    from msplatform.backends.simion.field_execution import execute_fields, plan_fields_execution
    from msplatform.backends.simion import native_completion
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(numerics, Mapping):
        raise ContractError("solve_fields requires explicit field numerics")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("solve_fields requires an explicit available SIMION executable")
    stage, policy_record = read_stage_policy(context, "solve_fields", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION field runtime only accepts explicit boolean simion_allow_asynchronous_io")
    source = load_field_model(model.reference if isinstance(model, OpenedArtifact) else model)
    selected_numerics = copy.deepcopy(dict(numerics))
    reuse_reference = None
    references = [{"manifest_record": source.artifact.reference["manifest"]}]
    if reuse_fields is not None:
        reused = artifact_reader.open_artifact(reuse_fields.reference if isinstance(reuse_fields, OpenedArtifact) else reuse_fields,
                               expected_kind="field_bundle")
        reuse_reference = reused.reference
        references.append({"manifest_record": reuse_reference["manifest"]})
        if reused.metadata.get("field_representation") in {"producer_owned_rf_fractional_family", "producer_owned_oa_fractional_family"}:
            original = reused.metadata.get("family_producer_reference", reused.reference)
            references.append({"manifest_record": original["manifest"]})
    graph = plan_fields_execution(source.model, numerics=selected_numerics, reuse_fields_reference=reuse_reference)
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="fields_only", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__simion__fields-" + uuid4().hex[:12],
        payload=dict(action="solve_fields", model=source.artifact.reference, numerics=selected_numerics,
                     reuse_fields=reuse_reference, stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record], retention=stage["artifact_retention"],
        expected_operation_ids=tuple(graph["expected_operation_ids"]),
        operation_dependencies=graph["operation_dependencies"],
        action=partial(execute_fields, model_reference=source.artifact.reference, numerics=selected_numerics,
            limits=stage["limits"], materialize_geometry=partial(materialize_payloads, limits=stage["limits"]),
            materializer_record=file_record(Path(materialize_payloads.__code__.co_filename).resolve(), "required_evidence"),
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io"), reuse_fields_reference=reuse_reference),
        action_record=file_record(Path(execute_fields.__code__.co_filename).resolve(), "required_evidence"),
        source_references=references, use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "fields"}, expected_kind="field_bundle")


def track(fields: OpenedArtifact | Mapping[str, Any],
          particles: ReleaseRealization | HandoffResult | Mapping[str, Any], *,
          propagation: Mapping[str, Any], observations: Mapping[str, Any],
          numerics: Mapping[str, Any], context: ExecutionContext,
          source_reference: OpenedArtifact | Mapping[str, Any] | None = None,
          unit_size: int | None = None, recovery_reference: Mapping[str, Any] | None = None,
          dispatch_profiles: Sequence[Mapping[str, Any]] = (),
          birth_source_authority: Mapping[str, Any] | None = None, hs1_request: Mapping[str, Any] | None = None,
          scalar_field_basis: Mapping[str, Any] | None = None) -> OpenedArtifact:
    """Publish an explicit fixed-field flight, preserving its original cohort/clock.

    A release realization starts at birth; a HandoffResult requires its published
    trajectory producer. The backend verifies the actual observed source before
    relaunch. Zero handoff publishes full mother facts without launching tools.
    unit_size fixes ordinal replay boundaries without changing original IDs or
    the full mother. recovery_reference is one explicit predecessor manifest
    file record: complete units are verified and reused, incomplete units fully
    replayed by the existing dispatcher. Opening a field never solves it.

    Complete RF-IP tracking requires an explicit hs1_request: typed IP-local
    bath_domain and outer GasFieldSpec, original vendor_record, and numerics
    containing seed and hs1_steps_per_mfp. The selected IP pose maps gas queries
    and velocities; the outer field must cover the complete parent. This route
    requires sequential grouped=0 and never restarts particles at gas boundaries.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.assembly.handoff import HandoffResult
    from msplatform.backends.simion.artifacts import CompiledPreparedModel
    from msplatform.backends.simion.model import require_prepared_model
    from msplatform.backends.simion.tracking_execution import execute_tracking, plan_tracking_execution, validate_birth_authority
    from msplatform.backends.simion.tracking_units import inspect_tracking_recovery, tracking_applicability
    from msplatform.backends.simion import native_completion
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.ion_release.authoring import ReleaseRealization

    source = fields if isinstance(fields, OpenedArtifact) else artifact_reader.open_artifact(fields, expected_kind="field_bundle")
    meta = source.metadata
    if (source.kind != "field_bundle" or meta.get("backend") != "simion"
            or meta.get("field_status") != "available" or meta.get("source_status") != "not_requested"):
        raise ContractError("track requires a published source-independent SIMION FieldBundle")
    model = CompiledPreparedModel(source.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    document = require_prepared_model(model)
    if meta.get("model_identity_sha256") != document["model_identity_sha256"] or meta.get("clock") != document["drive"]["clock"]:
        raise ContractError("tracking field model/clock identity differs")
    packet = particles.to_dict() if isinstance(particles, ReleaseRealization) else copy.deepcopy(particles)
    birth_authority = None if birth_source_authority is None else validate_birth_authority(birth_source_authority, packet)
    clocks = {name: dict(source.data_records[name], path=str(source.data_path(name)))
              for name in ("clock_authority", "instrument_epoch")}
    if (not isinstance(dispatch_profiles, Sequence) or isinstance(dispatch_profiles, (str, bytes))
            or any(not isinstance(profile, Mapping) for profile in dispatch_profiles)):
        raise ContractError("tracking dispatch_profiles must be an explicit sequence of resource profiles")
    profiles = tuple(copy.deepcopy(dict(profile)) for profile in dispatch_profiles)
    recovery = None
    if recovery_reference is not None:
        if (not isinstance(recovery_reference, Mapping)
                or not isinstance(recovery_reference.get("path"), str)
                or not Path(recovery_reference["path"]).is_absolute()):
            raise ContractError("tracking recovery requires an explicit absolute predecessor manifest file record")
        recovery = copy.deepcopy(dict(recovery_reference))
    planning = dict(particles=packet, clock_records=clocks, propagation=propagation,
                    observations=observations, numerics=numerics, unit_size=unit_size,
                    field_manifest_record=source.reference["manifest"],
                    **({'birth_source_authority': birth_authority} if birth_authority is not None else {}), hs1_request=hs1_request)
    graph = plan_tracking_execution(model, **planning)
    if scalar_field_basis is not None:
        if isinstance(packet, HandoffResult) or hs1_request is not None:
            raise ContractError('scalar basis requires an original-birth SFI flight')
        from msplatform.backends.simion.tracking_execution import _resolve_scalar_basis
        graph['scalar_field_basis'] = _resolve_scalar_basis(source, model, graph, scalar_field_basis)
    planned_applicability = tracking_applicability(graph) if hs1_request is not None or scalar_field_basis is not None else None
    if recovery is not None:
        inspected = inspect_tracking_recovery(graph, recovery)
        graph = plan_tracking_execution(model, **planning, reused_unit_keys=inspected["reused_unit_keys"])
        if scalar_field_basis is not None:
            graph['scalar_field_basis'] = _resolve_scalar_basis(source, model, graph, scalar_field_basis)
    predecessor = None
    references = [{"manifest_record": source.reference["manifest"]}]
    if birth_authority is not None:
        references.append({"manifest_record": birth_authority['manifest']})
    if scalar_field_basis is not None:
        admitted = graph['scalar_field_basis']
        references.append({'manifest_record': admitted['geometry_reference']['manifest']})
        for entry in admitted['bases'].values():
            references.append({'manifest_record': entry['reference']['manifest']})
            references.append({'manifest_record': entry['field_solution_reference']['manifest']})
    if meta.get('field_representation') in {'producer_owned_rf_fractional_family','producer_owned_oa_fractional_family','producer_owned_rf_ip_fractional_family'}:
        original=meta.get('family_producer_reference',source.reference)
        references.append({'manifest_record':original['manifest']})
    if recovery is not None:
        references.append({"manifest_record": recovery})
    if isinstance(packet, HandoffResult):
        if source_reference is None:
            raise ContractError("state relaunch requires its published trajectory source reference")
        predecessor = (source_reference if isinstance(source_reference, OpenedArtifact)
                       else artifact_reader.open_artifact(source_reference, expected_kind="trajectory_result"))
        if predecessor.kind != "trajectory_result":
            raise ContractError("handoff producer must be a published trajectory result")
        references.append({"manifest_record": predecessor.reference["manifest"]})
    elif source_reference is not None:
        raise ContractError("birth realization cannot claim a handoff producer")
    if graph["native_requested"] and ("simion" not in context.tools or not context.tools["simion"].is_file()):
        raise ContractError("nonempty tracking requires an explicit available SIMION executable")
    stage, policy_record = read_stage_policy(context, "track", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION tracking runtime only accepts explicit boolean simion_allow_asynchronous_io")
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="tracking", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__simion__track-" + uuid4().hex[:12],
        payload=dict(action="track", fields=source.reference,
            particles=asdict(packet) if isinstance(packet, HandoffResult) else packet,
            propagation=copy.deepcopy(dict(propagation)), observations=copy.deepcopy(dict(observations)),
            numerics=copy.deepcopy(dict(numerics)), source_reference=predecessor.reference if predecessor else None,
            unit_size=unit_size, recovery_reference=recovery, dispatch_profiles=copy.deepcopy(profiles),
            **({'scalar_field_basis': graph['scalar_field_basis']} if scalar_field_basis is not None else {}),
            **({'birth_source_authority': birth_authority} if birth_authority is not None else {}),
            **({'hs1_identity': graph['hs1_identity'], 'hs1_vendor_record': dict(hs1_request['vendor_record'])} if hs1_request is not None else {}),
            stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record], retention=stage["artifact_retention"],
        expected_operation_ids=tuple(graph["expected_operation_ids"]),
        operation_dependencies=graph["operation_dependencies"],
        action=partial(execute_tracking, fields_reference=source, particles=packet,
            propagation=graph["propagation"], observations=graph["observations"], numerics=graph["numerics"],
            limits=stage["limits"], source_reference=predecessor.reference if predecessor else None,
            unit_size=unit_size, recovery_reference=recovery, dispatch_profiles=profiles,
            **({'birth_source_authority': birth_authority} if birth_authority is not None else {}),
            hs1_request=hs1_request, expected_tracking_applicability=planned_applicability,
            **({'scalar_field_basis': scalar_field_basis, 'expected_scalar_basis': graph['scalar_field_basis']} if scalar_field_basis is not None else {}),
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
        action_record=file_record(Path(execute_tracking.__code__.co_filename).resolve(), "required_evidence"),
        source_references=references, use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "trajectory"}, expected_kind="trajectory_result")


def compile_geometry(assembly: Assembly, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile native geometry specifications only; no source, writes, solve or Fly."""
    if not isinstance(assembly, Assembly):
        raise ContractError("SIMION geometry compilation requires an explicitly assembled design")
    plan = assembly.composition_plan
    selected = plan["scope"]["instance_ids"]
    projects = [plan["components"][name]["project_id"] for name in selected]
    if len(projects) == 2 and set(projects) == {"rf_multipole_ion_optics", "dual_pressure_rectilinear_ion_processor"}:
        from .ip_compiler import compile_ip_assembly_geometry
        return compile_ip_assembly_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if len(projects) == 2 and set(projects) == {"rf_multipole_ion_optics", "orthogonal_accelerator"}:
        from .rf_oa_compiler import compile_rf_oa_geometry
        return compile_rf_oa_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if len(projects) == 2 and set(projects) == {"orthogonal_accelerator", "parallel_mirror_dual_stripe_mr_tof"}:
        from .mr_compiler import compile_complete_mr_geometry
        return compile_complete_mr_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if (len(projects) in (2, 3) and set(projects) in (
            {"dual_pressure_rectilinear_ion_processor", "parallel_mirror_dual_stripe_mr_tof"},
            {"rf_multipole_ion_optics", "dual_pressure_rectilinear_ion_processor", "parallel_mirror_dual_stripe_mr_tof"})):
        from .mr_compiler import compile_complete_mr_geometry
        return compile_complete_mr_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if selected and all(plan["components"][name]["project_id"] == "rf_multipole_ion_optics" for name in selected):
        return compile_independent_multipoles(
            dict(composition_plan=plan, components_resolved=assembly.components_resolved),
            numerics=copy.deepcopy(dict(numerics)),
        )
    if selected and all(plan["components"][name]["project_id"] == "orthogonal_accelerator" for name in selected):
        return compile_independent_accelerators(
            dict(composition_plan=plan, components_resolved={name:assembly.components_resolved[name] for name in selected}),
            numerics=copy.deepcopy(dict(numerics)))
    compiled = compile_simion_geometry(
        {"composition_plan": copy.deepcopy(dict(assembly.composition_plan)),
         "components_resolved": {name: copy.deepcopy(assembly.components_resolved[name]) for name in selected}},
        numerics=copy.deepcopy(dict(numerics)),
    )
    return replace(compiled, components_resolved=assembly.components_resolved)
