"""Store-managed paired OA static field comparison on one common point set."""
from __future__ import annotations

from contextlib import ExitStack
from functools import partial
import json
from pathlib import Path

from msplatform.analysis.paired_static_samples import validate_samples
from msplatform.backends.comsol.native_execution import declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion
from msplatform.backends.comsol.paired_static_field import prepare
from msplatform.backends.comsol.paired_static_model import paired_comsol_inputs
from msplatform.backends.comsol.paired_static_model_source import guard_paired_failed_prepared_model, guard_paired_saved_model, guard_paired_saved_samples
from msplatform.backends.simion.paired_static_store import run_paired_static_simion
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.inputs import freeze_file
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import current_managed_native_store, recover_managed_native_store_stage, run_managed_stage
from msplatform.execution.native_artifact_controls import current_native_artifact_scope, protect_native_controls
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, record_path, require_completed_terminal_publication, verify_record

_MATLAB = ('comsolstartup.m','build_and_export_paired_accelerator_field.m','oatof_build_accelerator_geometry.m',
           'build_sectioned_geometry.m','build_accelerator_grids.m','add_comsol_size_feature.m',
           'read_comsol_mesh_size_controls.m')
_SIMION = {'builder':'build_dirichlet_patch_operating_pa.lua','exporter':'export_detached_standalone_pa.lua',
           'sampler':'export_paired_accelerator_field.lua'}


def _freeze(session, source, name):
    target = session.declare_file(session.input_dir/name, 'required_evidence')
    target.parent.mkdir(parents=True, exist_ok=True)
    frozen = freeze_file(Path(source['path']), target, retention_role='required_evidence')
    frozen.pop('source_path',None)
    if any(frozen[key] != source[key] for key in ('bytes','sha256')):
        raise ValueError('paired frozen source differs: '+name)
    session.add_input(name.replace('/','_').replace('.','_'), frozen)
    return target, frozen


