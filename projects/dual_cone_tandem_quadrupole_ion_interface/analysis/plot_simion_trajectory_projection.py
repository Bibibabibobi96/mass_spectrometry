"""Plot full and downstream radial projections from governed SIMION CSV outputs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GEOMETRY = PROJECT_ROOT / "config" / "resolved_geometry.json"


def axial_reach_profile(
    tracks: Mapping[int, tuple[Sequence[float], Sequence[float]]],
    lower_z_mm: float,
    upper_z_mm: float,
) -> tuple[list[float], list[int]]:
    """Return a step profile of unique ions that reached each axial position."""
    if not math.isfinite(lower_z_mm) or not math.isfinite(upper_z_mm):
        raise ValueError("axial reach limits must be finite")
    if upper_z_mm <= lower_z_mm:
        raise ValueError("upper axial reach limit must exceed lower limit")

    maxima = [max(z_values) for z_values, _ in tracks.values() if z_values]
    current = sum(maximum >= lower_z_mm for maximum in maxima)
    losses = Counter(
        maximum for maximum in maxima if lower_z_mm < maximum < upper_z_mm
    )
    edges = [lower_z_mm]
    values: list[int] = []
    for position, count in sorted(losses.items()):
        values.append(current)
        edges.append(position)
        current -= count
    values.append(current)
    edges.append(upper_z_mm)
    return edges, values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True, type=Path)
    parser.add_argument("--final-state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY)
    parser.add_argument("--axis-center-x-mm", type=float, default=25.5)
    parser.add_argument("--axis-center-y-mm", type=float, default=25.5)
    parser.add_argument("--device-z-offset-mm", type=float, default=2.0)
    args = parser.parse_args()

    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.ticker import MaxNLocator

    resolved = json.loads(args.geometry.read_text(encoding="utf-8"))
    geometry = resolved["geometry_mm"]
    stage_2_end = float(geometry["stage_2_round_quadrupole"]["downstream_flat_end_z_mm"])
    plate = geometry["downstream_aperture_plate"]
    plate_up = float(plate["upstream_face_z_mm"])
    plate_down = float(plate["downstream_face_z_mm"])
    endpoint = float(plate["downstream_observation_end_z_mm"])

    passed: set[int] = set()
    with args.final_state.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if int(row["splat"]) == 1:
                passed.add(int(row["ion_number"]))

    tracks: dict[int, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    with args.trajectory.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            ion = int(row["ion_number"])
            x = float(row["x_mm"]) - args.axis_center_x_mm
            y = float(row["y_mm"]) - args.axis_center_y_mm
            z = float(row["z_mm"]) - args.device_z_offset_mm
            tracks[ion][0].append(z)
            tracks[ion][1].append(math.hypot(x, y))

    full_limits = (-2.0, endpoint)
    figure, axes = plt.subplots(3, 1, figsize=(11, 9.5), constrained_layout=True)
    for axis, limits in zip(axes[:2], [full_limits, (100.0, endpoint)]):
        passed_segments = [
            list(zip(z, radius))
            for ion, (z, radius) in tracks.items()
            if ion in passed
        ]
        lost_segments = [
            list(zip(z, radius))
            for ion, (z, radius) in tracks.items()
            if ion not in passed
        ]
        axis.add_collection(
            LineCollection(
                passed_segments,
                colors="#0072B2",
                linestyles="solid",
                alpha=0.32,
                linewidths=0.65,
            )
        )
        axis.add_collection(
            LineCollection(
                lost_segments,
                colors="#D55E00",
                linestyles="dashed",
                alpha=0.32,
                linewidths=0.65,
            )
        )
        axis.axvline(stage_2_end, color="#555555", linestyle="--", linewidth=1.0)
        axis.axvspan(plate_up, plate_down, color="#756bb1", alpha=0.25)
        axis.axhline(float(plate["aperture_radius_mm"]), color="#756bb1",
                     linestyle=":", linewidth=1.0)
        axis.set_xlim(*limits)
        axis.set_ylim(bottom=0)
        axis.grid(alpha=0.2)
        axis.set_ylabel("radial distance r (mm)")
    axes[0].set_title(
        f"SIMION N2/SDS trajectories (N={len(tracks)}): blue solid reaches terminal plane; "
        "orange dashed is lost"
    )
    axes[1].set_title("Downstream detail: rod end 108 mm, aperture plate 110.22–110.72 mm")
    reach_edges, reach_counts = axial_reach_profile(tracks, *full_limits)
    axes[2].stairs(reach_counts, reach_edges, color="#0072B2", linewidth=1.5)
    axes[2].axvline(stage_2_end, color="#555555", linestyle="--", linewidth=1.0)
    axes[2].axvspan(plate_up, plate_down, color="#756bb1", alpha=0.25)
    axes[2].set_xlim(*full_limits)
    axes[2].set_ylim(0, max(1, max(reach_counts, default=0)) * 1.05)
    axes[2].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[2].grid(alpha=0.2)
    axes[2].set_ylabel("ions reaching z, N")
    axes[2].set_title("Axial reach: unique ions with maximum sampled z at or beyond position")
    axes[2].set_xlabel("device z (mm)")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    plt.close(figure)
    print(f"SIMION_TRAJECTORY_PROJECTION=PASS PATH={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
