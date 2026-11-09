"""Managed dual-cone stages over the existing owner, writer and read contracts."""

from pathlib import Path
import json

from msplatform.execution.inputs import freeze_file
from msplatform.execution.payload_inputs import materialize_payloads
from msplatform.execution.resources import resource_path
from msplatform.io.manifest_records import file_record, verify_record
from .dual_cone_geometry import native_geometry_specification
from .dual_cone_stages import ELECTRODE_IDS, render_model_stage_configuration
from .dual_cone_transport_execution import (
    build_transport_geometry,
    refine_transport_fields,
    _native_operation,
    _write_spec,
)
from .model_execution import _protected_source, _clock_reference
from .resources import native_resource_path, structural_seed_path


def _record(session, path, role="required_evidence"):
    return file_record(session.canonical_path(path), role)


def _write(session, path, content, role="required_evidence"):
    path = session.declare_file(Path(path), role)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return path


def _document(session, name, value):
    path = _write(session, session.input_dir / (name + ".json"), json.dumps(value, indent=2, allow_nan=False) + "\n")
    session.add_input(name, _record(session, path))
    return path


def _sources(session, names):
    result = {}
    for name in names:
        path = session.declare_file(session.input_dir / "native_sources" / name, "required_evidence")
        path.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(native_resource_path(name), path)
        session.add_input("native_" + name, _record(session, path))
        result[name] = path
    path = session.declare_file(session.input_dir / "native_sources/native_run_path.lua", "required_evidence")
    freeze_file(resource_path("native_run_path.lua"), path)
    session.add_input("native_path", _record(session, path))
    result["native_path"] = path
    return result


def _copy_raw(session, product, *, limits):
    selected = {
        name: dict(product.data_records[name], path=str(product.data_path(name)))
        for name in ("raw_geometry", "fractional_surface", "surface_witnesses")
    }
    _protected_source(session, product.reference["manifest"], required_paths=[row["path"] for row in selected.values()])
    solver = session.run_dir / "simion"
    solver.mkdir(parents=True)
    copies = [dict(source_record=row, destination=str(solver / Path(row["path"]).name)) for row in selected.values()]
    rows = materialize_payloads(copies, session=session, operation_id="materialize_geometry", limits=limits)
    return {name: dict(row) for name, row in zip(selected, rows, strict=True)}


def _closed_rows(session, names):
    rows = [row for row in session.operations if row["operation_id"] in names]
    if len(rows) != len(names) or {row["operation_id"] for row in rows} != set(names):
        raise ValueError("stage operation closure is incomplete")
    for row in rows:
        o = row["observation"]
        if (
            o.get("exit_confirmed") is not True
            or o.get("returncode") != 0
            or any(type(o.get(key)) is not int or o[key] <= 0 for key in ("process_id", "process_started_at_utc_ticks"))
        ):
            raise ValueError("stage writer identity/exit is not confirmed")
    return rows


def _publish(session, *, kind, metadata, data, output_paths):
    return dict(
        status="success",
        summary=metadata,
        output_paths=list(output_paths),
        required_output_paths=list(output_paths),
        retention_preserve_paths=[],
        manifest_extra_fields={
            "products": {"stage": dict(schema_version=1, kind=kind, status="complete", metadata=metadata, data=data)}
        },
    )


