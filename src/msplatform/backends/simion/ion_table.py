"""Read recorded SIMION ION source rows for existing diagnostics."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from msplatform.contracts.particle_identity import parse_charge_state


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
                "ChargeState": parse_charge_state(columns[2]),
                "X0Mm": float(columns[3]),
                "Y0Mm": float(columns[4]),
                "Z0Mm": float(columns[5]),
                "EnergyEv": float(columns[8]),
            }
        )
    if not rows:
        raise ValueError(f"ION file is empty: {path}")
    return pd.DataFrame(rows)
