"""Shared physical electrode voltage-source lookup."""

import math


def physical_voltage_value(document: dict, pointer: str) -> float:
    """Read finite volts from an escaped pointer; reject missing or invalid values.

    This preserves the existing electrode lookup semantics and performs no I/O.
    """
    value: object = document
    for token in pointer.split('/')[1:]:
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdecimal() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValueError(f'physical electrode voltage source is missing: {pointer}')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'physical electrode voltage source is not finite: {pointer}')
    return float(value)
