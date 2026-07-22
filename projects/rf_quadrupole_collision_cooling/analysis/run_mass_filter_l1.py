"""Run a solver-free finite-length mass-filter functional screen.

The transverse field is the ideal linear quadrupole field documented in
``docs/multipoles``. Geometry, voltages, source envelope, scan definition and
acceptance thresholds come from project contracts. This L1 screen proves only
that the shared finite rod geometry can express a mass passband; it does not
model fringe fields or qualify a COMSOL/SIMION implementation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from scipy.constants import atomic_mass, elementary_charge, electron_volt

try:
    from . import quadrupole_l0 as l0
except ImportError:  # Direct script execution keeps the analysis directory importable.
    import quadrupole_l0 as l0


matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "baseline.json"
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"
DEFAULT_SOURCE = PROJECT_ROOT / "config" / "official_particle_source.json"
MANIFEST_TIMEOUT_S = 60


def load_json(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object from ``path``."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_l1_contract(
    baseline: dict[str, Any], mode: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Validate the L1 inputs and return derived scan and passband values."""
    l0_result = l0.validate_mass_filter_reference(baseline, mode)
    screen = mode.get("functional_screen", {})
    if screen.get("model_level") != "L1":
        raise ValueError("functional_screen.model_level must be L1")
    if screen.get("source_contract") != "../../official_particle_source.json":
        raise ValueError("functional_screen.source_contract must reference the official source")
    if int(screen.get("particle_count", 0)) < 64:
        raise ValueError("functional_screen.particle_count must be at least 64")
    if int(screen.get("steps_per_rf_period", 0)) < 40:
        raise ValueError("functional_screen.steps_per_rf_period must be at least 40")
    if int(source.get("charge_state", 0)) != 1:
        raise ValueError("L1 reference currently requires singly charged positive ions")

    scan = screen.get("mass_scan_Th", {})
    start = float(scan.get("min", math.nan))
    stop = float(scan.get("max", math.nan))
    step = float(scan.get("step", math.nan))
    if not all(math.isfinite(value) for value in (start, stop, step)) or not start < stop or step <= 0:
        raise ValueError("functional_screen.mass_scan_Th must define finite min < max and step > 0")
    masses = np.arange(start, stop + 0.5 * step, step, dtype=float)

    rf = mode["rf"]
    q_at_tune = float(l0_result["q_at_tune_mass"])
    passband = l0_result["ideal_scanline"]
    tune_mass = float(rf["tune_mass_Th"])
    theory_low = tune_mass * q_at_tune / float(passband["q_out"])
    theory_high = tune_mass * q_at_tune / float(passband["q_in"])
    if not start < theory_low < theory_high < stop:
        raise ValueError("L1 mass scan must bracket both ideal passband boundaries")
    return {
        "masses_Th": masses,
        "theory_low_mass_Th": theory_low,
        "theory_high_mass_Th": theory_high,
        "calibration_mass_Th": l0.mass_to_charge_th(
            float(passband["q_cal"]),
            float(rf["amplitude_V_zero_to_peak_per_group"]),
            float(rf["effective_radius_mm"]),
            float(rf["frequency_Hz"]),
        ),
    }


def generate_particles(
    source: dict[str, Any], particle_count: int, random_seed: int
) -> dict[str, np.ndarray]:
    """Sample the documented source envelope deterministically in SI units."""
    rng = np.random.default_rng(random_seed)
    position = source["position_mm"]
    energy = source["kinetic_energy_eV"]
    half_angle = math.radians(float(source["direction"]["half_angle_deg"]))
    cos_theta = rng.uniform(math.cos(half_angle), 1.0, particle_count)
    sin_theta = np.sqrt(1.0 - cos_theta**2)
    azimuth = rng.uniform(0.0, 2.0 * math.pi, particle_count)
    return {
        "x_m": rng.uniform(
            float(position["transverse_1"]["min"]),
            float(position["transverse_1"]["max"]),
            particle_count,
        ) * 1e-3,
        "y_m": rng.uniform(
            float(position["transverse_2"]["min"]),
            float(position["transverse_2"]["max"]),
            particle_count,
        ) * 1e-3,
        "energy_j": rng.uniform(
            float(energy["min"]), float(energy["max"]), particle_count
        ) * electron_volt,
        "direction_x": sin_theta * np.cos(azimuth),
        "direction_y": sin_theta * np.sin(azimuth),
        "direction_z": cos_theta,
        "rf_phase_rad": rng.uniform(0.0, 2.0 * math.pi, particle_count),
    }


