"""Select a detector-blind pulse-eligible source from independent SIMION pilots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path


SOURCE_COLUMNS = [
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s",
    "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
]
SELECTION_SEED = 2026081002


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _portable_receipt_path(path: Path) -> str:
    parts = path.as_posix().split("/")
    for marker in ("artifacts", "common", "integrations", "projects"):
        if marker in parts:
            return "/".join(parts[parts.index(marker) :])
    return path.name


def build(
    source_paths: list[Path],
    checkpoint_paths: list[Path],
    output_path: Path,
    receipt_path: Path,
    target_count: int | None = 1000,
    seed: int = SELECTION_SEED,
    batch_directory: Path | None = None,
    batch_count: int = 5,
    selection_mode: str = "random_subset",
) -> dict[str, object]:
    if len(source_paths) != len(checkpoint_paths) or not source_paths:
        raise ValueError("source and checkpoint batches must pair one-to-one")
    candidates: list[tuple[int, int, dict[str, str]]] = []
    batches: list[dict[str, object]] = []
    for batch_index, (source_path, checkpoint_path) in enumerate(
        zip(source_paths, checkpoint_paths, strict=True), 1
    ):
        with source_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != SOURCE_COLUMNS:
                raise ValueError("candidate source columns differ from contract")
            source_rows = {int(row["particle_id"]): row for row in reader}
        eligible_ids: set[int] = set()
        with checkpoint_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["event"] == "detector_crossing":
                    raise ValueError("selection pilot must terminate before detector transport")
                if row["event"] == "pre_pulse_state" and row["pulse_eligibility"] == "eligible":
                    eligible_ids.add(int(row["particle_id"]))
        if not eligible_ids.issubset(source_rows):
            raise ValueError("checkpoint particle identity is outside its source batch")
        candidates.extend(
            (batch_index, particle_id, source_rows[particle_id])
            for particle_id in sorted(eligible_ids)
        )
        batches.append({
            "batch_index": batch_index,
            "source_path": source_path.as_posix(),
            "source_sha256": sha256(source_path),
            "checkpoint_path": _portable_receipt_path(checkpoint_path),
            "checkpoint_sha256": sha256(checkpoint_path),
            "launched_count": len(source_rows),
            "eligible_count": len(eligible_ids),
        })
    if selection_mode == "all_eligible":
        if target_count is not None:
            raise ValueError("all-eligible selection must not declare a target count")
        selected = candidates
    elif selection_mode == "random_subset":
        if target_count is None or target_count < 1:
            raise ValueError("random-subset selection requires a positive target count")
        if len(candidates) < target_count:
            raise ValueError("candidate pool contains too few pulse-eligible ions")
        random.Random(seed).shuffle(candidates)
        selected = candidates[:target_count]
    else:
        raise ValueError("unknown steady-source selection mode")
    selected_count = len(selected)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for particle_id, (_, _, row) in enumerate(selected, 1):
            writer.writerow(dict(row, particle_id=str(particle_id)))
    output_batches: list[dict[str, object]] = []
    if batch_directory is not None:
        if batch_count < 1 or batch_count > selected_count:
            raise ValueError("execution batch count is outside selected population")
        batch_directory.mkdir(parents=True, exist_ok=True)
        quotient, remainder = divmod(selected_count, batch_count)
        start = 0
        for batch_index in range(batch_count):
            size = quotient + (1 if batch_index < remainder else 0)
            path = batch_directory / (
                f"{output_path.stem}_batch{batch_index + 1:02d}_{size}.csv"
            )
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for local_id, (_, _, row) in enumerate(
                    selected[start : start + size], 1
                ):
                    writer.writerow(dict(row, particle_id=str(local_id)))
            output_batches.append({
                "batch_index": batch_index + 1,
                "global_particle_id_offset": start,
                "particle_count": size,
                "path": _portable_receipt_path(path),
                "sha256": sha256(path),
            })
            start += size
    receipt: dict[str, object] = {
        "schema_version": 2,
        "role": "rf_oatof_steady_state_source_selection_receipt",
        "method": "detector_blind_prepulse_geometric_conditioning",
        "candidate_injection_contract": {
            "continuous_entrance_injection": True,
            "rf_phase_uniform_over_one_period": True,
            "pulse_phase_locked": True,
            "collisions_enabled": False,
            "space_charge_enabled": False,
        },
        "selected_population_contract": {
            "population": "all_detector_blind_pulse_eligible_particles",
            "conditional_on": "inside_open_accelerator_stage1_at_pulse",
            "rf_phase_uniformity_claim": False,
            "independent_particle_equivalence": True,
            "efficiency_denominator": "candidate_launched_count",
        },
        "selection_mode": selection_mode,
        "selection_seed": seed if selection_mode == "random_subset" else None,
        "candidate_launched_count": sum(int(batch["launched_count"]) for batch in batches),
        "candidate_eligible_count": len(candidates),
        "raw_pulse_capture_fraction": len(candidates) / sum(int(batch["launched_count"]) for batch in batches),
        "selected_count": selected_count,
        "unselected_eligible_count": len(candidates) - selected_count,
        "selection_uses_detector_outcome": False,
        "batches": batches,
        "selected_lineage_sha256": hashlib.sha256(
            "".join(
                f"{index},{batch},{original}\n"
                for index, (batch, original, _) in enumerate(selected, 1)
            ).encode("ascii")
        ).hexdigest().upper(),
        "output_path": _portable_receipt_path(output_path),
        "output_sha256": sha256(output_path),
        "execution_batch_count": batch_count if output_batches else 1,
        "execution_batches": output_batches,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, type=Path)
    parser.add_argument("--checkpoints", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--target-count", type=int)
    parser.add_argument(
        "--selection-mode",
        choices=("random_subset", "all_eligible"),
        default="random_subset",
    )
    parser.add_argument("--batch-directory", type=Path)
    parser.add_argument("--batch-count", type=int, default=5)
    args = parser.parse_args()
    receipt = build(
        args.source, args.checkpoints, args.output, args.receipt,
        1000 if args.selection_mode == "random_subset" and args.target_count is None
        else args.target_count,
        batch_directory=args.batch_directory, batch_count=args.batch_count,
        selection_mode=args.selection_mode,
    )
    print(
        "STEADY_STATE_SOURCE=PASS "
        f"CANDIDATES={receipt['candidate_launched_count']} "
        f"ELIGIBLE={receipt['candidate_eligible_count']} SELECTED={receipt['selected_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
