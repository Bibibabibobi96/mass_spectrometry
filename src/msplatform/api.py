"""Public staged operations over the platform's unique scientific implementations.

Importing this module does not discover tools, open models, or create a workspace.
Scientific defaults are visible in the versioned example, not inferred here.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform import assembly as assembly_domain
from msplatform import components as component_catalog
from msplatform.backends import simion as simion_backend
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution import artifact_reader

if TYPE_CHECKING:
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.context import ExecutionContext


def inspect_cad(result: OpenedArtifact | Mapping[str, Any], *, checks: Mapping[str, Any]) -> dict[str, Any]:
    """Independently cold-read published STEP data; no export, owner or viewer."""
    import json
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.exporters.step import inspect_assembly_step
    source = result if isinstance(result, OpenedArtifact) else artifact_reader.open_artifact(result, expected_kind="cad_geometry")
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
    snapshot = dict(composition_plan=assembly.composition_plan, components_resolved=assembly.components_resolved,
                    components_source=assembly.components_source)
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
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "cad_geometry"}, expected_kind="cad_geometry")


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
    source = model if isinstance(model, OpenedArtifact) else artifact_reader.open_artifact(model, expected_kind="cad_geometry")
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
                                               components_resolved=assembly.components_resolved,
                                               components_source=assembly.components_source))

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
