"""Prepare a full-Assembly COMSOL electrostatic model without Compute."""
from __future__ import annotations
import json
import math
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4
from msplatform.backends.comsol.native_execution import declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import open_artifact

_NATIVE_SOURCES=('comsolstartup.m','assembly_electrostatic_model.m','verify_assembly_electrostatic_bindings.m','validate_assembly_reference_selections.m','classify_assembly_reference_faces.m','add_comsol_size_feature.m','read_comsol_mesh_size_controls.m')


def _finite(value, label, *, positive=False):
    if type(value) not in (int,float) or not math.isfinite(value) or (positive and value<=0):
        raise ValueError(label+' must be '+('positive and ' if positive else '')+'finite')
    return float(value)


def validate_request(projection: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate explicit selected scientific groups and numerical authorities."""
    if not isinstance(request,Mapping) or set(request)!={'group_voltages','relative_permittivity','exterior','mesh','study'}:
        raise ValueError('explicit group_voltages, relative_permittivity, exterior, mesh and study required')
    groups=projection['electrode_groups']; expected=[(g['instance_id'],g['electrode_group_id']) for g in groups]
    if not expected or len(set(expected))!=len(expected):raise ValueError('geometry group identity differs')
    rows=request['group_voltages']
    if not isinstance(rows,(list,tuple)) or len(rows)!=len(expected):raise ValueError('group voltage coverage differs')
    values={}
    for row in rows:
        if not isinstance(row,Mapping) or set(row)!={'instance_id','electrode_group_id','voltage_v'}:raise ValueError('invalid group voltage row')
        key=(row['instance_id'],row['electrode_group_id'])
        if key in values:raise ValueError('duplicate group voltage')
        values[key]=_finite(row['voltage_v'],'group voltage')
    if set(values)!=set(expected):raise ValueError('group voltage identity differs')
    exterior=request['exterior']
    if not isinstance(exterior,Mapping) or set(exterior)!={'kind','voltage_v'} or exterior['kind']!='potential':raise ValueError('explicit exterior potential required')
    if request['study'] != {'kind': 'stationary'}:raise ValueError('explicit stationary study required')
    mesh=request['mesh']
    if not isinstance(mesh,Mapping) or set(mesh)!={'global_automatic_level','electrode_hmax_mm'}:raise ValueError('explicit mesh controls required')
    level=mesh['global_automatic_level']
    if type(level) is not int or not 1<=level<=9:raise ValueError('invalid mesh automatic level')
    return dict(group_voltages=[dict(instance_id=a,electrode_group_id=b,voltage_v=values[(a,b)]) for a,b in expected],
        relative_permittivity=_finite(request['relative_permittivity'],'relative permittivity',positive=True),
        exterior=dict(kind='potential',voltage_v=_finite(exterior['voltage_v'],'exterior voltage')),
        mesh=dict(global_automatic_level=level,electrode_hmax_mm=_finite(mesh['electrode_hmax_mm'],'electrode hmax',positive=True)), study=dict(kind='stationary'))


def prepare_model(geometry: Any, *, request: Mapping[str, Any], context: Any) -> Any:
    """Publish an independently reopenable unsolved model from a verified geometry.

    The geometry source is protected by the existing source-capacity reference and,
    during the only operation that reads its MPH, the process immutable-file guard.
    All scientific and numerical choices must be supplied explicitly by the caller.
    """
    source=open_artifact(geometry,expected_kind='geometry_artifact')
    if source.metadata.get('backend')!='comsol' or source.metadata.get('scope')!='geometry_only' or source.metadata.get('native_reopen_verified') is not True:raise ContractError('verified COMSOL geometry-only source required')
    paths={name:source.data_path(name) for name in ('projection','geometry_validation','descriptor','build_geometry','reopen_geometry')}
    projection=json.loads(paths['projection'].read_text(encoding='utf-8-sig')); resolved=validate_request(projection,request)
    for name in ('comsol_launcher','matlab_root'):
        path=context.tools.get(name)
        if path is None or not (path.is_dir() if name=='matlab_root' else path.is_file()):raise ContractError('COMSOL model requires explicit available tool: '+name)
    stage,authority=read_stage_policy(context,'prepare_assembly_electrostatic_model',required_roles=('solver_native_binary',))
    if stage.get('runtime'):raise ContractError('COMSOL model has no runtime overrides')
    result=run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='prepared_model',software=['COMSOL','MATLAB']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'__build__comsol__assembly-model-'+uuid4().hex[:12],
        payload=dict(action='prepare_assembly_electrostatic_model',request=resolved,stage_policy=stage),
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'],commitment_inputs=[authority],retention=stage['artifact_retention'],
        source_references=[{'manifest_record':source.reference['manifest']}],expected_operation_ids=('build_model','reopen_model'),
        operation_dependencies={'reopen_model':['build_model']},action=partial(execute_model,source=source,projection=projection,request=resolved,limits=stage['limits']),
        action_record=file_record(Path(__file__).resolve(),'required_evidence'),use_short_execution_path=True,completion_api=no_particle_batch_completion_api)
    return open_artifact({'manifest':result['manifest'],'product_id':'model'},expected_kind='prepared_model')


def _check_report(row, mode, projection, request, model):
    keys=[g['instance_id']+'/'+g['electrode_group_id'] for g in projection['electrode_groups']]
    voltage_values=row.get('group_voltages_v')
    if len(keys)==1 and type(voltage_values) in (int,float):voltage_values=[voltage_values]
    if (row.get('operation')!=mode or row.get('scope')!='assembly_electrostatic_unsolved' or
        row.get('group_keys')!=keys or voltage_values!=[r['voltage_v'] for r in request['group_voltages']] or
        row.get('relative_permittivity')!=request['relative_permittivity'] or row.get('exterior_voltage_v')!=request['exterior']['voltage_v'] or
        row.get('mesh')!=request['mesh'] or row.get('compute_calls')!=0 or row.get('solution_count')!=0 or
        row.get('model_rewritten') is not (mode=='build') or Path(row.get('model_path','')).resolve()!=model.resolve()):
        raise ValueError('COMSOL unsolved model report differs from frozen authority')
    if not row.get('vacuum_domains') or not row.get('outer_faces') or len(row.get('group_faces',[]))!=len(keys) or not all(row['group_faces']):raise ValueError('COMSOL unsolved model selections missing')


def execute_model(session, *, source, projection, request, limits):
    if session.expected_operation_ids!=('build_model','reopen_model'):raise ValueError('unsolved model requires build and cold reopen')
    launcher,sources=freeze_native_sources(session,_NATIVE_SOURCES); frozen={};paths={}
    session.add_input('geometry_manifest',source.reference['manifest'])
    source_model=dict(source.data_records['model'],path=str(source.data_locations['model']))
    session.add_input('geometry_model',source_model);paths['model']=source.data_locations['model']
    for name in ('projection','geometry_validation','descriptor','build_geometry','reopen_geometry'):
        src=source.data_path(name); target=session.declare_file(session.input_dir/'geometry'/src.name,'solver_native_binary' if name=='model' else 'required_evidence');target.parent.mkdir(parents=True,exist_ok=True)
        freeze_file(src,target);record=file_record(target,'solver_native_binary' if name=='model' else 'required_evidence')
        expected=source.data_records[name]
        if any(record[k]!=expected[k] for k in ('bytes','sha256')):raise ValueError('geometry copy identity differs')
        session.add_input('geometry_'+name,record);frozen[name]=record;paths[name]=target
    contract=session.declare_file(session.input_dir/'electrostatic_request.json','required_evidence');write_json_atomic(contract,request);contract_record=file_record(contract,'required_evidence');session.add_input('electrostatic_request',contract_record)
    output=session.declare_file(session.run_dir/'assembly-electrostatic-unsolved.mph','solver_native_binary');matlab=launcher.parent.parent/'matlab'
    host=json.dumps({n:str(getattr(session.context,n)) for n in ('workspace','python_executable','host_state_path','policy_path')});persisted=[];reports={};first=None
    for operation,mode in (('build_model','build'),('reopen_model','reopen')):
        report=session.declare_file(session.result_dir/(operation+'.json'),'required_evidence');bootstrap=session.declare_file(session.log_dir/(operation+'.bootstrap.log'),'required_evidence');completion=session.declare_file(session.log_dir/(operation+'.launcher.json'),'required_evidence');task=session.declare_file(session.input_dir/(operation+'.m'),'required_evidence');runtime=session.run_dir/'comsol_runtime'/operation;runtime.mkdir(parents=True)
        call='assembly_electrostatic_model('+','.join(map(matlab_text,(paths['projection'],paths['descriptor'],paths['geometry_validation'],paths['model'],contract,output,mode)))+')'
        task.write_text('addpath('+matlab_text(matlab)+');\nresult='+call+';\nfid=fopen('+matlab_text(report)+",'w','n','UTF-8');\nassert(fid>=0); cleanup=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n",encoding='utf-8',newline='\n')
        guards=[*sources,*frozen.values(),contract_record,file_record(task,'required_evidence'),*persisted]
        if mode=='build':guards.append(source_model)
        args=['-NoProfile','-File',str(launcher),'-HostContextJson',host,'-WorkingDirectory',str(session.run_dir),'-ComsolLauncherPath',str(session.context.tools['comsol_launcher']),'-MatlabRootPath',str(session.context.tools['matlab_root']),'-TaskScript',str(task),'-ReportPath',str(bootstrap),'-StartupAttempts','1','-RunId',session.run_id,'-RunDir',str(runtime),'-CompletionPath',str(completion)]
        primary=None
        try:session.run_process(operation,executable=session.context.powershell_executable,arguments=args,role='COMSOL',stage='solver',limits=limits,immutable_input_records=guards)
        except BaseException as error:primary=error;raise
        finally:
            try:declare_runtime_files(session,runtime,bootstrap=bootstrap)
            except BaseException as error:
                if primary is None:raise
                primary.add_note('COMSOL diagnostic preservation failed: '+repr(error))
        for record in guards:
            if record is not source_model:verify_record('COMSOL model immutable input',record)
        require_launcher_completion(completion,session.run_id)
        if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):raise ValueError('COMSOL model bootstrap failed')
        row=json.loads(report.read_text(encoding='utf-8-sig'));_check_report(row,mode,projection,request,output)
        baseline=json.loads(paths['reopen_geometry'].read_text(encoding='utf-8-sig'))
        for key in ('group_keys','group_faces','vacuum_domains','outer_faces'):
            if row[key]!=baseline[key]:raise ValueError('COMSOL model differs from source geometry: '+key)
        if mode=='build':first=row;persisted=[file_record(output,'solver_native_binary')]
        else:
            for key in ('group_keys','group_faces','vacuum_domains','outer_faces'):
                if row[key]!=first[key]:raise ValueError('COMSOL model cold readback differs: '+key)
        reports[operation]=report
    records=dict(model=persisted[0],request=contract_record,geometry_manifest=source.reference['manifest'],projection=frozen['projection'],descriptor=frozen['descriptor'],geometry_validation=frozen['geometry_validation'],reopen_geometry=frozen['reopen_geometry'],**{name:file_record(path,'required_evidence') for name,path in reports.items()})
    outputs=[output,*reports.values()]
    return dict(status='success',summary=dict(backend='comsol',scope='assembly_electrostatic_unsolved',field_status='not_solved',source_status='not_requested',scientific_qualification='not_granted',compute_calls_requested=0),output_paths=[str(p) for p in outputs],required_output_paths=[str(p) for p in outputs],retention_preserve_paths=[],manifest_extra_fields=dict(products=dict(model=dict(schema_version=1,kind='prepared_model',status='complete',metadata=dict(backend='comsol',scope='assembly_electrostatic_unsolved',field_status='not_solved',source_status='not_requested',native_reopen_verified=True,compute_calls_requested=0),data=records))))