"""Independent RF/OA field/source binding and structural IOB projection; no independent run owner."""
from pathlib import Path
import json
from collections.abc import Mapping
from typing import Any
from msplatform.contracts.gas import BoxDomain
from msplatform.contracts.rigid_transform import RigidTransform
from .artifacts import NativeStagePlan, CompiledPreparedModel
from .model import model_geometry, resolve_ip_schedule_authorities
from .model_execution import _clock_reference
from .native_plans import plan_geometry_build
from .resources import structural_seed_path,native_resource_path
from .source import lua_value,render_restart_fly2
from .rf_field_execution import require_rf_reuse
from msplatform.io.manifest_records import file_record


def execute_rf_tracking(session,*,source,model,document,**options):
    from .tracking_execution import _execute_tracking_bound_source,_artifact_record
    compiled=model_geometry(model)
    geometry=dict(compiled.frontend_geometry,native_frame_id=document['native_frame_id'])
    if geometry.get('role') == 'simion_neutral_world_collision_geometry':
        from .rf_field_execution import require_static_world_reuse, static_world_voltage_vector
        from msplatform.io.file_identity import canonical_json_sha256
        identity=source.metadata['spatial_identity']
        if (not isinstance(identity,Mapping) or set(identity)!={'schema_version','role','spatial_operator','voltages','identity_sha256'}
                or type(identity['schema_version']) is not int or identity['schema_version']!=1
                or identity['role']!='simion_static_world_operating_identity'
                or identity['voltages']!=static_world_voltage_vector(model)
                or canonical_json_sha256({key:identity[key] for key in identity if key!='identity_sha256'})!=identity['identity_sha256']):
            raise ValueError('static operating workpoint identity differs from the prepared model')
        selected,producer,assets=require_static_world_reuse(source.reference,identity=source.metadata['spatial_identity'],geometry=geometry)
        borrowed=[record for row in assets.values() for record in [row['carrier_record'],row['witness_record'], *([row['surface_record']] if 'surface_record' in row else []), *([row['state_record']] if 'state_record' in row else [])]]
    else:
        selected,producer,assets=require_rf_reuse(source.reference,identity=source.metadata['spatial_identity'],geometry=geometry)
        borrowed=[record for row in assets.values() for record in [*row['family_records'],row['witness_record'], *([row['state_record']] if 'state_record' in row else [])]]
    from .rf_field_execution import _protect_field_source
    for artifact in [selected,producer]:
        _protect_field_source(session,artifact,required_paths=[row['path'] for row in borrowed])
    clocks=dict(contract=_artifact_record(source,'clock_authority'),authority=_artifact_record(source,'instrument_epoch'))
    clocks['data_root']=str(Path(clocks['contract']['path']).parent)
    relative=_clock_reference(document,clocks)
    return _execute_tracking_bound_source(session,source=source,model=model,document=document,compiled=compiled,
        geometry=geometry,design=None,stored_bank=None,frontend=assets,downstream={},field_workbench=None,
        borrowed=borrowed,original_clock=clocks,relative_epoch=relative,**options)



