"""Parse the narrow SIMION 2020 native Fly completion fact.

This is repository-observed stdout, rather than a SIMION-documented stable
output ABI: the frozen 20261023_103822 run ends with ``status,Fly completed.
9 splats, 269.62 seconds``.  SIMION's documented command-line interface
starts the process, but does not define this line's grammar.  Consequently
this module recognizes only that observed ``Fly completed`` form.  Projects
remain responsible for TRACE, particle identities, clocks, and scientific
terminal criteria.
"""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
import re
from typing import Iterable, Literal


_FLY_COMPLETED = re.compile(
    r"^status,Fly completed\. (?P<splats>\d+) splats"
    r"(?:, (?P<elapsed_seconds>\d+(?:\.\d+)?) seconds)?\r?\n?$"
)


@dataclass(frozen=True)
class FlyCompletion:
    """One observed native Fly completion line; no scientific conclusion."""

    splats: int
    elapsed_seconds: float | None


def parse_fly_completed_line(line: str) -> FlyCompletion | None:
    """Parse one whole observed SIMION 2020 completion line, or return ``None``.

    A bare completion prefix, an old spelling, or a malformed numeric field is
    deliberately not a completion fact.  Callers that require completion must
    reject ``None`` or use :func:`require_one_fly_completion`.
    """
    match = _FLY_COMPLETED.fullmatch(line)
    if match is None:
        return None
    seconds = match["elapsed_seconds"]
    return FlyCompletion(splats=int(match["splats"]), elapsed_seconds=(float(seconds) if seconds else None))


def require_one_fly_completion(lines: Iterable[str]) -> FlyCompletion:
    """Return exactly one native completion fact from an already-opened log stream."""
    completions = [completion for line in lines if (completion := parse_fly_completed_line(line)) is not None]
    if len(completions) != 1:
        raise ValueError("expected exactly one SIMION native Fly completion line")
    return completions[0]


def frontend_batch_completion_path(run_dir: Path, phase: str, case_id: str) -> Path:
    """Locate a small per-process fact without consulting native payloads."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", phase) or not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
        raise ValueError("frontend batch completion identity is invalid")
    return run_dir / "results" / "frontend_batch_completion" / phase / f"{case_id}.json"


def validate_frontend_batch_completion(path: Path, *, phase: str, case_id: str, stdout: Path,
                                       count: int, row_range: list[int]) -> None:
    """Validate an already manifest-verified process fact against its frozen case."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        valid = (isinstance(value, dict) and value.get("schema_version") == 1
                 and value.get("role") == "frontend_batch_natural_completion"
                 and value.get("phase") == phase and value.get("case_id") == case_id
                 and type(value.get("exit_code")) is int and value["exit_code"] == 0 and value.get("natural_exit") is True
                 and value.get("count") == count and value.get("source_row_range") == row_range
                 and isinstance(value.get("stdout_relative_path"), str)
                 and not Path(value["stdout_relative_path"]).is_absolute()
                 and (path.parents[3] / value["stdout_relative_path"]).resolve().is_relative_to(path.parents[3].resolve())
                 and (path.parents[3] / value["stdout_relative_path"]).resolve() == stdout.resolve())
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as error:
        raise ValueError("frontend batch completion receipt is invalid") from error
    if not valid:
        raise ValueError("frontend batch completion receipt differs from its frozen case")


def recoverable_batch_log_kind(path: Path) -> Literal["trace", "stdout"] | None:
    """Identify existing run-local recovery log names without reading their bytes."""
    if path.parent.name.lower() != "logs":
        return None
    for kind in ("trace", "stdout"):
        if fnmatch.fnmatch(path.name.lower(), f"simion__batch*.{kind}.log"):
            return kind
    return None


def has_recoverable_batch_completion(path: Path) -> bool:
    """Check the closing fact, keeping repository TRACE distinct from native stdout.

    TRACE producers use the exact bare sentinel. Native stdout must satisfy the
    observed numeric grammar above. Neither fact establishes scientific success.
    Read only the tail of a potentially large log; never rewrite its source.
    """
    kind = recoverable_batch_log_kind(path)
    if kind is None:
        return False
    with path.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        tail = bytearray()
        while position > 0 and tail.count(b"\n") < 2:
            chunk_size = min(4096, position)
            position -= chunk_size
            stream.seek(position)
            tail[:0] = stream.read(chunk_size)
    lines = [line for line in bytes(tail).splitlines() if line.strip()]
    if not lines:
        return False
    if kind == "trace":
        return lines[-1] == b"status,Fly completed."
    try:
        line = lines[-1].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return parse_fly_completed_line(line) is not None


def recoverable_batch_logs(run_dir: Path) -> set[Path]:
    """List direct batch log files for the existing failed-run retention boundary."""
    logs = run_dir / "logs"
    if not logs.is_dir():
        return set()
    return {path.resolve() for path in logs.iterdir()
            if path.is_file() and recoverable_batch_log_kind(path) is not None}
