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
    names=['parent'] if joint else compiled.frontend_geometry['composition_plan']['scope']['instance_ids']
    if not native_source_rows or set(carriers)!=set(names):
        raise ValueError('RF tracking workbench needs its nonempty source and exact field domains')
    seed=file_record(structural_seed_path(len(names)),'required_evidence')
    projection=plan_geometry_build(compiled,run_directory=root,seed_record=seed,native_path_resource=native_path_resource)
    output=root/'simion/tracking/instrument.iob'
    spec=root/'inputs/tracking_iob.lua'
    original=projection.materializations[str(root/'inputs/geometry_iob.lua')]
    text='local spec=(function()\n'+original+'\nend)()\n'
    kind='RF_IP' if joint else 'OA' if compiled.frontend_geometry['role']=='simion_independent_oa_geometry' else 'RF'
    text+="spec.role="+lua_value('rf_ip_tracking_iob' if joint else 'independent_'+kind.lower()+'_tracking_iob')+"\nspec.output_iob="+lua_value(str(output))+"\nspec.response_fields={}\n"
    for index,name in enumerate(names,1):
        asset=carriers[name]
        surface=next(row for row in asset['family_records'] if row['path'].endswith('.pa-surf'))
        text+='spec.instances['+str(index)+'].path='+lua_value(asset['carrier_record']['path'])+'\n'
        text+='spec.instances['+str(index)+'].fractional_surface='+lua_value(surface['path'])+'\n'
        text+='spec.instances['+str(index)+'].surface_witnesses='+lua_value(asset['witness_record']['path'])+'\n'
        mappings=compiled.frontend_geometry['electrode_bindings']
        labels=sorted({value for group in mappings.values() for value in group.values()}) if joint else sorted(set(mappings[name].values()))
        text+='spec.instances['+str(index)+'].response_ids='+lua_value(labels)+'\n'
    text+='return spec\n'
    materials={str(spec):text,str(output.with_suffix('.lua')):program,str(output.with_suffix('.fly2')):render_restart_fly2(native_source_rows)}
    wrapper=native_resource_path('build_tracking_iob.lua')
    # The same canonical writer creates these neutral container inputs before
    # replacing all slots. Declare them even if a failed writer retains them.
    bootstraps=tuple(str(Path(projection.input_copies[0]['destination']).parent/f'iob_seed_placeholder_{index:02d}.pa0')
        for index in range(1,len(names)+1))
    marker_prefix='RF_IP' if joint else 'INDEPENDENT_'+kind
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

def prepare_rf_ip_hs1(model: CompiledPreparedModel, request: Mapping[str, Any]) -> dict[str, Any]:
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
    if geometry['role'] != 'simion_rf_ip_geometry':
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
    bounds = geometry['numerical_domains']['parent']['bounds_mm']
    parent = BoxDomain(tuple(bounds[a+'_min'] for a in 'xyz'), tuple(bounds[a+'_max'] for a in 'xyz'),
                       (True, True, True), (True, True, True))
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
    return dict(identity=identity, vendor_record=dict(vendor), vendor_original=original,
                vendor_adapted=adapted, bath_runtime=bath, outer_runtime=outside,
                query_frame_id=pose.to_frame_id)