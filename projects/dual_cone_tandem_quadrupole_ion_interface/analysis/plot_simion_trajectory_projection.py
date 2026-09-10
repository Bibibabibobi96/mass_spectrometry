"""Plot full and downstream radial projections from governed SIMION CSV outputs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GEOMETRY = PROJECT_ROOT / "config" / "resolved_geometry.json"


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

    figure, axes = plt.subplots(2, 1, figsize=(11, 7), constrained_layout=True)
    for axis, limits in zip(axes, [(-2.0, endpoint), (100.0, endpoint)]):
        for ion, (z, radius) in tracks.items():
            axis.plot(z, radius, color="#18794e" if ion in passed else "#c43c35",
                      alpha=0.28, linewidth=0.65)
        axis.axvline(stage_2_end, color="#555555", linestyle="--", linewidth=1.0)
        axis.axvspan(plate_up, plate_down, color="#756bb1", alpha=0.25)
        axis.axhline(float(plate["aperture_radius_mm"]), color="#756bb1",
                     linestyle=":", linewidth=1.0)
        axis.set_xlim(*limits)
        axis.set_ylim(bottom=0)
        axis.grid(alpha=0.2)
        axis.set_ylabel("radial distance r (mm)")
    axes[0].set_title("SIMION N2/SDS trajectories: green reaches terminal plane; red is lost")
    axes[1].set_title("Downstream detail: rod end 108 mm, aperture plate 110.22–110.72 mm")
    axes[1].set_xlabel("device z (mm)")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    plt.close(figure)
    print(f"SIMION_TRAJECTORY_PROJECTION=PASS PATH={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