def _action(session, *, request_record, source_records, source_base, limits, saved_model=None, saved_samples=None):
    request_path,_ = _freeze(session,request_record,'request.json')
    for name, record in source_records.items():
        _freeze(session,record,'sources/'+name+'.json')
    output = session.input_dir/'bvp'; output.mkdir(parents=True,exist_ok=True)
    for name in ('paired_accelerator.gem','paired_accelerator_geometry.json',
                 'paired_accelerator_field_points.csv','paired_accelerator_static_field_plan.json'):
        session.declare_file(output/name,'required_evidence')
    plan = prepare(request_path,output,source_snapshot_root=session.input_dir/'sources',source_base_dir=source_base)
    if saved_model is not None:
        previous=json.loads(Path(saved_model['plan']['path']).read_text(encoding='utf8'))
        if paired_comsol_inputs(previous)!=paired_comsol_inputs(plan):
            raise ValueError('saved COMSOL field common BVP differs')
        if saved_model['asset_id'] is not None:
            current_managed_native_store()['required_source_assets'].add(saved_model['asset_id'])
    if saved_samples is not None:
        previous=json.loads(Path(saved_samples['plan']['path']).read_text(encoding='utf8'))
        if paired_comsol_inputs(previous)!=paired_comsol_inputs(plan):
            raise ValueError('saved COMSOL samples common BVP differs')
        validate_samples(plan,Path(saved_samples['samples']['path']))
        if saved_samples['asset_id'] is not None:
            current_managed_native_store()['required_source_assets'].add(saved_samples['asset_id'])
    plan_path = output/'paired_accelerator_static_field_plan.json'
    plan_record = file_record(plan_path,'required_evidence')
    gem_record = file_record(output/'paired_accelerator.gem','required_evidence')
    points_record = file_record(output/'paired_accelerator_field_points.csv','required_evidence')
    for name,record in (('paired_plan',plan_record),('paired_gem',gem_record),('paired_points',points_record),
                        ('paired_geometry',file_record(output/'paired_accelerator_geometry.json','required_evidence'))):
        session.add_input(name,record)
    simion_resources = {}
    for role,name in _SIMION.items():
        source = file_record(native_resource_path(name),'required_evidence')
        target,_ = _freeze(session,source,'simion_resources/'+name)
        simion_resources[role] = target
    simion = run_paired_static_simion(session,operation_id='paired_simion',plan_record=plan_record,
        gem_record=gem_record,points_record=points_record,resources=simion_resources,limits=limits)
    if saved_samples is None:
        launcher, matlab_sources = freeze_native_sources(session,_MATLAB)
        comsol_dir = session.run_dir/'comsol'; comsol_dir.mkdir(parents=True,exist_ok=True)
        prepared = saved_model is not None and saved_model['source_stage']=='prepared_saved'
        model = (session.declare_file(comsol_dir/'paired_accelerator_static.mph','solver_native_binary')
                 if saved_model is None or prepared else Path(saved_model['model']['path']))
        samples = session.declare_file(comsol_dir/'comsol_field_samples.csv','required_evidence')
        native_facts = session.declare_file(comsol_dir/'comsol_field_native_facts.json','required_evidence')
        solution = (session.declare_file(comsol_dir/'comsol_field_solution.json','required_evidence')
                    if saved_model is None or prepared else Path(saved_model['solution']['path']))
        task = session.declare_file(session.input_dir/'paired_comsol_task.m','required_evidence')
        task.write_text('addpath('+matlab_text(launcher.parent.parent/'matlab')+');\n'
            'build_and_export_paired_accelerator_field('+matlab_text(plan_path)+','+matlab_text(comsol_dir)+','+
            matlab_text('' if saved_model is None else saved_model['model']['path'])+
            (",'prepared_saved'" if prepared else '')+');\n',
            encoding='utf8',newline='\n')
        task_record = file_record(task,'required_evidence'); session.add_input('paired_comsol_task',task_record)
        bootstrap = session.declare_file(session.log_dir/'paired_comsol.bootstrap.log','required_evidence')
        completion = session.declare_file(session.log_dir/'paired_comsol.launcher.json','required_evidence')
        runtime = session.run_dir/'comsol_runtime'/'paired'; runtime.mkdir(parents=True,exist_ok=True)
        host = json.dumps({name:str(getattr(session.context,name)) for name in ('workspace','python_executable','host_state_path','policy_path')})
        arguments = ['-NoProfile','-File',str(launcher),'-HostContextJson',host,'-WorkingDirectory',str(session.run_dir),
            '-ComsolLauncherPath',str(session.context.tools['comsol_launcher']),'-MatlabRootPath',str(session.context.tools['matlab_root']),
            '-TaskScript',str(task),'-ReportPath',str(bootstrap),'-StartupAttempts','1','-RunId',session.run_id,
            '-RunDir',str(runtime),'-CompletionPath',str(completion)]
        try:
            with ExitStack() as controls:
                immutable=[*matlab_sources,plan_record,points_record,task_record]
                if saved_model is not None:
                    immutable.extend(saved_model[name] for name in ('manifest','plan','solution','model'))
                    immutable.extend(saved_model.get('source_chain',()))
                    if saved_model['claim_token'] is not None:
                        scope=current_native_artifact_scope()
                        controls.enter_context(protect_native_controls(scope['store'],run_id=scope['run_id'],
                            claim_ids=(*scope['claim_ids'],saved_model['claim_token']),
                            reservation_ids=scope['reservation_ids'],work_directory=scope['work_directory']))
                session.run_process('paired_comsol',executable=session.context.powershell_executable,arguments=arguments,
                    role='COMSOL',stage='solver',limits=limits,immutable_input_records=immutable)
        except BaseException as failure:
            # Preserve actual files as failure evidence only; a later consumer
            # must prove writer exit, source identity and native facts.
            if saved_model is None or prepared:
                present=[path for path in (model,solution) if path.is_file()]
                failure.failure_output_paths=[*getattr(failure,'failure_output_paths',()),*present]
            raise
        finally:
            declare_runtime_files(session,runtime,bootstrap=bootstrap)
        require_launcher_completion(completion,session.run_id)
        if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
            raise ValueError('paired COMSOL bootstrap did not pass')
        data=json.loads(native_facts.read_text(encoding='utf-8-sig'))
        solved=json.loads(solution.read_text(encoding='utf-8-sig'))
        if (data.get('backend')!='COMSOL' or data.get('coordinate_unit')!='mm' or data.get('field_unit') != ['V/m']*3
                or data.get('point_count') != plan['sample_points']['count']
                or Path(data.get('plan_path','')).resolve()!=plan_path.resolve()
                or Path(data.get('model_path','')).resolve()!=model.resolve()
                or Path(data.get('sample_path','')).resolve()!=samples.resolve()
                or solved.get('role')!='oatof_paired_accelerator_static_field_solution'
                or solved.get('schema_version') != 1 or solved.get('solution_tag') != 'sol1'
                or ((saved_model is None or prepared) and solved.get('study_tag') != 'std1')
                or ((saved_model is None or prepared) and Path(solved.get('plan_path','')).resolve()!=plan_path.resolve())
                or ((saved_model is None or prepared) and Path(solved.get('model_path','')).resolve()!=model.resolve())
                or solved.get('status')!='solved_saved' or solved.get('solution_present') is not True
                or ((saved_model is None or prepared) and (solved.get('mesh_complete') is not True
                    or type(solved.get('tetrahedra')) is not int or solved['tetrahedra'] <= 0))):
            raise ValueError('paired COMSOL native facts differ')
    else:
        comsol_dir=session.run_dir/'comsol';comsol_dir.mkdir(parents=True,exist_ok=True)
        samples=session.declare_file(comsol_dir/'comsol_field_samples.csv','required_evidence')
        native_facts=session.declare_file(comsol_dir/'comsol_field_native_facts.json','required_evidence')
        for source,target in ((saved_samples['samples'],samples),(saved_samples['facts'],native_facts)):
            frozen=freeze_file(Path(source['path']),target,retention_role='required_evidence')
            if any(frozen[key]!=source[key] for key in ('bytes','sha256')):
                raise ValueError('paired saved sample changed while freezing')
    validate_samples(plan,samples)
    comparison = session.result_dir/'comparison'
    products = [session.declare_file(comparison/name,'required_evidence') for name in (
        'accelerator_vector_field_comparison.csv','accelerator_vector_field_metrics.json',
        'accelerator_vector_field_comparison.png')]
    session.run_process('paired_analysis',executable=session.context.python_executable,
        arguments=['-I','-B','-m','msplatform.analysis.vector_field_samples',str(samples),
                   str(simion['sample_record']['path']),'--output',str(comparison)],
        role='GATE',stage='postprocess',limits=limits,
        immutable_input_records=[file_record(samples,'required_evidence'),simion['sample_record']])
    outputs=[samples,native_facts,*products,Path(simion['sample_record']['path']),Path(simion['facts_record']['path'])]
    if saved_samples is None and (saved_model is None or saved_model['source_stage']=='prepared_saved'):
        outputs.extend((model,solution))
    return dict(status='success',summary=dict(role='paired_oa_static_comparison',
        qualification='descriptive_only_no_equivalence_tolerance',simion_cache=simion['cache_disposition'],
        simion_native_count=simion['native_count'],comsol_native_count=0 if saved_samples else 1,
        comsol_source=('completed_samples' if saved_samples else 'fresh_solve' if saved_model is None else saved_model['source_stage'])),output_paths=outputs,
        required_output_paths=outputs,retention_preserve_paths=[],manifest_extra_fields={})


