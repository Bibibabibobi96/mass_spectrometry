"""Resolve direct working-field cache inputs; never read particle sources or PA data."""
from __future__ import annotations

import json
import math
from pathlib import Path

from common.contracts.file_identity import file_sha256, canonical_json_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from common.simion.pa_family_cache import (
    canonical_pa_family_cache_key,
    load_pa_family_cache_transaction,
    validate_pa_family_cache_generation,
)
from integrations.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
)
from integrations.runtime.single_flight_frontend import frontend_electrode_maps

KINDS = ('carrier_off', 'rf_reference', 'pulse_delta')


def working_point_member_id(point: dict) -> str:
    """Stable PA member name: labels identify repeated RF responses only."""
    kind = point.get('kind')
    member = point.get('working_point_id') or kind
    if not isinstance(member, str) or not member or (member != kind and kind != 'rf_reference'):
        raise ValueError('working point member identity is invalid')
    return member


def _physical_working_points(points: list[dict], convergence: dict) -> list[dict]:
    """Cache physics excludes instance and member labels."""
    return [dict(kind=point['kind'], electrode_voltages_v=point['electrode_voltages_v'],
                 refine_convergence_v=convergence[point['kind']]) for point in points]
AUDIT_NAME = 'frontend_working_fields_audit.json'
_SOURCE_RECEIPT = 'frontend_field_source_receipt.json'


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in '0123456789abcdefABCDEF' for ch in value):
        raise ValueError(f'{label} must be a SHA-256')
    return value.upper()


def _member_projection(identity: dict, member: dict, *, member_id: str) -> dict:
    """Project explicit historical evidence onto one unchanged physical solve."""
    result = dict(identity)
    result['geometry'] = {key: value for key, value in identity['geometry'].items() if key != 'physical_samples'}
    result['working_points'] = [member]
    result['builder_identity'] = {key: identity['builder_identity'][key] for key in ('operating_builder', 'exporter')}
    if member['kind'] != 'rf_reference':
        result.pop('rf_reference_voltage_v', None)
    boundary = identity['boundary_policy']
    if isinstance(boundary, dict):
        filename = 'frontend.' + member_id + '.pa'
        parents = [row for row in boundary['parent_working_points'] if row['name'] == filename]
        if len(parents) != 1:
            raise ValueError('fine source does not bind its same-member parent')
        result['boundary_policy'] = dict(boundary, parent_working_points=parents)
    return result


def laplace_member_identity(*, dimensions: dict, bounds_mm: dict, gem_sha256: str,
                            cell_mm_xyz: dict, instance_origin_mm: dict, surface: str,
                            boundary_policy: str | dict, point: dict,
                            refine_convergence_v: float, rf_reference_voltage_v: float | None = None) -> dict:
    """Identity of one linear working solve, independent of source and member label.

    Callers retain ownership of endpoint/geometry validation and boundary policy:
    zero Dirichlet and native zero Neumann are deliberately different operators.
    """
    identity = dict(geometry=dict(dimensions=dimensions, bounds_mm=bounds_mm), gem=gem_sha256,
        working_points=[dict(kind=point['kind'], electrode_voltages_v=point['electrode_voltages_v'],
                             refine_convergence_v=refine_convergence_v)],
        mesh=cell_mm_xyz, grid_phase=instance_origin_mm, surface=surface, boundary_policy=boundary_policy)
    if point['kind'] == 'rf_reference':
        identity['rf_reference_voltage_v'] = rf_reference_voltage_v
    return identity



def _domain_inputs(design: dict, domain: dict, point: dict) -> dict:
    return laplace_member_identity(dimensions=domain['dimensions'], bounds_mm=domain['bounds_mm'],
        gem_sha256=domain['gem_sha256'], cell_mm_xyz=domain['cell_mm_xyz'],
        instance_origin_mm=domain['instance_origin_mm'], surface=design['surface'],
        boundary_policy=domain['boundary_policy'], point=point,
        refine_convergence_v=domain['refine_convergence_v'][point['kind']],
        rf_reference_voltage_v=design.get('rf_reference_voltage_v'))


def _parent_boundary(parent_origin: dict, parent: dict) -> dict:
    record = parent['record']
    if (not isinstance(parent.get('cache_key'), str) or len(parent['cache_key']) != 64
            or type(record.get('bytes')) is not int or record['bytes'] <= 0):
        raise ValueError('fine domain requires its published same-member parent')
    _require_sha256(record.get('sha256'), 'parent PA')
    row = dict(kind=record['kind'], name=Path(record['path']).name, bytes=record['bytes'], sha256=record['sha256'])
    if record.get('working_point_id'):
        row['working_point_id'] = record['working_point_id']
    return dict(kind='parent_dirichlet', parent_cache_key=parent['cache_key'],
                parent_origin_mm=parent_origin, parent_working_points=[row])


