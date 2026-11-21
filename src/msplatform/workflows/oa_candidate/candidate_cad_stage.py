"""Frozen CAD Candidate construction and scientific completion checks."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from msplatform.workflows.oa_candidate.candidate_source_closure import frozen_source_path, verify_candidate_source_closure

def execute_cad_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str, *, runtime: Any) -> dict[str, Any]:
    """Execute the declared frozen CAD stage using owner-managed processes."""
    from .candidate_stage_execution import _powershell, _require_pass_report, native_execution_context
    _run_managed_stage_command = runtime._run_managed_stage_command
    host_context, execution = native_execution_context(plan, Path(plan["run_root"]))
    closure = plan.get("execution_source_closure")
    if closure is not None:
        verify_candidate_source_closure(closure)
    run_root = Path(plan["run_root"])
    logs = run_root / "logs"
    if closure is None:
        raise RuntimeError("candidate source closure is required")
    report = logs / "cad_build.txt"
    environment = {
        "OATOF_CANDIDATE_MODEL_PATH": stage["model_path"],
        "OATOF_CANDIDATE_CAD_DIR": stage["output_dir"],
        "OATOF_CANDIDATE_ARTIFACT_ROOT": str(
            Path(closure["runtime"]["candidate_artifact_root"]).resolve().parents[1]
        ),
        "OATOF_CANDIDATE_PYTHON_EXECUTABLE": str(
            Path(closure["runtime"]["python_executable"]).resolve()
        ),
    }
    command = _powershell(
        frozen_source_path(closure, "src/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1"),
        [
            "-HostContextJson", host_context,
            "-WorkingDirectory", execution,
            "-TaskScript",
            frozen_source_path(
                closure,
                "src/msplatform/backends/comsol/matlab/run_candidate_cad_sync.m",
            ),
            "-ReportPath",
            str(report),
            "-RunId", plan["run_id"],
            "-RunDir", execution,
            "-CompletionPath", str(logs / "cad_completion.json"),
        ],
    )
    _run_managed_stage_command(command, logs / "cad_launcher.log", plan,
                               logs / "cad_completion.json", "comsol_launcher_completion", environment)
    _require_pass_report(report)
    cad_report = Path(stage["output_dir"]) / "oaTOF_solidworks_export_report.json"
    if not cad_report.is_file():
        raise RuntimeError(f"candidate CAD report is missing: {cad_report}")
    return {"report": str(report), "cad_report": str(cad_report)}
