"""Source admission for one existing-owner sampled IP–MR field action."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.assembly.model import Assembly
from msplatform.components.catalog import _from_provider
from msplatform.io.manifest_records import record_path, verify_record
from .field_closure import load_field_model, data_record
from .ip_mr_scalar_binding import resolve_ip_mr_scalar_basis
from .scalar_sample_binding import _small_product, _read
from .ip_mr_collision_lineage import plan_collision_conversions


def _priority_projection(model: Any, binding: Mapping[str, Any],
                         priority_evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Validate explicit background/slot geometry without materializing an output."""
    from .model import model_geometry
    from .native_plans import rigid_iob_placement
    from .ip_mr_collision_priority import compile_ip_mr_priority
    if not isinstance(priority_evidence,Mapping) or set(priority_evidence)!={'boxes_record','clearance_record','source_record'}:
        raise ValueError('explicit numerical boxes and clearance/source evidence required')
    grid=binding['grid'];origin=grid['origin_mm'];pitch=grid['pitch_mm'];dims=grid['dimensions']
    if any(type(n) is not int or n<3 for n in dims):raise ValueError('background grid requires at least three nodes per axis')
    compiled=model_geometry(model);geo=compiled.frontend_geometry
    projects=geo['composition_plan']['components'];selected=geo['composition_plan']['scope']['instance_ids']
    def component(project: str) -> str:
        values=[name for name in selected if projects[name]['project_id']==project]
        if len(values)!=1:raise ValueError('one explicitly selected '+project+' required')
        return values[0]
    rf=component('rf_multipole_ion_optics');ip=component('ion_processor')
    mr=component('multi_reflection_tof');background_id='numerical_background'
    roles=dict(background=background_id,rf=rf,ip=ip,analyzer=mr+'_analyzer',detector=mr+'_detector')
    background_bounds=[[origin[i],origin[i]+(dims[i]-1)*pitch[i]] for i in range(3)]
    instances=[dict(role=background_id,instance_index=1,priority_number=1,
        grid={**dict(zip(('nx','ny','nz'),dims)),**dict(zip(('dx_mm','dy_mm','dz_mm'),pitch))},
        rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=origin[0],y_mm=origin[1],z_mm=origin[2],
        az_deg=0,el_deg=0,rt_deg=0,scale=1))]
    for index,name in enumerate((rf,ip,mr+'_analyzer',mr+'_detector'),2):
        domain=geo['numerical_domains'][name];pose=geo['asset_poses'][name]
        instances.append(dict(role=name,instance_index=index,priority_number=index,
            grid={**domain['dimensions'],**{'d'+a+'_mm':domain['cell_mm_xyz'][a] for a in 'xyz'}},
            rotation=pose['rotation'],placement=rigid_iob_placement(pose,origin_mm=[domain['instance_origin_mm'][a] for a in 'xyz'])))
    verified=compile_ip_mr_priority(compiled,instances=instances,roles=roles,background_bounds_mm=background_bounds,**dict(priority_evidence))
    return dict(compiled=compiled,grid=copy.deepcopy(grid),roles=roles,instances=instances,
                background_bounds_mm=background_bounds,verified_priority=verified)



