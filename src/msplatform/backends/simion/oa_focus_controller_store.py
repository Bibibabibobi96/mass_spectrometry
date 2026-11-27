"""Store-owned focus controller bundle under the existing RunSession owner."""
from __future__ import annotations

import copy
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import shutil
import sys

from msplatform.backends.simion.oa_focus_identity import expected_files, identity
from msplatform.execution.context import ExecutionContext
from msplatform.execution.native_artifact_controls import current_native_artifact_scope, protect_native_controls
from msplatform.execution.owner import current_managed_native_store
from msplatform.execution.processes import inherited_host_token, run_observed_process
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.io.file_identity import canonical_json_sha256, file_sha256, guarded_file_identity
from msplatform.io.manifest_records import file_record, verify_record


def _run_native(context, *, name, arguments, directory, run_directory, limits, records, marker):
    log = directory/(name+'.stdout.log')
    receipt = run_observed_process(context, executable=context.tools['simion'], arguments=arguments,
        working_directory=directory, run_directory=run_directory, stdout_path=log,
        stderr_path=directory/(name+'.stderr.log'), usage_path=directory/(name+'.usage.json'),
        role='SIMION', stage='pa_refine', run_id=run_directory.name, limits=limits,
        operation_id=name, immutable_input_records=records)
    if receipt['host_release']['inherited'] is not True or receipt['host_release']['token'] != inherited_host_token(context, required=True):
        raise ValueError('focus child did not inherit the managed host lease')
    if marker not in log.read_text(encoding='utf-8-sig'):
        raise ValueError('focus native completion marker is absent: '+name)
    write_json_atomic(directory/(name+'.process.json'), receipt)
    return receipt


def _worker(context, request):
    """Execute real builder/exporter/verifier; the parent remains sole owner."""
    p = request['parameters']
    run = Path(p['run_directory']).resolve(strict=True)
    logs = Path(p['log_directory']).resolve()
    receipt_path = Path(p['receipt_path']).resolve()
    scratch = Path(p['execution_directory']).resolve()
    if (not logs.is_relative_to(run/'logs') or not scratch.is_relative_to(logs)
            or not receipt_path.is_relative_to(run/'results')):
        raise ValueError('focus worker paths escape owning run')
    logs.mkdir(parents=True, exist_ok=True)
    report = dict(schema_version=1, role='oa_focus_controller_worker', status='failed', native_count=0)
    primary = None
    try:
        inherited_host_token(context, required=True)
        for record in request['inputs']:
            verify_record('focus controller input', record)
        resources = {name: Path(value) for name, value in p['resources'].items()}
        actual_identity = identity(p['plan'], resources['builder'], context.tools['simion'])
        actual_key = canonical_json_sha256(dict(schema_version=1, science=actual_identity,
            exporter_sha256=file_sha256(resources['exporter']), verifier_sha256=file_sha256(resources['verifier'])))
        if actual_identity != p['identity'] or actual_key != p['cache_key']:
            raise ValueError('focus controller scientific identity differs')
        if p['disposition'] == 'miss':
            root = Path(p['execution_directory'])
            root.mkdir(parents=True, exist_ok=True)
            plan = p['plan']; count = plan['electrode_count']
            gem = root/'focus.gem'; gem.write_text(plan['gem'], encoding='ascii', newline='\n')
            raw = root/'orthogonal_accelerator_focus.pa#'
            builder, exporter, verifier = (Path(p['resources'][key]) for key in ('builder','exporter','verifier'))
            source = [file_record(gem, 'required_evidence'), file_record(builder, 'required_evidence')]
            _run_native(context, name='focus_build', arguments=['--nogui','--noprompt','lua',str(builder),str(gem),str(raw),str(count)],
                directory=root, run_directory=run, limits=p['limits'], records=source, marker='ACCELERATOR_COMPONENT_FOCUS_PA=PASS')
            report['native_count'] += 1
            for index in range(1, count+1):
                native = root/f'orthogonal_accelerator_focus.pa{index}'
                output = root/f'orthogonal_accelerator_focus.response{index}.pa'
                _run_native(context, name=f'focus_export_{index}', arguments=['--nogui','--noprompt','lua',str(exporter),str(native),str(output)],
                    directory=root, run_directory=run, limits=p['limits'],
                    records=[file_record(exporter,'required_evidence'), file_record(native,'solver_native_binary')],
                    marker='STANDALONE_PA_EXPORT=PASS')
                report['native_count'] += 1
            domain = plan['numerical_domain']; grid = [round(float(length)/float(mesh))+1
                for length, mesh in zip(domain['stored_span_mm'], domain['mesh_mm_per_gu'], strict=True)]
            records = [file_record(verifier,'required_evidence'), *[file_record(root/name,'solver_native_binary')
                for name in ['orthogonal_accelerator_focus.pa#', *[f'orthogonal_accelerator_focus.pa{i}' for i in range(count+1)]]]]
            _run_native(context, name='focus_verify', arguments=['--nogui','--noprompt','lua',str(verifier),str(raw),str(count),*map(str,grid)],
                directory=root, run_directory=run, limits=p['limits'], records=records,
                marker='ACCELERATOR_COMPONENT_FOCUS_PA_VERIFY=PASS')
            report['native_count'] += 1
            from msplatform.backends.simion.standalone_pa_response_set import ResponseExport, write_standalone_pa_response_set
            exports = [ResponseExport(i, f'orthogonal_accelerator_focus.pa{i}',
                                      f'orthogonal_accelerator_focus.response{i}.pa') for i in range(1,count+1)]
            write_standalone_pa_response_set(root, exporter, exports,
                root/'orthogonal_accelerator_focus.standalone_responses.json', source_directory=root)
            if any(not (root/name).is_file() for name in expected_files(plan)):
                raise ValueError('focus controller family is incomplete')
        elif p['disposition'] != 'hit':
            raise ValueError('focus cache disposition differs')
        report['status'] = 'success'
        return report
    except BaseException as failure:
        primary = failure
        report['exception'] = dict(type=type(failure).__name__, message=str(failure))
        raise
    finally:
        try:
            write_json_atomic(receipt_path, report)
        except BaseException as failure:
            if primary is None:
                raise
            primary.add_note('focus receipt preservation failed: '+str(failure))


