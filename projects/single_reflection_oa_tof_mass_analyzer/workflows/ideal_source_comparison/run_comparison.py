"""Run both ideal-field comparisons automatically; resume into a new immutable run.

Usage: python -m projects.single_reflection_oa_tof_mass_analyzer.workflows.
ideal_source_comparison.run_comparison --seed 20260827 [--resume-from RUN]
No commercial solver is imported, launched, or required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import scipy

from common.contracts.artifact_naming import validate_run_id
from common.analysis.peak_metrics import AnalysisSettings
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json
from common.contracts.verify_run_manifest import verify_record

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_experiment import (
    build_case_plan, summarize_stage,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison_plot import (
    export_comparison_figures,
)

from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.numerical_case import (
    _run_case, _working_points, _settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
ARTIFACT_ROOT = REPO_ROOT.parent / "artifacts" / "projects" / PROJECT_ROOT.name
DEFAULT_CONFIG = PROJECT_ROOT / "config/experiments/ideal_source_comparison.json"


def _write_json(path: Path, value: Any) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    with pending.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _command(arguments: list[str]) -> str:
    completed = subprocess.run(arguments, cwd=REPO_ROOT, check=False, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=120)
    if completed.returncode:
        raise RuntimeError(f"{arguments[:4]} exit={completed.returncode}: {completed.stdout}\n{completed.stderr}")
    return completed.stdout.strip()


def _inputs(config_path: Path) -> dict[str, Path]:
    local = ["ideal_source_comparison.py", "ideal_source_experiment.py", "ideal_source_comparison_plot.py", "three_zone_ideal_theory.py",
             "oatof_oaaccelerator_coupling.py", "reflectron_dual_stage_solver.py"]
    accelerator = REPO_ROOT / "projects/orthogonal_accelerator/analysis"
    return {"experiment": config_path, "entrypoint": Path(__file__),
            "numerical_case": Path(__file__).with_name("numerical_case.py"),
            "analysis_contract": PROJECT_ROOT / "config/analysis_contract.json",
            "particle_policy": REPO_ROOT / "common/contracts/particle_count_policy.json",
            "peak_metrics": REPO_ROOT / "common/analysis/peak_metrics.py",
            "accelerator_time_focus": accelerator / "accelerator_time_focus.py",
            "accelerator_three_zone_theory": accelerator / "three_zone_ideal_theory.py",
            "accelerator_two_zone_geometry": accelerator / "two_zone_geometry.py",
            **{Path(name).stem: PROJECT_ROOT / "analysis" / name for name in local}}








def _frozen_settings(run_dir: Path) -> AnalysisSettings:
    """Read the once-frozen analysis authority for every supported comparison role."""
    frozen_config = load_json(run_dir / "run_config.json")
    contract = Path(frozen_config["inputs"]["analysis_contract"])
    if file_sha256(contract) != frozen_config["input_sha256"]["analysis_contract"]:
        raise ValueError("frozen analysis contract changed after freezing")
    return _settings(contract)


def _reuse_case(previous: Path | None, case: dict[str, Any], identity: str, destination: Path) -> dict[str, Any] | None:
    if previous is None:
        return None
    path = previous / "results" / f"{case['case_id']}.json"
    if not path.is_file():
        return None
    document = load_json(path)
    if document["identity"] != identity or document["case"] != case or document["record_sha256"] != _digest({k: v for k, v in document.items() if k != "record_sha256"}):
        raise ValueError(f"checkpoint identity/content mismatch: {path}")
    record = document["particles"]
    if Path(record["path"]).name != record["path"]:
        raise ValueError("checkpoint particle file must be local to results")
    verify_record("checkpoint particles", record, base_dir=path.parent)
    shutil.copy2(path.parent / record["path"], destination / record["path"])
    shutil.copy2(path, destination / path.name)
    return document


def _publish_manifest(run_dir: Path, status: str) -> None:
    command = [sys.executable, "-m", "common.contracts.write_run_manifest", "--run-config", str(run_dir / "run_config.json"), "--status", status, "--software", f"Python {platform.python_version()}; NumPy {np.__version__}; SciPy {scipy.__version__}"]
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name not in {"run_config.json", "run_manifest.json"}:
            # Writer resolves outputs against run_config's parent. Relative paths
            # keep Windows CreateProcess below its command-line length limit.
            command.extend(["--output", path.relative_to(run_dir).as_posix()])
    print(_command(command), flush=True)
    print(_command([sys.executable, "-m", "common.contracts.verify_run_manifest", str(run_dir / "run_manifest.json"), "--require-status", status]), flush=True)


def _write_report(run_dir: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = ["# Ideal-field source comparison", "", f"Execution: {summary['status']}; elapsed {summary['elapsed_s']:.2f} s.", "", "Scope: synthetic axial sources, pulse-relative exact TOF, fixed geometry. Only mirror voltages change in the residual comparison. No 3D, physical transmission or global optimum claim.", ""]
    for result in summary["stages"]:
        lines.extend([f"## {result['stage']}", "", f"{result['scientific_status']}: {result['reason']}", ""])
        if "acceptance" in result:
            lines.extend(["|Residual (m/s)|Setting|Contiguous tested width (mm)|First failing width (mm)|", "|---:|---|---:|---:|"])
            for item in result["acceptance"]:
                lines.append(f"|{item['residual_sigma_m_per_s']}|{item['arm']}|{item['contiguous_tested_accepted_width_mm']}|{item['first_failing_width_mm']}|")
            lines.append("")
    lines.extend(["## Every case (all seeds, no selected best run)", "", "|Stage|Width (mm)|Residual (m/s)|Seed|Setting|R|FWHM (ns)|Model arrivals|", "|---|---:|---:|---:|---|---:|---:|---:|"])
    for record in records:
        case = record["case"]
        for name, arm in record["arms"].items():
            lines.append(f"|{case['stage']}|{case['full_width_mm']}|{case['residual_sigma_m_per_s']}|{case['seed']}|{name}|{arm['resolution']}|{arm['fwhm_ns']}|{arm['model_arrival_fraction']}|")
    if summary["failure_reason"]:
        lines.extend(["", "## Failure", "", f"{summary['failure_stage']}: {summary['failure_reason']}"])
    (run_dir / "results/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prepare_run(config_path: Path, *, seed: int, run_id: str, resume_from: Path | None,
                 artifact_root: Path, extra_inputs: dict[str, Path] | None = None,
                 mode: str = "ideal_source_comparison") -> tuple[Path, str]:
    """Shared immutable input freeze for ideal-source analysis modes."""
    validate_run_id(run_id)
    config_path = config_path.resolve()
    config = load_json(config_path)
    inputs = {**_inputs(config_path), **(extra_inputs or {})}
    identities = {name: file_sha256(path) for name, path in inputs.items()}
    numerical_inputs = {name: value for name, value in identities.items()
                        if name not in {"entrypoint", "ideal_source_comparison_plot"}}
    identity = _digest({"inputs": numerical_inputs, "seed": seed, "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__})
    if resume_from is not None:
        resume_from = resume_from.resolve()
        previous = load_json(resume_from / "run_config.json")
        if 'numerical_case' not in previous.get('input_sha256', {}):
            raise ValueError('resume source lacks a frozen numerical_case implementation identity; preserve the legacy run and start a new comparison')
        if previous["numerical_identity"] != identity:
            raise ValueError("resume code/config/seed/environment differs; start a new comparison without --resume-from")
        for name, path in previous["inputs"].items():
            if file_sha256(Path(path)) != previous["input_sha256"][name]:
                raise ValueError(f"resume frozen input changed: {name}")
    run_dir = artifact_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    for name in ("inputs", "results", "logs"):
        (run_dir / name).mkdir()
    frozen = {}
    for name, path in inputs.items():
        destination = run_dir / "inputs" / (name + path.suffix)
        shutil.copy2(path, destination)
        if file_sha256(destination) != identities[name]:
            raise ValueError(f"input changed during freeze: {name}")
        frozen[name] = str(destination.resolve())
    _write_json(run_dir / "run_config.json", {"schema_version": 2, "run_id": run_id,
                "project": PROJECT_ROOT.name, "mode": mode, "inputs": frozen,
                "input_sha256": identities, "numerical_input_sha256": numerical_inputs, "numerical_identity": identity,
                # Execution provenance is deliberately outside numerical/resume identity.
                "execution_source_sha256": {
                    name: file_sha256(REPO_ROOT / "common" / name)
                    for name in ("host_resource_python.py", "host_resource_python.ps1",
                                 "host_execution_lease.ps1", "host_resource_scheduler.py", "host_resource_policy.json")
                },
                "git_head": _command(["git", "rev-parse", "HEAD"]),
                "git_worktree_status": _command(["git", "status", "--short"]),
                "run_instance": {"seed": seed, "resume_from": str(resume_from) if resume_from else None},
                "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
                "formal_gate_passed": False, "claim_scope": config["scope"]})
    return run_dir, identity


def execute(config_path: Path, *, seed: int, run_id: str, resume_from: Path | None = None,
            artifact_root: Path = ARTIFACT_ROOT, max_workers: int | None = None) -> Path:
    """Execute the selected ideal analysis with frozen inputs and terminal evidence.