def prepare_ip_mr_field_inputs(model_reference: Mapping[str, Any], *, scalar_field_basis: Mapping[str, Any],
                               priority_evidence: Mapping[str, Mapping[str, Any]],
                               output_directory: Path) -> dict[str, Any]:
    """Admit source records before existing owner admission; no native action occurs."""
    source=load_field_model(model_reference,field_representation='assembly_sampled_basis_with_collision_geometry')
    model_manifest=source.artifact.manifest_location
    manifest=json.loads(model_manifest.read_text(encoding='utf-8-sig'))
    request_record=manifest['inputs']['execution_request']
    verify_record('prepared model execution request',request_record,base_dir=model_manifest.parent)
    model_request=dict(request_record,path=str(record_path(request_record,base_dir=model_manifest.parent)))
    request=_read(Path(model_request['path']))
    if request.get('role')!='run_artifact_workflow_request' or request['payload'].get('action')!='prepare_model':
        raise ValueError('prepared model source request differs')
    geometry_reference=request['payload']['geometry']
    original=geometry_reference['manifest'];frozen=data_record(source.artifact,'source_manifest')
    if any(str(original[k]).upper()!=str(frozen[k]).upper() for k in ('bytes','sha256')):
        raise ValueError('prepared model geometry source manifest differs')
    plan=plan_collision_conversions(source.model,geometry_reference,output_directory=output_directory)
    for task in plan['tasks']:
        owned=source.native_assets[task['role']]
        actual={'raw_geometry':owned['raw_record'],'surface_witnesses':owned['witness_record']}
        if owned['surface_records']: actual['fractional_surface']=owned['surface_records'][0]
        if 'state_record' in owned: actual['surface_state']=owned['state_record']
        if set(actual)!=set(task['source_records']):raise ValueError('model-owned collision surface closure differs')
        for label,record in actual.items():
            expected=task['source_records'][label]
            if any(str(record[k]).upper()!=str(expected[k]).upper() for k in ('bytes','sha256')):
                raise ValueError('model-owned collision source differs from original '+task['role']+' '+label)
        task['source_records']=copy.deepcopy(actual)
        task['raw_path']=actual['raw_geometry']['path']
    if not isinstance(scalar_field_basis,Mapping) or not {'geometry_artifact','operator','samples'}<=scalar_field_basis.keys() or set(scalar_field_basis)-{'geometry_artifact','operator','samples','refinement_windows'}:
        raise ValueError('explicit scalar basis geometry, operator and samples required')
    producer,geometry_product,location=_small_product(scalar_field_basis['geometry_artifact'],'geometry_artifact',('projection',))
    request_record=producer['inputs']['execution_request']
    verify_record('COMSOL geometry execution request',request_record,base_dir=location.parent)
    request=_read(record_path(request_record,base_dir=location.parent))
    if request.get('role')!='run_artifact_workflow_request' or request['payload'].get('action')!='build_comsol_geometry':
        raise ValueError('COMSOL geometry source request differs')
    snapshot=request['payload']['assembly'];layout=snapshot['composition_plan']
    provider_ids={'rf_multipole_ion_optics':'rf_multipole',
        'ion_processor':'ion_processor',
        'multi_reflection_tof':'multi_reflection_tof'}
    components={name:_from_provider(provider_ids[layout['components'][name]['project_id']],
        snapshot['components_resolved'][name],layout['components'][name],source_design=snapshot['components_source'][name])
        for name in layout['scope']['instance_ids']}
    assembly=Assembly(layout,components)
    binding=resolve_ip_mr_scalar_basis(model=source.model,assembly=assembly,**dict(scalar_field_basis))
    if binding['rf'] is None:
        raise ValueError('selected sampled-field action requires the RF component')
    references=[source.artifact.reference['manifest'],geometry_reference['manifest'],binding['geometry_reference']['manifest']]
    prepared_records={key:data_record(source.artifact,key) for key in
                      ('compiled_model','clock_authority','instrument_epoch','source_manifest')}
    guards=[model_request,*plan['immutable_input_records'],*prepared_records.values()]
    for task in plan['tasks']: guards.extend(task['source_records'].values())
    guards.append(dict(request_record,path=str(record_path(request_record,base_dir=location.parent))))
    projection_record=geometry_product['data']['projection']
    guards.append(dict(projection_record,path=str(record_path(projection_record,base_dir=location.parent))))
    for row in binding['bases'].values():
        for level in [row,*row.get('refinement_windows',[])]:
            references.extend((level['reference']['manifest'],level['field_solution_reference']['manifest']))
            if level.get('original_samples_reference') is not None:
                references.append(level['original_samples_reference']['manifest'])
            guards.extend(level['records'].values())
            small_names=('projection','request','report','reopen_geometry','reopen_solution',
                         'geometry_validation','field_solution_manifest')
            _,sample_product,sample_path=_small_product(level['reference'],'scalar_field_samples',small_names)
            for name in small_names:
                record=sample_product['data'][name]
                guards.append(dict(record,path=str(record_path(record,base_dir=sample_path.parent))))
            solution_names=('request','projection','geometry_validation','reopen_geometry','reopen_solution')
            _,solution_product,solution_path=_small_product(level['field_solution_reference'],'field_solution',solution_names)
            for name in solution_names:
                record=solution_product['data'][name]
                guards.append(dict(record,path=str(record_path(record,base_dir=solution_path.parent))))
    guards.extend(references)
    def unique(rows):
        result={}
        for row in rows:
            path=str(Path(row['path']).resolve());prior=result.get(path)
            if prior is not None and any(prior[k]!=row[k] for k in ('bytes','sha256')):
                raise ValueError('one protected path has conflicting identities')
            result[path]=dict(row)
        return result
    unique_refs=unique(references)
    unique_guards=unique([dict(row,retention_role=row.get('retention_role','required_evidence')) for row in guards])
    priority_projection=_priority_projection(source.model,binding,priority_evidence)
    ids=[name for task in plan['tasks'] for name in (task['build_operation'],task['verify_operation'])]
    ids.extend(['background_build','background_verify','collision_iob_build','collision_iob_verify'])
    return dict(model=source.model,prepared_source=source.artifact.reference,geometry_plan=plan,binding=binding,
        expected_operation_ids=tuple(ids),prepared_records=prepared_records,priority_projection=priority_projection,
        source_references=[dict(manifest_record=row) for row in unique_refs.values()],
        immutable_input_records=list(unique_guards.values()))


