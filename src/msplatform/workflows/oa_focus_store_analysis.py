"""Publish focus analysis from a complete, sealed public native Store run."""
from __future__ import annotations

import base64
from contextlib import ExitStack, contextmanager
import hashlib
import json

from msplatform.backends.simion.oa_focus_model_projection import build_focus_model, focus_model_facts, validate_focus_authority
from msplatform.backends.simion.tracking_execution import _birth_states
from msplatform.components.orthogonal_accelerator.focus_result import analyze_focus_result
from msplatform.execution.owner import store_growth_accountant
from msplatform.io.file_identity import guarded_file_identity
from msplatform.results.particle_data import read_particle_data

_NAMES = ('resolved.json', 'oa_focus_campaign.json', 'oa_focus_component_contract.json',
          'oa_focus_model.json', 'oa_focus_authority.json', 'oa_focus_source_packet.json',
          'oa_focus_projected_birth_rows.json', 'initial_states.parquet', 'terminal_states.parquet',
          'events.parquet', 'trajectories.h5', 'execution.json')


def publish_focus_analysis(*, store, source_run_id: str, budget_bytes: int,
                           exit_surface_id: str, focus_surface_id: str) -> dict:
    """Cold-read one completed focus run and publish its derived analysis.

    The originating run and exact original birth cohort remain the authority.
    No vendor process, re-sampling, or cache-derived native evidence is used.
    """
    if (exit_surface_id, focus_surface_id) != ('oa_focus_exit', 'oa_focus_plane'):
        raise ValueError('focus surfaces must match the native producer bindings')
    if type(budget_bytes) is not int or budget_bytes <= 0:
        raise ValueError('budget_bytes must be a positive integer')
    with ExitStack() as stack:
        root = store.inspect_run(source_run_id)
        manifest_path = root / 'run_manifest.json'
        stack.enter_context(guarded_file_identity(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding='utf8'))
        if manifest.get('execution_status') != 'succeeded':
            raise ValueError('focus analysis requires a successful source run')
        records = manifest['files']
        for name in _NAMES:
            if name not in records:
                raise ValueError('focus source run lacks required evidence: ' + name)
            record = records[name]
            stack.enter_context(guarded_file_identity(root / name, expected_bytes=record['bytes'],
                                                     expected_sha256=record['sha256']))
        # Recheck the Store's own indexed manifest after write-excluding all inputs.
        if store.inspect_run(source_run_id) != root:
            raise ValueError('focus source run identity changed')
        def load(name):
            return json.loads((root / name).read_text(encoding='utf8'))
        recipe, campaign, contract = (load(name) for name in _NAMES[:3])
        model, authority, packet, rows = (load(name) for name in _NAMES[3:7])
        snapshots = recipe['resource_snapshots']
        for name, record_name in (('oa_focus_campaign.json', 'campaign'),
                                  ('oa_focus_component_contract.json', 'component_contract')):
            payload = (root / name).read_bytes()
            snapshot = snapshots[name]
            record = authority[record_name]
            if (base64.b64decode(snapshot['bytes_base64'], validate=True) != payload
                    or snapshot['sha256'].upper() != records[name]['sha256'].upper()
                    or record['bytes'] != len(payload)
                    or record['sha256'].upper() != records[name]['sha256'].upper()):
                raise ValueError('focus original source identity differs from the sealed Study')
        validate_focus_authority(authority, campaign=campaign, component_contract=contract, model_document=model)
        projection = build_focus_model(campaign, component_contract=contract,
            campaign_record=authority['campaign'], contract_record=authority['component_contract'],
            geometry_profile=authority['geometry_profile'], mesh_mm_per_gu=authority['mesh_mm_per_gu'],
            clock=authority['clock'])
        study = recipe['study']['document']
        if (study['component_requests'] != projection['component_requests']
                or study['recipe'] != projection['recipe']
                or study['numerics']['geometry'] != projection['geometry_numerics']
                or study['drive']['groups'] != projection['drive']['groups']
                or study['release']['release_spec'] != campaign['release_spec']
                or packet['realization']['spec'] != campaign['release_spec']):
            raise ValueError('focus model or birth author differs from the sealed Study')
        release = study['release']
        if (packet.get('clock') != release['clock']
                or packet.get('realization', {}).get('time_mapping', {}).get('instrument_origin_us') != release['instrument_origin_us']
                or any(row.get('species_id') != release['species_id']
                       or row.get('source_component_id') != release['source_component_id'] for row in packet['rows'])):
            raise ValueError('focus frozen birth packet identity differs from the sealed Study')
        weights = release.get('relative_weights')
        if any(row['particle_weight'] != (1. if weights is None else weights.get(str(row['particle_id'])))
               for row in packet['rows']):
            raise ValueError('focus frozen birth weights differ from the sealed Study')
        geometry = dict(model['geometry']['frontend_geometry'], native_frame_id=model['native_frame_id'])
        calculated, _, _ = _birth_states(packet, geometry)
        if calculated != rows:
            raise ValueError('focus projected birth rows differ from the original packet and model')
        data = read_particle_data(root)
        facts = focus_model_facts(authority, campaign=campaign, component_contract=contract, model_document=model)
        result = analyze_focus_result(data, campaign=campaign, geometry_profile=authority['geometry_profile'],
            authority=authority, projected_birth_rows=calculated,
            exit_surface_id=exit_surface_id, focus_surface_id=focus_surface_id)
        run_id, work = store.begin_run()
        with store.run_writer(run_id):
            try:
                with store.reserve(budget_bytes) as reservation:
                    store.mark_running(run_id)
                    account = store_growth_accountant(store, reservation, budget_bytes, work)
                    (work / 'model_facts.json').write_text(json.dumps(facts, ensure_ascii=False, allow_nan=False,
                        indent=2, sort_keys=True) + '\n', encoding='utf8')
                    (work / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False,
                        indent=2, sort_keys=True) + '\n', encoding='utf8')
                    (work / 'provenance.json').write_text(json.dumps(dict(schema_version=1,
                        role='oa_focus_analysis_provenance', source_run_id=source_run_id,
                        source_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                        exit_surface_id=exit_surface_id, focus_surface_id=focus_surface_id), indent=2) + '\n', encoding='utf8')
                    account(work)
                    _, published = store.publish_run(work, run_id=run_id)
                return dict(run_id=run_id, path=str(published), source_run_id=source_run_id,
                            analysis=json.loads((store.inspect_run(run_id) / 'analysis.json').read_text(encoding='utf8')))
            except BaseException as failure:
                state = store.run_status(run_id)
                status = state['execution_status']
                if status == 'running' and state['publication_status'] != 'publishing':
                    store.finish_run(run_id, 'failed', reason=str(failure))
                elif status == 'queued':
                    store.set_queued_reason(run_id, str(failure))
                failure.add_note('Store run_id: ' + run_id)
                raise


