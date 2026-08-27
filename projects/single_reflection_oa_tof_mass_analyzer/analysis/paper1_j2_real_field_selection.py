"""Freeze detector-blind J2 selections from real-PA local sensitivity receipts.

This module intentionally does not launch SIMION or inspect any detector
observable.  A separate real-field calculation supplies one six-dimensional
arrival-time gradient for every member of an already frozen candidate pool.
The C1 source covariance then defines the source-whitened score
``g Sigma g^T``; the unweighted comparator uses the same state scales and
candidate list.  The two choices can subsequently be audited on locked runs.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


STATE_NAMES = (
    "x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s",
)


def _load(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _finite_vector(value: object, *, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (len(STATE_NAMES),) or not np.isfinite(result).all():
        raise ValueError(f"{label} must contain six finite values in canonical state order")
    return result


def _source_covariance(c1: Mapping[str, Any], *, source_id: str) -> np.ndarray:
    if c1.get("stage_id") != "C1" or c1.get("conclusion") != "PASS_CONTINUE":
        raise ValueError("J2 real-field selection requires a C1 PASS_CONTINUE report")
    metrics = c1.get("metrics")
    rows = metrics.get("sources") if isinstance(metrics, Mapping) else None
    source = next((item for item in rows or () if isinstance(item, Mapping) and item.get("source_id") == source_id), None)
    if source is None:
        raise ValueError("C1 report does not contain the requested source")
    bins = source.get("covariance_bins")
    if not isinstance(bins, list) or not bins:
        raise ValueError("C1 source covariance bins are missing")
    covariance = np.zeros((len(STATE_NAMES), len(STATE_NAMES)), dtype=float)
    total = 0
    for index, item in enumerate(bins):
        if not isinstance(item, Mapping):
            raise ValueError("C1 covariance bin is invalid")
        sample_count = int(item.get("sample_count", 0))
        matrix = np.asarray(item.get("covariance"), dtype=float)
        if sample_count < 1 or matrix.shape != covariance.shape or not np.isfinite(matrix).all():
            raise ValueError(f"C1 covariance bin {index} is invalid")
        covariance += sample_count * matrix
        total += sample_count
    covariance /= total
    if not np.allclose(covariance, covariance.T, rtol=0.0, atol=1e-10):
        raise ValueError("C1 pooled covariance is not symmetric")
    eigenvalues = np.linalg.eigvalsh(covariance)
    if float(eigenvalues.min()) < -1e-8 * max(1.0, float(np.max(np.abs(eigenvalues)))):
        raise ValueError("C1 pooled covariance is not positive semidefinite")
    return covariance


def select_j2_real_field_candidates(
    *, c1_stage_report: Path, request_path: Path, sensitivity_receipt: Path,
) -> dict[str, Any]:
    """Select one unweighted and one source-whitened candidate without detector data.

    ``request`` binds source, candidate-pool identity and canonical state scales.
    ``sensitivity_receipt`` is a solver-side local derivative receipt; it may
    contain no arrival-time samples, FWHM, transmission, or detector fields.
    """

    c1 = _load(c1_stage_report, label="C1 stage report")
    receipt = _load(sensitivity_receipt, label="real-field sensitivity receipt")
    request = _load(request_path, label="J2 fair-selection request")
    expected_request = {
        "role", "source_id", "candidate_pool_sha256", "candidate_ids", "state_names",
        "state_scale", "sensitivity_receipt_sha256",
    }
    if set(request) != expected_request or request.get("role") != "oatof_paper1_j2_fair_selection_request":
        raise ValueError("J2 fair-selection request fields differ from the contract")
    source_id = request.get("source_id")
    pool_sha = request.get("candidate_pool_sha256")
    if not isinstance(source_id, str) or not isinstance(pool_sha, str) or len(pool_sha) != 64:
        raise ValueError("J2 fair-selection request source or pool identity is invalid")
    declared_candidate_ids = request.get("candidate_ids")
    if (
        not isinstance(declared_candidate_ids, list)
        or len(declared_candidate_ids) < 2
        or any(not isinstance(item, str) or not item for item in declared_candidate_ids)
        or len(set(declared_candidate_ids)) != len(declared_candidate_ids)
    ):
        raise ValueError("J2 fair-selection request candidate IDs are invalid")
    declared_receipt_sha = request.get("sensitivity_receipt_sha256")
    if not isinstance(declared_receipt_sha, str) or declared_receipt_sha != _sha256(sensitivity_receipt):
        raise ValueError("J2 fair-selection request sensitivity receipt hash differs")
    if tuple(request.get("state_names", ())) != STATE_NAMES:
        raise ValueError("J2 fair-selection request state order differs from the canonical order")
    scale = _finite_vector(request.get("state_scale"), label="J2 state_scale")
    if np.any(scale <= 0.0):
        raise ValueError("J2 state_scale must be positive")
    if receipt.get("role") != "oatof_paper1_real_field_sensitivity_receipt":
        raise ValueError("real-field sensitivity receipt role differs")
    if receipt.get("source_id") != source_id or receipt.get("candidate_pool_sha256") != pool_sha:
        raise ValueError("real-field sensitivity receipt is not bound to this J2 request")
    if tuple(receipt.get("state_names", ())) != STATE_NAMES:
        raise ValueError("real-field sensitivity receipt state order differs")
    candidates = receipt.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("real-field sensitivity receipt requires at least two candidates")
    covariance = _source_covariance(c1, source_id=source_id)
    scores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping) or set(item) != {"candidate_id", "time_gradient_us_per_state"}:
            raise ValueError("real-field sensitivity candidate fields differ from the contract")
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in seen:
            raise ValueError("real-field sensitivity candidate identifiers must be unique")
        seen.add(candidate_id)
        gradient = _finite_vector(item.get("time_gradient_us_per_state"), label=f"gradient for {candidate_id}")
        scores.append({
            "candidate_id": candidate_id,
            "unweighted_score": float(np.dot(gradient * scale, gradient * scale)),
            "source_whitened_score": float(gradient @ covariance @ gradient),
        })
    if [item["candidate_id"] for item in scores] != declared_candidate_ids:
        raise ValueError("real-field sensitivity candidates differ from the frozen common pool")
    unweighted = min(scores, key=lambda item: (item["unweighted_score"], item["candidate_id"]))
    weighted = min(scores, key=lambda item: (item["source_whitened_score"], item["candidate_id"]))
    return {
        "stage_id": "J2_REAL_3D_PILOT_SELECTION",
        "claim_limit": "Detector-blind local selection only; no locked outcome, FWHM, transmission, or J2 success claim.",
        "source_id": source_id,
        "candidate_pool_sha256": pool_sha,
        "state_names": list(STATE_NAMES),
        "state_scale": scale.tolist(),
        "pooled_source_covariance": covariance.tolist(),
        "scores": scores,
        "unweighted_selection": unweighted,
        "source_whitened_selection": weighted,
        "claims_supported": ["Two pre-registered objectives selected candidates from one frozen pool without detector outcomes."],
        "claims_prohibited": ["J2 superiority, a physical variance lower bound, FWHM improvement, transmission improvement, or a locked-test conclusion."],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c1-stage-report", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--sensitivity-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = select_j2_real_field_candidates(
        c1_stage_report=args.c1_stage_report, request_path=args.request,
        sensitivity_receipt=args.sensitivity_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