def run_focus_controller(session, *, operation_id: str, plan: dict, resources: dict, limits: dict) -> dict:
    """Build or claim an exact closed-two-zone controller and response bundle."""
    scope, controls = current_managed_native_store(), current_native_artifact_scope()
    if scope is None or controls is None or controls['store'] is not scope['store']:
        raise ValueError('focus controller requires the protected Store parent')
    if operation_id not in session.expected_operation_ids or not operation_id.replace('_','').isalnum():
        raise ValueError('focus operation must be declared')
    if set(resources) != {'builder','exporter','verifier'}:
        raise ValueError('focus builder/exporter/verifier resources are required')
    plan = copy.deepcopy(plan)
    resources = {name:Path(value) for name,value in resources.items()}
    science = identity(plan, resources['builder'], session.context.tools['simion'])
    key = canonical_json_sha256(dict(schema_version=1, science=science,
        exporter_sha256=file_sha256(resources['exporter']), verifier_sha256=file_sha256(resources['verifier'])))
    store, lifetime = scope['store'], scope['lifetime']
    cache_key = 'simion-focus-controller-v1:' + key
    candidate = lifetime.enter_context(store.claim_key(cache_key))
    token = None
    if candidate:
        asset_id, asset_dir = candidate
        token, path = lifetime.enter_context(store.claim_token(asset_id))
        if path != asset_dir:
            raise ValueError('focus cache claim path differs')
        try:
            metadata = json.loads((asset_dir/'focus_identity.json').read_text(encoding='utf8'))
            proof = json.loads((asset_dir/'focus_verify.process.json').read_text(encoding='utf8'))
            marker = (asset_dir/'focus_verify.stdout.log').read_text(encoding='utf8')
            hit = (metadata == {'cache_key':key, 'identity':science}
                   and all((asset_dir/name).is_file() for name in expected_files(plan))
                   and proof.get('observation', {}).get('exit_code') == 0
                   and 'ACCELERATOR_COMPONENT_FOCUS_PA_VERIFY=PASS' in marker)
        except (OSError, ValueError):
            hit = False
    else:
        hit = False
    disposition = 'hit' if hit else 'miss'
    logs = session.log_dir/operation_id
    scratch = logs/'native'
    request_path = session.declare_file(session.input_dir/(operation_id+'.json'), 'required_evidence')
    receipt = session.declare_file(session.result_dir/(operation_id+'.json'), 'required_evidence')
    context = {name:str(getattr(session.context,name)) for name in ('workspace','python_executable','powershell_executable','host_state_path','policy_path','execution_root')}
    context['tools'] = {name:str(path) for name,path in session.context.tools.items()}
    sources = [file_record(path,'required_evidence') for path in resources.values()]
    sources.append(file_record(session.context.tools['simion'],'required_evidence'))
    if hit:
        sources.extend(file_record(asset_dir/name,'solver_native_binary') for name in expected_files(plan))
        sources.extend(file_record(asset_dir/name,'required_evidence') for name in
                       ('focus_identity.json','focus_verify.process.json','focus_verify.stdout.log'))
    from msplatform.execution.run_paths import project_run_path
    native_resources = {name:project_run_path(str(path), str(session.artifact_run_dir), str(session.run_dir))
                        for name,path in resources.items()}
    parameters = dict(plan=plan, resources=native_resources,
        identity=science, cache_key=key, disposition=disposition, run_directory=str(session.artifact_run_dir), log_directory=str(logs),
        execution_directory=str(scratch), receipt_path=str(receipt), limits=limits)
    write_json_atomic(request_path, dict(schema_version=1, context=context, parameters=parameters, inputs=sources))
    request_record = file_record(request_path,'required_evidence')
    session.add_input(operation_id+'_request', request_record)
    try:
        with protect_native_controls(store, run_id=controls['run_id'],
                claim_ids=(*controls['claim_ids'], *([token] if token else [])),
                reservation_ids=controls['reservation_ids'], work_directory=controls['work_directory']):
            session.run_process(operation_id, executable=session.context.python_executable,
                arguments=['-I','-B','-m',__name__,str(request_path)], role='SIMION', stage='pa_refine',
                limits=limits, immutable_input_records=[request_record,*sources])
        report = json.loads(receipt.read_text(encoding='utf8'))
        if report.get('request') != request_record or report.get('status') != 'success':
            raise ValueError('focus worker receipt differs')
        scope['account'](session._store_stage_directory)
        if not hit:
            work = store.new_work()
            try:
                for name in expected_files(plan):
                    shutil.copyfile(scratch/name, work/name)
                    scope['account'](work)
                for name in ('focus_verify.process.json','focus_verify.stdout.log'):
                    shutil.copyfile(scratch/name, work/name)
                (work/'focus_identity.json').write_text(json.dumps({'cache_key':key, 'identity':science},sort_keys=True)+'\n', encoding='utf8')
                scope['account'](work)
                asset_id, asset_dir = lifetime.enter_context(store.put_asset_claimed('simion_focus_controller', cache_key, work))
            except BaseException:
                if work.exists(): store.discard_work(work)
                raise
        scope['produced'].append(asset_id)
        report.update(cache_key=key, cache_disposition=disposition, asset_id=asset_id, asset_directory=str(asset_dir))
        write_json_atomic(receipt, report)
        return report
    finally:
        for path in session.canonical_path(logs).rglob('*'):
            if path.is_file():
                session.declare_file(path, 'solver_native_binary' if '.pa' in path.name.lower() and path.suffix.lower() != '.json' else 'required_evidence')


