"""Classify a complete Candidate bunch by its detector collection fraction."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def evaluate(cohort: dict[str, Any]) -> dict[str, Any]:
    """Return the fixed collection gate without discarding flight evidence."""
    if cohort.get("event_integrity_passed") is not True:
        return {
            "schema_version": 1,
            "role": "mrtof_bunch_collection_gate",
            "status": "invalid_event_receipt",
            "hard_stop": True,
            "continue_downstream": False,
            "reason": "complete cohort event integrity did not pass",
        }
    value = cohort.get("detection_rate")
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return {
            "schema_version": 1,
            "role": "mrtof_bunch_collection_gate",
            "status": "invalid_detection_rate",
            "hard_stop": True,
            "continue_downstream": False,
            "reason": "complete cohort has no finite detection rate",
        }
    rate = float(value)
    if not 0.0 <= rate <= 1.0:
        return {
            "schema_version": 1,
            "role": "mrtof_bunch_collection_gate",
            "status": "invalid_detection_rate",
            "hard_stop": True,
            "continue_downstream": False,
            "reason": "detection rate is outside [0, 1]",
        }
    if rate <= 0.40:
        status, warning, hard_stop = "below_hard_minimum", True, True
    elif rate < 0.80:
        status, warning, hard_stop = "warning_below_preferred", True, False
    else:
        status, warning, hard_stop = "accepted", False, False
    return {
        "schema_version": 1,
        "role": "mrtof_bunch_collection_gate",
        "status": status,
        "detection_rate": rate,
        "preferred_minimum": 0.80,
        "hard_minimum_exclusive": 0.40,
        "warning": warning,
        "hard_stop": hard_stop,
        "continue_downstream": not hard_stop,
        "reason": (
            "detector collection meets the preferred threshold"
            if not warning else
            "detector collection is above the hard minimum but below the preferred threshold"
            if not hard_stop else
            "detector collection is at or below the hard minimum"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observation = json.loads(args.observation.read_text(encoding="utf-8"))
    cohort = observation.get("cohort_analysis")
    if not isinstance(cohort, dict):
        cohort = {"event_integrity_passed": False}
    result = evaluate(cohort)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"MRTOF_BUNCH_COLLECTION_GATE={result['status']} "
        f"CONTINUE={result['continue_downstream']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
