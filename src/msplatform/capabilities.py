"""Pure capability planning over canonical domain and backend operations.

Importing this module does not discover tools, open models, or create a workspace.
Scientific defaults are visible in versioned examples, not inferred here.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from msplatform import assembly as assembly_domain
from msplatform import components as component_catalog
from msplatform.backends import simion as simion_backend
from msplatform.contracts.machine_contracts import ContractError


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
        from msplatform.exporters.operations import _validate_step_export_options
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
        validator, scope = plan_tracking_execution, "whole_unit_tracking_plan_not_Fly"
        result["execution_prerequisites"] = ["published_FieldBundle", "verified_original_source_and_clock", "execution_owner_and_stage_policy", "explicit_SIMION"]
        result["limitations"] = ["incomplete_units_replay_whole_not_process_checkpoint_resume"]
    elif operation == "export_cad":
        validator, scope = step_projection, "complete_physical_STEP_member_projection_not_exported"
        result["execution_prerequisites"] = ["cad-step_optional_dependencies", "execution_owner_and_stage_policy", "actual_STEP_export_and_reopen"]
    elif operation == "build_geometry":
        from msplatform.backends.simion.native_plans import plan_geometry_build
        validator, scope = plan_geometry_build, "actual_native_geometry_operation_plan_not_built"
        result["execution_prerequisites"] = ["actual_seed_and_native_resource_records", "execution_owner_and_stage_policy", "explicit_SIMION"]
    elif operation == "build_ei_model":
        from msplatform.backends.comsol.ei_model import resolve_ei_build_request
        validator, scope = resolve_ei_build_request, "resolved_EI_build_only_request_not_native_model"
        result["execution_prerequisites"] = ["execution_owner_and_stage_policy", "explicit_COMSOL_and_MATLAB", "native_save_and_fresh_reopen"]
        result["limitations"] = ["unsolved_collision_counting_model_not_heavy_ion_source_or_scientific_qualification"]
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
        result.update(contract_status="rejected", reason=dict(type=type(error).__name__, message=str(error)))
        return result
    result.update(contract_status="accepted", software_scope=scope)
    return result
