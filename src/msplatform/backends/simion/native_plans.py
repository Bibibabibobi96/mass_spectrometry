"""Real SIMION operation plans; the existing execution owner alone runs/publishes."""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

from .artifacts import NativeStagePlan
from .compiler import CompiledSimionGeometry
from .fields import prepare_field_design
from .field_identity import frontend_field_identity, working_point_member_id, _require_sha256, render_audit_spec
from .resources import native_resource_path, STRUCTURAL_SEEDS
from .source import lua_value, render_restart_fly2


def rigid_iob_placement(transform, *, origin_mm=(0., 0., 0.)):
    """Project the existing proper-rotation convention to official IOB controls.

    This is the single representation conversion used by RF and dual-cone;
    scientific position/vector transforms remain owned by RigidTransform.
    """
    from msplatform.contracts.rigid_transform import RigidTransform

    RigidTransform.from_contract(transform)
    rotation, translation = transform['rotation'], transform['translation_mm']
    cos_el = math.hypot(rotation[0][0], rotation[2][0])
    el = math.atan2(rotation[1][0], cos_el)
    if cos_el > 0.:
        az, rt = math.atan2(-rotation[2][0], rotation[0][0]), math.atan2(-rotation[1][2], rotation[1][1])
    else:
        az, rt = math.atan2(rotation[0][2], rotation[2][2]), 0.
    world_origin = [sum(rotation[a][k] * origin_mm[k] for k in range(3)) + translation[a] for a in range(3)]
    return dict(zip(('x_mm', 'y_mm', 'z_mm'), world_origin, strict=True),
                az_deg=math.degrees(az), el_deg=math.degrees(el), rt_deg=math.degrees(rt),
                scale=1., ox=0., oy=0., oz=0.)


def _operation(name: str, stage: str, arguments: list[str], outputs: list[str], marker: str) -> dict:
    return dict(operation_id=name, role="SIMION", stage=stage,
        arguments=["--nogui", "--noprompt", *arguments], outputs=outputs, success_marker=marker)


