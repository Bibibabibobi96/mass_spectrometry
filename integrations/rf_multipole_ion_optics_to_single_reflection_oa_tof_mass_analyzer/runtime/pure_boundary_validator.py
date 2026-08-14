"""Fail-closed validators for callback-neutral integration components."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Set
from typing import Any, TypeVar


class BoundaryContractError(ValueError):
    """Raised when a pure integration boundary is incomplete or ambiguous."""


_T = TypeVar("_T")
_FORBIDDEN_LUA_PATTERNS = {
    "simion.workbench_program": re.compile(r"(?<![\w.])simion\s*\.\s*workbench_program\b"),
    "segment.": re.compile(r"(?<!\w)segment\s*\."),
    "adj_elect": re.compile(r"(?<!\w)adj_elect(?!\w)"),
    "ion_time_of_birth": re.compile(r"(?<!\w)ion_time_of_birth(?!\w)"),
    "ion_time_of_flight": re.compile(r"(?<!\w)ion_time_of_flight(?!\w)"),
    "simion.wb": re.compile(r"(?<![\w.])simion\s*\.\s*wb\b"),
    "os.clock": re.compile(r"(?<![\w.])os\s*\.\s*clock\b"),
}


def validate_exact_mapping(
    value: object, *, name: str, required_keys: Set[str]
) -> Mapping[str, Any]:
    """Return a mapping only when it has exactly the declared string keys."""
    if not isinstance(value, Mapping):
        raise BoundaryContractError(f"{name} must be a mapping")
    actual = set(value)
    if actual != set(required_keys):
        missing = sorted(set(required_keys) - actual)
        unknown = sorted(actual - set(required_keys), key=str)
        raise BoundaryContractError(
            f"{name} fields mismatch: missing={missing}, unknown={unknown}"
        )
    return value


def validate_finite_number(value: object, *, name: str) -> float:
    """Return a finite non-boolean float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoundaryContractError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise BoundaryContractError(f"{name} must be a finite number")
    return result


def validate_positive_number(value: object, *, name: str) -> float:
    """Return a finite number strictly greater than zero."""
    result = validate_finite_number(value, name=name)
    if result <= 0:
        raise BoundaryContractError(f"{name} must be positive")
    return result


def validate_integer(value: object, *, name: str, minimum: int | None = None) -> int:
    """Return a non-boolean integer satisfying the optional lower bound."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BoundaryContractError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise BoundaryContractError(f"{name} must be at least {minimum}")
    return value


def validate_callable(value: object, *, name: str) -> Callable[..., Any]:
    """Return a callable dependency or fail before code generation."""
    if not callable(value):
        raise BoundaryContractError(f"{name} must be callable")
    return value


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
