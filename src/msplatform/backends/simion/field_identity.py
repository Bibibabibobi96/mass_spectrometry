"""The sole physical Laplace-member identity projection, without cache I/O."""
from __future__ import annotations
from pathlib import Path

def working_point_member_id(point: dict) -> str:
    """Stable PA member name: labels identify repeated RF responses only."""
    kind = point.get('kind')
    member = point.get('working_point_id') or kind
    if not isinstance(member, str) or not member or (member != kind and kind != 'rf_reference'):
        raise ValueError('working point member identity is invalid')
    return member


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



def render_audit_spec(plan: dict, raw: Path, payload: Path) -> str:
    """Render the same bounded native audit transport without writing."""
    rows = ['frontend_working_fields_audit_v2', 'domain\t'+plan['domain_id'], 'boundary\t'+plan['boundary_policy'], 'grid\t'+'\t'.join(map(str, plan['grid'])), 'raw\t'+str(raw), 'electrodes\t'+','.join(map(str, plan['physical_electrode_ids']))]
    for sample in plan['physical_samples']:
        rows.append('\t'.join(map(str, ['physical', sample['label'], sample['electrode_id'], *sample['gu']])))
    for point in plan['working_points']:
        rows.append('\t'.join(['working', point['kind'], str(point.get('path', payload / point['filename']))]))
        rows.append('\t'.join(['voltages', point['kind'], point['voltage_argument']]))
    return '\n'.join(rows)+'\n'
