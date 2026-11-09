"""RF field/source binding and structural IOB projection; no independent run owner."""
from pathlib import Path
from .artifacts import NativeStagePlan
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
    names=compiled.frontend_geometry['composition_plan']['scope']['instance_ids']
    if not native_source_rows or set(carriers)!=set(names):
        raise ValueError('RF tracking workbench needs its nonempty source and exact field domains')
    seed=file_record(structural_seed_path(len(names)),'required_evidence')
    projection=plan_geometry_build(compiled,run_directory=root,seed_record=seed,native_path_resource=native_path_resource)
    output=root/'simion/tracking/instrument.iob'
    spec=root/'inputs/tracking_iob.lua'
    original=projection.materializations[str(root/'inputs/geometry_iob.lua')]
    text='local spec=(function()\n'+original+'\nend)()\n'
    text+="spec.role='independent_rf_tracking_iob'\nspec.output_iob="+lua_value(str(output))+"\nspec.response_fields={}\n"
    for index,name in enumerate(names,1):
        asset=carriers[name]
        surface=next(row for row in asset['family_records'] if row['path'].endswith('.pa-surf'))
        text+='spec.instances['+str(index)+'].path='+lua_value(asset['carrier_record']['path'])+'\n'
        text+='spec.instances['+str(index)+'].fractional_surface='+lua_value(surface['path'])+'\n'
        text+='spec.instances['+str(index)+'].surface_witnesses='+lua_value(asset['witness_record']['path'])+'\n'
        text+='spec.instances['+str(index)+'].response_ids='+lua_value(sorted(set(compiled.frontend_geometry['electrode_bindings'][name].values())))+'\n'
    text+='return spec\n'
    materials={str(spec):text,str(output.with_suffix('.lua')):program,str(output.with_suffix('.fly2')):render_restart_fly2(native_source_rows)}
    wrapper=native_resource_path('build_tracking_iob.lua')
    # The same canonical writer creates these neutral container inputs before
    # replacing all slots. Declare them even if a failed writer retains them.
    bootstraps=tuple(str(Path(projection.input_copies[0]['destination']).parent/f'iob_seed_placeholder_{index:02d}.pa0')
        for index in range(1,len(names)+1))
    operations=tuple(dict(operation_id=name,role='SIMION',stage='prepare',
        arguments=['--nogui','--noprompt','lua',str(wrapper),str(spec),mode,str(native_path_resource)],
        outputs=[str(output),*bootstraps] if mode=='build' else [],success_marker=marker)
        for name,mode,marker in [('build_tracking_iob','build','INDEPENDENT_RF_TRACKING_IOB=PASS'),
                                ('verify_tracking_iob','verify','INDEPENDENT_RF_TRACKING_IOB_REOPEN=PASS')])
    return NativeStagePlan(materials,projection.input_copies,operations,(str(output),*bootstraps))
