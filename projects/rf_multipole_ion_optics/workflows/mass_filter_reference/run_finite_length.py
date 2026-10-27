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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy.constants import atomic_mass, elementary_charge, electron_volt

from projects.rf_multipole_ion_optics.core.mass_response import (
    export_response_figure as export_sampled_response_figure,
    prepare_response_analysis,
)

from . import theory


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
DEFAULT_BASELINE = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json"
DEFAULT_RESOLVED = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_mass_filter.json"
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json"
DEFAULT_SOURCE = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json"
MANIFEST_TIMEOUT_S = 60
ANALYSIS_TIMEOUT_S = 120


def load_json(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object from ``path``."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_l1_contract(
    baseline: dict[str, Any], mode: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Validate the L1 inputs and return derived scan and passband values."""
    l0_result = theory.validate_mass_filter_reference(baseline, mode)
    screen = mode.get("functional_screen", {})
    if screen.get("model_level") != "L1":
        raise ValueError("functional_screen.model_level must be L1")
    if screen.get("source_contract") != "../../variants/quadrupole/config/official_particle_source.json":
        raise ValueError("functional_screen.source_contract must reference the official source")
    if int(screen.get("particle_count", 0)) < 64:
        raise ValueError("functional_screen.particle_count must be at least 64")
    if int(screen.get("steps_per_rf_period", 0)) < 40:
        raise ValueError("functional_screen.steps_per_rf_period must be at least 40")
    charge = source.get("charge_state")
    if isinstance(charge, bool) or not isinstance(charge, (int, float)) or charge != 1:
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
        "calibration_mass_Th": theory.mass_to_charge_th(
            float(passband["q_cal"]),
            float(rf["amplitude_V_zero_to_peak_per_group"]),
            float(rf["effective_radius_mm"]),
            float(rf["frequency_Hz"]),
        ),
    }


def _l1_particles_from_release(
    source: dict[str, Any], particle_count: int, random_seed: int
) -> dict[str, np.ndarray]:
    """Project the common source release to the L1 integrator's SI state."""
    from common.ion_release.numpy_box_cone import sample_numpy_box_cone_phase_space

    release = sample_numpy_box_cone_phase_space(
        source=source,
        seed=random_seed,
        particle_count=particle_count,
    )
    return {
        "x_m": release["transverse_1_mm"] * 1e-3,
        "y_m": release["transverse_2_mm"] * 1e-3,
        "energy_j": release["energy_eV"] * electron_volt,
        "direction_x": release["direction_transverse_1"],
        "direction_y": release["direction_transverse_2"],
        "direction_z": release["direction_axial"],
        "rf_phase_rad": release["phase_rad"],
    }


def simulate_mass(
    mass_Th: float,
    particles: dict[str, np.ndarray],
    resolved: dict[str, Any],
    steps_per_rf_period: int,
) -> dict[str, float | int]:
    """Track one mass through the finite ideal rod region and hard ``r0`` aperture."""
    geometry = resolved["geometry_mm"]
    drive = resolved["drive"]
    mass_kg = float(mass_Th) * atomic_mass
    r0_m = float(geometry["inscribed_radius_r0"]) * 1e-3
    rod_length_m = (
        float(geometry["rod_z_max"]) - float(geometry["rod_z_min"])
    ) * 1e-3
    frequency_hz = float(drive["frequency_Hz"])
    omega = 2.0 * math.pi * frequency_hz
    time_step_s = 1.0 / (frequency_hz * steps_per_rf_period)
    dc_v = float(drive["dc_amplitude_V_per_group"])
    rf_v = float(drive["rf_amplitude_V_zero_to_peak_per_group"])

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
    analysis = prepare_response_analysis(rows)
    masses = np.asarray(analysis["mass_samples_Th"], dtype=float)
    transmission = np.asarray(analysis["transmission_fraction_samples"], dtype=float)
    low = float(derived["theory_low_mass_Th"])
    high = float(derived["theory_high_mass_Th"])
    acceptance = mode["functional_screen"]["acceptance"]
    inside = (masses >= low) & (masses <= high)
    if not np.any(inside):
        raise ValueError("mass response has no samples inside the theory passband")
    observed_band = analysis["observed_half_maximum_band_Th"]
    step = float(mode["functional_screen"]["mass_scan_Th"]["step"])
    checks = {
        "peak_transmission": float(np.max(transmission)) >= float(acceptance["minimum_peak_transmission"]),
        "inside_band_transmission": float(np.min(transmission[inside])) >= float(acceptance["minimum_inside_band_transmission"]),
        "outside_endpoint_rejection": max(float(transmission[0]), float(transmission[-1])) <= float(acceptance["maximum_endpoint_transmission"]),
        "low_boundary_alignment": observed_band is not None and abs(observed_band[0] - low) <= step,
        "high_boundary_alignment": observed_band is not None and abs(observed_band[1] - high) <= step,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "peak_mass_Th": analysis["peak_mass_Th"],
        "peak_transmission": analysis["peak_transmission"],
        "minimum_inside_theory_band_transmission": float(np.min(transmission[inside])),
        "maximum_scan_endpoint_transmission": max(float(transmission[0]), float(transmission[-1])),
        "theory_passband_Th": [low, high],
        "observed_half_maximum_band_Th": observed_band,
        "mass_step_Th": step,
        "sampled_response_analysis": analysis,
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
    low, high = metrics["theory_passband_Th"]
    export_sampled_response_figure(
        path, rows, (low, high), "Finite-length L1", metrics["sampled_response_analysis"],
    )


def _prepare_analysis_request(inputs: Path, results: Path) -> tuple[Path, dict[str, str]]:
    """Bind this workflow's analysis closure to the existing frozen-package runner."""
    from common.contracts.frozen_inputs import freeze_file

    prefix = "projects/rf_multipole_ion_optics/"
    support_files = [
        "common/contracts/run_artifact_support.ps1",
        "common/require_powershell7.ps1", "common/host_execution_lease.ps1",
        prefix + "runtime/frozen_python_package.ps1",
    ]
    support_root = inputs / "analysis_support"
    frozen_inputs: dict[str, str] = {}
    for relative in support_files:
        destination = support_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        record = freeze_file(REPOSITORY_ROOT / relative, destination)
        frozen_inputs["analysis_support_" + Path(relative).stem] = record["path"]
    relative_paths = [
        prefix + "workflows/__init__.py",
        prefix + "workflows/mass_filter_reference/__init__.py",
        prefix + "workflows/mass_filter_reference/run_finite_length.py",
        prefix + "workflows/mass_filter_reference/theory.py",
        prefix + "core/__init__.py", prefix + "core/family_contract.py",
        prefix + "core/mass_response.py", prefix + "core/paired_mass_scan.py",
        prefix + "config/contracts/family_contract.json",
        "common/analysis/peak_metrics.py", "common/contracts/file_identity.py",
    ]
    request = {
        "schema_version": 1, "role": "rf_mass_filter_l1_frozen_analysis_request",
        "source_root": str(REPOSITORY_ROOT), "code_root": str(inputs / "analysis_code"),
        "artifact_support": frozen_inputs["analysis_support_run_artifact_support"],
        "package_support": frozen_inputs["analysis_support_frozen_python_package"],
        "python": sys.executable, "relative_paths": relative_paths,
        "required_modules": [path[:-3].replace("/", ".") for path in relative_paths
                             if path.endswith(".py") and not path.endswith("/__init__.py")],
        "module": "projects.rf_multipole_ion_optics.workflows.mass_filter_reference.run_finite_length",
        "arguments": [
            "--analyze-response", str(inputs / "mass_response_for_analysis.csv"),
            "--baseline", str(inputs / "baseline.json"),
            "--mode", str(inputs / "mass_filter_reference.json"),
            "--source", str(inputs / "official_particle_source.json"),
            "--analysis-metrics", str(results / "mass-filter__functional-metrics.json"),
            "--analysis-figure", str(results / "mass-response__passband.png"),
        ],
        "forbidden_roots": [str(REPOSITORY_ROOT), str(PROJECT_ROOT)],
        "package_receipt": str(inputs / "analysis_package.json"),
        "execution_receipt": str(results / "analysis_execution.json"),
        "timeout_s": ANALYSIS_TIMEOUT_S,
    }
    path = inputs / "analysis_request.json"
    path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    frozen_inputs["analysis_request"] = str(path)
    return path, frozen_inputs


def _invoke_analysis_stage(request_path: Path, *, prepare_only: bool) -> dict[str, Any]:
    """Use the existing verified-copy and isolated-module implementation unchanged."""
    command = r"""
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$request = Get-Content -LiteralPath $env:RF_MASS_RESPONSE_REQUEST -Raw | ConvertFrom-Json
. $request.artifact_support
. $request.package_support
if ($env:RF_MASS_RESPONSE_PREPARE -eq '1') {
    $package = New-FrozenPythonPackage -SourceRoot $request.source_root `
        -CodeRoot $request.code_root -RelativePaths $request.relative_paths
    $environment = Invoke-IsolatedFrozenPythonModule -Python $request.python `
        -Package $package -Module $request.module -Arguments @('--help') `
        -DistributionNames @('numpy','scipy','matplotlib') `
        -RequiredModuleNames $request.required_modules `
        -ForbiddenRoots $request.forbidden_roots -ProbeOnly
    @{package=$package;environment=$environment} | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $request.package_receipt -Encoding utf8
} else {
    $prepared = Get-Content -LiteralPath $request.package_receipt -Raw | ConvertFrom-Json
    $environment = Invoke-IsolatedFrozenPythonModule -Python $request.python `
        -Package $prepared.package -Module $request.module -Arguments $request.arguments `
        -DistributionNames @('numpy','scipy','matplotlib') `
        -RequiredModuleNames $request.required_modules -ForbiddenRoots $request.forbidden_roots
    $environment | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $request.execution_receipt -Encoding utf8
}
"""
    request = load_json(request_path)
    environment = {**os.environ, "RF_MASS_RESPONSE_REQUEST": str(request_path),
                   "RF_MASS_RESPONSE_PREPARE": "1" if prepare_only else "0"}
    try:
        subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command], env=environment,
            cwd=request_path.parent, check=True, capture_output=True, text=True, encoding="utf-8",
            timeout=request["timeout_s"],
        )
    except subprocess.CalledProcessError as error:
        stage = "prepare" if prepare_only else "execute"
        raise RuntimeError(f"Frozen L1 analysis {stage} failed: {(error.stderr or error.stdout).strip()}") from error
    return load_json(Path(request["package_receipt" if prepare_only else "execution_receipt"]))