def execute_ip_mr_sampled_fields(session, *, model_reference: Mapping[str, Any],
        scalar_field_basis: Mapping[str, Any], priority_evidence: Mapping[str, Mapping[str, Any]],
        limits: Mapping[str, Any], allow_asynchronous_io: bool | None = None) -> dict[str, Any]:
    """Run collision preparation in the already-admitted field owner, with no field solve.

    All three kinds of PA remain explicit: sampled scalar fields, physical collision
    arrays, and the electrode-free numerical background. This action does not fly.
    """
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.resources import resource_path
    from msplatform.execution.run_paths import project_run_path
    from msplatform.io.manifest_records import file_record
    from .ip_mr_collision_lineage import collision_conversion_result
    from .ip_mr_collision_priority import project_ip_mr_collision_iob
    from .model import require_prepared_model
    from .model_execution import _protected_source
    from .native_io import apply_native_io_mode
    from .resources import native_resource_path, structural_seed_path
    from .source import lua_value

    if set(priority_evidence)!={'boxes_record','clearance_record','source_record'}:
        raise ValueError('explicit numerical boxes and clearance/source evidence required')
    owned_root=session.artifact_run_dir
    plan=prepare_ip_mr_field_inputs(model_reference,scalar_field_basis=scalar_field_basis,
                                   priority_evidence=priority_evidence,output_directory=owned_root/'simion/collision')
    tasks=plan['geometry_plan']['tasks']
    ids=tuple([name for task in tasks for name in (task['build_operation'],task['verify_operation'])]
        +['background_build','background_verify','collision_iob_build','collision_iob_verify'])
    if session.expected_operation_ids!=ids:
        raise ValueError('sampled field action differs from admitted operations')
    for ref in plan['source_references']:
        _protected_source(session,ref['manifest_record'])
    _protected_source(session,plan['prepared_source']['manifest'],
                      required_paths=[record['path'] for record in plan['immutable_input_records']])
    session.add_inputs(('sampled_source_'+str(index),record)
                       for index,record in enumerate(plan['immutable_input_records'],1))
    priority_evidence={name:dict(record,retention_role='required_evidence')
                       for name,record in priority_evidence.items()}
    for name,record in priority_evidence.items():
        verify_record(name,dict(record));session.add_input(name,dict(record))

    def owned(path: Path, role: str) -> Path:
        path=Path(path)
        if not path.is_absolute() or not session.canonical_path(path).is_relative_to(owned_root):
            raise ValueError('sampled field destination escapes admitted run')
        if path.exists() or path.is_symlink():
            raise FileExistsError('sampled field destination already exists: '+str(path))
        session.declare_file(path,role)
        return path

    def project(path: str | Path) -> str:
        return project_run_path(str(path),session.artifact_run_dir,session.run_dir)

    priority=plan['priority_projection']
    grid=priority['grid'];pitch=grid['pitch_mm'];dims=grid['dimensions']
    compiled=priority['compiled'];roles=priority['roles'];instances=priority['instances']
    background_id=roles['background'];background_bounds=priority['background_bounds_mm']

    frozen=session.input_dir/'native_sources'
    native_names=('raw_collision_pa.lua','create_numerical_background.lua','reopen_numerical_background.lua',
                  'build_geometry_iob.lua','iob_core.lua')
    resources={name:native_resource_path(name) for name in native_names}
    resources['native_run_path.lua']=resource_path('native_run_path.lua')
    from . import (ip_mr_field_execution, ip_mr_collision_lineage, ip_mr_collision_priority,
                   ip_mr_scalar_binding, scalar_sample_binding, field_closure, native_surface_state)
    code_guards=[]
    for module in (ip_mr_field_execution, ip_mr_collision_lineage, ip_mr_collision_priority,
                   ip_mr_scalar_binding, scalar_sample_binding, field_closure, native_surface_state):
        name=module.__name__.rsplit('.',1)[-1]
        path=Path(module.__file__).resolve(strict=True)
        original=file_record(path,'required_evidence')
        target=owned(frozen/(name+'.py'),'required_evidence');target.parent.mkdir(parents=True,exist_ok=True)
        freeze_file(path,target);copied=file_record(session.canonical_path(target),'required_evidence')
        if any(copied[k]!=original[k] for k in ('bytes','sha256')):
            raise ValueError('frozen Python source differs: '+name)
        session.add_input('sampled_source_code_'+name,copied)
        code_guards.extend((original,copied))
    resource_records={}
    for name,path in resources.items():
        target=owned(frozen/name,'required_evidence');target.parent.mkdir(parents=True,exist_ok=True)
        source_record=file_record(path,'required_evidence');freeze_file(path,target)
        record=file_record(session.canonical_path(target),'required_evidence')
        if any(record[k]!=source_record[k] for k in ('bytes','sha256')):
            raise ValueError('frozen native resource differs: '+name)
        session.add_input('sampled_native_'+name,record);resource_records[name]=record

    def run(operation: str, args: list[str], marker: str, guards: list[Mapping[str, Any]]) -> dict[str, Any]:
        argv=apply_native_io_mode([str(session.context.tools['simion']),'--nogui','--noprompt',*args],
                                 allow_asynchronous_io=allow_asynchronous_io)
        unique_guards={}
        closure=plan['immutable_input_records'] if operation in (ids[0],'collision_iob_verify') else ()
        if operation=='collision_iob_verify':
            for record in closure:verify_record('sampled field source before final native operation',dict(record))
        for record in [*guards,*code_guards,*priority_evidence.values(),*closure]:
            path=str(Path(record['path']).resolve());prior=unique_guards.get(path)
            if prior is not None and any(prior[k]!=record[k] for k in ('bytes','sha256')):
                raise ValueError('one native input path has conflicting identities')
            unique_guards[path]=dict(record)
        session.run_process(operation,executable=session.context.tools['simion'],arguments=argv[1:],
                            role='SIMION',stage='prepare',limits=limits,
                            immutable_input_records=list(unique_guards.values()))
        ordinal=session.expected_operation_ids.index(operation)+1
        log=session.canonical_path(session.log_dir/f'operation_{ordinal:04d}.stdout.log')
        if marker.encode('ascii') not in log.read_bytes():
            raise ValueError('sampled field native completion marker missing: '+operation)
        return file_record(log,'required_evidence')

    collision_records={};audits=[]
    for task in tasks:
        target=owned(Path(task['output_path']),'solver_native_binary')
        surface=owned(target.with_suffix('.pa-surf'),'solver_native_binary')
        target.parent.mkdir(parents=True,exist_ok=True)
        guards=[*task['source_records'].values(),resource_records['raw_collision_pa.lua'],resource_records['native_run_path.lua']]
        base=['lua',project(resource_records['raw_collision_pa.lua']['path'])]
        tail=[project(task['raw_path']),project(target),project(resource_records['native_run_path.lua']['path'])]
        state=task['source_records'].get('surface_state')
        if state: tail.append(project(state['path']))
        built=run(task['build_operation'],[*base,'build',*tail],'RAW_COLLISION_BUILD=PASS',guards)
        out=file_record(session.canonical_path(target),'solver_native_binary')
        surf=file_record(session.canonical_path(surface),'solver_native_binary') if surface.is_file() else None
        verified=run(task['verify_operation'],[*base,'verify',*tail],'RAW_COLLISION_VERIFY=PASS',[*guards,out,*([surf] if surf else [])])
        audit=collision_conversion_result(plan['geometry_plan'],task,output_record=out,surface_record=surf,
            build_log_record=built,verify_log_record=verified,converter_record=resource_records['raw_collision_pa.lua'])
        audits.append(audit)
        collision_records[task['role']]=dict(pa=out,surface_witnesses=task['source_records']['surface_witnesses'])
        if surf: collision_records[task['role']]['fractional_surface']=surf
        if state: collision_records[task['role']]['surface_state']=state

    background=owned(owned_root/'simion/collision/background.pa','solver_native_binary')
    background.parent.mkdir(parents=True,exist_ok=True)
    args=[project(background),*(str(x) for x in dims),*(format(x,'.17g') for x in pitch),project(resource_records['native_run_path.lua']['path'])]
    run('background_build',['lua',project(resource_records['create_numerical_background.lua']['path']),*args],
        'NUMERICAL_CARRIER_REOPEN=PASS',[resource_records['create_numerical_background.lua'],resource_records['native_run_path.lua']])
    bg=file_record(session.canonical_path(background),'solver_native_binary')
    run('background_verify',['lua',project(resource_records['reopen_numerical_background.lua']['path']),*args],
        'NUMERICAL_CARRIER_COLD_REOPEN=PASS',[bg,resource_records['reopen_numerical_background.lua'],resource_records['native_run_path.lua']])

    collision_records[background_id]={'pa':bg}
    seed_source=structural_seed_path(5);seed=owned(session.input_dir/'collision_seed/5_instance_seed.iob','required_evidence')
    seed.parent.mkdir(parents=True,exist_ok=True);freeze_file(seed_source,seed)
    seed_record=file_record(session.canonical_path(seed),'required_evidence');session.add_input('collision_seed',seed_record)
    control=owned(session.input_dir/'collision_empty.fly2','required_evidence');control.parent.mkdir(parents=True,exist_ok=True)
    control.write_text('particles{coordinates=0,}\n',encoding='utf8');control_record=file_record(session.canonical_path(control),'required_evidence');session.add_input('collision_empty',control_record)
    iob=owned(owned_root/'simion/collision/collision.iob','solver_native_binary')
    owned(iob.with_suffix('.fly2'),'required_evidence')
    for index in range(1,6):owned(seed.parent/f'iob_seed_placeholder_{index:02d}.pa0','solver_native_binary')
    selected_spec=project_ip_mr_collision_iob(compiled,instances=instances,roles=roles,background_bounds_mm=background_bounds,
        **dict(priority_evidence),asset_records=collision_records,seed_record=seed_record,empty_control_record=control_record,output_iob=iob)
    policy_path=owned(session.input_dir/'collision_priority.json','required_evidence')
    policy_path.write_text(json.dumps(selected_spec['policy'],allow_nan=False,indent=2)+'\n',encoding='utf8')
    policy_record=file_record(session.canonical_path(policy_path),'required_evidence');session.add_input('collision_priority',policy_record)
    spec=owned(session.input_dir/'collision_iob.lua','required_evidence')
    spec.write_text('return '+lua_value(selected_spec['spec'])+'\n',encoding='utf8')
    spec_record=file_record(session.canonical_path(spec),'required_evidence');session.add_input('collision_iob_spec',spec_record)
    guards=[spec_record,policy_record,*selected_spec['immutable_records'],resource_records['iob_core.lua'],resource_records['build_geometry_iob.lua'],resource_records['native_run_path.lua']]
    wrapper=project(resource_records['build_geometry_iob.lua']['path']);spec_path=project(spec);path_resource=project(resource_records['native_run_path.lua']['path'])
    run('collision_iob_build',['lua',wrapper,spec_path,'build_geometry',path_resource],'IP_MR_COLLISION_IOB=PASS',guards)
    iob_record=file_record(session.canonical_path(iob),'solver_native_binary')
    run('collision_iob_verify',['lua',wrapper,spec_path,'verify_geometry',path_resource],'IP_MR_COLLISION_IOB_REOPEN=PASS',[*guards,iob_record])

    for record in plan['immutable_input_records']:
        verify_record('sampled field source before publication',dict(record))
    basis=owned(session.input_dir/'sampled_basis.json','required_evidence');basis.write_text(json.dumps(plan['binding'],allow_nan=False,indent=2)+'\n',encoding='utf8')
    basis_record=file_record(session.canonical_path(basis),'required_evidence');session.add_input('sampled_basis',basis_record)
    audit_path=owned(session.result_dir/'collision_audits.json','required_evidence');audit_path.parent.mkdir(parents=True,exist_ok=True)
    audit_path.write_text(json.dumps(audits,allow_nan=False,indent=2)+'\n',encoding='utf8')
    records={key:plan['prepared_records'][key] for key in ('compiled_model','clock_authority','instrument_epoch')}
    zero_control=file_record(session.canonical_path(iob.with_suffix('.fly2')),'required_evidence')
    records.update(sampled_basis=basis_record,collision_priority=policy_record,collision_iob_spec=spec_record,
                   zero_particle_format_control=zero_control,
                   collision_audits=file_record(session.canonical_path(audit_path),'required_evidence'),
                   background=bg,workbench=iob_record)
    for name,asset in collision_records.items():
        if name!=background_id:
            records[name+'_collision']=asset['pa'];records[name+'_witness']=asset['surface_witnesses']
            if 'fractional_surface' in asset: records[name+'_surface']=asset['fractional_surface']
            if 'surface_state' in asset: records[name+'_surface_state']=asset['surface_state']
    document=require_prepared_model(plan['model'])
    metadata=dict(backend='simion',field_status='available',source_status='not_requested',
        model_identity_sha256=document['model_identity_sha256'],clock=copy.deepcopy(document['drive']['clock']),
        field_representation='assembly_sampled_basis_with_collision_geometry',
        refine_calls=0,compute_calls=0,fly_calls=0,scientific_qualification='not_granted',
        scalar_coverage='not_qualified',native_collision_qualification='not_granted')
    outputs=[str(session.canonical_path(path)) for path in [background,iob,iob.with_suffix('.fly2'),audit_path,
        *(Path(row['output_path']) for row in tasks),*(Path(row['output_path']).with_suffix('.pa-surf') for row in tasks if Path(row['output_path']).with_suffix('.pa-surf').is_file())]]
    return dict(status='success',summary=metadata,output_paths=outputs,required_output_paths=outputs,
        retention_preserve_paths=[],manifest_extra_fields={'products':{'fields':dict(schema_version=1,
        kind='field_bundle',status='complete',metadata=metadata,data=records)}})