def run_paired_static_comparison(context, *, artifact_store, request_path: Path, run_id: str,
                                 committed_new_bytes: int, saved_model_manifest: Path | None = None,
                                 saved_samples_manifest: Path | None = None,
                                 prepared_model_manifest: Path | None = None) -> dict:
    """Run the actual paired static diagnostic on a sealed common BVP request.

    An explicit successful saved model is sampled in place without a new solve.
    This does not grant numerical equivalence or accept old stopped producer
    checkpoints. Source and consumed records remain OS guarded.
    """
    if sum(value is not None for value in (saved_model_manifest,saved_samples_manifest,prepared_model_manifest))>1:
        raise ValueError('choose exactly one model or completed sample source')
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError('paired static requires a positive Store budget')
    request_path=Path(request_path).resolve(strict=True)
    request_record=file_record(request_path,'required_evidence')
    stage,policy=read_stage_policy(context,'paired_accelerator_static_field')
    with ExitStack() as guards:
        guards.enter_context(guarded_file_identity(request_path,expected_bytes=request_record['bytes'],expected_sha256=request_record['sha256']))
        request=json.loads(request_path.read_text(encoding='utf-8-sig'))
        verify_record('paired static request',request_record)
        if set(request.get('source_records',{}))!={'parent_manifest','frontend_geometry','oatof_resolved'}:
            raise ValueError('paired static request source records differ')
        sources={}
        for name,value in request['source_records'].items():
            path=record_path(value,base_dir=request_path.parent).resolve(strict=True)
            record=dict(value,path=str(path),exists=True,retention_role='required_evidence')
            verify_record('paired static '+name,record)
            guards.enter_context(guarded_file_identity(path,expected_bytes=record['bytes'],expected_sha256=record['sha256']))
            sources[name]=record
        parent_path=Path(sources['parent_manifest']['path'])
        require_completed_terminal_publication(parent_path)
        parent=json.loads(parent_path.read_text(encoding='utf-8-sig'))
        if parent.get('role')!='simulation_run_manifest' or parent.get('status')!='success':
            raise ValueError('paired static parent must be successfully published')
        saved_model=(guards.enter_context(guard_paired_saved_model(artifact_store,saved_model_manifest))
                     if saved_model_manifest is not None else None)
        if prepared_model_manifest is not None:
            saved_model=guards.enter_context(guard_paired_failed_prepared_model(artifact_store,prepared_model_manifest))
        saved_samples=(guards.enter_context(guard_paired_saved_samples(artifact_store,saved_samples_manifest))
                       if saved_samples_manifest is not None else None)
        return run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='paired_accelerator_static_field',
                software=['SIMION 2020','COMSOL 6.4','MATLAB R2025b']),run_id=run_id,
            payload=dict(qualification='descriptive_only_no_equivalence_tolerance'),committed_new_bytes=committed_new_bytes,
            commitment_inputs=[request_record,*sources.values(),policy,*([saved_model['manifest'],saved_model['plan'],
                saved_model['solution'],saved_model['model'],*saved_model.get('source_chain',[])] if saved_model is not None else []),
                *([saved_samples['manifest'],saved_samples['plan'],saved_samples['samples'],saved_samples['facts']]
                  if saved_samples is not None else [])],retention=stage['artifact_retention'],
            expected_operation_ids=(['paired_simion','paired_analysis'] if saved_samples else ['paired_simion','paired_comsol','paired_analysis']),
            operation_dependencies={'paired_analysis':(['paired_simion'] if saved_samples else ['paired_simion','paired_comsol'])},
            action=partial(_action,request_record=request_record,source_records=sources,source_base=request_path.parent,
                limits=stage['limits'],saved_model=saved_model,saved_samples=saved_samples),
            action_record=file_record(Path(__file__).resolve(),'required_evidence'),artifact_store=artifact_store,
            completion_api=no_particle_batch_completion_api,
            use_short_execution_path=True)