def _absolute(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("native plan destinations must be explicit absolute paths")
    return path


def _native_ascii(path: Path) -> Path:
    """Consume the existing owner's projection; never invent another alias."""
    path=_absolute(path)
    if not str(path).isascii():
        raise ValueError("Lua path transport requires the public owner's ASCII native projection")
    return path


def plan_geometry_build(compiled: CompiledSimionGeometry, *, run_directory: Path,
                        seed_record: Mapping[str, Any], native_path_resource: Path) -> NativeStagePlan:
    """Plan actual raw builds and source-free IOB save/reopen, without writing.

    The supplied structural seed is copied by the admitted owner. Only the
    reviewed Git-controlled four/five-slot seed identities are accepted; no
    author PA is bundled. Tiny neutral placeholders are made privately by Lua.
    Native validation of those seeds remains an explicit subsequent action.
    """
    root = _native_ascii(run_directory)
    path_resource = _native_ascii(native_path_resource)
    if compiled.frontend_geometry.get("role") in {"simion_independent_rf_geometry", "simion_independent_oa_geometry"}:
        return _plan_rf_geometry_build(compiled, root, seed_record, path_resource)
    domains = compiled.frontend_geometry["numerical_domains"]
    count = 4 + int("entrance_refinement" in domains)
    if (seed_record.get("bytes"), str(seed_record.get("sha256", "")).lower()) != STRUCTURAL_SEEDS[count]:
        raise ValueError("geometry bootstrap requires the reviewed structural seed identity")
    _absolute(Path(seed_record["path"]))
    materializations, operations, rows = {}, [], {}
    empty_control = root / "inputs/no_particles.fly2"
    materializations[str(empty_control)] = render_restart_fly2([])
    specs = {s["role"]:s for s in compiled.downstream_specs}
    projection = root / "inputs/downstream_projection.lua"
    # Existing downstream builders consume the exact legacy projection shape.
    physical = dict(simion={role:specs[role]["template_variables"]["component"]
                           for role in ("flight_tube", "reflectron")})
    detector = specs["detector"]["template_variables"]
    physical["simion"]["detector_marker"] = dict(
        cell_xy_mm=detector["mmgu_xy"], cell_z_mm=detector["mmgu_z"], active_radius_mm=detector["radius"],
        absorber_thickness_mm=detector["absorber_thickness"], front_margin_z_mm=detector["front_margin_z"],
        back_margin_z_mm=detector["back_margin_z"])
    # Full original build preconditions need these values, not a fake resolved design.
    contract = compiled.frontend_geometry.get("downstream_build_contract")
    if contract is None:
        raise ValueError("compiled geometry lacks the actual downstream build contract")
    materializations[str(projection)] = "return " + lua_value(dict(contract, physical_geometry=physical)) + "\n"
    for spec in compiled.downstream_specs:
        role = spec["role"]
        gem, raw = root/"inputs"/(role+".gem"), root/"simion/geometry"/(role+".pa#")
        materializations[str(gem)] = spec["template_text"]
        builder = native_resource_path("build_"+("reflectron" if role=="reflectron" else role)+"_variant.lua")
        surfaces = [str(raw.with_suffix(".pa-surf"))] if role != "reflectron" else []
        operations.append(_operation("geometry_"+role, "prepare",
            ["lua",str(builder),str(gem),str(raw),str(projection),"geometry-only"],
            [str(raw),*surfaces], "BUILD_GEOMETRY=PASS ROLE="+role))
        instance = spec["native_instance"]
        mesh = contract["simion_geometry_build"][role]
        cells = ([detector["mmgu_xy"],detector["mmgu_xy"],detector["mmgu_z"]] if role=="detector"
                 else [mesh["cell_axial_mm"],mesh["cell_radial_mm"],mesh["cell_radial_mm"]])
        rows[role] = dict(role=role, path=str(raw),
            grid={**{k:instance[k] for k in ("nx","ny","nz")},
                  **dict(zip(("dx_mm","dy_mm","dz_mm"),cells,strict=True))},
            placement=dict(x_mm=instance["x_mm"],y_mm=instance["y_mm"],z_mm=instance["z_mm"],
                           az_deg=instance["az_deg"],el_deg=0.,rt_deg=0.,scale=1.))
    for name, domain in domains.items():
        gem, raw = root/"inputs"/("frontend_"+name+".gem"), root/"simion/geometry"/("frontend_"+name+".pa#")
        materializations[str(gem)] = compiled.frontend_gems[name]
        grid = dict(domain["dimensions"], **{f"d{a}_mm":domain["cell_mm_xyz"][a] for a in "xyz"})
        audit = root/"inputs"/("frontend_"+name+"_build.lua")
        materializations[str(audit)] = "return " + lua_value(dict(schema_version=1,
            role="simion_frontend_raw_geometry",domain_id=name,gem=str(gem),output=str(raw),grid=grid,
            physical_samples=compiled.frontend_geometry["raw_physical_samples"][name])) + "\n"
        operations.append(_operation("geometry_"+name, "prepare",
            ["lua",str(native_resource_path("build_frontend_geometry.lua")),str(audit)],
            [str(raw)], "BUILD_GEOMETRY=PASS ROLE="+name))
        role = "accelerator" if name=="parent" else name
        rows[role] = dict(role=role,path=str(raw),grid=grid,
            placement=dict(**{a+"_mm":domain["instance_origin_mm"][a] for a in "xyz"},
                           az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.))
    ordered = [rows[role] for role in ("flight_tube","reflectron","accelerator","detector",
                                      *(("entrance_refinement",) if count==5 else ()))]
    for index,row in enumerate(ordered,1):
        row.update(instance_index=index,priority_number=index)
    seed = root/"simion/geometry/iob_seed"/(str(count)+"_instance_seed.iob")
    iob = root/"simion/geometry/geometry.iob"
    spec_path = root/"inputs/geometry_iob.lua"
    materializations[str(spec_path)] = "return " + lua_value(dict(schema_version=1,
        role="single_reflection_iob_build",instances=ordered,seed_iob=str(seed),output_iob=str(iob),
        empty_particle_control=str(empty_control),
        bootstrap_paths=[str(seed.parent/f"iob_seed_placeholder_{i:02d}.pa0") for i in range(1,count+1)])) + "\n"
    for mode in ("build_geometry","verify_geometry"):
        operations.append(_operation(mode,"prepare",["lua",str(native_resource_path("build_geometry_iob.lua")),
            str(spec_path),mode,str(path_resource)], [str(iob),str(iob.with_suffix(".fly2"))] if mode=="build_geometry" else [],
            "SINGLE_REFLECTION_GEOMETRY_IOB"+("_REOPEN" if mode=="verify_geometry" else "")+"=PASS"))
    outputs = tuple(dict.fromkeys(path for op in operations for path in op["outputs"]))
    return NativeStagePlan(materializations,(dict(source_record=dict(seed_record),destination=str(seed)),),
                           tuple(operations),outputs)


def _plan_rf_geometry_build(compiled, root, seed_record, path_resource):
    """Use the same native owner and IOB transport for independent RF arrays."""
    geometry = compiled.frontend_geometry
    names = geometry['composition_plan']['scope']['instance_ids']
    count = len(names)
    if count not in STRUCTURAL_SEEDS or (seed_record.get('bytes'), str(seed_record.get('sha256', '')).lower()) != STRUCTURAL_SEEDS[count]:
        raise ValueError('RF geometry requires the registered matching structural seed')
    _absolute(Path(seed_record['path']))
    poses = {row['instance_id']: row['transform'] for row in geometry['composition_plan']['recipe']['instances']}
    materializations, operations, instances = {}, [], []
    for index, name in enumerate(names, 1):
        domain = geometry['numerical_domains'][name]
        grid = dict(domain['dimensions'], **{'d'+axis+'_mm': domain['cell_mm_xyz'][axis] for axis in 'xyz'})
        raw = root/'simion/geometry'/(name+'.pa#')
        surface, witnesses = raw.with_suffix('.pa-surf'), root/'results'/(name+'_surface.csv')
        gem, audit = root/'inputs'/(name+'.gem'), root/'inputs'/(name+'_build.lua')
        materializations[str(gem)] = compiled.frontend_gems[name]
        samples = geometry['raw_physical_samples'][name]
        if not samples or not any(row.get('metal') is False for row in samples):
            raise ValueError('RF geometry requires physical metal and vacuum witnesses')
        materializations[str(audit)] = 'return '+lua_value(dict(schema_version=1,
            role='simion_frontend_raw_geometry', domain_id=name, gem=str(gem), output=str(raw), grid=grid,
            physical_samples=samples, fractional_surface=str(surface), surface_witnesses=str(witnesses)))+'\n'
        operations.append(_operation('geometry_'+name,'prepare',
            ['lua',str(native_resource_path('build_frontend_geometry.lua')),str(audit)],
            [str(raw),str(surface),str(witnesses)],'BUILD_GEOMETRY=PASS ROLE='+name))
        transform = poses[name]
        rotation = transform['rotation']
        placement = rigid_iob_placement(transform, origin_mm=[domain['instance_origin_mm'][axis] for axis in 'xyz'])
        instances.append(dict(role=name, instance_index=index, priority_number=index, path=str(raw),
            fractional_surface=str(surface), surface_witnesses=str(witnesses),grid=grid,
            physical_samples=samples, rotation=rotation,
            placement=placement))
    control = root/'inputs/no_particles.fly2'
    materializations[str(control)] = render_restart_fly2([])
    seed = root/'simion/geometry/iob_seed'/(str(count)+'_instance_seed.iob')
    iob = root/'simion/geometry/geometry.iob'
    spec = root/'inputs/geometry_iob.lua'
    materializations[str(spec)] = 'return '+lua_value(dict(schema_version=1,role=('independent_oa_geometry_iob_build' if geometry['role']=='simion_independent_oa_geometry' else 'independent_rf_geometry_iob_build'),
        instances=instances, seed_iob=str(seed),output_iob=str(iob),empty_particle_control=str(control),
        bootstrap_paths=[str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,count+1)]))+'\n'
    for mode in ('build_geometry','verify_geometry'):
        operations.append(_operation(mode,'prepare',['lua',str(native_resource_path('build_geometry_iob.lua')),
            str(spec),mode,str(path_resource)], [str(iob),str(iob.with_suffix('.fly2'))] if mode=='build_geometry' else [],
            ('INDEPENDENT_OA_GEOMETRY_IOB' if geometry['role']=='simion_independent_oa_geometry' else 'INDEPENDENT_RF_GEOMETRY_IOB')+('_REOPEN' if mode=='verify_geometry' else '')+'=PASS'))
    outputs = tuple(dict.fromkeys(path for op in operations for path in op['outputs']))
    return NativeStagePlan(materializations,(dict(source_record=dict(seed_record),destination=str(seed)),),tuple(operations),outputs)


