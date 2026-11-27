"""Bind a public split-TOF field response basis to an explicit fit study."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping

from msplatform.analysis.reflectron_voltage_fit import compile_fit_parameters
from msplatform.backends.simion.artifacts import CompiledPreparedModel
from msplatform.backends.simion.field_closure import load_reflectron_response_records
from msplatform.backends.simion.model import model_geometry, require_prepared_model
from msplatform.contracts.particle_state import binary64_serialization_close
from msplatform.results.artifacts import OpenedArtifact, open_artifact


def compile_response_fit(
    field: OpenedArtifact, *, expected_model: CompiledPreparedModel,
    expected_downstream_identity: Mapping[str, Any], expected_grid: Mapping[str, Any],
    expected_frame_id: str, regularization: float,
) -> dict[str, Any]:
    """Bind ordered existing responses and explicit fit parameters without running native work.

    Caller must keep the field source under its actual owner guard for the
    full use of the returned records and derive the expected downstream
    identity from its authenticated model, raw geometry, solver and builders.
    This function does not acquire a lease, publish, solve fields, or qualify
    the response's numerical accuracy.
    """
    if not isinstance(field, OpenedArtifact) or field.kind != "field_bundle":
        raise ValueError("a protected field_bundle product is required")
    field = open_artifact(field, expected_kind="field_bundle")
    expected = require_prepared_model(expected_model)
    actual = require_prepared_model(CompiledPreparedModel(
        json.dumps(json.loads(field.data_path("compiled_model").read_text(encoding="utf-8-sig")),
                   sort_keys=True, allow_nan=False)))
    if actual != expected:
        raise ValueError("field compiled model differs from the selected Study model")
    frontend = expected["geometry"]["frontend_geometry"]
    if frontend.get("role") != "simion_split_oa_tof_geometry":
        raise ValueError("response fit requires the public split OA–TOF model")
    frame = frontend["composition_plan"]["assembly_frame_id"]
    if not isinstance(expected_frame_id, str) or not expected_frame_id or frame != expected_frame_id:
        raise ValueError("response frame differs from the selected Study")
    tof_id = frontend["tof_instance_id"]
    tof = expected["components_resolved"][tof_id]
    if tof.get("role") != "single_reflection_tof_design":
        raise ValueError("response fit requires the resolved downstream TOF component")
    specs = [row for row in model_geometry(expected_model, downstream_drive=True).downstream_specs
             if row["role"] == "reflectron"]
    if len(specs) != 1:
        raise ValueError("selected model must contain exactly one reflectron")
    instance, variables = specs[0]["native_instance"], specs[0]["template_variables"]
    actual_grid = {**{name: instance[name] for name in ("nx", "ny", "nz")},
                   "dx_mm": variables["mmgu_axial"], "dy_mm": variables["mmgu_radial"],
                   "dz_mm": variables["mmgu_radial"]}
    if dict(expected_grid) != actual_grid:
        raise ValueError("response grid differs from the selected model")
    drive = expected["drive"]["groups"][tof_id]
    endpoints = {}
    for name, group in (("midgrid", "reflectron_midgrid"), ("backplate", "reflectron_backplate")):
        row = drive[group]
        if set(row) != {"kind", "voltage_v"} or row["kind"] != "static":
            raise ValueError("reflectron fit requires explicit static endpoint voltages")
        endpoints[name] = row["voltage_v"]
    geometry = {"rings": tof["rings"], "geometry_mm": tof["geometry_mm"], "electrodes_V": endpoints}
    parameters = compile_fit_parameters(geometry, regularization)
    mid, back = parameters["midgrid_voltage_v"], parameters["backplate_voltage_v"]
    if not 0.0 < mid <= back:
        raise ValueError("reflectron fit requires positive, nondecreasing endpoint voltages")
    for stage, first, last in ((1, 0.0, mid), (2, mid, back)):
        count_in_stage = parameters[f"stage{stage}_count"]
        for index in range(1, count_in_stage + 1):
            row = drive[f"reflectron_stage{stage}_ring_{index}"]
            expected_voltage = first + (last - first) * index / (count_in_stage + 1)
            if (set(row) != {"kind", "voltage_v"} or row["kind"] != "static"
                    or not binary64_serialization_close(float(row["voltage_v"]), expected_voltage)):
                raise ValueError("reflectron fit currently requires the declared linear-divider baseline")
    electrodes = variables["component"]["electrodes"]
    count = 4 + parameters["stage1_count"] + parameters["stage2_count"]
    if ([item.get("local_electrode_id") for item in electrodes] != list(range(1, count + 1))
            or len({item.get("component_electrode_id") for item in electrodes}) != count):
        raise ValueError("resolved reflectron electrode IDs differ from the expected ordered basis")
    records = load_reflectron_response_records(
        field, expected_model_identity_sha256=expected["model_identity_sha256"],
        expected_downstream_identity=expected_downstream_identity,
        expected_grid=expected_grid, expected_symmetry="2dcylindrical")
    if len(records) != count:
        raise ValueError("response electrode count differs from the resolved TOF geometry")
    return {"schema_version": 1, "role": "reflectron_response_fit_binding",
            "field_reference": field.reference, "model_identity_sha256": expected["model_identity_sha256"],
            "frame_id": frame, "downstream_identity": dict(expected_downstream_identity),
            "grid": dict(expected_grid), "symmetry": "2dcylindrical",
            "responses": records, "fit_parameters": parameters}


def plan_response_axis_sampling(
    field: OpenedArtifact, *, expected_model: CompiledPreparedModel,
    expected_downstream_identity: Mapping[str, Any], expected_grid: Mapping[str, Any],
    expected_frame_id: str, regularization: float, maximum_x_mm: float,
    sampling_directory: Path, exporter_resource: Path,
) -> tuple[dict[str, Any], Any]:
    """Plan sampling authenticated standalone responses; the owner must hold all sources.

    The returned records are dependencies, not a lease. The existing managed
    stage owner must protect them and the field manifest until publication.
    """
    from .artifacts import NativeStagePlan
    from .native_plans import _native_ascii, _operation
    from .source import lua_value

    binding = compile_response_fit(field, expected_model=expected_model,
        expected_downstream_identity=expected_downstream_identity, expected_grid=expected_grid,
        expected_frame_id=expected_frame_id, regularization=regularization)
    if (isinstance(maximum_x_mm, bool) or not isinstance(maximum_x_mm, (int, float))
            or not math.isfinite(maximum_x_mm) or maximum_x_mm < 0
            or maximum_x_mm > (expected_grid['nx'] - 1) * expected_grid['dx_mm']):
        raise ValueError("explicit sampling range must lie within the response grid")
    root, exporter = _native_ascii(sampling_directory), _native_ascii(exporter_resource)
    paths = [str(_native_ascii(Path(row['path']))) for row in binding['responses']]
    spec, output = root/'response_axis.lua', root/'response_axis.csv'
    contents = 'return ' + lua_value(dict(responses=paths, output=str(output),
        maximum_x_mm=maximum_x_mm, grid=dict(expected_grid), symmetry=binding['symmetry'])) + '\n'
    operation = _operation('sample_reflectron_responses', 'prepare',
        ['lua', str(exporter), str(spec)], [str(output)], 'AXIS_BASIS_EXPORT=PASS')
    return binding, NativeStagePlan({str(spec): contents}, (), (operation,), (str(output),))


def sample_response_axis(
    field: OpenedArtifact, *, expected_model: CompiledPreparedModel,
    expected_downstream_identity: Mapping[str, Any], expected_grid: Mapping[str, Any],
    expected_frame_id: str, regularization: float, maximum_x_mm: float,
    context: Any, artifact_store: Any,
) -> OpenedArtifact:
    """Run one owned native sampling stage on the authenticated standalone basis."""
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.native_source_guard import guard_native_source
    from msplatform.execution.owner import run_managed_stage, standalone_native_store
    from msplatform.io.file_identity import canonical_json_sha256
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record
    from .resources import native_resource_path

    if not isinstance(field, OpenedArtifact):
        raise ValueError("a concrete field product is required")
    if artifact_store is None:
        raise ValueError("sampling requires the caller's ArtifactStore owner")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ValueError("sampling requires an explicit SIMION executable")
    stage, authority = read_stage_policy(context, "sample_reflectron_responses", required_roles=("required_evidence",))
    exporter = native_resource_path("export_axis_basis.lua")
    raw_root = (context.workspace / "artifacts").resolve()
    with guard_native_source(field.reference, expected_kind="field_bundle",
                             expected_artifact_root=raw_root, artifact_store=artifact_store) as protected:
        binding = compile_response_fit(protected, expected_model=expected_model,
            expected_downstream_identity=expected_downstream_identity, expected_grid=expected_grid,
            expected_frame_id=expected_frame_id, regularization=regularization)
        manifest_path = Path(protected.reference["manifest"]["path"]).resolve()
        native_assets = (artifact_store.root / "assets" / "native_stage").resolve()
        required_assets = ()
        if manifest_path.is_relative_to(native_assets):
            parts = manifest_path.relative_to(artifact_store.root).parts
            if len(parts) < 6 or parts[:2] != ("assets", "native_stage"):
                raise ValueError("field source Store identity is invalid")
            required_assets = (parts[3],)
        key = canonical_json_sha256(dict(action="sample_reflectron_responses", binding=binding,
                                         maximum_x_mm=maximum_x_mm, exporter=file_record(exporter, "required_evidence")))
        with standalone_native_store(artifact_store, task_key=key,
                budget=stage["limits"]["transient_run_directory_bytes"], required_assets=required_assets):
            result = run_managed_stage(context,
            descriptor=dict(project="instrument_assembly", mode="analysis", software=["SIMION"]),
            run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__analysis__simion__axis-" + uuid4().hex[:12],
            payload=dict(action="sample_reflectron_responses", binding=binding, maximum_x_mm=maximum_x_mm, stage_policy=stage),
            committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
            commitment_inputs=[authority, file_record(exporter, "required_evidence")], retention=stage["artifact_retention"],
            expected_operation_ids=("sample_reflectron_responses",), operation_dependencies={},
            action=partial(_sample_axis_action, field_reference=protected.reference, expected_model=expected_model,
                expected_downstream_identity=expected_downstream_identity, expected_grid=expected_grid,
                expected_frame_id=expected_frame_id, regularization=regularization, maximum_x_mm=maximum_x_mm,
                limits=stage["limits"]),
            action_record=file_record(Path(__file__).resolve(), "required_evidence"),
            source_references=[{"manifest_record": protected.reference["manifest"]}],
            use_short_execution_path=True, completion_api=no_particle_batch_completion_api, artifact_store=artifact_store)
    if result["status"] != "success" or result["stage"] != "complete":
        raise ValueError("managed reflectron axis sampling did not complete")
    return open_artifact({"manifest": result["manifest"], "product_id": "axis"}, expected_kind="axis_response_samples")


def _sample_axis_action(session: Any, *, field_reference: Mapping[str, Any], expected_model: CompiledPreparedModel,
                        expected_downstream_identity: Mapping[str, Any], expected_grid: Mapping[str, Any],
                        expected_frame_id: str, regularization: float, maximum_x_mm: float,
                        limits: Mapping[str, Any]) -> dict[str, Any]:
    from msplatform.execution.inputs import freeze_file
    from msplatform.io.manifest_records import file_record
    from .native_io import apply_native_io_mode
    from .resources import native_resource_path

    field = open_artifact(field_reference, expected_kind="field_bundle")
    exporter_alias = session.input_dir / "export_axis_basis.lua"
    exporter = session.declare_file(exporter_alias, "required_evidence")
    freeze_file(native_resource_path("export_axis_basis.lua"), exporter, retention_role="required_evidence")
    exporter_record = file_record(session.canonical_path(exporter), "required_evidence")
    session.add_input("axis_exporter", exporter_record)
    binding, plan = plan_response_axis_sampling(field, expected_model=expected_model,
        expected_downstream_identity=expected_downstream_identity, expected_grid=expected_grid,
        expected_frame_id=expected_frame_id, regularization=regularization, maximum_x_mm=maximum_x_mm,
        sampling_directory=session.run_dir / "simion/axis", exporter_resource=exporter_alias)
    for index, record in enumerate(binding["responses"], 1):
        session.add_input("response_" + str(index), {k: v for k, v in record.items() if k != "response_id"})
    spec_records = []
    for path, contents in plan.materializations.items():
        target = session.declare_file(path, "required_evidence")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8", newline="\n")
        record = file_record(session.canonical_path(target), "required_evidence")
        session.add_input("axis_spec", record)
        spec_records.append(record)
    output = session.declare_file(plan.declared_outputs[0], "required_evidence")
    operation = plan.operations[0]
    command = apply_native_io_mode([str(session.context.tools["simion"]), *operation["arguments"]],
                                   allow_asynchronous_io=False)
    session.run_process(operation["operation_id"], executable=session.context.tools["simion"],
        arguments=command[1:], role="SIMION", stage="prepare", limits=limits,
        immutable_input_records=[exporter_record, *spec_records, *[{k:v for k,v in r.items() if k != "response_id"}
                                                    for r in binding["responses"]]])
    if operation["success_marker"].encode() not in (session.log_dir / "operation_0001.stdout.log").read_bytes():
        raise ValueError("native response axis completion marker is absent")
    output_record = file_record(session.canonical_path(output), "required_evidence")
    metadata = dict(binding=binding, maximum_x_mm=maximum_x_mm, samples_unit="V", position_unit="mm",
                    basis_normalization_v=10000.0)
    return dict(status="success", summary=dict(action="sample_reflectron_responses"),
        output_paths=[str(output)], required_output_paths=[str(output)], retention_preserve_paths=[],
        manifest_extra_fields={"products": {"axis": dict(schema_version=1, kind="axis_response_samples",
            status="complete", metadata=metadata, data={"axis_csv":output_record})}})


def fit_sampled_axis(samples: OpenedArtifact) -> dict[str, Any]:
    """Fit one authenticated complete native axis sample without hidden defaults."""
    import numpy as np
    from msplatform.analysis.reflectron_voltage_fit import optimize

    if not isinstance(samples, OpenedArtifact):
        raise ValueError("a published axis-response sample product is required")
    samples = open_artifact(samples, expected_kind="axis_response_samples")
    metadata = samples.metadata
    if (metadata.get("samples_unit") != "V" or metadata.get("position_unit") != "mm"
            or metadata.get("basis_normalization_v") != 10000.0):
        raise ValueError("axis sample units or native response normalization differ")
    binding = metadata["binding"]
    count = len(binding["responses"])
    with samples.data_path("axis_csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header != ["x_mm", *["basis_" + str(i) + "_V" for i in range(1, count + 1)]]:
            raise ValueError("axis sample columns differ from ordered response IDs")
        rows = list(reader)
    if not rows or any(len(row) != count + 1 for row in rows):
        raise ValueError("axis samples are empty or incomplete")
    try:
        array = np.asarray([[float(value) for value in row] for row in rows], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("axis samples must be numerical") from exc
    if not np.isfinite(array).all() or array[0, 0] != 0 or np.any(np.diff(array[:, 0]) <= 0):
        raise ValueError("axis sample positions and values must be finite and ordered")
    return optimize(array[:, 0], array[:, 1:] / metadata["basis_normalization_v"], **binding["fit_parameters"])


def plan_compensated_reflectron(field: OpenedArtifact, *, original_model: CompiledPreparedModel,
                                 compensated_model: CompiledPreparedModel,
                                 expected_downstream_identity: Mapping[str, Any],
                                 expected_grid: Mapping[str, Any], expected_frame_id: str,
                                 fit: Mapping[str, Any], regularization: float) -> dict[str, Any]:
    """Validate the exact old/new model relation and project a standalone PA rebias.

    This plans only: the existing field owner must hold the source and publish a
    full field bundle after composition, binding it to the compensated model.
    """
    from msplatform.analysis.reflectron_compensation import compile_compensated_study
    from .field_closure import require_downstream_reuse
    from .model import compile_prepared_model

    if (not isinstance(fit.get('fit'), Mapping)
            or fit['fit'].get('regularization') != regularization):
        raise ValueError('fit regularization differs from the explicit author parameter')
    binding = compile_response_fit(field, expected_model=original_model,
        expected_downstream_identity=expected_downstream_identity, expected_grid=expected_grid,
        expected_frame_id=expected_frame_id, regularization=regularization)
    original = require_prepared_model(original_model)
    frontend = original["geometry"]["frontend_geometry"]
    instance = frontend["tof_instance_id"]
    author = compile_compensated_study({"drive": original["drive"]}, instance_id=instance, fit=fit)
    expected = compile_prepared_model(model_geometry(original_model), original["components_resolved"],
                                      drive=author["drive"], physics=original["physics"])
    if require_prepared_model(compensated_model) != require_prepared_model(expected):
        raise ValueError("compensated model differs from the exact authored ring change")
    _, assets = require_downstream_reuse(field, expected_downstream_identity)
    def electrode_rows(model):
        spec = next(row for row in model_geometry(model, downstream_drive=True).downstream_specs
                    if row["role"] == "reflectron")
        return spec["template_variables"]["component"]["electrodes"]
    before, after = electrode_rows(original_model), electrode_rows(compensated_model)
    if len(before) != len(binding["responses"]) or len(after) != len(before):
        raise ValueError("response count differs from the model electrode sequence")
    responses = []
    for index, (old, new, record) in enumerate(zip(before, after, binding["responses"], strict=True), 1):
        if old["local_electrode_id"] != index or new["local_electrode_id"] != index:
            raise ValueError("electrode order differs from authenticated responses")
        responses.append(dict(response_id=index, record=record,
                              coefficient=(new["voltage_v"] - old["voltage_v"]) / 10000.0))
    return dict(schema_version=1, role="reflectron_standalone_rebias_plan",
        original_field=field.reference, original_model_identity_sha256=original["model_identity_sha256"],
        compensated_model_identity_sha256=require_prepared_model(compensated_model)["model_identity_sha256"],
        frame_id=expected_frame_id, base_record=assets["reflectron"]["carrier_record"],
        responses=responses, fit=dict(fit), normalization_v=10000.0)