def analyze_response_file(
    response_path: Path, baseline_path: Path, mode_path: Path, source_path: Path,
    metrics_path: Path, figure_path: Path,
) -> dict[str, Any]:
    """Analyze the frozen L1 CSV once; the JSON and figure share that result."""
    baseline, mode, source = (load_json(path) for path in (baseline_path, mode_path, source_path))
    derived = validate_l1_contract(baseline, mode, source)
    with response_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    screen = mode["functional_screen"]
    if [float(row["mass_Th"]) for row in rows] != derived["masses_Th"].tolist():
        raise ValueError("L1 response mass grid differs from its frozen mode")
    expected_count = int(screen["particle_count"])
    if any(int(row["particles"]) != expected_count for row in rows):
        raise ValueError("L1 response particle count differs from its frozen mode")
    if any(float(row["transmission_fraction"]) != int(row["transmitted"]) / expected_count for row in rows):
        raise ValueError("L1 response fraction differs from transmitted/particles")
    metrics = evaluate_response(rows, derived, mode)
    metrics.update({
        "schema_version": 1, "role": "quadrupole_mass_filter_l1_metrics", "model_level": "L1",
        "particle_count_per_mass": int(screen["particle_count"]),
        "random_seed": int(screen["random_seed"]),
        "calibration_mass_Th": float(derived["calibration_mass_Th"]),
        "claim_limit": "Finite-length ideal-field functional screen only; no fringe field or solver qualification.",
    })
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    export_response_figure(figure_path, rows, metrics)
    return metrics


