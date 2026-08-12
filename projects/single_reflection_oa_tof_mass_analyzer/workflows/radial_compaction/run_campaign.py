"""Run the governed SIMION-only oaTOF radial-compaction campaign."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "radial_compaction_campaign.json"
BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
MODE_PATH = PROJECT_ROOT / "config" / "modes" / "formal.json"
ARTIFACT_ROOT = (
    WORKSPACE_ROOT
    / "artifacts"
    / "projects"
    / "single_reflection_oa_tof_mass_analyzer"
)
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import load_json, sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    resolve_contract,
    serialized,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers import (
    prepare,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate import (
    validate_candidate_runtime,
)


MODE_FLAGS = {
    "actual": (0, 0, 0),
    "ideal_stage1": (0, 1, 0),
    "ideal_stage2": (0, 0, 1),
    "ideal_reflectron": (0, 1, 1),
    "ideal_all": (1, 1, 1),
}


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _verify_authorities(config: dict[str, Any]) -> tuple[Path, Path]:
    for key, path in (("baseline", BASELINE_PATH), ("solver_numerics", NUMERICS_PATH)):
        if sha256(path) != config["authorities"][key]["sha256"]:
            raise ValueError(f"radial campaign authority is stale: {key}")
    reference = config["authorities"]["reference_result"]
    reference_root = ARTIFACT_ROOT / "runs" / reference["run_id"]
    summary = reference_root / reference["relative_path"]
    particles = reference_root / reference["particle_relative_path"]
    if sha256(summary) != reference["sha256"]:
        raise ValueError("radial campaign reference summary changed")
    if sha256(particles) != reference["particle_sha256"]:
        raise ValueError("radial campaign reference particle table changed")
    return summary, particles


def _canonical_metrics(particle_csv: Path) -> dict[str, Any]:
    tof = []
    with particle_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row["Hit"]).lower() == "true":
                tof.append(float(row["TofUs"]))
    metrics, _ = compute_peak_metrics(np.asarray(tof), 524.0)
    return metrics


def _assert_only_allowed_changes(
    baseline: dict[str, Any], candidate: dict[str, Any], *, allow_ring_counts: bool,
    allowed_geometry_keys: set[str] | None = None,
) -> None:
    left, right = copy.deepcopy(baseline), copy.deepcopy(candidate)
    allowed_geometry_keys = allowed_geometry_keys or set()
    for document in (left, right):
        geometry = document["geometry_mm"]
        for key in {"bore_r", "ring_outer_r", "flight_tube_r"} | allowed_geometry_keys:
            geometry.pop(key)
        if allow_ring_counts:
            document["rings"].pop("stage1_count")
            document["rings"].pop("stage2_count")
        # This is a generated accelerator-envelope coordinate.  Older baseline
        # contracts predate the field; candidate compilation now materializes
        # it without changing any radial-compaction design freedom.
        document.get("geometry_derivation", {}).get("accelerator", {}).pop(
            "outer_envelope_min_z_mm", None
        )
    if left != right:
        raise ValueError("candidate changed a non-authorized geometry, source, voltage or solver value")


def _overrides(case: dict[str, Any]) -> list[dict[str, Any]]:
    values = [
        ("reflectron_bore_radius", case["bore_radius_mm"], "mm"),
        ("reflectron_ring_outer_radius", case["ring_outer_radius_mm"], "mm"),
        (
            "reflectron_shield_inner_radius",
            case["shared_shield_inner_radius_mm"],
            "mm",
        ),
    ]
    if "stage1_count" in case:
        values.extend(
            [
                ("reflectron_stage1_electrode_count", case["stage1_count"], "count"),
                ("reflectron_stage2_electrode_count", case["stage2_count"], "count"),
            ]
        )
    if "ring_thickness_mm" in case:
        values.append(
            ("reflectron_ring_thickness", case["ring_thickness_mm"], "mm")
        )
    return [
        {"variable": variable, "value": value, "unit": unit}
        for variable, value, unit in values
    ]


def _prepare_case(
    case: dict[str, Any], run_root: Path, baseline: dict[str, Any], seed: int,
    default_mesh: dict[str, Any],
) -> dict[str, Any]:
    case_root = run_root / "cases" / case["case_id"]
    contracts = case_root / "contracts"
    baseline_path = contracts / "candidate_baseline.json"
    resolved_path = contracts / "candidate_resolved_geometry.json"
    diff_path = contracts / "candidate_diff.json"
    numerics_path = contracts / "candidate_solver_numerics.json"
    if baseline_path.is_file() and resolved_path.is_file() and diff_path.is_file():
        return {
            **case,
            "case_root": case_root,
            "baseline_path": baseline_path,
            "resolved_path": resolved_path,
            "diff_path": diff_path,
            "text_dir": case_root / "prepared" / "simion",
            "simion_dir": case_root / "simion",
        }
    candidate, diff = compile_design_overrides(baseline, _overrides(case))
    _assert_only_allowed_changes(
        baseline, candidate, allow_ring_counts="stage1_count" in case,
        allowed_geometry_keys={
            "ring_thickness", "shield_bore_z_max", "shield_outer_z_max"
        }
        if "ring_thickness_mm" in case else set(),
    )
    contracts.mkdir(parents=True)
    _write_json(baseline_path, candidate)
    numerics = load_json(NUMERICS_PATH)
    numerics["simion"]["geometry_build"]["reflectron"]["cell_axial_mm"] = float(
        default_mesh["axial"]
    )
    numerics["simion"]["geometry_build"]["reflectron"]["cell_radial_mm"] = float(
        default_mesh["radial"]
    )
    if "reflectron_cell_axial_mm" in case:
        numerics["simion"]["geometry_build"]["reflectron"]["cell_axial_mm"] = float(
            case["reflectron_cell_axial_mm"]
        )
    _write_json(numerics_path, numerics)
    resolved = resolve_contract(
        baseline_path=baseline_path, mode_path=MODE_PATH, numerics_path=numerics_path
    )
    resolved_path.write_text(serialized(resolved), encoding="utf-8")
    _write_json(diff_path, diff)
    prepared = case_root / "prepared"
    prepare(resolved_path, prepared, particle_source_seed=seed)
    return {
        **case,
        "case_root": case_root,
        "baseline_path": baseline_path,
        "resolved_path": resolved_path,
        "diff_path": diff_path,
        "text_dir": prepared / "simion",
        "simion_dir": case_root / "simion",
    }


def _run_logged(command: list[str], cwd: Path, stdout: Path, stderr: Path) -> float:
    stdout.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with stdout.open("wb") as out, stderr.open("wb") as err:
        result = subprocess.run(
            command, cwd=cwd, stdout=out, stderr=err, check=False, timeout=1800
        )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}); see {stderr}")
    return elapsed


def _build_case(
    case: dict[str, Any], *, simion_exe: Path, template_iob: Path,
    reusable_dir: Path, reuse_components: str, seed: int, run_id: str
) -> None:
    stage_summary = case["simion_dir"] / "stage_summary.json"
    if (
        (case["simion_dir"] / "oatof_ideal_grounded.iob").is_file()
        and stage_summary.is_file()
        and load_json(stage_summary).get("status") == "success"
    ):
        case["pa_build_seconds"] = None
        case["pa_build_reused_from_interrupted_run"] = True
        return
    builder = PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1"
    logs = case["case_root"] / "logs"
    command = [
        "pwsh.exe", "-NoProfile", "-File", str(builder),
        "-SimionExe", str(simion_exe),
        "-OutputDir", str(case["simion_dir"]),
        "-ArtifactProjectRoot", str(ARTIFACT_ROOT),
        "-TemplateIob", str(template_iob),
        "-RunId", run_id,
        "-ContractPath", str(case["resolved_path"]),
        "-CandidateBaselinePath", str(case["baseline_path"]),
        "-CandidateTextDir", str(case["text_dir"]),
        "-ReusableComponentDir", str(reusable_dir),
        "-ReuseComponents", reuse_components,
        "-ReusableParticleDir", str(ARTIFACT_ROOT / "formal" / "simion"),
        "-ParticleSeed", str(seed),
        "-DeferRunFinalization",
    ]
    maximum_reflectron_electrode = 4 + int(case.get("stage1_count", 10)) + int(
        case.get("stage2_count", 5)
    )
    existing_reflectron = [
        case["simion_dir"] / "reflectron.pa#",
        case["simion_dir"] / "reflectron.pa0",
        *[
            case["simion_dir"] / f"reflectron.pa{index}"
            for index in range(1, maximum_reflectron_electrode + 1)
        ],
    ]
    if all(path.is_file() for path in existing_reflectron):
        command.append("-ResumeRefinedReflectron")
    case["pa_build_seconds"] = _run_logged(
        command, REPO_ROOT, logs / "pa_build.log", logs / "pa_build.stderr.log"
    )


def _fly(case: dict[str, Any], mode: str, simion_exe: Path, particle_count: int,
         trajectory_quality: int) -> dict[str, Any]:
    accel, stage1, stage2 = MODE_FLAGS[mode]
    logs = case["case_root"] / "logs"
    results = case["case_root"] / "results"
    log = logs / f"{mode}.log"
    error = logs / f"{mode}.stderr.log"
    particle_csv = results / f"{mode}_particles.csv"
    summary_path = results / f"{mode}_summary.json"
    if summary_path.is_file():
        return load_json(summary_path)
    ion = case["simion_dir"] / f"oatof_comsol_524amu_gaussian_N{particle_count}.ion"
    command = [
        str(simion_exe), "--default-num-particles", str(particle_count),
        "--nogui", "fly", "--trajectory-quality", str(trajectory_quality),
        "--retain-trajectories", "0", "--particles", str(ion),
        "--adjustable", f"trajectory_quality={trajectory_quality}",
        "--adjustable", f"ideal_accel_enable={accel}",
        "--adjustable", f"ideal_refl_stage1_enable={stage1}",
        "--adjustable", f"ideal_refl_stage2_enable={stage2}",
        "--adjustable", "trajectory_log_enable=1",
        str(case["simion_dir"] / "oatof_ideal_grounded.iob"),
    ]
    if log.is_file() and log.stat().st_size > 0 and error.is_file():
        elapsed = None
        reused_flight = True
    else:
        elapsed = _run_logged(command, case["simion_dir"], log, error)
        reused_flight = False
    analyze = [
        str(PYTHON), "-m",
        "projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics",
        "analyze-simion-log", "--log", str(log), "--ion-file", str(ion),
        "--mode", mode, "--distribution", "fixedN1000",
        "--detector-radius-mm", "40", "--particle-csv", str(particle_csv),
        "--allow-incomplete-census",
    ]
    result = subprocess.run(
        analyze, cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=120
    )
    diagnostics = json.loads(result.stdout)
    canonical = _canonical_metrics(particle_csv)
    summary = {
        "schema_version": 1,
        "role": "oatof_radial_compaction_case_result",
        "status": "success",
        "case_id": case["case_id"],
        "mode": mode,
        "flight_seconds": elapsed,
        "flight_reused_from_interrupted_run": reused_flight,
        "diagnostics": diagnostics,
        "canonical_peak_metrics": canonical,
    }
    _write_json(summary_path, summary)
    return summary


def _run_parallel_flights(
    cases: list[dict[str, Any]], mode: str, simion_exe: Path,
    particle_count: int, trajectory_quality: int, workers: int
) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _fly, case, mode, simion_exe, particle_count, trajectory_quality
            ): case["case_id"]
            for case in cases
        }
        for future in as_completed(futures):
            case_id = futures[future]
            outputs[case_id] = future.result()
            print(f"FLIGHT=PASS CASE={case_id} MODE={mode}", flush=True)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--simion-exe", type=Path,
        default=Path(r"C:\Program Files\SIMION-2020\simion.exe"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    validate_run_id(args.run_id)
    simion_exe = args.simion_exe.resolve(strict=True)
    config = load_json(CONFIG_PATH)
    reference_summary_path, reference_particles_path = _verify_authorities(config)
    baseline = load_json(BASELINE_PATH)
    reference_metrics = _canonical_metrics(reference_particles_path)
    run_root = ARTIFACT_ROOT / "runs" / args.run_id
    if run_root.exists() and not args.resume:
        raise ValueError(f"run output already exists: {run_root}")
    run_root.mkdir(parents=True, exist_ok=args.resume)
    if not (run_root / "run_config.json").is_file():
        _write_json(
            run_root / "run_config.json",
        {
            "schema_version": 1,
            "role": "oatof_radial_compaction_run_config",
            "run_id": args.run_id,
            "project": "single_reflection_oa_tof_mass_analyzer",
            "mode": "simion_radial_compaction_n1000",
            "inputs": {
                "campaign": str(CONFIG_PATH),
                "baseline": str(BASELINE_PATH),
                "solver_numerics": str(NUMERICS_PATH),
                "reference_summary": str(reference_summary_path),
                "reference_particles": str(reference_particles_path),
            },
            },
        )
    seed = int(config["fixed_contract"]["particle_source_seed"])
    count = int(config["fixed_contract"]["particle_count"])
    quality = int(config["fixed_contract"]["trajectory_quality"])
    default_mesh = config["fixed_contract"]["default_reflectron_mesh_mm"]
    primary = [
        _prepare_case(case, run_root, baseline, seed, default_mesh)
        for case in config["radius_screen"]
    ]
    if args.dry_run:
        _write_json(run_root / "summary.json", {"status": "dry_run", "cases": len(primary)})
        print(f"RADIAL_COMPACTION=DRY_RUN CASES={len(primary)} ROOT={run_root}")
        return

    runtime = validate_candidate_runtime(ARTIFACT_ROOT)
    template_iob = runtime["registration"]["source_iob"]
    formal_dir = ARTIFACT_ROOT / "formal" / "simion"
    for case in primary:
        _build_case(
            case, simion_exe=simion_exe, template_iob=template_iob,
            reusable_dir=formal_dir, reuse_components="accelerator,detector",
            seed=seed, run_id=args.run_id,
        )
        ion = case["simion_dir"] / f"oatof_comsol_524amu_gaussian_N{count}.ion"
        if sha256(ion) != config["fixed_contract"]["particle_table_sha256"]:
            raise ValueError(f"candidate source differs from reference: {case['case_id']}")
        print(f"PA_BUILD=PASS CASE={case['case_id']}", flush=True)

    workers = int(config["parallelism"]["n1000_flight_workers"])
    actual = _run_parallel_flights(primary, "actual", simion_exe, count, quality, workers)
    resolution_reference = float(reference_metrics["mass_resolution"])
    acceptance = config["acceptance"]

    def passes(result: dict[str, Any]) -> bool:
        diagnostics = result["diagnostics"]
        metrics = result["canonical_peak_metrics"]
        return (
            diagnostics["Hit"] / diagnostics["Emitted"]
            >= acceptance["minimum_hit_fraction"]
            and metrics["mass_resolution"] / resolution_reference
            >= acceptance["minimum_resolution_ratio_to_reference"]
            and metrics["significant_kde_modes"]
            <= acceptance["maximum_significant_kde_modes"]
        )

    failed = [case for case in primary if not passes(actual[case["case_id"]])]
    ideal: dict[str, dict[str, dict[str, Any]]] = {}
    if config["ideal_field_attribution"]["execute_for_failed_radius_cases"]:
        for mode in config["ideal_field_attribution"]["modes"]:
            ideal[mode] = _run_parallel_flights(
                failed, mode, simion_exe, count, quality, workers
            ) if failed else {}

    target_id = config["ring_count_compensation"]["target_case_id"]
    target = next(case for case in primary if case["case_id"] == target_id)
    compensation: list[dict[str, Any]] = []
    compensation_results: dict[str, dict[str, Any]] = {}
    compensation_ideal: dict[str, dict[str, dict[str, Any]]] = {}
    if (
        config["ring_count_compensation"]["execute_when_target_fails"]
        and not passes(actual[target_id])
        and actual[target_id]["diagnostics"]["Hit"]
        / actual[target_id]["diagnostics"]["Emitted"]
        >= acceptance["minimum_hit_fraction"]
        and ideal.get("ideal_reflectron", {})
        .get(target_id, {})
        .get("canonical_peak_metrics", {})
        .get("mass_resolution", 0.0)
        >= 0.95 * resolution_reference
    ):
        for ring_case in config["ring_count_compensation"]["cases"]:
            merged = {
                **{key: target[key] for key in (
                    "bore_radius_mm", "ring_outer_radius_mm",
                    "shared_shield_inner_radius_mm"
                )},
                **ring_case,
            }
            candidate = _prepare_case(merged, run_root, baseline, seed, default_mesh)
            _build_case(
                candidate, simion_exe=simion_exe, template_iob=template_iob,
                reusable_dir=target["simion_dir"],
                reuse_components="accelerator,detector,flight_tube",
                seed=seed, run_id=args.run_id,
            )
            compensation.append(candidate)
            print(f"PA_BUILD=PASS CASE={candidate['case_id']}", flush=True)
        compensation_results = _run_parallel_flights(
            compensation, "actual", simion_exe, count, quality, workers
        )
        diagnostic_ids = set(
            config["ring_count_compensation"].get(
                "ideal_field_diagnostic_case_ids", []
            )
        )
        diagnostic_cases = [
            case for case in compensation if case["case_id"] in diagnostic_ids
        ]
        missing_diagnostic_ids = diagnostic_ids - {
            case["case_id"] for case in diagnostic_cases
        }
        if missing_diagnostic_ids:
            raise ValueError(
                "unknown compensation ideal-field case: "
                + ", ".join(sorted(missing_diagnostic_ids))
            )
        for mode in config["ideal_field_attribution"]["modes"]:
            compensation_ideal[mode] = _run_parallel_flights(
                diagnostic_cases, mode, simion_exe, count, quality, workers
            )

    rows = []
    for case in primary + compensation:
        result = (actual if case in primary else compensation_results)[case["case_id"]]
        metrics = result["canonical_peak_metrics"]
        rows.append(
            {
                "case_id": case["case_id"],
                "shared_shield_inner_radius_mm": case["shared_shield_inner_radius_mm"],
                "instrument_outer_radius_mm": case["shared_shield_inner_radius_mm"]
                + config["fixed_contract"]["fixed_shield_wall_mm"],
                "bore_radius_mm": case["bore_radius_mm"],
                "ring_outer_radius_mm": case["ring_outer_radius_mm"],
                "stage1_count": case.get("stage1_count", baseline["rings"]["stage1_count"]),
                "stage2_count": case.get("stage2_count", baseline["rings"]["stage2_count"]),
                "ring_thickness_mm": case.get(
                    "ring_thickness_mm", baseline["geometry_mm"]["ring_thickness"]
                ),
                "reflectron_cell_axial_mm": case.get(
                    "reflectron_cell_axial_mm",
                    config["fixed_contract"]["default_reflectron_mesh_mm"]["axial"],
                ),
                "hit": result["diagnostics"]["Hit"],
                "mass_resolution": metrics["mass_resolution"],
                "resolution_ratio_to_reference": metrics["mass_resolution"] / resolution_reference,
                "significant_kde_modes": metrics["significant_kde_modes"],
                "accepted": passes(result),
                "pa_build_seconds": case["pa_build_seconds"],
                "flight_seconds": result["flight_seconds"],
            }
        )
    accepted = [row for row in rows if row["accepted"]]
    best = min(accepted, key=lambda row: row["instrument_outer_radius_mm"]) if accepted else None
    summary = {
        "schema_version": 1,
        "role": "oatof_radial_compaction_campaign_summary",
        "status": "success",
        "reference": {
            "mass_resolution": resolution_reference,
            "significant_kde_modes": reference_metrics["significant_kde_modes"],
            "instrument_outer_radius_mm": baseline["geometry_mm"]["flight_tube_r"]
            + baseline["geometry_mm"]["flight_tube_wall"],
        },
        "best_accepted_case": best,
        "cases": rows,
        "ideal_field_results": ideal,
        "compensation_ideal_field_results": compensation_ideal,
        "fixed_contract_verified": True,
        "shared_shield_radius_and_wall_verified": True,
    }
    _write_json(run_root / "summary.json", summary)
    manifest_command = [
        str(PYTHON), str(REPO_ROOT / "common" / "contracts" / "write_run_manifest.py"),
        "--run-config", str(run_root / "run_config.json"),
        "--manifest", str(run_root / "run_manifest.json"),
        "--status", "success", "--software", "SIMION 2020",
        "--output", str(run_root / "summary.json"),
    ]
    subprocess.run(manifest_command, cwd=REPO_ROOT, check=True, timeout=120)
    print(
        f"RADIAL_COMPACTION=PASS ROOT={run_root} "
        f"BEST={best['case_id'] if best else 'none'}",
        flush=True,
    )


if __name__ == "__main__":
    main()
