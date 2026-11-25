"""Source admission for neutral-world sampled collision field publication."""
from __future__ import annotations
import copy
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from msplatform.execution.run_session import RunSession
from msplatform.assembly.model import Assembly
from msplatform.components.catalog import _from_provider
from msplatform.components.registry import project_descriptor
from msplatform.io.manifest_records import verify_record, record_path
from .field_closure import load_field_model, data_record
from .generic_scalar_binding import admit_linear_samples
from .ip_mr_collision_lineage import plan_neutral_collision_conversions
from .scalar_sample_binding import _small_product, _read


def prepare_neutral_sampled_inputs(model_reference: Mapping[str, Any], *, selection: Mapping[str, Any], output_directory: Path) -> dict[str, Any]:
    """Resolve registered sources and fresh collision conversion destinations."""
    return _resolve_neutral_sampled_inputs(model_reference, selection=selection, output_directory=output_directory)


def verify_neutral_sampled_inputs(model_reference: Mapping[str, Any], *, selection: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate the same sources without planning or writing collision outputs."""
    return _resolve_neutral_sampled_inputs(model_reference, selection=selection, output_directory=None)


def _resolve_neutral_sampled_inputs(model_reference: Mapping[str, Any], *, selection: Mapping[str, Any], output_directory: Path | None) -> dict[str, Any]:
    if not isinstance(selection,Mapping) or set(selection)-{'geometry_artifact','operator','samples','refinement_windows'} or not {'geometry_artifact','operator','samples'}<=set(selection):
        raise ValueError('explicit generic scalar geometry, operator and samples required')
    source=load_field_model(model_reference)
    owner=source.artifact
    manifest=_read(owner.manifest_location)
    request=manifest['inputs']['execution_request']
    verify_record('prepared model execution request',request,base_dir=owner.manifest_location.parent)
    request_path=record_path(request,base_dir=owner.manifest_location.parent)
    payload=_read(request_path)
    if payload.get('role')!='run_artifact_workflow_request' or payload['payload'].get('action')!='prepare_model':
        raise ValueError('prepared model source request differs')
    geometry_ref=payload['payload']['geometry']
    original=geometry_ref['manifest'];frozen=data_record(owner,'source_manifest')
    if any(str(original[k]).upper()!=str(frozen[k]).upper() for k in ('bytes','sha256')):
        raise ValueError('prepared model source geometry differs')
    if output_directory is None:
        from .ip_mr_collision_lineage import verify_neutral_collision_sources
        plan=verify_neutral_collision_sources(source.model, geometry_ref)
    else:
        plan=plan_neutral_collision_conversions(source.model,geometry_ref,output_directory=Path(output_directory))
    geometry=source.model.document['geometry']['frontend_geometry']
    multi=geometry.get('role')=='simion_neutral_multi_domain_collision_geometry'
    expected=set(geometry['domain_order']) if multi else {'world'}
    if {task['role'] for task in plan['tasks']} != expected or set(source.native_assets)!=expected:
        raise ValueError('complete declared collision assets required')
    for task in plan['tasks']:
        owned=source.native_assets[task['role']]
        actual={'raw_geometry':owned['raw_record'],'surface_witnesses':owned['witness_record']}
        if owned['surface_records']:actual['fractional_surface']=owned['surface_records'][0]
        if 'state_record' in owned:actual['surface_state']=owned['state_record']
        if set(actual)!=set(task['source_records']):raise ValueError('model-owned collision surface closure differs')
        for label,record in actual.items():
            if any(str(record[k]).upper()!=str(task['source_records'][label][k]).upper() for k in ('bytes','sha256')):
                raise ValueError('model-owned collision source differs: '+label)
        task['source_records']=copy.deepcopy(actual);task['raw_path']=actual['raw_geometry']['path']
    snapshot=source.model.document['geometry']['frontend_geometry']['source_snapshot'];layout=snapshot['composition_plan']
    components={}
    for name,interface in layout['components'].items():
        descriptor=project_descriptor(interface['project_id'])
        components[name]=_from_provider(descriptor.provider_id,snapshot['components_resolved'][name],interface,source_design=snapshot['components_source'][name])
    assembly=Assembly(layout,components)
    if multi:
        from .resources import STRUCTURAL_SEEDS
        if len(plan['tasks'])+1 not in STRUCTURAL_SEEDS:
            raise ValueError('no registered sampled-field structural seed for domain count plus background')
    binding=admit_linear_samples(model_reference=model_reference,assembly=assembly,geometry_artifact=selection['geometry_artifact'],operator=selection['operator'],samples=selection['samples'],refinement_windows=selection.get('refinement_windows'))
    references=[source.artifact.reference['manifest'],geometry_ref['manifest'],binding['geometry_reference']['manifest']]
    _,projection_product,projection_path=_small_product(binding['geometry_reference'],'geometry_artifact',('projection',))
    projection_record=projection_product['data']['projection']
    guards=[dict(request,path=str(request_path)),binding['geometry_execution_request'],dict(projection_record,path=str(record_path(projection_record,base_dir=projection_path.parent))),plan['compiled_geometry_record'],plan['geometry_completion_record']]

    prepared={key:data_record(owner,key) for key in ('compiled_model','clock_authority','instrument_epoch')}
    guards.extend(prepared.values())
    for task in plan['tasks']:guards.extend(task['source_records'].values())
    for row in binding['bases'].values():
        for level in [row,*row.get('refinement_windows',[])]:
            references.extend((level['reference']['manifest'],level['field_solution_reference']['manifest']))
            if level.get('original_samples_reference') is not None: references.append(level['original_samples_reference']['manifest'])
            guards.extend(level['records'].values())
            for ref,kind,names in ((level['reference'],'scalar_field_samples',('projection','grid','request','geometry_validation','reopen_geometry','reopen_solution','report','field_solution_manifest')),(level['field_solution_reference'],'field_solution',('request','projection','geometry_validation','reopen_geometry','reopen_solution'))):
                _,product,path=_small_product(ref,kind,names)
                for name in names:
                    record=product['data'][name];guards.append(dict(record,path=str(record_path(record,base_dir=path.parent))))
    guards.extend(references)
    def unique(records):
        result={}
        for row in records:
            key=str(Path(row['path']).resolve());prior=result.get(key)
            if prior is not None and any(prior[k]!=row[k] for k in ('bytes','sha256')):raise ValueError('conflicting protected source identity')
            result[key]=dict(row)
        return list(result.values())
    return dict(model=source.model,prepared_source=source.artifact.reference,prepared_records=prepared,geometry_plan=plan,binding=binding,
                source_references=[dict(manifest_record=row) for row in unique(references)],immutable_input_records=unique(guards),
                expected_operation_ids=tuple(name for index in range(1,len(plan['tasks'])+1) for name in (f'collision_build_{index:02d}',f'collision_verify_{index:02d}')) + ('background_build','background_verify','collision_iob_build','collision_iob_verify'))


def neutral_source_paths(model_value: Any) -> dict[str, Path]:
    """Resolve the existing registered source closure for neutral field consumers."""
    from msplatform.execution import inputs as execution_inputs
    from msplatform.execution.inputs import resolve_python_module_sources
    from . import neutral_sampled_field, ip_mr_collision_lineage, generic_scalar_binding, scalar_sample_binding, field_closure, native_surface_state, model, assembly_geometry, collision_overlay, generic_geometry, mr_geometry
    from msplatform.backends.comsol import assembly_geometry as comsol_geometry, assembly_electrostatic_model, assembly_field_export, assembly_field_solution
    from msplatform.components import shape_query, geometry_members, registry, catalog, cad_geometry
    from msplatform.assembly import model as assembly_model, resolve_assembly
    from msplatform.contracts import rigid_transform
    modules=[neutral_sampled_field,ip_mr_collision_lineage,generic_scalar_binding,scalar_sample_binding,field_closure,native_surface_state,model,assembly_geometry,collision_overlay,generic_geometry,mr_geometry,comsol_geometry,assembly_electrostatic_model,assembly_field_export,assembly_field_solution,shape_query,geometry_members,registry,catalog,cad_geometry,assembly_model,resolve_assembly,rigid_transform,execution_inputs]
    paths={module.__name__:Path(module.__file__).resolve(strict=True) for module in modules}
    snapshot=model_value.document['geometry']['frontend_geometry']['source_snapshot']
    for name in snapshot['composition_plan']['scope']['instance_ids']:
        descriptor=project_descriptor(snapshot['composition_plan']['components'][name]['project_id'])
        paths.update(resolve_python_module_sources(descriptor.source_closure))
    return paths


def execute_neutral_sampled_fields(session: RunSession, *, model_reference: Mapping[str, Any], selection: Mapping[str, Any], limits: Mapping[str, Any], allow_asynchronous_io: bool | None = None) -> dict[str, Any]:
    """Use the existing owner to build and reopen world collision and background arrays."""
    import json
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.resources import resource_path
    from msplatform.execution.run_paths import project_run_path
    from msplatform.io.manifest_records import file_record
    from .ip_mr_collision_lineage import collision_conversion_result
    from .model import require_prepared_model, model_geometry
    from .model_execution import _protected_source
    from .native_io import apply_native_io_mode
    from .resources import native_resource_path, structural_seed_path
    from .source import lua_value
    plan=prepare_neutral_sampled_inputs(model_reference,selection=selection,output_directory=session.artifact_run_dir/'simion/collision')
    ids=plan['expected_operation_ids']
    if session.expected_operation_ids!=ids:raise ValueError('neutral sampled action operation graph differs')
    for ref in plan['source_references']:_protected_source(session,ref['manifest_record'])
    _protected_source(session,plan['prepared_source']['manifest'],required_paths=[r['path'] for r in plan['immutable_input_records']])
    session.add_inputs(('neutral_source_'+str(i),r) for i,r in enumerate(plan['immutable_input_records'],1))
    def owned(path,role):
        path=Path(path)
        if not path.is_absolute() or not session.canonical_path(path).is_relative_to(session.artifact_run_dir):raise ValueError('neutral field destination escapes owner')
        if path.exists() or path.is_symlink():raise FileExistsError('neutral field destination exists: '+str(path))
        path.parent.mkdir(parents=True,exist_ok=True);session.declare_file(path,role);return path
    def project(path):return project_run_path(str(path),session.artifact_run_dir,session.run_dir)
    modules=neutral_source_paths(plan['model'])
    guards=[]
    for module_name,path in modules.items():
        original=file_record(path,'required_evidence');name=module_name.replace('.','_');target=owned(session.input_dir/'native_sources'/(name+'.py'),'required_evidence');copied=freeze_file(path,target,retention_role='required_evidence')
        copied.pop('source_path',None)
        if any(original[k]!=copied[k] for k in ('bytes','sha256')):raise ValueError('frozen neutral source differs: '+name)
        session.add_input('neutral_code_'+name,copied);guards.extend((original,copied))
    names=('raw_collision_pa.lua','create_numerical_background.lua','reopen_numerical_background.lua','build_geometry_iob.lua','iob_core.lua')
    resources={name:native_resource_path(name) for name in names};resources['native_run_path.lua']=resource_path('native_run_path.lua');frozen={}
    for name,path in resources.items():
        original=file_record(path,'required_evidence');target=owned(session.input_dir/'native_sources'/name,'required_evidence');record=freeze_file(path,target,retention_role='required_evidence')
        record.pop('source_path',None)
        if any(original[k]!=record[k] for k in ('bytes','sha256')):raise ValueError('frozen native resource differs: '+name)
        session.add_input('neutral_resource_'+name,record);frozen[name]=record;guards.extend((original,record))
    def run(operation,args,marker,extra=()):
        unique={}
        for record in [*guards,*plan['immutable_input_records'],*extra]:
            key=str(Path(record['path']).resolve());prior=unique.get(key)
            if prior is not None and any(prior[k]!=record[k] for k in ('bytes','sha256')):raise ValueError('conflicting neutral guard identity')
            unique[key]=dict(record)
        argv=apply_native_io_mode([str(session.context.tools['simion']),'--nogui','--noprompt',*args],allow_asynchronous_io=allow_asynchronous_io)
        session.run_process(operation,executable=session.context.tools['simion'],arguments=argv[1:],role='SIMION',stage='prepare',limits=limits,immutable_input_records=list(unique.values()))
        ordinal=ids.index(operation)+1;log=session.canonical_path(session.log_dir/f'operation_{ordinal:04d}.stdout.log')
        if marker.encode('ascii') not in log.read_bytes():raise ValueError('neutral native completion marker missing: '+operation)
        return file_record(log,'required_evidence')
    if plan['model'].document['geometry']['frontend_geometry'].get('role') == 'simion_neutral_multi_domain_collision_geometry':
        return _execute_neutral_multi(session,plan=plan,owned=owned,project=project,run=run,frozen=frozen)
    task=plan['geometry_plan']['tasks'][0];target=owned(Path(task['output_path']),'solver_native_binary');side=owned(target.with_suffix('.pa-surf'),'solver_native_binary')
    tail=[project(task['raw_path']),project(target),project(frozen['native_run_path.lua']['path'])]
    if 'surface_state' in task['source_records']:tail.append(project(task['source_records']['surface_state']['path']))
    prefix=['lua',project(frozen['raw_collision_pa.lua']['path'])]
    built=run('collision_build_01',[*prefix,'build',*tail],'RAW_COLLISION_BUILD=PASS',task['source_records'].values())
    collision=file_record(session.canonical_path(target),'solver_native_binary');surface=file_record(session.canonical_path(side),'solver_native_binary') if side.is_file() else None
    verified=run('collision_verify_01',[*prefix,'verify',*tail],'RAW_COLLISION_VERIFY=PASS',[collision,*([surface] if surface else [])])
    audit=collision_conversion_result(plan['geometry_plan'],task,output_record=collision,surface_record=surface,build_log_record=built,verify_log_record=verified,converter_record=frozen['raw_collision_pa.lua'])
    compiled=model_geometry(plan['model']);geo=compiled.frontend_geometry;dims=geo['dimensions'];pitch=[geo['pitch_mm']]*3;origin=geo['domain']['minimum_mm'];grid=dict(zip(('nx','ny','nz'),dims,strict=True),dx_mm=pitch[0],dy_mm=pitch[1],dz_mm=pitch[2])
    background=owned(session.artifact_run_dir/'simion/collision/background.pa','solver_native_binary');args=[project(background),*(str(x) for x in dims),*(format(x,'.17g') for x in pitch),project(frozen['native_run_path.lua']['path'])]
    run('background_build',['lua',project(frozen['create_numerical_background.lua']['path']),*args],'NUMERICAL_CARRIER_REOPEN=PASS')
    bg=file_record(session.canonical_path(background),'solver_native_binary')
    run('background_verify',['lua',project(frozen['reopen_numerical_background.lua']['path']),*args],'NUMERICAL_CARRIER_COLD_REOPEN=PASS',[bg])
    seed_source=structural_seed_path(2);seed=owned(session.input_dir/'collision_seed/2_instance_seed.iob','required_evidence');freeze_file(seed_source,seed);seed_record=file_record(session.canonical_path(seed),'required_evidence');session.add_input('collision_seed',seed_record)
    control=owned(session.input_dir/'collision_empty.fly2','required_evidence');control.write_text('particles{coordinates=0,}\n',encoding='utf8');control_record=file_record(session.canonical_path(control),'required_evidence');session.add_input('collision_empty',control_record)
    iob=owned(session.artifact_run_dir/'simion/collision/collision.iob','solver_native_binary');fly=owned(iob.with_suffix('.fly2'),'required_evidence')
    for i in range(1,3):owned(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0','solver_native_binary')
    placement=dict(x_mm=origin[0],y_mm=origin[1],z_mm=origin[2],az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.);rotation=[[1,0,0],[0,1,0],[0,0,1]]
    first=dict(role='background',instance_index=1,priority_number=1,path=bg['path'],grid=grid,rotation=rotation,placement=placement)
    second=dict(role='world',instance_index=2,priority_number=2,path=collision['path'],grid=grid,rotation=rotation,placement=placement,physical_samples=geo['physical_samples'],electrode_witness_ids=geo['electrode_witness_ids'],surface_witnesses=task['source_records']['surface_witnesses']['path'],fractional_surface=str(target.with_suffix('.pa-surf')))
    if 'surface_state' in task['source_records']:second['surface_state']=task['source_records']['surface_state']['path']
    spec=dict(schema_version=1,role='neutral_sampled_collision_iob_build',collision_roles=dict(background='background',world='world'),instances=[first,second],seed_iob=str(seed),output_iob=str(iob),empty_particle_control=str(control),bootstrap_paths=[str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,3)])
    spec_path=owned(session.input_dir/'collision_iob.lua','required_evidence');spec_path.write_text('return '+lua_value(spec)+'\n',encoding='utf8');spec_record=file_record(session.canonical_path(spec_path),'required_evidence');session.add_input('collision_iob_spec',spec_record)
    tail=[project(spec_path),'build_geometry',project(frozen['native_run_path.lua']['path'])];wrapper=['lua',project(frozen['build_geometry_iob.lua']['path'])]
    iob_guards=[seed_record,control_record,spec_record,bg,collision,*([surface] if surface else [])]
    run('collision_iob_build',[*wrapper,*tail],'NEUTRAL_SAMPLED_COLLISION_IOB=PASS',iob_guards)
    iob_record=file_record(session.canonical_path(iob),'solver_native_binary');tail[1]='verify_geometry'
    run('collision_iob_verify',[*wrapper,*tail],'NEUTRAL_SAMPLED_COLLISION_IOB_REOPEN=PASS',[*iob_guards,iob_record])
    for record in plan['immutable_input_records']:verify_record('neutral field source before publication',dict(record))
    basis=owned(session.input_dir/'sampled_basis.json','required_evidence');basis.write_text(json.dumps(plan['binding'],allow_nan=False,indent=2)+'\n',encoding='utf8');basis_record=file_record(session.canonical_path(basis),'required_evidence');session.add_input('sampled_basis',basis_record)
    audit_path=owned(session.result_dir/'collision_audit.json','required_evidence');audit_path.write_text(json.dumps(audit,allow_nan=False,indent=2)+'\n',encoding='utf8')
    records=dict(plan['prepared_records'],sampled_basis=basis_record,background=bg,collision=collision,workbench=iob_record,zero_particle_format_control=file_record(session.canonical_path(fly),'required_evidence'),collision_audit=file_record(session.canonical_path(audit_path),'required_evidence'))
    if surface is not None:records['collision_surface']=surface
    document=require_prepared_model(plan['model']);metadata=dict(backend='simion',field_status='available',source_status='not_requested',model_identity_sha256=document['model_identity_sha256'],clock=document['drive']['clock'],field_representation='neutral_sampled_basis_with_collision_geometry',refine_calls=0,compute_calls=0,fly_calls=0,scientific_qualification='not_granted',scalar_coverage='not_qualified')
    outputs=[str(session.canonical_path(path)) for path in [target,background,iob,fly,audit_path,*([side] if surface else [])]]
    return dict(status='success',summary=metadata,output_paths=outputs,required_output_paths=outputs,retention_preserve_paths=[],manifest_extra_fields={'products':{'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=records)}})


def neutral_multi_background_grid(model, binding):
    geometry=model.document['geometry']['frontend_geometry']; grid=binding['grid']
    dims=grid['dimensions'];pitch=grid['pitch_mm'];origin=grid['origin_mm']
    if grid['frame_id'] != model.document['native_frame_id']:
        raise ValueError('scalar background frame differs from collision domains')
    maximum=[origin[i]+(dims[i]-1)*pitch[i] for i in range(3)]
    for name in geometry['domain_order']:
        domain=geometry['domains'][name]['domain']
        if any(domain['minimum_mm'][i]<origin[i] or domain['maximum_mm'][i]>maximum[i] for i in range(3)):
            raise ValueError('scalar background does not enclose each collision domain')
    return copy.deepcopy(grid)

def _execute_neutral_multi(session, *, plan, owned, project, run, frozen):
    """Publish each verified collision PA and a scalar-grid background under one owner."""
    import json
    from .source import lua_value
    from .resources import structural_seed_path
    from .ip_mr_collision_lineage import collision_conversion_result
    from .model import require_prepared_model
    from msplatform.execution.inputs import freeze_file
    from msplatform.io.manifest_records import file_record,verify_record
    geometry=plan['model'].document['geometry']['frontend_geometry'];tasks=plan['geometry_plan']['tasks'];sample_grid=neutral_multi_background_grid(plan['model'],plan['binding'])
    dims=sample_grid['dimensions'];pitch=sample_grid['pitch_mm'];origin=sample_grid['origin_mm']
    grid=dict(zip(('nx','ny','nz'),dims,strict=True),**dict(zip(('dx_mm','dy_mm','dz_mm'),pitch,strict=True)))
    background=owned(session.artifact_run_dir/'simion/collision/background.pa','solver_native_binary')
    args=[project(background),*(str(x) for x in dims),*(format(x,'.17g') for x in pitch),project(frozen['native_run_path.lua']['path'])]
    converted=[]; audits=[]; outputs=[]
    for index,task in enumerate(tasks,1):
        target=owned(Path(task['output_path']),'solver_native_binary');side=owned(target.with_suffix('.pa-surf'),'solver_native_binary')
        tail=[project(task['raw_path']),project(target),project(frozen['native_run_path.lua']['path'])]
        if 'surface_state' in task['source_records']:tail.append(project(task['source_records']['surface_state']['path']))
        prefix=['lua',project(frozen['raw_collision_pa.lua']['path'])]
        built=run(f'collision_build_{index:02d}',[*prefix,'build',*tail],'RAW_COLLISION_BUILD=PASS',task['source_records'].values())
        record=file_record(session.canonical_path(target),'solver_native_binary');surface=file_record(session.canonical_path(side),'solver_native_binary') if side.is_file() else None
        verified=run(f'collision_verify_{index:02d}',[*prefix,'verify',*tail],'RAW_COLLISION_VERIFY=PASS',[record,*([surface] if surface else [])])
        audits.append(collision_conversion_result(plan['geometry_plan'],task,output_record=record,surface_record=surface,build_log_record=built,verify_log_record=verified,converter_record=frozen['raw_collision_pa.lua']))
        converted.append((task,record,surface,target));outputs.extend([target,*([side] if surface else [])])
    run('background_build',['lua',project(frozen['create_numerical_background.lua']['path']),*args],'NUMERICAL_CARRIER_REOPEN=PASS')
    bg=file_record(session.canonical_path(background),'solver_native_binary')
    run('background_verify',['lua',project(frozen['reopen_numerical_background.lua']['path']),*args],'NUMERICAL_CARRIER_COLD_REOPEN=PASS',[bg])
    count=len(tasks)+1;seed_source=structural_seed_path(count);seed=owned(session.input_dir/'collision_seed'/f'{count}_instance_seed.iob','required_evidence');freeze_file(seed_source,seed);seed_record=file_record(session.canonical_path(seed),'required_evidence');session.add_input('collision_seed',seed_record)
    control=owned(session.input_dir/'collision_empty.fly2','required_evidence');control.write_text('particles{coordinates=0,}\n',encoding='utf8');control_record=file_record(session.canonical_path(control),'required_evidence');session.add_input('collision_empty',control_record)
    iob=owned(session.artifact_run_dir/'simion/collision/collision.iob','solver_native_binary');fly=owned(iob.with_suffix('.fly2'),'required_evidence')
    for i in range(1,count+1):owned(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0','solver_native_binary')
    rotation=[[1,0,0],[0,1,0],[0,0,1]]
    def placement(x):return dict(x_mm=x[0],y_mm=x[1],z_mm=x[2],az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.)
    instances=[dict(role='background',instance_index=1,priority_number=1,path=bg['path'],grid=grid,rotation=rotation,placement=placement(origin))];assets={};records=dict(plan['prepared_records']);guards=[seed_record,control_record,bg]
    for index,(task,record,surface,target) in enumerate(converted,1):
        role=f'domain_{index:02d}';geo=geometry['domains'][task['role']];d=geo['dimensions'];p=geo['pitch_mm'];native_grid=dict(zip(('nx','ny','nz'),d,strict=True),dx_mm=p,dy_mm=p,dz_mm=p)
        row=dict(role=role,instance_index=index+1,priority_number=index+1,path=record['path'],grid=native_grid,rotation=rotation,placement=placement(geo['domain']['minimum_mm']),physical_samples=geo['physical_samples'],electrode_witness_ids=geo['electrode_witness_ids'],surface_witnesses=task['source_records']['surface_witnesses']['path'],fractional_surface=str(target.with_suffix('.pa-surf')))
        if 'surface_state' in task['source_records']:row['surface_state']=task['source_records']['surface_state']['path']
        instances.append(row);key=f'collision_{index:02d}';records[key]=record;assets[task['role']]=dict(collision=key)
        guards.append(record)
        if surface is not None:records[key+'_surface']=surface;assets[task['role']]['surface']=key+'_surface';guards.append(surface)
    spec=dict(schema_version=1,role='neutral_multi_sampled_collision_iob_build',collision_roles=dict(background='background',domains=[r['role'] for r in instances[1:]]),instances=instances,seed_iob=str(seed),output_iob=str(iob),empty_particle_control=str(control),bootstrap_paths=[str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,count+1)])
    spec_path=owned(session.input_dir/'collision_iob.lua','required_evidence');spec_path.write_text('return '+lua_value(spec)+'\n',encoding='utf8');spec_record=file_record(session.canonical_path(spec_path),'required_evidence');session.add_input('collision_iob_spec',spec_record);guards.append(spec_record)
    tail=[project(spec_path),'build_geometry',project(frozen['native_run_path.lua']['path'])];wrapper=['lua',project(frozen['build_geometry_iob.lua']['path'])]
    run('collision_iob_build',[*wrapper,*tail],'NEUTRAL_SAMPLED_COLLISION_IOB=PASS',guards);iob_record=file_record(session.canonical_path(iob),'solver_native_binary');tail[1]='verify_geometry'
    run('collision_iob_verify',[*wrapper,*tail],'NEUTRAL_SAMPLED_COLLISION_IOB_REOPEN=PASS',[*guards,iob_record])
    for record in plan['immutable_input_records']:verify_record('neutral field source before publication',dict(record))
    basis=owned(session.input_dir/'sampled_basis.json','required_evidence');basis.write_text(json.dumps(plan['binding'],allow_nan=False,indent=2)+'\n',encoding='utf8');basis_record=file_record(session.canonical_path(basis),'required_evidence');session.add_input('sampled_basis',basis_record)
    audit=owned(session.result_dir/'collision_audit.json','required_evidence');audit.write_text(json.dumps(audits,allow_nan=False,indent=2)+'\n',encoding='utf8')
    records.update(sampled_basis=basis_record,background=bg,workbench=iob_record,zero_particle_format_control=file_record(session.canonical_path(fly),'required_evidence'),collision_audit=file_record(session.canonical_path(audit),'required_evidence'))
    document=require_prepared_model(plan['model']);metadata=dict(backend='simion',field_status='available',source_status='not_requested',model_identity_sha256=document['model_identity_sha256'],clock=document['drive']['clock'],field_representation='neutral_multi_sampled_basis_with_collision_geometry',collision_assets=assets,refine_calls=0,compute_calls=0,fly_calls=0,scientific_qualification='not_granted',scalar_coverage='not_qualified')
    outputs=[str(session.canonical_path(p)) for p in [*outputs,background,iob,fly,audit]]
    return dict(status='success',summary=metadata,output_paths=outputs,required_output_paths=outputs,retention_preserve_paths=[],manifest_extra_fields={'products':{'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=records)}})