def frontend_field_identity(design: dict, domain_id: str, *, member_id: str, parent_fields: dict | None = None) -> dict:
    domains = {row['domain_id']: row for row in design['domains']}
    point = next(point for point in design['working_points'] if working_point_member_id(point) == member_id)
    identity = _domain_inputs(design, domains[domain_id], point)
    if domain_id == 'entrance_refinement':
        identity['boundary_policy'] = _parent_boundary(domains['parent']['instance_origin_mm'], parent_fields[member_id])
    elif parent_fields is not None:
        raise ValueError('parent domain cannot depend on fine fields')
    return identity


def bind_parent_fields(domain_plan: dict, parent_fields: dict) -> dict:
    if domain_plan['domain_id'] != 'entrance_refinement':
        raise ValueError('only entrance refinement consumes parent fields')
    result = dict(domain_plan, members=[])
    for member in domain_plan['members']:
        value = dict(member)
        boundary = _parent_boundary(domain_plan['parent_origin_mm'], parent_fields[value['member_id']])
        value['identity'] = dict(value['identity'], boundary_policy=boundary)
        value['cache_key'] = canonical_pa_family_cache_key(value['identity'])
        if 'frozen_field_source' in value:
            _check_source_physics(value)
        result['members'].append(value)
    return result


def validate_frozen_generation_metadata(plan: dict, generation: Path) -> dict:
    """Use common metadata validation; never hash a published PA here."""
    manifest = validate_pa_family_cache_generation(generation, expected_cache_key=plan['cache_key'],
        expected_filenames=plan['filenames'], verify_payload=False)
    if (generation.resolve().name != manifest['generation_sha256'] or generation.parent.name != 'generations'
            or generation.parent.parent.name != plan['cache_key'] or manifest['identity'] != plan['identity']):
        raise ValueError('frozen frontend field source generation identity differs')
    inventory = {row['name']: row for row in manifest['files']}
    for expected in plan['frozen_field_source']['working_points']:
        actual = inventory.get(Path(expected['path']).name)
        if (actual is None or actual['bytes'] != expected['bytes']
                or actual['sha256'].upper() != expected['sha256'].upper()):
            raise ValueError('frozen frontend field source member differs')
    return manifest


def _check_source_physics(member: dict) -> None:
    source = member['frozen_field_source']
    identity = source['identity']
    point = source['physical_point']
    projected = (identity if source['source_schema_version'] == 3 else
                 _member_projection(identity, point, member_id=member['member_id']))
    if projected != member['identity']:
        raise ValueError(f"{member['member_id']}: frozen field source physical identity differs")


def _bound_source_audit(manifest: dict, record: dict | None) -> dict | None:
    """Resolve a small audit through the frozen producer's durable manifest.

    Stage receipts can retain a retired execution alias. Terminal publication
    already records its durable path; never infer an alias replacement or scan
    files, and keep byte/hash binding and the normal audit verification.
    """
    if record is None:
        return None
    producer = Path(manifest['run_config']['path']).parent
    matches = {}
    for candidate in [*manifest.get('inputs', {}).values(), *manifest.get('outputs', [])]:
        if (candidate.get('bytes') == record.get('bytes')
                and str(candidate.get('sha256', '')).upper() == str(record.get('sha256', '')).upper()
                and Path(candidate.get('path', '')).name == Path(record['path']).name):
            path = record_path(candidate, base_dir=producer)
            matches[str(path)] = path
    if len(matches) != 1:
        raise ValueError('source field audit is not uniquely identity-bound by its producer manifest')
    return dict(record, path=str(next(iter(matches.values()))))