def recover_paired_static_publication(context, *, artifact_store, stage_asset_id: str,
                                      store_run_id: str) -> dict:
    """Recover two explicitly identified terminal publications, never rerun a solver.

    Both existing Store primitives independently require writer-stop and complete
    publication evidence. A failed stage remains failed and is never promoted.
    """
    stage=artifact_store.asset_status(stage_asset_id)
    runs=Path(stage['path'])/'runs'
    candidates=list(runs.iterdir()) if runs.is_dir() else []
    if len(candidates)!=1 or not candidates[0].is_dir():
        raise ValueError('paired stage recovery requires one terminal run')
    manifest=json.loads((candidates[0]/'run_manifest.json').read_text(encoding='utf8'))
    if (manifest.get('role')!='simulation_run_manifest' or manifest.get('project')!='instrument_assembly'
            or manifest.get('mode')!='paired_accelerator_static_field' or manifest.get('run_id')!=candidates[0].name):
        raise ValueError('recovery stage is not a paired static field run')
    stage_recovered=recover_managed_native_store_stage(artifact_store,stage_asset_id,context=context)
    run_recovered=artifact_store.recover_run_publication(store_run_id)
    return dict(stage_recovered=stage_recovered,run_recovered=run_recovered,
                stage=artifact_store.asset_status(stage_asset_id),run=artifact_store.run_status(store_run_id))
