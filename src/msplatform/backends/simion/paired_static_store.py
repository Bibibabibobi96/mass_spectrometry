"""Store-managed SIMION working field and common-point sample for paired OA BVP."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import shutil
import sys

from msplatform.analysis.paired_static_samples import validate_samples
from msplatform.backends.simion.pa_identity import canonical_pa_family_cache_key
from msplatform.backends.simion.paired_static_identity import paired_static_pa_identity
from msplatform.backends.simion.paired_static_projection import render_simion_sample_task
from msplatform.execution.context import ExecutionContext
from msplatform.execution.native_artifact_controls import current_native_artifact_scope, protect_native_controls
from msplatform.execution.owner import current_managed_native_store
from msplatform.execution.processes import inherited_host_token, run_observed_process
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_paths import project_run_path
from msplatform.io.file_identity import file_sha256, guarded_file_identity
from msplatform.io.manifest_records import file_record, record_path, verify_record


def _run_native(context, *, name, arguments, directory, run_directory, limits, records, marker=None):
    stdout = directory/(name+'.stdout.log')
    receipt = run_observed_process(context, executable=context.tools['simion'], arguments=arguments,
        working_directory=directory, run_directory=run_directory, stdout_path=stdout,
        stderr_path=directory/(name+'.stderr.log'), usage_path=directory/(name+'.usage.json'),
        role='SIMION', stage='pa_refine' if name == 'refine' else 'prepare', run_id=run_directory.name,
        limits=limits, operation_id=name, immutable_input_records=records)
    if receipt['host_release']['inherited'] is not True or receipt['host_release']['token'] != inherited_host_token(context, required=True):
        raise ValueError('paired static child did not inherit the actual host lease')
    if marker is not None and marker not in stdout.read_text(encoding='utf-8-sig'):
        raise ValueError('paired static native marker is absent: '+name)
    write_json_atomic(directory/(name+'.process.json'), receipt)


def _validate_native_facts(path: Path, count: int) -> None:
    headers = dict(line.split('=',1) for line in path.read_text(encoding='utf-8-sig').splitlines() if '=' in line)
    if (headers.get('backend') != 'SIMION' or headers.get('api') != 'pa:field_vc'
            or headers.get('native_field_unit') != 'V/gu' or headers.get('export_field_unit') != 'V/m'
            or headers.get('field_sign') != 'negative_potential_gradient'
            or int(headers.get('point_count',-1)) != count):
        raise ValueError('paired static native sampling facts differ')


def _valid_cache_evidence(directory: Path) -> bool:
    """Revalidate the recorded physical PA and full original sampling proof."""
    try:
        proof = json.loads((directory/'verification.json').read_text(encoding='utf8'))
        required = {'schema_version','role','pa_sha256','points_sha256','samples_sha256',
                    'facts_sha256','task_sha256','sampler_sha256','point_count'}
        if (set(proof) != required or proof['schema_version'] != 1
                or proof['role'] != 'paired_static_pa_sample_verification'
                or type(proof['point_count']) is not int or proof['point_count'] < 1):
            return False
        for field, name in (('pa_sha256','paired_static_on.pa'),('points_sha256','verification_points.csv'),
                            ('samples_sha256','verification_samples.csv'),('facts_sha256','verification_facts.txt'),
                            ('task_sha256','verification_task.lua')):
            if file_sha256(directory/name) != proof[field]: return False
        if not isinstance(proof['sampler_sha256'],str) or len(proof['sampler_sha256']) != 64: return False
        with (directory/'verification_points.csv').open(encoding='utf8', newline='') as stream:
            if sum(1 for _ in csv.DictReader(stream)) != proof['point_count']:
                return False
        validate_samples({'sample_points':{'path':str(directory/'verification_points.csv')}}, directory/'verification_samples.csv')
        _validate_native_facts(directory/'verification_facts.txt', proof['point_count'])
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _worker(context, request):
    p = request['parameters']
    run = Path(p['run_directory']).resolve(strict=True)
    logs = Path(p['log_directory']).resolve()
    scratch = Path(p['execution_directory']).resolve()
    receipt_path = Path(p['receipt_path']).resolve()
    result = Path(p['samples_path']).resolve()
    facts = Path(p['facts_path']).resolve()
    if (not logs.is_relative_to(run/'logs') or not scratch.is_relative_to(logs)
            or not receipt_path.is_relative_to(run/'results') or not result.is_relative_to(run/'results')
            or not facts.is_relative_to(logs)):
        raise ValueError('paired static worker paths escape owning run')
    Path(p['execution_directory']).mkdir(parents=True, exist_ok=True)
    report = dict(schema_version=1, role='paired_static_simion_worker', status='failed', native_count=0)
    primary = None
    try:
        inherited_host_token(context, required=True)
        for record in request['inputs']:
            verify_record('paired static input', record)
        plan = p['plan']; root = Path(p['execution_directory']); resources = {name:Path(value) for name,value in p['resources'].items()}
        gem = Path(p['gem_record']['path']); points = Path(p['points_record']['path'])
        pa = root/'paired_static_on.pa'
        if p['disposition'] == 'miss':
            raw = root/'working.pa#'; working = root/'working.pa0'
            _run_native(context, name='gem2pa', arguments=['--nogui','--noprompt','gem2pa',str(gem),str(raw)],
                directory=root, run_directory=run, limits=p['limits'], records=[p['gem_record']])
            if not raw.is_file() or raw.stat().st_size == 0: raise ValueError('paired static raw PA is missing')
            report['native_count'] += 1
            origin = plan['native_geometry_compilation']['grid']['instance_origin_mm']
            origin_arg = ','.join(format(origin[axis],'.17g') for axis in 'xyz')
            voltages = {int(key):value for key,value in plan['static_on_electrode_voltages_v'].items()}
            voltage_arg = ','.join(format(voltages.get(index,0.),'.17g') for index in range(1,max(voltages)+1))
            _run_native(context, name='refine', arguments=['--nogui','--noprompt','lua',str(resources['builder']),
                    str(raw),str(working),'zero_neumann',origin_arg,origin_arg,voltage_arg],
                directory=root, run_directory=run, limits=p['limits'],
                records=[file_record(resources['builder'],'required_evidence'),file_record(raw,'solver_native_binary')],
                marker='DIRICHLET_PATCH_OPERATING_PA=PASS')
            if not working.is_file(): raise ValueError('paired static working PA is missing')
            report['native_count'] += 1
            _run_native(context, name='detach', arguments=['--nogui','--noprompt','lua',str(resources['exporter']),str(working),str(pa)],
                directory=root, run_directory=run, limits=p['limits'],
                records=[file_record(resources['exporter'],'required_evidence'),file_record(working,'solver_native_binary')],
                marker='DETACHED_STANDALONE_PA_EXPORT=PASS')
            if not pa.is_file(): raise ValueError('paired static detached PA is missing')
            report['native_count'] += 1
        elif p['disposition'] == 'hit':
            verify_record('private paired static PA', p['cached_pa'])
        else:
            raise ValueError('paired static cache disposition differs')
        sample_task = root/'sample.lua'
        sample_task.write_text(render_simion_sample_task(plan, pa=pa, points=points,
            output=Path(p['samples_path']), native_facts=Path(p['facts_path']), exporter=resources['sampler']),
            encoding='utf8', newline='\n')
        _run_native(context, name='sample', arguments=['--nogui','--noprompt','lua',str(sample_task)],
            directory=root, run_directory=run, limits=p['limits'],
            records=[file_record(sample_task,'required_evidence'), file_record(resources['sampler'],'required_evidence'),
                     file_record(pa,'solver_native_binary'), p['points_record']], marker='PAIRED_FIELD_EXPORT=PASS')
        report['native_count'] += 1
        validate_samples(dict(plan, sample_points=dict(plan['sample_points'], path=str(points))), Path(p['samples_path']))
        _validate_native_facts(Path(p['facts_path']), plan['sample_points']['count'])
        report.update(status='success', pa_path=str(pa))
        return report
    except BaseException as failure:
        primary = failure
        report['exception'] = dict(type=type(failure).__name__, message=str(failure))
        raise
    finally:
        try: write_json_atomic(receipt_path, report)
        except BaseException as error:
            if primary is None: raise
            primary.add_note('paired static receipt preservation failed: '+str(error))


def run_paired_static_simion(session, *, operation_id: str, plan_record: dict, gem_record: dict,
                             points_record: dict, resources: dict, limits: dict) -> dict:
    """Run/reuse the original OA PA and sample one exact shared-point inventory."""
    scope, controls = current_managed_native_store(), current_native_artifact_scope()
    if scope is None or controls is None or scope['store'] is not controls['store']:
        raise ValueError('paired static SIMION requires its protected Store parent')
    if operation_id not in session.expected_operation_ids or not operation_id.replace('_','').isalnum():
        raise ValueError('paired static operation must be declared')
    if set(resources) != {'builder','exporter','sampler'}:
        raise ValueError('paired static builder/exporter/sampler are required')
    for name, record in (('plan',plan_record),('gem',gem_record),('points',points_record)):
        verify_record('paired static '+name, record)
    plan = json.loads(Path(plan_record['path']).read_text(encoding='utf-8-sig'))
    if plan.get('role') != 'oatof_paired_accelerator_static_field_plan':
        raise ValueError('paired static plan identity differs')
    bound_gem = plan.get('native_geometry_compilation', {}).get('gem_record')
    if (not isinstance(bound_gem, dict)
            or record_path(bound_gem, base_dir=Path(plan_record['path']).parent) != Path(gem_record['path']).resolve()
            or bound_gem.get('bytes') != gem_record.get('bytes')
            or str(bound_gem.get('sha256', '')).upper() != str(gem_record.get('sha256', '')).upper()):
        raise ValueError('paired static GEM differs from the prepared plan')
    if Path(plan['sample_points']['path']).resolve() != Path(points_record['path']).resolve():
        raise ValueError('paired static points differ from prepared plan')
    resources = {name:Path(value) for name,value in resources.items()}
    simion = file_record(session.context.tools['simion'],'required_evidence')
    science = paired_static_pa_identity(plan, gem_sha256=gem_record['sha256'], simion_bytes=simion['bytes'],
        simion_sha256=simion['sha256'], builder_sha256={
            'build_dirichlet_patch_operating_pa.lua':file_sha256(resources['builder']),
            'export_detached_standalone_pa.lua':file_sha256(resources['exporter'])})
    key = canonical_pa_family_cache_key(science)
    store, lifetime = scope['store'], scope['lifetime']; store_key = 'paired-oa-static-v1:'+key
    candidate = lifetime.enter_context(store.claim_key(store_key)); token = None
    if candidate:
        asset_id, asset_dir = candidate
        token, protected = lifetime.enter_context(store.claim_token(asset_id))
        if protected != asset_dir: raise ValueError('paired static cache claim differs')
        try:
            metadata = json.loads((asset_dir/'identity.json').read_text(encoding='utf8'))
            proof = json.loads((asset_dir/'sample.process.json').read_text(encoding='utf8'))
            hit = (metadata == {'cache_key':key,'identity':science} and (asset_dir/'paired_static_on.pa').is_file()
                   and proof.get('observation',{}).get('exit_code') == 0
                   and 'PAIRED_FIELD_EXPORT=PASS' in (asset_dir/'sample.stdout.log').read_text(encoding='utf8')
                   and _valid_cache_evidence(asset_dir))
        except (OSError, ValueError): hit = False
    else: hit = False
    disposition = 'hit' if hit else 'miss'
    logs = session.log_dir/operation_id; scratch = logs/'native'; scratch.mkdir(parents=True,exist_ok=True)
    cached = None
    if hit:
        cached = file_record(asset_dir/'paired_static_on.pa','solver_native_binary')
        shutil.copyfile(cached['path'], scratch/'paired_static_on.pa')
        cached = dict(cached, path=str(scratch/'paired_static_on.pa'))
        verify_record('private paired static PA', cached)
        session.declare_file(cached['path'],'solver_native_binary')
    def project(record):
        return dict(record,path=project_run_path(record['path'],str(session.artifact_run_dir),str(session.run_dir)))
    native_resources = {name:project_run_path(str(path),str(session.artifact_run_dir),str(session.run_dir)) for name,path in resources.items()}
    samples = session.declare_file(session.result_dir/'simion_field_samples.csv','required_evidence')
    facts = session.declare_file(logs/'simion_field_native_facts.txt','required_evidence')
    receipt = session.declare_file(session.result_dir/(operation_id+'.json'),'required_evidence')
    request_path = session.declare_file(session.input_dir/(operation_id+'.json'),'required_evidence')
    context = {name:str(getattr(session.context,name)) for name in ('workspace','python_executable','powershell_executable','host_state_path','policy_path','execution_root')}
    context['tools']={name:str(path) for name,path in session.context.tools.items()}
    sources = [plan_record,gem_record,points_record,simion,*[file_record(path,'required_evidence') for path in resources.values()]]
    if cached:
        sources.append(file_record(session.canonical_path(cached['path']),'solver_native_binary'))
    parameters = dict(plan=copy.deepcopy(plan), gem_record=project(gem_record), points_record=project(points_record),
        cached_pa=cached, resources=native_resources, disposition=disposition, run_directory=str(session.artifact_run_dir),
        log_directory=str(logs), execution_directory=str(scratch), receipt_path=str(receipt),
        samples_path=project_run_path(str(samples),str(session.artifact_run_dir),str(session.run_dir)),
        facts_path=project_run_path(str(facts),str(session.artifact_run_dir),str(session.run_dir)), limits=limits)
    write_json_atomic(request_path,dict(schema_version=1,context=context,parameters=parameters,inputs=sources))
    request_record=file_record(request_path,'required_evidence');session.add_input(operation_id+'_request',request_record)
    try:
        with protect_native_controls(store,run_id=controls['run_id'],
                claim_ids=(*controls['claim_ids'],*([token] if token else [])),
                reservation_ids=controls['reservation_ids'],work_directory=controls['work_directory']):
            session.run_process(operation_id,executable=session.context.python_executable,
                arguments=['-I','-B','-m',__name__,str(request_path)],role='SIMION',stage='pa_refine',
                limits=limits,immutable_input_records=[request_record,*sources])
        report=json.loads(receipt.read_text(encoding='utf8'))
        if report.get('status')!='success' or report.get('request')!=request_record:
            raise ValueError('paired static worker receipt differs')
        scope['account'](session._store_stage_directory)
        if not hit:
            work=store.new_work()
            try:
                shutil.copyfile(scratch/'paired_static_on.pa',work/'paired_static_on.pa')
                scope['account'](work)
                for name in ('sample.process.json','sample.stdout.log'):
                    shutil.copyfile(scratch/name,work/name)
                    scope['account'](work)
                for origin, name in ((Path(points_record['path']),'verification_points.csv'),
                                     (Path(samples),'verification_samples.csv'),(Path(facts),'verification_facts.txt'),
                                     (scratch/'sample.lua','verification_task.lua')):
                    shutil.copyfile(origin,work/name)
                    scope['account'](work)
                proof = dict(schema_version=1, role='paired_static_pa_sample_verification',
                    pa_sha256=file_sha256(work/'paired_static_on.pa'),
                    points_sha256=file_sha256(work/'verification_points.csv'),
                    samples_sha256=file_sha256(work/'verification_samples.csv'),
                    facts_sha256=file_sha256(work/'verification_facts.txt'),
                    task_sha256=file_sha256(work/'verification_task.lua'),
                    sampler_sha256=file_sha256(resources['sampler']), point_count=plan['sample_points']['count'])
                (work/'verification.json').write_text(json.dumps(proof,sort_keys=True)+'\n',encoding='utf8')
                (work/'identity.json').write_text(json.dumps({'cache_key':key,'identity':science},sort_keys=True)+'\n',encoding='utf8')
                if not _valid_cache_evidence(work):
                    raise ValueError('paired static cache proof does not close')
                scope['account'](work)
                asset_id,asset_dir=lifetime.enter_context(store.put_asset_claimed('paired_oa_static_pa',store_key,work))
            except BaseException:
                if work.exists(): store.discard_work(work)
                raise
        report.update(cache_key=key,cache_disposition=disposition,asset_id=asset_id,
                      sample_record=file_record(samples,'required_evidence'),facts_record=file_record(facts,'required_evidence'))
        write_json_atomic(receipt,report)
        return report
    finally:
        for path in session.canonical_path(logs).rglob('*'):
            if path.is_file():
                session.declare_file(path,'solver_native_binary' if '.pa' in path.name.lower() else 'required_evidence')


def main():
    if len(sys.argv)!=2: raise ValueError('paired static worker requires its frozen request')
    path=Path(sys.argv[1]).resolve(strict=True)
    with guarded_file_identity(path) as bound:
        request=json.loads(path.read_text(encoding='utf8'))
        if set(request)!={'schema_version','context','parameters','inputs'} or request['schema_version']!=1:
            raise ValueError('paired static request differs')
        p=request['parameters'];run=Path(p['run_directory']).resolve(strict=True)
        logs=Path(p['log_directory']).resolve();scratch=Path(p['execution_directory']).resolve()
        receipt=Path(p['receipt_path']).resolve(); samples=Path(p['samples_path']).resolve();facts=Path(p['facts_path']).resolve()
        if (not path.is_relative_to(run/'inputs') or not logs.is_relative_to(run/'logs') or not scratch.is_relative_to(logs)
                or not receipt.is_relative_to(run/'results') or not samples.is_relative_to(run/'results') or not facts.is_relative_to(logs)):
            raise ValueError('paired static request paths escape owning run')
        primary=None
        try: _worker(ExecutionContext(**request['context']),request)
        except BaseException as failure:
            primary=failure
            raise
        finally:
            try:
                result=json.loads(receipt.read_text(encoding='utf8'))
                result['request']=dict(path=str(path),exists=True,bytes=bound.bytes_count,sha256=bound.sha256,retention_role='required_evidence')
                write_json_atomic(receipt,result)
            except BaseException as error:
                if primary is None: raise
                primary.add_note('paired static request binding failed: '+str(error))


if __name__ == '__main__': main()
