"""Resolve canonical workspace roots once; project only explicit run-local paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Mapping


ROOT_FIELDS = ("source_root", "artifact_root", "execution_root", "host_resource_state_path")


def _absolute(value: str | os.PathLike[str], name: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ValueError(f"{name} requires a nonempty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} requires an absolute path: {value}")
    return path


def _validate_root_kinds(context: Mapping[str, str]) -> None:
    for name, value in context.items():
        path = Path(value)
        if path.exists() and (path.is_dir() if name == "host_resource_state_path" else not path.is_dir()):
            raise ValueError(f"{name} has the wrong filesystem kind: {value}")


def resolve_workspace_paths(
    source_root: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str] | None = None,
    execution_root: str | os.PathLike[str] | None = None,
    host_resource_state_path: str | os.PathLike[str] | None = None,
    frozen_context: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return canonical roots, independent of cwd and later environment changes.

    A frozen context is a complete authoritative selection, including its original
    checkout root. It is never inferred again from the current source snapshot.
    The caller freezes this small projection in its existing run configuration.
    """
    _absolute(source_root, "source_root")
    if frozen_context is not None:
        if not isinstance(frozen_context, Mapping) or set(frozen_context) != set(ROOT_FIELDS):
            raise ValueError("frozen workspace context requires exactly four root fields")
        result = {}
        for name in ROOT_FIELDS:
            value = frozen_context[name]
            path = _absolute(value, name)
            canonical = str(path.resolve())
            if str(path) != canonical:
                raise ValueError(f"frozen {name} is not canonical: {value}")
            result[name] = canonical
        _validate_root_kinds(result)
        return result
    source = _absolute(source_root, "source_root").resolve()
    if not source.is_dir():
        raise ValueError(f"initial source_root must be an existing directory: {source}")
    artifact = _absolute(artifact_root if artifact_root is not None else
                         os.environ.get("MASS_SPECTROMETRY_ARTIFACT_ROOT", str(source.parent / "artifacts")), "artifact_root").resolve()
    execution = _absolute(execution_root if execution_root is not None else
                          os.environ.get("MASS_SPECTROMETRY_EXECUTION_ROOT", str(artifact / "common/execution_aliases")), "execution_root").resolve()
    # The shared host budget keeps its existing identity when payload storage moves.
    host = _absolute(host_resource_state_path if host_resource_state_path is not None else
                     os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH", str(source.parent / "artifacts/common/host_resources.sqlite3")), "host_resource_state_path").resolve()
    result = dict(zip(ROOT_FIELDS, map(str, (source, artifact, execution, host))))
    _validate_root_kinds(result)
    return result


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


def _stdin_request() -> None:
    """Private PowerShell bridge; structured operations never execute commands."""
    request = json.load(sys.stdin)
    if request.get("operation") == "resolve":
        result = resolve_workspace_paths(**request["arguments"])
    elif request.get("operation") == "project":
        arguments = request["arguments"]
        result = [project_run_path(path, arguments["artifact_run_dir"], arguments["run_dir"])
                  for path in arguments["paths"]]
    else:
        raise ValueError("unknown workspace path bridge operation")
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    _stdin_request()
