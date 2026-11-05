"""Explicit transport to the original path-capacity and junction owner."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence
from msplatform.execution.context import ExecutionContext
from msplatform.execution.process_transport import _finish_bridge_after_failure
from msplatform.execution.resources import resource_path


def _path_operation(context: ExecutionContext, request: dict[str, Any]) -> dict[str, Any]:
    command = [str(context.powershell_executable), "-NoProfile", "-NonInteractive", "-File",
               str(resource_path("run_paths_owner.ps1"))]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, cwd=context.workspace)
    try:
        output, errors = process.communicate(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    except BaseException as failure:
        _finish_bridge_after_failure(process, failure)
        raise
    prefix = "EXECUTION_PATH_RESULT="
    lines = [line[len(prefix):] for line in output.decode("utf-8", "backslashreplace").splitlines()
             if line.startswith(prefix)]
    if process.returncode or len(lines) != 1:
        failure = RuntimeError(f"Execution path operation failed: exit={process.returncode}; stderr={errors!r}")
        failure.stdout, failure.stderr = output, errors
        raise failure
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        raise ValueError("Execution path operation must return one object")
    return value


def path_capacity(context: ExecutionContext, run_directory: Path, *,
                  additional_directories: Sequence[str] = (),
                  expected_relative_paths: Sequence[str] = ()) -> dict[str, Any]:
    return _path_operation(context, dict(action="capacity", run_directory=str(run_directory),
        additional_directories=list(additional_directories), expected_relative_paths=list(expected_relative_paths)))


def create_execution_alias(context: ExecutionContext, run_directory: Path, *,
                           additional_directories: Sequence[str] = (),
                           expected_relative_paths: Sequence[str] = ()) -> dict[str, Any]:
    return _path_operation(context, dict(action="create", run_directory=str(run_directory),
        execution_root=str(context.execution_root), additional_directories=list(additional_directories),
        expected_relative_paths=list(expected_relative_paths)))


def remove_execution_alias(context: ExecutionContext, alias: Path, run_directory: Path) -> None:
    _path_operation(context, dict(action="remove", run_directory=str(run_directory), execution_alias=str(alias)))
