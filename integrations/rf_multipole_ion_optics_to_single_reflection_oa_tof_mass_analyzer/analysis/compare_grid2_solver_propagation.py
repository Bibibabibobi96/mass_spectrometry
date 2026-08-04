"""Compare middle-solver grid2 states and their common oaTOF propagation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Callable

from common.contracts.component_particle_state import validate_component_particle_state_csv


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _rms(values: list[float]) -> float | None:
    return math.sqrt(statistics.fmean(value * value for value in values)) if values else None


def _sample_sigma(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _grid2(path: Path, solver: str) -> dict[int, dict[str, float]]:
    if solver == "comsol":
        validate_component_particle_state_csv(path)
        return {
            int(row["particle_id"]): {
                "t": float(row["instrument_time_us"]),
                **{axis: float(row[f"position_{axis}_mm"]) for axis in "xyz"},
                **{f"v{axis}": float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"},
                "energy": float(row["kinetic_energy_eV"]),
            }
            for row in _rows(path)
        }
    return {
        int(row["particle_id"]): {
            "t": float(row["instrument_time_us"]),
            **{axis: float(row[axis]) for axis in "xyz"},
            **{f"v{axis}": float(row[f"v{axis}"]) for axis in "xyz"},
            "energy": float(row["energy"]),
        }
        for row in _rows(path)
    }


def _downstream(particles: Path, row_map: Path) -> dict[int, dict[str, float]]:
    identity = {
        int(row["solver_row_index"]): int(row["particle_id"])
        for row in _rows(row_map)
    }
    result: dict[int, dict[str, float]] = {}
    for row in _rows(particles):
        if row["Hit"].strip().lower() != "true" or not row["InstrumentTimeUs"].strip():
            continue
        result[identity[int(row["Ion"])]] = {
            "t": float(row["InstrumentTimeUs"]),
            "x": float(row["XMm"]),
            "y": float(row["YMm"]),
            "radius": float(row["RadiusMm"]),
            "tof": float(row["TofUs"]),
        }
    return result


def _detector_summary(hits: dict[int, dict[str, float]]) -> dict[str, float | int | None]:
    if not hits:
        return {"hits": 0}
    rows = list(hits.values())
    mean_x = statistics.fmean(row["x"] for row in rows)
    mean_y = statistics.fmean(row["y"] for row in rows)
    times = [row["t"] for row in rows]
    return {
        "hits": len(rows),
        "centroid_x_mm": mean_x,
        "centroid_y_mm": mean_y,
        "centered_rms_radius_mm": math.sqrt(statistics.fmean(
            (row["x"] - mean_x) ** 2 + (row["y"] - mean_y) ** 2 for row in rows
        )),
        "mean_instrument_time_us": statistics.fmean(times),
        "sample_sigma_instrument_time_us": _sample_sigma(times),
        "maximum_hit_radius_mm": max(row["radius"] for row in rows),
    }


def compare(
    *, label: str, handoff_count: int, simion_grid2_path: Path,
    comsol_grid2_path: Path, simion_downstream_path: Path,
    simion_row_map_path: Path, comsol_downstream_path: Path,
    comsol_row_map_path: Path, middle_comparison_path: Path,
) -> dict[str, object]:
    simion_grid2 = _grid2(simion_grid2_path, "simion")
    comsol_grid2 = _grid2(comsol_grid2_path, "comsol")
    simion_hits = _downstream(simion_downstream_path, simion_row_map_path)
    comsol_hits = _downstream(comsol_downstream_path, comsol_row_map_path)
    paired_grid2 = sorted(set(simion_grid2) & set(comsol_grid2))
    common_hits = sorted(set(simion_hits) & set(comsol_hits))

    def differences(function: Callable[[dict[str, float], dict[str, float]], float]) -> list[float]:
        return [function(simion_grid2[i], comsol_grid2[i]) for i in paired_grid2]

    grid2_pair = {
        "particles": len(paired_grid2),
        "position_vector_rms_difference_mm": _rms(differences(lambda a, b: math.sqrt(
            sum((a[k] - b[k]) ** 2 for k in "xyz")
        ))),
        "velocity_vector_rms_difference_m_s": _rms(differences(lambda a, b: math.sqrt(
            sum((a[f"v{k}"] - b[f"v{k}"]) ** 2 for k in "xyz")
        ))),
        "energy_rms_difference_eV": _rms(differences(lambda a, b: a["energy"] - b["energy"])),
        "instrument_time_rms_difference_us": _rms(differences(lambda a, b: a["t"] - b["t"])),
    }
    detector_pair = {
        "particles": len(common_hits),
        "position_vector_rms_difference_mm": _rms([
            math.hypot(
                simion_hits[i]["x"] - comsol_hits[i]["x"],
                simion_hits[i]["y"] - comsol_hits[i]["y"],
            ) for i in common_hits
        ]),
        "instrument_time_rms_difference_us": _rms([
            simion_hits[i]["t"] - comsol_hits[i]["t"] for i in common_hits
        ]),
    }

    branches: dict[str, object] = {}
    for solver, states, hits in (
        ("simion", simion_grid2, simion_hits),
        ("comsol", comsol_grid2, comsol_hits),
    ):
        branches[solver] = {
            "grid2_particles": len(states),
            "handoff_to_grid2_efficiency": len(states) / handoff_count,
            "detector_hits": len(hits),
            "grid2_to_detector_hit_efficiency": len(hits) / len(states),
            "handoff_to_detector_hit_efficiency": len(hits) / handoff_count,
            "detector": _detector_summary(hits),
        }

    return {
        "schema_version": 1,
        "role": "rf_oatof_middle_solver_downstream_propagation_comparison",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "scope": (
            "same canonical multipole handoff; solver-specific continuous shield "
            "interface plus pulsed accelerator to physical grid2; identical restarted "
            "SIMION oaTOF downstream operator; no convergence or resolution claim"
        ),
        "case": label,
        "handoff_particles": handoff_count,
        "branches": branches,
        "grid2_identity": {
            "paired_particles": len(paired_grid2),
            "simion_only_particle_ids": sorted(set(simion_grid2) - set(comsol_grid2)),
            "comsol_only_particle_ids": sorted(set(comsol_grid2) - set(simion_grid2)),
        },
        "grid2_ensemble_simion_minus_comsol": json.loads(
            middle_comparison_path.read_text(encoding="utf-8-sig")
        )["simion_minus_comsol"],
        "grid2_paired_difference": grid2_pair,
        "detector_identity": {
            "common_hit_particles": len(common_hits),
            "simion_only_hit_particle_ids": sorted(set(simion_hits) - set(comsol_hits)),
            "comsol_only_hit_particle_ids": sorted(set(comsol_hits) - set(simion_hits)),
        },
        "detector_paired_difference": detector_pair,
        "claims": {"diagnostic_only": True, "resolution_claim_allowed": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--handoff-count", required=True, type=int)
    for name in (
        "simion-grid2", "comsol-grid2", "simion-downstream", "simion-row-map",
        "comsol-downstream", "comsol-row-map", "middle-comparison", "output",
    ):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    result = compare(
        label=args.label, handoff_count=args.handoff_count,
        simion_grid2_path=args.simion_grid2,
        comsol_grid2_path=args.comsol_grid2,
        simion_downstream_path=args.simion_downstream,
        simion_row_map_path=args.simion_row_map,
        comsol_downstream_path=args.comsol_downstream,
        comsol_row_map_path=args.comsol_row_map,
        middle_comparison_path=args.middle_comparison,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"GRID2_SOLVER_PROPAGATION=PASS CASE={args.label}")


if __name__ == "__main__":
    main()
