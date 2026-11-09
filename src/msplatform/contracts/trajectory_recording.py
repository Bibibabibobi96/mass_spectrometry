"""Validate explicitly requested solver callback observation and retention."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from typing import Any


def resolve_trajectory_recording(contract: dict[str, Any]) -> dict[str, Any] | None:
    """Validate callback observation without changing integration or event settings."""
    value = contract["simion"].get("trajectory_recording")
    if value is None:
        return None
    common = {"schema_version", "mode", "retention_class", "reason", "output_budget_bytes"}
    if not isinstance(value, dict) or value.get("mode") not in {"every_step", "fixed_interval"}:
        raise ValueError("trajectory_recording requires every_step or fixed_interval")
    expected = common | ({"interval_us"} if value["mode"] == "fixed_interval" else set())
    if set(value) != expected or value["schema_version"] != 1:
        raise ValueError("trajectory_recording fields differ from its schema 1 sampling mode")
    if value["retention_class"] != "solver_review" or not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("recorded trajectories require solver_review with a reason")
    if type(value["output_budget_bytes"]) is not int or value["output_budget_bytes"] < 1:
        raise ValueError("trajectory output_budget_bytes must be a positive integer")
    if value["mode"] == "fixed_interval":
        interval = value["interval_us"]
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("trajectory interval_us must be finite and positive")
    return dict(value)



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(resolve_trajectory_recording(json.loads(args.contract.read_text(encoding="utf-8-sig")))))


if __name__ == "__main__":
    main()