def plan_model_preparation(model, *, geometry_assets: Mapping[str, dict], run_directory: Path,
                           seed_record: Mapping[str, Any], native_path_resource: Path) -> NativeStagePlan:
    """Declare owned raw-geometry copies and two unsolved model operations.

    The existing geometry compiler's IOB projection is reused, not its GEM2PA
    operations. Input copies are declarations for the admitted payload owner;
    this pure function never copies a PA or opens a source workbench.
    """
    from .model import model_geometry, render_model_configuration

    compiled = model_geometry(model)
    root = _native_ascii(run_directory)
    independent_component = compiled.frontend_geometry.get('role') in {'simion_independent_rf_geometry', 'simion_independent_oa_geometry'}
    expected = (set(compiled.frontend_geometry['numerical_domains']) if independent_component else
                {'flight_tube', 'reflectron', 'detector', *compiled.frontend_geometry['numerical_domains']})
    if set(geometry_assets) != expected:
        raise ValueError('model geometry assets differ from complete selected scope')
    projection = plan_geometry_build(compiled, run_directory=root, seed_record=seed_record,
        native_path_resource=native_path_resource)
    copies = []
    for operation in projection.operations:
        if not operation['operation_id'].startswith('geometry_'):
            continue
        domain = operation['operation_id'].removeprefix('geometry_')
        rows = geometry_assets[domain]
        if set(rows) != ({'raw_record', 'surface_records', 'witness_record'} if independent_component else {'raw_record', 'surface_records'}):
            raise ValueError('model geometry requires explicit raw and surface records')
        records = [rows['raw_record'], *rows['surface_records'], *([rows['witness_record']] if independent_component else [])]
        if len(records) != len(operation['outputs']):
            raise ValueError('model geometry fractional surface closure differs')
        for record, destination in zip(records, operation['outputs'], strict=True):
            source = _absolute(Path(record['path']))
            suffix = '.csv' if destination.endswith('.csv') else '.pa#' if destination.endswith('.pa#') else '.pa-surf'
            if not str(source).lower().endswith(suffix) or type(record.get('bytes')) is not int or record['bytes'] <= 0:
                raise ValueError('model geometry must preserve positive raw/surface representation')
            _require_sha256(record.get('sha256'), 'model raw geometry')
            copies.append(dict(source_record=copy.deepcopy(record), destination=destination))
    configuration = root / 'inputs/model_drive_configuration.lua'
    spec_path = root / 'inputs/geometry_iob.lua'
    readback = root / 'results/model_drive_readback.txt'
    sources = root / 'inputs/native_sources'
    native = dict(configuration=str(configuration), report=str(readback),
        consumer=str(sources/'model_drive.lua'), rf_drive=str(sources/'rf_drive.lua'),
        pulse_hook=str(sources/'single_flight_pulse_hook.lua'), waveforms=str(sources/'voltage_waveforms.lua'))
    original = projection.materializations[str(spec_path)]
    if not original.startswith('return '):
        raise ValueError('canonical IOB specification representation differs')
    empty_control = root/'inputs/no_particles.fly2'
    materializations = {str(empty_control): projection.materializations[str(empty_control)],
        str(configuration): render_model_configuration(model),
        str(spec_path): 'local spec=' + original.removeprefix('return ') + '\nspec.model=' + lua_value(native) + '\nreturn spec\n'}
    native_operations = tuple(_operation(mode, 'prepare', ['lua', str(native_resource_path('build_model_iob.lua')),
        str(spec_path), mode, str(_native_ascii(native_path_resource))],
        [str(root/'simion/geometry/geometry.iob'), str(root/'simion/geometry/geometry.fly2')] if mode == 'build_model' else [str(readback)],
        ('INDEPENDENT_OA_MODEL_' if compiled.frontend_geometry.get('role') == 'simion_independent_oa_geometry' else 'INDEPENDENT_RF_MODEL_' if independent_component else 'SINGLE_REFLECTION_MODEL_') + ('BUILD' if mode == 'build_model' else 'READBACK') + '=PASS')
        for mode in ('build_model', 'verify_model'))
    materialization = dict(operation_id='materialize_geometry', role='GATE', stage='prepare',
        action='explicit_geometry_payload_callback', outputs=[row['destination'] for row in copies])
    operations = (materialization, *native_operations)
    declared = tuple(dict.fromkeys(path for operation in operations for path in operation['outputs']))
    return NativeStagePlan(materializations, tuple([*projection.input_copies, *copies]), operations, declared)