def _frozen_field_source(prepared: Path, design: dict, plans: list[dict]) -> bool:
    request_path = prepared / 'request.json'
    if not request_path.is_file():
        return False
    request = json.loads(request_path.read_text(encoding='utf-8-sig'))
    providers = request['providers']
    if 'frontend_fields' not in providers:
        return False
    receipt = json.loads((prepared / _SOURCE_RECEIPT).read_text(encoding='utf-8-sig'))
    version = receipt.get('schema_version')
    if (version not in (2, 3) or receipt.get('role') != 'single_reflection_frontend_working_fields'
            or receipt.get('status') != 'success'):
        raise ValueError('explicit frontend source must be successful schema2/3 evidence')
    manifest = json.loads((prepared / 'frontend_field_source_manifest.json').read_text(encoding='utf-8-sig'))
    if manifest.get('role') != 'simulation_run_manifest':
        raise ValueError('frozen frontend source producer manifest differs')
    if [row['domain_id'] for row in receipt['domains']] != [row['domain_id'] for row in plans]:
        raise ValueError('frozen frontend source domains differ')
    selected = providers.get('frontend_field_reuse_members', [working_point_member_id(p) for p in design['working_points']])
    for domain, source_domain in zip(plans, receipt['domains'], strict=True):
        source_points = source_domain['working_points']
        for member in domain['members']:
            if member['member_id'] not in selected:
                continue
            matches = [row for row in source_points if working_point_member_id(row) == member['member_id']]
            if len(matches) != 1:
                raise ValueError('selected frozen source member absent or duplicated')
            record = matches[0]
            info = source_domain if version == 2 else record
            identity_path = prepared / ('frontend_field_source_' + domain['domain_id'] +
                ('' if version == 2 else '_' + member['member_id']) + '_identity.json')
            identity_record = info['cache_identity_record']
            if (not identity_path.is_file() or identity_path.stat().st_size != identity_record['bytes']
                    or file_sha256(identity_path).upper() != identity_record['sha256'].upper()):
                raise ValueError('frozen frontend source identity copy differs')
            identity = json.loads(identity_path.read_text(encoding='utf-8-sig'))
            source_version = 2 if version == 2 else info['source_schema_version']
            physical_points = identity['working_points']
            ordinal = source_points.index(record) if source_version == 2 else 0
            if source_version == 2 and version == 3:
                matches = [i for i,p in enumerate(physical_points) if p['kind'] == record['kind']
                    and p['electrode_voltages_v'] == member['identity']['working_points'][0]['electrode_voltages_v']]
                if len(matches) != 1:
                    raise ValueError('inherited frozen source physical member differs or is ambiguous')
                ordinal = matches[0]
            physical_point = physical_points[ordinal]
            filenames = ([Path(row['path']).name for row in source_points] + [AUDIT_NAME]
                         if version == 2 else info['cache_filenames'])
            check = dict(identity=identity, cache_key=info['cache_key'], filenames=filenames,
                         frozen_field_source=dict(working_points=[record]))
            generation = Path(info['generation_directory']).resolve()
            publication = validate_frozen_generation_metadata(check, generation)
            canonical_record = dict(record, path=str(generation / Path(record['path']).name))
            source = dict(identity=identity, cache_key=info['cache_key'], generation_directory=str(generation),
                identity_path=str(identity_path), cache_filenames=filenames,
                source_schema_version=source_version, physical_point=physical_point,
                record=canonical_record, audit_record=(_bound_source_audit(manifest, info.get('audit_record')) if version == 3 else
                    dict(path=str(generation/AUDIT_NAME), **{k:next(row for row in publication['files'] if row['name']==AUDIT_NAME)[k] for k in ('bytes','sha256')})))
            member['frozen_field_source'] = source
            if domain['domain_id'] == 'parent':
                _check_source_physics(member)
    return True


