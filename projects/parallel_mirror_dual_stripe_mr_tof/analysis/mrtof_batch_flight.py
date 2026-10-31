"""Materialize contiguous MR-TOF Fly2 slices and merge global-ID event logs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record
from common.simion.native_completion import parse_fly_completed_line
from common.simion.scientific_event_io import iter_csv_rows

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events, read_scientific_events

_ION_FIELD = re.compile(r"(?<![A-Za-z_])(ion=)(\d+)(?=\s|$)")


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
        "fly2_sha256": file_sha256(output_path).lower(),
    }


def merge_rebased_event_logs(
    *, batches: list[tuple[Path, int, int]], particle_count: int,
    output_path: Path, receipt_path: Path, particle_id_min: int = 1,
    scientific_event_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not batches:
        raise ValueError("at least one batch log is required")
    if scientific_event_outputs is not None:
        return _merge_structured_batches(batches=batches, declarations=scientific_event_outputs,
            particle_count=particle_count, particle_id_min=particle_id_min, output_path=output_path, receipt_path=receipt_path)
    # Explicit historical-log READ adapter. New materializers declare CSV and
    # take the structured branch above; never duplicate native scientific output.
    covered: list[int] = []
    records = []
    total_splats = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".legacy.partial")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as merged:
            for path, offset, count in batches:
                if offset < 0 or count < 1:
                    raise ValueError("batch offset/count is invalid")
                digest = hashlib.sha256()
                completions = []
                with path.open("rb") as source:
                    for number, raw in enumerate(source):
                        digest.update(raw)
                        line = raw.decode("utf-8-sig" if number == 0 else "utf-8")
                        completion = parse_fly_completed_line(line)
                        if completion is not None:
                            completions.append(completion)
                            continue
                        for event in parse_events(line):
                            local_id = int(event["ion"])
                            if not 1 <= local_id <= count:
                                raise ValueError(f"batch event particle ID is outside its local interval: {path}")
                        merged.write(_ION_FIELD.sub(
                            lambda match: f"{match.group(1)}{int(match.group(2)) + offset}",
                            line.rstrip("\r\n")) + "\n")
                if len(completions) != 1 or completions[0].splats != count:
                    raise ValueError(f"batch completion differs from its plan: {path}")
                covered.extend(range(offset + 1, offset + count + 1))
                total_splats += count
                records.append({"path": str(path.resolve()), "sha256": digest.hexdigest(),
                                "offset": offset, "count": count})
            expected_ids = list(range(particle_id_min, particle_id_min + particle_count))
            if covered != expected_ids or total_splats != particle_count:
                raise ValueError("batch logs do not cover the frozen cohort exactly once")
            merged.write(f"status,Fly completed. {particle_count} splats\n")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {
        "schema_version": 1,
        "role": "mrtof_rebased_batch_log_merge",
        "status": "success",
        "particle_count": particle_count,
        "global_particle_ids": [expected_ids[0], expected_ids[-1]],
        "all_batch_losses_retained": True,
        "batches": records,
        "merged_log": {"path": str(output_path.resolve()), "sha256": file_sha256(output_path).lower()},
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def _merge_structured_batches(*, batches, declarations, particle_count, particle_id_min, output_path, receipt_path, batch_original_ids=None):
    if len(batches) != len(declarations):
        raise ValueError("every batch must declare its scientific event output")
    records, events, covered = [], [], []
    trajectory_path=receipt_path.with_name(receipt_path.stem+".trajectory.csv")
    trajectory_columns=("ion","phase","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us")
    trajectory_created=False
    for batch_number, ((log, offset, count), declaration) in enumerate(zip(batches, declarations, strict=True)):
        actual_ids = batch_original_ids[batch_number] if batch_original_ids is not None else list(range(1,count+1))
        rows, completions, log_identity = read_scientific_events(log, scientific_event_output=declaration)
        if len(completions) != 1 or completions[0].splats != count:
            raise ValueError("structured batch lacks exact native completion")
        terminal = []
        for row in rows:
            local = int(row["ion"])
            if local not in actual_ids:
                raise ValueError("structured batch ID is outside its frozen interval")
            row = dict(row, ion=local if batch_original_ids is not None else local+offset)
            if row["kind"] == "terminal": terminal.append(local)
            events.append(row)
        if sorted(terminal) != sorted(actual_ids):
            raise ValueError("structured batch lacks exact terminal coverage")
        if declaration.get("trajectory_path") is not None:
            trajectory_path.parent.mkdir(parents=True,exist_ok=True)
            with trajectory_path.open("a" if trajectory_created else "w",encoding="utf-8",newline="") as stream:
                trajectory_writer=csv.DictWriter(stream,fieldnames=trajectory_columns,lineterminator="\n")
                if not trajectory_created: trajectory_writer.writeheader()
                for sample in iter_csv_rows(Path(declaration["trajectory_path"]),trajectory_columns,exact_header=trajectory_columns, expected_record=declaration.get("trajectory_record")):
                    local=int(sample["ion"])
                    if local not in actual_ids: raise ValueError("trajectory ID is outside frozen batch")
                    trajectory_writer.writerow(dict(sample,ion=local if batch_original_ids is not None else local+offset))
            trajectory_created=True
        covered.extend(actual_ids if batch_original_ids is not None else range(offset+1,offset+count+1))
        records.append(dict(path=str(log.resolve()),sha256=log_identity,scientific_event_output=declaration,offset=offset,count=count))
    expected=[particle for group in batch_original_ids for particle in group] if batch_original_ids is not None else list(range(particle_id_min,particle_id_min+particle_count))
    if covered != expected:
        raise ValueError("structured batches do not cover frozen cohort exactly once")
    output_path.parent.mkdir(parents=True,exist_ok=True)
    event_path=receipt_path.with_name(receipt_path.stem+".events.csv")
    columns=["kind","ion"]+sorted(set().union(*(row.keys() for row in events)) - {"kind","ion"})
    with event_path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,lineterminator="\n")
        writer.writeheader();writer.writerows(events)
    output_path.write_text(f"status,Fly completed. {particle_count} splats\n",encoding="utf-8")
    event_record=file_record(event_path)
    result=dict(schema_version=1,role="mrtof_rebased_batch_log_merge",status="success",particle_count=particle_count,
        global_particle_ids=[expected[0],expected[-1]],all_batch_losses_retained=True,batches=records,
        merged_log=file_record(output_path),scientific_event_output=dict(events_path=str(event_path.resolve()),events_record=event_record),
        scientific_event_records=dict(events=event_record))
    if trajectory_created:
        result["scientific_event_output"]["trajectory_path"]=str(trajectory_path.resolve())
        trajectory_record=file_record(trajectory_path)
        result["scientific_event_output"]["trajectory_record"]=trajectory_record
        result["scientific_event_records"]["trajectory"]=trajectory_record
    receipt_path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def _validate_measured_batch_source(*, batch_receipt_path, preparation):
    batch = json.loads(batch_receipt_path.read_text(encoding="utf-8-sig"))
    ids = batch["original_particle_ids"]
    count = batch["count"]
    if (batch.get("schema_version") != 1 or batch.get("role") != "mrtof_measured_source_batch"
            or count < 1 or len(ids) != count or len(set(ids)) != count):
        raise ValueError("Measured batch IDs do not close")
    if batch["solver_epoch_instrument_time_us"] != preparation["solver_epoch_instrument_time_us"]:
        raise ValueError("Measured batch epoch differs from full source")
    fly_path = batch_receipt_path.parent / "joint.fly2"
    verify_record("actual launched batch FLY2", dict(batch["outputs"]["source"], path=str(fly_path.resolve())),
                  base_dir=batch_receipt_path.parent)
    return ids, batch, fly_path


def validate_measured_batch_terminal(*, log_path: Path, batch_receipt_path: Path,
                                    preparation: dict[str, Any], scientific_event_output=None) -> tuple[list[int], dict[str, Any], Path]:
    """Validate one complete measured-source batch without materializing its log."""
    ids, batch, fly_path = _validate_measured_batch_source(batch_receipt_path=batch_receipt_path, preparation=preparation)
    count = len(ids)
    if scientific_event_output is not None:
        batch = dict(batch, scientific_event_output=scientific_event_output)
    completions, terminal_ids = 0, set()
    if "scientific_event_output" in batch:
        events, finished, _ = read_scientific_events(log_path,scientific_event_output=batch["scientific_event_output"])
        if len(finished)!=1 or finished[0].splats!=count:
            raise ValueError("Measured native completion differs from plan")
        completions=len(finished)
        for event in events:
            particle=int(event["ion"])
            if particle not in ids: raise ValueError("Measured event ID is outside original batch")
            if event["kind"]=="terminal":
                if particle in terminal_ids: raise ValueError("Duplicate measured terminal event")
                terminal_ids.add(particle)
    else:
        with log_path.open(encoding="utf-8-sig") as source:
            for line in source:
                completion = parse_fly_completed_line(line)
                if completion:
                    completions += 1
                    if completion.splats != count:
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
    if completions != 1 or terminal_ids != set(ids):
        raise ValueError("Measured batch lacks exact terminal coverage")
    return ids, batch, fly_path


def merge_measured_event_logs(*, batches: list[tuple[Path, Path]], preparation_path: Path,
                              output_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Stream original-ID events/trajectory samples; never ordinal-rebase measured IDs."""
    preparation = json.loads(preparation_path.read_text(encoding="utf-8-sig"))
    expected = preparation["expected_particle_ids"]
    batch_receipts=[json.loads(receipt.read_text(encoding="utf-8-sig")) for _,receipt in batches]
    if any("scientific_event_output" in receipt for receipt in batch_receipts):
        if not all("scientific_event_output" in receipt for receipt in batch_receipts):
            raise ValueError("mixed scientific event representations need explicit historical conversion")
        validated=[_validate_measured_batch_source(batch_receipt_path=receipt,preparation=preparation) for _,receipt in batches]
        all_ids=[particle for ids,_,_ in validated for particle in ids]
        if all_ids!=expected: raise ValueError("Measured batches differ from frozen original-ID order")
        result=_merge_structured_batches(batches=[(log,0,len(ids)) for (log,_),(ids,_,_) in zip(batches,validated,strict=True)],
            declarations=[receipt["scientific_event_output"] for receipt in batch_receipts],particle_count=len(expected),
            particle_id_min=1,output_path=output_path,receipt_path=receipt_path,batch_original_ids=[ids for ids,_,_ in validated])
        result.update(role="mrtof_measured_batch_log_merge",preparation=file_record(preparation_path),
            mother_particle_count=preparation["mother_particle_count"],original_particle_ids=expected,
            solver_epoch_instrument_time_us=preparation["solver_epoch_instrument_time_us"],id_rebasing_applied=False)
        result["batches"]=[dict(log=dict(path=merged["path"], sha256=merged["sha256"]),batch_receipt=file_record(receipt),fly2=file_record(fly),
            scientific_event_output=batch["scientific_event_output"]) for (log,receipt),(_,batch,fly),merged in zip(batches,validated,result["batches"],strict=True)]
        receipt_path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        return result
    covered: list[int] = []
    records = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for path, batch_receipt_path in batches:
            ids, batch, fly_path = validate_measured_batch_terminal(
                log_path=path, batch_receipt_path=batch_receipt_path, preparation=preparation,
            )
            with path.open(encoding="utf-8-sig") as source:
                for line in source:
                    if parse_fly_completed_line(line) is None:
                        output.write(line)
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
    merge.add_argument("--batch-scientific-output", action="append")
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
    analyze_joint.add_argument("--analysis-contract", type=Path)
    compare_joint = sub.add_parser("compare-joint")
    compare_joint.add_argument("--preparation", required=True, type=Path)
    compare_joint.add_argument("--log", required=True, type=Path)
    compare_joint.add_argument("--output", required=True, type=Path)
    compare_joint.add_argument("--scientific-event-receipt", type=Path)
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
                                     merge_receipt=args.preparation.parent / "batch_log_merge_receipt.json",
                                     analysis_contract=args.analysis_contract)
        print("PREPARED_JOINT_DIAGNOSTICS=PASS")
    elif args.command == "compare-joint":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import compare_trajectory_representation
        compare_trajectory_representation(args.preparation, args.log, args.output,scientific_event_receipt=args.scientific_event_receipt)
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
            scientific_event_outputs=([json.loads(value) for value in args.batch_scientific_output] if args.batch_scientific_output is not None else None),
        )
        print("MRTOF_BATCH_LOG_MERGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