def plan_solve_fields(model, components_resolved=None, *, drive=None, numerics: dict) -> dict:
    """Plan from the sole prepared-model drive; legacy callers are explicit adapters.

    The former geometry+resolved draft call delegates its original contract to
    plan_legacy_solve_fields. New models never accept a second drive authority.
    """
    from .artifacts import CompiledPreparedModel
    from .model import model_geometry, require_prepared_model

    if isinstance(model, CompiledSimionGeometry):
        return plan_legacy_solve_fields(model, components_resolved, drive=drive, numerics=numerics)
    if not isinstance(model, CompiledPreparedModel) or components_resolved is not None or drive is not None:
        raise ValueError('model field planning rejects a competing provider/drive')
    document = require_prepared_model(model)
    geometry = model_geometry(model)
    from .frontend import native_frontend_instances
    multipoles, tof = native_frontend_instances(geometry.frontend_geometry['composition_plan'])
    expected = {'frontend_domains', 'rf_reference_voltage_v'} if multipoles else {'frontend_domains'}
    if set(numerics) != expected:
        raise ValueError('model field numerics fields differ')
    components = document['components_resolved']
    physics = document['physics']
    design = prepare_field_design({name:components[name] for name in multipoles}, components[tof],
        geometry.frontend_geometry, variant_id=geometry.frontend_geometry['composition_plan']['components'][tof]['variant_id'],
        pulse_voltage_policy_id=physics['pulse_voltage_policy_id'], boundary_policy=physics['boundary_policy'],
        frontend_domains=numerics['frontend_domains'], rf_reference_voltage_v=numerics.get('rf_reference_voltage_v'),
        flight={'pulse':document['drive']['pulse']}, electrical_projection=document['electrical_projection'])
    result = _field_plan(model_geometry(model, downstream_drive=True), design)
    result['model_identity_sha256'] = document['model_identity_sha256']
    return result


