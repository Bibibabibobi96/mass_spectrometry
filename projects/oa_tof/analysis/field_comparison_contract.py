"""Shared data-integrity and numerical contracts for field comparisons."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


def merge_complete_samples(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    keys: Sequence[str],
    left_label: str,
    right_label: str,
    suffixes: tuple[str, str] = ("_left", "_right"),
) -> pd.DataFrame:
    """Merge one-to-one samples only when both inputs have identical key coverage."""
    key_list = list(keys)
    for label, frame in ((left_label, left), (right_label, right)):
        missing = set(key_list) - set(frame.columns)
        if missing:
            raise ValueError(f"{label} misses sample keys: {sorted(missing)}")
        duplicated = frame.duplicated(key_list, keep=False)
        if duplicated.any():
            raise ValueError(
                f"{label} contains duplicate sample keys: "
                f"{int(duplicated.sum())} rows"
            )

    coverage = left[key_list].merge(
        right[key_list],
        on=key_list,
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    left_only = int((coverage["_merge"] == "left_only").sum())
    right_only = int((coverage["_merge"] == "right_only").sum())
    if left_only or right_only:
        raise ValueError(
            "Field sample coverage differs: "
            f"{left_label}_only={left_only}, {right_label}_only={right_only}"
        )

    return (
        left.merge(
            right,
            on=key_list,
            how="inner",
            suffixes=suffixes,
            validate="one_to_one",
        )
        .sort_values(key_list, kind="stable")
        .reset_index(drop=True)
    )


def normalized_rms_difference_pct(
    reference: np.ndarray,
    values: np.ndarray,
) -> dict[str, float | None]:
    """Return scale-aware RMS ratios without dividing by a near-zero reference."""
    reference = np.asarray(reference, dtype=float)
    values = np.asarray(values, dtype=float)
    if reference.shape != values.shape or reference.size == 0:
        raise ValueError("Field arrays must be nonempty and have identical shapes")
    if not np.isfinite(reference).all() or not np.isfinite(values).all():
        raise ValueError("Field arrays must contain only finite values")

    difference_rms = float(np.sqrt(np.mean((values - reference) ** 2)))
    reference_rms = float(np.sqrt(np.mean(reference**2)))
    values_rms = float(np.sqrt(np.mean(values**2)))
    symmetric_scale = max(reference_rms, values_rms)
    numerical_floor = np.finfo(float).eps * max(symmetric_scale, 1.0)
    relative_to_reference = (
        100.0 * difference_rms / reference_rms
        if reference_rms > numerical_floor
        else None
    )
    symmetric_ratio = (
        100.0 * difference_rms / symmetric_scale
        if symmetric_scale > numerical_floor
        else 0.0
    )
    return {
        "reference_rms_V_per_m": reference_rms,
        "values_rms_V_per_m": values_rms,
        "difference_rms_V_per_m": difference_rms,
        "relative_to_reference_rms_pct": relative_to_reference,
        "symmetric_scale_pct": symmetric_ratio,
        "numerical_zero_floor_V_per_m": numerical_floor,
    }


def convergence_decision() -> dict[str, Any]:
    """State that metrics alone cannot establish convergence without criteria."""
    return {
        "status": "NOT_EVALUATED",
        "reason": "NO_ACCEPTANCE_CRITERIA",
        "claim_limit": (
            "The script reports field changes only; it does not claim mesh "
            "convergence without an approved acceptance contract."
        ),
    }
