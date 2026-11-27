"""Provider-owned MR scientific group voltage projection."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .assembly_interface import _component_electrodes, _scientific_groups
from .candidate_voltage import candidate_authority


def scientific_group_voltages(authority: Mapping[str, Any], resolved: dict) -> dict[str, float]:
    """Project explicit candidate, detector and shields onto physical MR groups."""
    if not isinstance(authority, Mapping) or set(authority) != {'source', 'candidate', 'mirror_voltages_v', 'detector_voltage_v', 'mirror_shield_voltages_v'}:
        raise ValueError('MR authority fields differ')
    voltage = candidate_authority(authority['source'], authority['candidate'], mirror_voltages_v=authority['mirror_voltages_v'])
    shields = authority['mirror_shield_voltages_v']
    if not isinstance(shields, Mapping) or set(shields) != {'positive_mirror_ground_shield', 'negative_mirror_ground_shield'}:
        raise ValueError('MR mirror shields fields differ')
    rows = _component_electrodes(resolved)
    groups = _scientific_groups(resolved, rows)
    values = {}
    if len(groups) != len(rows) + 2:
        raise ValueError('MR physical groups differ from the two explicit shields')
    def finite(value: Any, label: str) -> float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{label} must be finite')
        return float(value)
    for electrode, group in zip(rows, groups[:-2], strict=True):
        physical_id = electrode['component_electrode_id']; name = group['electrode_group_id']
        if group['role'] == 'detector':
            values[name] = finite(authority['detector_voltage_v'], 'MR detector voltage')
        elif 1 <= physical_id <= 20:
            values[name] = finite(voltage['analyzer_electrode_voltages_v'][physical_id-1], name)
        else:
            raise ValueError(f'no declared analyzer voltage for {name}')
    # Physical group order must survive JSON key sorting on a saved model.
    for group in groups[-2:]:
        name = group['electrode_group_id']
        values[name] = finite(shields[name], name)
    return values