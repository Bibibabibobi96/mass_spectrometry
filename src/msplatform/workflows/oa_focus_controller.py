"""Public Store-managed production of one closed two-zone focus controller."""
from __future__ import annotations

from functools import partial
from importlib.resources import files
import json
from pathlib import Path

from msplatform.backends.simion.oa_focus_controller_store import run_focus_controller
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.inputs import freeze_file
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, verify_record

_RESOURCES = {'builder':'build_component_focus_pa.lua', 'exporter':'export_standalone_pa.lua',
              'verifier':'verify_component_focus_pa.lua'}


def _focus_action(session, *, plan, plan_bytes, campaign_bytes, contract_bytes, limits):
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
    output = session.declare_file(session.result_dir/'focus_controller_result.json', 'required_evidence')
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf8')
    return dict(status='success', summary=dict(role='oa_focus_controller_result',
        cache_disposition=result['cache_disposition'], native_count=result['native_count'],
        qualification='controller_only_focus_flight_pending'), output_paths=[output],
        required_output_paths=[output], retention_preserve_paths=[], manifest_extra_fields={})


def run_focus_controller_campaign(context, *, artifact_store, campaign_path: Path,
                                  mesh_mm_per_gu: list[float], run_id: str,
                                  committed_new_bytes: int) -> dict:
    """Compile the original OA campaign and build its Store controller.

    Campaign and installed provider contract remain OS-guarded through the
    existing plan compiler and publication; flight remains a separate result.
    """
    from msplatform.backends.simion.oa_focus_plan import derive
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError('focus controller requires a positive Store budget')
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
                mode='focus_controller', software=['SIMION 2020']), run_id=run_id,
            payload=dict(focus_controller_only=True), committed_new_bytes=committed_new_bytes,
            commitment_inputs=[record, contract_record, policy], retention=stage['artifact_retention'],
            expected_operation_ids=['focus_controller'], operation_dependencies={},
            action=partial(_focus_action, plan=plan, plan_bytes=plan_bytes,
                           campaign_bytes=campaign_bytes, contract_bytes=contract_bytes, limits=stage['limits']),
            action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
            artifact_store=artifact_store, completion_api=no_particle_batch_completion_api,
            use_short_execution_path=True)