Resume verifies identical code/config/environment and copies completed cases into
a new run. It never edits or finalizes a previous run, including crash leftovers.
"""
    config_path = config_path.resolve()
    config = load_json(config_path)
    if config.get("role") == "ideal_acceptance_theory":
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.acceptance_theory import execute_theory
        return execute_theory(config_path, seed=seed, run_id=run_id, resume_from=resume_from,
                              artifact_root=artifact_root, max_workers=max_workers)
    if config.get("role") == "ideal_source_slope_scan":
        if max_workers is not None:
            raise ValueError("max workers is unsupported by ideal_source_slope_scan")
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.slope_scan import execute_slope_scan
        return execute_slope_scan(config_path, seed=seed, run_id=run_id, resume_from=resume_from,
                                  artifact_root=artifact_root)
    if max_workers is not None:
        raise ValueError("max workers is supported only by ideal_acceptance_theory runs")
    plan = build_case_plan(config, seed)
    run_dir, identity = _prepare_run(config_path, seed=seed, run_id=run_id,
                                    resume_from=resume_from, artifact_root=artifact_root)
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    stage, reused, error, current_case = "working_points", 0, None, None
    status = "success"
    try:
        points, settings = _working_points(config), _frozen_settings(run_dir)
        _write_json(run_dir / "results/working_points.json", {k: v.to_dict() for k, v in points.items()})
        for stage in ("residual_scan", "width_scan"):
            print(f"IDEAL_COMPARISON STAGE={stage} EVENT=START", flush=True)
            for case in (c for c in plan if c["stage"] == stage):
                stage = case["stage"]
                current_case = case["case_id"]
                record = _reuse_case(resume_from, case, identity, run_dir / "results")
                if record is None:
                    record = _run_case(case, config, points, settings, run_dir / "results")
                    record["identity"] = identity
                    record["record_sha256"] = _digest(record)
                    _write_json(run_dir / "results" / f"{case['case_id']}.json", record)
                else:
                    reused += 1
                records.append(record)
                print(f"IDEAL_COMPARISON CASE={case['case_id']} EVENT=COMPLETE DONE={len(records)}/{len(plan)} REUSED={reused}", flush=True)
            conclusion = summarize_stage(stage, [r for r in records if r["case"]["stage"] == stage], config)
            stages.append(conclusion)
            _write_json(run_dir / "results" / f"{stage}__summary.json", conclusion)
            print(f"IDEAL_COMPARISON STAGE={stage} SCIENTIFIC_STATUS={conclusion['scientific_status']} REASON={conclusion['reason']}", flush=True)
            current_case = None
        stage = "figures"
        export_comparison_figures(records, config, run_dir / "results")
    except (Exception, KeyboardInterrupt) as exc:
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        error = f"{type(exc).__name__}: {exc}"
        (run_dir / "logs/failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    summary = {"schema_version": 1, "role": "ideal_source_comparison_summary", "status": status,
               "stages": stages, "completed_cases": len(records), "planned_cases": len(plan), "reused_cases": reused,
               "failure_stage": stage if error else None, "failure_reason": error,
               "failure_case_id": current_case if error else None,
               "elapsed_s": time.perf_counter() - started, "formal_gate_passed": False,
               "next_action": "inspect stage conclusions" if status == "success" else "inspect failure.log; fix inputs/code if needed; resume unchanged cases only into a new run"}
    _write_json(run_dir / "summary.json", summary)
    _write_report(run_dir, records, summary)
    try:
        _publish_manifest(run_dir, status)
    except Exception as exc:
        summary.update(status="failed", failure_stage="manifest_publication",
                       failure_reason=f"{type(exc).__name__}: {exc}",
                       next_action="repair publication; completed case checkpoints remain available")
        _write_json(run_dir / "summary.json", summary)
        (run_dir / "logs/failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        _write_report(run_dir, records, summary)
        raise
    print(f"IDEAL_COMPARISON STATUS={status} COMPLETED={len(records)}/{len(plan)} ELAPSED_S={summary['elapsed_s']:.2f} RUN={run_dir} REASON={error or 'both scans completed'}", flush=True)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    """Single public CLI; no stage-by-stage manual continuation is required."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--max-workers", type=int,
                        help="Theory-only process-pool cap; does not change frozen science inputs.")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.plan:
            config = load_json(args.config)
            if config.get("role") == "ideal_acceptance_theory":
                from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.acceptance_theory import validate_theory_config
                validate_theory_config(config)
                plan = config
            elif config.get("role") == "ideal_source_slope_scan":
                from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.slope_scan import validate_slope_scan_config
                validate_slope_scan_config(config)
                plan = config
            else:
                plan = build_case_plan(config, args.seed)
            print(json.dumps(plan, indent=2))
            return 0
        from common.host_resource_python import ensure_heavy_entry

        ensure_heavy_entry(
            "projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison", argv,
        )
        run_id = args.run_id or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S__analysis__python__ideal-source-comparison")
        run_dir = execute(args.config, seed=args.seed, run_id=run_id,
                          resume_from=args.resume_from, max_workers=args.max_workers)
        return 0 if load_json(run_dir / "summary.json")["status"] == "success" else 1
    except Exception as exc:
        print(f"IDEAL_COMPARISON STATUS=failed REASON={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