def prepare_reused_ip_mr_collisions(model_reference, *, scalar_field_basis, priority_evidence, reuse_reference, output_directory):
    """Admit a fresh basis while borrowing one verified collision producer."""
    from msplatform.results.artifacts import open_artifact
    from .model import require_prepared_model
    normalized_evidence={name:dict(record,retention_role='required_evidence')
                         for name,record in priority_evidence.items()}
    plan = prepare_ip_mr_field_inputs(model_reference, scalar_field_basis=scalar_field_basis,
                                      priority_evidence=normalized_evidence, output_directory=output_directory)
    previous = open_artifact(reuse_reference, expected_kind='field_bundle')
    previous_reference = previous.reference
    previous_reference['manifest']['path'] = str(previous.manifest_location)
    producer_reference = previous.metadata.get('collision_producer_reference', previous_reference)
    producer = previous if producer_reference == previous_reference else open_artifact(producer_reference, expected_kind='field_bundle')
    producer_reference = producer.reference
    producer_reference['manifest']['path'] = str(producer.manifest_location)
    expected_representation = 'assembly_sampled_basis_with_collision_geometry'
    for source in (previous, producer):
        if (source.producer['status'] != 'success' or source.metadata.get('backend') != 'simion'
                or source.metadata.get('field_representation') != expected_representation
                or source.metadata.get('field_status') != 'available'
                or source.metadata.get('source_status') != 'not_requested'):
            raise ValueError('collision reuse requires successful sampled field producers')
        manifest=_read(source.manifest_location)
        producer_request=manifest['inputs']['execution_request']
        verify_record('collision producer request',producer_request,base_dir=source.manifest_location.parent)
        request_path=record_path(producer_request,base_dir=source.manifest_location.parent)
        request=_read(request_path)
        if request.get('role')!='run_artifact_workflow_request' or request['payload'].get('action')!='solve_fields':
            raise ValueError('collision producer workflow request differs')
    if producer.metadata.get('collision_producer_reference') is not None:
        raise ValueError('collision producer must be the original native producer')
    document = require_prepared_model(plan['model'])
    for source in (previous, producer):
        if (source.metadata.get('model_identity_sha256') != document['model_identity_sha256']
                or source.metadata.get('clock') != document['drive']['clock']):
            raise ValueError('collision reuse prepared model or clock differs')
        for key in ('compiled_model','clock_authority','instrument_epoch'):
            selected=plan['prepared_records'][key]; existing=source.data_records[key]
            if any(str(selected[k]).lower()!=str(existing[k]).lower() for k in ('bytes','sha256')):
                raise ValueError('collision reuse prepared record differs: '+key)
        policy=_read(source.data_locations['collision_priority'])
        if plan['priority_projection']['verified_priority'] != policy:
            raise ValueError('collision reuse priority or background grid differs')
    excluded = {'compiled_model', 'clock_authority', 'instrument_epoch', 'sampled_basis'}
    keys = set(producer.data_records) - excluded
    required={'collision_priority','collision_iob_spec','zero_particle_format_control','collision_audits','background','workbench'}
    roles=plan['priority_projection']['roles']
    for name in (roles['rf'],roles['ip'],roles['analyzer'],roles['detector']):
        required.update((name+'_collision',name+'_witness'))
        if name+'_surface' not in keys and name+'_surface_state' not in keys:
            raise ValueError('collision reuse requires surface evidence: '+name)
    if not required <= keys:
        raise ValueError('collision reuse required records are missing')
    if keys != set(previous.data_records) - excluded:
        raise ValueError('collision reuse record closure differs')
    for key in keys:
        previous_record = dict(previous.data_records[key], path=str(previous.data_locations[key]))
        producer_record = dict(producer.data_records[key], path=str(producer.data_locations[key]))
        if previous_record != producer_record:
            raise ValueError('collision reuse producer record differs: ' + key)
    plan['collision_producer_reference'] = producer_reference
    plan['collision_source_records'] = {key: dict(producer.data_records[key],
        path=str(producer.data_locations[key])) for key in keys}
    plan['collision_metadata'] = producer.metadata
    plan['source_references'].extend([{'manifest_record':previous_reference['manifest']},
                                      {'manifest_record':producer_reference['manifest']}])
    return plan


