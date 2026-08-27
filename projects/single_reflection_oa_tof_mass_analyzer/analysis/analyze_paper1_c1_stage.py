"""Close Paper 1 C1 only from two frozen detector-blind source assessments."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("C1 source assessment must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _summarize(path: Path) -> dict[str, Any]:
    assessment = _load(path)
    if assessment.get("role") != "oatof_paper1_c1_source_assessment":
        raise ValueError("C1 source assessment role differs")
    if assessment.get("qualification") != "DETECTOR_BLIND_SOURCE_ONLY":
        raise ValueError("C1 source assessment is not detector blind")
    evidence_tier = assessment.get("evidence_tier")
    if evidence_tier not in {"DEVELOPMENT_ONLY", "PROSPECTIVE"}:
        raise ValueError("C1 source assessment evidence tier differs")
    cohort = assessment.get("cohort", {})
    counts = cohort.get("counts", {})
    if (
        cohort.get("model_selection_roles") != ["development", "validation"]
        or cohort.get("prohibited_from_model_selection") != ["optimization", "locked_test"]
        or set(counts) != {"development", "validation", "optimization", "locked_test"}
        or min(counts.values(), default=0) < 1
    ):
        raise ValueError("C1 cohort governance differs")
    mother = assessment.get("mother_cohort", {})
    modes = assessment.get("residual_modes", {})
    alignment = modes.get("bootstrap_alignment_lower_95", [])
    if (
        not isinstance(mother.get("count"), int)
        or mother["count"] < 1000
        or not isinstance(mother.get("observed_pre_pulse_count"), int)
        or mother["observed_pre_pulse_count"] < 1
        or not alignment
        or min(alignment) <= 0.0
    ):
        raise ValueError("C1 source stability evidence is insufficient")
    selected = assessment.get("selected_model", {})
    return {
        "assessment": {"path": str(path.resolve()), "sha256": _sha256(path)},
        "source_id": assessment.get("source_id"),
        "evidence_tier": evidence_tier,
        "anchor": assessment.get("anchor"),
        "mother_cohort": mother,
        "cohort": {"salt": cohort.get("salt"), "counts": counts},
        "selected_model": selected,
        "covariance_bins": assessment.get("covariance_bins", []),
        "residual_modes": modes,
    }


def assess_c1_stage(*, first_path: Path, second_path: Path) -> dict[str, Any]:
    """Verify that two independently frozen source conditions clear C1 input gates."""

    sources = [_summarize(first_path), _summarize(second_path)]
    identifiers = [source["source_id"] for source in sources]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise ValueError("C1 source identifier differs")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("C1 source identifiers must be distinct")
    prospective = all(source["evidence_tier"] == "PROSPECTIVE" for source in sources)
    return {
        "stage_id": "C1",
        "conclusion": "PASS_CONTINUE" if prospective else "INCONCLUSIVE_REVISE",
        "claim_limit": (
            "C1 source identifiability only; does not predict focusability, "
            "optimize controls, or make detector or resolution claims."
        ),
        "inputs": {
            "source_assessments": [source["assessment"] for source in sources],
            "source_ids": identifiers,
        },
        "metrics": {"sources": sources},
        "claims_supported": ([
            "Two distinct frozen RF-source conditions provide detector-blind OA pre-pulse states with preserved mother-cohort denominators.",
            "Each source has deterministic development/validation/optimization/locked-test cohorts and a stable source-specific conditional residual model.",
        ] if prospective else [
            "Development-only source assessments remain detector-blind diagnostics and cannot become a prospective C1 gate."
        ]),
        "claims_prohibited": [
            "Cross-source equality of conditional models or residual modes.",
            "Source-distribution-weighted focus prediction, additional-control-direction value, control optimization, detector performance, resolution, transmission, or Formal claims.",
            "A development-only source assessment is promoted to prospective or locked evidence.",
        ],
        "failures": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = assess_c1_stage(first_path=args.first, second_path=args.second)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
