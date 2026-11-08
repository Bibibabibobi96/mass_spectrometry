"""Public SIMION operations over complete domain objects."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform.assembly.model import Assembly
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution import artifact_reader
from .compiler import CompiledSimionGeometry, compile_geometry as compile_simion_geometry
from .rf_compiler import compile_independent_multipoles

if TYPE_CHECKING:
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.context import ExecutionContext


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
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(compiled, CompiledSimionGeometry):
        raise ContractError("build_geometry requires compiled SIMION geometry")
    if compiled.frontend_geometry.get("role") == "simion_independent_rf_geometry":
        raise ContractError("independent RF native build remains in the project workflow; this SDK operation is pure compile only")
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
    source = artifact_reader.open_artifact(geometry.reference if isinstance(geometry, OpenedArtifact) else geometry,
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
        reused = artifact_reader.open_artifact(reuse_fields.reference if isinstance(reuse_fields, OpenedArtifact) else reuse_fields,
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
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "fields"}, expected_kind="field_bundle")


def compile_geometry(assembly: Assembly, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile native geometry specifications only; no source, writes, solve or Fly."""
    if not isinstance(assembly, Assembly):
        raise ContractError("SIMION geometry compilation requires an explicitly assembled design")
    plan = assembly.composition_plan
    selected = plan["scope"]["instance_ids"]
    if selected and all(plan["components"][name]["project_id"] == "rf_multipole_ion_optics" for name in selected):
        return compile_independent_multipoles(
            dict(composition_plan=plan, components_resolved=assembly.components_resolved),
            numerics=copy.deepcopy(dict(numerics)),
        )
    compiled = compile_simion_geometry(
        {"composition_plan": copy.deepcopy(dict(assembly.composition_plan)),
         "components_resolved": {name: copy.deepcopy(assembly.components_resolved[name]) for name in selected}},
        numerics=copy.deepcopy(dict(numerics)),
    )
    return replace(compiled, components_resolved=assembly.components_resolved)
