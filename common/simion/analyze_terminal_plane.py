"""Summarize SIMION final states at a configured transverse acceptance plane."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {
    "ion_number", "time_us", "x_mm", "y_mm", "z_mm",
    "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "splat",
}


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def analyze_terminal_plane(
    path: Path,
    *,
    source_count: int,
    pass_code: int,
    axis_center_x_mm: float,
    axis_center_y_mm: float,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if source_count < 1:
        raise ValueError("source_count must be positive")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or set(reader.fieldnames) != REQUIRED_COLUMNS:
            raise ValueError("SIMION final-state columns differ from the terminal-plane contract")
        rows = list(reader)
    if len(rows) != source_count:
        raise ValueError("SIMION final-state census differs from the source count")
    ids = [int(row["ion_number"]) for row in rows]
    if sorted(ids) != list(range(1, source_count + 1)):
        raise ValueError("SIMION final-state particle identities are incomplete or duplicated")
    for row in rows:
        for name in REQUIRED_COLUMNS - {"ion_number", "splat"}:
            if not math.isfinite(float(row[name])):
                raise ValueError(f"SIMION final-state {name} is nonfinite")
    counts = Counter(int(row["splat"]) for row in rows)
    transmitted = [row for row in rows if int(row["splat"]) == pass_code]
    spatial: dict[str, Any] | None = None
    if transmitted:
        xs = [float(row["x_mm"]) for row in transmitted]
        ys = [float(row["y_mm"]) for row in transmitted]
        radii = [
            math.hypot(x - axis_center_x_mm, y - axis_center_y_mm)
            for x, y in zip(xs, ys, strict=True)
        ]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        spatial = {
            "centroid_x_mm": mean_x,
            "centroid_y_mm": mean_y,
            "sigma_x_mm": math.sqrt(sum((x - mean_x) ** 2 for x in xs) / len(xs)),
            "sigma_y_mm": math.sqrt(sum((y - mean_y) ** 2 for y in ys) / len(ys)),
            "mean_radius_mm": sum(radii) / len(radii),
            "rms_radius_mm": math.sqrt(sum(radius * radius for radius in radii) / len(radii)),
            "radius_q50_mm": _quantile(radii, 0.50),
            "radius_q90_mm": _quantile(radii, 0.90),
            "radius_q95_mm": _quantile(radii, 0.95),
            "maximum_radius_mm": max(radii),
        }
    return ({
        "schema_version": 1,
        "role": "simion_terminal_plane_transport_metrics",
        "source_count": source_count,
        "transmitted_count": len(transmitted),
        "transmission_fraction": len(transmitted) / source_count,
        "terminal_code_counts": {str(code): count for code, count in sorted(counts.items())},
        "pass_code": pass_code,
        "axis_center_mm": [axis_center_x_mm, axis_center_y_mm],
        "transmitted_spatial_distribution": spatial,
    }, transmitted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-state", required=True, type=Path)
    parser.add_argument("--source-count", required=True, type=int)
    parser.add_argument("--pass-code", required=True, type=int)
    parser.add_argument("--axis-center-x-mm", required=True, type=float)
    parser.add_argument("--axis-center-y-mm", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--transmitted-output", required=True, type=Path)
    args = parser.parse_args()
    metrics, transmitted = analyze_terminal_plane(
        args.final_state,
        source_count=args.source_count,
        pass_code=args.pass_code,
        axis_center_x_mm=args.axis_center_x_mm,
        axis_center_y_mm=args.axis_center_y_mm,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    args.transmitted_output.parent.mkdir(parents=True, exist_ok=True)
    with args.transmitted_output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted(REQUIRED_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(transmitted)
    print(
        "SIMION_TERMINAL_PLANE_ANALYSIS=PASS "
        f"TRANSMISSION={metrics['transmission_fraction']:.9g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
