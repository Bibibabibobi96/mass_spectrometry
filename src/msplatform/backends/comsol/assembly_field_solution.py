"""Validate saved single-workpoint COMSOL solution readback records."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from msplatform.execution.context import ExecutionContext
from msplatform.execution.run_session import RunSession
from msplatform.results.artifacts import OpenedArtifact


def validate_solution_readback(record: Mapping[str, Any], *, study_tag: str,
                               solution_tag: str, dataset_tag: str) -> None:
    """Require stored solution identity, dimensions and explicit dataset binding."""
    if not isinstance(record, Mapping):
        raise ValueError('stationary solution readback must be an object')
    if any(not isinstance(tag, str) or not tag.strip() for tag in (study_tag, solution_tag, dataset_tag)):
        raise ValueError('stationary study, solution and dataset tags must be explicit')
    expected = {'study_tag': study_tag, 'solution_tag': solution_tag, 'dataset_tag': dataset_tag,
                'dataset_solution': solution_tag, 'solution_empty': False,
                'solution_count': 1, 'stored_main_solutions': 1}
    if any(record.get(name) != value or type(record.get(name)) is not type(value)
           for name, value in expected.items()):
        raise ValueError('stationary solution identity, dataset binding or count differs')
    dofs = record.get('solution_dofs')
    import math
    if type(dofs) not in (int, float) or not math.isfinite(dofs) or dofs <= 0 or dofs != int(dofs):
        raise ValueError('stationary solution requires positive actual degrees of freedom')


def solve_stationary(model: Mapping[str, Any] | OpenedArtifact, *, solver_numerics: Mapping[str, Any],
                     context: ExecutionContext) -> OpenedArtifact:
    """Solve one explicitly selected stationary workpoint and cold-reopen it."""
    from datetime import datetime
    from functools import partial
    from pathlib import Path
    from uuid import uuid4
    import json
    from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
    from msplatform.contracts.machine_contracts import ContractError
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record
    from msplatform.results.artifacts import open_artifact

    if solver_numerics != {'kind': 'comsol_stationary_default'}:
        raise ValueError('explicit comsol_stationary_default solver numerics required')
    source = open_artifact(model, expected_kind='prepared_model')
    metadata = source.metadata
    if (metadata.get('backend') != 'comsol' or metadata.get('scope') != 'assembly_electrostatic_unsolved'
            or metadata.get('field_status') != 'not_solved' or metadata.get('native_reopen_verified') is not True):
        raise ContractError('verified unsolved Assembly electrostatic model required')
    names = ('model', 'request', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry',
             'build_model', 'reopen_model')
    paths = {name: source.data_path(name) for name in names}
    request = json.loads(paths['request'].read_text(encoding='utf-8-sig'))
    projection = json.loads(paths['projection'].read_text(encoding='utf-8-sig'))
    if validate_request(projection, request) != request:
        raise ValueError('prepared model request differs from canonical projection')
    manifest_record = dict(source.reference['manifest'], path=str(source.manifest_location))
    for name in ('comsol_launcher', 'matlab_root'):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == 'matlab_root' else path.is_file()):
            raise ContractError('COMSOL stationary solve requires explicit tool: ' + name)
    stage, authority = read_stage_policy(context, 'solve_assembly_stationary', required_roles=('solver_native_binary',))
    if stage.get('runtime'):
        raise ContractError('COMSOL stationary solve has no runtime overrides')
    result = run_managed_stage(context,
        descriptor=dict(project='instrument_assembly', mode='stationary_workpoint', software=['COMSOL', 'MATLAB']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__sim__comsol__assembly-field-' + uuid4().hex[:12],
        payload=dict(action='solve_assembly_stationary', solver_numerics=dict(solver_numerics), stage_policy=stage),
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], source_references=[{'manifest_record': manifest_record}],
        expected_operation_ids=('solve_stationary', 'reopen_solution'),
        operation_dependencies={'reopen_solution': ['solve_stationary']},
        action=partial(execute_stationary, source=source, manifest_record=manifest_record, names=names, projection=projection, request=request,
                       solver_numerics=dict(solver_numerics), limits=stage['limits']),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)
    return open_artifact({'manifest': result['manifest'], 'product_id': 'solution'}, expected_kind='field_solution')


def execute_stationary(session: RunSession, *, source: OpenedArtifact, manifest_record: Mapping[str, Any],
                       names: tuple[str, ...], projection: Mapping[str, Any], request: Mapping[str, Any],
                       solver_numerics: Mapping[str, Any], limits: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the verified model, run one solve, then independently reopen it."""
    import json
    from msplatform.backends.comsol.native_execution import (
        declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
    )
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.io.manifest_records import file_record, verify_record

    if session.expected_operation_ids != ('solve_stationary', 'reopen_solution'):
        raise ValueError('stationary solve requires one compute followed by one cold reopen')
    launcher, sources = freeze_native_sources(session, ('comsolstartup.m', 'solve_assembly_stationary.m',
        'read_assembly_stationary_solution.m', 'verify_assembly_electrostatic_bindings.m',
        'read_comsol_mesh_size_controls.m'))
    session.add_input('prepared_model_manifest', manifest_record)
    frozen, paths, frozen_records = [], {}, {}
    model_path = source.data_path('model')
    model_record = dict(source.data_records['model'], path=str(model_path))
    verify_record('borrowed prepared model', model_record)
    session.add_input('prepared_model_model', model_record)
    paths['model'] = model_path
    for name in names:
        if name == 'model':
            continue
        src = source.data_path(name)
        target = session.declare_file(session.input_dir / 'prepared_model' / name / src.name,
                                      'required_evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(src, target)
        record = file_record(target, 'required_evidence')
        if any(record[key] != source.data_records[name][key] for key in ('bytes', 'sha256')):
            raise ValueError('prepared model frozen input differs: ' + name)
        session.add_input('prepared_' + name, record)
        frozen.append(record)
        paths[name] = target
        frozen_records[name] = record
    numerics = session.declare_file(session.input_dir / 'solver-numerics.json', 'required_evidence')
    write_json_atomic(numerics, solver_numerics)
    numeric_record = file_record(numerics, 'required_evidence')
    session.add_input('solver_numerics', numeric_record)
    session.add_input('comsol_launcher', file_record(session.context.tools['comsol_launcher'], 'required_evidence'))
    output = session.declare_file(session.run_dir / 'assembly-stationary-field.mph', 'solver_native_binary')
    raw_output = session.declare_file(session.run_dir / 'assembly-stationary-computed-raw.mph', 'solver_native_binary')
    matlab = launcher.parent.parent / 'matlab'
    host = json.dumps({name: str(getattr(session.context, name)) for name in
                       ('workspace', 'python_executable', 'host_state_path', 'policy_path')})
    baseline = json.loads(paths['reopen_geometry'].read_text(encoding='utf-8-sig'))
    reports, saved, first = {}, [], None
    try:
        for operation, mode in (('solve_stationary', 'compute'), ('reopen_solution', 'reopen')):
            report = session.declare_file(session.result_dir / (operation + '.json'), 'required_evidence')
            bootstrap = session.declare_file(session.log_dir / (operation + '.bootstrap.log'), 'required_evidence')
            completion = session.declare_file(session.log_dir / (operation + '.launcher.json'), 'required_evidence')
            task = session.declare_file(session.input_dir / (operation + '.m'), 'required_evidence')
            runtime = session.run_dir / 'comsol_runtime' / operation
            runtime.mkdir(parents=True)
            compute_report = session.result_dir / 'solve_stationary.json'
            call = 'solve_assembly_stationary(' + ','.join(map(matlab_text, (paths['projection'], paths['request'],
                paths['reopen_geometry'], paths['model'], output, raw_output, compute_report, mode))) + ')'
            task.write_text('addpath(' + matlab_text(matlab) + ');\nresult=' + call + ';\n'
                'fid=fopen(' + matlab_text(report) + ",'w','n','UTF-8');\n"
                "assert(fid>=0); cleanup=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n",
                encoding='utf-8', newline='\n')
            guards = [*sources, *frozen, numeric_record, file_record(task, 'required_evidence'), *saved]
            if mode == 'compute':
                guards.append(model_record)
            args = ['-NoProfile', '-File', str(launcher), '-HostContextJson', host, '-WorkingDirectory', str(session.run_dir),
                '-ComsolLauncherPath', str(session.context.tools['comsol_launcher']), '-MatlabRootPath',
                str(session.context.tools['matlab_root']), '-TaskScript', str(task), '-ReportPath', str(bootstrap),
                '-StartupAttempts', '1', '-RunId', session.run_id, '-RunDir', str(runtime), '-CompletionPath', str(completion)]
            primary = None
            try:
                session.run_process(operation, executable=session.context.powershell_executable, arguments=args,
                    role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
            except BaseException as error:
                primary = error
                raise
            finally:
                try:
                    declare_runtime_files(session, runtime, bootstrap=bootstrap)
                except BaseException as error:
                    if primary is None:
                        raise
                    primary.add_note('COMSOL diagnostic preservation failed: ' + repr(error))
            for record in guards:
                verify_record('stationary immutable input', record)
            for name in names:
                source.data_path(name)
            require_launcher_completion(completion, session.run_id)
            if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
                raise ValueError('COMSOL stationary bootstrap failed')
            row = json.loads(report.read_text(encoding='utf-8-sig'))
            _check_stationary_report(row, mode=mode, projection=projection, baseline=baseline, model=output)
            if mode == 'compute':
                first = row
                saved = [file_record(output, 'solver_native_binary'), file_record(report, 'required_evidence')]
            else:
                if row['solution'] != first['solution']:
                    raise ValueError('stationary solution cold readback differs')
            reports[operation] = report
        records = dict(model=saved[0], solver_numerics=numeric_record,
                       prepared_manifest=manifest_record,
                       **{name: frozen_records[name] for name in
                          ('request', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry')},
                       **{name: file_record(path, 'required_evidence') for name, path in reports.items()})
        outputs = [output, raw_output, *reports.values()]
        metadata = dict(backend='comsol', scope='single_stationary_workpoint', field_status='solved',
                        source_status='not_requested', scientific_qualification='not_granted',
                        native_reopen_verified=True, solution=first['solution'])
        return dict(status='success', summary=metadata, output_paths=[str(path) for path in outputs],
            required_output_paths=[str(path) for path in outputs], retention_preserve_paths=[],
            manifest_extra_fields=dict(products=dict(solution=dict(schema_version=1, kind='field_solution',
                status='complete', metadata=metadata, data=records))))
    except BaseException as failure:
        try:
            present = [path for path in (raw_output, output, session.result_dir / 'solve_stationary.json', session.result_dir / 'reopen_solution.json') if path.is_file()]
            if present:
                prior = getattr(failure, 'failure_output_paths', ())
                if not isinstance(prior, (tuple, list)):
                    raise ValueError('Existing failure output paths differ')
                failure.failure_output_paths = [*prior, *present]
        except BaseException as secondary:
            failure.add_note('Raw computed-model evidence preservation failed: ' + repr(secondary))
        raise


def _check_stationary_report(row: Mapping[str, Any], *, mode: str, projection: Mapping[str, Any],
                             baseline: Mapping[str, Any], model: Any) -> None:
    from pathlib import Path
    if (not isinstance(row, Mapping) or row.get('scope') != 'single_stationary_workpoint'
            or row.get('operation') != mode or row.get('compute_calls') != (1 if mode == 'compute' else 0)
            or Path(row.get('model_path', '')).resolve() != model.resolve()):
        raise ValueError('stationary workpoint report differs')
    keys = [g['instance_id'] + '/' + g['electrode_group_id'] for g in projection['electrode_groups']]
    if row.get('group_keys') != keys:
        raise ValueError('stationary scientific groups differ')
    for name in ('group_keys', 'group_faces', 'vacuum_domains', 'outer_faces'):
        if row.get(name) != baseline.get(name):
            raise ValueError('stationary model differs from frozen geometry: ' + name)
    solution = row.get('solution')
    if not isinstance(solution, Mapping):
        raise ValueError('stationary solution readback missing')
    validate_solution_readback(solution, study_tag='std1', solution_tag=solution.get('solution_tag'),
                               dataset_tag='assembly_field_solution')
    if (solution.get('solver_policy') != 'comsol_stationary_default'
            or str(solution.get('solver_type', '')).lower() != 'stationary'
            or not solution.get('solver_sequence_type') or not solution.get('solver_features')
            or not solution.get('comsol_version')):
        raise ValueError('stationary solver configuration evidence is incomplete')


def recover_stationary(failed_manifest: Mapping[str, Any], *, selected_output: Mapping[str, Any],
                       context: ExecutionContext) -> OpenedArtifact:
    """Cold-verify an explicit failed producer's saved solution, without Compute."""
    import json
    from datetime import datetime
    from functools import partial
    from pathlib import Path
    from uuid import uuid4
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record, record_path, verify_record, require_completed_terminal_publication
    from msplatform.results.artifacts import open_artifact
    verify_record('failed manifest', failed_manifest)
    manifest_path = record_path(failed_manifest)
    require_completed_terminal_publication(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest.get('status') != 'failed':
        raise ValueError('explicit failed terminal producer required')
    outputs = manifest.get('outputs', [])
    if sum(record == selected_output for record in outputs) != 1 or selected_output.get('retention_role') != 'solver_native_binary':
        raise ValueError('selected solution must be one exact failed producer output')
    verify_record('selected solution', selected_output)
    def output(name):
        records = [record for record in outputs if Path(record['path']).name == name]
        if len(records) != 1:
            raise ValueError('missing unique failed producer evidence: ' + name)
        verify_record(name, records[0])
        return json.loads(record_path(records[0]).read_text(encoding='utf-8-sig'))
    summary, completion = output('summary.json'), output('execution_completion.json')
    writers = completion['writer_completion']
    if summary.get('writers_stopped') is not True or completion.get('status') != 'failed' or completion.get('run_id') != manifest.get('run_id') or summary.get('run_id') != manifest.get('run_id'):
        raise ValueError('failed source has not stopped')
    ops = writers['operations']
    if [op.get('operation_id') for op in ops] not in (['solve_stationary'], ['solve_stationary', 'reopen_solution']):
        raise ValueError('source operation prefix differs')
    if any(op['observation'].get('exit_confirmed') is not True or type(op['observation'].get('returncode')) is not int for op in ops) or ops[0]['observation']['returncode'] != 0:
        raise ValueError('source writer exit not confirmed or compute failed')
    releases = writers['resource_releases']
    release_ids = [item.get('release_id') for item in releases]
    if len(set(release_ids)) != len(release_ids) or any(not isinstance(item, str) or not item for item in release_ids) or set(release_ids) != {op.get('resource_release_id') for op in ops}:
        raise ValueError('source host release identities differ')
    for item in releases:
        host = item['completion_receipt']['host_release']
        if not isinstance(host, dict) or set(host) != {'inherited', 'token', 'result', 'error'} or type(host['inherited']) is not bool or not isinstance(host['token'], str) or not host['token'] or host['error'] is not None:
            raise ValueError('source host receipt differs')
        if host['inherited']:
            if host['result'] is not None:
                raise ValueError('inherited host receipt cannot attest owner release')
        elif host['result'] != {'status': 'released', 'token': host['token']}:
            raise ValueError('source host reservation not released')
    numeric_record = manifest['inputs']['solver_numerics']
    verify_record('failed solver numerics', numeric_record)
    if json.loads(record_path(numeric_record).read_text(encoding='utf-8-sig')) != {'kind': 'comsol_stationary_default'}:
        raise ValueError('failed solver numerics differ')
    source_record = manifest['inputs']['prepared_model_manifest']
    verify_record('prepared source manifest', source_record)
    prepared = open_artifact({'manifest': source_record, 'product_id': 'model'}, expected_kind='prepared_model')
    metadata = prepared.metadata
    if metadata.get('backend') != 'comsol' or metadata.get('scope') != 'assembly_electrostatic_unsolved' or metadata.get('field_status') != 'not_solved' or metadata.get('native_reopen_verified') is not True:
        raise ValueError('verified unsolved Assembly model required')
    names = ('model', 'request', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry', 'build_model', 'reopen_model')
    for name in names:
        expected = prepared.data_records[name]
        recorded = manifest['inputs']['prepared_model_model' if name == 'model' else 'prepared_' + name]
        verify_record('failed source input ' + name, recorded)
        if any(recorded[key] != expected[key] for key in ('sha256', 'bytes')):
            raise ValueError('prepared input identity differs: ' + name)
    projection = json.loads(prepared.data_path('projection').read_text(encoding='utf-8-sig'))
    request = json.loads(prepared.data_path('request').read_text(encoding='utf-8-sig'))
    from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
    if validate_request(projection, request) != request:
        raise ValueError('prepared request differs')
    for name in ('comsol_launcher', 'matlab_root'):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == 'matlab_root' else path.is_file()):
            raise ValueError('COMSOL stationary recovery requires explicit tool: ' + name)
    stage, authority = read_stage_policy(context, 'recover_assembly_stationary', required_roles=('solver_native_binary',))
    result = run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='stationary_recovery', software=['COMSOL', 'MATLAB']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__analysis__comsol__stationary-recovery-' + uuid4().hex[:12],
        payload=dict(action='recover_assembly_stationary', stage_policy=stage), committed_new_bytes=stage['limits']['transient_run_directory_bytes'],
        commitment_inputs=[authority, failed_manifest, source_record, numeric_record], retention=stage['artifact_retention'],
        source_references=[{'manifest_record': failed_manifest}, {'manifest_record': source_record}],
        expected_operation_ids=('reopen_solution',), operation_dependencies={},
        action=partial(_execute_recovery, source=prepared, failed_manifest=failed_manifest, selected_output=selected_output, numeric_record=numeric_record, names=names, projection=projection, limits=stage['limits']),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)
    return open_artifact({'manifest': result['manifest'], 'product_id': 'solution'}, expected_kind='field_solution')


def _execute_recovery(session, *, source, failed_manifest, selected_output, numeric_record, names, projection, limits):
    import json
    from msplatform.backends.comsol.native_execution import declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion
    from msplatform.execution.inputs import freeze_file
    from msplatform.io.manifest_records import file_record, verify_record, record_path
    launcher, sources = freeze_native_sources(session, ('comsolstartup.m', 'solve_assembly_stationary.m', 'read_assembly_stationary_solution.m', 'verify_assembly_electrostatic_bindings.m', 'read_comsol_mesh_size_controls.m'))
    session.add_input('failed_manifest', failed_manifest)
    session.add_input('borrowed_solution', selected_output)
    source_manifest = dict(source.reference['manifest'], path=str(source.manifest_location))
    session.add_input('prepared_model_manifest', source_manifest)
    selected_path = record_path(selected_output)
    numerics_path = session.declare_file(session.input_dir / 'solver-numerics.json', 'required_evidence')
    freeze_file(record_path(numeric_record), numerics_path)
    frozen_numeric = file_record(numerics_path, 'required_evidence')
    if any(frozen_numeric[key] != numeric_record[key] for key in ('bytes','sha256')): raise ValueError('frozen solver numerics differ')
    session.add_input('solver_numerics', frozen_numeric)
    paths, frozen, records = {}, [frozen_numeric], {}
    for name in names:
        source_path = source.data_path(name)
        original = dict(source.data_records[name], path=str(source_path))
        if name == 'model':
            session.add_input('prepared_model_model', original)
            paths[name] = source_path
            frozen.append(original)
            continue
        target = session.declare_file(session.input_dir / 'prepared_model' / name / source_path.name, 'required_evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source_path, target)
        record = file_record(target, 'required_evidence')
        if any(record[key] != original[key] for key in ('bytes', 'sha256')):
            raise ValueError('frozen prepared input differs: ' + name)
        session.add_input('prepared_' + name, record)
        frozen.append(record); records[name] = record; paths[name] = target
    report = session.declare_file(session.result_dir / 'reopen_solution.json', 'required_evidence')
    bootstrap = session.declare_file(session.log_dir / 'reopen_solution.bootstrap.log', 'required_evidence')
    completion = session.declare_file(session.log_dir / 'reopen_solution.launcher.json', 'required_evidence')
    task = session.declare_file(session.input_dir / 'reopen_solution.m', 'required_evidence')
    runtime = session.run_dir / 'comsol_runtime' / 'reopen_solution'; runtime.mkdir(parents=True)
    matlab = launcher.parent.parent / 'matlab'
    call = 'solve_assembly_stationary(' + ','.join(map(matlab_text, (paths['projection'], paths['request'], paths['reopen_geometry'], paths['model'], selected_path, selected_path, report, 'recover'))) + ')'
    task.write_text('addpath(' + matlab_text(matlab) + ');\nresult=' + call + ';\nfid=fopen(' + matlab_text(report) + ",'w','n','UTF-8'); assert(fid>=0); c=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n", encoding='utf-8', newline='\n')
    host = json.dumps({name: str(getattr(session.context, name)) for name in ('workspace','python_executable','host_state_path','policy_path')})
    args = ['-NoProfile','-File',str(launcher),'-HostContextJson',host,'-WorkingDirectory',str(session.run_dir),'-ComsolLauncherPath',str(session.context.tools['comsol_launcher']),'-MatlabRootPath',str(session.context.tools['matlab_root']),'-TaskScript',str(task),'-ReportPath',str(bootstrap),'-StartupAttempts','1','-RunId',session.run_id,'-RunDir',str(runtime),'-CompletionPath',str(completion)]
    guards = [*sources, *frozen, failed_manifest, selected_output, source_manifest, file_record(task, 'required_evidence')]
    primary = None
    try:
        session.run_process('reopen_solution', executable=session.context.powershell_executable, arguments=args, role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
    except BaseException as error:
        primary = error; raise
    finally:
        try:
            declare_runtime_files(session, runtime, bootstrap=bootstrap)
        except BaseException as error:
            if primary is None: raise
            primary.add_note('Recovery diagnostic preservation failed: ' + repr(error))
    for record in guards: verify_record('recovery immutable input', record)
    require_launcher_completion(completion, session.run_id)
    if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'): raise ValueError('COMSOL recovery bootstrap failed')
    row = json.loads(report.read_text(encoding='utf-8-sig'))
    baseline = json.loads(paths['reopen_geometry'].read_text(encoding='utf-8-sig'))
    _check_stationary_report(row, mode='recover', projection=projection, baseline=baseline, model=selected_path)
    data = dict(model=selected_output, solver_numerics=frozen_numeric, prepared_manifest=source_manifest, **{name: records[name] for name in ('request','projection','descriptor','geometry_validation','reopen_geometry')}, reopen_solution=file_record(report,'required_evidence'))
    metadata = dict(backend='comsol', scope='single_stationary_workpoint', field_status='solved', source_status='not_requested', scientific_qualification='not_granted', native_reopen_verified=True, recovery_compute_calls=0, solution=row['solution'])
    return dict(status='success', summary=metadata, output_paths=[str(report)], required_output_paths=[str(report)], retention_preserve_paths=[], manifest_extra_fields=dict(products=dict(solution=dict(schema_version=1, kind='field_solution', status='complete', metadata=metadata, data=data))))
