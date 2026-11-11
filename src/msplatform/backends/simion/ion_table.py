"""Read recorded SIMION ION source rows for existing diagnostics."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _validated_charge_state(value: Any) -> int:
    """Parse a finite nonzero integer charge without truncating source text."""
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("charge_state must be a finite nonzero integer") from exc
    if (isinstance(value, (bool, np.bool_)) or not number.is_finite()
            or number == 0 or number != number.to_integral_value()):
        raise ValueError("charge_state must be a finite nonzero integer")
    return int(number)


def read_ion_table(path: Path) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for ion, line in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
        if not line.strip():
            continue
        columns = line.split(",")
        if len(columns) < 9:
            raise ValueError(f"Malformed ION line {ion} in {path}")
        rows.append(
            {
                "Ion": ion,
                "TobUs": float(columns[0]),
                "MassAmu": float(columns[1]),
                "ChargeState": _validated_charge_state(columns[2]),
                "X0Mm": float(columns[3]),
                "Y0Mm": float(columns[4]),
                "Z0Mm": float(columns[5]),
                "EnergyEv": float(columns[8]),
            }
        )
    if not rows:
        raise ValueError(f"ION file is empty: {path}")
    return pd.DataFrame(rows)
