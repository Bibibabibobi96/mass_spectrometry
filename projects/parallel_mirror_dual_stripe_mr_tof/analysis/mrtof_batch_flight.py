"""Materialize contiguous MR-TOF Fly2 slices and merge global-ID event logs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval as _resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    FLY_COMPLETED,
    parse_events,
)

_ION_FIELD = re.compile(r"(?<![A-Za-z_])(ion=)(\d+)(?=\s|$)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_bunch_source_interval(
    *, receipt_path: Path, particle_id_min: int, particle_id_max: int,
) -> dict[str, Any]:
    """Compatibility entrypoint for the shared immutable interval resolver."""
    return _resolve_bunch_source_interval(
        receipt_path=receipt_path,
        particle_id_min=particle_id_min,
        particle_id_max=particle_id_max,
    )


def materialize_batch_fly2(
    *, receipt_path: Path, particle_id_min: int, particle_id_max: int,
    output_path: Path,
) -> dict[str, Any]:
    selection = resolve_bunch_source_interval(
        receipt_path=receipt_path, particle_id_min=particle_id_min,
        particle_id_max=particle_id_max,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(selection["fly2"], encoding="utf-8", newline="\n")
    return {
        "particle_id_min": particle_id_min,
        "particle_id_max": particle_id_max,
        "count": len(selection["states"]),
        "simion_particle_id_offset": particle_id_min - 1,
        "fly2_sha256": _sha256(output_path),
    }


def merge_rebased_event_logs(
    *, batches: list[tuple[Path, int, int]], particle_count: int,
    output_path: Path, receipt_path: Path, particle_id_min: int = 1,
) -> dict[str, Any]:
    if not batches:
        raise ValueError("at least one batch log is required")
    covered: list[int] = []
    merged_lines: list[str] = []
    records = []
    total_splats = 0
    for path, offset, count in batches:
        if offset < 0 or count < 1:
            raise ValueError("batch offset/count is invalid")
        text = path.read_text(encoding="utf-8-sig")
        completions = list(FLY_COMPLETED.finditer(text))
        if len(completions) != 1 or int(completions[0].group("splats")) != count:
            raise ValueError(f"batch completion differs from its plan: {path}")
        for event in parse_events(text):
            local_id = int(event["ion"])
            if not 1 <= local_id <= count:
                raise ValueError(f"batch event particle ID is outside its local interval: {path}")
        for line in text.splitlines():
            if FLY_COMPLETED.match(line):
                continue
            merged_lines.append(_ION_FIELD.sub(
                lambda match: f"{match.group(1)}{int(match.group(2)) + offset}", line,
            ))
        covered.extend(range(offset + 1, offset + count + 1))
        total_splats += count
        records.append({
            "path": str(path.resolve()), "sha256": _sha256(path),
            "offset": offset, "count": count,
        })
    expected_ids = list(range(particle_id_min, particle_id_min + particle_count))
    if covered != expected_ids or total_splats != particle_count:
        raise ValueError("batch logs do not cover the frozen cohort exactly once")
    merged_lines.append(f"status,Fly completed. {particle_count} splats")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(merged_lines) + "\n", encoding="utf-8", newline="\n")
    receipt = {
        "schema_version": 1,
        "role": "mrtof_rebased_batch_log_merge",
        "status": "success",
        "particle_count": particle_count,
        "global_particle_ids": [expected_ids[0], expected_ids[-1]],
        "all_batch_losses_retained": True,
        "batches": records,
        "merged_log": {"path": str(output_path.resolve()), "sha256": _sha256(output_path)},
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def merge_measured_event_logs(*, batches: list[tuple[Path, Path]], preparation_path: Path,
                              output_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Stream original-ID events/trajectory samples; never ordinal-rebase measured IDs."""
    preparation = json.loads(preparation_path.read_text(encoding="utf-8-sig"))
    expected = preparation["expected_particle_ids"]
    covered: list[int] = []
    records = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for path, batch_receipt_path in batches:
            batch = json.loads(batch_receipt_path.read_text(encoding="utf-8-sig"))
            ids = batch["original_particle_ids"]
            count = batch["count"]
            if (batch.get("schema_version") != 1 or batch.get("role") != "mrtof_measured_source_batch"
                    or count < 1 or len(ids) != count or len(set(ids)) != count):
                raise ValueError("Measured batch IDs do not close")
            if batch["solver_epoch_instrument_time_us"] != preparation["solver_epoch_instrument_time_us"]:
                raise ValueError("Measured batch epoch differs from full source")
            # The runtime launches this copy, not the source materializer's path.
            # Recovery may retain the copy after the original path is retired.
            fly_path = batch_receipt_path.parent / "joint.fly2"
            verify_record("actual launched batch FLY2", dict(batch["outputs"]["source"], path=str(fly_path.resolve())),
                          base_dir=batch_receipt_path.parent)
            completions, terminal_ids = 0, set()
            with path.open(encoding="utf-8-sig") as source:
                for line in source:
                    completion = FLY_COMPLETED.match(line)
                    if completion:
                        completions += 1
                        if int(completion.group("splats")) != count:
                            raise ValueError("Measured batch completion differs from its plan")
                        continue
                    if line.startswith(("MRTOF_EVENT ", "MRTOF_TRAJECTORY ")):
                        match = _ION_FIELD.search(line)
                        if match is None or int(match[2]) not in ids:
                            raise ValueError("Measured event ID is outside its original-ID batch")
                        if line.startswith("MRTOF_EVENT terminal "):
                            if int(match[2]) in terminal_ids:
                                raise ValueError("Duplicate measured terminal event")
                            terminal_ids.add(int(match[2]))
                    output.write(line)
            if completions != 1 or terminal_ids != set(ids):
                raise ValueError("Measured batch lacks exact terminal coverage")
            covered.extend(ids)
            records.append(dict(log=file_record(path), batch_receipt=file_record(batch_receipt_path),
                                fly2=file_record(fly_path)))
        if covered != expected or len(set(covered)) != len(expected):
            raise ValueError("Measured batches do not cover the transferred cohort exactly once")
        output.write(f"status,Fly completed. {len(expected)} splats\n")
    result = dict(schema_version=1, role="mrtof_measured_batch_log_merge", status="success",
                  preparation=file_record(preparation_path),
                  particle_count=len(expected), mother_particle_count=preparation["mother_particle_count"],
                  original_particle_ids=expected, all_batch_losses_retained=True,
                  solver_epoch_instrument_time_us=preparation["solver_epoch_instrument_time_us"],
                  id_rebasing_applied=False, batches=records, merged_log=file_record(output_path))
    receipt_path.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--receipt", required=True, type=Path)
    materialize.add_argument("--particle-id-min", required=True, type=int)
    materialize.add_argument("--particle-id-max", required=True, type=int)
    materialize.add_argument("--output", required=True, type=Path)
    merge = sub.add_parser("merge")
    merge.add_argument("--particle-count", required=True, type=int)
    merge.add_argument("--particle-id-min", type=int, default=1)
    merge.add_argument("--batch-log", action="append", nargs=3, required=True)
    merge.add_argument("--output", required=True, type=Path)
    merge.add_argument("--receipt", required=True, type=Path)
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
    analyze_joint = sub.add_parser("analyze-joint")
    analyze_joint.add_argument("--preparation", required=True, type=Path)
    analyze_joint.add_argument("--log", required=True, type=Path)
    analyze_joint.add_argument("--output", required=True, type=Path)
    compare_joint = sub.add_parser("compare-joint")
    compare_joint.add_argument("--preparation", required=True, type=Path)
    compare_joint.add_argument("--log", required=True, type=Path)
    compare_joint.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare-joint":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import prepare_trial
        prepare_trial(args.prepared_run, args.contract, args.run_directory, args.equivalence_reference_run)
        print("PREPARED_JOINT_TRIAL=PASS")
    elif args.command == "materialize-joint":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import materialize_batch
        materialize_batch(args.preparation, args.particle_id_min, args.particle_id_max, args.output)
        print("PREPARED_JOINT_BATCH=PASS")
    elif args.command == "merge-joint":
        merge_measured_event_logs(batches=[(Path(log), Path(receipt)) for log, receipt in args.batch_log],
                                  preparation_path=args.preparation, output_path=args.output,
                                  receipt_path=args.receipt)
        print("PREPARED_JOINT_MERGE=PASS")
    elif args.command == "analyze-joint":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_diagnostics import analyze_prepared_joint_flight
        analyze_prepared_joint_flight(args.preparation, args.log, args.output,
                                     merge_receipt=args.preparation.parent / "batch_log_merge_receipt.json")
        print("PREPARED_JOINT_DIAGNOSTICS=PASS")
    elif args.command == "compare-joint":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import compare_trajectory_representation
        compare_trajectory_representation(args.preparation, args.log, args.output)
        print("PREPARED_JOINT_TRAJECTORY_EQUIVALENCE=PASS")
    elif args.command == "materialize":
        result = materialize_batch_fly2(
            receipt_path=args.receipt, particle_id_min=args.particle_id_min,
            particle_id_max=args.particle_id_max, output_path=args.output,
        )
        print(json.dumps(result, separators=(",", ":")))
    else:
        merge_rebased_event_logs(
            batches=[(Path(path), int(offset), int(count)) for path, offset, count in args.batch_log],
            particle_count=args.particle_count, output_path=args.output,
            receipt_path=args.receipt, particle_id_min=args.particle_id_min,
        )
        print("MRTOF_BATCH_LOG_MERGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
