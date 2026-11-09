"""EI build-only request and public operation over the canonical model implementation."""
from __future__ import annotations
import copy
from typing import Any, Mapping
from msplatform.components.apertured_tube_electron_impact_ion_source.resolve_contract import resolve_contract
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.context import ExecutionContext
from msplatform.results.artifacts import OpenedArtifact
from .model_execution import UnsolvedModelSpec, build_unsolved_model

NATIVE_MODEL = UnsolvedModelSpec(run_label="ei-model",
    matlab_resources=("ms_stage1_ei_source.m", "load_ei_source_contract.m", "comsolstartup.m",
        "verify_ei_source_model.m", "verify_ei_source_parameter_bindings.m", "ei_source_unit_text.m"),
    build_function="ms_stage1_ei_source", verify_function="verify_ei_source_model",
    model_relative_paths=("comsol/MS_Stage1_EISource_ei_prepared_model__build_only.mph",),
    build_extra_arguments=("ei_prepared_model",))


def build_ei_model(baseline: Mapping[str, Any], modes: Mapping[str, Any], *, mode_id: str,
                   context: ExecutionContext, evidence_particle_count: int | None = None) -> OpenedArtifact:
    """Save and independently reopen build-only geometry/mesh/physics/solver trees.

    Physical inputs and the numerical table remain caller-owned. This operation
    does not Compute, solve fields, release particles or confer scientific status.
    """
    resolved = resolve_ei_build_request(baseline, modes, mode_id=mode_id,
                                      evidence_particle_count=evidence_particle_count)
    return build_unsolved_model(resolved, baseline, modes, action_name="build_ei_model",
                                spec=NATIVE_MODEL, context=context)


def resolve_ei_build_request(baseline: Mapping[str, Any], modes: Mapping[str, Any], *, mode_id: str,
                             evidence_particle_count: int | None = None) -> dict:
    """Resolve exactly the same build-only applicability for query and execution."""
    resolved = resolve_contract(copy.deepcopy(dict(baseline)), copy.deepcopy(dict(modes)),
                                mode_id, evidence_particle_count)
    if resolved["numerical"]["execution_mode"] != "build_only":
        raise ContractError("build_ei_model currently implements only the selected build_only mode")
    return resolved
