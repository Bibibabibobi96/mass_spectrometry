"""Compare SIMION port-and-pulse transport with COMSOL local-exit state."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

from common.contracts.component_particle_state import validate_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev


LOCAL_EXIT = re.compile(
    r"TRACE: local_accelerator_exit ion=(\d+) instrument_time_us=([-+0-9.eE]+) "
    r"x_mm=([-+0-9.eE]+) y_mm=([-+0-9.eE]+) z_mm=([-+0-9.eE]+) "
    r"vx_mm_per_us=([-+0-9.eE]+) vy_mm_per_us=([-+0-9.eE]+) "
    r"vz_mm_per_us=([-+0-9.eE]+)"
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _summary(rows: list[dict[str, float]]) -> dict[str, float | int | None]:
    if not rows:
        return {"particles": 0}
    mean_x = statistics.fmean(row["x"] for row in rows)
    mean_y = statistics.fmean(row["y"] for row in rows)
    mean_ax = statistics.fmean(row["ax"] for row in rows)
    mean_ay = statistics.fmean(row["ay"] for row in rows)
    energies = [row["energy"] for row in rows]
    return {
        "particles": len(rows),
        "centroid_x_mm": mean_x,
        "centroid_y_mm": mean_y,
        "centered_rms_radius_mm": math.sqrt(statistics.fmean(
            (row["x"] - mean_x) ** 2 + (row["y"] - mean_y) ** 2 for row in rows
        )),
        "mean_angle_x_deg": mean_ax,
        "mean_angle_y_deg": mean_ay,
        "centered_rms_angle_deg": math.sqrt(statistics.fmean(
            (row["ax"] - mean_ax) ** 2 + (row["ay"] - mean_ay) ** 2 for row in rows
        )),
        "mean_energy_eV": statistics.fmean(energies),
        "sample_sigma_energy_eV": statistics.stdev(energies) if len(energies) > 1 else 0.0,
    }


def compare(log: Path, row_map: Path, canonical_input: Path,
            comsol_exit: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    validate_component_particle_state_csv(canonical_input)
    validate_component_particle_state_csv(comsol_exit)
    mapping = {int(row["solver_row_index"]): int(row["particle_id"])
               for row in _rows(row_map)}
    source = {int(row["particle_id"]): row for row in _rows(canonical_input)}
    simion: list[dict[str, object]] = []
    seen: set[int] = set()
    for match in LOCAL_EXIT.finditer(log.read_text(encoding="utf-8-sig")):
        solver_index = int(match.group(1))
        if solver_index in seen or solver_index not in mapping:
            raise ValueError("SIMION local-exit identity is duplicated or unmapped")
        seen.add(solver_index)
        particle_id = mapping[solver_index]
        mass = float(source[particle_id]["mass_amu"])
        vx, vy, vz = (float(match.group(index)) * 1000.0 for index in (6, 7, 8))
        simion.append({
            "particle_id": particle_id, "instrument_time_us": float(match.group(2)),
            "x": float(match.group(3)), "y": float(match.group(4)),
            "z": float(match.group(5)), "vx": vx, "vy": vy, "vz": vz,
            "ax": math.degrees(math.atan2(vx, vz)),
            "ay": math.degrees(math.atan2(vy, vz)),
            "energy": kinetic_energy_ev(mass, vx, vy, vz),
        })
    comsol: list[dict[str, object]] = []
    for row in _rows(comsol_exit):
        vx, vy, vz = (float(row[f"velocity_{axis}_m_s"]) for axis in "xyz")
        comsol.append({
            "particle_id": int(row["particle_id"]),
            "instrument_time_us": float(row["instrument_time_us"]),
            "x": float(row["position_x_mm"]), "y": float(row["position_y_mm"]),
            "z": float(row["position_z_mm"]), "vx": vx, "vy": vy, "vz": vz,
            "ax": math.degrees(math.atan2(vx, vz)),
            "ay": math.degrees(math.atan2(vy, vz)),
            "energy": float(row["kinetic_energy_eV"]),
        })
    simion_by_id = {int(row["particle_id"]): row for row in simion}
    comsol_by_id = {int(row["particle_id"]): row for row in comsol}
    paired = sorted(set(simion_by_id) & set(comsol_by_id))
    simion_summary = _summary(simion)  # type: ignore[arg-type]
    comsol_summary = _summary(comsol)  # type: ignore[arg-type]
    deltas = {
        key: simion_summary[key] - comsol_summary[key]  # type: ignore[operator]
        for key in (
            "centroid_x_mm", "centroid_y_mm", "centered_rms_radius_mm",
            "mean_angle_x_deg", "mean_angle_y_deg", "centered_rms_angle_deg",
            "mean_energy_eV", "sample_sigma_energy_eV",
        ) if key in simion_summary and key in comsol_summary
    }
    result = {
        "schema_version": 1,
        "role": "rf_oatof_simion_comsol_interface_transport_comparison",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "scope": "real side port plus timed pulse through local accelerator exit; no convergence or qualification claim",
        "source_particles": len(source),
        "simion": simion_summary,
        "comsol": comsol_summary,
        "simion_minus_comsol": deltas,
        "paired_particle_count": len(paired),
        "simion_only_particle_ids": sorted(set(simion_by_id) - set(comsol_by_id)),
        "comsol_only_particle_ids": sorted(set(comsol_by_id) - set(simion_by_id)),
    }
    return result, simion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--row-map", required=True, type=Path)
    parser.add_argument("--canonical-input", required=True, type=Path)
    parser.add_argument("--comsol-exit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--simion-exit", required=True, type=Path)
    args = parser.parse_args()
    result, rows = compare(args.log, args.row_map, args.canonical_input, args.comsol_exit)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with args.simion_exit.open("w", encoding="utf-8", newline="") as handle:
        fields = ["particle_id", "instrument_time_us", "x", "y", "z", "vx", "vy", "vz", "ax", "ay", "energy"]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    print(f"SIMION_INTERFACE_COMPARISON=PASS LOCAL_EXIT={result['simion']['particles']} PAIRED={result['paired_particle_count']}")


if __name__ == "__main__":
    main()
