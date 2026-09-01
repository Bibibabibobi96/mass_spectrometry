"""Verify that a restart population is covered by the reduced post-pulse IOB."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _bounds(contract: dict[str, Any], *, role: str) -> dict[str, float]:
    raw = contract.get("active_bounds_mm", contract.get("instance_bounds_mm"))
    expected = {f"{axis}_{side}" for axis in ("x", "y", "z") for side in ("min", "max")}
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError(f"{role} bounds are incomplete")
    bounds = {key: float(value) for key, value in raw.items()}
    if not all(math.isfinite(value) for value in bounds.values()):
        raise ValueError(f"{role} bounds are non-finite")
    if any(bounds[f"{axis}_min"] >= bounds[f"{axis}_max"] for axis in ("x", "y", "z")):
        raise ValueError(f"{role} bounds are invalid")
    return bounds


def _contains(bounds: dict[str, float], point: dict[str, float]) -> bool:
    return all(bounds[f"{axis}_min"] <= point[axis] <= bounds[f"{axis}_max"] for axis in ("x", "y", "z"))


def validate_handoff_envelope(
    source_path: Path, main_contract_path: Path, local_contract_path: Path
) -> dict[str, Any]:
    """Return a compact coverage receipt or fail if the reduced IOB has a gap."""
    main_bounds = _bounds(_load(main_contract_path), role="accelerator main")
    local_bounds = _bounds(_load(local_contract_path), role="entrance local")
    total = 0
    uncovered: list[dict[str, Any]] = []
    with source_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"simulation_particle_id", "x_mm", "y_mm", "z_mm"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("restart source lacks canonical position columns")
        for row in reader:
            total += 1
            try:
                point = {axis: float(row[f"{axis}_mm"]) for axis in ("x", "y", "z")}
            except (TypeError, ValueError) as error:
                raise ValueError("restart source has an invalid position") from error
            if not all(math.isfinite(value) for value in point.values()):
                raise ValueError("restart source has a non-finite position")
            if not (_contains(main_bounds, point) or _contains(local_bounds, point)):
                if len(uncovered) < 8:
                    uncovered.append(
                        {"simulation_particle_id": row["simulation_particle_id"], **point}
                    )
    if total == 0:
        raise ValueError("restart source is empty")
    if uncovered:
        raise ValueError(
            "post-pulse reduced IOB would omit restart states outside main/local coverage: "
            + json.dumps(uncovered, separators=(",", ":"))
        )
    return {
        "schema_version": 1,
        "role": "rf_oatof_post_pulse_handoff_envelope_validation",
        "source_row_count": total,
        "coverage": "accelerator_main_or_entrance_local_v1",
        "accelerator_main_bounds_mm": main_bounds,
        "accelerator_entrance_local_bounds_mm": local_bounds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--accelerator-main-contract", required=True, type=Path)
    parser.add_argument("--entrance-local-contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = validate_handoff_envelope(
        args.source, args.accelerator_main_contract, args.entrance_local_contract
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