def execute_reused_ip_mr_collisions(session, *, model_reference, scalar_field_basis, priority_evidence, reuse_reference):
    """Publish an independently admitted basis using protected original collisions."""
    from .model_execution import _protected_source
    from msplatform.io.manifest_records import file_record
    plan=prepare_reused_ip_mr_collisions(model_reference,scalar_field_basis=scalar_field_basis,
        priority_evidence=priority_evidence,reuse_reference=reuse_reference,
        output_directory=session.artifact_run_dir/'simion/collision')
    if session.expected_operation_ids != ():
        raise ValueError('collision reuse requires no native operations')
    for ref in plan['source_references']:
        _protected_source(session,ref['manifest_record'])
    _protected_source(session,plan['prepared_source']['manifest'],required_paths=[record['path'] for record in plan['immutable_input_records']])
    _protected_source(session,plan['collision_producer_reference']['manifest'],required_paths=[record['path'] for record in plan['collision_source_records'].values()])
    records={key:plan['prepared_records'][key] for key in ('compiled_model','clock_authority','instrument_epoch')}
    records.update(plan['collision_source_records'])
    for key,record in records.items():
        verify_record('collision reuse '+key,record);session.add_input('reuse_'+key,record)
    for i,record in enumerate(plan['immutable_input_records']):
        verify_record('new basis input',record);session.add_input('basis_source_'+str(i),record)
    basis=session.declare_file(session.input_dir/'sampled_basis.json','required_evidence')
    basis.write_text(json.dumps(plan['binding'],allow_nan=False,indent=2)+'\n',encoding='utf8')
    records['sampled_basis']=file_record(session.canonical_path(basis),'required_evidence')
    session.add_input('sampled_basis',records['sampled_basis'])
    metadata=copy.deepcopy(plan['collision_metadata'])
    metadata['collision_producer_reference']=plan['collision_producer_reference']
    metadata.update(refine_calls=0,compute_calls=0,fly_calls=0,scalar_coverage='not_qualified')
    return dict(status='success',summary=metadata,output_paths=[str(session.canonical_path(basis))],
        required_output_paths=[str(session.canonical_path(basis))],retention_preserve_paths=[],
        manifest_extra_fields={'products':{'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=records)}})
