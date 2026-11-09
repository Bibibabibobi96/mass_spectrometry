"""Explicit fresh dual-cone operations; one existing RunSession owns native work.

No operation imports, opens or copies a previously published SIMION family.
Independent stage publication and saved-field reuse are not implemented here.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping

from msplatform.contracts.particle_count import validate_positive_particle_count
from .dual_cone_geometry import render_gem


from .dual_cone_stages import ELECTRODE_IDS, transport_refinement

NATIVE_OPERATION_IDS = (
    "build_geometry",
    "refine_fields",
    "audit_fields",
    "build_tracking_model",
    "verify_tracking_model",
    "fly",
)


def plan_transport_operations(*, resolved: Mapping, numerics: Mapping, science: Mapping, source_spec: Mapping) -> dict:
    """Validate scientific selections and return the actual serial native graph.

    Preparation and analysis are pure in-process responsibilities, not fabricated
    process receipts. Geometry/surface audit is performed by the geometry builder;
    field readback and tracking-model reopen have separate native processes.
    """
    gem = render_gem(dict(resolved), dict(numerics))
    refinement = transport_refinement(numerics)
    if numerics["pa"]["surface_enhancement"] != "fractional":
        raise ValueError("dual-cone transport requires its declared fractional surface")
    if science.get("role") != "dual_cone_simion_ion_transport_science":
        raise ValueError("dual-cone transport science role differs")
    if science.get("trajectory_authority") != "simion":
        raise ValueError("SIMION must remain the trajectory authority")
    if science["gas"]["collision_model"] != "simion_official_collision_sds":
        raise ValueError("dual-cone gas transport requires the declared official SDS model")
    groups = []
    for name in ("stage_1", "stage_2"):
        groups.extend(science["electric_field"][name]["electrode_group_ids"].values())
    if sorted(groups) != list(ELECTRODE_IDS[3:]):
        raise ValueError("drive does not bind the actual seven-electrode geometry")
    count = validate_positive_particle_count(source_spec["particle_count"])
    if validate_positive_particle_count(source_spec["mother_particle_count"]) != count:
        raise ValueError("fresh transport requires its complete declared mother source")
    trajectory = numerics["trajectory"]
    for name in ("maximum_time_us", "maximum_step_us", "sample_interval_us"):
        value = trajectory[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("trajectory " + name + " must be positive and finite")
    return dict(
        schema_version=1,
        role="dual_cone_fresh_transport_plan",
        expected_operation_ids=list(NATIVE_OPERATION_IDS),
        operation_dependencies={
            name: [NATIVE_OPERATION_IDS[index - 1]] for index, name in enumerate(NATIVE_OPERATION_IDS) if index
        },
        electrode_ids=list(ELECTRODE_IDS),
        source_count=count,
        refinement=refinement,
        gem=gem,
        numerics=copy.deepcopy(dict(numerics)),
        scientific_qualification="not_granted",
        independent_stage_publication="not_implemented",
        saved_field_reuse="not_implemented",
    )


def _native_operation(
    session,
    operation_id,
    *,
    arguments,
    limits,
    marker=None,
    immutable_input_records=(),
    environment=None,
    allow_asynchronous_io=None,
):
    """Use the sole observed process transport and its actual closed receipt."""
    from .native_io import apply_native_io_mode

    executable = session.context.tools["simion"]
    receipt = session.run_process(
        operation_id,
        executable=executable,
        arguments=apply_native_io_mode([str(executable), *arguments], allow_asynchronous_io=allow_asynchronous_io)[1:],
        role="SIMION",
        stage="flight" if operation_id == "fly" else "pa_refine" if operation_id == "refine_fields" else "prepare",
        limits=limits,
        immutable_input_records=immutable_input_records,
        environment=environment,
    )
    matches = [row for row in session.operations if row["operation_id"] == operation_id]
    if (
        len(matches) != 1
        or matches[0]["observation"].get("exit_confirmed") is not True
        or matches[0]["observation"].get("returncode") != 0
    ):
        raise ValueError("native operation has no successful closed writer: " + operation_id)
    ordinal = session.expected_operation_ids.index(operation_id) + 1
    stdout = session.log_dir / f"operation_{ordinal:04d}.stdout.log"
    if marker is not None and marker.encode("ascii") not in stdout.read_bytes():
        raise ValueError("native operation completion marker missing: " + operation_id)
    return receipt, stdout


def build_transport_geometry(session, *, builder, specification, limits, allow_asynchronous_io=None):
    """Build only fresh raw geometry; audit namespace/grid/surface in that process."""
    from pathlib import Path

    for name in ("output", "fractional_surface", "surface_witnesses"):
        path = Path(specification[name])
        if path.exists():
            raise FileExistsError("fresh geometry refuses an existing output: " + str(path))
        if not session.canonical_path(path).is_relative_to(session.artifact_run_dir):
            raise ValueError("fresh geometry output escapes its admitted run")
        session.declare_file(path, "required_evidence" if name == "surface_witnesses" else "solver_native_binary")
        path.parent.mkdir(parents=True, exist_ok=True)
    spec = _write_spec(session, "geometry", specification)
    _native_operation(
        session,
        "build_geometry",
        arguments=["--nogui", "--noprompt", "lua", str(builder), str(spec)],
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
        marker="BUILD_GEOMETRY=PASS",
    )
    for name in ("output", "fractional_surface", "surface_witnesses"):
        if not Path(specification[name]).is_file() or Path(specification[name]).stat().st_size == 0:
            raise ValueError("geometry did not produce its exact fractional closure")


def _write_spec(session, name, value):
    """Freeze a generated backend request using the existing Lua serializer."""
    from msplatform.io.manifest_records import file_record
    from .source import lua_value

    path = session.declare_file(session.input_dir / (name + ".lua"), "required_evidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("return " + lua_value(value) + "\n")
    session.add_input(name + "_specification", file_record(path, "required_evidence"))
    return path


def refine_transport_fields(session, *, refiner, raw, refinement, limits, allow_asynchronous_io=None):
    """Explicit fresh Refine only; never discover/reuse a published family."""
    from pathlib import Path

    raw = Path(raw)
    if not raw.is_file() or not str(raw).endswith(".pa#"):
        raise ValueError("fresh Refine requires its actual raw PA#")
    if not session.canonical_path(raw).is_relative_to(session.artifact_run_dir):
        raise ValueError("Refine refuses a family outside its admitted run")
    responses = [raw.with_suffix(".pa0"), *(raw.with_suffix(".pa" + str(eid)) for eid in ELECTRODE_IDS)]
    if any(path.exists() for path in responses):
        raise FileExistsError("fresh Refine refuses existing solved responses")
    for path in responses:
        session.declare_file(path, "solver_native_binary")
    spec = {"input": str(raw)}
    if refinement["refine_policy"] == "explicit_convergence":
        spec["convergence_v"] = refinement["convergence_v"]
    elif refinement["refine_policy"] != "simion_refine_without_convergence_argument":
        raise ValueError("unsupported selected Refine policy")
    spec = _write_spec(session, "refinement", spec)
    _native_operation(
        session,
        "refine_fields",
        arguments=["--nogui", "--noprompt", "lua", str(refiner), str(spec)],
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
        marker="INDEPENDENT_RF_REFINE=PASS",
    )
    if any(not path.is_file() or path.stat().st_size == 0 for path in responses):
        raise ValueError("Refine omitted an actual seven-electrode response")
    return responses


def track_transport(
    session,
    *,
    workbench,
    fly2,
    run_config,
    numerics,
    source_count,
    limits,
    final_state,
    immutable_input_records,
    allow_asynchronous_io=None,
):
    """Fly verified run-owned fields; this function cannot build or Refine."""
    from pathlib import Path
    from .native_completion import require_one_fly_completion
    from .native_io import apply_native_io_mode
    from msplatform.analysis.terminal_plane import analyze_terminal_plane

    workbench = Path(workbench)
    if not session.canonical_path(workbench).is_relative_to(session.artifact_run_dir):
        raise ValueError("fresh tracking refuses an external/published workbench")
    if not workbench.is_file():
        raise ValueError("tracking requires its verified saved workbench")
    if not immutable_input_records:
        raise ValueError("tracking requires its original audited native input identities")
    args = [
        "--nogui",
        "--noprompt",
        "fly",
        "--particles",
        str(fly2),
        "--programs",
        "1",
        "--retain-trajectories",
        "0",
        "--trajectory-quality",
        str(numerics["trajectory"]["trajectory_quality"]),
        str(workbench),
    ]
    # RunSession owns launch identity, writer closure, limits and shared leases.
    # Program paths/config remain frozen inputs; no global environment mutation.
    executable = session.context.tools["simion"]
    session.run_process(
        "fly",
        executable=executable,
        arguments=apply_native_io_mode([str(executable), *args], allow_asynchronous_io=allow_asynchronous_io)[1:],
        role="SIMION",
        stage="flight",
        limits=limits,
        environment={"DUAL_CONE_SIMION_RUN_CONFIG_LUA": str(run_config)},
        immutable_input_records=immutable_input_records,
    )
    completed = [row for row in session.operations if row["operation_id"] == "fly"]
    if (
        len(completed) != 1
        or completed[0]["observation"].get("exit_confirmed") is not True
        or completed[0]["observation"].get("returncode") != 0
    ):
        raise ValueError("Fly has no confirmed successful native writer exit")
    ordinal = session.expected_operation_ids.index("fly") + 1
    stdout = session.log_dir / f"operation_{ordinal:04d}.stdout.log"
    with stdout.open(encoding="utf-8-sig") as stream:
        completion = require_one_fly_completion(stream)
    if completion.splats != source_count:
        raise ValueError("native Fly completion count differs from the complete declared source")
    offsets = numerics["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]
    return analyze_terminal_plane(
        Path(final_state),
        source_count=source_count,
        pass_code=1,
        axis_center_x_mm=offsets["x"],
        axis_center_y_mm=offsets["y"],
    )


def _prepare_execution_inputs(session, *, request):
    """Freeze the pure preparation and exact implementation resource closure."""
    import inspect
    import json
    from pathlib import Path
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.resources import resource_path
    from msplatform.io.manifest_records import file_record
    from msplatform.results.gas_field import read_gas_field
    from .dual_cone_transport import prepare_transport
    from .model_execution import _protected_source
    from .resources import native_resource_path

    values = {
        name: json.loads(Path(request[name + "_path"]).read_text(encoding="utf-8-sig"))
        for name in ("resolved", "numerics", "science", "source_spec")
    }
    plan = plan_transport_operations(**values)
    if tuple(plan["expected_operation_ids"]) != session.expected_operation_ids or plan[
        "operation_dependencies"
    ] != dict(session.operation_dependencies):
        raise ValueError("transport graph differs from its admitted owner operations")
    gas = read_gas_field(request["gas_field_reference"])
    _protected_source(
        session, gas.reference["manifest"], required_paths=[str(path) for path in gas.data_locations.values()]
    )
    prepared = session.run_dir / "transport"
    # Declare the pure preparer's finite output closure before its first write,
    # including partial preparation failures; never adopt arbitrary native files.
    from .dual_cone_transport import SDS_FILES

    input_names = (
        "resolved_geometry.json",
        "simion_solver_numerics.json",
        "ion_transport_science.json",
        "gas_field_interface.json",
        "compiled_gas_field_manifest.json",
        "gas_field_manifest.json",
        "gas_producer_manifest.json",
        "gas_producer_science.json",
        "gas_producer_numerics.json",
        "gas_producer_geometry.json",
        "gas_flow_science.json",
        "cylindrical_ion_source.json",
        "cylindrical_ion_source.csv",
        "cylindrical_ion_source_receipt.json",
    )
    solver_names = (
        "dual_cone_tandem.gem",
        "simion_rf_drive.lua",
        "gas_assisted_transport.lua",
        "compiled_gas_field.lua",
        "gas_field_runtime.lua",
        "gas_source.fly2",
        "gas_source_states.lua",
        "run_config.lua",
    )
    for name in input_names:
        session.declare_file(prepared / "input" / name, "required_evidence")
    for name in solver_names:
        session.declare_file(prepared / "solver/simion" / name, "required_evidence")
    for name in SDS_FILES:
        session.declare_file(prepared / "solver/simion/collision_sds" / name, "required_evidence")
    session.declare_file(prepared / "preparation_receipt.json", "required_evidence")
    receipt = prepare_transport(prepared, mode="gas_assisted_transport", **request)
    # These are known outputs of the installed pure preparer. No native process
    # has started and no unknown writer/output is adopted by this registration.
    records = {}

    def bind(name, path, role="required_evidence", expected=None):
        row = file_record(session.canonical_path(path), role)
        if expected is not None and (
            row["sha256"].upper() != expected["sha256"].upper()
            or ("bytes" in expected and row["bytes"] != expected["bytes"])
        ):
            raise ValueError("prepared input differs from its original frozen identity: " + name)
        session.add_input(name, row)
        records[name] = row
        return row

    for name, record in receipt["inputs"].items():
        if isinstance(record, dict) and ("frozen_path" in record or "path" in record):
            bind("prepared_" + name, Path(record.get("frozen_path", record.get("path"))), expected=record)
    for name, record in receipt["inputs"]["simion_official_collision_sds"].items():
        bind("prepared_sds_" + name, Path(record["frozen_path"]), expected=record)
    compiled = receipt["inputs"]["gas_field_manifest_identity"]["runtime_lua"]
    bind("prepared_compiled_gas_context", Path(compiled["path"]), expected=compiled)
    bind("preparation_receipt", prepared / "preparation_receipt.json")
    frozen = session.input_dir / "native_sources"
    sources = {}
    names = (
        "build_frontend_geometry.lua",
        "gem2pa_geometry.lua",
        "refine_rf_field_family.lua",
        "audit_rf_field_family.lua",
        "build_tracking_iob.lua",
        "iob_core.lua",
    )
    for name in names:
        target = session.declare_file(frozen / name, "required_evidence")
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(native_resource_path(name), target)
        bind("native_" + name, target)
        sources[name] = target
    path_helper = session.declare_file(frozen / "native_run_path.lua", "required_evidence")
    freeze_file(resource_path("native_run_path.lua"), path_helper)
    bind("native_path", path_helper)
    action_source = session.declare_file(frozen / "dual_cone_transport_execution.py", "required_evidence")
    freeze_file(Path(inspect.getsourcefile(execute_transport)), action_source)
    bind("action_source", action_source)
    return plan, values, prepared, records, sources, path_helper


def _build_and_audit_fields(session, *, prepared, values, plan, sources, limits, allow_asynchronous_io=None):
    """Compose explicit fresh geometry, Refine and read-only field verification."""
    import json
    from msplatform.io.manifest_records import file_record
    from .dual_cone_geometry import geometry_grid

    solver = prepared / "solver/simion"
    raw = solver / "dual_cone_tandem.pa#"
    grid = geometry_grid(values["resolved"], values["numerics"])
    witnesses = solver / "dual_cone_surface.csv"
    # The axis is vacuum in the declared monolithic cone/rod representation.
    # Namespace witnesses come from actual integer electrode nodes, not guessed
    # thin-cone sample points or a second implementation of GEM geometry.
    offsets = values["numerics"]["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]
    samples = [
        dict(
            gu=[round(offsets["x"] / grid["dx_mm"]), round(offsets["y"] / grid["dy_mm"]), 1],
            metal=False,
            label="upstream_axis_vacuum",
        )
    ]
    geometry_spec = dict(
        schema_version=1,
        role="simion_frontend_raw_geometry",
        domain_id="dual_cone",
        gem=str(solver / "dual_cone_tandem.gem"),
        output=str(raw),
        grid=grid,
        physical_samples=samples,
        electrode_witness_ids=list(ELECTRODE_IDS),
        fractional_surface=str(raw.with_suffix(".pa-surf")),
        surface_witnesses=str(witnesses),
    )
    for suffix in (".source.gem", ".source.processed.gem"):
        session.declare_file(raw.with_suffix(suffix), "required_evidence")
    build_transport_geometry(
        session,
        builder=sources["build_frontend_geometry.lua"],
        specification=geometry_spec,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    responses = refine_transport_fields(
        session,
        refiner=sources["refine_rf_field_family.lua"],
        raw=raw,
        refinement=plan["refinement"],
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    family = [raw, raw.with_suffix(".pa-surf"), *responses]
    guards = [file_record(session.canonical_path(path), "solver_native_binary") for path in family]
    guards.append(file_record(session.canonical_path(witnesses), "required_evidence"))
    audit = session.declare_file(session.result_dir / "field_audit.json", "required_evidence")
    audit.parent.mkdir(parents=True, exist_ok=True)
    spec = _write_spec(
        session,
        "field_audit",
        dict(
            assets=[
                dict(
                    domain_id="dual_cone",
                    carrier_path=str(raw.with_suffix(".pa0")),
                    family_paths=[str(path) for path in family],
                    response_ids=list(ELECTRODE_IDS),
                    grid=grid,
                    physical_samples=samples,
                    surface_witnesses=str(witnesses),
                )
            ],
            output=str(audit),
        ),
    )
    _native_operation(
        session,
        "audit_fields",
        arguments=["--nogui", "--noprompt", "lua", str(sources["audit_rf_field_family.lua"]), str(spec)],
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
        marker="INDEPENDENT_RF_FIELDS_READBACK=PASS",
        immutable_input_records=guards,
    )
    actual = json.loads(audit.read_text())
    if actual.get("status") != "success" or actual.get("checked_domains") != ["dual_cone"]:
        raise ValueError("actual dual-cone fractional family audit is incomplete")
    return raw, grid, samples, witnesses, guards, audit


def build_transport_tracking_model(
    session,
    *,
    solver,
    raw,
    grid,
    samples,
    witnesses,
    guards,
    prepared_records,
    sources,
    path_helper,
    limits,
    allow_asynchronous_io=None,
):
    """Save/reopen only a source-bearing model over already audited owned fields."""
    from pathlib import Path
    from msplatform.execution.inputs import freeze_file
    from msplatform.io.manifest_records import file_record
    from .resources import structural_seed_path

    seed = session.declare_file(solver / "seed/one_instance.iob", "required_evidence")
    seed.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(structural_seed_path(1), seed)
    seed_record = file_record(session.canonical_path(seed), "required_evidence")
    session.add_input("tracking_structural_seed", seed_record)
    # Native seed-local spelling must use this run's existing execution alias;
    # declare_file retains canonical accounting identities and is not a projector.
    bootstrap_execution_path = solver / "seed/iob_seed_placeholder_01.pa0"
    session.declare_file(bootstrap_execution_path, "solver_native_binary")
    iob_execution_path = solver / "transport.iob"
    iob = session.declare_file(iob_execution_path, "solver_native_binary")
    from msplatform.io.manifest_records import verify_record

    companions = []
    for name, destination in (
        ("prepared_simion_program", iob.with_suffix(".lua")),
        ("prepared_particle_fly2", iob.with_suffix(".fly2")),
    ):
        original = prepared_records[name]
        verify_record(name, original)
        session.declare_file(destination, "required_evidence")
        freeze_file(Path(original["path"]), destination)
        expected = dict(original, path=str(session.canonical_path(destination)))
        verify_record(name + " copy", expected)
        companions.append(expected)
    read_inputs = [*guards, *prepared_records.values(), seed_record]
    # wb.save may legitimately rewrite/restore the companions during build.
    # Their expected copy identities were fixed before that operation.
    final_guards = None
    iob_spec = _write_spec(
        session,
        "tracking_model",
        dict(
            schema_version=1,
            role="dual_cone_tracking_iob",
            seed_iob=str(seed),
            output_iob=str(iob),
            bootstrap_paths=[str(bootstrap_execution_path)],
            response_fields=[],
            instances=[
                dict(
                    role="dual_cone",
                    instance_index=1,
                    priority_number=1,
                    rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    path=str(raw.with_suffix(".pa0")),
                    grid=grid,
                    placement=dict(x_mm=0, y_mm=0, z_mm=0, az_deg=0, el_deg=0, rt_deg=0, scale=1),
                    fractional_surface=str(raw.with_suffix(".pa-surf")),
                    surface_witnesses=str(witnesses),
                    response_ids=list(ELECTRODE_IDS),
                    physical_samples=samples,
                )
            ],
        ),
    )
    read_inputs.append(file_record(session.canonical_path(iob_spec), "required_evidence"))
    for operation, mode, marker in (
        ("build_tracking_model", "build", "DUAL_CONE_TRACKING_IOB=PASS"),
        ("verify_tracking_model", "verify", "DUAL_CONE_TRACKING_IOB_REOPEN=PASS"),
    ):
        _native_operation(
            session,
            operation,
            arguments=[
                "--nogui",
                "--noprompt",
                "lua",
                str(sources["build_tracking_iob.lua"]),
                str(iob_spec),
                mode,
                str(path_helper),
            ],
            limits=limits,
            allow_asynchronous_io=allow_asynchronous_io,
            marker=marker,
            immutable_input_records=read_inputs if mode == "build" else final_guards,
            environment={"DUAL_CONE_SIMION_RUN_CONFIG_LUA": str(solver / "run_config.lua")},
        )
        if mode == "build":
            for expected in companions:
                verify_record("built tracking companion", expected)
            created = file_record(session.canonical_path(iob), "solver_native_binary")
            if not created["exists"] or created["bytes"] <= 0:
                raise ValueError("tracking model build omitted its actual workbench")
            final_guards = [*read_inputs, created, *companions]
    return iob_execution_path, final_guards


def _fly_and_collect_transport(
    session, *, prepared, records, plan, values, iob, native_guards, solver, audit, limits, allow_asynchronous_io=None
):
    """Read complete final states and publish their small existing analysis closure."""
    import json
    from msplatform.io.manifest_records import file_record

    final_state = session.declare_file(prepared / "results/particle_final_state.csv", "required_evidence")
    session.declare_file(prepared / "results/trajectory_samples.csv", "dense_trajectory")
    metrics, _transmitted = track_transport(
        session,
        workbench=iob,
        fly2=iob.with_suffix(".fly2"),
        run_config=solver / "run_config.lua",
        numerics=values["numerics"],
        source_count=plan["source_count"],
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
        final_state=final_state,
        immutable_input_records=native_guards,
    )
    metrics_path = session.declare_file(session.result_dir / "terminal_plane_metrics.json", "required_evidence")
    with metrics_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(metrics, stream, indent=2, allow_nan=False)
        stream.write("\n")
    data = dict(
        final_state=file_record(session.canonical_path(final_state), "required_evidence"),
        metrics=file_record(session.canonical_path(metrics_path), "required_evidence"),
        preparation_receipt=records["preparation_receipt"],
        source_csv=file_record(
            session.canonical_path(prepared / "input/cylindrical_ion_source.csv"), "required_evidence"
        ),
    )
    metadata = dict(
        backend="simion",
        model="dual_cone_sds_gas_assisted_transport",
        execution_count=plan["source_count"],
        mother_count=plan["source_count"],
        refine_calls=1,
        fly_calls=1,
        independent_stage_publication="not_implemented",
        saved_field_reuse="not_implemented",
        scientific_qualification="not_granted",
    )
    outputs = [session.canonical_path(path) for path in (final_state, metrics_path, audit)]
    outputs.extend(session.canonical_path(path) for path in prepared.rglob("*") if path.is_file())
    outputs = list(dict.fromkeys(outputs))
    return dict(
        status="success",
        summary=metadata,
        output_paths=outputs,
        required_output_paths=[final_state, metrics_path],
        retention_preserve_paths=[],
        manifest_extra_fields={
            "products": {
                "trajectory": dict(
                    schema_version=1, kind="trajectory_result", status="complete", metadata=metadata, data=data
                )
            }
        },
    )


def execute_transport(session, *, request, limits, allow_asynchronous_io=None):
    """Compose explicit backend operations in the same existing managed owner."""
    plan, values, prepared, records, sources, path_helper = _prepare_execution_inputs(session, request=request)
    raw, grid, samples, witnesses, guards, audit = _build_and_audit_fields(
        session,
        prepared=prepared,
        values=values,
        plan=plan,
        sources=sources,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    solver = raw.parent
    iob, native_guards = build_transport_tracking_model(
        session,
        solver=solver,
        raw=raw,
        grid=grid,
        samples=samples,
        witnesses=witnesses,
        guards=guards,
        prepared_records=records,
        sources=sources,
        path_helper=path_helper,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    return _fly_and_collect_transport(
        session,
        prepared=prepared,
        records=records,
        plan=plan,
        values=values,
        iob=iob,
        native_guards=native_guards,
        solver=solver,
        audit=audit,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
