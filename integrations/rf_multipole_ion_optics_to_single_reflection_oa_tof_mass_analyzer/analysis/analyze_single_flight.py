"""Extract particle-resolved checkpoints and detector metrics from one SIMION flight."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np

from common.contracts.particle_physics import kinetic_energy_ev
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import compute_peak_metrics


STATE_PATTERN = re.compile(
    r"TRACE: (?P<event>source_release|single_flight_handoff|pre_pulse_state|local_accelerator_exit) "
    r"ion=(?P<ion>\d+) instrument_time_us=(?P<t>[-+0-9.eE]+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+)"
)
DETECTOR_PATTERN = re.compile(
    r"TRACE: detector_crossing ion=(?P<ion>\d+) t=(?P<t>[-+0-9.eE]+) "
    r"x=(?P<x>[-+0-9.eE]+) y=(?P<y>[-+0-9.eE]+) z=(?P<z>[-+0-9.eE]+)"
)
PULSE_PATTERN = re.compile(r"TRACE: handoff_pulse_on(?: ion=\d+)? instrument_time_us=(?P<t>[-+0-9.eE]+)")
COLUMNS = [
    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm",
    "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "kinetic_energy_eV",
]


def analyze(
    log_path: Path,
    launched: int,
    mass_amu: float,
    geometry_path: Path | None = None,
    pulse_time_us: float | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    pulse_times: list[float] = []
    for line in log_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = STATE_PATTERN.search(line)
        if match:
            event = {
                "source_release": "source_release",
                "single_flight_handoff": "multipole_handoff",
                "pre_pulse_state": "pre_pulse_state",
                "local_accelerator_exit": "local_accelerator_exit",
            }[match["event"]]
            key = (int(match["ion"]), event)
            if key in seen:
                raise ValueError(f"duplicate checkpoint: particle={key[0]} event={event}")
            seen.add(key)
            vx = float(match["vx"])
            vy = float(match["vy"])
            vz = float(match["vz"])
            rows.append({
                "particle_id": key[0], "event": event, "instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": vx, "vy_mm_per_us": vy, "vz_mm_per_us": vz,
                "kinetic_energy_eV": kinetic_energy_ev(
                    mass_amu, 1000.0 * vx, 1000.0 * vy, 1000.0 * vz
                ),
            })
            continue
        match = DETECTOR_PATTERN.search(line)
        if match:
            key = (int(match["ion"]), "detector_crossing")
            if key in seen:
                raise ValueError(f"duplicate detector crossing: particle={key[0]}")
            seen.add(key)
            rows.append({
                "particle_id": key[0], "event": key[1], "instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": "", "vy_mm_per_us": "", "vz_mm_per_us": "",
                "kinetic_energy_eV": "",
            })
            continue
        match = PULSE_PATTERN.search(line)
        if match:
            pulse_times.append(float(match["t"]))
    rows.sort(key=lambda row: (int(row["particle_id"]), str(row["event"])))
    counts = {event: sum(row["event"] == event for row in rows) for event in (
        "source_release", "multipole_handoff", "pre_pulse_state",
        "local_accelerator_exit", "detector_crossing",
    )}
    if launched < 1 or any(int(row["particle_id"]) < 1 or int(row["particle_id"]) > launched for row in rows):
        raise ValueError("logged particle identity is outside the launched mother sample")
    detector_times = np.asarray([float(row["instrument_time_us"]) for row in rows if row["event"] == "detector_crossing"])
    resolution = None
    if detector_times.size >= 3:
        peak, _ = compute_peak_metrics(detector_times, mass_amu)
        resolution = peak
    injection_energy_validation = None
    if geometry_path is not None:
        geometry = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
        dimensions = geometry["geometry_mm"]
        axis_x = float(geometry["coordinate_convention"]["accelerator_axis_x"])
        repeller_z = float(dimensions["accelerator_repeller_z"])
        grid1_z = float(dimensions["accelerator_grid1_z"])
        bore_half = float(dimensions["accelerator_bore_half"])
        samples = [row for row in rows if row["event"] == "pre_pulse_state"]
        if not samples:
            raise ValueError("injection energy validation requires pre_pulse_state samples")
        inside = [
            abs(float(row["x_mm"]) - axis_x) < bore_half
            and abs(float(row["y_mm"])) < bore_half
            and repeller_z < float(row["z_mm"]) < grid1_z
            for row in samples
        ]
        if not all(inside):
            raise ValueError("pre_pulse_state energy sample is outside the accelerator interior")
        if pulse_time_us is None or any(
            float(row["instrument_time_us"]) > pulse_time_us + 1e-9
            for row in samples
        ):
            raise ValueError("pre_pulse_state energy sample is not before the accelerator pulse")
        energies = np.asarray(
            [float(row["kinetic_energy_eV"]) for row in samples], dtype=float
        )
        target = geometry.get("single_flight_layout_derivation", {}).get(
            "target_injection_energy_eV"
        )
        injection_energy_validation = {
            "sampling_event": "pre_pulse_state",
            "sampling_scope": "oatof_accelerator_stage1_interior_before_pulse",
            "sample_count": len(samples),
            "all_samples_inside_accelerator_stage1": True,
            "all_samples_at_or_before_pulse": True,
            "target_kinetic_energy_eV": target,
            "mean_kinetic_energy_eV": float(np.mean(energies)),
            "sample_sigma_kinetic_energy_eV": float(np.std(energies, ddof=1)) if len(energies) > 1 else 0.0,
            "minimum_kinetic_energy_eV": float(np.min(energies)),
            "maximum_kinetic_energy_eV": float(np.max(energies)),
            "mean_target_error_eV": None if target is None else float(np.mean(energies) - float(target)),
            "terminal_or_handoff_energy_is_target_validation": False,
        }
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_simion_single_flight_summary",
        "status": "success",
        "census": {"launched": launched, **counts},
        "transmission": {
            "multipole_handoff_fraction": counts["multipole_handoff"] / launched,
            "detector_fraction": counts["detector_crossing"] / launched,
        },
        "pulse_first_observed_us": min(pulse_times) if pulse_times else None,
        "instrument_clock_peak": resolution,
        "instrument_clock_peak_is_resolution_claim": False,
        "injection_energy_validation": injection_energy_validation,
        "spatial_six_panel": "results/single_flight_spatial_six_panel.png",
        "formal_gate_passed": False,
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--launched", required=True, type=int)
    parser.add_argument("--mass-amu", required=True, type=float)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--pulse-time-us", type=float)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    rows, summary = analyze(
        args.log, args.launched, args.mass_amu, args.geometry, args.pulse_time_us
    )
    args.checkpoints.parent.mkdir(parents=True, exist_ok=True)
    with args.checkpoints.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_ANALYSIS=PASS HANDOFF={summary['census']['multipole_handoff']} DETECTOR={summary['census']['detector_crossing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
