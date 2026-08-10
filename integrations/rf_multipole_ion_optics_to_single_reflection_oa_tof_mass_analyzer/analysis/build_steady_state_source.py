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
    target_count: int = 1000,
    seed: int = SELECTION_SEED,
    batch_directory: Path | None = None,
    batch_count: int = 5,
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
    if len(candidates) < target_count:
        raise ValueError("candidate pool contains too few pulse-eligible ions")
    random.Random(seed).shuffle(candidates)
    selected = candidates[:target_count]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for particle_id, (_, _, row) in enumerate(selected, 1):
            writer.writerow(dict(row, particle_id=str(particle_id)))
    output_batches: list[dict[str, object]] = []
    if batch_directory is not None:
        if target_count % batch_count:
            raise ValueError("selected source must divide evenly into execution batches")
        batch_directory.mkdir(parents=True, exist_ok=True)
        size = target_count // batch_count
        for batch_index in range(batch_count):
            path = batch_directory / f"rf_multipole_steady_pulse_eligible_v1_batch{batch_index + 1:02d}_{size}.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for local_id, (_, _, row) in enumerate(
                    selected[batch_index * size : (batch_index + 1) * size], 1
                ):
                    writer.writerow(dict(row, particle_id=str(local_id)))
            output_batches.append({
                "batch_index": batch_index + 1,
                "global_particle_id_offset": batch_index * size,
                "particle_count": size,
                "path": _portable_receipt_path(path),
                "sha256": sha256(path),
            })
    receipt: dict[str, object] = {
        "schema_version": 1,
        "role": "rf_oatof_steady_state_source_selection_receipt",
        "method": "detector_blind_prepulse_geometric_conditioning",
        "physics_scope": {
            "continuous_entrance_injection": True,
            "rf_phase_uniform_over_one_period": True,
            "pulse_phase_locked": True,
            "collisions_enabled": False,
            "space_charge_enabled": False,
        },
        "selection_seed": seed,
        "candidate_launched_count": sum(int(batch["launched_count"]) for batch in batches),
        "candidate_eligible_count": len(candidates),
        "raw_pulse_capture_fraction": len(candidates) / sum(int(batch["launched_count"]) for batch in batches),
        "selected_count": target_count,
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
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--batch-directory", type=Path)
    parser.add_argument("--batch-count", type=int, default=5)
    args = parser.parse_args()
    receipt = build(
        args.source, args.checkpoints, args.output, args.receipt,
        args.target_count, batch_directory=args.batch_directory,
        batch_count=args.batch_count,
    )
    print(
        "STEADY_STATE_SOURCE=PASS "
        f"CANDIDATES={receipt['candidate_launched_count']} "
        f"ELIGIBLE={receipt['candidate_eligible_count']} SELECTED={receipt['selected_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
