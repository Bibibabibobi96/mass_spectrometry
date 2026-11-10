"""Canonical lexical projection and transport to the existing junction owner."""
from __future__ import annotations
import json
import os
import sys
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


def _absolute(value: str | os.PathLike[str], name: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ValueError(f"{name} requires a nonempty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} requires an absolute path: {value}")
    return path


def project_run_path(
    path: str | os.PathLike[str], artifact_run_dir: str | os.PathLike[str], run_dir: str | os.PathLike[str],
) -> str:
    """Map only a lexical canonical-run descendant into its execution spelling.

    Do not resolve execution junctions: doing so would restore the long native
    path. External read-only inputs and paths already in the execution view stay
    unchanged. This projection is never a substitute for canonical identity.
    """
    original = os.fspath(path)
    persistent = _absolute(artifact_run_dir, "artifact_run_dir")
    execution = _absolute(run_dir, "run_dir")
    candidate = Path(original)
    try:
        relative = candidate.relative_to(persistent)
    except ValueError:
        return original
    if ".." in relative.parts:
        raise ValueError("run path projection requires a normalized path without '..'")
    return str(execution / relative)


def project_native_run_path(path: str | os.PathLike[str]) -> str:
    """Project explicit native-consumer paths using the current process context.

    Read on every call: modules can be imported before the owner establishes a
    native execution view. These ephemeral spellings never enter file identity.
    """
    persistent = os.environ.get("MASS_SPECTROMETRY_RUN_DIRECTORY")
    execution = os.environ.get("MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY")
    if persistent is None and execution is None:
        return os.fspath(path)
    if not persistent or not execution:
        raise ValueError("native run projection requires both canonical and execution directories")
    return project_run_path(path, persistent, execution)



def _stdin_project_paths() -> None:
    """Original private project request transport; no new public CLI."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    if request.get("operation") != "project":
        raise ValueError("unknown workspace path bridge operation")
    arguments = request["arguments"]
    result = [project_run_path(path, arguments["artifact_run_dir"], arguments["run_dir"])
              for path in arguments["paths"]]
    json.dump(result, sys.stdout, ensure_ascii=False)
