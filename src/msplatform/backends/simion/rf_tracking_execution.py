"""Independent RF/OA field/source binding and structural IOB projection; no independent run owner."""
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from msplatform.contracts.gas import BoxDomain, GasFieldSpec
from msplatform.contracts.rigid_transform import RigidTransform
from .artifacts import NativeStagePlan, CompiledPreparedModel
from .model import model_geometry
from .model_execution import _protected_source,_clock_reference
from .native_plans import plan_geometry_build
from .resources import structural_seed_path,native_resource_path
from .source import lua_value,render_restart_fly2
from .rf_field_execution import require_rf_reuse
from msplatform.io.manifest_records import file_record


def execute_rf_tracking(session,*,source,model,document,**options):
    from .tracking_execution import _execute_tracking_bound_source,_artifact_record
    compiled=model_geometry(model)
    geometry=dict(compiled.frontend_geometry,native_frame_id=document['native_frame_id'])
    selected,producer,assets=require_rf_reuse(source.reference,identity=source.metadata['spatial_identity'],geometry=geometry)
    borrowed=[record for row in assets.values() for record in [*row['family_records'],row['witness_record']]]
    for artifact in [selected,producer]:
        _protected_source(session,artifact.reference['manifest'],required_paths=[row['path'] for row in borrowed])
    clocks=dict(contract=_artifact_record(source,'clock_authority'),authority=_artifact_record(source,'instrument_epoch'))
    clocks['data_root']=str(Path(clocks['contract']['path']).parent)
    relative=_clock_reference(document,clocks)
    return _execute_tracking_bound_source(session,source=source,model=model,document=document,compiled=compiled,
        geometry=geometry,design=None,stored_bank=None,frontend=assets,downstream={},field_workbench=None,
        borrowed=borrowed,original_clock=clocks,relative_epoch=relative,**options)


def plan_rf_tracking_workbench(compiled,*,carriers,run_directory,program,native_source_rows,native_path_resource):
    root=Path(run_directory)
    joint=compiled.frontend_geometry.get('role')=='simion_rf_ip_geometry'
    static_world=compiled.frontend_geometry.get('role')=='simion_neutral_world_collision_geometry'
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
        surface=next(row for row in asset['family_records'] if row['path'].endswith('.pa-surf'))
        text+='spec.instances['+str(index)+'].path='+lua_value(asset['carrier_record']['path'])+'\n'
        text+='spec.instances['+str(index)+'].fractional_surface='+lua_value(surface['path'])+'\n'
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



def compile_continuous_hs1_gas(baseline: dict, *, bath_domain: BoxDomain,
                               outer: GasFieldSpec, placement: RigidTransform,
                               parent_domain: BoxDomain) -> tuple[str, str]:
    """Compile explicit IP bath and outer fields in the selected native frame."""
    from msplatform.backends.simion.gas_runtime import compile_gas_runtime
    from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import (
        build_gas_field_spec, validate_continuous_hs1_gas, validate_continuous_parent_coverage)
    from msplatform.gas.field import prepare_gas_field

    bath = build_gas_field_spec(baseline, domain=bath_domain)
    validate_continuous_hs1_gas(bath, outer, gas_mass_amu=baseline['gas']['mass_amu'])
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

    if not isinstance(request, Mapping) or set(request) != {'bath_domain', 'outer', 'vendor_record', 'numerics'}:
        raise ValueError('RF-IP HS1 requires explicit bath, outer, vendor record and numerics')
    bath_domain, outer, vendor, numerics = (request[k] for k in ('bath_domain', 'outer', 'vendor_record', 'numerics'))
    if not isinstance(bath_domain, BoxDomain) or not isinstance(outer, GasFieldSpec):
        raise ValueError('RF-IP HS1 gas inputs require explicit typed field contracts')
    if outer.source.reference is not None:
        raise ValueError('RF-IP HS1 referenced outer gas needs its published-source owner')
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
    composition = geometry['composition_plan']
    ids = [name for name, row in composition['components'].items()
           if row['project_id'] == 'dual_pressure_rectilinear_ion_processor']
    poses = [row['transform'] for row in composition['recipe']['instances']
             if len(ids) == 1 and row['instance_id'] == ids[0]]
    if len(poses) != 1:
        raise ValueError('RF-IP HS1 requires one selected IP placement')
    pose = RigidTransform.from_contract(poses[0])
    if pose.from_frame_id != outer.frame_id or pose.to_frame_id != document['native_frame_id']:
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
    baseline = document['drive']['ip_schedule']['baseline']
    bath, outside = compile_continuous_hs1_gas(baseline, bath_domain=bath_domain, outer=outer,
                                                placement=pose, parent_domain=parent)
    def sha(data):
        return hashlib.sha256(data).hexdigest()
    identity = dict(bath_domain=asdict(bath_domain), placement=poses[0], numerics=dict(numerics),
                    vendor={k: vendor[k] for k in ('bytes', 'sha256')},
                    vendor_adapted_sha256=sha(adapted.encode('utf-8')),
                    bath_runtime_sha256=sha(bath.encode('utf-8')),
                    outer_runtime_sha256=sha(outside.encode('utf-8')))
    if role == 'simion_ip_mr_complete_geometry':
        identity['common_world_domain'] = asdict(parent)
        identity['common_world_frame_id'] = common_world_frame_id
    return dict(identity=identity, vendor_record=dict(vendor), vendor_original=original,
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
    def record(key):
        return dict(source.data_records[key], path=str(source.data_path(key)))
    assets = {roles['background']: {'pa': record('background')}}
    for name in (roles['rf'], roles['ip'], roles['analyzer'], roles['detector']):
        assets[name] = {'pa': record(name + '_collision'),
                        'fractional_surface': record(name + '_surface'),
                        'surface_witnesses': record(name + '_witness')}
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
    spec = copy.deepcopy(projected['spec'])
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
    return NativeStagePlan(materializations, (dict(source_record=seed_record, destination=str(seed)),),
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
        surface = _artifact_record(source, name+'_surface')
        witness = _artifact_record(source, name+'_witness')
        assets[name] = dict(carrier_record=pa, family_records=[pa,surface], witness_record=witness)
    clocks = dict(contract=_artifact_record(source,'clock_authority'), authority=_artifact_record(source,'instrument_epoch'))
    clocks['data_root'] = str(Path(clocks['contract']['path']).parent)
    relative = _clock_reference(document,clocks)
    compiled = model_geometry(model)
    geometry = dict(compiled.frontend_geometry, native_frame_id=document['native_frame_id'])
    return _execute_tracking_bound_source(session, source=source,model=model,document=document,compiled=compiled,
        geometry=geometry,design=None,stored_bank=None,frontend=assets,downstream={},field_workbench=None,
        borrowed=admission['immutable_input_records'],original_clock=clocks,relative_epoch=relative,
        ip_mr_admission=admission,**options)
