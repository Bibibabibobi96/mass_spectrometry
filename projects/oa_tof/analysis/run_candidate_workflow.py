"""Execute one prepared oa-TOF candidate workflow without promoting it."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
from candidate_run_lifecycle import finalize_candidate_run, start_candidate_run
from machine_contracts import load_json, sha256


StageExecutor = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]


class CandidateWorkflowError(RuntimeError):
    def __init__(self, message: str, run_root: Path):
        super().__init__(message)
        self.run_root = run_root


class CandidateWorkflowInterrupted(KeyboardInterrupt):
    def __init__(self, run_root: Path):
        super().__init__(f"candidate workflow interrupted: {run_root}")
        self.run_root = run_root


def _powershell(entrypoint: str, arguments: list[str]) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", entrypoint, *arguments]


def _run_command(command: list[str], log_path: Path, environment: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(environment or {})
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        result = subprocess.run(command, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}; log={log_path}")


def _ps_arguments(values: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in values.items():
        result.extend([f"-{key}", str(value)])
    return result


def _require_pass_report(path: Path) -> None:
    if not path.is_file() or "STATUS=PASS" not in path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"required PASS report is missing or failed: {path}")


def execute_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str) -> dict[str, Any]:
    stage_id = stage["stage_id"]
    run_root = Path(plan["run_root"])
    logs = run_root / "logs"
    if stage_id == "static_inputs":
        output = Path(stage["pending_output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        command = _powershell(stage["entrypoint"], _ps_arguments(stage["arguments"]))
        _run_command(command, logs / "static_inputs.log")
        if not output.is_file():
            raise RuntimeError(f"candidate particle table was not generated: {output}")
        return {"particle_table": str(output)}

    if stage_id == "comsol_candidate":
        environment = {key: str(value) for key, value in stage["environment"].items()}
        build_report = Path(stage["report_path"])
        build_command = _powershell(stage["entrypoint"], [
            "-TaskScript", stage["task_script"], "-ReportPath", str(build_report)
        ])
        _run_command(build_command, logs / "comsol_build_launcher.log", environment)
        _require_pass_report(build_report)
        sync_report = logs / "comsol_sync.txt"
        sync_environment = {
            "OATOF_COMSOL_MODEL_PATH": stage["model_path"],
            "OATOF_CONTRACT_PATH": stage["contract_path"],
        }
        sync_command = _powershell(stage["entrypoint"], [
            "-TaskScript", str(PROJECT_ROOT / "tests" / "comsol" / "verify_oatof_comsol_sync.m"),
            "-ReportPath", str(sync_report),
        ])
        _run_command(sync_command, logs / "comsol_sync_launcher.log", sync_environment)
        _require_pass_report(sync_report)
        return {"model": stage["model_path"], "build_report": str(build_report), "sync_report": str(sync_report)}

    if stage_id == "simion_candidate":
        arguments = [
            "-OutputDir", stage["output_dir"], "-RunId", plan["run_id"],
            "-ContractPath", stage["contract_path"], "-CandidateBaselinePath", stage["baseline_path"],
            "-CandidateTextDir", stage["text_dir"], "-SimionExe", simion_exe,
            "-DeferRunFinalization",
        ]
        _run_command(_powershell(stage["entrypoint"], arguments), logs / "simion_build.log")
        iob = Path(stage["output_dir"]) / "oatof_ideal_grounded.iob"
        verify = PROJECT_ROOT / "tests" / "simion" / "verify_iob_runtime_contract.ps1"
        _run_command(
            _powershell(str(verify), ["-IobPath", str(iob), "-SimionExe", simion_exe]),
            logs / "simion_runtime_verify.log",
        )
        summary = Path(stage["output_dir"]) / "stage_summary.json"
        if load_json(summary).get("status") != "success":
            raise RuntimeError("SIMION candidate stage summary did not pass")
        ion_n100 = Path(stage["output_dir"]) / "oatof_comsol_524amu_gaussian_N100.ion"
        if not ion_n100.is_file():
            raise RuntimeError(f"SIMION candidate N=100 particle table is missing: {ion_n100}")
        return {
            "iob": str(iob), "ion_n100": str(ion_n100), "stage_summary": str(summary),
            "runtime_log": str(logs / "simion_runtime_verify.log")
        }

    if stage_id == "cad_candidate":
        report = logs / "cad_build.txt"
        environment = {
            "OATOF_CANDIDATE_MODEL_PATH": stage["model_path"],
            "OATOF_CANDIDATE_CAD_DIR": stage["output_dir"],
        }
        command = _powershell(stage["entrypoint"], [
            "-TaskScript", stage["task_script"], "-ReportPath", str(report)
        ])
        _run_command(command, logs / "cad_launcher.log", environment)
        _require_pass_report(report)
        cad_report = Path(stage["output_dir"]) / "oaTOF_solidworks_export_report.json"
        if not cad_report.is_file():
            raise RuntimeError(f"candidate CAD report is missing: {cad_report}")
        return {"report": str(report), "cad_report": str(cad_report)}

    if stage_id == "cross_solver_acceptance":
        evidence = {item["stage_id"]: item.get("evidence", {}) for item in plan["stage_results_so_far"]}
        required = {
            "static_inputs": ("particle_table",),
            "comsol_candidate": ("model", "sync_report"),
            "simion_candidate": ("iob", "ion_n100", "stage_summary"),
            "cad_candidate": ("cad_report",),
        }
        for source_stage, keys in required.items():
            for key in keys:
                path = Path(evidence.get(source_stage, {}).get(key, ""))
                if not path.is_file():
                    raise RuntimeError(f"cross-stage evidence is missing: {source_stage}.{key}")
        comsol_ion = Path(evidence["static_inputs"]["particle_table"])
        simion_ion = Path(evidence["simion_candidate"]["ion_n100"])
        if sha256(comsol_ion).lower() != sha256(simion_ion).lower():
            raise RuntimeError("COMSOL and SIMION candidate N=100 particle tables differ")
        output_dir = Path(stage["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        acceptance = {
            "schema_version": 1,
            "role": "oa_tof_candidate_acceptance",
            "status": "success",
            "scope": stage["acceptance_scope"],
            "performance_claim_allowed": bool(stage["performance_claim_allowed"]),
            "formal_modified": False,
            "promotion_authorized": False,
            "shared_particle_table_sha256": sha256(comsol_ion),
            "evidence": evidence,
        }
        path = output_dir / "candidate_acceptance.json"
        path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"acceptance": str(path), "scope": acceptance["scope"]}

    raise ValueError(f"unsupported candidate workflow stage: {stage_id}")


def _remaining_results(stages: list[dict[str, Any]], completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done = {item["stage_id"] for item in completed}
    return completed + [
        {"stage_id": stage["stage_id"], "status": "blocked"}
        for stage in stages if stage["stage_id"] not in done
    ]


def run_candidate_workflow(
    plan_path: Path,
    simion_exe: str = r"C:\Program Files\SIMION-2020\simion.exe",
    stage_executor: StageExecutor = execute_stage,
) -> tuple[Path, dict[str, Any]]:
    run_root = start_candidate_run(plan_path)
    runtime_plan_path = run_root / "candidate_workflow_plan.json"
    runtime_plan = load_json(runtime_plan_path)
    stages = runtime_plan["stages"]
    results: list[dict[str, Any]] = []
    current_stage = "orchestration"
    try:
        for stage in stages:
            current_stage = stage["stage_id"]
            runtime_plan["stage_results_so_far"] = results
            evidence = stage_executor(stage, runtime_plan, simion_exe)
            results.append({"stage_id": current_stage, "status": "success", "evidence": evidence})
        summary, _ = finalize_candidate_run(run_root, "success", results)
        return run_root, summary
    except KeyboardInterrupt as exc:
        results.append({"stage_id": current_stage, "status": "interrupted", "error": str(exc)})
        finalize_candidate_run(run_root, "interrupted", _remaining_results(stages, results), current_stage)
        raise CandidateWorkflowInterrupted(run_root) from exc
    except Exception as exc:
        results.append({"stage_id": current_stage, "status": "failed", "error": str(exc)})
        finalize_candidate_run(run_root, "failed", _remaining_results(stages, results), current_stage)
        raise CandidateWorkflowError(str(exc), run_root) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--simion-exe", default=r"C:\Program Files\SIMION-2020\simion.exe")
    args = parser.parse_args()
    try:
        run_root, summary = run_candidate_workflow(args.plan, args.simion_exe)
    except CandidateWorkflowInterrupted as exc:
        raise SystemExit(130) from exc
    except CandidateWorkflowError as exc:
        print(f"CANDIDATE_WORKFLOW=FAIL RUN_ROOT={exc.run_root} ERROR={exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"CANDIDATE_WORKFLOW=PASS RUN_ROOT={run_root} DECISION={summary['candidate_decision']}")


if __name__ == "__main__":
    main()