def simulate_mass(
    mass_Th: float,
    particles: dict[str, np.ndarray],
    baseline: dict[str, Any],
    mode: dict[str, Any],
    steps_per_rf_period: int,
) -> dict[str, float | int]:
    """Track one mass through the finite ideal rod region and hard ``r0`` aperture."""
    geometry = baseline["geometry_mm"]
    rf = mode["rf"]
    mass_kg = float(mass_Th) * atomic_mass
    r0_m = float(geometry["field_radius_r0"]) * 1e-3
    rod_length_m = float(geometry["rod_length"]) * 1e-3
    frequency_hz = float(rf["frequency_Hz"])
    omega = 2.0 * math.pi * frequency_hz
    time_step_s = 1.0 / (frequency_hz * steps_per_rf_period)
    dc_v = float(rf["dc_amplitude_V_per_group"])
    rf_v = float(rf["amplitude_V_zero_to_peak_per_group"])

    speed = np.sqrt(2.0 * particles["energy_j"] / mass_kg)
    x = particles["x_m"].copy()
    y = particles["y_m"].copy()
    z = np.zeros_like(x)
    vx = speed * particles["direction_x"]
    vy = speed * particles["direction_y"]
    vz = speed * particles["direction_z"]
    phase = particles["rf_phase_rad"]
    alive = np.ones(x.size, dtype=bool)
    maximum_steps = math.ceil(rod_length_m / float(np.min(vz)) / time_step_s)
    acceleration_scale = 2.0 * elementary_charge / (mass_kg * r0_m**2)
    time_s = 0.0

    for _ in range(maximum_steps):
        active = alive & (z < rod_length_m)
        if not np.any(active):
            break
        voltage = dc_v - rf_v * np.cos(omega * time_s + phase)
        ax = -acceleration_scale * voltage * x
        ay = acceleration_scale * voltage * y
        vx[active] += 0.5 * time_step_s * ax[active]
        vy[active] += 0.5 * time_step_s * ay[active]
        x[active] += time_step_s * vx[active]
        y[active] += time_step_s * vy[active]
        z[active] += time_step_s * vz[active]
        time_s += time_step_s
        voltage = dc_v - rf_v * np.cos(omega * time_s + phase)
        ax = -acceleration_scale * voltage * x
        ay = acceleration_scale * voltage * y
        vx[active] += 0.5 * time_step_s * ax[active]
        vy[active] += 0.5 * time_step_s * ay[active]
        alive &= x**2 + y**2 < r0_m**2

    transmitted = int(np.count_nonzero(alive & (z >= rod_length_m)))
    return {
        "mass_Th": float(mass_Th),
        "particles": int(x.size),
        "transmitted": transmitted,
        "transmission_fraction": transmitted / int(x.size),
    }


def evaluate_response(
    rows: list[dict[str, float | int]], derived: dict[str, Any], mode: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate the frozen functional acceptance rules against a mass response."""
    masses = np.asarray([row["mass_Th"] for row in rows], dtype=float)
    transmission = np.asarray([row["transmission_fraction"] for row in rows], dtype=float)
    low = float(derived["theory_low_mass_Th"])
    high = float(derived["theory_high_mass_Th"])
    acceptance = mode["functional_screen"]["acceptance"]
    inside = (masses >= low) & (masses <= high)
    half_maximum = 0.5 * float(np.max(transmission))
    half_indices = np.flatnonzero(transmission >= half_maximum)
    observed_low = float(masses[half_indices[0]])
    observed_high = float(masses[half_indices[-1]])
    step = float(mode["functional_screen"]["mass_scan_Th"]["step"])
    checks = {
        "peak_transmission": float(np.max(transmission)) >= float(acceptance["minimum_peak_transmission"]),
        "inside_band_transmission": float(np.min(transmission[inside])) >= float(acceptance["minimum_inside_band_transmission"]),
        "outside_endpoint_rejection": max(float(transmission[0]), float(transmission[-1])) <= float(acceptance["maximum_endpoint_transmission"]),
        "low_boundary_alignment": abs(observed_low - low) <= step,
        "high_boundary_alignment": abs(observed_high - high) <= step,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "peak_mass_Th": float(masses[int(np.argmax(transmission))]),
        "peak_transmission": float(np.max(transmission)),
        "minimum_inside_theory_band_transmission": float(np.min(transmission[inside])),
        "maximum_scan_endpoint_transmission": max(float(transmission[0]), float(transmission[-1])),
        "theory_passband_Th": [low, high],
        "observed_half_maximum_band_Th": [observed_low, observed_high],
        "mass_step_Th": step,
    }


def write_response_csv(path: Path, rows: list[dict[str, float | int]]) -> None:
    """Write the complete sampled mass response."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_response_figure(
    path: Path, rows: list[dict[str, float | int]], metrics: dict[str, Any]
) -> None:
    """Export the L1 response as an accessible report-profile PNG."""
    masses = [float(row["mass_Th"]) for row in rows]
    transmission = [float(row["transmission_fraction"]) for row in rows]
    low, high = metrics["theory_passband_Th"]
    with plt.rc_context({"font.size": 8, "axes.labelsize": 9, "legend.fontsize": 8}):
        figure, axis = plt.subplots(figsize=(160 / 25.4, 90 / 25.4), constrained_layout=True)
        axis.axvspan(low, high, color="#56B4E9", alpha=0.22, label="Ideal Mathieu passband")
        axis.plot(masses, transmission, color="#0072B2", marker="o", markersize=3.5, linewidth=1.2, label="Finite-length L1")
        axis.set_xlabel("Mass-to-charge ratio (Th)")
        axis.set_ylabel("Transmission fraction")
        axis.set_ylim(-0.03, 1.03)
        axis.grid(axis="y", linewidth=0.5, alpha=0.3)
        axis.legend(frameon=False, loc="lower center")
        figure.savefig(path, format="png", dpi=240, facecolor="white")
        plt.close(figure)


