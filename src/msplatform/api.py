"""Public staged operations over the platform's unique scientific implementations.

Importing this module does not discover tools, open models, or create a workspace.
Scientific defaults are visible in the versioned example, not inferred here.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform import assembly as assembly_domain
from msplatform import components as component_catalog
from msplatform.backends import simion as simion_backend
from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.clock import ClockIdentity

if TYPE_CHECKING:
    from msplatform.assembly.handoff import HandoffResult
    from msplatform.backends.simion.compiler import CompiledSimionGeometry
    from msplatform.execution.artifact_reader import ArtifactResolver, OpenedArtifact
    from msplatform.execution.context import ExecutionContext


@dataclass(frozen=True, init=False)
class ReleaseRealization:
    """Canonical birth rows and their complete, independently copied authoring facts."""

    _document: dict[str, Any]

    def __init__(self, request: Mapping[str, Any]):
        required = {"schema_version", "role", "release_spec", "clock", "instrument_origin_us",
                    "species_id", "source_component_id", "relative_weights"}
        if (not isinstance(request, Mapping) or not required <= request.keys()
                or set(request) - required - {"particle_ids"}
                or type(request["schema_version"]) is not int or request["schema_version"] != 1
                or request["role"] != "canonical_birth_source_request"):
            raise ContractError("release requires a version-1 canonical_birth_source_request")
        document = copy.deepcopy(dict(request))
        if not isinstance(document["clock"], dict) or set(document["clock"]) != {"clock_epoch_id", "authority_sha256"}:
            raise ContractError("release clock requires an explicit epoch and authority identity")
        clock = ClockIdentity(**document["clock"])
        weights = document["relative_weights"]
        if isinstance(weights, Mapping):
            converted = {}
            for key, value in weights.items():
                if isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key:
                    key = int(key)
                if type(key) is not int or key in converted:
                    raise ContractError("release weight keys must be unique canonical particle IDs")
                converted[key] = value
            weights = converted
        from msplatform.ion_release.authoring import author_release
        result = author_release(document["release_spec"], clock=clock,
            instrument_origin_us=document["instrument_origin_us"], species_id=document["species_id"],
            source_component_id=document["source_component_id"], relative_weights=weights,
            particle_ids=document.get("particle_ids"))
        object.__setattr__(self, "_document", result)

    @property
    def rows(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._document["rows"])

    @property
    def mother(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["mother"])

    @property
    def clock(self) -> ClockIdentity:
        return ClockIdentity(**self._document["clock"])

    def to_dict(self) -> dict[str, Any]:
        """Expand the exact sampler inputs, actual rows, ID mapping and clock mapping."""
        return copy.deepcopy(self._document)


def sample_release(spec: Mapping[str, Any]) -> ReleaseRealization:
    """Author canonical births without fields, materialized source files or native actions.

    The request supplies the existing release spec, clock, birth origin, species,
    component and explicit weight policy. Existing low-level sampler contracts
    remain available from msplatform.ion_release.release unchanged.
    """
    return ReleaseRealization(spec)


def build_geometry(compiled: CompiledSimionGeometry, *, context: ExecutionContext) -> OpenedArtifact:
    """Materialize actual unsolved geometry through the one public execution owner.

    Engineering limits and retention are explicit in context.stage_policy_path.
    Native reopen/relocation qualifications remain separate recorded facts.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.simion.compiler import CompiledSimionGeometry
    from msplatform.backends.simion.geometry_execution import execute_geometry
    from msplatform.backends.simion.native_plans import plan_geometry_build
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.backends.simion import native_completion
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(compiled, CompiledSimionGeometry):
        raise ContractError("build_geometry requires compiled SIMION geometry")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("build_geometry requires an explicit available SIMION executable")
    stage, authority = read_stage_policy(context, "build_geometry", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime
                and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION geometry runtime only accepts explicit boolean simion_allow_asynchronous_io")
    snapshot = CompiledSimionGeometry(**asdict(compiled))
    seed = file_record(structural_seed_path(4 + int(
        "entrance_refinement" in snapshot.frontend_geometry["numerical_domains"])), "required_evidence")
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
    return open_artifact({"manifest": result["manifest"], "product_id": "geometry"}, expected_kind="geometry_artifact")


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
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.clock_authority import validate_clock_authority
    from msplatform.execution.manifest_records import file_record, verify_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy

    if (not isinstance(drive, Mapping) or not {"pulse", "clock", "clock_authority"} <= drive.keys()
            or set(drive) - {"pulse", "clock", "clock_authority", "groups"}
            or not isinstance(drive["clock"], Mapping)
            or set(drive["clock"]) != {"phase_reference_instrument_time_us"}):
        raise ContractError("model drive requires pulse, explicit clock authority and phase reference; groups are optional")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("prepare_model requires an explicit available SIMION executable")
    source = open_artifact(geometry.reference if isinstance(geometry, OpenedArtifact) else geometry,
                           expected_kind="geometry_artifact")
    stage, policy_record = read_stage_policy(context, "prepare_model", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION model runtime only accepts explicit boolean simion_allow_asynchronous_io")
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
    values = json.loads(source.data_path("compiled_geometry").read_text(encoding="utf-8-sig"))
    values["downstream_specs"] = tuple(values["downstream_specs"])
    compiled = CompiledSimionGeometry(**values)
    selected = compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]
    components = {name: compiled.components_resolved[name] for name in selected}
    clock = dict(clock_epoch_id=validation["clock_epoch_id"], authority_sha256=validation["authority_sha256"],
                 **dict(drive["clock"]))
    expanded = project_resolved_drive(compiled, components, pulse=drive["pulse"], clock=clock)
    if "groups" in drive:
        expanded["groups"] = copy.deepcopy(drive["groups"])
    model = compile_prepared_model(compiled, components, drive=expanded, physics=physics)
    seed = file_record(structural_seed_path(4 + int(
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
    return open_artifact({"manifest": result["manifest"], "product_id": "model"}, expected_kind="prepared_model")


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
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.manifest_records import file_record
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
        reused = open_artifact(reuse_fields.reference if isinstance(reuse_fields, OpenedArtifact) else reuse_fields,
                               expected_kind="field_bundle")
        reuse_reference = reused.reference
        references.append({"manifest_record": reuse_reference["manifest"]})
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
    return open_artifact({"manifest": result["manifest"], "product_id": "fields"}, expected_kind="field_bundle")


def track(fields: OpenedArtifact | Mapping[str, Any],
          particles: ReleaseRealization | HandoffResult | Mapping[str, Any], *,
          propagation: Mapping[str, Any], observations: Mapping[str, Any],
          numerics: Mapping[str, Any], context: ExecutionContext,
          source_reference: OpenedArtifact | Mapping[str, Any] | None = None,
          unit_size: int | None = None, recovery_reference: Mapping[str, Any] | None = None,
          dispatch_profiles: Sequence[Mapping[str, Any]] = ()) -> OpenedArtifact:
    """Publish an explicit fixed-field flight, preserving its original cohort/clock.

    A release realization starts at birth; a HandoffResult requires its published
    trajectory producer. The backend verifies the actual observed source before
    relaunch. Zero handoff publishes full mother facts without launching tools.
    unit_size fixes ordinal replay boundaries without changing original IDs or
    the full mother. recovery_reference is one explicit predecessor manifest
    file record: complete units are verified and reused, incomplete units fully
    replayed by the existing dispatcher. Opening a field never solves it.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.assembly.handoff import HandoffResult
    from msplatform.backends.simion.artifacts import CompiledPreparedModel
    from msplatform.backends.simion.model import require_prepared_model
    from msplatform.backends.simion.tracking_execution import execute_tracking, plan_tracking_execution
    from msplatform.backends.simion.tracking_units import inspect_tracking_recovery
    from msplatform.backends.simion import native_completion
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    source = fields if isinstance(fields, OpenedArtifact) else open_artifact(fields, expected_kind="field_bundle")
    meta = source.metadata
    if (source.kind != "field_bundle" or meta.get("backend") != "simion"
            or meta.get("field_status") != "available" or meta.get("source_status") != "not_requested"):
        raise ContractError("track requires a published source-independent SIMION FieldBundle")
    model = CompiledPreparedModel(source.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    document = require_prepared_model(model)
    if meta.get("model_identity_sha256") != document["model_identity_sha256"] or meta.get("clock") != document["drive"]["clock"]:
        raise ContractError("tracking field model/clock identity differs")
    packet = particles.to_dict() if isinstance(particles, ReleaseRealization) else copy.deepcopy(particles)
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
                    field_manifest_record=source.reference["manifest"])
    graph = plan_tracking_execution(model, **planning)
    if recovery is not None:
        inspected = inspect_tracking_recovery(graph, recovery)
        graph = plan_tracking_execution(model, **planning, reused_unit_keys=inspected["reused_unit_keys"])
    predecessor = None
    references = [{"manifest_record": source.reference["manifest"]}]
    if recovery is not None:
        references.append({"manifest_record": recovery})
    if isinstance(packet, HandoffResult):
        if source_reference is None:
            raise ContractError("state relaunch requires its published trajectory source reference")
        predecessor = (source_reference if isinstance(source_reference, OpenedArtifact)
                       else open_artifact(source_reference, expected_kind="trajectory_result"))
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
            stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record], retention=stage["artifact_retention"],
        expected_operation_ids=tuple(graph["expected_operation_ids"]),
        operation_dependencies=graph["operation_dependencies"],
        action=partial(execute_tracking, fields_reference=source, particles=packet,
            propagation=graph["propagation"], observations=graph["observations"], numerics=graph["numerics"],
            limits=stage["limits"], source_reference=predecessor.reference if predecessor else None,
            unit_size=unit_size, recovery_reference=recovery, dispatch_profiles=profiles,
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
        action_record=file_record(Path(execute_tracking.__code__.co_filename).resolve(), "required_evidence"),
        source_references=references, use_short_execution_path=True, completion_api=lambda: native_completion)
    return open_artifact({"manifest": result["manifest"], "product_id": "trajectory"}, expected_kind="trajectory_result")


def analyze(result: OpenedArtifact | Mapping[str, Any], *,
            selection: Mapping[str, Any], method: Mapping[str, Any]) -> dict[str, Any]:
    """Read published trajectory observations and compute descriptive statistics.

    Selection and method are explicit version-1 contracts. Missing observations
    or unclassified inherited fates remain unavailable; no tool is started to
    supply them. The common time reference is not a particle birth or age.
    """
    from msplatform.backends.simion.trajectory_analysis import analyze_published_trajectory
    from msplatform.execution.artifact_reader import OpenedArtifact

    source = result if isinstance(result, OpenedArtifact) else open_artifact(result, expected_kind="trajectory_result")
    if source.kind != "trajectory_result" or source.metadata.get("backend") != "simion":
        raise ContractError("analysis requires a trajectory result from the supported SIMION data adapter")
    if not isinstance(selection, Mapping) or not isinstance(method, Mapping):
        raise ContractError("analysis requires explicit selection and method contracts")
    return analyze_published_trajectory(source, selection=copy.deepcopy(dict(selection)), method=copy.deepcopy(dict(method)))


def compare_trajectories(left: OpenedArtifact | Mapping[str, Any], right: OpenedArtifact | Mapping[str, Any], *,
                         selection: Mapping[str, Any], method: Mapping[str, Any]) -> dict[str, Any]:
    """Read two published trajectories and describe actual event t/xyz differences.

    This creates no owner, starts no tool and writes no data. Missing original
    observations remain explicit; completion is not equality or qualification.
    """
    from msplatform.backends.simion.trajectory_comparison import compare_published_trajectories
    from msplatform.execution.artifact_reader import OpenedArtifact

    sources = [value if isinstance(value, OpenedArtifact) else open_artifact(value, expected_kind="trajectory_result")
               for value in (left, right)]
    if not isinstance(selection, Mapping) or not isinstance(method, Mapping):
        raise ContractError("comparison requires explicit selection and method contracts")
    return compare_published_trajectories(*sources, selection=copy.deepcopy(dict(selection)),
                                         method=copy.deepcopy(dict(method)))


def inspect_cad(result: OpenedArtifact | Mapping[str, Any], *, checks: Mapping[str, Any]) -> dict[str, Any]:
    """Independently cold-read published STEP data; no export, owner or viewer."""
    import json
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.exporters.step import inspect_assembly_step
    source = result if isinstance(result, OpenedArtifact) else open_artifact(result, expected_kind="cad_geometry")
    if source.kind != "cad_geometry" or not isinstance(checks, Mapping) or set(checks) != {"schema_version", "kind", "probes"}:
        raise ContractError("STEP inspection requires explicit current checks and cad_geometry")
    if type(checks['schema_version']) is not int or checks['schema_version'] != 1 or checks['kind'] != 'physical_solids_step_v1' or not isinstance(checks['probes'],(list,tuple)):
        raise ContractError("unsupported STEP inspection checks")
    report = json.loads(source.data_path('report').read_text(encoding='utf-8-sig'))
    for key, report_key in (('step','step_record'),('assembly_snapshot','snapshot_record'),('export_options','options_record')):
        source.data_path(key)
        actual, declared = source.data_records[key], report[report_key]
        if actual['bytes'] != declared['bytes'] or actual['sha256'].upper() != declared['sha256'].upper():
            raise ContractError("STEP report content identity differs from the published data")
    snapshot = json.loads(source.data_path('assembly_snapshot').read_text(encoding='utf-8-sig'))
    options = json.loads(source.data_path('export_options').read_text(encoding='utf-8-sig'))
    if report['projection']['options'] != options:
        raise ContractError("STEP report options differ from its frozen input")
    inspection = inspect_assembly_step(source.data_path('step'), assembly=snapshot, export_report=report,
                                       probes=copy.deepcopy(checks['probes']))
    inspection.update(cad_reference=source.reference, producer=source.producer, checks=copy.deepcopy(dict(checks)))
    return inspection


def _validate_step_export_options(assembly, format, options) -> str:
    """One pure option boundary shared by STEP planning and actual export."""
    from msplatform.exporters.step import step_export_filename
    if not isinstance(assembly, assembly_domain.Assembly) or format != "step":
        raise ContractError("export_cad requires a complete Assembly and the supported step format")
    if not isinstance(options, Mapping) or options.get('representation') != 'physical_solids':
        raise ContractError("STEP options require physical_solids and explicit write_pcurves/precision_mode")
    try:
        return step_export_filename({key: value for key, value in options.items() if key != 'representation'})
    except ValueError as error:
        raise ContractError(str(error)) from error


def export_cad(assembly: assembly_domain.Assembly, *, format: str, options: Mapping[str, Any],
               context: ExecutionContext) -> OpenedArtifact:
    """Publish an independent STEP without solver, source, field or GUI actions.

    The selected context Python must have this distribution and cad-step extra
    installed. Optional options["name"] is the file stem and STEP root display
    name; omitted it preserves assembly.step. Engineering/retention policy is
    explicit, as for native geometry.
    """
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.exporters.step import assembly_geometry_members
    from msplatform.exporters.execution import execute_cad_export, no_particle_batch_completion_api
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    filename = _validate_step_export_options(assembly, format, options)
    snapshot = dict(composition_plan=assembly.composition_plan, components_resolved=assembly.components_resolved)
    assembly_geometry_members(snapshot)
    stage, authority = read_stage_policy(context, "export_cad", required_roles=("solver_native_binary",))
    if stage.get("runtime"):
        raise ContractError("The STEP exporter has no additional runtime mode")
    source = file_record(Path(execute_cad_export.__code__.co_filename).resolve(), "required_evidence")
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="cad_only", software=["CadQuery", "OCCT"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__cad__assembly-" + uuid4().hex[:12],
        payload=dict(action="export_cad", assembly=snapshot, options=copy.deepcopy(dict(options)), stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"], commitment_inputs=[authority],
        retention=stage["artifact_retention"], expected_operation_ids=("export_step",),
        operation_dependencies={"export_step": ()},
        action=partial(execute_cad_export, snapshot=snapshot, representation=options["representation"],
            options={name: options[name] for name in ("write_pcurves", "precision_mode", "name") if name in options}, limits=stage["limits"]),
        action_record=source, completion_api=no_particle_batch_completion_api,
        expected_relative_paths=("results/" + filename, "results/cad_export_report.json"))
    return open_artifact({"manifest": result["manifest"], "product_id": "cad_geometry"}, expected_kind="cad_geometry")


def _open_simion_model(model: OpenedArtifact | Mapping[str, Any], context: ExecutionContext) -> dict[str, Any]:
    """Compose the unique unsolved-model preparation and explicit GUI action."""
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.applications.simion_model_execution import execute_simion_open_model
    from msplatform.backends.simion.field_closure import load_field_model
    from msplatform.backends.simion.model import model_geometry
    from msplatform.backends.simion.model_view_preparation import prepare_view
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.exporters.execution import no_particle_batch_completion_api

    source = load_field_model(model)
    exe = context.tools.get("simion")
    if exe is None or not exe.is_file() or exe.name.lower() != "simion.exe":
        raise ContractError("SIMION viewing requires the explicit available SIMION executable")
    stage, authority = read_stage_policy(context, "open_model", required_roles=("solver_native_binary", "required_evidence"))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION view runtime only accepts explicit boolean simion_allow_asynchronous_io")
    geometry = model_geometry(source.model)
    seed = file_record(structural_seed_path(4 + int("entrance_refinement" in geometry.frontend_geometry["numerical_domains"])),
                       "required_evidence")
    ids = ("materialize_geometry", "build_model", "verify_model", "view_model")
    return run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="model_view", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__test__simion__view-" + uuid4().hex[:12],
        payload=dict(action="open_model", source=source.artifact.reference, application="simion", stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"], commitment_inputs=[authority],
        retention=stage["artifact_retention"], expected_operation_ids=ids,
        operation_dependencies={name: [ids[index-1]] for index, name in enumerate(ids) if index},
        action=partial(execute_simion_open_model, model_reference=source.artifact,
            prepare_view=partial(prepare_view, seed_record=seed, limits=stage["limits"],
                materialize_geometry=partial(materialize_payloads, limits=stage["limits"]),
                materializer_record=file_record(Path(materialize_payloads.__code__.co_filename).resolve(), "required_evidence"),
                allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
            preparer_record=file_record(Path(prepare_view.__code__.co_filename).resolve(), "required_evidence"),
            limits=stage["limits"]),
        action_record=file_record(Path(execute_simion_open_model.__code__.co_filename).resolve(), "required_evidence"),
        source_references=[{"manifest_record": source.artifact.reference["manifest"]}],
        use_short_execution_path=True, completion_api=no_particle_batch_completion_api)


def open_model(model: OpenedArtifact | Mapping[str, Any], *, application: str | None = None,
               context: ExecutionContext, checks: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Explicitly view a published model copy and await its normal closure.

    The current application action supports SolidWorks2022 STEP viewing. Close
    the imported document to finish; existing user applications are not adopted.
    SIMION viewing rebuilds/verifies an owned unsolved container from the same
    raw geometry and drive, then waits for application exit without Refine/Fly.
    An opened PreparedModel selects SIMION by default; raw references should
    select their application explicitly. Export/prepare never call this action.
    Optional SolidWorks checks select at most7 published STEP members for bounded
    readonly native observations, never automatic geometric qualification.
    """
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.applications.model_execution import execute_open_model
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.exporters.execution import no_particle_batch_completion_api

    selected = ("simion" if isinstance(model, OpenedArtifact) and model.kind == "prepared_model" else "solidworks") if application is None else application
    if selected == "simion":
        if checks is not None:
            raise ContractError("SIMION model viewing does not support SolidWorks geometry checks")
        return _open_simion_model(model, context)
    if selected != "solidworks":
        raise ContractError("open_model supports the explicit SolidWorks STEP or SIMION PreparedModel action")
    source = model if isinstance(model, OpenedArtifact) else open_artifact(model, expected_kind="cad_geometry")
    if source.kind != "cad_geometry":
        raise ContractError("SolidWorks viewing requires a published CAD geometry product")
    if checks is not None:
        from msplatform.applications.model_execution import _inspection_input
        checks = copy.deepcopy(dict(checks)) if isinstance(checks, Mapping) else checks
        _inspection_input(source, checks)
    exe = context.tools.get("solidworks")
    if exe is None or not exe.is_file() or exe.name.lower() != "sldworks.exe":
        raise ContractError("open_model requires the explicit available SolidWorks executable")
    stage, authority = read_stage_policy(context, "open_model", required_roles=("required_evidence",))
    settings = stage.get("runtime", {})
    if (set(settings) != {"com_class", "part_template", "assembly_template", "lifecycle"}
            or settings["com_class"] != "SldWorks.Application.30" or settings["lifecycle"] != "document_close"
            or any(not isinstance(settings[name], str) or not Path(settings[name]).is_absolute()
                   or not Path(settings[name]).is_file() for name in ("part_template", "assembly_template"))):
        raise ContractError("open_model runtime requires explicit2022 class, clean part/assembly templates and document_close lifecycle")
    return run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="model_view", software=["SolidWorks"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__test__cad__view-" + uuid4().hex[:12],
        payload=dict(action="open_model", source=source.reference, application=selected, stage_policy=stage,
            **({"checks": checks} if checks is not None else {})),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"], commitment_inputs=[authority],
        retention=stage["artifact_retention"], expected_operation_ids=("materialize_view", "view_model"),
        operation_dependencies={"view_model": ["materialize_view"]},
        action=partial(execute_open_model, model_reference=source, application=selected, limits=stage["limits"],
            materialize_payloads=partial(materialize_payloads, limits=stage["limits"]),
            materializer_record=file_record(Path(materialize_payloads.__code__.co_filename).resolve(), "required_evidence"),
            application_settings=settings, checks=checks),
        action_record=file_record(Path(execute_open_model.__code__.co_filename).resolve(), "required_evidence"),
        source_references=[{"manifest_record": source.reference["manifest"]}],
        completion_api=no_particle_batch_completion_api)


def resume_run(run_ref: str | Path, *, mode: str, context: ExecutionContext) -> dict[str, Any]:
    """Resume original stopped finalization from its explicit Result path.

    Result is mutable recovery transport, so the existing owner verifies the
    original request, completion, capacity authority and terminal publication.
    No action callback, field computation or flight is replayed here. Incomplete
    unit replay remains a separate pending public execution capability.
    """
    import json
    from msplatform.execution.owner import resume_finalization

    if mode != "finalization":
        raise ContractError("resume_run currently supports finalization; use analyze for published-data reanalysis")
    path = Path(run_ref)
    if not path.is_absolute() or not path.is_file():
        raise ContractError("finalization requires the explicit absolute existing Result path")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    root = Path(result["run_directory"])
    request = json.loads((root / "inputs/execution_request.json").read_text(encoding="utf-8-sig"))
    action = request["payload"]["action"]
    if action in {"build_geometry", "prepare_model", "solve_fields", "track"}:
        from msplatform.backends.simion import native_completion
        completion = lambda: native_completion
    elif action in {"export_cad", "open_model"}:
        from msplatform.exporters.execution import no_particle_batch_completion_api
        completion = no_particle_batch_completion_api
    else:
        raise ContractError("No installed completion policy for this explicit run action")
    return resume_finalization(context, path, completion_api=completion)


def open_artifact(reference: Mapping[str, Any], *, expected_kind: str,
                  resolver: ArtifactResolver | None = None) -> OpenedArtifact:
    """Read an explicitly published data product without invoking any execution owner."""
    from msplatform.execution.artifact_reader import open_artifact as read
    return read(reference, expected_kind=expected_kind, resolver=resolver)


def execution_context(*, workspace: str | Path, tools: Mapping[str, str | Path],
                      policy: Mapping[str, str | Path]) -> ExecutionContext:
    """Construct explicit local execution configuration without probing or creating paths.

    Tools must declare python and powershell executables; policy names the shared
    host state database; policy_path can override the installed current policy.
    No checkout is discovered.
    """
    if not {"python", "powershell"} <= tools.keys():
        raise ContractError("execution tools must explicitly declare python and powershell")
    required_policy = {"host_state_path"}
    if not required_policy <= policy.keys() or set(policy) - required_policy - {"policy_path", "execution_root", "stage_policy_path"}:
        raise ContractError("execution policy requires host_state_path; policy_path, execution_root and stage_policy_path are optional")
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.resources import resource_path
    policy_path = Path(policy["policy_path"]) if "policy_path" in policy else resource_path("host_resource_policy.json")
    return ExecutionContext(workspace=Path(workspace).absolute(), python_executable=Path(tools["python"]),
        powershell_executable=Path(tools["powershell"]), tools={key: Path(value) for key, value in tools.items()},
        host_state_path=Path(policy["host_state_path"]), policy_path=policy_path,
        execution_root=Path(policy["execution_root"]) if "execution_root" in policy else None,
        stage_policy_path=Path(policy["stage_policy_path"]) if "stage_policy_path" in policy else None)


def capabilities(request: Mapping[str, Any], *, environment: Mapping[str, Any] | None = None) -> dict:
    """Validate one actual request using pure compilers/planners, never execute.

    Planning arguments are explicitly not the execution API signature. An
    accepted plan does not authenticate published artifacts, tools, licenses,
    native completion, GUI inspection, precision or scientific qualification.
    Environment is an explicit caller observation, never discovered here.
    """
    import inspect

    if (not isinstance(request, Mapping) or set(request) != {"schema_version", "operation", "arguments"}
            or type(request["schema_version"]) is not int or request["schema_version"] != 1
            or not isinstance(request["operation"], str) or not isinstance(request["arguments"], Mapping)):
        raise ContractError("capability query requires version1 operation and explicit arguments")
    environment_status = "not_supplied"
    if environment is not None:
        if (not isinstance(environment, Mapping) or set(environment) != {"schema_version", "tools"}
                or type(environment["schema_version"]) is not int or environment["schema_version"] != 1
                or not isinstance(environment["tools"], Mapping)):
            raise ContractError("environment requires version1 explicit tool observations")
        for name, observation in environment["tools"].items():
            if (not isinstance(name, str) or not name or not isinstance(observation, Mapping)
                    or type(observation.get("available")) is not bool):
                raise ContractError("tool availability must be explicitly observed boolean")
        environment_status = ("incomplete" if not environment["tools"] else "declared_unavailable"
            if any(not row["available"] for row in environment["tools"].values()) else "declared_available")
    operation, arguments = request["operation"], dict(request["arguments"])
    result = dict(schema_version=1, operation=operation, contract_status="unsupported",
                  software_scope="not_validated", query_scope="compile_or_plan_only_not_execution_signature",
                  environment_status=environment_status, environment=copy.deepcopy(environment),
                  environment_compatibility="not_validated", execution_readiness="not_assessed",
                  native_qualification="not_granted", missing_arguments=[], reason=None,
                  execution_prerequisites=[], limitations=[])

    def step_projection(assembly, *, format, options):
        from msplatform.exporters.step import assembly_geometry_members
        _validate_step_export_options(assembly, format, options)
        return assembly_geometry_members(dict(composition_plan=assembly.composition_plan,
                                               components_resolved=assembly.components_resolved))

    if operation == "resolve_component":
        validator, scope = component_catalog.resolve_component, "provider_scientific_document_and_component_interface"
    elif operation == "compile_assembly":
        validator, scope = assembly_domain.assemble, "complete_parent_mechanical_layout"
    elif operation == "compile_geometry":
        validator, scope = simion_backend.compile_geometry, "native_geometry_specifications_not_built"
    elif operation == "prepare_model":
        from msplatform.backends.simion.model import compile_prepared_model
        validator, scope = compile_prepared_model, "pure_drive_physics_binding_not_native_preparation"
        result["execution_prerequisites"] = ["published_geometry", "verified_clock_records", "execution_owner_and_stage_policy", "explicit_SIMION"]
    elif operation == "solve_fields":
        from msplatform.backends.simion.field_execution import plan_fields_execution
        validator, scope = plan_fields_execution, "actual_field_operation_plan_not_solved"
        result["execution_prerequisites"] = ["published_prepared_model", "verified_payload_records", "execution_owner_and_stage_policy", "explicit_SIMION"]
    elif operation == "track":
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        validator, scope = plan_tracking_execution, "one_complete_cohort_tracking_plan_not_Fly"
        result["execution_prerequisites"] = ["published_FieldBundle", "verified_original_source_and_clock", "execution_owner_and_stage_policy", "explicit_SIMION"]
        result["limitations"] = ["explicit_one_complete_cohort_unit_v1", "shared_dispatcher_and_four_unit_recovery_not_proved"]
    elif operation == "export_cad":
        validator, scope = step_projection, "complete_physical_STEP_member_projection_not_exported"
        result["execution_prerequisites"] = ["cad-step_optional_dependencies", "execution_owner_and_stage_policy", "actual_STEP_export_and_reopen"]
    elif operation == "build_geometry":
        from msplatform.backends.simion.native_plans import plan_geometry_build
        validator, scope = plan_geometry_build, "actual_native_geometry_operation_plan_not_built"
        result["execution_prerequisites"] = ["actual_seed_and_native_resource_records", "execution_owner_and_stage_policy", "explicit_SIMION"]
    else:
        result["reason"] = "No pure planning adapter for this requested operation; no execution was attempted"
        return result
    signature = inspect.signature(validator)
    required = [name for name, parameter in signature.parameters.items()
                if parameter.default is inspect.Parameter.empty
                and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)]
    missing = [name for name in required if name not in arguments]
    result["validator"] = validator.__module__ + "." + validator.__qualname__
    if missing:
        result.update(contract_status="insufficient_request", missing_arguments=missing,
                      reason="Actual pure validator arguments are required; no records or paths were fabricated")
        return result
    try:
        signature.bind(**arguments)
        validator(**arguments)
    except (ValueError, TypeError, KeyError) as error:
        # Existing validators do not expose typed unsupported-vs-invalid errors;
        # retain the genuine reason rather than guessing from its message.
        result.update(contract_status="rejected", reason=dict(type=type(error).__name__, message=str(error)))
        return result
    result.update(contract_status="accepted", software_scope=scope)
    return result
