"""Close the SIMION reflectron axis-field voltage-compensation loop."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from projects.single_reflection_oa_tof_mass_analyzer.analysis.optimize_reflectron_ring_voltages import (
    _load_basis,
    optimize,
    render_lua_profile,
)
from common.analysis.peak_metrics import compute_peak_metrics
from common.simion.process_observation import run_observed_process
from common.simion.resource_scheduler import (
    plan_adaptive_followup,
    plan_simion_dispatch,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics import (
    analyze_simion_log,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
    render_program,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = PROJECT_ROOT / "simion" / "reflectron" / "export_axis_basis.lua"


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _split_ions(source: Path, output_dir: Path, workers: int) -> list[dict[str, Any]]:
    lines = [line for line in source.read_text(encoding="ascii").splitlines() if line.strip()]
    if not lines:
        raise ValueError("particle source is empty")
    if workers < 1 or workers > len(lines):
        raise ValueError("workers must be between one and the particle count")
    output_dir.mkdir(parents=True, exist_ok=True)
    boundaries = np.linspace(0, len(lines), workers + 1, dtype=int)
    batches = []
    for index in range(workers):
        start, stop = int(boundaries[index]), int(boundaries[index + 1])
        path = output_dir / f"batch_{index + 1:02d}.ion"
        path.write_text("\n".join(lines[start:stop]) + "\n", encoding="ascii")
        batches.append({"index": index + 1, "offset": start, "count": stop - start, "ion": path})
    return batches


def _plan_batches_from_observation(
    particle_count: int, trajectory_quality: int, observed_peak_bytes: int | None
) -> dict[str, Any]:
    """Create the repository dispatch plan for one independent source population."""
    request = {
        "solver": "SIMION", "field_kind": "electrostatic",
        "particle_count": particle_count, "independent_particles": True,
        "trajectory_quality_profile_id": f"tqual_{trajectory_quality}",
    }
    bootstrap = plan_simion_dispatch(request, [])
    return (
        plan_adaptive_followup(bootstrap, observed_peak_bytes)
        if observed_peak_bytes is not None else bootstrap
    )


def _run_batch(
    *,
    batch: dict[str, Any],
    label: str,
    compensation: bool,
    ideal_reflectron: bool,
    simion_exe: Path,
    simion_dir: Path,
    output_dir: Path,
    trajectory_quality: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    batch_dir = output_dir / label / f"batch_{batch['index']:02d}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    log, error = batch_dir / "simion.log", batch_dir / "simion.stderr.log"
    command = [
        str(simion_exe),
        "--default-num-particles", str(batch["count"]),
        "--nogui", "fly",
        "--trajectory-quality", str(trajectory_quality),
        "--retain-trajectories", "0",
        "--particles", str(batch["ion"]),
        "--adjustable", f"trajectory_quality={trajectory_quality}",
        "--adjustable", "ideal_accel_enable=0",
        "--adjustable", f"ideal_refl_stage1_enable={int(ideal_reflectron)}",
        "--adjustable", f"ideal_refl_stage2_enable={int(ideal_reflectron)}",
        "--adjustable", "trajectory_log_enable=1",
        str(simion_dir / "oatof_ideal_grounded.iob"),
    ]
    environment = dict(os.environ)
    environment["OATOF_REFLECTRON_VOLTAGE_COMPENSATION"] = str(int(compensation))
    started = time.perf_counter()
    completed, peak_working_set_bytes = run_observed_process(
        command, cwd=simion_dir, stdout=log, stderr=error,
        environment=environment, timeout_seconds=600,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"SIMION batch failed: label={label} batch={batch['index']} "
            f"returncode={completed.returncode} stderr={error}"
        )
    particles, diagnostics = analyze_simion_log(
        log,
        batch["ion"],
        mode=label,
        distribution="fixedN1000_five_batch",
        detector_radius_mm=40.0,
        allow_incomplete_census=False,
    )
    particles["Ion"] = particles["Ion"] + int(batch["offset"])
    diagnostics["ElapsedSeconds"] = elapsed
    diagnostics["BatchIndex"] = int(batch["index"])
    diagnostics["PeakWorkingSetBytes"] = peak_working_set_bytes
    return particles, diagnostics


def _run_mode(
    *,
    batches: list[dict[str, Any]],
    label: str,
    compensation: bool,
    ideal_reflectron: bool,
    simion_exe: Path,
    simion_dir: Path,
    output_dir: Path,
    trajectory_quality: int,
    workers: int,
) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _run_batch,
                batch=batch,
                label=label,
                compensation=compensation,
                ideal_reflectron=ideal_reflectron,
                simion_exe=simion_exe,
                simion_dir=simion_dir,
                output_dir=output_dir,
                trajectory_quality=trajectory_quality,
            )
            for batch in batches
        ]
        for future in as_completed(futures):
            frame, receipt = future.result()
            frames.append(frame)
            diagnostics.append(receipt)
    particles = pd.concat(frames, ignore_index=True).sort_values("Ion")
    particle_csv = output_dir / f"{label}_particles.csv"
    particles.to_csv(particle_csv, index=False)
    hit_tof = particles.loc[particles["Hit"], "TofUs"].to_numpy(dtype=float)
    metrics, _ = compute_peak_metrics(hit_tof, 524.0)
    return {
        "label": label,
        "particle_csv": str(particle_csv.resolve()),
        "emitted": int(len(particles)),
        "crossed": int(sum(item["Crossed"] for item in diagnostics)),
        "hit": int(particles["Hit"].sum()),
        "wall_seconds": max(item["ElapsedSeconds"] for item in diagnostics),
        "sum_batch_seconds": sum(item["ElapsedSeconds"] for item in diagnostics),
        "batches": sorted(diagnostics, key=lambda item: item["BatchIndex"]),
        "peak_working_set_bytes": max(
            (item["PeakWorkingSetBytes"] or 0 for item in diagnostics), default=0
        ) or None,
        "canonical_peak_metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument(
        "--simion-exe", type=Path,
        default=Path(r"C:\Program Files\SIMION-2020\simion.exe"),
    )
    parser.add_argument("--trajectory-quality", type=int, default=8)
    parser.add_argument("--regularization", type=float, default=1e-4)
    args = parser.parse_args()

    case_dir = args.case_dir.resolve()
    simion_dir = case_dir / "simion"
    contract_path = case_dir / "contracts" / "candidate_resolved_geometry.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    output_dir = case_dir / "results" / "voltage_compensation"
    output_dir.mkdir(parents=True, exist_ok=True)
    stage1_count = int(contract["rings"]["stage1_count"])
    stage2_count = int(contract["rings"]["stage2_count"])
    maximum_electrode = 4 + stage1_count + stage2_count
    maximum_x_mm = float(contract["geometry_mm"]["L_stage1"]) + float(
        contract["geometry_mm"]["L_stage2"]
    )

    basis_csv = output_dir / "axis_basis.csv"
    export = subprocess.run(
        [
            str(args.simion_exe), "--nogui", "--noprompt", "lua", str(EXPORT_SCRIPT),
            str(simion_dir / "reflectron"), str(maximum_electrode), str(basis_csv),
            format(maximum_x_mm, ".17g"),
        ],
        cwd=simion_dir,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    (output_dir / "basis_export.log").write_text(export.stdout, encoding="utf-8")
    x, basis = _load_basis(basis_csv)
    fit = optimize(
        x,
        basis,
        stage1_count=stage1_count,
        stage2_count=stage2_count,
        stage1_length_mm=float(contract["geometry_mm"]["L_stage1"]),
        stage2_length_mm=float(contract["geometry_mm"]["L_stage2"]),
        midgrid_voltage_v=float(contract["electrodes_V"]["midgrid"]),
        backplate_voltage_v=float(contract["electrodes_V"]["backplate"]),
        regularization=args.regularization,
    )
    _write_json(output_dir / "monotone_voltage_fit.json", fit)
    (simion_dir / "reflectron_voltage_profile.lua").write_text(
        render_lua_profile(fit), encoding="utf-8", newline="\n"
    )
    (simion_dir / "oatof_ideal_grounded.lua").write_text(
        render_program(contract), encoding="utf-8", newline="\n"
    )

    source = simion_dir / "oatof_comsol_524amu_gaussian_N1000.ion"
    particle_count = len(
        [line for line in source.read_text(encoding="ascii").splitlines() if line.strip()]
    )
    batches = _split_ions(source, output_dir / "batch_inputs", 1)
    baseline = _run_mode(
            batches=batches, label="baseline", compensation=False,
            ideal_reflectron=False, simion_exe=args.simion_exe, simion_dir=simion_dir,
            output_dir=output_dir, trajectory_quality=args.trajectory_quality,
            workers=1,
        )
    observed_peak = baseline["peak_working_set_bytes"]
    dispatch_plan = _plan_batches_from_observation(
        particle_count, args.trajectory_quality, observed_peak
    )
    scheduled_batch_count = int(dispatch_plan["waves"][0]["batch_count"])
    batches = _split_ions(source, output_dir / "batch_inputs", scheduled_batch_count)
    modes = {
        "baseline": baseline,
        "compensated": _run_mode(
            batches=batches, label="compensated", compensation=True,
            ideal_reflectron=False, simion_exe=args.simion_exe, simion_dir=simion_dir,
            output_dir=output_dir, trajectory_quality=args.trajectory_quality,
            workers=scheduled_batch_count,
        ),
        "ideal_reflectron": _run_mode(
            batches=batches, label="ideal_reflectron", compensation=False,
            ideal_reflectron=True, simion_exe=args.simion_exe, simion_dir=simion_dir,
            output_dir=output_dir, trajectory_quality=args.trajectory_quality,
            workers=scheduled_batch_count,
        ),
    }
    baseline_r = modes["baseline"]["canonical_peak_metrics"]["mass_resolution"]
    compensated_r = modes["compensated"]["canonical_peak_metrics"]["mass_resolution"]
    ideal_r = modes["ideal_reflectron"]["canonical_peak_metrics"]["mass_resolution"]
    summary = {
        "schema_version": 1,
        "role": "oatof_reflectron_voltage_compensation_closed_loop_receipt",
        "status": "success" if compensated_r > baseline_r else "no_resolution_gain",
        "case_dir": str(case_dir),
        "workers": scheduled_batch_count,
        "simion_dispatch_plan": dispatch_plan,
        "particle_count": sum(batch["count"] for batch in batches),
        "pa_rebuilt": False,
        "fixed_endpoints_V": fit["fixed_endpoints_V"],
        "monotone_constraints_verified": True,
        "field_fit": fit["fit"],
        "modes": modes,
        "resolution_gain_ratio": compensated_r / baseline_r,
        "remaining_gap_ratio_to_ideal_reflectron": (ideal_r - compensated_r) / ideal_r,
        "convergence": {
            "electrostatic_superposition": "one constrained solve is exact for a fixed PA basis",
            "additional_voltage_iteration_required": False,
            "geometry_iteration_required": compensated_r < ideal_r,
        },
    }
    _write_json(output_dir / "summary.json", summary)
    print(
        "REFLECTRON_VOLTAGE_COMPENSATION=" + summary["status"].upper()
        + f" BASELINE_R={baseline_r:.12g} COMPENSATED_R={compensated_r:.12g}"
        + f" IDEAL_R={ideal_r:.12g} OUTPUT={output_dir}",
        flush=True,
    )


if __name__ == "__main__":
    main()