def build_field_plan(prepared: Path, executable: Path, repo: Path) -> dict:
    """Validate schema3 domain inputs once; bind the fine key after parent publication."""
    design = json.loads((prepared / 'frontend_field_design.json').read_text(encoding='utf-8-sig'))
    geometry = json.loads((prepared / 'frontend_geometry.json').read_text(encoding='utf-8-sig'))
    if (design.get('schema_version') != 3 or design.get('role') != 'frontend_native_field_design'
            or design.get('surface') != 'none'):
        raise ValueError('schema3 surface=none frontend design required')
    domain_ids = [row['domain_id'] for row in design['domains']]
    if domain_ids not in (['parent'], ['parent', 'entrance_refinement']):
        raise ValueError('ordered parent and optional entrance refinement required')
    if set(geometry['numerical_domains']) != set(domain_ids):
        raise ValueError('geometry numerical domains differ from field design')
    points = design['working_points']
    multipole_ids, mapping = frontend_electrode_maps(geometry)
    electrode_ids = sorted({eid for value in mapping.values() for eid in (value if isinstance(value, list) else [value])}
                           | {eid for binding in multipole_ids.values() for eid in binding.values()})
    kinds = tuple(point['kind'] for point in points)
    expected_kinds = ('carrier_off', *(kind for kind in kinds if kind == 'rf_reference'),
                      *(('pulse_delta',) if 'pulse_delta' in kinds else ()))
    if kinds != expected_kinds:
        raise ValueError('ordered carrier, RF responses and optional pulse field required')
    has_rf = 'rf_reference' in kinds
    if has_rf != ('rf_reference_voltage_v' in design):
        raise ValueError('RF reference must be present exactly when an RF field is declared')
    if not has_rf and (domain_ids != ['parent'] or multipole_ids):
        raise ValueError('RF-free accelerator field requires only its parent domain')
    parent_sample_count = len(electrode_ids)
    for multipole_id, binding in multipole_ids.items():
        provider = json.loads((prepared / 'components' / multipole_id / 'resolved_design.json').read_text(encoding='utf-8-sig'))
        rods = provider['segmentation']['segmented_rod_array']['electrodes']
        rod_ids = {binding[rod['electrode_id']] for rod in rods}
        parent_sample_count += len(rods) - len(rod_ids)
    for point in points:
        if set(point) - {'kind', 'working_point_id', 'electrode_voltages_v'} or set(point) < {'kind', 'electrode_voltages_v'}:
            raise ValueError('working point must contain only its physical voltage table and optional repeated-RF member identity')
        working_point_member_id(point)
        values = point['electrode_voltages_v']
        if set(values) != {str(i) for i in electrode_ids} or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in values.values()):
            raise ValueError('complete finite model voltage namespace required')
    reference = design.get('rf_reference_voltage_v')
    if has_rf and (type(reference) not in (int, float) or not math.isfinite(reference) or reference <= 0):
        raise ValueError('RF reference must be finite and positive')
    builders = {
        'operating_builder': repo / 'common/simion/build_dirichlet_patch_operating_pa.lua',
        'exporter': repo / 'common/simion/export_detached_standalone_pa.lua',
    }
    authority = dict(simion_identity=dict(release='SIMION 2020', executable_bytes=executable.stat().st_size,
                                         executable_sha256=file_sha256(executable)),
                     builder_identity={name: file_sha256(path) for name, path in builders.items()})
    plans = []
    for domain in design['domains']:
        name = domain['domain_id']
        numerical = geometry['numerical_domains'][name]
        for field in ('dimensions', 'cell_mm_xyz', 'instance_origin_mm', 'bounds_mm', 'active_bounds_mm'):
            if domain.get(field) != numerical.get(field):
                raise ValueError(f'{name}: field design {field} differs from frozen geometry')
        dimensions, pitch = domain['dimensions'], domain['cell_mm_xyz']
        if any(type(dimensions['n'+a]) is not int or dimensions['n'+a] < 2 for a in 'xyz'):
            raise ValueError('invalid PA dimensions')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in pitch.values()):
            raise ValueError('mesh must be finite and positive')
        expected_boundary = 'native_zero_neumann' if name == 'parent' else 'parent_dirichlet'
        if domain['boundary_policy'] != expected_boundary or (
                name != 'parent' and domain.get('parent_domain_id') != 'parent'):
            raise ValueError('invalid domain boundary or parent binding')
        convergence = domain['refine_convergence_v']
        if set(convergence) != set(kinds) or any(type(v) not in (int, float)
                or not math.isfinite(v) or v <= 0 for v in convergence.values()):
            raise ValueError('explicit finite positive Refine convergence for every actual field required')
        samples = domain['physical_samples']
        if not samples or len({r['label'] for r in samples}) != len(samples):
            raise ValueError('unique actual body samples required')
        if name == 'parent':
            if len(samples) != parent_sample_count or {r['electrode_id'] for r in samples} != set(electrode_ids):
                raise ValueError('complete parent body samples required')
        for sample in samples:
            if (sample['electrode_id'] not in electrode_ids or len(sample['gu']) != 3
                    or any(type(v) is not int or not 0 <= v < dimensions['n'+a]
                           for a, v in zip('xyz', sample['gu'], strict=True))):
                raise ValueError('physical sample outside declared grid or electrode namespace')
        stem = 'frontend' if name == 'parent' else 'frontend_entrance_refinement'
        gem = prepared / (stem+'.gem')
        if domain['gem_sha256'] != file_sha256(gem):
            raise ValueError('frozen field design GEM identity differs from prepared GEM')
        plan = dict(domain_id=name, gem_filename=gem.name,
            grid=[dimensions['n'+a] for a in 'xyz']+[pitch[a] for a in 'xyz'],
            instance_origin_mm=domain['instance_origin_mm'], physical_samples=samples,
            physical_electrode_ids=electrode_ids, boundary_policy=domain['boundary_policy'], members=[],
            working_points=[dict(**point, filename=f'{stem}.{working_point_member_id(point)}.pa',
                voltage_argument=','.join(format(point['electrode_voltages_v'].get(str(i), 0.), '.17g') for i in range(1, max(electrode_ids)+1)),
                convergence_argument=format(convergence[point['kind']], '.17g')) for point in points])
        if name != 'parent':
            plan['parent_origin_mm'] = design['domains'][0]['instance_origin_mm']
        for point in plan['working_points']:
            identity = dict(_domain_inputs(design, domain, point), **authority)
            plan['members'].append(dict(member_id=working_point_member_id(point), identity=identity,
                cache_key=canonical_pa_family_cache_key(identity) if name == 'parent' else None,
                filenames=[point['filename']], working_points=[point]))
        plans.append(plan)
    frozen = _frozen_field_source(prepared, design, plans)
    return dict(domains=plans, frozen_field_source=frozen,
                **({'rf_reference_voltage_v': reference} if has_rf else {}))