def plan_legacy_solve_fields(compiled: CompiledSimionGeometry, components_resolved: Mapping[str, dict], *,
                      drive: dict, numerics: dict) -> dict:
    """Resolve actual voltage math/order; cache ownership remains with execution."""
    from .frontend import native_frontend_instances
    multipoles, tof = native_frontend_instances(compiled.frontend_geometry["composition_plan"])
    required_drive = {"pulse_voltage_policy_id", *({"rf_reference_voltage_v"} if multipoles else set())}
    if set(drive) != required_drive or set(numerics) != {"boundary_policy","frontend_domains"}:
        raise ValueError("field drive/numerics fields differ")
    design = prepare_field_design({name:components_resolved[name] for name in multipoles},components_resolved[tof],
        compiled.frontend_geometry,variant_id=compiled.frontend_geometry["composition_plan"]["components"][tof]["variant_id"],
        pulse_voltage_policy_id=drive["pulse_voltage_policy_id"],boundary_policy=numerics["boundary_policy"],
        frontend_domains=numerics["frontend_domains"],rf_reference_voltage_v=drive.get("rf_reference_voltage_v"))
    return _field_plan(compiled, design)


def _field_plan(compiled: CompiledSimionGeometry, design: dict) -> dict:
    from .field_validation import require_supported_split_interfaces
    require_supported_split_interfaces(compiled.frontend_geometry, design)
    members=[]
    for domain in design["domains"]:
        domain["gem_sha256"]=hashlib.sha256(compiled.frontend_gems[domain["domain_id"]].encode("utf-8")).hexdigest()
        for point in design["working_points"]:
            member=working_point_member_id(point)
            members.append(dict(domain_id=domain["domain_id"],member_id=member,
                requires_published_parent=(member if domain["domain_id"]=="entrance_refinement" else None)))
    return dict(field_design=design,ordered_members=members,downstream_specs=copy.deepcopy(compiled.downstream_specs))


def operating_member_identity(plan: dict, *, domain_id: str, member_id: str,
                              tool_identity: dict, published_parent: dict | None = None) -> dict:
    """Bind real tool and same-member parent identities before any cache key."""
    if set(tool_identity) != {"simion_identity","builder_identity"}:
        raise ValueError("actual SIMION and builder identities are required")
    native=tool_identity["simion_identity"]
    if (native.get("release") != "SIMION 2020" or type(native.get("executable_bytes")) is not int
            or native["executable_bytes"] <= 0):
        raise ValueError("invalid admitted SIMION identity")
    _require_sha256(native.get("executable_sha256"),"SIMION executable")
    if set(tool_identity["builder_identity"]) != {"operating_builder","exporter"}:
        raise ValueError("operating builder and exporter identities are required")
    for name,digest in tool_identity["builder_identity"].items():
        _require_sha256(digest,name)
    if domain_id=="entrance_refinement":
        if not published_parent or working_point_member_id(published_parent["record"]) != member_id:
            raise ValueError("fine domain requires its actual published same-member parent")
        parents={member_id:published_parent}
    else:
        if published_parent is not None:
            raise ValueError("parent solve cannot depend on another parent response")
        parents=None
    return dict(frontend_field_identity(plan["field_design"],domain_id,
        member_id=member_id,parent_fields=parents),**copy.deepcopy(tool_identity))