def admit_neutral_sampled_tracking_fields(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate the actual field producer and its complete sampled source closure."""
    import copy
    import json
    from msplatform.results.artifacts import open_artifact
    from msplatform.io.manifest_records import record_path, verify_record
    from .neutral_sampled_field import verify_neutral_sampled_inputs

    source = open_artifact(reference, expected_kind='field_bundle')
    if source.metadata.get('field_representation') not in {'neutral_sampled_basis_with_collision_geometry','neutral_multi_sampled_basis_with_collision_geometry'}:
        raise ValueError('published neutral sampled FieldBundle required')
    manifest = json.loads(source.manifest_location.read_text(encoding='utf-8-sig'))
    request_record = manifest['inputs']['execution_request']
    verify_record('neutral sampled field request', request_record, base_dir=source.manifest_location.parent)
    request_path = record_path(request_record, base_dir=source.manifest_location.parent)
    request = json.loads(request_path.read_text(encoding='utf-8-sig'))
    payload = request['payload']
    if request.get('role') != 'run_artifact_workflow_request' or payload.get('action') != 'solve_fields':
        raise ValueError('neutral sampled field producer request differs')
    planned = verify_neutral_sampled_inputs(payload['model'], selection=payload['scalar_field_basis'])
    if json.loads(source.data_path('sampled_basis').read_text(encoding='utf-8-sig')) != planned['binding']:
        raise ValueError('published neutral sampled basis differs from producer sources')
    audits = json.loads(source.data_path('collision_audit').read_text(encoding='utf-8-sig'))
    multi=source.metadata.get('field_representation')=='neutral_multi_sampled_basis_with_collision_geometry'
    if not multi: audits=[audits]
    actual_multi=planned['model'].document['geometry']['frontend_geometry'].get('role')=='simion_neutral_multi_domain_collision_geometry'
    if multi != actual_multi:raise ValueError('field representation and geometry role differ')
    tasks=planned['geometry_plan']['tasks']
    if not isinstance(audits,list) or len(audits)!=len(tasks):raise ValueError('collision audit count differs')
    assets=source.metadata.get('collision_assets') if multi else {'world':dict(collision='collision',**({'surface':'collision_surface'} if 'collision_surface' in source.data_records else {}))}
    if not isinstance(assets,dict) or set(assets)!={task['role'] for task in tasks}:raise ValueError('collision asset roles differ')
    keys=['compiled_model','clock_authority','instrument_epoch','sampled_basis','background','workbench','zero_particle_format_control','collision_audit']
    for index,(audit,task) in enumerate(zip(audits,tasks,strict=True),1):
        if (audit.get('role') != task['role'] or audit.get('source_records') != task['source_records']
                or audit.get('geometry_reference') != planned['geometry_plan']['geometry_reference']
                or audit.get('compiled_geometry_record') != planned['geometry_plan']['compiled_geometry_record']):
            raise ValueError('published collision audit differs from geometry lineage')
        row=assets[task['role']]; expected_collision=f'collision_{index:02d}' if multi else 'collision'
        if not isinstance(row,dict) or set(row) not in ({'collision'},{'collision','surface'}) or row['collision']!=expected_collision:
            raise ValueError('published collision asset keys differ')
        expected_surface=expected_collision+'_surface' if multi else 'collision_surface'
        if 'surface' in row and row['surface']!=expected_surface:raise ValueError('published collision surface key differs')
        for label,key in (('output_record',row['collision']),('surface_record',row.get('surface'))):
            selected=audit.get(label)
            if key is None:
                if selected is not None:raise ValueError('collision audit declares an unpublished '+label)
                continue
            actual=source.data_records[key]
            if (not isinstance(selected,dict) or any(str(selected[k]).lower()!=str(actual[k]).lower() for k in ('bytes','sha256'))
                    or Path(selected['path']).resolve(strict=True)!=source.data_path(key).resolve(strict=True)):
                raise ValueError('collision audit differs from published '+key)
            keys.append(key)
    document = planned['model'].document
    if (source.metadata.get('model_identity_sha256') != document['model_identity_sha256']
            or source.metadata.get('clock') != document['drive']['clock']):
        raise ValueError('neutral sampled field model or clock differs')
    for key in ('compiled_model', 'clock_authority', 'instrument_epoch'):
        expected, actual = planned['prepared_records'][key], source.data_records[key]
        if any(str(expected[k]).lower() != str(actual[k]).lower() for k in ('bytes', 'sha256')):
            raise ValueError('neutral sampled prepared record differs: ' + key)
    records = [dict(source.data_records[k], path=str(source.data_path(k))) for k in keys]
    records.extend(copy.deepcopy(planned['immutable_input_records']))
    records.append(dict(request_record, path=str(request_path)))
    for row in records:
        verify_record('neutral sampled tracking input', row)
    from .neutral_sampled_field import neutral_source_paths
    code_records = {name: file_record(path, 'required_evidence')
                    for name, path in neutral_source_paths(planned['model']).items()}
    return dict(source=source, model=planned['model'], basis=planned['binding'], plan=planned,
                code_records=code_records, immutable_input_records=records,
                source_manifests=[row['manifest_record'] for row in planned['source_references']])

def execute_neutral_sampled_tracking(session: Any, *, source: Any, model: CompiledPreparedModel,
                                     document: Mapping[str, Any], **options: Any) -> dict[str, Any]:
    """Rebind the published sampled field inside the existing tracking owner."""
    from .tracking_execution import _artifact_record, _execute_tracking_bound_source
    admission = admit_neutral_sampled_tracking_fields(source.reference)
    if admission['model'].document != model.document:
        raise ValueError('neutral sampled field model changed after admission')
    from .neutral_sampled_field import protect_neutral_records
    protect_neutral_records(session, [source.reference, *admission['plan']['protected_products']],
                            admission['immutable_input_records'])
    for index, record in enumerate(admission['immutable_input_records']):
        session.add_input('neutral_sampled_field_input_'+str(index), record)
    clocks = dict(contract=_artifact_record(source, 'clock_authority'), authority=_artifact_record(source, 'instrument_epoch'))
    clocks['data_root'] = str(Path(clocks['contract']['path']).parent)
    relative = _clock_reference(document, clocks)
    compiled = model_geometry(model)
    geometry = dict(compiled.frontend_geometry, native_frame_id=document['native_frame_id'])
    return _execute_tracking_bound_source(session, source=source, model=model, document=document,
        compiled=compiled, geometry=geometry, design=None, stored_bank=None, frontend={}, downstream={},
        field_workbench=None, borrowed=admission['immutable_input_records'], original_clock=clocks,
        relative_epoch=relative, neutral_admission=admission, **options)


def plan_neutral_sampled_tracking_workbench(compiled: Any, *, admission: Mapping[str, Any],
        run_directory: Path, program: str, native_source_rows: list[Mapping[str, Any]],
        native_path_resource: Path) -> NativeStagePlan:
    """Build the same background/world priority slots with a fresh flight Program."""
    import json
    from .source import lua_value, render_restart_fly2
    if not native_source_rows or not program:
        raise ValueError('neutral sampled tracking requires original births and Program')
    root = Path(run_directory)
    source, basis, plan = admission['source'], admission['basis'], admission['plan']
    geometry = compiled.frontend_geometry
    if geometry.get('role')=='simion_neutral_multi_domain_collision_geometry':
        return _plan_neutral_multi_tracking_workbench(compiled,admission=admission,run_directory=root,program=program,native_source_rows=native_source_rows,native_path_resource=native_path_resource)
    task = plan['geometry_plan']['tasks'][0]
    dimensions, origin, pitch = geometry['dimensions'], geometry['domain']['minimum_mm'], geometry['pitch_mm']
    grid = dict(zip(('nx', 'ny', 'nz'), dimensions, strict=True), dx_mm=pitch, dy_mm=pitch, dz_mm=pitch)
    placement = dict(x_mm=origin[0], y_mm=origin[1], z_mm=origin[2], az_deg=0., el_deg=0., rt_deg=0., scale=1.)
    rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    def record(key):
        return dict(source.data_records[key], path=str(source.data_path(key)))
    background, collision = record('background'), record('collision')
    if 'collision_surface' in source.data_records:
        if Path(record('collision_surface')['path']).resolve() != Path(collision['path']).with_suffix('.pa-surf').resolve():
            raise ValueError('collision surface must be the published adjacent companion')
    elif 'surface_state' not in task['source_records']:
        raise ValueError('collision surface state or companion required')
    first = dict(role='background', instance_index=1, priority_number=1, path=background['path'],
                 grid=grid, rotation=rotation, placement=placement)
    second = dict(role='world', instance_index=2, priority_number=2, path=collision['path'],
                  grid=grid, rotation=rotation, placement=placement, physical_samples=geometry['physical_samples'],
                  electrode_witness_ids=geometry['electrode_witness_ids'],
                  surface_witnesses=task['source_records']['surface_witnesses']['path'],
                  fractional_surface=str(Path(collision['path']).with_suffix('.pa-surf')))
    if 'surface_state' in task['source_records']:
        second['surface_state'] = task['source_records']['surface_state']['path']
    seed_record = file_record(structural_seed_path(2), 'required_evidence')
    seed, output = root/'inputs/structural_seed/2_instance_seed.iob', root/'simion/tracking/instrument.iob'
    binding, spec_path = root/'inputs/sampled_basis.json', root/'inputs/tracking_iob.lua'
    bootstraps = tuple(str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1, 3))
    spec = dict(schema_version=1, role='neutral_sampled_tracking_iob',
        field_representation='neutral_sampled_basis_with_collision_geometry', scalar_binding=str(binding),
        collision_roles=dict(background='background', world='world'), instances=[first, second],
        seed_iob=str(seed), output_iob=str(output), response_fields=[], bootstrap_paths=list(bootstraps))
    materials = {str(spec_path): 'return '+lua_value(spec)+'\n',
        str(binding): json.dumps(basis, ensure_ascii=False, allow_nan=False, indent=2)+'\n',
        str(output.with_suffix('.lua')): program,
        str(output.with_suffix('.fly2')): render_restart_fly2(native_source_rows)}
    wrapper = native_resource_path('build_tracking_iob.lua')
    ops = tuple(dict(operation_id=name, role='SIMION', stage='prepare',
        arguments=['--nogui', '--noprompt', 'lua', str(wrapper), str(spec_path), mode, str(native_path_resource)],
        outputs=[str(output), *bootstraps] if mode=='build' else [], success_marker=marker)
        for name, mode, marker in [('build_tracking_iob', 'build', 'NEUTRAL_SAMPLED_TRACKING_IOB=PASS'),
            ('verify_tracking_iob', 'verify', 'NEUTRAL_SAMPLED_TRACKING_IOB_REOPEN=PASS')])
    return NativeStagePlan(materials, (dict(source_record=seed_record, destination=str(seed)),), ops,
                           (str(output), *bootstraps))


def plan_rf_tracking_workbench(compiled,*,carriers,run_directory,program,native_source_rows,native_path_resource,program_metadata=None):
    root=Path(run_directory)
    joint=compiled.frontend_geometry.get('role')=='simion_rf_ip_geometry'
    static_world=compiled.frontend_geometry.get('role')=='simion_neutral_world_collision_geometry'
    from .rf_field_execution import _mirror_oa
    mirror_oa = _mirror_oa(compiled.frontend_geometry)
    names=['world'] if static_world else ['parent'] if joint else compiled.frontend_geometry['composition_plan']['scope']['instance_ids']
    if not native_source_rows or set(carriers)!=set(names):
        raise ValueError('RF tracking workbench needs its nonempty source and exact field domains')
    seed=file_record(structural_seed_path(len(names)),'required_evidence')
    projection=plan_geometry_build(compiled,run_directory=root,seed_record=seed,native_path_resource=native_path_resource)
    output=root/'simion/tracking/instrument.iob'
    spec=root/'inputs/tracking_iob.lua'
    original=projection.materializations[str(root/'inputs/geometry_iob.lua')]
    text='local spec=(function()\n'+original+'\nend)()\n'
    kind='STATIC_WORLD' if static_world else 'RF_IP' if joint else 'OA' if compiled.frontend_geometry['role']=='simion_independent_oa_geometry' else 'RF'
    text+="spec.role="+lua_value('static_world_tracking_iob' if static_world else 'rf_ip_tracking_iob' if joint else 'independent_'+kind.lower()+'_tracking_iob')+"\nspec.output_iob="+lua_value(str(output))+"\nspec.response_fields={}\n"
    for index,name in enumerate(names,1):
        asset=carriers[name]
        if static_world:
            import math
            if (not {'carrier_record','witness_record'} <= set(asset)
                    or set(asset)-{'carrier_record','surface_record','witness_record','state_record'}):
                raise ValueError('static operating field requires exact operating and surface evidence records')
            from .rf_field_execution import _static_surface_mode, _field_domains
            surface=asset.get('surface_record'); carrier=Path(asset['carrier_record']['path'])
            mode='present'
            if 'state_record' in asset:
                domain=_field_domains(compiled.frontend_geometry)['world']
                grid=dict(domain['dimensions'], **{'d'+axis+'_mm':domain['cell_mm_xyz'][axis] for axis in 'xyz'})
                mode=_static_surface_mode(asset['state_record'],surface,grid)
            elif surface is None:
                raise ValueError('static surface state or fractional surface is required')
            if (carrier.suffix.lower()!='.pa' or (surface is not None and carrier.with_suffix('.pa-surf') != Path(surface['path']))
                    or (mode=='empty' and carrier.with_suffix('.pa-surf').exists())):
                raise ValueError('static operating PA and fractional surface must be matching standalone siblings')
            values=program_metadata.get('static_operating_voltages') if isinstance(program_metadata,Mapping) else None
            labels=sorted(row['native_id'] for row in compiled.frontend_geometry['electrode_mapping'])
            if (not isinstance(values,list) or len(values)!=len(labels)
                    or [row.get('electrode_id') for row in values if isinstance(row,Mapping)]!=labels
                    or any(set(row)!={'electrode_id','voltage_v'} or type(row['electrode_id']) is not int or type(row['voltage_v']) not in (int,float)
                           or not math.isfinite(row['voltage_v']) for row in values)):
                raise ValueError('static operating voltage map differs from native electrodes')
            text+='spec.instances['+str(index)+'].operating_voltages='+lua_value(values)+'\n'
        elif mirror_oa:
            from .rf_field_execution import _static_surface_mode, _field_domains
            domain = _field_domains(compiled.frontend_geometry)[name]
            grid = dict(domain['dimensions'], **{'d'+axis+'_mm':domain['cell_mm_xyz'][axis] for axis in 'xyz'})
            if _static_surface_mode(asset.get('state_record'), None, grid) != 'empty':
                raise ValueError('mirror OA tracking requires verified empty surface')
            carrier = Path(asset['carrier_record']['path'])
            surface = None
            if carrier.with_suffix('.pa-surf').exists():
                raise ValueError('mirror OA forbids a fractional surface companion')
        else:
            surface=next(row for row in asset['family_records'] if row['path'].endswith('.pa-surf'))
        text+='spec.instances['+str(index)+'].path='+lua_value(asset['carrier_record']['path'])+'\n'
        surface_path = str(carrier.with_suffix('.pa-surf')) if (static_world or mirror_oa) and surface is None else surface['path']
        text+='spec.instances['+str(index)+'].fractional_surface='+lua_value(surface_path)+'\n'
        if static_world or mirror_oa:
            text+='spec.instances['+str(index)+'].surface_state='+lua_value(asset['state_record']['path'] if 'state_record' in asset else None)+'\n'
        text+='spec.instances['+str(index)+'].surface_witnesses='+lua_value(asset['witness_record']['path'])+'\n'
        mappings=compiled.frontend_geometry.get('electrode_bindings', {})
        labels=sorted(row['native_id'] for row in compiled.frontend_geometry['electrode_mapping']) if static_world else sorted({value for group in mappings.values() for value in group.values()}) if joint else sorted(set(mappings[name].values()))
        text+='spec.instances['+str(index)+'].response_ids='+lua_value(labels)+'\n'
    text+='return spec\n'
    materials={str(spec):text,str(output.with_suffix('.lua')):program,str(output.with_suffix('.fly2')):render_restart_fly2(native_source_rows)}
    wrapper=native_resource_path('build_tracking_iob.lua')
    # The same canonical writer creates these neutral container inputs before
    # replacing all slots. Declare them even if a failed writer retains them.
    bootstraps=tuple(str(Path(projection.input_copies[0]['destination']).parent/f'iob_seed_placeholder_{index:02d}.pa0')
        for index in range(1,len(names)+1))
    marker_prefix='STATIC_WORLD' if static_world else 'RF_IP' if joint else 'INDEPENDENT_'+kind
    operations=tuple(dict(operation_id=name,role='SIMION',stage='prepare',
        arguments=['--nogui','--noprompt','lua',str(wrapper),str(spec),mode,str(native_path_resource)],
        outputs=[str(output),*bootstraps] if mode=='build' else [],success_marker=marker)
        for name,mode,marker in [('build_tracking_iob','build',marker_prefix+'_TRACKING_IOB=PASS'),
                                ('verify_tracking_iob','verify',marker_prefix+'_TRACKING_IOB_REOPEN=PASS')])
    return NativeStagePlan(materials,projection.input_copies,operations,(str(output),*bootstraps))



def compile_continuous_hs1_gas(baseline: dict, *, environment_author: dict, bath_domain: BoxDomain,
                               outer_domain: BoxDomain, placement: RigidTransform,
                               parent_domain: BoxDomain) -> tuple[str, str]:
    """Compile explicit IP bath and outer fields in the selected native frame."""
    from msplatform.backends.simion.gas_runtime import compile_gas_runtime
    from msplatform.components.ion_processor.gas_regions import (
        resolve_ip_continuous_environment, validate_continuous_hs1_gas, validate_continuous_parent_coverage)
    from msplatform.gas.field import prepare_gas_field

    environment = resolve_ip_continuous_environment(environment_author, baseline, bath_domain=bath_domain,
                                                     outer_domain=outer_domain)
    bath, outer = environment.fields
    validate_continuous_hs1_gas(bath, outer, gas_mass_amu=bath.composition[0].mass_amu)
    validate_continuous_parent_coverage(outer, placement=placement, parent_domain=parent_domain)
    return (compile_gas_runtime(prepare_gas_field(bath), placement=placement),
            compile_gas_runtime(prepare_gas_field(outer), placement=placement))

def _prepare_ip_hs1(model: CompiledPreparedModel, request: Mapping[str, Any], *, role: str,
                    common_world_domain: BoxDomain | None = None, common_world_frame_id: str | None = None) -> dict[str, Any]:
    """Validate explicit gas and vendor inputs and derive a deterministic runtime."""
    import hashlib
    from dataclasses import asdict
    from msplatform.backends.simion.collision_hs1 import adapt_hs1_for_repeat_fly
    from msplatform.io.manifest_records import validate_file_record, verify_record
    from .model import require_prepared_model

    if not isinstance(request, Mapping) or set(request) != {'bath_domain', 'outer_domain', 'vendor_record', 'numerics', 'environment_record', 'environment_instance_id'}:
        raise ValueError('RF-IP HS1 requires explicit bath and outer domains, vendor, numerics and bound environment')
    bath_domain, outer_domain, vendor, numerics = (request[k] for k in ('bath_domain', 'outer_domain', 'vendor_record', 'numerics'))
    if not isinstance(bath_domain, BoxDomain) or not isinstance(outer_domain, BoxDomain):
        raise ValueError('RF-IP HS1 gas inputs require explicit typed domains')
    if (not isinstance(numerics, Mapping) or set(numerics) != {'seed', 'hs1_steps_per_mfp'}
            or type(numerics['seed']) is not int or not 1 <= numerics['seed'] <= 2147483646
            or type(numerics['hs1_steps_per_mfp']) is not int or numerics['hs1_steps_per_mfp'] < 1):
        raise ValueError('RF-IP HS1 requires explicit supported seed and steps')
    if not isinstance(vendor, Mapping) or not Path(str(vendor.get('path', ''))).is_absolute():
        raise ValueError('RF-IP HS1 requires the explicit original vendor file record')
    vendor = validate_file_record(vendor, 'original HS1 vendor')
    verify_record('original HS1 vendor', vendor)
    original = Path(vendor['path']).read_bytes()
    verify_record('original HS1 vendor', dict(vendor))
    adapted = adapt_hs1_for_repeat_fly(original.decode('utf-8-sig'))
    document = require_prepared_model(model)
    geometry = document['geometry']['frontend_geometry']
    if geometry['role'] != role:
        raise ValueError('RF-IP HS1 requires the actual selected joint model')
    composition = (geometry['source_snapshot']['composition_plan']
                   if role == 'simion_neutral_world_collision_geometry' else geometry['composition_plan'])
    if role == 'simion_neutral_world_collision_geometry':
        ids = sorted({row['instance_id'] for row in document['native_drive_rows'] if row['kind'] == 'ip_schedule'})
    else:
        ids = [name for name, row in composition['components'].items()
               if row['project_id'] == 'ion_processor']
    poses = [row['transform'] for row in composition['recipe']['instances']
             if len(ids) == 1 and row['instance_id'] == ids[0]]
    if len(poses) != 1:
        raise ValueError('RF-IP HS1 requires one selected IP placement')
    if request['environment_instance_id'] != ids[0]:
        raise ValueError('IP gas environment is bound to a different instance')
    environment_record = validate_file_record(request['environment_record'], 'IP gas environment author')
    if not Path(str(environment_record['path'])).is_absolute():
        raise ValueError('IP gas environment author requires an absolute path')
    environment_bytes = Path(environment_record['path']).read_bytes()
    if (len(environment_bytes) != environment_record['bytes']
            or hashlib.sha256(environment_bytes).hexdigest().lower() != environment_record['sha256'].lower()):
        raise ValueError('IP gas environment author identity differs')
    environment_author = json.loads(environment_bytes)
    pose = RigidTransform.from_contract(poses[0])
    if pose.to_frame_id != document['native_frame_id']:
        raise ValueError('RF-IP HS1 gas frame differs from selected placement')
    if role == 'simion_rf_ip_geometry':
        bounds = geometry['numerical_domains']['parent']['bounds_mm']
        parent = BoxDomain(tuple(bounds[a+'_min'] for a in 'xyz'), tuple(bounds[a+'_max'] for a in 'xyz'),
                           (True, True, True), (True, True, True))
    else:
        if not isinstance(common_world_domain, BoxDomain):
            raise ValueError('IP-MR HS1 requires an explicit common world BoxDomain')
        if common_world_frame_id != document['native_frame_id']:
            raise ValueError('IP-MR common world box frame differs from model')
        parent = common_world_domain
    baseline = resolve_ip_schedule_authorities(document['drive'], set(ids))[ids[0]]['baseline']
    if pose.from_frame_id != baseline['clock']['frame_id']:
        raise ValueError('RF-IP HS1 gas frame differs from selected placement')
    bath, outside = compile_continuous_hs1_gas(baseline, environment_author=environment_author, bath_domain=bath_domain, outer_domain=outer_domain,
                                                placement=pose, parent_domain=parent)
    def sha(data):
        return hashlib.sha256(data).hexdigest()
    from msplatform.components.ion_processor.gas_regions import project_ip_baseline, project_ip_resolved_gas_view, resolve_ip_continuous_environment
    gas_environment = resolve_ip_continuous_environment(environment_author, baseline, bath_domain=bath_domain,
                                                        outer_domain=outer_domain).to_dict()
    native_gas_view = project_ip_resolved_gas_view(gas_environment)
    if native_gas_view != project_ip_baseline(environment_author, baseline)['gas']:
        raise ValueError('IP native gas view differs from its resolved environment')
    identity = dict(bath_domain=asdict(bath_domain), outer_domain=asdict(outer_domain), placement=poses[0], numerics=dict(numerics),
                    environment_instance_id=ids[0], environment_author_sha256=environment_record['sha256'],
                    gas_environment=gas_environment,
                    native_gas_view=native_gas_view,
                    vendor={k: vendor[k] for k in ('bytes', 'sha256')},
                    vendor_adapted_sha256=sha(adapted.encode('utf-8')),
                    bath_runtime_sha256=sha(bath.encode('utf-8')),
                    outer_runtime_sha256=sha(outside.encode('utf-8')))
    if role in {'simion_ip_mr_complete_geometry', 'simion_neutral_world_collision_geometry'}:
        identity['common_world_domain'] = asdict(parent)
        identity['common_world_frame_id'] = common_world_frame_id
    return dict(identity=identity, environment_bytes=environment_bytes, vendor_record=dict(vendor), vendor_original=original,
                vendor_adapted=adapted, bath_runtime=bath, outer_runtime=outside,
                query_frame_id=pose.to_frame_id)

def prepare_rf_ip_hs1(model: CompiledPreparedModel, request: Mapping[str, Any]) -> dict[str, Any]:
    """Retain the existing RF-IP parent-domain authority and validation."""
    return _prepare_ip_hs1(model, request, role='simion_rf_ip_geometry')


def prepare_ip_mr_hs1(model: CompiledPreparedModel, request: Mapping[str, Any], *,
                      common_world_domain: BoxDomain, common_world_frame_id: str) -> dict[str, Any]:
    """Bind selected IP gas to the caller's verified common world query box."""
    return _prepare_ip_hs1(model, request, role='simion_ip_mr_complete_geometry',
                           common_world_domain=common_world_domain, common_world_frame_id=common_world_frame_id)

def prepare_neutral_ip_hs1(model: CompiledPreparedModel, request: Mapping[str, Any], *, basis: Mapping[str, Any]) -> dict[str, Any]:
    """Bind gas coverage to the intersection of verified scalar and collision boxes."""
    geometry = model_geometry(model).frontend_geometry
    grid = basis['grid']
    domain = geometry['domain']
    if grid['frame_id'] != domain['frame_id']:
        raise ValueError('neutral scalar and collision frames differ')
    # Windows are ordered by the existing router, but every active box may
    # be selected. Their bounding union is conservative even where masks leave
    # holes; it does not declare those holes to be valid field support.
    base_upper = [origin + (count - 1) * pitch for origin, pitch, count in
                  zip(grid['origin_mm'], grid['pitch_mm'], grid['dimensions'], strict=True)]
    boxes = [(grid['origin_mm'], base_upper)]
    for sample in basis.get('bases', {}).values():
        for window in sample.get('refinement_windows', []):
            if window['grid']['frame_id'] != domain['frame_id']:
                raise ValueError('neutral refinement and collision frames differ')
            active = window['active_box_mm']
            boxes.append(([axis[0] for axis in active], [axis[1] for axis in active]))
    lower = [min(box[0][i] for box in boxes) for i in range(3)]
    upper = [max(box[1][i] for box in boxes) for i in range(3)]
    lo = tuple(max(a, b) for a, b in zip(lower, domain['minimum_mm'], strict=True))
    hi = tuple(min(a, b) for a, b in zip(upper, domain['maximum_mm'], strict=True))
    if any(a >= b for a, b in zip(lo, hi, strict=True)):
        raise ValueError('neutral scalar and collision domains do not overlap')
    return _prepare_ip_hs1(model, request, role='simion_neutral_world_collision_geometry',
        common_world_domain=BoxDomain(lo, hi, (True, True, True), (True, True, True)),
        common_world_frame_id=grid['frame_id'])


def plan_ip_mr_tracking_workbench(compiled: Any, *, admission: Mapping[str, Any],
                                run_directory: Path, program: str,
                                program_metadata: Mapping[str, Any],
                                native_source_rows: list[Mapping[str, Any]],
                                native_path_resource: Path) -> NativeStagePlan:
    """Project the verified five-slot sampled bundle into the existing writer."""
    import copy
    import json
    from .ip_mr_collision_priority import project_ip_mr_collision_iob
    if not native_source_rows or not isinstance(program, str) or not program:
        raise ValueError('sampled tracking requires original source and Program')
    if not isinstance(program_metadata, dict) or program_metadata.get('collision_priority_applied') is not True:
        raise ValueError('sampled tracking requires the verified collision priority Program')
    root = Path(run_directory)
    if not root.is_absolute() or not str(root).isascii():
        raise ValueError('tracking requires the existing absolute ASCII native projection')
    source, policy = admission['source'], admission['priority']
    roles = policy['roles']
    external_copies = []
    copy_paths = {}
    def record(key):
        source_record = source.data_records[key]
        source_path = source.data_path(key)
        stem = key[:-len('_surface')]+'_collision' if key.endswith('_surface') else key
        destination = root/'inputs/native_fields'/(stem+source_path.suffix)
        external_copies.append(dict(source_record=source_record,destination=str(destination)))
        copy_paths[str(source_path)] = str(destination)
        return dict(source_record)
    assets = {roles['background']: {'pa': record('background')}}
    for name in (roles['rf'], roles['ip'], roles['analyzer'], roles['detector']):
        assets[name] = {'pa': record(name + '_collision'), 'surface_witnesses': record(name + '_witness')}
        if name + '_surface' in source.data_records: assets[name]['fractional_surface'] = record(name + '_surface')
        if name + '_surface_state' in source.data_records: assets[name]['surface_state'] = record(name + '_surface_state')
        if 'fractional_surface' not in assets[name] and 'surface_state' not in assets[name]:
            raise ValueError('collision surface evidence missing')
    evidence = dict(zip(('boxes_record', 'clearance_record', 'source_record'),
                        policy['evidence_records'], strict=True))
    seed_record = file_record(structural_seed_path(5), 'required_evidence')
    seed = root/'inputs/structural_seed/5_instance_seed.iob'
    output = root/'simion/tracking/instrument.iob'
    projected = project_ip_mr_collision_iob(compiled, instances=policy['instances'], roles=roles,
        background_bounds_mm=policy['background_bounds_mm'], **evidence, asset_records=assets,
        seed_record=seed_record, empty_control_record=record('zero_particle_format_control'), output_iob=output)
    if projected['policy'] != policy:
        raise ValueError('tracking collision projection differs from admitted priority')
    def localize(value):
        if isinstance(value, dict):
            return {key:localize(item) for key,item in value.items()}
        if isinstance(value, list):
            return [localize(item) for item in value]
        return copy_paths.get(value,value) if isinstance(value,str) else value
    spec = localize(copy.deepcopy(projected['spec']))
    for instance in spec['instances'][1:]:
        local_companion = str(Path(instance['path']).with_suffix('.pa-surf'))
        instance['fractional_surface'] = local_companion
    binding = root/'inputs/sampled_basis.json'
    spec.update(role='ip_mr_sampled_tracking_iob',
                field_representation='assembly_sampled_basis_with_collision_geometry',
                scalar_binding=str(binding), seed_iob=str(seed), response_fields=[],
                bootstrap_paths=[str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1, 6)])
    spec_path = root/'inputs/tracking_iob.lua'
    materializations = {str(spec_path): 'return '+lua_value(spec)+'\n',
        str(binding): json.dumps(admission['basis'], ensure_ascii=False, allow_nan=False, indent=2)+'\n',
        str(output.with_suffix('.lua')): program,
        str(output.with_suffix('.fly2')): render_restart_fly2(native_source_rows)}
    wrapper = native_resource_path('build_tracking_iob.lua')
    bootstraps = tuple(spec['bootstrap_paths'])
    operations = tuple(dict(operation_id=name, role='SIMION', stage='prepare',
        arguments=['--nogui', '--noprompt', 'lua', str(wrapper), str(spec_path), mode, str(native_path_resource)],
        outputs=[str(output), *bootstraps] if mode == 'build' else [], success_marker=marker)
        for name, mode, marker in [('build_tracking_iob', 'build', 'IP_MR_SAMPLED_TRACKING_IOB=PASS'),
                                    ('verify_tracking_iob', 'verify', 'IP_MR_SAMPLED_TRACKING_IOB_REOPEN=PASS')])
    return NativeStagePlan(materializations,
                           (dict(source_record=seed_record, destination=str(seed)), *external_copies),
                           operations, (str(output), *bootstraps))


