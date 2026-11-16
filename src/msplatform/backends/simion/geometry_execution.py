"""Execute the real geometry plan through the shared admitted run session."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.execution.inputs import freeze_file
from msplatform.io.manifest_records import file_record
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession

from .compiler import CompiledSimionGeometry
from .native_plans import plan_geometry_build
from .native_io import apply_native_io_mode
from .resources import native_resource_path


GEOMETRY_RESOURCES = (
    "gem2pa_geometry.lua", "build_frontend_geometry.lua", "build_geometry_iob.lua", "iob_core.lua",
    "build_flight_tube_variant.lua", "build_detector_variant.lua", "build_reflectron_variant.lua",
)


def execute_geometry(session: RunSession, *, compiled: CompiledSimionGeometry,
                     seed_record: Mapping[str, Any], limits: Mapping[str, Any],
                     allow_asynchronous_io: bool | None = None,
                     surface_validator_record: Mapping[str, Any] | None = None,
                     provider_source_records: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Build raw PA geometry and reopen its IOB; never sample, Refine or Fly.

    The caller admits capacity and supplies tool/engineering limits to the one
    normal owner. A same-projection native reopen does not prove relocation;
    that qualification is deliberately recorded separately.
    """
    from msplatform.io.manifest_records import verify_record

    if not isinstance(compiled, CompiledSimionGeometry):
        raise TypeError("SIMION geometry requires a compiled scientific geometry")
    verify_record("geometry structural seed", dict(seed_record))
    independent_rf = compiled.frontend_geometry.get("role") in {"simion_independent_rf_geometry", "simion_independent_oa_geometry", "simion_rf_ip_geometry", "simion_oa_mr_complete_geometry", "simion_ip_mr_complete_geometry", "simion_rf_oa_geometry", "simion_neutral_world_collision_geometry", "simion_neutral_multi_domain_collision_geometry"}
    names = GEOMETRY_RESOURCES[:4] if independent_rf else GEOMETRY_RESOURCES
    sources = {name: native_resource_path(name) for name in names}
    sources["native_run_path.lua"] = resource_path("native_run_path.lua")
    if compiled.frontend_geometry.get("role") in {"simion_ip_mr_complete_geometry", "simion_neutral_world_collision_geometry", "simion_neutral_multi_domain_collision_geometry"}:
        from . import native_surface_state
        actual = file_record(Path(native_surface_state.__file__).resolve(), "required_evidence")
        if surface_validator_record is None or any(actual[key] != surface_validator_record[key] for key in ("path", "bytes", "sha256")):
            raise ValueError("surface validator source differs from admitted record")
        verify_record("surface validator source", dict(surface_validator_record))
        sources["native_surface_state.py"] = Path(actual["path"])
    elif surface_validator_record is not None:
        raise ValueError("unexpected surface validator record")
    frozen_dir = session.input_dir / "native_sources"
    # Validate the complete pure plan before any materialization or native call.
    plan = plan_geometry_build(compiled, run_directory=session.run_dir,
        seed_record=seed_record, native_path_resource=frozen_dir / "native_run_path.lua")
    operation_ids = tuple(row["operation_id"] for row in plan.operations)
    if operation_ids != session.expected_operation_ids:
        raise ValueError("Geometry plan differs from the owner's admitted operations")

    def owned(path: str | Path, role: str) -> Path:
        path = Path(path)
        if not path.is_absolute() or not session.canonical_path(path).is_relative_to(session.artifact_run_dir):
            raise ValueError("Geometry plan destination escapes its admitted run")
        session.declare_file(path, role)
        return path

    materializations = {owned(path, "required_evidence"): text
                        for path, text in plan.materializations.items()}
    copies = [(row["source_record"], owned(row["destination"], "required_evidence"))
              for row in plan.input_copies]
    controls = {Path(row["outputs"][1]) for row in plan.operations
                if row["operation_id"] == "build_geometry" and len(row["outputs"]) == 2}
    outputs = [owned(path, "required_evidence" if Path(path) in controls or str(path).endswith(("_surface.csv", "_surface_state.json")) else "solver_native_binary")
               for path in plan.declared_outputs]
    optional_surfaces = {row["operation_id"]: owned(row["optional_surface"], "solver_native_binary")
                         for row in plan.operations if "optional_surface" in row}
    for path in outputs:
        if path.name.endswith(".pa#"):
            # Existing GEM transport removes these staging files normally;
            # declare their roles also for interrupted/failed materialization.
            owned(path.with_suffix(".source.gem"), "required_evidence")
            owned(path.with_suffix(".source.processed.gem"), "required_evidence")
    compiled_path = owned(session.input_dir / "compiled_geometry.json", "required_evidence")
    destinations = [*materializations, *(path for _, path in copies), compiled_path,
                    *(frozen_dir / name for name in sources)]
    if len(set(destinations)) != len(destinations) or any(path.exists() for path in destinations + outputs + list(optional_surfaces.values())):
        raise FileExistsError("Geometry action refuses to overwrite any existing input or output")

    def bind(name: str, path: Path) -> dict[str, Any]:
        record = file_record(session.canonical_path(path), "required_evidence")
        session.add_input(name, record)
        return record

    frozen_sources = {}
    source_guards = []
    for name, source in sources.items():
        target = owned(frozen_dir / name, "required_evidence")
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source, target)
        copied = bind("native_source_" + name, target)
        if name == "native_surface_state.py":
            if any(copied[key] != surface_validator_record[key] for key in ("bytes", "sha256")):
                raise ValueError("frozen surface validator differs")
            session.add_input("surface_validator_original", dict(surface_validator_record))
            source_guards.extend([dict(surface_validator_record), copied])
        frozen_sources[str(source)] = str(target)
    if compiled.frontend_geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry':
        from .generic_geometry import multi_domain_source_paths
        expected=multi_domain_source_paths(compiled)
        if not isinstance(provider_source_records, Mapping) or set(provider_source_records)!=set(expected):
            raise ValueError('multi-domain provider source closure differs')
        for name,path in expected.items():
            original=dict(provider_source_records[name]);verify_record('multi-domain provider source',original)
            if Path(original['path']).resolve()!=path.resolve():raise ValueError('multi-domain provider source path differs')
            target=owned(frozen_dir/('provider_'+name.replace('.','_')+'.py'),'required_evidence')
            if target.exists():raise FileExistsError('multi-domain provider source destination exists')
            freeze_file(path,target);copied=bind('provider_source_'+name,target)
            if any(original[k]!=copied[k] for k in ('bytes','sha256')):raise ValueError('multi-domain provider source copy differs')
            source_guards.extend((original,copied))
    elif provider_source_records:
        raise ValueError('unexpected multi-domain provider source records')
    compiled_path.parent.mkdir(parents=True, exist_ok=True)
    with compiled_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(asdict(compiled), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    compiled_record = bind("compiled_geometry", compiled_path)
    for source_record, path in copies:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Recheck the selected identity immediately before the existing copier.
        verify_record("geometry structural seed", dict(source_record))
        freeze_file(Path(source_record["path"]), path)
        copied = bind("structural_seed", path)
        if (copied["bytes"], copied["sha256"]) != (source_record["bytes"], str(source_record["sha256"]).upper()):
            raise AssertionError("Geometry structural seed changed before freezing")
    for ordinal, (path, content) in enumerate(materializations.items(), 1):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        bind("geometry_spec_" + str(ordinal), path)
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    # Tiny neutral seed bootstrap files exist only during the native IOB build.
    seed_path = copies[0][1]
    count = len(compiled.frontend_gems) if independent_rf else 4 + int("entrance_refinement" in compiled.frontend_geometry["numerical_domains"])
    for index in range(1, count + 1):
        owned(seed_path.parent / f"iob_seed_placeholder_{index:02d}.pa0", "solver_native_binary")
    for ordinal, operation in enumerate(plan.operations, 1):
        arguments = apply_native_io_mode(
            [str(session.context.tools["simion"]),
             *(frozen_sources.get(value, value) for value in operation["arguments"])],
            allow_asynchronous_io=allow_asynchronous_io)[1:]
        session.run_process(operation["operation_id"], executable=session.context.tools["simion"],
            arguments=arguments, role=operation["role"], stage=operation["stage"], limits=limits,
            immutable_input_records=source_guards)
        stdout = session.log_dir / f"operation_{ordinal:04d}.stdout.log"
        if operation["success_marker"].encode("ascii") not in stdout.read_bytes():
            raise ValueError("Native geometry completion marker is missing: " + operation["operation_id"])
        if any(not Path(path).is_file() for path in operation["outputs"]):
            raise FileNotFoundError("Native geometry did not produce its declared outputs")
        if operation["operation_id"] in optional_surfaces:
            raw, witness, state_path = map(Path, operation["outputs"])
            state = json.loads(state_path.read_text(encoding="utf8"))
            role = operation["operation_id"].removeprefix("geometry_")
            if compiled.frontend_geometry.get("role") == "simion_neutral_multi_domain_collision_geometry":
                domain = compiled.frontend_geometry["domains"][operation["asset_id"]]
                grid = domain["dimensions"]
                pitch = [domain["pitch_mm"]] * 3
            elif compiled.frontend_geometry.get("role") == "simion_neutral_world_collision_geometry":
                grid = compiled.frontend_geometry["dimensions"]
                pitch = [compiled.frontend_geometry["pitch_mm"]] * 3
            else:
                domain = compiled.frontend_geometry["numerical_domains"][role]
                grid = [domain["dimensions"]["n" + axis] for axis in "xyz"]
                pitch = [domain["cell_mm_xyz"][axis] for axis in "xyz"]
            surface = optional_surfaces[operation["operation_id"]]
            from .native_surface_state import validate_native_surface_state
            native_grid=dict(zip(('nx','ny','nz'),grid,strict=True), **dict(zip(('dx_mm','dy_mm','dz_mm'),pitch,strict=True)))
            if surface.exists() and not surface.is_file():raise ValueError('fractional companion is not a file')
            mode=validate_native_surface_state(state,grid=native_grid,surface_present=surface.is_file())
            if mode=='present':
                if surface.stat().st_size<=0: raise ValueError('fractional surface companion empty')
                outputs.append(surface)
    for record in source_guards:verify_record("surface validator source after geometry", record)
    records = {"compiled_geometry": compiled_record}
    native_assets = {}
    for operation in plan.operations:
        operation_id = operation["operation_id"]
        if operation_id.startswith("geometry_"):
            role = operation.get("asset_id", operation_id.removeprefix("geometry_"))
            member = {}
            paths = list(operation["outputs"])
            if operation_id in optional_surfaces:
                labels = ("raw_geometry", "surface_witnesses", "surface_state")
            elif independent_rf:
                labels = ("raw_geometry", "fractional_surface", "surface_witnesses")
            elif role in {"flight_tube", "detector"}:
                labels = ("raw_geometry", "fractional_surface")
            else:
                labels = ("raw_geometry",)
            if operation_id in optional_surfaces and optional_surfaces[operation_id].is_file():
                paths.append(str(optional_surfaces[operation_id])); labels += ("fractional_surface",)
            for label, path in zip(labels, paths, strict=True):
                key = operation_id.removeprefix("geometry_") + "_" + label
                records[key] = file_record(session.canonical_path(path), "required_evidence" if label in {"surface_witnesses", "surface_state"} else "solver_native_binary")
                member[label] = key
            native_assets[role] = member
        elif operation_id == "build_geometry":
            records["workbench"] = file_record(session.canonical_path(operation["outputs"][0]), "solver_native_binary")
            if len(operation["outputs"]) == 2:
                records["zero_particle_format_control"] = file_record(
                    session.canonical_path(operation["outputs"][1]), "required_evidence")
    metadata = dict(backend="simion", geometry_materialized=True, field_status="not_solved",
        source_status="not_requested", refine_calls=0, fly_calls=0, gui_calls=0,
        provider_content_identities=compiled.provider_content_identities,
        native_assets=native_assets,
        native_reopen="same_execution_projection", relocation_qualification="not_assessed",
        requested_allow_asynchronous_io=allow_asynchronous_io,
        particle_format_control="explicit_zero_beam_native_serialization" if controls else "not_materialized",
        sampled_particles=0,
        scientific_qualification="not_granted")
    return dict(status="success", summary=metadata,
        output_paths=[str(path) for path in outputs], required_output_paths=[str(path) for path in outputs],
        retention_preserve_paths=[],
        manifest_extra_fields={"products": {"geometry": dict(schema_version=1,
            kind="geometry_artifact", status="complete", metadata=metadata, data=records)}})