def recover_focus_analysis_publication(*, store, run_id: str) -> bool:
    """Resume the Store's existing publication transaction after interruption."""
    return store.recover_run_publication(run_id)


@contextmanager
def guard_focus_analysis(*, store, run_id: str):
    """Hold one published focus analysis and its verified original run identity."""
    with ExitStack() as stack:
        root=store.inspect_run(run_id)
        manifest_path=root/'run_manifest.json'
        stack.enter_context(guarded_file_identity(manifest_path))
        manifest=json.loads(manifest_path.read_text(encoding='utf8'))
        if manifest.get('execution_status')!='succeeded':
            raise ValueError('focus analysis run did not succeed')
        for name in ('model_facts.json','analysis.json','provenance.json'):
            record=manifest['files'].get(name)
            if record is None:
                raise ValueError('focus analysis evidence is incomplete')
            stack.enter_context(guarded_file_identity(root/name,expected_bytes=record['bytes'],
                                                      expected_sha256=record['sha256']))
        if store.inspect_run(run_id)!=root:
            raise ValueError('focus analysis run identity changed')
        facts=json.loads((root/'model_facts.json').read_text(encoding='utf8'))
        analysis=json.loads((root/'analysis.json').read_text(encoding='utf8'))
        provenance=json.loads((root/'provenance.json').read_text(encoding='utf8'))
        if (facts.get('role')!='oa_focus_authenticated_model_facts'
                or analysis.get('role')!='oa_focus_si_analysis'
                or provenance.get('role')!='oa_focus_analysis_provenance'):
            raise ValueError('focus analysis evidence roles differ')
        source=store.inspect_run(provenance['source_run_id'])
        source_manifest=source/'run_manifest.json'
        stack.enter_context(guarded_file_identity(source_manifest,
            expected_bytes=source_manifest.stat().st_size,expected_sha256=provenance['source_manifest_sha256']))
        if store.inspect_run(provenance['source_run_id'])!=source:
            raise ValueError('focus original run identity changed')
        yield dict(model_facts=facts,analysis=analysis,provenance=provenance)