def audit_input_identity(plan: dict) -> str:
    return canonical_json_sha256(dict(domain_id=plan['domain_id'], grid=plan['grid'],
        boundary_policy=plan['boundary_policy'], gem=plan['identity']['gem'],
        physical_electrode_ids=plan['physical_electrode_ids'],
        physical_samples=[{key: row[key] for key in ('electrode_id', 'gu')} for row in plan['physical_samples']],
        working_points=[{key: row[key] for key in ('kind', 'voltage_argument')} for row in plan['working_points']]))


def reusable_audit(plan: dict, generation: Path, verifier: Path) -> dict | None:
    source = plan.get('frozen_field_source')
    if source is not None:
        record = source.get('audit_record')
        if record is None:
            return None
        verify_record('source field audit', record)
    else:
        transaction = load_pa_family_cache_transaction(generation.parent.parent.parent, plan['cache_key'])
        evidence = transaction.get('verification')
        if evidence is None:
            return None
        audit_path = Path(evidence['verification_output_path'])
        if not audit_path.is_file():
            return None
        record = dict(path=str(audit_path), bytes=audit_path.stat().st_size,
                      sha256=evidence['verification_output_sha256'])
        verify_record('published field audit', record)
    report = json.loads(Path(record['path']).read_text(encoding='utf-8-sig'))
    if (report.get('status') != 'pass' or report.get('audit_input_sha256') != audit_input_identity(plan)
            or report.get('audit_verifier_sha256') != file_sha256(verifier)):
        return None
    return file_record(Path(record['path']))


def write_audit_spec(plan: dict, raw: Path, payload: Path, output: Path) -> None:
    """Write only bounded native sample instructions, with actual volts and grid."""
    rows = ['frontend_working_fields_audit_v2', 'domain\t'+plan['domain_id'], 'boundary\t'+plan['boundary_policy'], 'grid\t'+'\t'.join(map(str, plan['grid'])), 'raw\t'+str(raw), 'electrodes\t'+','.join(map(str, plan['physical_electrode_ids']))]
    for sample in plan['physical_samples']:
        rows.append('\t'.join(map(str, ['physical', sample['label'], sample['electrode_id'], *sample['gu']])))
    for point in plan['working_points']:
        rows.append('\t'.join(['working', point['kind'], str(point.get('path', payload / point['filename']))]))
        rows.append('\t'.join(['voltages', point['kind'], point['voltage_argument']]))
    output.write_text('\n'.join(rows)+'\n', encoding='utf-8', newline='\n')


def field_bank(design: dict, domain_ids: list[str]) -> dict:
    """Project the actual working members; no independent field-selection flag."""
    points = design['working_points']
    members = [working_point_member_id(point) for point in points]
    rf_member_ids = [member for member, point in zip(members, points, strict=True)
                     if point['kind'] == 'rf_reference']
    rows = []
    for index, name in enumerate(domain_ids, 1):
        stem = 'frontend' if name == 'parent' else 'frontend_entrance_refinement'
        row = dict(role='coarse_frontend' if name == 'parent' else 'entrance_refinement',
            instance_index=index, carrier_pa_basename=stem+'.carrier_off.pa')
        if any(point['kind'] == 'pulse_delta' for point in points):
            row['pulse_delta_pa_basename'] = stem+'.pulse_delta.pa'
        if rf_member_ids:
            row.update(rf_differential_pa_basenames=[stem+'.'+member+'.pa' for member in rf_member_ids],
                       rf_reference_voltage_v=design['rf_reference_voltage_v'])
        rows.append(row)
    return dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
        runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION, dynamic_roles=rows)
