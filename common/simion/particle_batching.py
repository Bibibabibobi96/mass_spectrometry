"""Shared, contract-shaped planning for one-wave SIMION particle batching.

The plan is solver- and workflow-neutral: it owns only the canonical population
and its contiguous global particle IDs.  A workflow remains responsible for its
own source projection and physics-specific output materialization.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any


def available_physical_memory_bytes() -> int | None:
    """Return presently available physical memory, or ``None`` if unavailable."""
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.available_physical)


def choose_memory_bound_batch_count(
    particle_count: int,
    default_batch_count: int,
    maximum_batch_count: int,
    per_batch_peak_working_set_bytes: int,
    reserve_available_memory_bytes: int,
    available_memory_bytes: int | None = None,
) -> dict[str, Any]:
    """Choose the largest one-wave parallel batch count supported by memory.

    The caller supplies a measured peak for the exact solver resource profile.
    No synthetic memory model or probe run is used.  If the host cannot report
    available memory, the contract default is retained.
    """
    if particle_count < 1:
        raise ValueError("particle count must be positive")
    if not 1 <= default_batch_count <= maximum_batch_count <= particle_count:
        raise ValueError("invalid default or maximum batch count")
    if per_batch_peak_working_set_bytes < 1 or reserve_available_memory_bytes < 0:
        raise ValueError("memory values must be non-negative with a positive per-batch peak")
    available = available_physical_memory_bytes() if available_memory_bytes is None else available_memory_bytes
    if available is None:
        selected, reason = default_batch_count, "host_memory_unavailable_use_contract_default"
    else:
        available = int(available)
        capacity = (available - reserve_available_memory_bytes) // per_batch_peak_working_set_bytes
        if capacity < 1:
            raise ValueError(
                "available memory cannot support even one batch after the reserved memory"
            )
        selected = min(maximum_batch_count, particle_count, int(capacity))
        reason = "largest_count_within_current_available_memory"
    return {
        "schema_version": 1,
        "role": "simion_memory_bound_single_wave_batch_decision",
        "dispatch": "single_wave_parallel",
        "selected_batch_count": selected,
        "default_batch_count": default_batch_count,
        "maximum_batch_count": maximum_batch_count,
        "per_batch_peak_working_set_bytes": per_batch_peak_working_set_bytes,
        "reserve_available_memory_bytes": reserve_available_memory_bytes,
        "available_memory_bytes": available,
        "selection_reason": reason,
    }


def select_nearest_memory_profile(
    target: dict[str, Any], candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select the most similar completed resource profile for memory planning.

    Similarity deliberately uses execution-resource descriptors only.  A larger
    score means fewer extrapolated dimensions; ties prefer the larger observed
    peak so the selected estimate remains useful as a planning upper estimate.
    """
    if not candidates:
        raise ValueError("at least one completed memory profile is required")
    keys = (
        "solver", "mode", "frontend_grid_profile_id",
        "oatof_numerical_profile_id", "trajectory_quality_profile_id",
        "time_integration_profile_id", "accelerator_field_profile_id",
        "frontend_pa0_sha256", "accelerator_overlay_pa0_sha256",
        "reflectron_pa0_sha256",
    )
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for candidate in candidates:
        peak = candidate.get("per_batch_peak_working_set_bytes")
        descriptors = candidate.get("resource_identity")
        if not isinstance(peak, int) or peak < 1 or not isinstance(descriptors, dict):
            raise ValueError("memory profile lacks descriptors or a positive per-batch peak")
        score = sum(
            1 for key in keys
            if target.get(key) is not None and target.get(key) == descriptors.get(key)
        )
        ranked.append((score, peak, candidate))
    score, _peak, selected = max(ranked, key=lambda item: (item[0], item[1]))
    result = dict(selected)
    result["match_score"] = score
    result["match_kind"] = (
        "exact_resource_profile" if score == len(keys)
        else "estimated_from_nearest_profile"
    )
    return result


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
    parser.add_argument("--event")
    parser.add_argument("--status")
    args = parser.parse_args()
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
