"""Plan and rank bounded automatic recovery probes for a failed Candidate bunch."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


class RecoveryInputError(ValueError):
    """Raised when a recovery input cannot identify a physical candidate."""


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise RecoveryInputError(f"{label} must be a four-voltage vector")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise RecoveryInputError(f"{label} must be finite")
    return result


def _stripe_seed(theory: dict[str, Any]) -> list[float]:
    seed = theory.get("selected_seed")
    if not isinstance(seed, dict):
        raise RecoveryInputError("theory summary has no selected_seed")
    biases = seed.get("stripe_biases_v")
    if not isinstance(biases, list) or len(biases) != 2:
        raise RecoveryInputError("theory selected_seed has no two Stripe biases")
    result = [float(item) for item in biases]
    if not all(math.isfinite(item) for item in result):
        raise RecoveryInputError("theory Stripe biases must be finite")
    return result


def plan(workpoint: dict[str, Any], theory: dict[str, Any], *, stage: str = "theory") -> dict[str, Any]:
    """Return a bounded, deterministic S-only probe plan from recorded evidence.

    P1/P2 are intentionally held fixed: their constraints were already measured
    by the workpoint controller.  Candidate locations are derived only from the
    accepted physical point and the theory-owned Stripe seed; no operator voltage
    or current iteration number is accepted by this interface.
    """
    selected = workpoint.get("selected_workpoint")
    if not isinstance(selected, dict):
        raise RecoveryInputError("workpoint handoff has no selected_workpoint")
    anchor = _vector(selected.get("voltages_v"), "selected workpoint voltages")
    theory_s1, theory_s2 = _stripe_seed(theory)
    if stage == "theory":
        midpoint = [(anchor[0] + theory_s1) / 2.0, (anchor[1] + theory_s2) / 2.0]
        policy = "theory_seed_then_midpoint_s_only__bounded_two_probe"
        candidates = [
            ("theory_stripe_seed", [theory_s1, theory_s2, anchor[2], anchor[3]]),
            ("stripe_midpoint_to_theory", [midpoint[0], midpoint[1], anchor[2], anchor[3]]),
        ]
    elif stage == "reverse_axis":
        # A failed pair of same-direction theory trials says nothing about the
        # two independent Stripe responses.  Probe each axis in the opposite,
        # half-theory direction from the accepted anchor before combining them.
        half_s1 = (anchor[0] - theory_s1) / 2.0
        half_s2 = (anchor[1] - theory_s2) / 2.0
        policy = "failed_theory_direction_then_independent_reverse_half_theory_axes"
        candidates = [
            ("reverse_s1_half_theory", [anchor[0] + half_s1, anchor[1], anchor[2], anchor[3]]),
            ("reverse_s2_half_theory", [anchor[0], anchor[1] + half_s2, anchor[2], anchor[3]]),
        ]
    else:
        raise RecoveryInputError(f"unsupported recovery stage: {stage}")
    unique: list[dict[str, Any]] = []
    for purpose, voltages in candidates:
        if all(max(abs(left - right) for left, right in zip(voltages, known["voltages_v"])) > 1e-9 for known in unique):
            unique.append({
                "purpose": purpose,
                "voltages_v": voltages,
                "delta_from_accepted_v": [voltages[index] - anchor[index] for index in range(4)],
                "p_constraints_held": True,
            })
    if not unique:
        raise RecoveryInputError("theory Stripe seed duplicates the accepted workpoint")
    return {
        "schema_version": 1,
        "role": "mrtof_bunch_transport_recovery_plan",
        "status": "planned",
        "policy": policy,
        "stage": stage,
        "accepted_anchor_voltages_v": anchor,
        "theory_stripe_biases_v": [theory_s1, theory_s2],
        "probe_particle_count": 100,
        "candidates": unique,
        "selection_rule": "event integrity, then detector collection, then target-K fraction",
    }


def rank(plan_document: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Select only a physically valid improving candidate from completed probes."""
    candidates = {item["purpose"]: item for item in plan_document.get("candidates", [])}
    scored: list[dict[str, Any]] = []
    for observation in observations:
        purpose = observation.get("purpose")
        cohort = observation.get("cohort_analysis")
        if purpose not in candidates or not isinstance(cohort, dict):
            continue
        rate = cohort.get("detection_rate")
        target = cohort.get("target_k_fraction")
        if cohort.get("event_integrity_passed") is not True or not isinstance(rate, (int, float)) or not math.isfinite(float(rate)):
            continue
        target_value = float(target) if isinstance(target, (int, float)) and math.isfinite(float(target)) else -1.0
        scored.append({"purpose": purpose, "voltages_v": candidates[purpose]["voltages_v"], "detection_rate": float(rate), "target_k_fraction": target_value, "observation": observation})
    if not scored:
        return {"schema_version": 1, "role": "mrtof_bunch_transport_recovery_selection", "status": "unrecoverable", "reason": "no event-integrity-valid completed recovery probe"}
    scored.sort(key=lambda item: (item["detection_rate"], item["target_k_fraction"]), reverse=True)
    best = scored[0]
    return {
        "schema_version": 1,
        "role": "mrtof_bunch_transport_recovery_selection",
        "status": "selected" if best["detection_rate"] > 0.40 else "unrecoverable",
        "selected": best if best["detection_rate"] > 0.40 else None,
        "ranked_completed_probes": scored,
        "reason": "selected highest collection event-valid probe above hard minimum" if best["detection_rate"] > 0.40 else "all bounded recovery probes remain at or below the collection hard minimum",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--workpoint", type=Path, required=True)
    plan_parser.add_argument("--theory", type=Path, required=True)
    plan_parser.add_argument("--stage", choices=("theory", "reverse_axis"), default="theory")
    plan_parser.add_argument("--output", type=Path, required=True)
    rank_parser = subparsers.add_parser("rank")
    rank_parser.add_argument("--plan", type=Path, required=True)
    rank_parser.add_argument("--observation", type=Path, action="append", required=True)
    rank_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = plan(json.loads(args.workpoint.read_text(encoding="utf-8")), json.loads(args.theory.read_text(encoding="utf-8")), stage=args.stage)
    else:
        result = rank(json.loads(args.plan.read_text(encoding="utf-8")), [json.loads(path.read_text(encoding="utf-8")) for path in args.observation])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_BUNCH_TRANSPORT_RECOVERY={result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