@contextmanager
def materialize_focus_runtime(session, *, asset_id: str, plan: dict, resources: dict):
    """Hold and privately copy a verified focus controller through its consumer.

    This is the original mirrored/surface-none identity, not a generic OA
    FieldBundle. The enclosing Store scope remains the only lifecycle owner.
    """
    from msplatform.execution.inputs import freeze_file
    scope,controls=current_managed_native_store(),current_native_artifact_scope()
    if scope is None or controls is None or scope['store'] is not controls['store']:
        raise ValueError('focus runtime requires its managed Store parent')
    if set(resources)!={'builder','exporter','verifier'}:
        raise ValueError('focus runtime requires the exact original resources')
    store=scope['store'];science=identity(plan,Path(resources['builder']),session.context.tools['simion'])
    key=canonical_json_sha256(dict(schema_version=1,science=science,
        exporter_sha256=file_sha256(resources['exporter']),verifier_sha256=file_sha256(resources['verifier'])))
    with ExitStack() as stack:
        verified=stack.enter_context(store.claim_key('simion-focus-controller-v1:'+key))
        if verified is None or verified[0]!=asset_id:
            raise ValueError('focus runtime asset is not the verified scientific cache identity')
        token,asset=stack.enter_context(store.claim_token(asset_id))
        if asset!=verified[1]:
            raise ValueError('focus runtime Store claim differs')
        for name in ('focus_identity.json','focus_verify.process.json','focus_verify.stdout.log'):
            stack.enter_context(guarded_file_identity(asset/name))
        metadata=json.loads((asset/'focus_identity.json').read_text(encoding='utf8'))
        proof=json.loads((asset/'focus_verify.process.json').read_text(encoding='utf8'))
        marker=(asset/'focus_verify.stdout.log').read_text(encoding='utf-8-sig')
        if (metadata!={'cache_key':key,'identity':science} or proof.get('observation',{}).get('exit_code')!=0
                or 'ACCELERATOR_COMPONENT_FOCUS_PA_VERIFY=PASS' not in marker
                or any(not (asset/name).is_file() for name in expected_files(plan))):
            raise ValueError('focus runtime controller identity or verification differs')
        names=[f'orthogonal_accelerator_focus.pa{index}' for index in range(plan['electrode_count']+1)]
        target=session.input_dir/'focus_runtime';target.mkdir(parents=True,exist_ok=False)
        records=[]
        for name in names:
            source=asset/name
            stack.enter_context(guarded_file_identity(source))
            destination=session.declare_file(target/name,'solver_native_binary')
            record=freeze_file(source,destination,retention_role='solver_native_binary')
            record.pop('source_path',None);records.append(record)
            session.add_input('focus_runtime_pa'+str(len(records)-1),record)
            scope['account'](session._store_stage_directory)
        scope['required_source_assets'].add(asset_id)
        stack.enter_context(protect_native_controls(store,run_id=controls['run_id'],
            claim_ids=(*controls['claim_ids'],token),reservation_ids=controls['reservation_ids'],
            work_directory=controls['work_directory']))
        yield dict(asset_id=asset_id,cache_key=key,controller=records[0],members=records,
                   field_identity='mirrored_surface_none_focus_controller')