def _sourcefree_model(session, *, geometry, raw_records, sources, model, limits, allow_asynchronous_io):
    """Use the existing zero-source canonical IOB writer, no dummy particle."""

    solver = Path(raw_records["raw_geometry"]["path"]).parent
    seed = session.declare_file(solver / "seed/one_instance.iob", "required_evidence")
    seed.parent.mkdir()
    freeze_file(structural_seed_path(1), seed)
    session.add_input("structural_seed", _record(session, seed))
    bootstrap = session.declare_file(seed.parent / "iob_seed_placeholder_01.pa0", "solver_native_binary")
    iob = session.declare_file(solver / "model.iob", "solver_native_binary")
    empty = _write(session, solver / "no_particles.fly2", "particles{coordinates=0,}\n")
    session.declare_file(iob.with_suffix(".fly2"), "required_evidence")
    spec = native_geometry_specification(geometry["resolved"], geometry["numerics"], solver)
    row = dict(
        role="dual_cone",
        instance_index=1,
        priority_number=1,
        path=raw_records["raw_geometry"]["path"],
        fractional_surface=raw_records["fractional_surface"]["path"],
        surface_witnesses=raw_records["surface_witnesses"]["path"],
        response_ids=list(ELECTRODE_IDS),
        grid=geometry["grid"],
        physical_samples=spec["physical_samples"],
        rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        placement=dict(x_mm=0, y_mm=0, z_mm=0, az_deg=0, el_deg=0, rt_deg=0, scale=1),
    )
    request = dict(
        schema_version=1,
        role="dual_cone_geometry_iob",
        seed_iob=str(seed),
        output_iob=str(iob),
        bootstrap_paths=[str(bootstrap)],
        instances=[row],
        response_fields=[],
        empty_particle_control=str(empty),
    )
    extra = {}
    if model is not None:
        configuration = _write(
            session, solver / "model_drive_configuration.lua", render_model_stage_configuration(model)
        )
        readback = session.declare_file(session.result_dir / "model_readback.txt", "required_evidence")
        readback.parent.mkdir(parents=True, exist_ok=True)
        request["model"] = dict(
            configuration=str(configuration),
            consumer=str(sources["model_drive.lua"]),
            rf_drive=str(sources["rf_drive.lua"]),
            pulse_hook=str(sources["single_flight_pulse_hook.lua"]),
            waveforms=str(sources["voltage_waveforms.lua"]),
            report=str(readback),
        )
        extra = dict(model_configuration=configuration, model_readback=readback)
    path = _write_spec(session, "sourcefree_model", request)
    guards = [
        *raw_records.values(),
        _record(session, empty),
        _record(session, seed),
        _record(session, path),
        *[_record(session, p) for p in sources.values()],
    ]
    if model is not None:
        guards.append(_record(session, configuration))
    sequence = (
        (
            ("build_model", "build_model", "DUAL_CONE_MODEL_BUILD=PASS"),
            ("verify_model", "verify_model", "DUAL_CONE_MODEL_READBACK=PASS"),
        )
        if model is not None
        else (
            ("build_geometry_model", "build_geometry", "DUAL_CONE_GEOMETRY_IOB=PASS"),
            ("verify_geometry_model", "verify_geometry", "DUAL_CONE_GEOMETRY_IOB_REOPEN=PASS"),
        )
    )
    for index, (operation, mode, marker) in enumerate(sequence):
        _native_operation(
            session,
            operation,
            arguments=[
                "--nogui",
                "--noprompt",
                "lua",
                str(sources["build_model_iob.lua" if model is not None else "build_geometry_iob.lua"]),
                str(path),
                mode,
                str(sources["native_path"]),
            ],
            limits=limits,
            marker=marker,
            immutable_input_records=guards,
            allow_asynchronous_io=allow_asynchronous_io,
        )
        if index == 0:
            # Capture newly closed workbench once; subsequent reads cannot adopt changes.
            guards.extend([_record(session, iob, "solver_native_binary"), _record(session, iob.with_suffix(".fly2"))])
    return dict(workbench=iob, zero_particle_format_control=iob.with_suffix(".fly2"), **extra)


def _freeze_clock(session, model, reference):
    relative = _clock_reference(dict(drive=dict(clock=model["clock"])), reference)
    root = session.input_dir / "clock"
    root.mkdir()
    result = {}
    for label, key, target in [
        ("clock_authority", "contract", root / Path(reference["contract"]["path"]).name),
        ("instrument_epoch", "authority", root / relative),
    ]:
        target = session.declare_file(target, "required_evidence")
        target.parent.mkdir(parents=True, exist_ok=True)
        original = reference[key]
        verify_record(label, original)
        freeze_file(Path(original["path"]), target)
        expected = dict(original, path=str(session.canonical_path(target)))
        verify_record(label, expected)
        session.add_input(label, expected)
        result[label] = target
    return result


