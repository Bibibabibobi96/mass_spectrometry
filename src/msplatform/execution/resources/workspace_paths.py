"""Canonical workspace, run-owner and platform artifact paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping
from msplatform.execution import run_paths as _paths


ROOT_FIELDS = ("source_root", "artifact_root", "execution_root", "host_resource_state_path")
RUN_OWNER_COLLECTIONS = {"component": "components", "assembly": "assemblies"}
ARTIFACT_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")


def resolve_run_artifact_root(
    artifact_root: str | os.PathLike[str], *, owner_kind: str, owner_id: str,
) -> Path:
    """Return the sole new-run root for a component or the instrument assembly."""

    root = Path(artifact_root).resolve()
    if owner_kind not in RUN_OWNER_COLLECTIONS:
        raise ValueError("run owner_kind must be 'component' or 'assembly'")
    if ARTIFACT_ID.fullmatch(owner_id) is None:
        raise ValueError("run owner_id must be a lowercase snake_case identifier")
    if owner_kind == "assembly" and owner_id != "instrument_assembly":
        raise ValueError("the only assembly run owner is instrument_assembly")
    return root / RUN_OWNER_COLLECTIONS[owner_kind] / owner_id


def resolve_platform_artifact_path(
    artifact_root: str | os.PathLike[str], *relative_parts: str,
) -> Path:
    """Return a contained platform path; historical roots require explicit paths."""

    if not relative_parts:
        raise ValueError("platform artifact path requires at least one relative part")
    if any(not isinstance(part, str) or not part for part in relative_parts):
        raise ValueError("platform artifact path parts must be nonempty strings")
    relative = Path(*relative_parts)
    if relative.is_absolute() or relative.drive or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("platform artifact path must be a contained relative path")
    return Path(artifact_root).resolve() / "platform" / relative




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
    source = _paths._absolute(source_root, "source_root")
    if frozen_context is not None:
        if not isinstance(frozen_context, Mapping) or set(frozen_context) != set(ROOT_FIELDS):
            raise ValueError("frozen workspace context requires exactly four root fields")
        result = {}
        for name in ROOT_FIELDS:
            value = frozen_context[name]
            path = _paths._absolute(value, name)
            canonical = str(path.resolve())
            if str(path) != canonical:
                raise ValueError(f"frozen {name} is not canonical: {value}")
            result[name] = canonical
        _validate_root_kinds(result)
        return result
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"initial source_root must be an existing directory: {source}")
    artifact = _paths._absolute(artifact_root if artifact_root is not None else
                         os.environ.get("MASS_SPECTROMETRY_ARTIFACT_ROOT", str(source.parent / "artifacts")), "artifact_root").resolve()
    execution = _paths._absolute(execution_root if execution_root is not None else
                          os.environ.get("MASS_SPECTROMETRY_EXECUTION_ROOT", str(resolve_platform_artifact_path(artifact, "execution_aliases"))), "execution_root").resolve()
    # An overridden payload root does not silently create another host scheduler.
    host = _paths._absolute(host_resource_state_path if host_resource_state_path is not None else
                     os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH", str(resolve_platform_artifact_path(source.parent / "artifacts", "host_resources.sqlite3"))), "host_resource_state_path").resolve()
    result = dict(zip(ROOT_FIELDS, map(str, (source, artifact, execution, host))))
    _validate_root_kinds(result)
    return result






def _stdin_request() -> None:
    """Private PowerShell bridge; structured operations never execute commands."""
    # Match the caller's UTF-8 pipes, including diagnostics, regardless of locale.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    if request.get("operation") == "resolve":
        result = resolve_workspace_paths(**request["arguments"])
    elif request.get("operation") == "run_root":
        result = str(resolve_run_artifact_root(**request["arguments"]))
    elif request.get("operation") == "platform":
        arguments = request["arguments"]
        result = str(resolve_platform_artifact_path(arguments["artifact_root"], *arguments["relative_parts"]))
    else:
        raise ValueError("unknown workspace path bridge operation")
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    _stdin_request()
