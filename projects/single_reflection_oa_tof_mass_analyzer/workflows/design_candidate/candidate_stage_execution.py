"""Pure argument transport and dispatch for the Candidate native stages."""
from __future__ import annotations

from pathlib import Path
from typing import Any

def _powershell(entrypoint: str, arguments: list[str]) -> list[str]:
    # The shared COMSOL launcher uses ProcessStartInfo.ArgumentList, which is
    # unavailable under Windows PowerShell 5.1.  Keep integrated commercial
    # workflows on the repository's PowerShell 7 runtime.
    return ["pwsh.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", entrypoint, *arguments]

def _require_pass_report(path: Path) -> None:
    if not path.is_file() or "STATUS=PASS" not in path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"required PASS report is missing or failed: {path}")



from .candidate_comsol_stage import execute_comsol_stage
from .candidate_simion_stage import execute_simion_stage
from .candidate_cad_stage import execute_cad_stage

def execute_candidate_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str, *, runtime: Any) -> dict[str, Any]:
    """Dispatch native stages; each stage owns its frozen scientific construction."""
    stage_id = stage["stage_id"]
    if stage_id == "comsol_candidate":
        return execute_comsol_stage(stage, plan, simion_exe, runtime=runtime)
    if stage_id == "simion_candidate":
        return execute_simion_stage(stage, plan, simion_exe, runtime=runtime)
    if stage_id == "cad_candidate":
        return execute_cad_stage(stage, plan, simion_exe, runtime=runtime)
    raise ValueError(f"unsupported candidate native stage: {stage_id}")
