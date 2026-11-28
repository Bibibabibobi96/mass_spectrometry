"""Store-owned closed two-zone OA focus workflow and legacy MR handoff."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, nullcontext
from functools import partial
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import (
    current_managed_native_store,
    recover_managed_native_store_stage,
    run_managed_stage,
    standalone_native_store,
)
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.resources import resource_path
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.execution.context import ExecutionContext
from msplatform.io.file_identity import file_sha256, guarded_file_identity
from msplatform.io.manifest_records import file_record
from msplatform.storage import ArtifactStore
from msplatform.workflows.oa_focus_controller import run_focus_controller_campaign
from msplatform.workflows.oa_focus_mr_runtime_receipt import project, write_receipt
from msplatform.workflows.oa_focus_workflow import compile_workflow

_PROJECT = 'orthogonal_accelerator'
_SOFTWARE = ['SIMION 2020', 'Python 3.11']
_MODES = {
    'flight': 'component_focus_flight',
    'field-contrast': 'component_focus_field_contrast',
    'fast-adjust': 'component_focus_fast_adjust',
}
_SCRIPTS = {name: 'component_focus_' + name.replace('-', '_') + '_action.ps1' for name in _MODES}


def _write_json(session, path: Path, value: Any) -> Path:
    target = session.declare_file(path, 'required_evidence')
    write_json_atomic(target, value)
    return target


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _result_receipt(store: ArtifactStore, scope: dict, run_id: str, result: dict | None) -> dict:
    value = dict(result or {}, run_id=run_id, store_run_id=scope['parent_run_id'],
                 store_run_path=str(scope['published_path']) if scope['published_path'] else None)
    if 'manifest' not in value:
        with store._db() as db:
            row = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()
        if row is not None:
            asset = store.asset_status(row[0])
            value['manifest'] = file_record(asset['path']/'runs'/run_id/'run_manifest.json', 'required_evidence')
    if 'manifest' in value:
        value['run_directory'] = str(Path(value['manifest']['path']).parent)
        value['summary'] = str(Path(value['manifest']['path']).parent/'summary.json')
    return value


def _failure_outputs(session) -> list[Path]:
    paths = [session.artifact_run_dir/'summary.json']
    for name in ('results', 'simion'):
        root = session.artifact_run_dir/name
        if root.is_dir():
            paths.extend(path for path in root.rglob('*') if path.is_file()
                         and path.name != 'execution_completion.json')
    return list(dict.fromkeys(paths))


def _powershell_action(session, *, script: Path, arguments: Mapping[str, Any],
                       limits: Mapping[str, Any], source_records: list[dict], role: str) -> dict:
    transport = session.declare_file(session.input_dir/'action_transport.json', 'required_evidence')
    write_json_atomic(transport, dict(schema_version=1, role='oa_focus_store_action_transport',
        package=dict(run_dir=str(session.run_dir), artifact_run_dir=str(session.artifact_run_dir),
            input_dir=str(session.input_dir), result_dir=str(session.result_dir), log_dir=str(session.log_dir),
            run_config=str(session.run_config), summary=str(session.run_dir/'summary.json'))))
    session.add_input('action_transport', file_record(transport, 'required_evidence'))
    argv = ['-NoProfile', '-NonInteractive', '-File', str(script), '-PackagePath', str(transport)]
    for name, value in arguments.items():
        if value is None or value is False:
            continue
        argv.append('-'+name)
        if value is True:
            continue
        values = value if isinstance(value, (list, tuple)) else (value,)
        argv.extend(str(item) for item in values)
    try:
        session.run_process('action', executable=session.context.powershell_executable, arguments=argv,
            role=role, stage='oa_focus_'+role.lower(), limits=limits,
            immutable_input_records=[file_record(script, 'required_evidence'),
                file_record(transport, 'required_evidence'), *source_records])
        publication_path = session.artifact_run_dir/'results/action_publication.json'
        publication = _read_json(publication_path)
        if publication.get('role') != 'oa_focus_action_publication' or not isinstance(publication.get('outputs'), list):
            raise ValueError('focus action did not publish its explicit output list')
        outputs = [session.canonical_path(path) for path in publication['outputs']]
        outputs.append(publication_path)
        for path in outputs:
            session.declare_file(path, 'solver_native_binary' if path.suffix.lower() in {
                '.pa', '.pa#', '.iob', '.fly2'} or '.pa' in path.name.lower() else 'required_evidence')
        summary = _read_json(session.artifact_run_dir/'summary.json')
        return dict(status='success', summary=summary, output_paths=outputs,
            required_output_paths=outputs, retention_preserve_paths=[], manifest_extra_fields={})
    except BaseException as failure:
        outputs = _failure_outputs(session)
        for path in outputs:
            session.declare_file(path, 'solver_native_binary' if path.suffix.lower() in {
                '.pa', '.pa#', '.iob', '.fly2'} or '.pa' in path.name.lower() else 'required_evidence')
        failure.failure_output_paths = outputs
        raise


def _run_action(context: ExecutionContext, *, artifact_store: ArtifactStore, action: str,
                run_id: str, arguments: Mapping[str, Any], source_paths: Iterable[Path],
                protected_payloads: Iterable[Path] = (), receipt_path: Path | None = None) -> dict:
    """Run one native science action without a second package or finalizer."""
    if action not in _MODES:
        raise ValueError('unknown OA focus action')
    arguments = dict(arguments)
    arguments.update(WorkspaceRoot=context.workspace, ArtifactRoot=artifact_store.root,
        PythonExe=context.python_executable, SimionExe=context.tools.get('simion'))
    stage, policy = read_stage_policy(context, 'oa_focus_'+action.replace('-', '_'))
    budget = stage['limits']['transient_run_directory_bytes']
    sources = [Path(path).resolve(strict=True) for path in source_paths]
    records = [file_record(path, 'required_evidence') for path in sources]
    protected = [*sources, *(Path(path).resolve(strict=True) for path in protected_payloads)]
    script = native_resource_path(_SCRIPTS[action]).resolve(strict=True)
    scope = None
    parent = current_managed_native_store()
    owner = (nullcontext() if parent is not None else
             standalone_native_store(artifact_store, task_key='oa-focus-'+action+':'+run_id, budget=budget))
    try:
        with owner as active:
            scope = parent if parent is not None else active
            result = run_managed_stage(context, descriptor=dict(project=_PROJECT,
                mode=_MODES[action], software=_SOFTWARE), run_id=run_id,
                payload=dict(action=action, store_managed=True), committed_new_bytes=budget,
                commitment_inputs=[policy, file_record(script, 'required_evidence'), *records],
                retention=stage['artifact_retention'], expected_operation_ids=['action'],
                operation_dependencies={}, action=partial(_powershell_action, script=script,
                    arguments=arguments, limits=stage['limits'], source_records=records,
                    role='SIMION' if action == 'flight' else 'GATE'),
                action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
                protected_paths=protected, use_short_execution_path=True,
                completion_api=no_particle_batch_completion_api, artifact_store=artifact_store)
            scope['reported_status'] = result['status']
            if receipt_path is not None:
                write_json_atomic(receipt_path, _result_receipt(artifact_store, scope, run_id, result))
            if parent is not None:
                return result
        return _result_receipt(artifact_store, scope, run_id, result)
    except BaseException:
        if receipt_path is not None and scope is not None and scope['produced']:
            write_json_atomic(receipt_path, _result_receipt(artifact_store, scope, run_id, None))
        raise


def _freeze(session, name: str, source: Path) -> Path:
    from msplatform.execution.inputs import freeze_file
    target = session.declare_file(session.input_dir/name, 'required_evidence')
    record = freeze_file(source, target, retention_role='required_evidence')
    session.add_input(name.removesuffix('.json'), record)
    return target


def _workflow_action(session, *, artifact_store: ArtifactStore, request: Path, release: Path,
                     workflow: dict, run_id: str, runtime_checkpoint: Path | None) -> dict:
    _freeze(session, 'consumer_request.json', request)
    release_frozen = _freeze(session, 'release_spec.json', release)
    plan_path = _write_json(session, session.result_dir/'component_focus_workflow_plan.json', workflow)
    campaign_path = _write_json(session, session.input_dir/'resolved_campaign.json', workflow['campaign'])
    session.add_input('resolved_campaign', file_record(campaign_path, 'required_evidence'))
    pa = run_focus_controller_campaign(session.context, artifact_store=artifact_store,
        campaign_path=campaign_path, mesh_mm_per_gu=workflow['pa_plan']['numerical_domain']['mesh_mm_per_gu'],
        run_id=run_id+'__pa', committed_new_bytes=read_stage_policy(session.context, 'oa_focus_controller')[0]['limits']['transient_run_directory_bytes'],
        legacy_pa_output=True, runtime_checkpoint_path=runtime_checkpoint)
    pa_run = Path(pa['run_directory'])
    pa_result_path = pa_run/'results/component_focus_pa_result.json'
    pa_result = _read_json(pa_result_path)
    controller = Path(pa_result['runtime_controller_path'])
    flight = _run_action(session.context, artifact_store=artifact_store, action='flight',
        run_id=run_id+'__n100', arguments=dict(PABuildRunPath=pa_run, RuntimeControllerPath=controller,
            CampaignPath=campaign_path, ReleaseSpecPath=release_frozen, FieldMode='native'),
        source_paths=[campaign_path, release_frozen], protected_payloads=[pa_run, controller])
    flight_run = Path(flight['run_directory'])
    selected_run = flight_run
    selected_id = run_id+'__n100'
    flight_summary = _read_json(flight_run/'summary.json')
    contrast_child = None
    adjust_child = None
    accepted_campaign = campaign_path
    if flight_summary['status'] != 'candidate_complete':
        contrast = _run_action(session.context, artifact_store=artifact_store, action='field-contrast',
            run_id=run_id+'__field-contrast__r01', arguments=dict(RootRunId=run_id,
                PABuildRunPath=pa_run, RuntimeControllerPath=controller, CampaignPath=campaign_path,
                ReleaseSpecPath=release_frozen, InitialAnalysisPath=flight_run/'results/focus_analysis.json'),
            source_paths=[campaign_path, release_frozen, flight_run/'results/focus_analysis.json'],
            protected_payloads=[pa_run, controller])
        contrast_run = Path(contrast['run_directory'])
        contrast_child = dict(run_id=contrast['run_id'],
            manifest_sha256=file_sha256(contrast_run/'run_manifest.json').lower(),
            contrast_sha256=file_sha256(contrast_run/'results/two_zone_ideal_field_contrast.json').lower())
        adjust = _run_action(session.context, artifact_store=artifact_store, action='fast-adjust',
            run_id=run_id+'__fast-adjust__r01', arguments=dict(RootRunId=run_id, PABuildRunPath=pa_run,
                RuntimeControllerPath=controller, CampaignPath=campaign_path, ReleaseSpecPath=release_frozen,
                InitialAnalysisPath=flight_run/'results/focus_analysis.json', MaximumTrials=7),
            source_paths=[campaign_path, release_frozen, flight_run/'results/focus_analysis.json'],
            protected_payloads=[pa_run, controller])
        adjust_run = Path(adjust['run_directory'])
        adjust_summary = _read_json(adjust_run/'summary.json')
        if adjust_summary['status'] != 'accepted':
            raise ValueError('Provider bounded Fast-Adjust exhausted without passing the complete N=100 transport and exit-energy gates; MR runtime receipt is withheld')
        accepted_campaign = adjust_run/'results/accepted_campaign.json'
        adjust_receipt = _read_json(adjust_run/'results/component_focus_fast_adjust_receipt.json')
        selected_id = adjust_receipt['accepted_trial']['run_id']
        selected_run = Path(adjust_receipt['accepted_trial']['run_directory'])
        adjust_child = dict(run_id=adjust['run_id'], manifest_sha256=file_sha256(adjust_run/'run_manifest.json').lower(),
            summary_sha256=file_sha256(adjust_run/'summary.json').lower(),
            accepted_campaign_sha256=file_sha256(accepted_campaign).lower(), accepted_flight_run_id=selected_id)
    selected_manifest = selected_run/'run_manifest.json'
    selected_analysis = selected_run/'results/focus_analysis.json'
    analysis = _read_json(selected_analysis)
    if (analysis['status'] != 'candidate_complete' or not all(analysis['hard_gate'][name] for name in (
            'complete_transport_passed', 'exit_slow_energy_passed', 'exit_axial_energy_passed',
            'exit_transverse_energy_passed', 'exit_transverse_velocity_bias_passed'))
            or analysis['exit_energy_assessment']['passed'] is not True):
        raise ValueError('Selected provider flight has not passed transport, exit Ex/Ey/Ez, and signed x-velocity gates; runtime receipt is withheld')
    analysis_record = file_record(selected_analysis, 'required_evidence')
    receipt = _write_json(session, session.result_dir/'component_focus_workflow_receipt.json', dict(
        schema_version=1, role='orthogonal_accelerator_component_focus_workflow_receipt', status='candidate_complete',
        qualification='candidate_prototype_numeric_component_focus_only', consumer_project_id=workflow['consumer_project_id'],
        request_sha256=workflow['request_sha256'], release_spec_sha256=workflow['release_spec_sha256'],
        resolved_campaign_sha256=file_sha256(accepted_campaign).lower(), provider_plan_sha256=file_sha256(plan_path).lower(),
        pa_child=dict(run_id=run_id+'__pa', manifest_sha256=file_sha256(pa_run/'run_manifest.json').lower(),
            cache_key=pa_result['cache_key'], generation_sha256=pa_result['generation_sha256']),
        flight_child=dict(run_id=selected_id, manifest_sha256=file_sha256(selected_manifest).lower(),
            analysis=dict(path=str(selected_analysis), bytes=analysis_record['bytes'], sha256=analysis_record['sha256'].lower()),
            source_release_receipt_sha256=file_sha256(selected_run/'inputs/release_receipt.json').lower()),
        hard_gate=analysis['hard_gate'], exit_energy_assessment=analysis['exit_energy_assessment'],
        field_contrast_child=contrast_child, fast_adjust_child=adjust_child,
        pa_policy='one_store_cache_claim__at_most_one_native_build__claimed_read_only_runtime_fast_adjust',
        release_policy='one_frozen_common_release__materialized_only_inside_n100_flight__excluded_from_pa_identity'))
    mr_receipt = session.result_dir/'mrtof_runtime_receipt.json'
    value = project(workflow_receipt_path=receipt, pa_result_path=pa_result_path,
        pa_manifest_path=pa_run/'run_manifest.json', campaign_path=accepted_campaign,
        plan_path=pa_run/'results/component_focus_pa_plan.json')
    write_receipt(value, mr_receipt)
    session.declare_file(mr_receipt, 'required_evidence')
    summary = _write_json(session, session.artifact_run_dir/'summary.json', dict(schema_version=1,
        role='orthogonal_accelerator_component_focus_workflow', status='candidate_complete',
        qualification='candidate_prototype_numeric_component_focus_only', receipt_sha256=file_sha256(receipt).lower(),
        mrtof_runtime_receipt_sha256=file_sha256(mr_receipt).lower(), pa_run_id=run_id+'__pa', flight_run_id=selected_id))
    outputs = [summary, plan_path, receipt, mr_receipt]
    return dict(status='success', summary=_read_json(summary), output_paths=outputs,
        required_output_paths=outputs, retention_preserve_paths=[], manifest_extra_fields={})


def run_component_focus(context: ExecutionContext, *, artifact_store: ArtifactStore, request_path: Path,
                        release_spec_path: Path, run_id: str, runtime_checkpoint_path: Path | None = None,
                        receipt_path: Path | None = None) -> dict:
    """Execute the original OA focus science with Store as its sole run owner."""
    stage, policy = read_stage_policy(context, 'oa_focus_workflow')
    request = Path(request_path).resolve(strict=True)
    release = Path(release_spec_path).resolve(strict=True)
    sources = [request, release]
    if runtime_checkpoint_path is not None:
        sources.append(Path(runtime_checkpoint_path).resolve(strict=True))
    records = [file_record(path, 'required_evidence') for path in sources]
    with ExitStack() as guards:
        for record in records:
            guards.enter_context(guarded_file_identity(Path(record['path']), expected_bytes=record['bytes'],
                                                       expected_sha256=record['sha256']))
        workflow = compile_workflow(request, release)
        budget = stage['limits']['transient_run_directory_bytes']
        scope = None
        try:
            with standalone_native_store(artifact_store, task_key='oa-focus-workflow:'+run_id,
                                         budget=budget) as scope:
                result = run_managed_stage(context, descriptor=dict(project=_PROJECT,
                    mode='component_focus_workflow', software=_SOFTWARE), run_id=run_id,
                    payload=dict(store_managed=True), committed_new_bytes=budget,
                    commitment_inputs=[policy, *records], retention=stage['artifact_retention'],
                    expected_operation_ids=[], operation_dependencies={}, action=partial(_workflow_action,
                        artifact_store=artifact_store, request=request, release=release, workflow=workflow,
                        run_id=run_id, runtime_checkpoint=runtime_checkpoint_path),
                    action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
                    protected_paths=sources, use_short_execution_path=True,
                    completion_api=no_particle_batch_completion_api, artifact_store=artifact_store)
                scope['reported_status'] = result['status']
                if receipt_path is not None:
                    write_json_atomic(receipt_path, _result_receipt(artifact_store, scope, run_id, result))
            return _result_receipt(artifact_store, scope, run_id, result)
        except BaseException:
            if receipt_path is not None and scope is not None and scope['produced']:
                write_json_atomic(receipt_path, _result_receipt(artifact_store, scope, run_id, None))
            raise


def recover_component_focus_publication(*, store: ArtifactStore, store_run_id: str,
                                        stage_asset_id: str | None = None, context: ExecutionContext) -> dict:
    """Replay only the existing Store native-stage and publication journals."""
    stage_recovered = (recover_managed_native_store_stage(store, stage_asset_id, context=context)
                       if stage_asset_id is not None else False)
    run_recovered = store.recover_run_publication(store_run_id)
    return dict(stage_recovered=stage_recovered, run_recovered=run_recovered,
                run=store.run_status(store_run_id))


def _context(arguments) -> ExecutionContext:
    powershell = arguments.powershell_exe
    policy = arguments.stage_policy
    if policy is None:
        policy = Path(str(files('msplatform.components.orthogonal_accelerator')
                        .joinpath('config/component_focus_store_policy.json')))
    simion = Path(arguments.simion_exe).absolute() if arguments.simion_exe else Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'SIMION-2020/simion.exe'
    workspace = Path(arguments.workspace_root).absolute()
    return ExecutionContext(workspace=workspace, python_executable=Path(sys.executable).resolve(),
        powershell_executable=Path(powershell).resolve(), tools={'simion': simion.absolute()},
        host_state_path=workspace/'artifacts/platform/host_resources.sqlite3', policy_path=resource_path('host_resource_policy.json'),
        stage_policy_path=policy.absolute())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=['workflow', *_MODES], required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--workspace-root', type=Path, required=True)
    parser.add_argument('--store-root', type=Path, required=True)
    parser.add_argument('--powershell-exe', required=True)
    parser.add_argument('--stage-policy', type=Path)
    parser.add_argument('--simion-exe')
    parser.add_argument('--receipt-path', type=Path)
    parser.add_argument('--request-path', type=Path)
    parser.add_argument('--release-spec-path', type=Path)
    parser.add_argument('--runtime-checkpoint-path', type=Path)
    parser.add_argument('--pa-build-run-path', type=Path)
    parser.add_argument('--runtime-controller-path', type=Path)
    parser.add_argument('--campaign-path', type=Path)
    parser.add_argument('--root-run-id')
    parser.add_argument('--initial-analysis-path', type=Path)
    parser.add_argument('--field-mode', default='native')
    parser.add_argument('--maximum-trials', type=int, default=7)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    context = _context(args)
    store = ArtifactStore(args.store_root.absolute())
    if args.action == 'workflow':
        result = run_component_focus(context, artifact_store=store, request_path=args.request_path,
            release_spec_path=args.release_spec_path, run_id=args.run_id,
            runtime_checkpoint_path=args.runtime_checkpoint_path, receipt_path=args.receipt_path)
    else:
        required = [args.pa_build_run_path, args.runtime_controller_path, args.campaign_path, args.release_spec_path]
        if any(value is None for value in required):
            raise ValueError('native focus action requires PA, runtime, campaign and release inputs')
        arguments = dict(PABuildRunPath=args.pa_build_run_path, RuntimeControllerPath=args.runtime_controller_path,
            CampaignPath=args.campaign_path, ReleaseSpecPath=args.release_spec_path, SimionExe=args.simion_exe)
        sources = [args.pa_build_run_path, args.runtime_controller_path, args.campaign_path, args.release_spec_path]
        if args.action == 'flight':
            arguments['FieldMode'] = args.field_mode
        else:
            if args.root_run_id is None or args.initial_analysis_path is None:
                raise ValueError('contrast and Fast-Adjust require root and initial-analysis identities')
            arguments.update(RootRunId=args.root_run_id, InitialAnalysisPath=args.initial_analysis_path)
            sources.append(args.initial_analysis_path)
            if args.action == 'fast-adjust':
                arguments['MaximumTrials'] = args.maximum_trials
        result = _run_action(context, artifact_store=store, action=args.action, run_id=args.run_id,
            arguments=arguments, source_paths=[args.campaign_path, args.release_spec_path, *sources[4:]],
            protected_payloads=[args.pa_build_run_path, args.runtime_controller_path], receipt_path=args.receipt_path)
    print(json.dumps(result, default=str, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
