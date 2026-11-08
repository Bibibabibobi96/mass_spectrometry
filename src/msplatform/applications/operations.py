"""Explicit native application viewing operations."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution import artifact_reader

if TYPE_CHECKING:
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.context import ExecutionContext


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
    from msplatform.execution.completion import no_particle_batch_completion_api

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
    from msplatform.execution.completion import no_particle_batch_completion_api

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
