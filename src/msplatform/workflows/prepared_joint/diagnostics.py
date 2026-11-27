"""Temporary recorded diagnostic command; Store migration in progress."""
from pathlib import Path
from msplatform.workflows.historical_joint_analysis import analyze_prepared_joint_flight


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze-joint")
    analyze.add_argument("--preparation", required=True, type=Path)
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    analyze.add_argument("--analysis-contract", type=Path)
    args = parser.parse_args()
    analyze_prepared_joint_flight(args.preparation, args.log, args.output,
        merge_receipt=args.preparation.parent / "batch_log_merge_receipt.json", analysis_contract=args.analysis_contract)
    print("PREPARED_JOINT_DIAGNOSTICS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
