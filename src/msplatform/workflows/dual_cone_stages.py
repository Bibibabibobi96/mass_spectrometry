"""Independent managed dual-cone geometry, unsolved models and spatial fields."""

from datetime import datetime
from functools import partial
from pathlib import Path
import json
from uuid import uuid4

from msplatform.backends.simion import native_completion
from msplatform.backends.simion.dual_cone_stages import (
    plan_geometry_stage,
    plan_model_stage,
    require_geometry_product,
    require_model_product,
    require_fields_product,
)
from msplatform.backends.simion.dual_cone_stage_execution import execute_geometry, execute_model, execute_fields
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact


def _payload(value):
    if hasattr(value, "reference"):
        return value.reference
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _payload(item) for key, item in value.items()}
    return value


def _run(context, action, ids, implementation, arguments, sources, kind):
    stage, authority = read_stage_policy(context, action, required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if set(runtime) - {"simion_allow_asynchronous_io"} or (
        "simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool
    ):
        raise ValueError("SIMION stage runtime only accepts explicit boolean simion_allow_asynchronous_io")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ValueError("stage requires an explicit available SIMION executable")
    sources = list({str(source.manifest_location): source for source in sources}.values())
    result = run_managed_stage(
        context,
        descriptor=dict(project="dual_cone_tandem_quadrupole_ion_interface", mode=action, software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S")
        + "__sim__simion__"
        + action.replace("_", "-")
        + "-"
        + uuid4().hex[:12],
        payload=dict(action=action, stage_policy=stage, request=_payload(arguments)),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[authority],
        retention=stage["artifact_retention"],
        expected_operation_ids=tuple(ids),
        operation_dependencies={name: [ids[i - 1]] for i, name in enumerate(ids) if i},
        action=partial(
            implementation,
            **arguments,
            limits=stage["limits"],
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io"),
        ),
        action_record=file_record(Path(implementation.__code__.co_filename), "required_evidence"),
        source_references=[dict(manifest_record=source.reference["manifest"]) for source in sources],
        use_short_execution_path=True,
        completion_api=lambda: native_completion,
    )
    return open_artifact(
        dict(manifest=result["manifest"], product_id="trajectory" if kind == "trajectory_result" else "stage"),
        expected_kind=kind,
    )


def build_geometry(*, resolved, numerics, context):
    """Build/save/reopen zero-source unsolved geometry; no gas/source/Refine."""
    plan = plan_geometry_stage(resolved=resolved, numerics=numerics)
    result = _run(
        context,
        "dual_cone_geometry",
        plan["expected_operation_ids"],
        execute_geometry,
        dict(plan=plan),
        [],
        "geometry_artifact",
    )
    return require_geometry_product(result)


def prepare_model(geometry_reference, *, electric_field, clock, physics, clock_authority_reference, context):
    """Bind drive to an independently materialized raw geometry; no particles."""
    source = require_geometry_product(geometry_reference)
    geometry = json.loads(source.data_path("compiled_geometry").read_text(encoding="utf-8-sig"))
    plan = plan_model_stage(geometry, electric_field=electric_field, clock=clock, physics=physics)
    from msplatform.backends.simion.model_execution import _clock_reference

    _clock_reference(dict(drive=dict(clock=plan["projection"]["clock"])), clock_authority_reference)
    result = _run(
        context,
        "dual_cone_model",
        plan["expected_operation_ids"],
        execute_model,
        dict(source=source, model=plan["projection"], clock_reference=clock_authority_reference),
        [source],
        "prepared_model",
    )
    return require_model_product(result)


def solve_fields(model_reference, *, numerics, context, reuse_fields_reference=None):
    """Copy only unsolved raw geometry, then Refine/audit an independent family."""
    source = require_model_product(model_reference)
    model = json.loads(source.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    # Validate the selected refinement before owner admission or native I/O.
    from msplatform.backends.simion.dual_cone_stages import require_field_numerics

    require_field_numerics(model, numerics)
    reuse_source, reuse_producer = (
        (None, None) if reuse_fields_reference is None else require_fields_product(reuse_fields_reference)
    )
    if (
        reuse_source is not None
        and reuse_source.metadata["spatial_identity"]["geometry_identity_sha256"]
        != model["geometry"]["identity_sha256"]
    ):
        raise ValueError("saved basis geometry differs from selected new model")
    result = _run(
        context,
        "dual_cone_fields",
        ["materialize_geometry", "refine_fields", "audit_fields"] if reuse_source is None else ["audit_fields"],
        execute_fields,
        dict(source=source, model=model, numerics=numerics, reuse_source=reuse_source, reuse_producer=reuse_producer),
        [source] + ([] if reuse_source is None else [reuse_source, reuse_producer]),
        "field_bundle",
    )
    return require_fields_product(result)[0]


def track_fields(
    fields_reference,
    *,
    gas_field_reference,
    source_spec_path,
    numerics_path,
    collision_science,
    interface_path,
    collision_sds_dir,
    context,
):
    """Prepare the selected source/gas and Fly original published fields directly."""
    from msplatform.backends.simion.dual_cone_stages import plan_saved_field_fly
    from msplatform.backends.simion.dual_cone_stage_execution import execute_saved_fly
    from msplatform.backends.simion.dual_cone_transport import SDS_FILES
    from msplatform.results.gas_field import read_gas_field

    fields, producer = require_fields_product(fields_reference)
    model = json.loads(fields.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    source = json.loads(Path(source_spec_path).read_text(encoding="utf-8-sig"))
    numerics = json.loads(Path(numerics_path).read_text(encoding="utf-8-sig"))
    # A source/observation change cannot silently redefine the published PA domain.
    selected_geometry = plan_geometry_stage(resolved=model["geometry"]["resolved"], numerics=numerics)["projection"]
    if selected_geometry != model["geometry"]:
        raise ValueError("tracking numerics redefine the selected saved geometry")
    sds = {name: file_record(Path(collision_sds_dir) / name, "required_evidence") for name in SDS_FILES}
    plan = plan_saved_field_fly(
        fields_reference=fields,
        gas_field_reference=gas_field_reference,
        source_spec=source,
        numerics=numerics,
        collision_science=collision_science,
        collision_sds_records=sds,
    )
    gas = read_gas_field(gas_field_reference)
    request = dict(
        gas_field_reference=gas.reference,
        source_spec_path=Path(source_spec_path),
        numerics_path=Path(numerics_path),
        collision_science=collision_science,
        interface_path=Path(interface_path),
        collision_sds_dir=Path(collision_sds_dir),
    )
    return _run(
        context,
        "dual_cone_saved_fly",
        plan["expected_operation_ids"],
        execute_saved_fly,
        dict(fields=fields, producer=producer, plan=plan, request=request, model=model),
        [fields, producer, gas],
        "trajectory_result",
    )
