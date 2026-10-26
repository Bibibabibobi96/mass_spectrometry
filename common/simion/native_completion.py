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
import re
from typing import Iterable


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
