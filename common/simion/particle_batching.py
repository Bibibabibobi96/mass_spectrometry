"""Shared, contract-shaped planning for one-wave SIMION particle batching.

The plan is solver- and workflow-neutral: it owns only the canonical population
and its contiguous global particle IDs.  A workflow remains responsible for its
own source projection and physics-specific output materialization.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def plan_single_wave_batches(particle_count: int, batch_count: int) -> dict[str, Any]:
    """Return an exact balanced partition of canonical IDs ``1..particle_count``."""
    if isinstance(particle_count, bool) or particle_count < 1:
        raise ValueError("particle count must be a positive integer")
    if isinstance(batch_count, bool) or not 1 <= batch_count <= particle_count:
        raise ValueError("batch count must be between one and the particle count")
    quotient, remainder = divmod(particle_count, batch_count)
    offset = 0
    batches: list[dict[str, int]] = []
    for index in range(1, batch_count + 1):
        count = quotient + (1 if index <= remainder else 0)
        first = offset + 1
        last = offset + count
        batches.append(
            {
                "index": index,
                "count": count,
                "particle_id_min": first,
                "particle_id_max": last,
                "simion_particle_id_offset": offset,
            }
        )
        offset = last
    if offset != particle_count:
        raise AssertionError("single-wave batch plan does not cover its population")
    return {
        "schema_version": 1,
        "role": "simion_single_wave_particle_batch_plan",
        "dispatch": "single_wave_parallel",
        "particle_count": particle_count,
        "batch_count": batch_count,
        "batches": batches,
    }


def batch_plan_from_dispatch(dispatch_plan: dict[str, Any]) -> dict[str, Any]:
    """Project the scheduler's current particle partition into merge format."""
    if dispatch_plan.get("role") != "simion_repository_dispatch_plan":
        raise ValueError("dispatch plan has an unsupported role")
    waves = dispatch_plan.get("waves")
    if not isinstance(waves, list) or len(waves) != 1 or not isinstance(waves[0], dict):
        raise ValueError("dispatch plan must contain exactly one wave")
    wave = waves[0]
    batches = wave.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ValueError("dispatch wave has no particle batches")
    result = {
        "schema_version": 1,
        "role": "simion_single_wave_particle_batch_plan",
        "dispatch": "single_wave_parallel",
        "particle_count": dispatch_plan.get("particle_count"),
        "batch_count": len(batches),
        "coverage": wave.get("coverage"),
        "batches": batches,
    }
    if wave.get("coverage") == "complete_population":
        expected = list(range(1, int(result["particle_count"]) + 1))
        actual = [
            particle_id
            for batch in batches
            for particle_id in range(
                batch["particle_id_min"], batch["particle_id_max"] + 1
            )
        ]
        if actual != expected:
            raise ValueError("complete dispatch wave does not cover each particle exactly once")
    return result


def merge_rebased_particle_csvs(
    batches: list[tuple[Path, int]], output: Path
) -> None:
    """Merge batch CSVs while restoring canonical global particle IDs.

    Rows remain in batch and solver emission order.  This supports both event
    tables (multiple rows per particle) and trajectory tables.
    """
    if not batches:
        raise ValueError("at least one batch CSV is required")
    expected_header: list[str] | None = None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as destination:
        writer: csv.DictWriter | None = None
        for source, offset in batches:
            if offset < 0:
                raise ValueError("SIMION particle ID offset must be non-negative")
            with source.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames or reader.fieldnames[0] != "particle_id":
                    raise ValueError(f"batch CSV lacks a leading particle_id column: {source}")
                if expected_header is None:
                    expected_header = list(reader.fieldnames)
                    writer = csv.DictWriter(destination, fieldnames=expected_header)
                    writer.writeheader()
                elif reader.fieldnames != expected_header:
                    raise ValueError(f"batch CSV header differs: {source}")
                assert writer is not None
                for row in reader:
                    try:
                        local_id = int(row["particle_id"])
                    except (KeyError, ValueError) as error:
                        raise ValueError(f"batch CSV has an invalid particle ID: {source}") from error
                    if local_id < 1:
                        raise ValueError(f"batch CSV has a non-positive particle ID: {source}")
                    row["particle_id"] = str(local_id + offset)
                    writer.writerow(row)


