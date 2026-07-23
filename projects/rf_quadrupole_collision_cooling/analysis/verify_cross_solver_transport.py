"""Close the converged COMSOL and SIMION no-collision transport results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def relative_difference(left: float, right: float) -> float:
    scale = (abs(left) + abs(right)) / 2
    return abs(left - right) / scale if scale else 0.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--comsol-run-id", required=True)
    parser.add_argument("--simion-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    artifact = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling"
    comsol_results = artifact / "runs" / args.comsol_run_id / "results"
    simion_results = artifact / "runs" / args.simion_run_id / "results"
    comsol_summary_path = comsol_results / "solver_summary.json"
    comsol_particles_path = comsol_results / "particles.csv"
    simion_summary_path = simion_results / "solver_summary.json"
    simion_particles_path = simion_results / "particles.csv"
    output_dir = args.output_dir.resolve()
    output_dir.relative_to((artifact / "runs").resolve())
    output_dir.mkdir(parents=True, exist_ok=True)

    comsol_summary = json.loads(comsol_summary_path.read_text(encoding="utf-8"))
    simion_summary = json.loads(simion_summary_path.read_text(encoding="utf-8"))
    resolved = json.loads((args.project / "config/resolved_geometry.json").read_text(encoding="utf-8"))
    mode = resolved["mode"]
    geometry = resolved["geometry_mm"]
    comsol_rows = load_csv(comsol_particles_path)
    simion_rows = load_csv(simion_particles_path)

    comsol_by_id = {int(row["particle_id"]): row for row in comsol_rows}
    simion_by_id = {int(row["particle_id"]): row for row in simion_rows}
    ids = sorted(comsol_by_id)
    if ids != sorted(simion_by_id) or ids != list(range(1, 26)):
        raise AssertionError("paired particle IDs are not exactly 1..25 in both solvers")

    paired: list[dict[str, float | int]] = []
    for particle_id in ids:
        c = comsol_by_id[particle_id]
        s = simion_by_id[particle_id]
        c_tof = float(c["arrival_time_us"])
        s_tof = float(s["arrival_time_us"])
        paired.append(
            {
                "particle_id": particle_id,
                "comsol_arrival_time_us": c_tof,
                "simion_arrival_time_us": s_tof,
                "arrival_time_difference_us": c_tof - s_tof,
                "comsol_max_rod_radius_mm": float(c["max_rod_radius_mm"]),
                "simion_max_rod_radius_mm": float(s["max_rod_radius_mm"]),
            }
        )

    transmission_delta = abs(float(comsol_summary["transmission"]) - float(simion_summary["transmission"]))
    mean_tof_comsol = mean([float(row["arrival_time_us"]) for row in comsol_rows])
    mean_tof_simion = mean([float(row["arrival_time_us"]) for row in simion_rows])
    mean_tof_relative_difference = relative_difference(mean_tof_comsol, mean_tof_simion)
    max_rod_comsol = max(float(row["max_rod_radius_mm"]) for row in comsol_rows)
    max_rod_simion = max(float(row["max_rod_radius_mm"]) for row in simion_rows)
    paired_mean_absolute_tof_difference = mean(
        [abs(float(row["arrival_time_difference_us"])) for row in paired]
    )

    gates = {
        "particle_identity": len(ids) == 25,
        "collision_free": not comsol_summary["collision_feature_present"]
        and simion_summary["collision_model"] == "none",
        "transmission": transmission_delta
        <= mode["numerics"]["cross_solver_transmission_absolute_tolerance"],
        "mean_tof": mean_tof_relative_difference
        <= mode["numerics"]["cross_solver_relative_mean_tof_tolerance"],
        "confinement": max(max_rod_comsol, max_rod_simion) < geometry["field_radius_r0"],
    }
    result = {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "mode": "transport_no_collision",
        "particles": len(ids),
        "source_ion_sha256": sha256(args.project / "config/particles/official_fixed_100.ion"),
        "geometry_gem_sha256": sha256(args.project / "simion/geometry/quad_include.gem"),
        "comsol": comsol_summary,
        "simion": simion_summary,
        "comparison": {
            "transmission_absolute_difference": transmission_delta,
            "mean_tof_comsol_us": mean_tof_comsol,
            "mean_tof_simion_us": mean_tof_simion,
            "mean_tof_relative_difference": mean_tof_relative_difference,
            "paired_mean_absolute_tof_difference_us": paired_mean_absolute_tof_difference,
            "max_rod_radius_comsol_mm": max_rod_comsol,
            "max_rod_radius_simion_mm": max_rod_simion,
        },
        "gates": gates,
    }
    (output_dir / "transport_no_collision_closure.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_dir / "transport_no_collision_paired.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(paired[0]))
        writer.writeheader()
        writer.writerows(paired)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
