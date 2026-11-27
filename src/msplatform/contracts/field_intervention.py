"""Vendor-neutral declared field intervention selector contract."""
from collections.abc import Mapping
import re
from typing import Any


def resolve_field_selector(selector: str) -> dict[str, int]:
    """Project one declared regional Ez selector to the existing SIMION flags."""
    flags = dict(A=0, D=0, S1=0, S2=0)
    if selector == 'real':
        return flags
    if selector == 'ideal:reflectron.full':
        return {**flags, 'S1_FULL': 1, 'S2_FULL': 1}
    if not isinstance(selector, str) or not selector.startswith('ideal:'):
        raise ValueError(f'Unsupported selector syntax: {selector}')
    regions = {'accel': ('A',), 'drift': ('D',), 'stage1': ('S1',),
               'stage2': ('S2',), 'reflectron': ('S1', 'S2'), 'all': tuple(flags)}
    for term in selector[len('ideal:'):].split('+'):
        parts = term.split('.')
        if len(parts) != 2:
            raise ValueError(f'Malformed selector term: {term}')
        if parts[1].lower() != 'ez':
            raise ValueError(f'SIMION supports composable Ez only; unsupported term: {term}')
        selected = regions.get(parts[0].lower())
        if selected is None:
            raise ValueError(f'Unsupported SIMION field region: {parts[0]}')
        for region in selected:
            flags[region] = 1
    return flags


def _case(case: Mapping[str, Any]) -> tuple[str, dict[str, int]]:
    if not isinstance(case, Mapping):
        raise ValueError('a frozen diagnostic case is required')
    case_id = case.get('id')
    if not isinstance(case_id, str) or re.fullmatch(r'[A-Za-z0-9_]+', case_id) is None:
        raise ValueError('diagnostic case ID must be an ASCII identifier')
    return case_id, resolve_field_selector(case.get('selector'))
