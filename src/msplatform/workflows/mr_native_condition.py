"""Store owners for the explicit MR native-condition and ordered campaign."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.owner import (
    recover_managed_native_store_stage,
    run_managed_stage,
    standalone_native_store,
)
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.resources import resource_path
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record
from msplatform.storage import ArtifactStore

_PROJECT = 'multi_reflection_tof'
_SOFTWARE = ['SIMION 2020', 'Python 3.11']


def _resource(name: str) -> Path:
    return Path(str(files('msplatform.workflows').joinpath('resources/'+name))).resolve(strict=True)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _unique_records(records: Iterable[dict]) -> list[dict]:
    return list({str(Path(record['path']).resolve()): record for record in records}.values())


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    return list(dict.fromkeys(Path(path).resolve(strict=True) for path in paths))


def _legacy_artifact_root(context_path: Path) -> Path:
    value = _read_json(context_path).get('legacy_artifact_root')
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError('condition context requires an absolute legacy_artifact_root for its existing MR children')
    return Path(value)


def _context_sources(context_path: Path) -> list[Path]:
    """Resolve only the explicit paths in the existing condition context."""
    document = _read_json(context_path)
    base = context_path.parent
    paths = []
    for name, value in document.items():
        if not isinstance(value, str) or not value:
            continue
        if name.endswith(('_path', '_manifest')) or name in {
                'geometry_review_run_path', 'native_corridor_bank_run_path'}:
            path = Path(value)
            paths.append(path if path.is_absolute() else base/path)
    return _unique_paths(paths)


def _receipt(store: ArtifactStore, scope: dict, run_id: str, result: dict | None) -> dict:
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


def _write_receipt(path: Path | None, store: ArtifactStore, scope: dict | None,
                   run_id: str, result: dict | None) -> None:
    if path is not None and scope is not None:
        write_json_atomic(path, _receipt(store, scope, run_id, result))


def _condition_action(session, *, script: Path, arguments: Mapping[str, Any],
                      limits: Mapping[str, Any], source_records: list[dict]) -> dict:
    package = session.declare_file(session.input_dir/'condition_package.json', 'required_evidence')
    write_json_atomic(package, dict(run_dir=str(session.run_dir), artifact_run_dir=str(session.artifact_run_dir),
        input_dir=str(session.input_dir), result_dir=str(session.result_dir), log_dir=str(session.log_dir),
        run_config=str(session.run_config), summary=str(session.run_dir/'summary.json')))
    session.add_input('condition_package', file_record(package, 'required_evidence'))
    argv = ['-NoProfile', '-NonInteractive', '-File', str(script), '-PackagePath', str(package)]
    for name, value in arguments.items():
        if value is None or value == '':
            continue
        argv.extend(['-'+name, str(value)])
    try:
        session.run_process('condition_action', executable=session.context.powershell_executable,
            arguments=argv, role='GATE', stage='mr_native_condition', limits=limits,
            immutable_input_records=[file_record(script, 'required_evidence'),
                file_record(package, 'required_evidence'), *source_records])
    except ProcessExecutionError:
        summary = _read_json(session.artifact_run_dir/'summary.json')
        if summary.get('status') != 'failed':
            raise
        session.declare_file(session.artifact_run_dir/'summary.json', 'required_evidence')
        return dict(status='failed', summary=summary, output_paths=[session.artifact_run_dir/'summary.json'],
            required_output_paths=[session.artifact_run_dir/'summary.json'], retention_preserve_paths=[],
            manifest_extra_fields={})
    summary_path = session.declare_file(session.artifact_run_dir/'summary.json', 'required_evidence')
    summary = _read_json(summary_path)
    return dict(status='success', summary=summary, output_paths=[summary_path],
        required_output_paths=[summary_path], retention_preserve_paths=[], manifest_extra_fields={})


def run_native_condition(context: ExecutionContext, *, artifact_store: ArtifactStore,
                         condition_path: Path, context_path: Path, composition_plan_path: Path,
                         run_id: str, artifact_root: Path, local_scope_path: Path | None = None,
                         receipt_path: Path | None = None, **reuse: Any) -> dict:
    """Run one real MR condition; existing scientific children retain their roots."""
    stage, policy = read_stage_policy(context, 'mr_native_condition')
    primary = _unique_paths([condition_path, context_path, composition_plan_path,
                             *([local_scope_path] if local_scope_path is not None else [])])
    script = _resource('native_candidate_condition_action.ps1')
    context_values = _context_sources(Path(context_path).resolve(strict=True))
    reuse_paths = [Path(value) for value in reuse.values() if isinstance(value, (str, Path)) and value]
    protected = _unique_paths([*primary, *context_values, *reuse_paths])
    records = [file_record(path, 'required_evidence') for path in primary]
    budget = stage['limits']['transient_run_directory_bytes']
    scope = None
    try:
        with ExitStack() as guards:
            for record in records:
                guards.enter_context(guarded_file_identity(Path(record['path']), expected_bytes=record['bytes'],
                                                           expected_sha256=record['sha256']))
            with standalone_native_store(artifact_store, task_key='mr-native-condition:'+run_id,
                                         budget=budget) as scope:
                arguments = dict(ConditionPath=primary[0], ContextPath=primary[1], RunId=run_id,
                    WorkspaceRoot=context.workspace, ArtifactRoot=Path(artifact_root).absolute(),
                    CompositionPlanPath=primary[2], PythonExe=context.python_executable,
                    StoreRoot=artifact_store.root, SimionExe=context.tools.get('simion'),
                    LocalScopePath=primary[3] if len(primary) > 3 else None,
                    **{''.join(part.title() for part in name.split('_')): value
                       for name, value in reuse.items()})
                result = run_managed_stage(context, descriptor=dict(project=_PROJECT,
                    mode='native_candidate_single_condition', software=_SOFTWARE), run_id=run_id,
                    payload=dict(store_managed=True, legacy_science_artifact_root=str(Path(artifact_root).absolute())),
                    committed_new_bytes=budget, commitment_inputs=[policy,
                        file_record(script, 'required_evidence'), *records], retention=stage['artifact_retention'],
                    expected_operation_ids=['condition_action'], operation_dependencies={},
                    action=partial(_condition_action, script=script, arguments=arguments,
                                   limits=stage['limits'], source_records=records),
                    action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
                    protected_paths=protected, use_short_execution_path=True,
                    completion_api=no_particle_batch_completion_api, artifact_store=artifact_store)
                scope['reported_status'] = result['status']
                _write_receipt(receipt_path, artifact_store, scope, run_id, result)
            return _receipt(artifact_store, scope, run_id, result)
    except BaseException:
        _write_receipt(receipt_path, artifact_store, scope, run_id, None)
        raise


def _campaign_action(session, *, script: Path, arguments: Mapping[str, Any],
                     limits: Mapping[str, Any], source_records: list[dict], checkpoint: Path) -> dict:
    package = session.declare_file(session.input_dir/'campaign_package.json', 'required_evidence')
    write_json_atomic(package, dict(run_dir=str(session.run_dir), artifact_run_dir=str(session.artifact_run_dir),
        input_dir=str(session.input_dir), result_dir=str(session.result_dir), log_dir=str(session.log_dir),
        run_config=str(session.run_config), summary=str(session.run_dir/'summary.json')))
    session.add_input('campaign_package', file_record(package, 'required_evidence'))
    argv = ['-NoProfile', '-NonInteractive', '-File', str(script), '-PackagePath', str(package)]
    for name, value in arguments.items():
        if value is None or value == '':
            continue
        argv.extend(['-'+name, str(value)])
    failed = None
    try:
        session.run_process('campaign_action', executable=session.context.powershell_executable,
            arguments=argv, role='GATE', stage='mr_native_campaign', limits=limits,
            immutable_input_records=_unique_records([file_record(script, 'required_evidence'),
                file_record(package, 'required_evidence'), *source_records]))
    except ProcessExecutionError as failure:
        failed = failure
    if not checkpoint.is_file():
        if failed is not None:
            stderr = session.artifact_run_dir/'logs/operation_0001.stderr.log'
            if stderr.is_file():
                failed.add_note(stderr.read_text(encoding='utf-8', errors='replace')[-4000:])
            raise failed
        raise FileNotFoundError('campaign did not publish its checkpoint: '+str(checkpoint))
    state = _read_json(checkpoint)
    outputs = []
    for name, source in (('campaign_checkpoint.json', checkpoint),
                         ('campaign_comparison.json', Path(state.get('comparison_path', '')))):
        if source.is_file():
            target = session.declare_file(session.result_dir/name, 'required_evidence')
            target.write_bytes(source.read_bytes())
            outputs.append(target)
    summary_path = session.declare_file(session.artifact_run_dir/'summary.json', 'required_evidence')
    status = 'failed' if failed is not None else 'success'
    summary = dict(schema_version=1, role='mrtof_native_candidate_campaign_summary', status=status,
        campaign_status=state.get('status'), condition_count=len(state.get('conditions', [])),
        conditions=[dict(ordinal=row.get('ordinal'), terminal_state=row.get('terminal_state'),
            attempt_count=row.get('attempt_count'), run_manifest=row.get('run_manifest'),
            workflow_outcome=row.get('workflow_outcome')) for row in state.get('conditions', [])])
    if failed is not None:
        summary['failure_reason'] = str(failed)
    write_json_atomic(summary_path, summary)
    outputs.append(summary_path)
    return dict(status=status, summary=summary, output_paths=outputs, required_output_paths=outputs,
        retention_preserve_paths=[], manifest_extra_fields={})


def run_native_campaign(context: ExecutionContext, *, artifact_store: ArtifactStore, campaign_path: Path,
                        checkpoint_path: Path, condition_context_path: Path, composition_plan_path: Path,
                        artifact_root: Path, local_scope_path: Path | None = None,
                        condition_runner_path: Path | None = None, initial_provider_reuse_map_path: Path | None = None,
                        condition_reuse_map_path: Path | None = None, campaign_stamp: str | None = None,
                        simion_exe: Path | None = None, receipt_path: Path | None = None) -> dict:
    """Run or resume the ordered campaign; the first failed condition stops dispatch."""
    stage, policy = read_stage_policy(context, 'mr_native_campaign')
    script = _resource('native_candidate_campaign_action.ps1')
    runner = Path(condition_runner_path).resolve(strict=True) if condition_runner_path else Path(__file__).resolve()
    primary = [campaign_path, condition_context_path, composition_plan_path, script, runner]
    optional = [local_scope_path, initial_provider_reuse_map_path, condition_reuse_map_path]
    primary.extend(value for value in optional if value is not None)
    sources = _unique_paths(primary)
    records = [file_record(path, 'required_evidence') for path in sources]
    checkpoint = Path(checkpoint_path).absolute()
    budget = stage['limits']['transient_run_directory_bytes']
    campaign_run_id = _campaign_run_id(checkpoint, campaign_stamp)
    scope = None
    try:
        with ExitStack() as guards:
            for record in records:
                guards.enter_context(guarded_file_identity(Path(record['path']), expected_bytes=record['bytes'],
                                                           expected_sha256=record['sha256']))
            with standalone_native_store(artifact_store, task_key='mr-native-campaign:'+campaign_run_id,
                                         budget=budget) as scope:
                arguments = dict(CampaignPath=Path(campaign_path).resolve(), CheckpointPath=checkpoint,
                    WorkspaceRoot=context.workspace, ArtifactRoot=_legacy_artifact_root(Path(condition_context_path).resolve()),
                    ConditionRunnerPath=Path(condition_runner_path).resolve() if condition_runner_path else None,
                    ConditionContextPath=Path(condition_context_path).resolve(),
                    CompositionPlanPath=Path(composition_plan_path).resolve(), LocalScopePath=local_scope_path,
                    InitialProviderReuseMapPath=initial_provider_reuse_map_path,
                    ConditionReuseMapPath=condition_reuse_map_path, CampaignStamp=campaign_stamp,
                    PythonExe=context.python_executable, StoreRoot=artifact_store.root, SimionExe=simion_exe,
                    StagePolicyPath=context.stage_policy_path)
                result = run_managed_stage(context, descriptor=dict(project=_PROJECT,
                    mode='native_candidate_campaign', software=_SOFTWARE),
                    run_id=campaign_run_id, payload=dict(store_managed=True),
                    committed_new_bytes=budget, commitment_inputs=[policy, *records],
                    retention=stage['artifact_retention'], expected_operation_ids=['campaign_action'],
                    operation_dependencies={}, action=partial(_campaign_action, script=script, arguments=arguments,
                        limits=stage['limits'], source_records=records, checkpoint=checkpoint),
                    action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
                    protected_paths=sources, use_short_execution_path=True,
                    completion_api=no_particle_batch_completion_api, artifact_store=artifact_store)
                scope['reported_status'] = result['status']
                _write_receipt(receipt_path, artifact_store, scope, campaign_run_id, result)
            return _receipt(artifact_store, scope, campaign_run_id, result)
    except BaseException:
        _write_receipt(receipt_path, artifact_store, scope, campaign_run_id, None)
        raise


def _campaign_run_id(checkpoint: Path, stamp: str | None) -> str:
    from datetime import datetime
    from uuid import uuid4
    selected = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
    return selected+'__analysis__python__mrtof-native-campaign__'+uuid4().hex[:12]


def recover_native_condition_publication(*, store: ArtifactStore, store_run_id: str,
                                         context: ExecutionContext, stage_asset_id: str | None = None) -> dict:
    """Use the common stopped-stage and Store publication recovery only."""
    stage = (recover_managed_native_store_stage(store, stage_asset_id, context=context)
             if stage_asset_id is not None else False)
    run = store.recover_run_publication(store_run_id)
    return dict(stage_recovered=stage, run_recovered=run, run_status=store.run_status(store_run_id))


def _context(arguments) -> ExecutionContext:
    powershell = arguments.powershell_exe
    policy = arguments.stage_policy
    if policy is None:
        policy = Path(str(files('msplatform.components.multi_reflection_tof')
                        .joinpath('config/native_candidate_store_policy.json')))
    simion = Path(arguments.simion_exe).absolute() if arguments.simion_exe else Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'SIMION-2020/simion.exe'
    workspace = Path(arguments.workspace_root).absolute()
    return ExecutionContext(workspace=workspace, python_executable=Path(sys.executable).resolve(),
        powershell_executable=Path(powershell).resolve(), tools={'simion': simion.absolute()},
        host_state_path=workspace/'artifacts/platform/host_resources.sqlite3', policy_path=resource_path('host_resource_policy.json'),
        stage_policy_path=policy.absolute())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='action', required=True)
    condition = subparsers.add_parser('condition')
    condition.add_argument('--condition-path', type=Path, required=True)
    condition.add_argument('--context-path', type=Path, required=True)
    condition.add_argument('--composition-plan-path', type=Path, required=True)
    condition.add_argument('--local-scope-path', type=Path)
    condition.add_argument('--run-id', required=True)
    condition.add_argument('--receipt-path', type=Path)
    condition.add_argument('--provider-reuse-path', type=Path)
    condition.add_argument('--stripe-reuse-run-manifest', type=Path)
    condition.add_argument('--continuation-reuse-run-manifest', type=Path)
    condition.add_argument('--candidate-reuse-run-manifest', type=Path)
    condition.add_argument('--qualified-workpoint-run-path', type=Path)
    condition.add_argument('--accelerator-runtime-checkpoint', type=Path)
    condition.add_argument('--workpoint-resume-initial-manifest', type=Path)
    condition.add_argument('--workpoint-resume-parent-checkpoint', type=Path)
    condition.add_argument('--workpoint-resume-successful-child-manifest', type=Path)
    condition.add_argument('--artifact-root', type=Path)
    campaign = subparsers.add_parser('campaign')
    campaign.add_argument('--campaign-path', type=Path, required=True)
    campaign.add_argument('--checkpoint-path', type=Path, required=True)
    campaign.add_argument('--condition-context-path', type=Path, required=True)
    campaign.add_argument('--composition-plan-path', type=Path, required=True)
    campaign.add_argument('--local-scope-path', type=Path)
    campaign.add_argument('--condition-runner-path', type=Path)
    campaign.add_argument('--initial-provider-reuse-map-path', type=Path)
    campaign.add_argument('--condition-reuse-map-path', type=Path)
    campaign.add_argument('--campaign-stamp')
    campaign.add_argument('--receipt-path', type=Path)
    campaign.add_argument('--artifact-root', type=Path)
    for sub in (condition, campaign):
        sub.add_argument('--workspace-root', type=Path, required=True)
        sub.add_argument('--store-root', type=Path, required=True)
        sub.add_argument('--powershell-exe', required=True)
        sub.add_argument('--stage-policy', type=Path)
        sub.add_argument('--simion-exe')
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    context = _context(args)
    store = ArtifactStore(args.store_root.absolute())
    common = dict(context=context, artifact_store=store, artifact_root=args.artifact_root,
        local_scope_path=args.local_scope_path, receipt_path=args.receipt_path)
    if args.action == 'condition':
        common['artifact_root'] = _legacy_artifact_root(args.context_path)
        names = ('provider_reuse_path', 'stripe_reuse_run_manifest', 'continuation_reuse_run_manifest',
            'candidate_reuse_run_manifest', 'qualified_workpoint_run_path', 'accelerator_runtime_checkpoint',
            'workpoint_resume_initial_manifest', 'workpoint_resume_parent_checkpoint',
            'workpoint_resume_successful_child_manifest')
        reuse = {name: getattr(args, name) for name in names if getattr(args, name) is not None}
        result = run_native_condition(condition_path=args.condition_path, context_path=args.context_path,
            composition_plan_path=args.composition_plan_path, run_id=args.run_id, **common, **reuse)
    else:
        result = run_native_campaign(campaign_path=args.campaign_path, checkpoint_path=args.checkpoint_path,
            condition_context_path=args.condition_context_path, composition_plan_path=args.composition_plan_path,
            condition_runner_path=args.condition_runner_path,
            initial_provider_reuse_map_path=args.initial_provider_reuse_map_path,
            condition_reuse_map_path=args.condition_reuse_map_path, campaign_stamp=args.campaign_stamp,
            simion_exe=Path(args.simion_exe).absolute() if args.simion_exe else None, **common)
    print(json.dumps(result, default=str, allow_nan=False))
    return 0 if result.get('status') == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