def plan_operating_member(plan: dict, *, domain_id: str, member_id: str,
                          tool_identity: dict, raw_geometry_record: dict,
                          working_directory: Path, payload_directory: Path,
                          resource_paths: Mapping[str, Path],
                          published_parent: dict | None = None) -> tuple[NativeStagePlan, dict]:
    """Plan one real cache-miss member in the existing transaction's directories.

    Resource paths and admitted tool identities are explicit. This does not
    begin a cache transaction, infer a hit, publish a generation or reserve
    capacity. The caller binds those facts through the existing owner.
    """
    identity=operating_member_identity(plan,domain_id=domain_id,member_id=member_id,
        tool_identity=tool_identity,published_parent=published_parent)
    if set(resource_paths) != {"operating_builder","exporter","verifier"}:
        raise ValueError("the original operating builder, exporter and native verifier are required")
    resources={key:_native_ascii(value) for key,value in resource_paths.items()}
    raw=_native_ascii(Path(raw_geometry_record["path"]))
    if not str(raw).lower().endswith(".pa#") or type(raw_geometry_record.get("bytes")) is not int or raw_geometry_record["bytes"]<=0:
        raise ValueError("actual raw geometry record is required")
    _require_sha256(raw_geometry_record.get("sha256"),"raw geometry")
    scratch,payload=_native_ascii(working_directory),_native_ascii(payload_directory)
    domain=next(row for row in plan["field_design"]["domains"] if row["domain_id"]==domain_id)
    point=next(row for row in plan["field_design"]["working_points"] if working_point_member_id(row)==member_id)
    volts=point["electrode_voltages_v"]
    labels=sorted(int(key) for key in volts)
    voltage_argument=",".join(format(volts.get(str(i),0.),".17g") for i in range(1,max(labels)+1))
    convergence=format(domain["refine_convergence_v"][point["kind"]],".17g")
    parent_origin=plan["field_design"]["domains"][0]["instance_origin_mm"]
    source=(str(_native_ascii(Path(published_parent["record"]["path"]))) if published_parent is not None else "zero_neumann")
    source_origin=",".join(format(parent_origin[a],".17g") for a in "xyz") if published_parent is not None else "0,0,0"
    patch_origin=",".join(format(domain["instance_origin_mm"][a],".17g") for a in "xyz") if published_parent is not None else "0,0,0"
    working=scratch/"working.pa0"
    stem="frontend" if domain_id=="parent" else "frontend_entrance_refinement"
    exported=payload/(stem+"."+member_id+".pa")
    audit_spec,audit_output=scratch/"audit.tsv",scratch/"audit.json"
    audit_plan=dict(domain_id=domain_id,boundary_policy=domain["boundary_policy"],
        grid=[domain["dimensions"]["n"+a] for a in "xyz"]+[domain["cell_mm_xyz"][a] for a in "xyz"],
        physical_electrode_ids=labels,physical_samples=domain["physical_samples"],
        working_points=[dict(point,path=str(exported),filename=exported.name,voltage_argument=voltage_argument)])
    operations=(
        _operation("refine_"+domain_id+"_"+member_id,"pa_refine",
            ["lua",str(resources["operating_builder"]),str(raw),str(working),source,
             source_origin,patch_origin,voltage_argument,convergence],[str(working)],"DIRICHLET_PATCH_OPERATING_PA=PASS"),
        _operation("export_"+domain_id+"_"+member_id,"prepare",
            ["lua",str(resources["exporter"]),str(working),str(exported)],[str(exported)],"DETACHED_STANDALONE_PA_EXPORT=PASS"),
        _operation("audit_"+domain_id+"_"+member_id,"prepare",
            ["lua",str(resources["verifier"]),str(audit_spec),str(audit_output)],[str(audit_output)],"FRONTEND_WORKING_FIELDS_AUDIT=PASS"),
    )
    return NativeStagePlan({str(audit_spec):render_audit_spec(audit_plan,raw,payload)},(),operations,
                           (str(working),str(exported),str(audit_output))),identity


def plan_downstream_solve(compiled: CompiledSimionGeometry, *, raw_geometry_assets: Mapping[str, dict],
                          working_directory: Path, convergence_v: Mapping[str, float],
                          exporter_resource: Path, verifier_resource: Path) -> NativeStagePlan:
    """Return the original native plan; its worker also consumes the same asset bindings."""
    return _plan_downstream_solve_with_assets(compiled, raw_geometry_assets=raw_geometry_assets,
        working_directory=working_directory, convergence_v=convergence_v,
        exporter_resource=exporter_resource, verifier_resource=verifier_resource)[0]


