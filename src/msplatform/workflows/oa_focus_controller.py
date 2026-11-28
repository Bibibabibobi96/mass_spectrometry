"""Public Store-managed production of one closed two-zone focus controller."""
from __future__ import annotations

from functools import partial
from importlib.resources import files
import json
from pathlib import Path

from msplatform.backends.simion.oa_focus_controller_store import materialize_focus_runtime, run_focus_controller
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.inputs import freeze_file
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, verify_record

_RESOURCES = {'builder':'build_component_focus_pa.lua', 'exporter':'export_standalone_pa.lua',
              'verifier':'verify_component_focus_pa.lua'}


def _write_json(session, path: Path, value: dict) -> Path:
    target = session.declare_file(path, 'required_evidence')
    target.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf8')
    return target


def _legacy_pa_result(session, *, result: dict, plan: dict, plan_bytes: bytes,
                      resources: dict, runtime_checkpoint_path: Path | None = None) -> list[Path]:
    """Expose the original small PA/run-time contract over Store evidence."""
    if 'legacy_cache_key' not in result or 'generation_sha256' not in result:
        raise ValueError('legacy focus handoff requires a Store response-bank manifest')
    if runtime_checkpoint_path is None:
        with materialize_focus_runtime(session, asset_id=result['asset_id'], plan=plan,
                                       resources=resources) as runtime:
            controller = Path(runtime['controller']['path'])
            checkpoint = _write_json(session, session.result_dir/'accelerator_runtime_checkpoint.json', dict(
                schema_version=1, role='orthogonal_accelerator_shared_runtime_checkpoint', status='prepared',
                cache_key=result['legacy_cache_key'], generation_sha256=result['generation_sha256'],
                directory=str(controller.parent), members=[dict(name=Path(record['path']).name,
                    bytes=record['bytes']) for record in runtime['members']],
                controller_refine='solutions={0}', response_refine_performed=False,
                published_native_members_opened=False))
    else:
        checkpoint = runtime_checkpoint_path.resolve(strict=True)
        saved = json.loads(checkpoint.read_text(encoding='utf-8-sig'))
        if (saved.get('cache_key') != result['legacy_cache_key']
                or saved.get('generation_sha256') != result['generation_sha256']):
            raise ValueError('provided focus runtime checkpoint differs from the Store field identity')
        controller = Path(saved['directory']).resolve(strict=True)/'orthogonal_accelerator_focus.pa0'
    plan_output = session.declare_file(session.result_dir/'component_focus_pa_plan.json', 'required_evidence')
    plan_output.write_bytes(plan_bytes)
    pa_result = _write_json(session, session.result_dir/'component_focus_pa_result.json', dict(
        schema_version=1, role='orthogonal_accelerator_component_focus_pa_result', status='published',
        action_required='complete', disposition=result['cache_disposition'], cache_key=result['legacy_cache_key'],
        generation_sha256=result['generation_sha256'], generation_directory=result['asset_directory'],
        store_asset_id=result['asset_id'], runtime_checkpoint_path=str(checkpoint),
        runtime_controller_path=str(controller)))
    return [plan_output, pa_result, checkpoint]