def execute_geometry(session, *, plan, limits, allow_asynchronous_io):
    geometry = plan["projection"]
    sources = _sources(
        session, ("build_frontend_geometry.lua", "gem2pa_geometry.lua", "build_geometry_iob.lua", "iob_core.lua")
    )
    solver = session.run_dir / "simion"
    solver.mkdir()
    gem = _write(session, solver / "dual_cone_tandem.gem", geometry["gem"])
    session.add_input("geometry_gem", _record(session, gem))
    spec = native_geometry_specification(geometry["resolved"], geometry["numerics"], solver)
    raw = Path(spec["output"])
    for suffix in (".source.gem", ".source.processed.gem"):
        session.declare_file(raw.with_suffix(suffix), "required_evidence")
    build_transport_geometry(
        session,
        builder=sources["build_frontend_geometry.lua"],
        specification=spec,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    records = {
        name: _record(session, path, role)
        for name, path, role in (
            ("raw_geometry", raw, "solver_native_binary"),
            ("fractional_surface", Path(spec["fractional_surface"]), "solver_native_binary"),
            ("surface_witnesses", Path(spec["surface_witnesses"]), "required_evidence"),
        )
    }
    companions = _sourcefree_model(
        session,
        geometry=geometry,
        raw_records=records,
        sources=sources,
        model=None,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    projection = _document(session, "compiled_geometry", geometry)
    receipts = _write(
        session,
        session.result_dir / "native_stage_receipts.json",
        json.dumps(_closed_rows(session, plan["expected_operation_ids"])) + "\n",
    )
    paths = dict(
        compiled_geometry=projection,
        native_stage_receipts=receipts,
        **{k: Path(v["path"]) for k, v in records.items()},
        **companions,
    )
    data = {
        k: _record(
            session,
            p,
            "solver_native_binary" if k in {"raw_geometry", "fractional_surface", "workbench"} else "required_evidence",
        )
        for k, p in paths.items()
    }
    return _publish(
        session,
        kind="geometry_artifact",
        metadata=dict(
            backend="simion",
            domain_id="dual_cone",
            geometry_materialized=True,
            sampled_particles=0,
            source_status="not_requested",
            field_status="not_solved",
        ),
        data=data,
        output_paths=list(paths.values()),
    )


def execute_model(session, *, source, model, clock_reference, limits, allow_asynchronous_io):
    from .model_execution import MODEL_RESOURCES

    sources = _sources(session, MODEL_RESOURCES)
    records = _copy_raw(session, source, limits=limits)
    clocks = _freeze_clock(session, model, clock_reference)
    companions = _sourcefree_model(
        session,
        geometry=model["geometry"],
        raw_records=records,
        sources=sources,
        model=model,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    projection = _document(session, "compiled_model", model)
    receipts = _write(
        session,
        session.result_dir / "native_stage_receipts.json",
        json.dumps(_closed_rows(session, session.expected_operation_ids)) + "\n",
    )
    paths = dict(
        compiled_model=projection,
        native_stage_receipts=receipts,
        **clocks,
        **{k: Path(v["path"]) for k, v in records.items()},
        **companions,
    )
    data = {
        k: _record(
            session,
            p,
            "solver_native_binary" if k in {"raw_geometry", "fractional_surface", "workbench"} else "required_evidence",
        )
        for k, p in paths.items()
    }
    return _publish(
        session,
        kind="prepared_model",
        metadata=dict(
            backend="simion",
            domain_id="dual_cone",
            geometry_materialized=True,
            drive_configured=True,
            sampled_particles=0,
            source_status="not_requested",
            field_status="not_solved",
        ),
        data=data,
        output_paths=list(paths.values()),
    )


def execute_fields(
    session, *, source, model, numerics, limits, allow_asynchronous_io, reuse_source=None, reuse_producer=None
):
    from .dual_cone_stages import plan_fields_stage

    sources = _sources(session, ("refine_rf_field_family.lua", "audit_rf_field_family.lua"))
    if reuse_source is None:
        records = _copy_raw(session, source, limits=limits)
    else:
        records = {
            name: dict(source.data_records[name], path=str(source.data_path(name)))
            for name in ("raw_geometry", "fractional_surface", "surface_witnesses")
        }
        _protected_source(
            session, source.reference["manifest"], required_paths=[row["path"] for row in records.values()]
        )
    raw = Path(records["raw_geometry"]["path"])
    solver = raw.parent
    # Preserve the model clock's original contract/authority bytes and relative pointer.
    clock_contract = source.data_path("clock_authority")
    clocks = _freeze_clock(
        session,
        model,
        dict(
            contract=dict(source.data_records["clock_authority"], path=str(clock_contract)),
            authority=dict(source.data_records["instrument_epoch"], path=str(source.data_path("instrument_epoch"))),
            data_root=str(clock_contract.parent),
        ),
    )
    implementation = dict(
        simion=file_record(session.context.tools["simion"], "required_evidence"),
        refiner=_record(session, sources["refine_rf_field_family.lua"]),
        auditor=_record(session, sources["audit_rf_field_family.lua"]),
    )
    selected = plan_fields_stage(
        model,
        numerics=numerics,
        raw_records=records,
        implementation_records=implementation,
        reuse_reference=None if reuse_source is None else reuse_source.reference,
    )
    external = {}
    if reuse_source is None:
        responses = refine_transport_fields(
            session,
            refiner=sources["refine_rf_field_family.lua"],
            raw=raw,
            refinement=selected["spatial_identity"]["refinement"],
            limits=limits,
            allow_asynchronous_io=allow_asynchronous_io,
        )
        for label, record in records.items():
            verify_record(label, record)
        family = [raw, raw.with_suffix(".pa-surf"), *responses]
        guards = [_record(session, path, "solver_native_binary") for path in family] + [records["surface_witnesses"]]
    else:
        keys = [
            "family_raw",
            "family_surface",
            "family_carrier",
            "surface_witnesses",
            *["response_" + str(eid) for eid in ELECTRODE_IDS],
        ]
        external = {
            name: dict(reuse_producer.data_records[name], path=str(reuse_producer.data_path(name))) for name in keys
        }
        for selected_source in (reuse_source, reuse_producer):
            _protected_source(
                session,
                selected_source.reference["manifest"],
                required_paths=[row["path"] for row in external.values()],
            )
        for name, record in external.items():
            session.add_input("original_basis_" + name, record)
        raw = Path(external["family_raw"]["path"])
        solver = raw.parent
        records["surface_witnesses"] = external["surface_witnesses"]
        family = [Path(row["path"]) for name, row in external.items() if name != "surface_witnesses"]
        guards = list(external.values())
    spec = native_geometry_specification(model["geometry"]["resolved"], model["geometry"]["numerics"], solver)
    audit = session.declare_file(session.result_dir / "field_audit.json", "required_evidence")
    audit.parent.mkdir(exist_ok=True)
    request = _write_spec(
        session,
        "field_audit",
        dict(
            assets=[
                dict(
                    domain_id="dual_cone",
                    carrier_path=str(raw.with_suffix(".pa0")),
                    family_paths=[str(p) for p in family],
                    response_ids=list(ELECTRODE_IDS),
                    grid=model["geometry"]["grid"],
                    physical_samples=spec["physical_samples"],
                    surface_witnesses=records["surface_witnesses"]["path"],
                )
            ],
            output=str(audit),
        ),
    )
    _native_operation(
        session,
        "audit_fields",
        arguments=["--nogui", "--noprompt", "lua", str(sources["audit_rf_field_family.lua"]), str(request)],
        limits=limits,
        marker="INDEPENDENT_RF_FIELDS_READBACK=PASS",
        immutable_input_records=guards,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    actual = json.loads(audit.read_text())
    if actual.get("status") != "success" or actual.get("checked_domains") != ["dual_cone"]:
        raise ValueError("field audit did not close the actual dual-cone domain")
    projection = _document(session, "compiled_model", model)
    receipts = dict(
        field_audit_receipts=_write(
            session,
            session.result_dir / "field_audit_receipts.json",
            json.dumps(_closed_rows(session, ["audit_fields"])) + "\n",
        )
    )
    if reuse_source is None:
        receipts["field_native_receipts"] = _write(
            session,
            session.result_dir / "field_native_receipts.json",
            json.dumps(_closed_rows(session, ["refine_fields"])) + "\n",
        )
    else:
        receipts["field_native_receipts"] = reuse_producer.data_path("field_native_receipts")
        external["field_native_receipts"] = dict(
            reuse_producer.data_records["field_native_receipts"], path=str(receipts["field_native_receipts"])
        )
        session.add_input("original_basis_refine_receipts", external["field_native_receipts"])
    paths = dict(
        compiled_model=projection,
        field_audit=audit,
        **clocks,
        **receipts,
        family_raw=raw,
        family_surface=raw.with_suffix(".pa-surf"),
        family_carrier=raw.with_suffix(".pa0"),
        surface_witnesses=Path(records["surface_witnesses"]["path"]),
        **{"response_" + str(eid): raw.with_suffix(".pa" + str(eid)) for eid in ELECTRODE_IDS},
    )
    data = {
        k: external[k]
        if k in external
        else _record(
            session, p, "solver_native_binary" if k.startswith(("family_", "response_")) else "required_evidence"
        )
        for k, p in paths.items()
    }
    return _publish(
        session,
        kind="field_bundle",
        metadata=dict(
            backend="simion",
            domain_id="dual_cone",
            sampled_particles=0,
            source_status="not_requested",
            field_status="available",
            field_representation="producer_owned_dual_cone_fractional_family",
            spatial_identity=selected["spatial_identity"],
            fields_reused=reuse_source is not None,
            refine_calls=0 if reuse_source is not None else 1,
            **({} if reuse_source is None else dict(family_producer_reference=reuse_producer.reference)),
        ),
        data=data,
        output_paths=[p for p in paths.values() if session.canonical_path(p).is_relative_to(session.artifact_run_dir)],
    )


def execute_saved_fly(session, *, fields, producer, plan, request, model, limits, allow_asynchronous_io):
    """Track over original published fields directly; never copy or Refine them."""
    from .dual_cone_transport_execution import (
        _prepare_execution_inputs,
        build_transport_tracking_model,
        _fly_and_collect_transport,
    )

    names = [
        "family_raw",
        "family_surface",
        "family_carrier",
        "surface_witnesses",
        *["response_" + str(eid) for eid in ELECTRODE_IDS],
    ]
    guards = [dict(producer.data_records[name], path=str(producer.data_path(name))) for name in names]
    for selected in (fields, producer):
        _protected_source(session, selected.reference["manifest"], required_paths=[row["path"] for row in guards])
    from msplatform.results.gas_field import read_gas_field

    gas = read_gas_field(request["gas_field_reference"])
    request = dict(request)
    request["resolved_path"] = _document(session, "saved_field_geometry", model["geometry"]["resolved"])
    science = dict(
        schema_version=1,
        role="dual_cone_simion_ion_transport_science",
        project_id="dual_cone_tandem_quadrupole_ion_interface",
        trajectory_authority="simion",
        gas=request.pop("collision_science"),
        electric_field=model["electric_field"],
    )
    request["science_path"] = _document(session, "saved_model_transport_science", science)
    request["gas_science_path"] = gas.data_path("science")
    _, values, prepared, records, sources, path_helper = _prepare_execution_inputs(
        session, request=request, selected_plan=plan, model_projection=model
    )
    clock_contract = fields.data_path("clock_authority")
    clocks = _freeze_clock(
        session,
        model,
        dict(
            contract=dict(fields.data_records["clock_authority"], path=str(clock_contract)),
            authority=dict(fields.data_records["instrument_epoch"], path=str(fields.data_path("instrument_epoch"))),
            data_root=str(clock_contract.parent),
        ),
    )
    records.update({name: _record(session, path) for name, path in clocks.items()})
    raw = producer.data_path("family_raw")
    solver = prepared / "solver/simion"
    spec = native_geometry_specification(model["geometry"]["resolved"], model["geometry"]["numerics"], solver)
    iob, native_guards = build_transport_tracking_model(
        session,
        solver=solver,
        raw=raw,
        grid=model["geometry"]["grid"],
        samples=spec["physical_samples"],
        witnesses=producer.data_path("surface_witnesses"),
        guards=guards,
        prepared_records=records,
        sources=sources,
        path_helper=path_helper,
        limits=limits,
        allow_asynchronous_io=allow_asynchronous_io,
    )
    # Copy only the small audit evidence, never a published native PA member.
    audit = session.declare_file(session.input_dir / "selected_field_audit.json", "required_evidence")
    original = dict(fields.data_records["field_audit"], path=str(fields.data_path("field_audit")))
    verify_record("selected field audit", original)
    freeze_file(Path(original["path"]), audit)
    verify_record("copied selected field audit", dict(original, path=str(session.canonical_path(audit))))
    result = _fly_and_collect_transport(
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
    metadata = result["summary"]
    metadata.update(
        refine_calls=0,
        geometry_build_calls=0,
        saved_field_reuse=True,
        field_recomputed=False,
        fields_reference=fields.reference,
        family_producer_reference=producer.reference,
        independent_stage_publication="stage_specific",
    )
    result["manifest_extra_fields"]["products"]["trajectory"]["metadata"] = metadata
    for record in guards:
        verify_record("original published basis after Fly", record)
    return result