def _plan_downstream_solve_with_assets(compiled: CompiledSimionGeometry, *, raw_geometry_assets: Mapping[str, dict],
                          working_directory: Path, convergence_v: Mapping[str, float],
                          exporter_resource: Path, verifier_resource: Path) -> tuple[NativeStagePlan, tuple[dict, ...]]:
    """Solve fresh private downstream families; never rebuild or mutate geometry.

    Fractional tube/detector surfaces stay with their complete native families.
    Only the surface=none operating reflectron is exported to standalone.
    """
    from .artifacts import CompiledPreparedModel
    if isinstance(compiled, CompiledPreparedModel):
        from .model import model_geometry
        compiled = model_geometry(compiled, downstream_drive=True)
    roles={"flight_tube","reflectron","detector"}
    if set(raw_geometry_assets)!=roles or set(convergence_v)!=roles:
        raise ValueError("downstream geometry and explicit convergence require exactly three roles")
    for value in convergence_v.values():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError("downstream Refine convergence must be finite and positive")
    root=_native_ascii(working_directory)
    exporter,verifier=_native_ascii(exporter_resource),_native_ascii(verifier_resource)
    contract=compiled.frontend_geometry["downstream_build_contract"]
    specs={row["role"]:row for row in compiled.downstream_specs}
    physical=dict(simion={role:specs[role]["template_variables"]["component"] for role in ("flight_tube","reflectron")})
    physical["simion"]["detector_marker"]=contract["simion_detector_marker"]
    projection=root/"projection.lua"
    materializations={str(projection):"return "+lua_value(dict(contract,physical_geometry=physical))+"\n"}
    copies,operations,assets=[],[],[]
    for role in ("flight_tube","detector","reflectron"):
        entry=raw_geometry_assets[role]
        if set(entry)!={"raw_record","surface_records"}:
            raise ValueError("downstream geometry must contain raw and explicit surface records only")
        expected_surfaces=0 if role=="reflectron" else 1
        if len(entry["surface_records"])!=expected_surfaces:
            raise ValueError("fractional geometry surface companions must be preserved")
        raw=root/(role+".pa#")
        for index,record in enumerate([entry["raw_record"],*entry["surface_records"]]):
            _absolute(Path(record["path"]))
            suffix=".pa#" if index==0 else ".pa-surf"
            if not str(record["path"]).lower().endswith(suffix):
                raise ValueError("geometry copy must preserve raw/surface representation; family responses are forbidden")
            if type(record.get("bytes")) is not int or record["bytes"]<=0:
                raise ValueError("downstream source record must have its actual positive size")
            _require_sha256(record.get("sha256"),"downstream raw/surface")
            copies.append(dict(source_record=copy.deepcopy(record),destination=str(raw if index==0 else raw.with_suffix(".pa-surf"))))
        gem=root/(role+".gem")
        materializations[str(gem)]=specs[role]["template_text"]
        family=[str(raw),str(raw.with_suffix(".pa0"))]
        count=(len(specs[role]["template_variables"]["component"]["electrodes"]) if role=="reflectron" else 1)
        family.extend(str(raw.with_suffix(".pa"+str(i))) for i in range(1,count+1))
        if role!="reflectron":family.append(str(raw.with_suffix(".pa-surf")))
        operations.append(_operation("solve_"+role,"pa_refine",["lua",
            str(native_resource_path("build_"+role+"_variant.lua")),str(gem),str(raw),str(projection),
            "solve-only",format(convergence_v[role],".17g")],family,"BUILD: PASS"))
        instance=specs[role]["native_instance"]
        variables=specs[role]["template_variables"]
        cells=([variables["mmgu_xy"],variables["mmgu_xy"],variables["mmgu_z"]] if role=="detector"
               else [variables["mmgu_axial"],variables["mmgu_radial"],variables["mmgu_radial"]])
        asset=dict(role=role,carrier_path=str(raw.with_suffix(".pa0")),
            family_paths=family,symmetry="3dplanar" if role=="detector" else "2dcylindrical",
            grid={**{key:instance[key] for key in ("nx","ny","nz")},
                  **dict(zip(("dx_mm","dy_mm","dz_mm"),cells,strict=True))})
        if role=="reflectron":
            operating=root/"reflectron.pa"
            operations.append(_operation("export_reflectron","prepare",
                ["lua",str(exporter),str(raw.with_suffix(".pa0")),str(operating)],
                [str(operating)],"STANDALONE_PA_EXPORT=PASS"))
            g,v=contract["geometry_mm"],contract["electrodes_V"]
            asset.update(carrier_path=str(operating),family_paths=[],endpoint_samples=[dict(x=0,voltage=0),
                dict(x=round(g["L_stage1"]/cells[0]),voltage=v["midgrid"]),
                dict(x=math.ceil(g["L_reflectron"]/cells[0]),voltage=v["backplate"])])
        assets.append(asset)
    audit_spec,audit_output=root/"audit.lua",root/"audit.json"
    materializations[str(audit_spec)]="return "+lua_value(dict(assets=assets,output=str(audit_output)))+"\n"
    operations.append(_operation("audit_downstream","prepare",["lua",str(verifier),str(audit_spec)],
        [str(audit_output)],"DOWNSTREAM_NATIVE_AUDIT=PASS"))
    outputs=tuple(dict.fromkeys(p for op in operations for p in op["outputs"]))
    return NativeStagePlan(materializations,tuple(copies),tuple(operations),outputs), tuple(assets)