def execute_ip_mr_tracking(session: Any, *, source: Any, model: CompiledPreparedModel,
                         document: Mapping[str, Any], **options: Any) -> dict[str, Any]:
    """Bind a published sampled bundle to the existing tracking-unit owner."""
    from .tracking_execution import _artifact_record, _execute_tracking_bound_source
    from .ip_mr_tracking_admission import admit_ip_mr_tracking_fields
    admission = admit_ip_mr_tracking_fields(source.reference)
    if admission['model'].document != model.document:
        raise ValueError('tracking model differs from admitted sampled field')
    policy = admission['priority']; roles = policy['roles']
    assets = {}
    for name in (roles['rf'], roles['ip'], roles['analyzer'], roles['detector']):
        pa = _artifact_record(source, name+'_collision')
        witness = _artifact_record(source, name+'_witness')
        family = [pa]
        for suffix in ('_surface', '_surface_state'):
            if name + suffix in source.data_records:
                family.append(_artifact_record(source, name + suffix))
        if len(family) == 1:
            raise ValueError('collision surface evidence missing')
        assets[name] = dict(carrier_record=pa, family_records=family, witness_record=witness)
    clocks = dict(contract=_artifact_record(source,'clock_authority'), authority=_artifact_record(source,'instrument_epoch'))
    clocks['data_root'] = str(Path(clocks['contract']['path']).parent)
    relative = _clock_reference(document,clocks)
    compiled = model_geometry(model)
    geometry = dict(compiled.frontend_geometry, native_frame_id=document['native_frame_id'])
    return _execute_tracking_bound_source(session, source=source,model=model,document=document,compiled=compiled,
        geometry=geometry,design=None,stored_bank=None,frontend=assets,downstream={},field_workbench=None,
        borrowed=admission['immutable_input_records'],original_clock=clocks,relative_epoch=relative,
        ip_mr_admission=admission,**options)


