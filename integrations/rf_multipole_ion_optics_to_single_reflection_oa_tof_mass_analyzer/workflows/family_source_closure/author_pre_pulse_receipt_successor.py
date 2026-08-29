"""Author a fresh pre-pulse campaign to materialize current screening receipts.

The source campaign remains immutable.  This narrowly scoped author changes
only the campaign identity and run-id timestamp, so a completed legacy screen
is never overwritten while the same frozen physical arms can be replayed with
the current receipt-producing runtime.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import ContractError


RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}(?P<suffix>__.+)$")
STAMP_PATTERN = re.compile(r"^\d{8}_\d{6}$")


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("source pre-pulse campaign is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("source pre-pulse campaign must be an object")
    return value


def author_successor(
    *, source_path: Path, output_path: Path, campaign_id: str, run_stamp: str
) -> dict[str, Any]:
    """Create an independent, receipt-producing replay of every source arm."""

    if not campaign_id:
        raise ContractError("successor campaign_id is required")
    if not STAMP_PATTERN.fullmatch(run_stamp):
        raise ContractError("successor run stamp must use YYYYMMDD_HHMMSS")
    output = output_path.resolve()
    if output.exists():
        raise ContractError("successor campaign output already exists")
    source = _load_object(source_path)
    screening = source.get("pre_pulse_time_series_screening")
    experiments = source.get("experiments")
    if (
        source.get("role") != "rf_multipole_oatof_experiment_campaign"
        or not isinstance(screening, dict)
        or screening.get("mode") != "real_pa_rf_pre_pulse_time_series"
        or not isinstance(experiments, dict)
        or not isinstance(experiments.get("rows"), list)
    ):
        raise ContractError("source campaign is not a real pre-pulse campaign")

    successor = copy.deepcopy(source)
    successor["campaign_id"] = campaign_id
    successor["claim_limit"] = (
        "DETECTOR_BLIND_SOURCE_ONLY. Receipt-materialization successor: each "
        "arm replays the unchanged frozen physical configuration and complete "
        "mother cohort solely to publish the current manifest-bound pre-pulse "
        "screening receipt. Resolution and detector claims remain prohibited."
    )
    shared = successor["experiments"].get("shared")
    if not isinstance(shared, dict):
        raise ContractError("source campaign shared experiment settings are incomplete")
    # A receipt successor changes no field-affecting input.  It must therefore
    # consume the already verified PA generations rather than authorizing a
    # new boundary transfer or Refine under the guise of a particle replay.
    shared["single_flight_pa_cache_policy"] = "require_existing"
    seen_run_ids: set[str] = set()
    first_stamp = datetime.strptime(run_stamp, "%Y%m%d_%H%M%S")
    for index, row in enumerate(successor["experiments"]["rows"]):
        if not isinstance(row, dict) or not isinstance(row.get("run_id"), str):
            raise ContractError("source campaign row run_id is incomplete")
        match = RUN_ID_PATTERN.fullmatch(row["run_id"])
        if match is None:
            raise ContractError("source campaign row run_id has an invalid identity")
        # The governed child SIMION identity is derived from the first
        # fifteen characters of the parent run ID.  A shared parent stamp
        # would therefore collide across aperture arms.  Allocate adjacent
        # second-level stamps here: this changes only run identity while
        # preserving every frozen physical input and lets a successor run all
        # arms without serial manual campaign authoring.
        row_stamp = (first_stamp + timedelta(seconds=index)).strftime("%Y%m%d_%H%M%S")
        new_run_id = row_stamp + match.group("suffix")
        if new_run_id in seen_run_ids:
            raise ContractError("successor campaign would duplicate a run_id")
        seen_run_ids.add(new_run_id)
        row["run_id"] = new_run_id
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(successor, indent=2) + "\n", encoding="utf-8")
    return successor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--run-stamp", required=True)
    args = parser.parse_args()
    author_successor(
        source_path=args.source,
        output_path=args.output,
        campaign_id=args.campaign_id,
        run_stamp=args.run_stamp,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