def run(
    baseline_path: Path, mode_path: Path, source_path: Path, run_id: str, artifact_project_root: Path
) -> Path:
    """Execute one immutable L1 run and write its complete provenance triplet."""
    baseline = load_json(baseline_path)
    mode = load_json(mode_path)
    source = load_json(source_path)
    derived = validate_l1_contract(baseline, mode, source)
    screen = mode["functional_screen"]
    particles = generate_particles(source, int(screen["particle_count"]), int(screen["random_seed"]))
    destination = artifact_project_root.resolve() / "runs" / run_id
    if destination.exists():
        raise FileExistsError(destination)
    results = destination / "results"
    inputs = destination / "inputs"
    results.mkdir(parents=True)
    inputs.mkdir()
    frozen_baseline = inputs / "baseline.json"
    frozen_mode = inputs / "mass_filter_reference.json"
    frozen_source = inputs / "official_particle_source.json"
    frozen_runner = inputs / "run_mass_filter_l1.py.txt"
    frozen_l0 = inputs / "quadrupole_l0.py.txt"
    shutil.copy2(baseline_path, frozen_baseline)
    shutil.copy2(mode_path, frozen_mode)
    shutil.copy2(source_path, frozen_source)
    shutil.copy2(Path(__file__), frozen_runner)
    shutil.copy2(Path(l0.__file__), frozen_l0)

    rows = [
        simulate_mass(float(mass), particles, baseline, mode, int(screen["steps_per_rf_period"]))
        for mass in derived["masses_Th"]
    ]
    metrics = evaluate_response(rows, derived, mode)
    metrics.update({
        "schema_version": 1,
        "role": "quadrupole_mass_filter_l1_metrics",
        "model_level": "L1",
        "particle_count_per_mass": int(screen["particle_count"]),
        "random_seed": int(screen["random_seed"]),
        "calibration_mass_Th": float(derived["calibration_mass_Th"]),
        "claim_limit": "Finite-length ideal-field functional screen only; no fringe field or solver qualification.",
    })
    response_path = results / "mass-response__finite-length.csv"
    metrics_path = results / "mass-filter__functional-metrics.json"
    figure_path = results / "mass-response__passband.png"
    write_response_csv(response_path, rows)
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    export_response_figure(figure_path, rows, metrics)

    run_config = destination / "run_config.json"
    run_config.write_text(json.dumps({
        "schema_version": 1,
        "run_id": run_id,
        "project": "rf_quadrupole_collision_cooling",
        "mode": "mass_filter_reference",
        "project_root": str(REPOSITORY_ROOT),
        "inputs": {
            "baseline": str(frozen_baseline),
            "mode": str(frozen_mode),
            "source": str(frozen_source),
            "runner": str(frozen_runner),
            "l0_reference": str(frozen_l0),
        },
        "parameters": {"model_level": "L1", "solver_rerun": False},
        "formal_gate_passed": False,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = destination / "summary.json"
    summary.write_text(json.dumps({
        "schema_version": 1,
        "role": "quadrupole_mass_filter_l1_run_summary",
        "status": "success" if metrics["status"] == "PASS" else "failed",
        "functional_gate": metrics["status"],
        "model_level": "L1",
        "result": "results/mass-filter__functional-metrics.json",
        "figure": "results/mass-response__passband.png",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "common" / "contracts" / "write_run_manifest.py"),
        "--run-config", str(run_config),
        "--manifest", str(destination / "run_manifest.json"),
        "--status", "success" if metrics["status"] == "PASS" else "failed",
        "--software", "Python 3.11 solver-free quadrupole L1",
    ]
    for output in (response_path, metrics_path, figure_path, summary):
        command.extend(("--output", str(output)))
    subprocess.run(command, check=True, cwd=REPOSITORY_ROOT, timeout=MANIFEST_TIMEOUT_S)
    if metrics["status"] != "PASS":
        raise RuntimeError("mass-filter L1 functional gate failed")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--run-id")
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument(
        "--artifact-project-root",
        type=Path,
        default=WORKSPACE_ROOT / "artifacts" / "projects" / "rf_quadrupole_collision_cooling",
    )
    args = parser.parse_args()
    if args.check_contract:
        validate_l1_contract(load_json(args.baseline), load_json(args.mode), load_json(args.source))
        print("QUADRUPOLE_MASS_FILTER_L1_CONTRACT=PASS")
        return
    if not args.run_id:
        parser.error("--run-id is required unless --check-contract is used")
    destination = run(args.baseline, args.mode, args.source, args.run_id, args.artifact_project_root)
    print(f"QUADRUPOLE_MASS_FILTER_L1=PASS RUN={destination.name}")


if __name__ == "__main__":
    main()