def run_focus_recipe(recipe_path, *, artifact_store, context, analysis_budget_bytes: int,
                     reserve_bytes=0, source_revision=None, tracking_execution=None) -> dict:
    """Run the public native Recipe once, then publish its cold-read focus analysis."""
    from .tracing import run_recipe

    if type(analysis_budget_bytes) is not int or analysis_budget_bytes <= 0:
        raise ValueError('analysis_budget_bytes must be a positive integer')
    run=run_recipe(recipe_path,artifact_root=artifact_store.root,context=context,
        high_water_bytes=artifact_store.high,low_water_bytes=artifact_store.low,safety_bytes=artifact_store.safety,
        reserve_bytes=reserve_bytes,source_revision=source_revision,tracking_execution=tracking_execution)
    result=publish_focus_analysis(store=artifact_store,source_run_id=run['run_id'],budget_bytes=analysis_budget_bytes,
        exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
    return dict(source_run=run,focus_analysis=result)


@contextmanager
def guard_focus_original_birth(*, store, analysis_run_id: str):
    """Hold the original focus birth packet and its already compiled-frame rows.

    The same immutable birth may be used by a continuous consumer; terminal
    states are not converted into a new release.
    """
    with ExitStack() as stack:
        evidence=stack.enter_context(guard_focus_analysis(store=store,run_id=analysis_run_id))
        source=store.inspect_run(evidence['provenance']['source_run_id'])
        manifest=json.loads((source/'run_manifest.json').read_text(encoding='utf8'))
        names=('oa_focus_source_packet.json','oa_focus_projected_birth_rows.json','oa_focus_model.json','oa_focus_campaign.json')
        for name in names:
            record=manifest['files'].get(name)
            if record is None:
                raise ValueError('focus original birth evidence is incomplete')
            stack.enter_context(guarded_file_identity(source/name,expected_bytes=record['bytes'],
                                                      expected_sha256=record['sha256']))
        if store.inspect_run(evidence['provenance']['source_run_id'])!=source:
            raise ValueError('focus original birth run identity changed')
        packet,rows,model,campaign=(json.loads((source/name).read_text(encoding='utf8')) for name in names)
        from msplatform.io.file_identity import canonical_json_sha256
        if (canonical_json_sha256(model)!=evidence['model_facts']['model_sha256']
                or manifest['files']['oa_focus_campaign.json']['sha256'].upper()!=evidence['model_facts']['campaign_sha256'].upper()
                or packet.get('realization',{}).get('spec')!=evidence['model_facts']['release_spec']):
            raise ValueError('focus original birth or model identity differs from analysis')
        geometry=dict(model['geometry']['frontend_geometry'],native_frame_id=model['native_frame_id'])
        projected,_,_=_birth_states(packet,geometry)
        if projected!=rows:
            raise ValueError('focus original birth projection differs')
        yield dict(packet=packet,projected_birth_rows=rows,campaign=campaign,model_facts=evidence['model_facts'],
                   analysis=evidence['analysis'],provenance=evidence['provenance'])


def initialize_focus_adjustment(*, store, base_analysis_run_id: str, maximum_trials: int) -> dict:
    """Initialize the bounded scientific decision from an authenticated source run."""
    from msplatform.components.orthogonal_accelerator.focus_voltage_adjustment import _parameters
    if type(maximum_trials) is not int or not 4 <= maximum_trials <= 20:
        raise ValueError('maximum trials must be between 4 and 20')
    with guard_focus_original_birth(store=store,analysis_run_id=base_analysis_run_id) as source:
        return dict(schema_version=1,role='oa_focus_bounded_adjustment',status='running',
            base_analysis_run_id=base_analysis_run_id,campaign_sha256=source['model_facts']['campaign_sha256'],
            model_profile_sha256=source['model_facts']['model_sha256'],maximum_trials=maximum_trials,
            records=[],next_parameters=_parameters(source['campaign']),phase='base',base_record_index=None,
            probe_relative_step=None,best_record_index=None)


def advance_focus_adjustment(*, store, state: dict, analysis_run_id: str) -> dict:
    """Advance one decision using a guarded same-birth Store analysis, without running a solver."""
    import copy
    from msplatform.components.orthogonal_accelerator.focus_voltage_adjustment import (
        _candidate_campaign, _parameters, adjustment_record_from_si, advance_adjustment_state)
    if (not isinstance(state,dict) or state.get('schema_version')!=1
            or state.get('role')!='oa_focus_bounded_adjustment' or state.get('status')!='running'
            or not isinstance(state.get('next_parameters'),dict)):
        raise ValueError('focus bounded adjustment state is invalid')
    with ExitStack() as stack:
        base=stack.enter_context(guard_focus_original_birth(store=store,analysis_run_id=state['base_analysis_run_id']))
        trial=stack.enter_context(guard_focus_original_birth(store=store,analysis_run_id=analysis_run_id))
        if (base['model_facts']['campaign_sha256']!=state.get('campaign_sha256')
                or base['model_facts']['model_sha256']!=state.get('model_profile_sha256')
                or trial['packet']!=base['packet']):
            raise ValueError('focus adjustment base or original birth identity differs')
        # The original frozen profile is carried by the source authority.
        source=store.inspect_run(base['provenance']['source_run_id'])
        manifest=json.loads((source/'run_manifest.json').read_text(encoding='utf8'))
        record=manifest['files']['oa_focus_authority.json']
        stack.enter_context(guarded_file_identity(source/'oa_focus_authority.json',expected_bytes=record['bytes'],
                                                  expected_sha256=record['sha256']))
        authority=json.loads((source/'oa_focus_authority.json').read_text(encoding='utf8'))
        profile=authority['geometry_profile']
        if (state['phase']=='base' and not state['records']
                and state['next_parameters']!=_parameters(base['campaign'])):
            raise ValueError('focus adjustment initial parameters differ from its author')
        expected=(base['campaign'] if state['phase']=='base' and not state['records'] else
                  _candidate_campaign(base['campaign'],state['next_parameters'],geometry_profile=profile))
        if trial['campaign']!=expected:
            raise ValueError('focus adjustment analysis does not match its pending authored parameters')
        record=dict(kind=state['phase'],parameters=copy.deepcopy(state['next_parameters']),
                    analysis_run_id=analysis_run_id,**adjustment_record_from_si(trial['analysis']))
        updated=advance_adjustment_state(copy.deepcopy(state),record,base['campaign'],geometry_profile=profile)
        next_campaign=None if updated['next_parameters'] is None else _candidate_campaign(
            base['campaign'],updated['next_parameters'],geometry_profile=profile)
        return dict(state=updated,next_campaign=next_campaign)


def publish_focus_adjustment_step(*, store, base_analysis_run_id: str, analysis_run_id: str,
                                  budget_bytes: int, maximum_trials: int | None = None,
                                  previous_run_id: str | None = None) -> dict:
    """Publish one bounded decision with its prior Store decision as input."""
    if type(budget_bytes) is not int or budget_bytes<=0:
        raise ValueError('budget_bytes must be a positive integer')
    with ExitStack() as stack:
        if previous_run_id is None:
            state=initialize_focus_adjustment(store=store,base_analysis_run_id=base_analysis_run_id,
                                              maximum_trials=maximum_trials)
        else:
            if maximum_trials is not None:
                raise ValueError('maximum_trials belongs only to the initial decision')
            previous=store.inspect_run(previous_run_id)
            manifest_path=previous/'run_manifest.json'
            stack.enter_context(guarded_file_identity(manifest_path))
            manifest=json.loads(manifest_path.read_text(encoding='utf8'))
            if manifest.get('execution_status')!='succeeded':
                raise ValueError('previous focus adjustment is not successful')
            for name in ('state.json','provenance.json'):
                record=manifest['files'].get(name)
                if record is None:
                    raise ValueError('previous focus adjustment evidence is incomplete')
                stack.enter_context(guarded_file_identity(previous/name,expected_bytes=record['bytes'],
                                                          expected_sha256=record['sha256']))
            if store.inspect_run(previous_run_id)!=previous:
                raise ValueError('previous focus adjustment identity changed')
            state=json.loads((previous/'state.json').read_text(encoding='utf8'))
            provenance=json.loads((previous/'provenance.json').read_text(encoding='utf8'))
            if (state.get('base_analysis_run_id')!=base_analysis_run_id
                    or provenance.get('role')!='oa_focus_adjustment_provenance'
                    or provenance.get('base_analysis_run_id')!=base_analysis_run_id):
                raise ValueError('previous focus adjustment belongs to another source')
        decision=advance_focus_adjustment(store=store,state=state,analysis_run_id=analysis_run_id)
        run_id,work=store.begin_run()
        with store.run_writer(run_id):
            try:
                with store.reserve(budget_bytes) as reservation:
                    store.mark_running(run_id)
                    for name,payload in (('state.json',decision['state']),('next_campaign.json',decision['next_campaign']),
                        ('provenance.json',dict(schema_version=1,role='oa_focus_adjustment_provenance',
                            base_analysis_run_id=base_analysis_run_id,analysis_run_id=analysis_run_id,
                            previous_run_id=previous_run_id))):
                        (work/name).write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,
                            indent=2,sort_keys=True)+'\n',encoding='utf8')
                    store_growth_accountant(store,reservation,budget_bytes,work)(work)
                    _,published=store.publish_run(work,run_id=run_id)
                return dict(run_id=run_id,path=str(published),**decision)
            except BaseException as failure:
                status=store.run_status(run_id)
                if status['execution_status']=='running' and status['publication_status']!='publishing':
                    store.finish_run(run_id,'failed',reason=str(failure))
                elif status['execution_status']=='queued':
                    store.set_queued_reason(run_id,str(failure))
                failure.add_note('Store run_id: '+run_id)
                raise


def recover_focus_adjustment_publication(*, store, run_id: str) -> bool:
    """Resume exactly one stopped decision publication using the Store journal."""
    return store.recover_run_publication(run_id)
