"""Read and reduce SIMION PA field-comparison CSV output.

The module owns only the solver-output protocol and residual arithmetic. It
does not assign samples to physical regions or define acceptance thresholds.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence


RESIDUAL_COLUMNS = (
    "delta_potential_V",
    "delta_ex_V_per_mm",
    "delta_ey_V_per_mm",
    "delta_ez_V_per_mm",
)


class FieldComparisonError(ValueError):
    """Raised when a field-comparison CSV or residual set is invalid."""


@dataclass(frozen=True)
class FieldComparisonRow:
    """One validated comparison row with text and finite numeric fields."""

    text: Mapping[str, str]
    numeric: Mapping[str, float]


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FieldComparisonError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise FieldComparisonError(f"{label} must be finite")
    return result


def read_field_comparison_csv(
    path: str | Path,
    *,
    required_columns: Iterable[str] = (),
    finite_columns: Iterable[str] = (),
) -> list[FieldComparisonRow]:
    """Read comparison rows and validate all requested numeric fields.

    The four residual columns emitted by ``compare_pa_fields_at_samples.lua``
    are always required and finite. Callers may require protocol extensions
    such as sample coordinates or frozen contract identities without moving
    their project semantics into this module.
    """

    source = Path(path)
    requested = tuple(required_columns)
    requested_finite = tuple(finite_columns)
    required = set(RESIDUAL_COLUMNS) | set(requested) | set(requested_finite)
    numeric_columns = tuple(dict.fromkeys((*RESIDUAL_COLUMNS, *requested_finite)))
    rows: list[FieldComparisonRow] = []
    try:
        with source.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise FieldComparisonError(f"field comparison columns differ: {source}")
            for raw in reader:
                numeric = {
                    column: _finite(raw[column], column)
                    for column in numeric_columns
                }
                rows.append(FieldComparisonRow(text=dict(raw), numeric=numeric))
    except OSError as exc:
        raise FieldComparisonError(f"field comparison CSV is unreadable: {source}") from exc
    return rows


def _rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def compute_field_residual_metrics(
    rows: Iterable[FieldComparisonRow],
) -> dict[str, int | float]:
    """Compute RMS and maximum residuals without applying acceptance limits."""

    samples = tuple(rows)
    if not samples:
        raise FieldComparisonError("field comparison is empty")
    potential = [row.numeric["delta_potential_V"] for row in samples]
    ex = [row.numeric["delta_ex_V_per_mm"] for row in samples]
    ey = [row.numeric["delta_ey_V_per_mm"] for row in samples]
    ez = [row.numeric["delta_ez_V_per_mm"] for row in samples]
    field = [
        math.sqrt(dx * dx + dy * dy + dz * dz)
        for dx, dy, dz in zip(ex, ey, ez)
    ]
    return {
        "sample_count": len(samples),
        "delta_potential_rms_V": _rms(potential),
        "delta_potential_max_abs_V": max(abs(value) for value in potential),
        "delta_field_rms_V_per_mm": _rms(field),
        "delta_field_max_V_per_mm": max(field),
        "delta_ex_rms_V_per_mm": _rms(ex),
        "delta_ey_rms_V_per_mm": _rms(ey),
        "delta_ez_rms_V_per_mm": _rms(ez),
    }


def compute_delta_field_rms(
    rows: Iterable[FieldComparisonRow],
) -> float:
    """Compute vector-field RMS using the legacy component accumulation order."""

    samples = tuple(rows)
    if not samples:
        raise FieldComparisonError("field comparison is empty")
    return math.sqrt(
        sum(
            row.numeric["delta_ex_V_per_mm"] ** 2
            + row.numeric["delta_ey_V_per_mm"] ** 2
            + row.numeric["delta_ez_V_per_mm"] ** 2
            for row in samples
        )
        / len(samples)
    )


__all__ = [
    "FieldComparisonError",
    "FieldComparisonRow",
    "compute_delta_field_rms",
    "compute_field_residual_metrics",
    "read_field_comparison_csv",
]
