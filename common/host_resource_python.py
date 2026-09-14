"""Shared heavy-entry adapter for repository Python 3.11 computations.

MR/OA theory and multipole transport consumers call ``ensure_heavy_entry`` at
their CLI boundary, before computation or pool creation. Mixed campaigns use
``run_heavy_function`` for one complete pool instead of reentering their main.
This module owns no
ledger or worker scheduler. Existing worker counts, numerical algorithms and
checkpoint behavior remain the responsibility of each consumer.
"""

from __future__ import annotations

import json
import importlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

_TOKEN = "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN"
_REENTRY = "MASS_SPECTROMETRY_PYTHON_HEAVY_REENTRY"
_RESULT = "HOST_RESOURCE_PYTHON_RESULT="


def _bridge(operation: str, **payload: Any) -> subprocess.CompletedProcess:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Repository heavy Python entry requires Python 3.11")
    if os.name != "nt":
        raise RuntimeError("Host resource execution requires Windows PowerShell 7")
    request = {"schema_version": 1, "operation": operation,
               "python": str(Path(sys.executable).resolve()), **payload}
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
         str(Path(__file__).with_suffix(".ps1"))],
        input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        cwd=Path.cwd(),
        # Solver/workflow budgets own enter/call deadlines. Assert already uses
        # the facade's 45-second transaction timeout and contention retry loop;
        # a second outer deadline would incorrectly cut off valid admission.
        timeout=None,
        # Entry keeps normal task output visible; machine-only operations use
        # bytes so Windows console encodings cannot corrupt protocol parsing.
        capture_output=operation not in {"enter", "call"}, check=False,
    )


def _read_result(result: subprocess.CompletedProcess) -> dict[str, Any]:
    if result.returncode:
        raise RuntimeError(f"Host resource bridge failed ({result.returncode}): {result.stderr!r}")
    lines = result.stdout.decode("utf-8").splitlines()
    records = [line[len(_RESULT):] for line in lines if line.startswith(_RESULT)]
    if len(records) != 1:
        raise RuntimeError("Host resource bridge returned no unique result")
    value = json.loads(records[0])
    if not isinstance(value, dict):
        raise RuntimeError("Host resource bridge result must be an object")
    return value


def ensure_heavy_entry(
    module: str, argv: list[str] | None = None, *, role: str = "GATE", stage: str = "theory_compute",
) -> None:
    """Verify a live heavy grant, or reenter this module once under that grant.

    Call with the importable module name, not ``__main__`` or a shell command.
    The original invocation exits with the managed invocation's exit code.
    Arguments are transported as strings, never interpolated into shell code.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module) or module == "__main__":
        raise ValueError("heavy entry requires an importable Python module name")
    if role not in {"GATE", "SIMION", "COMSOL"} or not re.fullmatch(r"[A-Za-z_]\w*", stage):
        raise ValueError("heavy entry requires a known role and named stage")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(not isinstance(argument, str) or "\0" in argument for argument in arguments):
        raise ValueError("heavy entry arguments must be strings without NUL")
    if os.environ.get(_TOKEN):
        if _read_result(_bridge("assert")).get("heavy") is not True:
            raise RuntimeError("Host resource bridge did not verify a heavy grant")
        return
    if os.environ.get(_REENTRY):
        raise RuntimeError("Managed Python reentry lost its heavy token; refusing another reentry")
    raise SystemExit(_bridge("enter", module=module, argv=arguments, role=role, stage=stage).returncode)


def _encode_value(value: Any) -> Any:
    """Use tagged containers so user dictionaries cannot impersonate a Path."""
    if isinstance(value, Path):
        return {"kind": "path", "value": str(value)}
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {"kind": "dict", "value": {key: _encode_value(item) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return {"kind": "tuple" if isinstance(value, tuple) else "list", "value": [_encode_value(item) for item in value]}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported stage argument/result type: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    kind, payload = value["kind"], value["value"]
    if kind == "path":
        return Path(payload)
    if kind == "dict":
        return {key: _decode_value(item) for key, item in payload.items()}
    if kind in {"list", "tuple"}:
        items = [_decode_value(item) for item in payload]
        return tuple(items) if kind == "tuple" else items
    raise ValueError(f"Unknown stage value kind: {kind}")


def run_heavy_function(module: str, function: str, *args: Any,
                       role: str = "SIMION", stage: str = "flight", **kwargs: Any) -> Any:
    """Run one complete pool function under a grant; never grant individual workers.

    Inherited heavy callers stay in-process. A light parent is rejected, never
    detached. Standalone calls use a short-lived managed child and temporary
    JSON result; progress/error streams remain attached to the calling console.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module) or module == "__main__":
        raise ValueError("stage call requires an importable module")
    if not re.fullmatch(r"[A-Za-z_]\w*", function):
        raise ValueError("stage call requires a simple function name")
    if role not in {"GATE", "SIMION", "COMSOL"} or not re.fullmatch(r"[A-Za-z_]\w*", stage):
        raise ValueError("stage call requires a known role and named stage")
    if os.environ.get(_TOKEN):
        if _read_result(_bridge("assert")).get("heavy") is not True:
            raise RuntimeError("Stage call requires an inherited heavy grant")
        return getattr(importlib.import_module(module), function)(*args, **kwargs)
    if os.environ.get(_REENTRY):
        raise RuntimeError("Managed Python reentry lost its heavy token")
    with tempfile.TemporaryDirectory(prefix="host-resource-python-call-") as directory:
        result_path = Path(directory) / "result.json"
        result = _bridge("call", module=module, function=function, role=role, stage=stage,
                         args=_encode_value(args), kwargs=_encode_value(kwargs), result_path=str(result_path))
        if result.returncode:
            raise RuntimeError(f"Managed stage {module}.{function} failed ({result.returncode}); see preceding stderr")
        return _decode_value(json.loads(result_path.read_text(encoding="utf-8")))


def _execute_call() -> None:
    """Internal bridge target; stdin carries data, never executable source."""
    request = json.load(sys.stdin)
    if _read_result(_bridge("assert")).get("heavy") is not True:
        raise RuntimeError("Managed function has no verified heavy grant")
    result = getattr(importlib.import_module(request["module"]), request["function"])(
        *_decode_value(request["args"]), **_decode_value(request["kwargs"]))
    Path(request["result_path"]).write_text(json.dumps(_encode_value(result)), encoding="utf-8")