def main():
    if len(sys.argv) != 2:
        raise ValueError('focus worker requires its frozen request')
    path = Path(sys.argv[1]).resolve(strict=True)
    with guarded_file_identity(path) as bound:
        request = json.loads(path.read_text(encoding='utf8'))
        if set(request) != {'schema_version','context','parameters','inputs'} or request['schema_version'] != 1:
            raise ValueError('focus request differs')
        p = request['parameters']; run = Path(p['run_directory']).resolve(strict=True)
        if not path.is_relative_to(run/'inputs'):
            raise ValueError('focus request escapes owning run')
        receipt = Path(p['receipt_path']).resolve()
        logs = Path(p['log_directory']).resolve()
        scratch = Path(p['execution_directory']).resolve()
        if (not receipt.is_relative_to(run/'results') or not logs.is_relative_to(run/'logs')
                or not scratch.is_relative_to(logs)):
            raise ValueError('focus worker paths escape owning run')
        primary = None
        try:
            _worker(ExecutionContext(**request['context']), request)
        except BaseException as failure:
            primary = failure
            raise
        finally:
            try:
                report = json.loads(receipt.read_text(encoding='utf8'))
                report['request'] = dict(path=str(path), exists=True, bytes=bound.bytes_count,
                    sha256=bound.sha256, retention_role='required_evidence')
                write_json_atomic(receipt, report)
            except BaseException as failure:
                if primary is None: raise
                primary.add_note('focus request binding failed: '+str(failure))


if __name__ == '__main__':
    main()
