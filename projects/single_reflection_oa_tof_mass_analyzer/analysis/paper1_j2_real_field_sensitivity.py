"""Reduce controlled real-field central differences to a J2 sensitivity receipt.

This module is the narrow bridge between future paired SIMION local-response
runs and the detector-blind J2 selector.  It accepts only pre-registered
``+/-`` arrival-time observations for each canonical source-state coordinate;
it neither fits a source model nor reads FWHM, transmission, tails, modes, or
locked outcomes.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_j2_real_field_selection import STATE_NAMES


def _canonical_sha256(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def _finite_vector(value: object, *, label: str, positive: bool = False) -> list[float]:
    if not isinstance(value, list) or len(value) != len(STATE_NAMES):
        raise ValueError(f"{label} must contain six values in canonical state order")
    result: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool):
            raise ValueError(f"{label}[{index}] must be finite")
        number = float(item)
        if not math.isfinite(number) or (positive and number <= 0.0):
            raise ValueError(f"{label}[{index}] must be {'positive and ' if positive else ''}finite")
        result.append(number)
    return result


def build_j2_real_field_sensitivity_receipt(observations: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical six-state gradients from paired central differences."""

    required = {"role", "source_id", "candidate_pool_sha256", "state_names", "state_steps", "numeric_identity_sha256", "candidates"}
    if set(observations) != required or observations.get("role") != "oatof_paper1_real_field_central_difference_observations":
        raise ValueError("J2 finite-difference observation fields differ from the contract")
    source_id, pool_sha, numeric_sha = (observations.get(name) for name in ("source_id", "candidate_pool_sha256", "numeric_identity_sha256"))
    if not all(isinstance(value, str) and value for value in (source_id, pool_sha, numeric_sha)) or len(pool_sha) != 64 or len(numeric_sha) != 64:
        raise ValueError("J2 finite-difference identities are invalid")
    if tuple(observations.get("state_names", ())) != STATE_NAMES:
        raise ValueError("J2 finite-difference state order differs from the canonical order")
    steps = _finite_vector(observations.get("state_steps"), label="state_steps", positive=True)
    candidates = observations.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("J2 finite-difference observations require at least two candidates")
    reduced: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping) or set(item) != {"candidate_id", "plus_arrival_time_us", "minus_arrival_time_us"}:
            raise ValueError("J2 finite-difference candidate fields differ from the contract")
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in seen:
            raise ValueError("J2 finite-difference candidate IDs must be unique")
        seen.add(candidate_id)
        plus = _finite_vector(item.get("plus_arrival_time_us"), label=f"{candidate_id}.plus_arrival_time_us")
        minus = _finite_vector(item.get("minus_arrival_time_us"), label=f"{candidate_id}.minus_arrival_time_us")
        reduced.append({"candidate_id": candidate_id, "time_gradient_us_per_state": [(plus[index] - minus[index]) / (2.0 * steps[index]) for index in range(len(STATE_NAMES))]})
    observation_identity = _canonical_sha256(observations)
    return {
        "role": "oatof_paper1_real_field_sensitivity_receipt",
        "source_id": source_id,
        "candidate_pool_sha256": pool_sha,
        "state_names": list(STATE_NAMES),
        "candidates": reduced,
        "method": "paired_central_difference_real_field_v1",
        "state_steps": steps,
        "numeric_identity_sha256": numeric_sha,
        "finite_difference_observations_sha256": observation_identity,
        "claim_limit": "Local real-field derivative receipt only; no source fit, candidate ranking, FWHM, transmission, or locked-test conclusion.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    observations = json.loads(args.observations.read_text(encoding="utf-8-sig"))
    result = build_j2_real_field_sensitivity_receipt(observations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0
