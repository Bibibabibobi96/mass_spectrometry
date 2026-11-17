"""Public prepared-joint preparation, batch materialization and comparison CLI."""
from __future__ import annotations

import argparse
from pathlib import Path

from msplatform.backends.simion.mrtof_batch_flight import merge_measured_event_logs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    joint = sub.add_parser("prepare-joint")
    joint.add_argument("--prepared-run", required=True, type=Path)
    joint.add_argument("--contract", required=True, type=Path)
    joint.add_argument("--run-directory", required=True, type=Path)
    joint.add_argument("--equivalence-reference-run", type=Path)
    slice_joint = sub.add_parser("materialize-joint")
    slice_joint.add_argument("--preparation", required=True, type=Path)
    slice_joint.add_argument("--particle-id-min", required=True, type=int)
    slice_joint.add_argument("--particle-id-max", required=True, type=int)
    slice_joint.add_argument("--output", required=True, type=Path)
    merge_joint = sub.add_parser("merge-joint")
    merge_joint.add_argument("--preparation", required=True, type=Path)
    merge_joint.add_argument("--batch-log", action="append", nargs=2, required=True)
    merge_joint.add_argument("--output", required=True, type=Path)
    merge_joint.add_argument("--receipt", required=True, type=Path)
    compare_joint = sub.add_parser("compare-joint")
    compare_joint.add_argument("--preparation", required=True, type=Path)
    compare_joint.add_argument("--log", required=True, type=Path)
    compare_joint.add_argument("--output", required=True, type=Path)
    compare_joint.add_argument("--scientific-event-receipt", type=Path)
    args = parser.parse_args()
    if args.command == "prepare-joint":
        from msplatform.workflows.prepared_joint.trial import prepare_trial
        prepare_trial(args.prepared_run, args.contract, args.run_directory, args.equivalence_reference_run)
        print("PREPARED_JOINT_TRIAL=PASS")
    elif args.command == "materialize-joint":
        from msplatform.workflows.prepared_joint.trial import materialize_batch
        materialize_batch(args.preparation, args.particle_id_min, args.particle_id_max, args.output)
        print("PREPARED_JOINT_BATCH=PASS")
    elif args.command == "merge-joint":
        merge_measured_event_logs(batches=[(Path(log), Path(receipt)) for log, receipt in args.batch_log],
                                  preparation_path=args.preparation, output_path=args.output,
                                  receipt_path=args.receipt)
        print("PREPARED_JOINT_MERGE=PASS")
    elif args.command == "compare-joint":
        from msplatform.workflows.prepared_joint.trial import compare_trajectory_representation
        compare_trajectory_representation(args.preparation, args.log, args.output,
                                          scientific_event_receipt=args.scientific_event_receipt)
        print("PREPARED_JOINT_TRAJECTORY_EQUIVALENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
