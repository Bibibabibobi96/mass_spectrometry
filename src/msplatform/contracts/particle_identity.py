"""Exact lexical parsing for a particle's signed integer charge state."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np


def parse_charge_state(value: Any) -> int:
    """Parse a finite nonzero integer charge without truncating source text."""
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("charge_state must be a finite nonzero integer") from exc
    if (isinstance(value, (bool, np.bool_)) or not number.is_finite()
            or number == 0 or number != number.to_integral_value()):
        raise ValueError("charge_state must be a finite nonzero integer")
    return int(number)
