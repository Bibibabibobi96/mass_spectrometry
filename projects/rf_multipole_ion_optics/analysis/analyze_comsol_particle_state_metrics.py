"""Derive RF-quadrupole COMSOL transport metrics from canonical particle state."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import stdev
from typing import Any


def _finite(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _load_state(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"particle_id", "event", "status", "radial_position_mm", "kinetic_energy_eV"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"canonical state has incomplete columns: {path}")
    keys = {(row["particle_id"], row["event"]) for row in rows}
    if len(keys) != len(rows):
        raise ValueError(f"canonical state has duplicate particle/event rows: {path}")
    return rows


def derive(raw_metadata: dict[str, Any], state_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Return the legacy solver-summary contract from raw COMSOL state only."""
    if raw_metadata.get("role") != "rf_quadrupole_comsol_raw_solver_metadata":
        raise ValueError("raw COMSOL metadata role differs")
    source_ids = {row["particle_id"] for row in state_rows if row["event"] == "source"}
    terminal = [row for row in state_rows if row["event"] == "terminal"]
    if {row["particle_id"] for row in terminal} != source_ids or not source_ids:
        raise ValueError("canonical terminal rows do not close the source cohort")
    transmitted = [row for row in terminal if row["status"] == "transmitted"]
    radii = [_finite(row["radial_position_mm"]) for row in transmitted]
    energies = [_finite(row["kinetic_energy_eV"]) for row in transmitted]
    if any(value is None for value in radii + energies):
        raise ValueError("transmitted terminal state has non-finite radius or energy")
    numeric_radii = [float(value) for value in radii]
    numeric_energies = [float(value) for value in energies]
    summary = dict(raw_metadata)
    summary.pop("role", None)
    summary.update(
        {
            "role": "rf_quadrupole_comsol_solver_summary",
            "metrics_authority": "python_canonical_particle_state",
            "particles": len(source_ids),
            "hits": len(transmitted),
            "transmission": len(transmitted) / len(source_ids),
            "exit_rms_radius_mm": (
                math.sqrt(sum(value * value for value in numeric_radii) / len(numeric_radii))
                if numeric_radii else None
            ),
            "mean_output_energy_eV": (
                sum(numeric_energies) / len(numeric_energies) if numeric_energies else None
            ),
            "output_energy_standard_deviation_eV": (
                stdev(numeric_energies) if len(numeric_energies) > 1 else None
            ),
        }
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-metadata", type=Path, required=True)
    parser.add_argument("--particle-state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.raw_metadata.read_text(encoding="utf-8-sig"))
    result = derive(raw, _load_state(args.particle_state))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
