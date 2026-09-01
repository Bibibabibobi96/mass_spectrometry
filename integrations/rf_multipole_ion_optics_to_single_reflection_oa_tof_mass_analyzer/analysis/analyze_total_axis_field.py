"""Compare a SIMION total-axis export with its resolved three-zone axial field."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {"z_mm", "potential_V", "Ez_V_per_mm"}
PLANE_ROLES = ("repeller", "intermediate1", "intermediate2", "exit")
ZONE_ROLES = (
    ("zone1", "repeller", "intermediate1"),
    ("zone2", "intermediate1", "intermediate2"),
    ("zone3", "intermediate2", "exit"),
)


def _finite(value: object, name: str) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite")
    return resolved


def _load_axis_rows(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not REQUIRED_COLUMNS <= set(reader.fieldnames):
            raise ValueError("total-axis field CSV has invalid columns")
        rows = [
            {
                "z_mm": _finite(row["z_mm"], "z_mm"),
                "potential_V": _finite(row["potential_V"], "potential_V"),
                "Ez_V_per_mm": _finite(row["Ez_V_per_mm"], "Ez_V_per_mm"),
            }
            for row in reader
        ]
    if len(rows) < 2:
        raise ValueError("total-axis field CSV needs at least two samples")
    if any(left["z_mm"] >= right["z_mm"] for left, right in zip(rows, rows[1:])):
        raise ValueError("total-axis field z samples must be strictly increasing")
    return rows


def analyze(axis_rows: list[dict[str, float]], geometry: dict[str, Any]) -> dict[str, Any]:
    """Return zone-wise on-axis deviations from the resolved ideal field."""

    topology = geometry.get("accelerator_topology")
    if not isinstance(topology, dict):
        raise ValueError("resolved geometry lacks accelerator topology")
    planes = topology.get("planes_global_z_mm")
    potentials = topology.get("potentials_v")
    if not isinstance(planes, dict) or not isinstance(potentials, dict):
        raise ValueError("resolved geometry topology lacks planes or potentials")
    if set(planes) != set(PLANE_ROLES) or set(potentials) != set(PLANE_ROLES):
        raise ValueError("resolved geometry topology must have exactly four named planes and potentials")
    resolved_planes = {role: _finite(planes[role], f"plane {role}") for role in PLANE_ROLES}
    resolved_potentials = {
        role: _finite(potentials[role], f"potential {role}") for role in PLANE_ROLES
    }
    if any(
        resolved_planes[left] >= resolved_planes[right]
        for left, right in zip(PLANE_ROLES, PLANE_ROLES[1:])
    ):
        raise ValueError("resolved geometry planes must be strictly increasing")
    if any(
        resolved_potentials[left] <= resolved_potentials[right]
        for left, right in zip(PLANE_ROLES, PLANE_ROLES[1:])
    ):
        raise ValueError("resolved geometry potentials must be strictly decreasing")

    zones: list[dict[str, Any]] = []
    for zone_id, left, right in ZONE_ROLES:
        z_min = resolved_planes[left]
        z_max = resolved_planes[right]
        expected = (resolved_potentials[left] - resolved_potentials[right]) / (z_max - z_min)
        samples = [row["Ez_V_per_mm"] for row in axis_rows if z_min < row["z_mm"] < z_max]
        if not samples:
            raise ValueError(f"axis export has no interior samples for {zone_id}")
        errors = [sample - expected for sample in samples]
        rms_error = math.sqrt(sum(error * error for error in errors) / len(errors))
        zones.append(
            {
                "zone_id": zone_id,
                "z_min_mm": z_min,
                "z_max_mm": z_max,
                "expected_Ez_V_per_mm": expected,
                "sample_count": len(samples),
                "mean_Ez_V_per_mm": sum(samples) / len(samples),
                "median_Ez_V_per_mm": sorted(samples)[len(samples) // 2],
                "rms_error_V_per_mm": rms_error,
                "rms_relative_error": rms_error / expected,
                "maximum_absolute_error_V_per_mm": max(abs(error) for error in errors),
            }
        )
    return {
        "schema_version": 1,
        "role": "rf_oatof_total_axis_field_theory_comparison",
        "claim_status": "DIAGNOSTIC_ONLY",
        "comparison_basis": "SIMION total on-axis Ez against resolved piecewise-uniform zone fields",
        "zones": zones,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axis-field", required=True, type=Path)
    parser.add_argument("--oatof-geometry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(
        _load_axis_rows(args.axis_field),
        json.loads(args.oatof_geometry.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