def merge_simion_summaries(
    summaries: list[Path], batch_plan: dict[str, Any], output: Path
) -> None:
    """Aggregate per-batch SIMION summaries under one validated batch plan."""
    if not summaries:
        raise ValueError("at least one batch summary is required")
    documents = [json.loads(path.read_text(encoding="utf-8-sig")) for path in summaries]
    first = documents[0]
    for field in ("solver", "mode", "operating_point", "parent_resolved_design_sha256"):
        if any(document.get(field) != first.get(field) for document in documents[1:]):
            raise ValueError(f"batch summary field differs: {field}")
    for field in ("particles", "census_plane_crossings", "hits"):
        if any(not isinstance(document.get(field), int) for document in documents):
            raise ValueError(f"batch summary lacks integer {field}")
    result = dict(first)
    for field in ("particles", "census_plane_crossings", "hits"):
        result[field] = sum(document[field] for document in documents)
    if result["particles"] != batch_plan["particle_count"]:
        raise ValueError("batch summaries do not cover the planned particle population")
    result["transmission"] = result["census_plane_crossings"] / result["particles"]
    result["batch_execution"] = {
        "dispatch": batch_plan["dispatch"],
        "batch_count": batch_plan["batch_count"],
        "particle_id_intervals": [
            {"first": item["particle_id_min"], "last": item["particle_id_max"]}
            for item in batch_plan["batches"]
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def count_csv_rows(path: Path, event: str | None = None, status: str | None = None) -> int:
    """Stream-count CSV rows, optionally under exact event/status selectors."""
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError(f"CSV lacks a header: {path}")
        if event is not None and "event" not in reader.fieldnames:
            raise ValueError(f"CSV lacks event column: {path}")
        if status is not None and "status" not in reader.fieldnames:
            raise ValueError(f"CSV lacks status column: {path}")
        return sum(1 for row in reader if (event is None or row["event"] == event) and (status is None or row["status"] == status))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particle-count", type=int)
    parser.add_argument("--batch-count", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--merge-rebase-csv", action="store_true")
    parser.add_argument("--batch-csv", action="append", nargs=2, metavar=("PATH", "OFFSET"))
    parser.add_argument("--merge-summaries", action="store_true")
    parser.add_argument("--batch-summary", action="append", type=Path)
    parser.add_argument("--batch-plan", type=Path)
    parser.add_argument("--count-csv", type=Path)
    parser.add_argument("--from-dispatch-plan", type=Path)
    parser.add_argument("--event")
    parser.add_argument("--status")
    args = parser.parse_args()
    if args.from_dispatch_plan:
        if (
            args.count_csv or args.merge_rebase_csv or args.merge_summaries
            or args.particle_count or args.batch_count
        ):
            parser.error("dispatch projection accepts no other operation")
        dispatch = json.loads(args.from_dispatch_plan.read_text(encoding="utf-8-sig"))
        result = batch_plan_from_dispatch(dispatch)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"SIMION_DISPATCH_BATCH_PLAN=PASS BATCHES={result['batch_count']}")
        return 0
    if args.count_csv:
        if args.merge_rebase_csv or args.merge_summaries or args.particle_count or args.batch_count:
            parser.error("CSV count accepts no batch or merge arguments")
        result = {"rows": count_csv_rows(args.count_csv, args.event, args.status)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result) + "\n", encoding="utf-8")
        print(f"SIMION_PARTICLE_CSV_COUNT=PASS ROWS={result['rows']}")
        return 0
    if args.merge_rebase_csv:
        if args.particle_count or args.batch_count:
            parser.error("CSV merge does not accept batch-plan arguments")
        batches = [(Path(path), int(offset)) for path, offset in args.batch_csv or []]
        merge_rebased_particle_csvs(batches, args.output)
        print(f"SIMION_PARTICLE_CSV_MERGE=PASS BATCHES={len(batches)}")
        return 0
    if args.merge_summaries:
        if args.particle_count or args.batch_count or not args.batch_plan:
            parser.error("summary merge requires only --batch-plan and --batch-summary")
        batch_plan = json.loads(args.batch_plan.read_text(encoding="utf-8-sig"))
        merge_simion_summaries(args.batch_summary or [], batch_plan, args.output)
        print(f"SIMION_SUMMARY_MERGE=PASS BATCHES={len(args.batch_summary or [])}")
        return 0
    if args.particle_count is None or args.batch_count is None:
        parser.error("batch planning requires --particle-count and --batch-count")
    plan = plan_single_wave_batches(args.particle_count, args.batch_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(
        "SIMION_SINGLE_WAVE_BATCH_PLAN=PASS "
        f"PARTICLES={args.particle_count} BATCHES={args.batch_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
