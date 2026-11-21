"""Shared structured expected-value checks for solver-free reference CLIs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def assert_expected_values(
    actual: Any,
    expected: Any,
    path: str,
    *,
    abs_tol: float,
    rel_tol: float,
    sequence_length_message: str = "sequence length differs",
) -> None:
    """Compare a partial expected tree, raising SystemExit at the first mismatch.

    Mapping expectations allow additional actual keys; sequences require equal
    lengths. Numeric expectations use caller-supplied absolute/relative tolerances,
    while other leaves retain Python equality. This is a CLI reference assertion,
    not a schema/type validator. The optional length message is presentation only
    and may contain {actual} and {expected} length placeholders.
    """
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise SystemExit(f"MISMATCH {path}: actual is not a mapping")
        for key, value in expected.items():
            if key not in actual:
                raise SystemExit(f"MISMATCH {path}.{key}: missing actual key")
            assert_expected_values(
                actual[key], value, f"{path}.{key}", abs_tol=abs_tol, rel_tol=rel_tol,
                sequence_length_message=sequence_length_message
            )
        return
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes)):
            raise SystemExit(f"MISMATCH {path}: actual is not a sequence")
        if len(actual) != len(expected):
            message = sequence_length_message.format(actual=len(actual), expected=len(expected))
            raise SystemExit(f"MISMATCH {path}: {message}")
        for index, (a_value, e_value) in enumerate(zip(actual, expected, strict=True)):
            assert_expected_values(
                a_value,
                e_value,
                f"{path}[{index}]",
                abs_tol=abs_tol,
                rel_tol=rel_tol,
                sequence_length_message=sequence_length_message,
            )
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not math.isclose(
            float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol
        ):
            raise SystemExit(
                f"MISMATCH {path}: actual={actual!r} expected={expected!r}"
            )
        return
    if actual != expected:
        raise SystemExit(f"MISMATCH {path}: actual={actual!r} expected={expected!r}")
