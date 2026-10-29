"""Validate the stopped worker evidence needed to reuse an RF SIMION batch."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common.simion.native_completion import require_one_fly_completion


def validate_batch_completion(*, stdout: Path, state: Path, summary: Path,
                              particle_count: int, mechanical: Path | None = None) -> None:
    """Require a native completion and one terminal row for every local particle.

    Worker IDs are local to the batch; the existing batch plan supplies their
    original-ID offset when the files are merged.  This is completion evidence,
    not a scientific acceptance decision.
    """
    if particle_count <= 0:
        raise ValueError("batch particle count must be positive")
    with stdout.open(encoding="utf-8-sig", errors="strict") as stream:
        require_one_fly_completion(stream)
    document = json.loads(summary.read_text(encoding="utf-8-sig"))
    if document.get("solver") != "SIMION" or document.get("particles") != particle_count:
        raise ValueError("batch summary does not cover the planned population")
    with state.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"particle_id", "event"} <= set(reader.fieldnames):
            raise ValueError("batch state lacks particle identity or event")
        terminals = [int(row["particle_id"]) for row in reader if row["event"] == "terminal"]
    if len(terminals) != particle_count or set(terminals) != set(range(1, particle_count + 1)):
        raise ValueError("batch terminal rows do not close the planned population")
    if mechanical is not None:
        with mechanical.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "particle_id" not in reader.fieldnames:
                raise ValueError("batch mechanical exit lacks particle identity")
            observed = [int(row["particle_id"]) for row in reader]
        if len(observed) != len(set(observed)) or not set(observed) <= set(terminals):
            raise ValueError("batch mechanical exit identities differ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--particle-count", required=True, type=int)
    parser.add_argument("--mechanical", type=Path)
    args = parser.parse_args()
    validate_batch_completion(stdout=args.stdout, state=args.state, summary=args.summary,
                              particle_count=args.particle_count, mechanical=args.mechanical)
    print("RF_SIMION_BATCH_COMPLETION=PASS")


if __name__ == "__main__":
    main()
