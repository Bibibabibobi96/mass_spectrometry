"""SFI frontend scientific projection under its existing caller-owned PS capacity loop.

The outer research owner retains admission, pressure recovery and accounting.
This module selects through the existing PA manager once; its worker rechecks
that actual selection before protected work. It creates no owner or lease.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from uuid import uuid4

from msplatform.backends.simion import pa_family_cache as cache
from msplatform.backends.simion.field_audit import reusable_audit
from msplatform.backends.simion.field_bank import field_bank
from msplatform.backends.simion.field_identity import working_point_member_id
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.inputs import freeze_file
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from .field_plan import build_field_plan, bind_parent_fields

_RESOURCE_NAMES = dict(operating_builder='build_dirichlet_patch_operating_pa.lua',
    exporter='export_detached_standalone_pa.lua', verifier='audit_frontend_working_fields.lua')


def prepare_stage(prepared: Path, executable: Path, run_directory: Path) -> dict:
    """Project the actual frozen scientific request without any cache decision."""
    prepared, run = Path(prepared).resolve(), Path(run_directory).resolve()
    if prepared != run / 'inputs' or not (run / 'run_config.json').is_file():
        raise ValueError('Frontend producer requires its original managed inputs')
    bundle = build_field_plan(prepared, Path(executable))
    design_path = prepared / 'frontend_field_design.json'
    design = json.loads(design_path.read_text(encoding='utf-8-sig'))
    resources = {}
    for name, filename in _RESOURCE_NAMES.items():
        destination = prepared / 'frontend_field_resources' / filename
        source = native_resource_path(filename)
        if destination.exists():
            if file_sha256(destination) != file_sha256(source):
                raise ValueError('Frozen frontend native resource differs')
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            freeze_file(source, destination)
        resources[name] = file_record(destination, 'required_evidence')
    authority = bundle['domains'][0]['members'][0]['identity']
    tool = {name: copy.deepcopy(authority[name]) for name in ('simion_identity', 'builder_identity')}
    provenance_path = prepared / 'source_provenance.json'
    provenance = (json.loads(provenance_path.read_text(encoding='utf-8-sig'))
                  if provenance_path.exists() else {'input_records': {}})
    request_path = prepared / 'request.json'
    request = json.loads(request_path.read_text(encoding='utf-8-sig')) if request_path.exists() else {}
    handoffs = {}
    for index, row in enumerate(request.get('continuation', {}).get('frontend_field_transactions', []), 1):
        records = provenance['input_records']
        handoffs[row['domain_id'] + '/' + row['member_id']] = dict(schema_version=1,
            transaction_record=records[f'continuation_field_transaction_{index:03d}'],
            predecessor_manifest=records['continuation_parent_manifest'],
            stopped_receipt=records['continuation_stopped_receipt'])
    return dict(bundle=bundle, field_plan=dict(field_design=design), tool_identity=tool,
        design_record=file_record(design_path, 'required_evidence'), resources=resources,
        producer_manifest_record=provenance['input_records'].get('frontend_fields_manifest'),
        handoffs=handoffs, run_directory=str(run))



def _verify_stage(stage: dict) -> None:
    run = Path(stage['run_directory']).resolve()
    record = stage['design_record']
    if Path(record['path']).resolve() != run / 'inputs/frontend_field_design.json':
        raise ValueError('Frontend stage design is not its original frozen input')
    verify_record('frontend field design', record)
    if json.loads(Path(record['path']).read_text(encoding='utf-8-sig')) != stage['field_plan']['field_design']:
        raise ValueError('Frontend stage projection differs from its frozen scientific design')


def domain_members(stage: dict, domain_index: int, completed_domains: list[dict]) -> dict:
    """Bind actual completed same-member parents in the declared domain order."""
    _verify_stage(stage)
    declared = stage['bundle']['domains']
    if (type(domain_index) is not int or not 0 <= domain_index < len(declared)
            or not isinstance(completed_domains, list) or len(completed_domains) != domain_index
            or [row['domain_id'] for row in completed_domains] != [row['domain_id'] for row in declared[:domain_index]]):
        raise ValueError('Frontend domain requires its explicit completed predecessor receipts')
    domain = copy.deepcopy(declared[domain_index])
    parents, parent_sources = {}, {}
    if domain['domain_id'] == 'entrance_refinement':
        expected = {row['member_id'] for row in declared[0]['members']}
        rows = completed_domains[0]['working_points']
        if len(rows) != len(expected) or {working_point_member_id(row) for row in rows} != expected:
            raise ValueError('Frontend fine domain requires every actual same-member parent')
        parents = {working_point_member_id(row): dict(cache_key=row['cache_key'], record=row) for row in rows}
        for member in declared[0]['members']:
            source = copy.deepcopy(member.get('frozen_field_source'))
            if source is not None:
                source['producer_manifest_record'] = stage['producer_manifest_record']
            parent_sources[member['member_id']] = source
        domain = bind_parent_fields(domain, parents)
    result = []
    for member in domain['members']:
        merged = dict(domain, **member)
        merged.pop('members', None)
        source = merged.get('frozen_field_source')
        if source is not None:
            source['producer_manifest_record'] = stage['producer_manifest_record']
        if parents:
            merged.update(published_parent=parents[member['member_id']],
                          published_parent_source=parent_sources[member['member_id']])
        result.append(merged)
    return dict(domain_id=domain['domain_id'], members=result)


def assess_member(stage: dict, member: dict, cache_root: Path) -> dict:
    """Select once using the real PA manager; bind metadata for worker replay."""
    _verify_stage(stage)
    verifier = stage['resources']['verifier']
    verify_record('frontend verifier', verifier)
    source = member.get('frozen_field_source')
    identity = source['identity'] if source else member['identity']
    key = source['cache_key'] if source else member['cache_key']
    selection = None
    member = copy.deepcopy(member)
    if source:
        generation = Path(source['generation_directory'])
    else:
        identity_path = Path(stage['run_directory']) / 'inputs' / (member['domain_id'] + '_' + member['member_id'] + '_cache_identity.json')
        write_json_atomic(identity_path, identity)
        member['identity_record'] = file_record(identity_path, 'required_evidence')
        probe = cache.probe_pa_family_cache(Path(cache_root), identity, expected_filenames=member['filenames'])
        if probe.disposition not in {cache.CacheDisposition.HIT, cache.CacheDisposition.MISS}:
            raise cache.PAFamilyCacheError('Frontend member cache is not reusable: ' + str(probe.detail))
        generation = probe.generation_directory
        key_root = Path(cache_root) / key
        metadata = dict(pointer=file_record(key_root / cache.POINTER_NAME, 'required_evidence'),
            transaction=file_record(Path(cache_root) / cache.TRANSACTION_DIRECTORY / key / cache.TRANSACTION_NAME,
                                    'required_evidence'))
        if generation is not None:
            metadata['generation'] = file_record(generation / cache.MANIFEST_NAME, 'required_evidence')
        selection = dict(probe=dict(disposition=probe.disposition.value, cache_key=key,
            generation_directory=str(generation) if generation else None, detail=probe.detail), metadata=metadata)
    audit = reusable_audit(member, generation, Path(verifier['path'])) if generation else None
    if selection is not None:
        selection.update(verifier_record=verifier, audit_record=audit)
    cells = member['grid'][0] * member['grid'][1] * member['grid'][2]
    run = Path(stage['run_directory'])
    raw = run / 'simion/frontend_working_fields' / (member['domain_id'] + '_audit_geometry') / 'frontend.pa#'
    prefix = member['domain_id'] + '_' + member['member_id']
    scratch = (Path(cache_root) / cache.TRANSACTION_DIRECTORY / key / 'build-scratch'
               if generation is None else run / 'logs' / ('frontend_' + prefix) / 'audit')
    payload = Path(cache_root) / cache.TRANSACTION_DIRECTORY / key / 'payload' if generation is None else generation
    native_paths = [raw.parent, raw, raw.with_suffix('.gem'), scratch, payload,
        scratch / 'working.pa0', payload / member['filenames'][0],
        *[Path(row['path']) for row in stage['resources'].values()]]
    if member.get('published_parent') is not None:
        native_paths.append(Path(member['published_parent']['record']['path']))
    return dict(member=member, selection=selection, audit_record=audit, native_paths=list(map(str, native_paths)),
        resource_stage='prepare' if source or generation is not None else 'pa_refine',
        # The outer original owner applies these established floors with its
        # real pressure-recovery callback before the worker can create bytes.
        required_extra_bytes=(cells * 24 if not source and generation is None else cells * 8 if audit is None else 0),
        key_bytes_before=cache._key_root_bytes(Path(cache_root) / key) if not source else 0)


def member_parameters(stage: dict, assessment: dict, *, cache_root: Path, capacity_session: dict,
                      reserved_run_payload_bytes: int, native_path_projection: dict,
                      raw_geometry_record: dict | None = None) -> dict:
    """Freeze the actual selection and original-owner authority for one worker."""
    _verify_stage(stage)
    member = assessment['member']
    domain, member_id = member['domain_id'], member['member_id']
    run = Path(stage['run_directory'])
    prefix = domain + '_' + member_id + '_' + uuid4().hex
    resources = {name: row['path'] for name, row in stage['resources'].items()}
    for row in stage['resources'].values():
        verify_record('frontend native resource', row)
    handoff = copy.deepcopy(stage['handoffs'].get(domain + '/' + member_id))
    if handoff is not None:
        handoff.update(capacity_lease_id=capacity_session['lease_id'], capacity_lease_owner=capacity_session['owner'])
    parameters = dict(field_plan=stage['field_plan'], domain_id=domain, member_id=member_id,
        tool_identity=stage['tool_identity'], raw_geometry_record=raw_geometry_record,
        resources=resources, cache_root=str(cache_root), producer_run_config=str(run / 'run_config.json'),
        capacity_lease_id=capacity_session['lease_id'], capacity_lease_owner=capacity_session['owner'],
        run_directory=str(run), log_directory=str(run / 'logs' / ('frontend_' + prefix)),
        receipt_path=str(run / 'results' / ('frontend_' + prefix + '.json')),
        published_parent=member.get('published_parent'),
        published_parent_source=member.get('published_parent_source'), producer_handoff=handoff,
        capacity_session=capacity_session, reserved_run_payload_bytes=reserved_run_payload_bytes,
        native_path_projection=native_path_projection, cache_selection=assessment['selection'],
        published_pin_reason='Retain standalone frontend fields required by saved instrument workbenches.')
    if raw_geometry_record is None:
        parameters.update(gem_geometry_record=file_record(run / 'inputs' / member['gem_filename'], 'required_evidence'),
            raw_geometry_path=str(run / 'simion/frontend_working_fields' / (domain + '_audit_geometry') / 'frontend.pa#'))
    if member.get('frozen_field_source'):
        parameters['frozen_field_source'] = member['frozen_field_source']
        parameters['source_audit_record'] = assessment['audit_record']
    return parameters


def _receipt_record(record):
    return {name: record[name] for name in ('path', 'bytes', 'sha256')}


def member_record(member: dict, report: dict) -> dict:
    """Project the unchanged schema3 member evidence from actual worker output."""
    if report.get('status') != 'success':
        raise ValueError('Frontend member worker did not complete')
    point = member['working_points'][0]
    source = member.get('frozen_field_source')
    generation = Path(report['generation_directory'])
    manifest = json.loads((generation / cache.MANIFEST_NAME).read_text(encoding='utf-8-sig'))
    rows = [row for row in manifest['files'] if row['name'] == point['filename']]
    if len(rows) != 1:
        raise ValueError('Published member absent or duplicated')
    expected = rows[0]
    if (Path(report['record']['path']) != generation / expected['name']
            or report['record']['bytes'] != expected['bytes'] or report['record']['sha256'] != expected['sha256']):
        raise ValueError('Worker member differs from actual published inventory')
    record = dict(kind=point['kind'], path=str(generation / expected['name']), bytes=expected['bytes'],
        sha256=expected['sha256'], read_only=True, cache_key=report['cache_key'], generation_directory=str(generation),
        cache_filenames=[row['name'] for row in manifest['files']],
        source_schema_version=source['source_schema_version'] if source else 3,
        cache_identity_record=_receipt_record(file_record(Path(source['identity_path']) if source else Path(member['identity_record']['path']))),
        audit_record=_receipt_record(report['audit_record']), refine_performed=any(
            row['stage'] == 'pa_refine' for row in report['native_operations']))
    if 'working_point_id' in point:
        record['working_point_id'] = point['working_point_id']
    if source:
        record['source'] = dict(schema_version=source['source_schema_version'], cache_key=report['cache_key'],
            generation_directory=str(generation))
    return record


def finish_stage(stage: dict, domains: list[dict]) -> dict:
    """Publish the same small field-bank and schema3 receipt, never a new owner."""
    _verify_stage(stage)
    run = Path(stage['run_directory'])
    if [row['domain_id'] for row in domains] != [row['domain_id'] for row in stage['bundle']['domains']]:
        raise ValueError('Frontend completed domains differ from its frozen plan')
    bank = run / 'simion/frontend_working_fields/standalone_field_bank.json'
    write_json_atomic(bank, field_bank(stage['field_plan']['field_design'], [row['domain_id'] for row in domains]))
    receipt = run / 'inputs/frontend_working_field_stage_receipt.json'
    document = dict(schema_version=3, role='single_reflection_frontend_working_fields', status='success',
        domains=domains, field_bank_record=_receipt_record(file_record(bank)), fly_performed=False,
        validation_scope='native_grid_and_physical_metal_voltage_samples_only__not_field_convergence')
    if 'rf_reference_voltage_v' in stage['bundle']:
        document['rf_reference_voltage_v'] = stage['bundle']['rf_reference_voltage_v']
    write_json_atomic(receipt, document)
    records = [record for domain in domains for record in domain['working_points']]
    return dict(field_paths=[row['path'] for row in records], field_bank=str(bank), cache_receipt=str(receipt),
        cache_keys=list(dict.fromkeys(row['cache_key'] for row in records)))


def main() -> None:
    """Private transport for the existing PS owner, not a standalone run owner."""
    import sys
    if len(sys.argv) != 3:
        raise ValueError('Frontend field transport requires action and frozen request')
    action, path = sys.argv[1], Path(sys.argv[2])
    from msplatform.io.file_identity import guarded_file_identity
    with guarded_file_identity(path):
        request = json.loads(path.read_text(encoding='utf-8-sig'))
        expected = request.pop('implementation_record')
        if Path(expected['path']).resolve() != Path(__file__).resolve():
            raise ValueError('Frontend coordinator is not the selected frozen implementation')
        verify_record('frozen frontend coordinator', expected)
        if action == 'prepare':
            result = prepare_stage(Path(request['prepared']), Path(request['executable']), Path(request['run_directory']))
        elif action == 'domain':
            result = domain_members(request['stage'], request['domain_index'], request['completed_domains'])
        elif action == 'assess':
            result = assess_member(request['stage'], request['member'], Path(request['cache_root']))
        elif action == 'parameters':
            result = member_parameters(request.pop('stage'), request.pop('assessment'), **request)
        elif action == 'record':
            result = member_record(request['member'], request['report'])
        elif action == 'finish':
            result = finish_stage(request['stage'], request['domains'])
        else:
            raise ValueError('Unknown frontend field transport action')
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
