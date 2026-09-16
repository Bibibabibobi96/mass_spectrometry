"""Materialize contiguous MR-TOF Fly2 slices and merge global-ID event logs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    load_verified_bunch_source_receipt,
    render_bunch_fly2,
    source_cohort_identity,
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
    """Resolve one immutable contiguous interval from a verified mother cohort."""
    receipt = load_verified_bunch_source_receipt(receipt_path)
    count = int(receipt["particle_count"])
    if not 1 <= particle_id_min <= particle_id_max <= count:
        raise ValueError("source particle interval is outside the frozen cohort")
    with Path(receipt["state_table"]["path"]).open(
        "r", encoding="utf-8", newline="",
    ) as stream:
        rows = list(csv.DictReader(stream))
    selected = rows[particle_id_min - 1:particle_id_max]
    particle_ids = list(range(particle_id_min, particle_id_max + 1))
    if [int(row["particle_id"]) for row in selected] != particle_ids:
        raise ValueError("source selection is not one contiguous global-ID interval")
    states = [{
        "tob_us": float(row["tob_us"]),
        "mass_th": float(row["mass_th"]),
        "charge_e": int(row["charge_e"]),
        "kinetic_energy_ev": float(row["kinetic_energy_ev"]),
        "position_workbench_mm": [float(row[key]) for key in ("x_mm", "y_mm", "z_mm")],
        "direction_workbench": [
            float(row[key]) for key in ("direction_x", "direction_y", "direction_z")
        ],
    } for row in selected]
    fly2 = render_bunch_fly2(states)
    ids_payload = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    state_payload = json.dumps(states, sort_keys=True, separators=(",", ":")).encode("utf-8")
    parent_identity = source_cohort_identity(receipt)
    cohort_identity = {
        **parent_identity,
        "particle_count": len(states),
        "expected_particle_ids_sha256": hashlib.sha256(ids_payload).hexdigest(),
        "particle_states_sha256": hashlib.sha256(state_payload).hexdigest(),
        "selection": {
            "role": "contiguous_frozen_source_diagnostic_selection",
            "particle_id_min": particle_id_min,
            "particle_id_max": particle_id_max,
            "parent_particle_count": count,
            "parent_particle_states_sha256": parent_identity["particle_states_sha256"],
            "source_receipt_sha256": _sha256(receipt_path),
        },
    }
    selected_fly2_sha256 = hashlib.sha256(fly2.encode("utf-8")).hexdigest()
    cohort_identity["selection"].update({
        "expected_particle_ids_sha256": cohort_identity["expected_particle_ids_sha256"],
        "particle_states_sha256": cohort_identity["particle_states_sha256"],
        "fly2_sha256": selected_fly2_sha256,
    })
    return {
        "particle_ids": particle_ids,
        "states": states,
        "fly2": fly2,
        "fly2_sha256": selected_fly2_sha256,
        "source_cohort": cohort_identity,
    }


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
    args = parser.parse_args()
    if args.command == "materialize":
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