def plan_field_workbench(compiled: CompiledSimionGeometry, *, field_design: dict,
                         components_resolved: Mapping[str, dict], carriers: Mapping[str, dict],
                         response_fields: list[dict], run_directory: Path,
                         seed_record: Mapping[str, Any], native_path_resource: Path) -> NativeStagePlan:
    """Declare a zero-beam solved container and its independent full field audit.

    The admitted owner must verify/protect every carrier representation, including
    complete owned fractional families/surfaces. This pure projection neither
    reads PA payloads nor infers a family closure from the existence of PA0.
    """
    from .field_validation import (interface_field_probes, native_priority_occupancy_probes,
                                   require_supported_split_interfaces)
    from .frontend import native_frontend_instances

    geometry = compiled.frontend_geometry
    require_supported_split_interfaces(geometry, field_design)
    root = _native_ascii(run_directory)
    projection = plan_geometry_build(compiled, run_directory=root, seed_record=seed_record,
                                     native_path_resource=native_path_resource)
    roles = ['flight_tube', 'reflectron', 'accelerator', 'detector']
    if 'entrance_refinement' in geometry['numerical_domains']:
        roles.append('entrance_refinement')
    if set(carriers) != set(roles):
        raise ValueError('field workbench carriers must cover every declared slot')
    paths = {}
    for role in roles:
        record = carriers[role]
        if type(record.get('bytes')) is not int or record['bytes'] <= 0:
            raise ValueError('positive verified carrier record required')
        _require_sha256(record.get('sha256'), 'field carrier')
        paths[role] = str(_native_ascii(Path(record['path'])))
    expected = {(domain['domain_id'], working_point_member_id(point))
                for domain in field_design['domains'] for point in field_design['working_points']
                if point['kind'] != 'carrier_off'}
    actual = [(row['domain'], row['kind']) for row in response_fields]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('field response paths must cover exactly the solved working members')
    domains = {row['domain_id']: row for row in field_design['domains']}
    responses = copy.deepcopy(response_fields)
    for row in responses:
        domain = domains[row['domain']]
        grid = dict(domain['dimensions'], **{f'd{a}_mm': domain['cell_mm_xyz'][a] for a in 'xyz'})
        if row['grid'] != grid:
            raise ValueError('field response grid differs from solved design')
        row['path'] = str(_native_ascii(Path(row['path'])))
    _, tof = native_frontend_instances(geometry['composition_plan'])
    probes = native_priority_occupancy_probes(geometry, field_design)
    interfaces = interface_field_probes(geometry, components_resolved[tof])
    original_path = root/'inputs/geometry_iob.lua'
    original = projection.materializations[str(original_path)]
    spec_path = root/'inputs/field_iob.lua'
    output = root/'simion/fields/fields.iob'
    transport = dict(output_iob=str(output), response_fields=responses,
                     interface_field_probes=interfaces, native_priority_occupancy_probes=probes)
    source = ('local spec=' + original.removeprefix('return ') + '\nlocal paths=' + lua_value(paths)
              + '\nfor _,row in ipairs(spec.instances) do row.path=paths[row.role] end\n'
              + 'local fields=' + lua_value(transport)
              + '\nfor key,value in pairs(fields) do spec[key]=value end\nreturn spec\n')
    empty = root/'inputs/no_particles.fly2'
    materializations = {str(empty): projection.materializations[str(empty)], str(spec_path): source}
    operations = tuple(_operation(mode, 'prepare', ['lua', str(native_resource_path('build_field_iob.lua')),
        str(spec_path), mode, str(_native_ascii(native_path_resource))],
        [str(output), str(output.with_suffix('.fly2'))] if mode == 'build_fields' else [],
        'SINGLE_REFLECTION_FIELD_IOB' + ('_REOPEN' if mode == 'verify_fields' else '') + '=PASS')
        for mode in ('build_fields', 'verify_fields'))
    return NativeStagePlan(materializations, projection.input_copies, operations,
                           tuple(path for operation in operations for path in operation['outputs']))
