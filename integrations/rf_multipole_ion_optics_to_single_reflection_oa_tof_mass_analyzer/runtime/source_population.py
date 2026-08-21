"""Derive a source population from a manifest-frozen state selector."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256


def derive_source_population(
    state_path: Path,
    *,
    expected_state_sha256: str,
    selector: Mapping[str, str],
) -> dict[str, Any]:
    """Return the receipt for the ordered unique IDs selected from ``state_path``."""
    actual_sha256 = file_sha256(state_path)
    if actual_sha256 != expected_state_sha256:
        raise ValueError("source state SHA-256 differs")
    event = selector.get("event")
    status = selector.get("status")
    if not event or not status:
        raise ValueError("source population selector is incomplete")
    ordered_ids: list[int] = []
    with state_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"particle_id", "event", "status"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("source state lacks selector columns")
        for row in reader:
            if row["event"] == event and row["status"] == status:
                particle_id = int(row["particle_id"])
                if particle_id < 1:
                    raise ValueError("source state contains a non-positive particle ID")
                ordered_ids.append(particle_id)
    if not ordered_ids:
        raise ValueError("source population selector matched no particles")
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("source population selector matched duplicate particle IDs")
    ordered_id_sha256 = hashlib.sha256(
        json.dumps(ordered_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    return {
        "schema_version": 1,
        "role": "rf_multipole_oatof_source_population_receipt",
        "status": "PASS",
        "source_state": {"sha256": actual_sha256},
        "selector": {"event": event, "status": status},
        "particle_count": len(ordered_ids),
        "ordered_particle_id_sha256": ordered_id_sha256,
    }


def write_source_population_receipt(
    state_path: Path,
    output_path: Path,
    *,
    expected_state_sha256: str,
    selector: Mapping[str, str],
) -> dict[str, Any]:
    receipt = derive_source_population(
        state_path,
        expected_state_sha256=expected_state_sha256,
        selector=selector,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
