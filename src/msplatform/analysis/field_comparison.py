"""Shared data-integrity and numerical contracts for field comparisons."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from msplatform.contracts.rigid_transform import RigidTransform
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


def compare_static_field_samples(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    reference_metadata: dict[str, Any],
    candidate_metadata: dict[str, Any],
    reference_transform: RigidTransform,
    candidate_transform: RigidTransform,
    coordinate_tolerance_mm: float,
) -> dict[str, Any]:
    """Compare explicit static samples after declared rigid frame transforms.

    Metadata carries caller-owned source identity, BVP, frame, units and optional
    potential reference; this pure function does not validate external files.
    Statuses are explicit and all IDs remain in the returned coverage audit.
    """
    from msplatform.contracts.rigid_transform import FramedPosition, FramedVector

    if isinstance(coordinate_tolerance_mm, (bool, np.bool_)) or not np.isfinite(coordinate_tolerance_mm) or coordinate_tolerance_mm < 0:
        raise ValueError("coordinate tolerance must be finite and nonnegative")
    required_meta = {"source", "bvp", "frame_id", "units", "potential_reference"}
    for label, metadata, transform in (("reference", reference_metadata, reference_transform),
                                       ("candidate", candidate_metadata, candidate_transform)):
        if not isinstance(metadata, dict) or set(metadata) != required_meta:
            raise ValueError(f"{label} metadata fields differ")
        if not isinstance(metadata["source"], dict) or not metadata["source"]:
            raise ValueError(f"{label} source identity is required")
        if not isinstance(metadata["bvp"], dict) or not metadata["bvp"]:
            raise ValueError(f"{label} BVP is required")
        if metadata["units"] != {"length": "mm", "electric_field": "V/m", "potential": "V"}:
            raise ValueError(f"{label} units differ")
        if not isinstance(transform, RigidTransform) or transform.from_frame_id != metadata["frame_id"]:
            raise ValueError(f"{label} frame transform differs")
    if reference_transform.to_frame_id != candidate_transform.to_frame_id:
        raise ValueError("common frame differs")
    if reference_metadata["bvp"] != candidate_metadata["bvp"]:
        raise ValueError("BVP differs")
    if reference_metadata["potential_reference"] != candidate_metadata["potential_reference"]:
        raise ValueError("potential reference differs")
    states = {"valid", "solid", "interface", "outside", "excluded", "sample_error"}
    required = {"point_id", "x_mm", "y_mm", "z_mm", "Ex_V_per_m", "Ey_V_per_m", "Ez_V_per_m", "status"}
    transformed = []
    for label, frame, metadata, transform in (("reference", reference, reference_metadata, reference_transform),
                                               ("candidate", candidate, candidate_metadata, candidate_transform)):
        if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns) or frame.empty:
            raise ValueError(f"{label} samples missing required fields or empty")
        if frame["point_id"].isna().any() or frame["point_id"].duplicated().any():
            raise ValueError(f"{label} point IDs must be unique and non-null")
        if not frame["status"].isin(states).all():
            raise ValueError(f"{label} has an unknown sample status")
        rows = []
        for row in frame.to_dict("records"):
            pos = transform.transform_position(FramedPosition(metadata["frame_id"],
                (row["x_mm"], row["y_mm"], row["z_mm"]))).coordinates_mm
            item = {"point_id": row["point_id"], "status": row["status"], "position_mm": pos}
            if row["status"] == "valid":
                vector = transform.transform_vector(FramedVector(metadata["frame_id"],
                    (row["Ex_V_per_m"], row["Ey_V_per_m"], row["Ez_V_per_m"]), "polar")).components
                item["field"] = vector
                if "potential_V" in frame.columns:
                    value = float(row["potential_V"])
                    if not np.isfinite(value):
                        raise ValueError(f"{label} potential must be finite")
                    item["potential_V"] = value
            rows.append(item)
        transformed.append({row["point_id"]: row for row in rows})
    if ("potential_V" in reference.columns) != ("potential_V" in candidate.columns):
        raise ValueError("potential availability differs")
    if "potential_V" in reference.columns and not reference_metadata["potential_reference"]:
        raise ValueError("potential reference is required")
    left, right = transformed
    ids = sorted(set(left) | set(right), key=lambda value: (type(value).__name__, str(value)))
    coverage = []
    valid_left, valid_right = [], []
    for point_id in ids:
        a, b = left.get(point_id), right.get(point_id)
        if a is not None and b is not None and not np.allclose(a["position_mm"], b["position_mm"], rtol=0, atol=coordinate_tolerance_mm):
            raise ValueError(f"sample coordinates differ for {point_id}")
        coverage.append({"point_id": point_id, "reference": a["status"] if a else "missing",
                         "candidate": b["status"] if b else "missing"})
        if a and b and a["status"] == b["status"] == "valid":
            valid_left.append(a); valid_right.append(b)
    metrics = None
    if valid_left:
        a = np.asarray([row["field"] for row in valid_left], dtype=float)
        b = np.asarray([row["field"] for row in valid_right], dtype=float)
        delta = b-a
        metrics = {"field_components": {}, "field_vector": {
            "rms_difference_V_per_m": float(np.sqrt(np.mean(np.sum(delta**2, axis=1)))),
            "maximum_difference_V_per_m": float(np.max(np.linalg.norm(delta, axis=1)))}}
        for index, name in enumerate(("Ex", "Ey", "Ez")):
            normalized = normalized_rms_difference_pct(a[:, index], b[:, index])
            if (max(normalized["reference_rms_V_per_m"], normalized["values_rms_V_per_m"])
                    <= normalized["numerical_zero_floor_V_per_m"]
                    and normalized["difference_rms_V_per_m"] != 0.0):
                normalized["symmetric_scale_pct"] = None
            metrics["field_components"][name] = {**normalized,
                "maximum_absolute_difference_V_per_m": float(np.max(np.abs(delta[:, index])))}
        if "potential_V" in reference.columns:
            pa = np.asarray([row["potential_V"] for row in valid_left]); pb = np.asarray([row["potential_V"] for row in valid_right])
            difference = pb-pa; ref_rms = float(np.sqrt(np.mean(pa**2)))
            floor = np.finfo(float).eps * max(ref_rms, float(np.sqrt(np.mean(pb**2))), 1.0)
            metrics["potential"] = {"rms_difference_V": float(np.sqrt(np.mean(difference**2))),
                "maximum_absolute_difference_V": float(np.max(np.abs(difference))),
                "relative_to_reference_rms_pct": float(100*np.sqrt(np.mean(difference**2))/ref_rms) if ref_rms > floor else None}
    return {"role": "static_field_sample_comparison", "status": "DESCRIPTIVE_ONLY",
            "common_frame_id": reference_transform.to_frame_id,
            "reference_source": copy.deepcopy(reference_metadata["source"]), "candidate_source": copy.deepcopy(candidate_metadata["source"]),
            "bvp": copy.deepcopy(reference_metadata["bvp"]), "potential_reference": copy.deepcopy(reference_metadata["potential_reference"]),
            "coverage": coverage, "coverage_counts": {"total_union": len(coverage),
                "reference": {status: sum(row["reference"] == status for row in coverage) for status in sorted(states | {"missing"})},
                "candidate": {status: sum(row["candidate"] == status for row in coverage) for status in sorted(states | {"missing"})}},
            "paired_valid_count": len(valid_left), "metrics": metrics}


def validate_static_comparison_authority(authority: dict[str, Any]) -> None:
    """Validate one versioned persisted static-comparison authority envelope."""
    expected = {"schema_version", "role", "coordinate_tolerance_mm", "reference", "candidate"}
    if not isinstance(authority, dict) or set(authority) != expected:
        raise ValueError("static comparison authority fields differ")
    if (type(authority["schema_version"]) is not int or authority["schema_version"] != 1
            or authority["role"] != "static_field_comparison_authority"):
        raise ValueError("static comparison authority version or role differs")
    for name in ("reference", "candidate"):
        side = authority[name]
        if not isinstance(side, dict) or set(side) != {"metadata", "transform", "status_by_point_id"}:
            raise ValueError(f"{name} authority fields differ")
        metadata = side["metadata"]
        if not isinstance(metadata, dict) or set(metadata) != {"source", "bvp", "frame_id", "units", "potential_reference"}:
            raise ValueError(f"{name} metadata fields differ")
        if not isinstance(side["status_by_point_id"], dict):
            raise ValueError(f"{name} point status map is required")
        RigidTransform.from_contract(side["transform"])
