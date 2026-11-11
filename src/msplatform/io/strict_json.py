"""Small, fail-closed primitives for machine-contract JSON readers.

This module deliberately contains only representation checks.  Project
resolvers keep ownership of their identities, physical ranges, and cross-field
rules.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class StrictJsonError(ValueError):
    """Raised when a JSON value is not a strict machine-contract value."""


def require_exact_keys(
    value: dict[str, Any], expected: set[str], context: str
) -> None:
    """Require an object to have exactly the declared keys."""

    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise StrictJsonError(
            f"{context} keys mismatch; missing={missing}, unknown={unknown}"
        )


def require_dict(value: Any, context: str) -> dict[str, Any]:
    """Require a JSON object."""

    if not isinstance(value, dict):
        raise StrictJsonError(f"{context} must be an object")
    return value


def require_bool(value: Any, context: str) -> bool:
    """Require a JSON boolean without accepting integer lookalikes."""

    if not isinstance(value, bool):
        raise StrictJsonError(f"{context} must be boolean")
    return value


def require_string(value: Any, context: str) -> str:
    """Require a non-empty JSON string."""

    if not isinstance(value, str) or not value:
        raise StrictJsonError(f"{context} must be a non-empty string")
    return value


def require_number(
    value: Any,
    context: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    strict_minimum: bool = False,
) -> float:
    """Require a finite JSON number and apply caller-supplied bounds."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrictJsonError(f"{context} must be numeric")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise StrictJsonError(f"{context} must be finite") from exc
    if not math.isfinite(numeric):
        raise StrictJsonError(f"{context} must be finite")
    if minimum is not None:
        if strict_minimum and numeric <= minimum:
            raise StrictJsonError(f"{context} must be > {minimum}")
        if not strict_minimum and numeric < minimum:
            raise StrictJsonError(f"{context} must be >= {minimum}")
    if maximum is not None and numeric > maximum:
        raise StrictJsonError(f"{context} must be <= {maximum}")
    return numeric


def require_positive_integer(value: Any, context: str) -> int:
    """Require a positive JSON integer without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StrictJsonError(f"{context} must be a positive integer")
    return value


def load_json_object(path: Path) -> dict[str, Any]:
    """Read UTF-8 (optional BOM) object JSON without duplicate/nonfinite values.

    Parsing is representation-only: project identities, units, scientific bounds
    and frozen byte identities remain the caller's responsibility.
    """

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise StrictJsonError(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def finite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise StrictJsonError(f"{path}: non-finite JSON number {token}")
        return value

    def reject_constant(token: str) -> None:
        raise StrictJsonError(f"{path}: non-finite JSON number {token}")

    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            value = json.load(stream, object_pairs_hook=unique_object,
                              parse_float=finite_float, parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrictJsonError(f"cannot read {path}: {exc}") from exc
    return require_dict(value, str(path))
