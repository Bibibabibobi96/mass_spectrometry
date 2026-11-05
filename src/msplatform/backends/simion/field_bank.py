"""The existing dynamic standalone field-bank protocol projection, without execution."""
from .field_identity import working_point_member_id
from .tracking_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
)


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
