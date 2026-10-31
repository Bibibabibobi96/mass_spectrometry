"""Frozen COMSOL Candidate construction and scientific completion checks."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import load_json
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import frozen_source_path, verify_candidate_source_closure

def _report_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if value:
                return value
    raise RuntimeError(f"required {key} record is missing from {path}")


def execute_comsol_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str, *, runtime: Any) -> dict[str, Any]:
    """Execute the declared frozen COMSOL stage using owner-managed processes."""
    from .candidate_stage_execution import _powershell, _require_pass_report
    _run_command = runtime._run_command
    _run_managed_stage_command = runtime._run_managed_stage_command
    _verify_frozen_cad_python = runtime._verify_frozen_cad_python
    closure = plan.get("execution_source_closure")
    if closure is not None:
        verify_candidate_source_closure(closure)
    run_root = Path(plan["run_root"])
    logs = run_root / "logs"
    if closure is None:
        raise RuntimeError("candidate source closure is required")
    _verify_frozen_cad_python(closure, logs / "cad_python_preflight.log")
    environment = {key: str(value) for key, value in stage["environment"].items()}
    environment["OATOF_CANDIDATE_ARTIFACT_ROOT"] = str(
        Path(closure["runtime"]["candidate_artifact_root"]).resolve().parents[1]
    )
    build_report = Path(stage["report_path"])
    build_command = _powershell(
        frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
        [
            "-TaskScript",
            frozen_source_path(
                closure,
                "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m",
            ),
            "-ReportPath",
            str(build_report),
            "-RunId", plan["run_id"],
            "-CompletionPath", str(logs / "comsol_build_completion.json"),
        ],
    )
    _run_managed_stage_command(build_command, logs / "comsol_build_launcher.log", plan,
                               logs / "comsol_build_completion.json", "comsol_launcher_completion", environment)
    _require_pass_report(build_report)
    analysis_request = Path(_report_value(build_report, "PYTHON_ANALYSIS_REQUEST"))
    if not analysis_request.is_file():
        raise RuntimeError(f"COMSOL detector-event analysis request is missing: {analysis_request}")
    _run_command(
        [
            str(Path(closure["runtime"]["python_executable"]).resolve()),
            "-m",
            "projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events",
            "--request",
            str(analysis_request),
        ],
        logs / "comsol_detector_event_analysis.log",
    )
    request_document = load_json(analysis_request)
    analysis_output = Path(request_document["analysis_output_dir"])
    analysis_receipt = analysis_output / "analysis_receipt.json"
    if not analysis_receipt.is_file():
        raise RuntimeError(f"COMSOL detector-event Python analysis receipt is missing: {analysis_receipt}")
    sync_report = logs / "comsol_sync.txt"
    sync_environment = {
        "OATOF_COMSOL_MODEL_PATH": stage["model_path"],
        "OATOF_CONTRACT_PATH": stage["contract_path"],
    }
    sync_command = _powershell(
        frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
        [
            "-TaskScript",
            frozen_source_path(
                closure,
                "projects/single_reflection_oa_tof_mass_analyzer/comsol/verify_oatof_comsol_sync.m",
            ),
            "-ReportPath",
            str(sync_report),
            "-RunId", plan["run_id"],
            "-CompletionPath", str(logs / "comsol_sync_completion.json"),
        ],
    )
    _run_managed_stage_command(sync_command, logs / "comsol_sync_launcher.log", plan,
                               logs / "comsol_sync_completion.json", "comsol_launcher_completion", sync_environment)
    _require_pass_report(sync_report)
    return {
        "model": stage["model_path"], "build_report": str(build_report),
        "sync_report": str(sync_report), "analysis_request": str(analysis_request),
        "analysis_receipt": str(analysis_receipt),
    }