def _plan_neutral_multi_tracking_workbench(compiled, *, admission, run_directory, program, native_source_rows, native_path_resource):
    import json
    from .source import lua_value, render_restart_fly2
    from .neutral_sampled_field import neutral_multi_background_grid
    root=Path(run_directory);source,basis,plan=admission['source'],admission['basis'],admission['plan'];geometry=compiled.frontend_geometry;tasks=plan['geometry_plan']['tasks']
    background_grid=neutral_multi_background_grid(admission['model'],basis);dims=background_grid['dimensions'];origin=background_grid['origin_mm'];pitch=background_grid['pitch_mm']
    grid=dict(zip(('nx','ny','nz'),dims,strict=True),**dict(zip(('dx_mm','dy_mm','dz_mm'),pitch,strict=True)))
    rotation=[[1,0,0],[0,1,0],[0,0,1]]
    def placement(v):return dict(x_mm=v[0],y_mm=v[1],z_mm=v[2],az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.)
    def record(key):return dict(source.data_records[key],path=str(source.data_path(key)))
    first=dict(role='background',instance_index=1,priority_number=1,path=record('background')['path'],grid=grid,rotation=rotation,placement=placement(origin));instances=[first]
    for index,task in enumerate(tasks,1):
        role=f'domain_{index:02d}';geo=geometry['domains'][task['role']];dims=geo['dimensions'];pitch=geo['pitch_mm'];native_grid=dict(zip(('nx','ny','nz'),dims,strict=True),dx_mm=pitch,dy_mm=pitch,dz_mm=pitch)
        key=source.metadata['collision_assets'][task['role']]['collision'];collision=record(key);surface_key=source.metadata['collision_assets'][task['role']].get('surface')
        if surface_key is not None:
            if Path(record(surface_key)['path']).resolve()!=Path(collision['path']).with_suffix('.pa-surf').resolve():raise ValueError('collision surface must be adjacent')
        elif 'surface_state' not in task['source_records']:raise ValueError('collision surface state or companion required')
        row=dict(role=role,instance_index=index+1,priority_number=index+1,path=collision['path'],grid=native_grid,rotation=rotation,placement=placement(geo['domain']['minimum_mm']),physical_samples=geo['physical_samples'],electrode_witness_ids=geo['electrode_witness_ids'],surface_witnesses=task['source_records']['surface_witnesses']['path'],fractional_surface=str(Path(collision['path']).with_suffix('.pa-surf')))
        if 'surface_state' in task['source_records']:row['surface_state']=task['source_records']['surface_state']['path']
        instances.append(row)
    count=len(instances);seed_record=file_record(structural_seed_path(count),'required_evidence');seed=root/'inputs/structural_seed'/f'{count}_instance_seed.iob';output=root/'simion/tracking/instrument.iob';binding=root/'inputs/sampled_basis.json';spec_path=root/'inputs/tracking_iob.lua';bootstraps=tuple(str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,count+1))
    spec=dict(schema_version=1,role='neutral_multi_sampled_tracking_iob',field_representation='neutral_multi_sampled_basis_with_collision_geometry',scalar_binding=str(binding),collision_roles=dict(background='background',domains=[row['role'] for row in instances[1:]]),instances=instances,seed_iob=str(seed),output_iob=str(output),response_fields=[],bootstrap_paths=list(bootstraps))
    materials={str(spec_path):'return '+lua_value(spec)+'\n',str(binding):json.dumps(basis,ensure_ascii=False,allow_nan=False,indent=2)+'\n',str(output.with_suffix('.lua')):program,str(output.with_suffix('.fly2')):render_restart_fly2(native_source_rows)}
    wrapper=native_resource_path('build_tracking_iob.lua');ops=tuple(dict(operation_id=name,role='SIMION',stage='prepare',arguments=['--nogui','--noprompt','lua',str(wrapper),str(spec_path),mode,str(native_path_resource)],outputs=[str(output),*bootstraps] if mode=='build' else [],success_marker=marker) for name,mode,marker in [('build_tracking_iob','build','NEUTRAL_SAMPLED_TRACKING_IOB=PASS'),('verify_tracking_iob','verify','NEUTRAL_SAMPLED_TRACKING_IOB_REOPEN=PASS')])
    return NativeStagePlan(materials,(dict(source_record=seed_record,destination=str(seed)),),ops,(str(output),*bootstraps))
