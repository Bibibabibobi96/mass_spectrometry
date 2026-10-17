"""Fail-closed validators for callback-neutral integration components."""

from __future__ import annotations

import re


class BoundaryContractError(ValueError):
    """Raised when a pure integration boundary is incomplete or ambiguous."""


_FORBIDDEN_LUA_PATTERNS = {
    "simion.workbench_program": re.compile(r"(?<![\w.])simion\s*\.\s*workbench_program\b"),
    "segment.": re.compile(r"(?<!\w)segment\s*\."),
    "adj_elect": re.compile(r"(?<!\w)adj_elect(?!\w)"),
    "ion_time_of_birth": re.compile(r"(?<!\w)ion_time_of_birth(?!\w)"),
    "ion_time_of_flight": re.compile(r"(?<!\w)ion_time_of_flight(?!\w)"),
    "simion.wb": re.compile(r"(?<![\w.])simion\s*\.\s*wb\b"),
    "os.clock": re.compile(r"(?<![\w.])os\s*\.\s*clock\b"),
}


def validate_pure_lua_component_source(source: str, name: str) -> str:
    """Reject callback, electrode, native-clock, and Workbench ownership in Lua.

    The returned source is unchanged.  This validator is the single Python
    boundary used before callback-neutral Lua is embedded into a SIMION Program.
    """
    if not isinstance(source, str) or not source.strip():
        raise BoundaryContractError(f"{name} must be non-empty Lua source")
    if not isinstance(name, str) or not name.strip():
        raise BoundaryContractError("pure Lua component name must be non-empty")
    violations = [
        token for token, pattern in _FORBIDDEN_LUA_PATTERNS.items() if pattern.search(source)
    ]
    if violations:
        raise BoundaryContractError(
            f"{name} is not callback-neutral; forbidden tokens: {', '.join(violations)}"
        )
    return source