def _focus_action(session, *, plan, plan_bytes, campaign_bytes, contract_bytes, limits,
                  legacy_pa_output=False, runtime_checkpoint_path=None):
    for name, data in (('campaign.json', campaign_bytes), ('component_contract.json', contract_bytes)):
        target = session.declare_file(session.input_dir/name, 'required_evidence')
        target.write_bytes(data)
        session.add_input(name.removesuffix('.json'), file_record(target, 'required_evidence'))
    plan_target = session.declare_file(session.input_dir/'focus_plan.json', 'required_evidence')
    plan_target.write_bytes(plan_bytes)
    session.add_input('focus_plan', file_record(plan_target, 'required_evidence'))
    resources = {}
    for role, name in _RESOURCES.items():
        source = native_resource_path(name)
        target = session.declare_file(session.input_dir/name, 'required_evidence')
        record = freeze_file(source, target, retention_role='required_evidence')
        record.pop('source_path', None)
        session.add_input('focus_'+role, record)
        resources[role] = target
    result = run_focus_controller(session, operation_id='focus_controller', plan=plan,
                                  resources=resources, limits=limits)
    output = _write_json(session, session.result_dir/'focus_controller_result.json', result)
    outputs = [output]
    summary = dict(role='oa_focus_controller_result', cache_disposition=result['cache_disposition'],
                   native_count=result['native_count'], qualification='controller_only_focus_flight_pending')
    if legacy_pa_output:
        outputs.extend(_legacy_pa_result(session, result=result, plan=plan, plan_bytes=plan_bytes,
                                         resources=resources, runtime_checkpoint_path=runtime_checkpoint_path))
        summary = dict(schema_version=1, role='orthogonal_accelerator_component_focus_pa', status='success',
            qualification='native_controller_plus_standalone_responses__focus_flight_pending',
            cache_key=result['legacy_cache_key'], generation_sha256=result['generation_sha256'],
            generation_directory=result['asset_directory'], store_asset_id=result['asset_id'],
            runtime_checkpoint_path=str(session.artifact_run_dir/'results/accelerator_runtime_checkpoint.json'),
            cache_policy='store_claimed_native_family__private_runtime_from_manifest_bound_standalone_responses')
    return dict(status='success', summary=summary, output_paths=outputs,
        required_output_paths=outputs, retention_preserve_paths=[], manifest_extra_fields={})


def run_focus_controller_campaign(context, *, artifact_store, campaign_path: Path,
                                  mesh_mm_per_gu: list[float], run_id: str,
                                  committed_new_bytes: int, legacy_pa_output: bool = False,
                                  runtime_checkpoint_path: Path | None = None) -> dict:
    """Compile the original OA campaign and build its Store controller.

    Campaign and installed provider contract remain OS-guarded through the
    existing plan compiler and publication; flight remains a separate result.
    The optional legacy projection preserves only the established MR handoff.
    """
    from msplatform.backends.simion.oa_focus_plan import derive
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError('focus controller requires a positive Store budget')
    if type(legacy_pa_output) is not bool:
        raise ValueError('legacy_pa_output must be Boolean')
    path = Path(campaign_path).resolve(strict=True)
    contract_path = Path(str(files('msplatform.components.orthogonal_accelerator')
                             .joinpath('component_contract.json'))).resolve(strict=True)
    record = file_record(path, 'required_evidence')
    contract_record = file_record(contract_path, 'required_evidence')
    stage, policy = read_stage_policy(context, 'oa_focus_controller')
    with guarded_file_identity(path, expected_bytes=record['bytes'], expected_sha256=record['sha256']), \
         guarded_file_identity(contract_path, expected_bytes=contract_record['bytes'],
                               expected_sha256=contract_record['sha256']):
        campaign_bytes = path.read_bytes()
        contract_bytes = contract_path.read_bytes()
        verify_record('focus campaign source', record)
        verify_record('focus component contract', contract_record)
        campaign = json.loads(campaign_bytes.decode('utf-8-sig'))
        contract = json.loads(contract_bytes.decode('utf-8-sig'))
        profile = contract['geometry_profiles'][campaign['geometry_profile_id']]
        plan = derive(path, geometry_profile=profile, mesh_mm_per_gu=mesh_mm_per_gu)
        plan_bytes = (json.dumps(plan, indent=2, allow_nan=False)+'\n').encode('utf8')
        return run_managed_stage(context, descriptor=dict(project='orthogonal_accelerator',
                mode='component_focus_pa_build' if legacy_pa_output else 'focus_controller',
                software=['SIMION 2020']), run_id=run_id,
            payload=dict(focus_controller_only=True, store_response_bank=True),
            committed_new_bytes=committed_new_bytes, commitment_inputs=[record, contract_record, policy],
            retention=stage['artifact_retention'], expected_operation_ids=['focus_controller'],
            operation_dependencies={}, action=partial(_focus_action, plan=plan, plan_bytes=plan_bytes,
                campaign_bytes=campaign_bytes, contract_bytes=contract_bytes, limits=stage['limits'],
                legacy_pa_output=legacy_pa_output, runtime_checkpoint_path=runtime_checkpoint_path),
            action_record=file_record(Path(__file__).resolve(),
                'required_evidence'), artifact_store=artifact_store,
            completion_api=no_particle_batch_completion_api, use_short_execution_path=True)
