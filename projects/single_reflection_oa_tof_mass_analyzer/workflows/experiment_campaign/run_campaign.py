"""Inspect or run the project-authoritative oa-TOF experiment campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.experiment_campaign import (
    DEFAULT_CAMPAIGN,
    campaign_status,
    execute_campaign,
    read_campaign_receipt,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate import (
    execute_request,
    validate_candidate_runtime,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--receipt", metavar="CAMPAIGN_RUN_ID")
    action.add_argument("--experiment-id")
    action.add_argument("--all", action="store_true")
    parser.add_argument("--campaign-run-id")
    args = parser.parse_args()

    if args.status:
        if args.campaign_run_id:
            parser.error("--status is read-only and does not accept --campaign-run-id")
        print(json.dumps(campaign_status(args.campaign), ensure_ascii=False, indent=2))
        return
    if args.receipt:
        if args.campaign_run_id:
            parser.error("--receipt is read-only and does not accept --campaign-run-id")
        print(json.dumps(read_campaign_receipt(args.receipt), ensure_ascii=False, indent=2))
        return
    if not args.campaign_run_id:
        parser.error("execution requires --campaign-run-id")

    # Machine/runtime evidence is intentionally outside CI artifacts. Validate it
    # before execute_campaign is allowed to allocate campaign or child evidence.
    validate_candidate_runtime()
    run_root, summary = execute_campaign(
        args.campaign,
        args.campaign_run_id,
        experiment_id=args.experiment_id,
        run_all=args.all,
        candidate_executor=execute_request,
    )
    print(
        f"OATOF_CAMPAIGN={summary['status'].upper()} "
        f"RUN_ROOT={run_root} ROWS={len(summary['rows'])}"
    )
    if summary["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