def run(
    baseline_path: Path,
    resolved_path: Path,
    mode_path: Path,
    source_path: Path,
    run_id: str,
    artifact_project_root: Path,
) -> Path:
    """Execute one immutable L1 run and write its complete provenance triplet."""
    from common.contracts.frozen_inputs import freeze_file

    baseline = load_json(baseline_path)
    resolved = load_json(resolved_path)
    mode = load_json(mode_path)
    source = load_json(source_path)
    derived = validate_l1_contract(baseline, mode, source)
    destination = artifact_project_root.resolve() / "runs" / run_id
    if destination.exists():
        raise FileExistsError(destination)
    results = destination / "results"
    inputs = destination / "inputs"
    results.mkdir(parents=True)
    inputs.mkdir()
    frozen_baseline = inputs / "baseline.json"
    frozen_resolved = inputs / "resolved_design_mass_filter.json"
    frozen_mode = inputs / "mass_filter_reference.json"
    frozen_source = inputs / "official_particle_source.json"
    for source_file, frozen_file in (
        (baseline_path, frozen_baseline), (resolved_path, frozen_resolved),
        (mode_path, frozen_mode), (source_path, frozen_source),
    ):
        freeze_file(source_file, frozen_file)
    request_path, analysis_inputs = _prepare_analysis_request(inputs, results)
    frozen_analysis = _invoke_analysis_stage(request_path, prepare_only=True)
    for entry in frozen_analysis["package"]["files"]:
        key = "analysis_code_" + entry["relative_path"].replace("/", "_").replace(".", "_")
        analysis_inputs[key] = entry["path"]
    analysis_inputs["analysis_package"] = str(inputs / "analysis_package.json")
    baseline, resolved, mode, source = (
        load_json(path) for path in (frozen_baseline, frozen_resolved, frozen_mode, frozen_source)
    )
    derived = validate_l1_contract(baseline, mode, source)
    screen = mode["functional_screen"]
    particles = _l1_particles_from_release(
        source, int(screen["particle_count"]), int(screen["random_seed"]),
    )
    frozen_workflow = Path(frozen_analysis["package"]["code_root"]) / (
        "projects/rf_multipole_ion_optics/workflows/mass_filter_reference"
    )

    rows = [
        simulate_mass(float(mass), particles, resolved, int(screen["steps_per_rf_period"]))
        for mass in derived["masses_Th"]
    ]
    response_path = results / "mass-response__finite-length.csv"
    metrics_path = results / "mass-filter__functional-metrics.json"
    figure_path = results / "mass-response__passband.png"
    write_response_csv(response_path, rows)
    frozen_response = inputs / "mass_response_for_analysis.csv"
    freeze_file(response_path, frozen_response)
    analysis_inputs["response_for_analysis"] = str(frozen_response)
    execution = _invoke_analysis_stage(request_path, prepare_only=False)
    metrics = load_json(metrics_path)

    run_config = destination / "run_config.json"
    run_config.write_text(json.dumps({
        "schema_version": 1,
        "role": "rf_quadrupole_mass_filter_l1_run_config",
        "run_id": run_id,
        "project": "rf_multipole_ion_optics",
        "mode": "mass_filter_reference",
        "project_root": str(REPOSITORY_ROOT),
        "inputs": {
            "baseline": str(frozen_baseline),
            "resolved_design": str(frozen_resolved),
            "mode": str(frozen_mode),
            "source": str(frozen_source),
            "runner": str(frozen_workflow / "run_finite_length.py"),
            "l0_reference": str(frozen_workflow / "theory.py"),
            **analysis_inputs,
        },
        "frozen_python_analysis": {"package": frozen_analysis["package"], "environment": execution},
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
    for output in (response_path, metrics_path, figure_path, summary, results / "analysis_execution.json"):
        command.extend(("--output", str(output)))
    subprocess.run(command, check=True, cwd=REPOSITORY_ROOT, timeout=MANIFEST_TIMEOUT_S)
    if metrics["status"] != "PASS":
        raise RuntimeError("mass-filter L1 functional gate failed")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--resolved-design", type=Path, default=DEFAULT_RESOLVED)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--run-id")
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--analyze-response", type=Path, help="Analyze an existing frozen L1 response only")
    parser.add_argument("--analysis-metrics", type=Path)
    parser.add_argument("--analysis-figure", type=Path)
    parser.add_argument(
        "--artifact-project-root",
        type=Path,
        default=WORKSPACE_ROOT / "artifacts" / "projects" / "rf_multipole_ion_optics",
    )
    args = parser.parse_args()
    if args.analyze_response is not None:
        if args.run_id or args.check_contract or args.analysis_metrics is None or args.analysis_figure is None:
            parser.error("--analyze-response requires only analysis outputs, not --run-id or --check-contract")
        metrics = analyze_response_file(
            args.analyze_response, args.baseline, args.mode, args.source,
            args.analysis_metrics, args.analysis_figure,
        )
        print(f"QUADRUPOLE_MASS_FILTER_L1_ANALYSIS=COMPLETED FUNCTIONAL={metrics['status']}")
        return
    if args.check_contract:
        validate_l1_contract(load_json(args.baseline), load_json(args.mode), load_json(args.source))
        print("QUADRUPOLE_MASS_FILTER_L1_CONTRACT=PASS")
        return
    if not args.run_id:
        parser.error("--run-id is required unless --check-contract is used")
    destination = run(
        args.baseline,
        args.resolved_design,
        args.mode,
        args.source,
        args.run_id,
        args.artifact_project_root,
    )
    print(f"QUADRUPOLE_MASS_FILTER_L1=PASS RUN={destination.name}")


if __name__ == "__main__":
    main()
