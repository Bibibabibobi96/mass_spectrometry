"""Materialize an explicitly selected subset of a compact TRACE handoff."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    ATTRIBUTION_COLUMNS,
    materialize_pre_pulse_restart,
)


COMPACT_RECEIPT_ROLE = "rf_oatof_compact_pre_pulse_trace_handoff_receipt"
SUBSET_RECEIPT_ROLE = "rf_oatof_compact_pre_pulse_subset_receipt"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "schemas"
    / "rf_oatof_compact_pre_pulse_subset_receipt.schema.json"
)


def _id_sha256(particle_ids: list[int]) -> str:
    """Return the canonical identity for an ordered particle-ID sequence."""

    payload = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("compact handoff receipt is unreadable") from exc
    if not isinstance(receipt, dict):
        raise ContractError("compact handoff receipt must be an object")
    return receipt


def materialize_compact_pre_pulse_subset(
    compact_state_path: Path,
    compact_receipt_path: Path,
    subset_output_path: Path,
    subset_receipt_path: Path,
    *,
    ordered_source_particle_ids: list[int],
) -> dict[str, Any]:
    """Copy selected compact states into an attribution-preserving restart table.

    The compact state already contains only detector-blind pulse-eligible ions.
    This function never ranks or filters it implicitly: callers state the exact
    ordered original IDs, which remain in ``source_particle_id`` while the
    restart-only simulation IDs become contiguous.
    """

    compact_receipt = _load_receipt(compact_receipt_path)
    selection = compact_receipt.get("selection")
    target = compact_receipt.get("pulse_target_state")
    if (
        compact_receipt.get("role") != COMPACT_RECEIPT_ROLE
        or compact_receipt.get("status") != "success"
        or compact_receipt.get("detector_results_used") is not False
        or compact_receipt.get("selection_uses_detector_outcome") is not False
        or not isinstance(selection, dict)
        or not isinstance(target, dict)
        or target.get("sha256") != file_sha256(compact_state_path)
    ):
        raise ContractError("compact handoff receipt identity differs")
    source_ids = selection.get("pulse_eligible_particle_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(value, int) or isinstance(value, bool) for value in source_ids)
        or len(source_ids) != len(set(source_ids))
        or target.get("particle_count") != len(source_ids)
        or target.get("ordered_particle_id_sha256") != _id_sha256(source_ids)
    ):
        raise ContractError("compact handoff source population differs")
    if (
        not ordered_source_particle_ids
        or len(ordered_source_particle_ids) != len(set(ordered_source_particle_ids))
        or any(value not in source_ids for value in ordered_source_particle_ids)
    ):
        raise ContractError("compact subset source particle IDs are invalid")
    pulse_time_us = target.get("pulse_effective_time_us")
    if not isinstance(pulse_time_us, (int, float)) or isinstance(pulse_time_us, bool):
        raise ContractError("compact handoff pulse time is invalid")
    _, compact_rows, row_map = materialize_pre_pulse_restart(
        compact_state_path, float(pulse_time_us), return_row_map=True
    )
    row_by_source_id = {
        int(mapping["source_particle_id"]): row
        for row, mapping in zip(compact_rows, row_map, strict=True)
    }
    if set(row_by_source_id) != set(source_ids):
        raise ContractError("compact handoff state rows differ from its receipt")
    subset_rows: list[dict[str, str]] = []
    restart_map: list[dict[str, int]] = []
    for simulation_id, source_id in enumerate(ordered_source_particle_ids, start=1):
        row = row_by_source_id[source_id]
        subset_rows.append({
            "simulation_particle_id": str(simulation_id),
            "source_particle_id": str(source_id),
            "arm_id": "compact_pre_pulse_trace_handoff",
            "instrument_time_us": row["instrument_time_us"],
            "mass_amu": row["mass_amu"],
            "charge_state": row["charge_state"],
            **{axis + "_mm": row["position_" + axis + "_mm"] for axis in "xyz"},
            **{"v" + axis + "_m_s": row["velocity_" + axis + "_m_s"] for axis in "xyz"},
            "kinetic_energy_eV": row["kinetic_energy_eV"],
        })
        restart_map.append({
            "simulation_particle_id": simulation_id,
            "source_particle_id": source_id,
        })
    subset_output_path.parent.mkdir(parents=True, exist_ok=True)
    with subset_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ATTRIBUTION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(subset_rows)
    receipt = {
        "schema_version": 1,
        "role": SUBSET_RECEIPT_ROLE,
        "status": "success",
        "method": "explicit_ordered_subset_from_compact_trace_handoff_v1",
        "detector_results_used": False,
        "selection_uses_detector_outcome": False,
        "pulse_disabled": True,
        "producer": {
            "compact_handoff_receipt": {
                "path": str(compact_receipt_path),
                "sha256": file_sha256(compact_receipt_path),
            },
            "compact_handoff_state": {
                "path": str(compact_state_path),
                "sha256": file_sha256(compact_state_path),
            },
        },
        "selection": {
            "mother_population_count": selection["mother_population_count"],
            "compact_pulse_eligible_particle_count": len(source_ids),
            "ordered_source_particle_ids": ordered_source_particle_ids,
            "ordered_source_particle_id_sha256": _id_sha256(ordered_source_particle_ids),
            "simulation_to_source_particle_id": restart_map,
            "postselection_prohibited": True,
        },
        "pulse_target_state": {
            "path": str(subset_output_path),
            "sha256": file_sha256(subset_output_path),
            "particle_count": len(subset_rows),
            "ordered_particle_id_sha256": _id_sha256(ordered_source_particle_ids),
            "source_state_epoch": target["source_state_epoch"],
            "coordinate_frame": target["coordinate_frame"],
            "clock_basis": target["clock_basis"],
            "clock_authority": target["clock_authority"],
            "pulse_effective_time_us": pulse_time_us,
        },
        "claim_limit": "DETECTOR_BLIND_PRE_PULSE_SUBSET_HANDOFF_ONLY",
    }
    validate_schema(receipt, SCHEMA_PATH)
    subset_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    subset_receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact-state", required=True, type=Path)
    parser.add_argument("--compact-receipt", required=True, type=Path)
    parser.add_argument("--output-state", required=True, type=Path)
    parser.add_argument("--output-receipt", required=True, type=Path)
    parser.add_argument("--source-particle-id", required=True, action="append", type=int)
    arguments = parser.parse_args()
    receipt = materialize_compact_pre_pulse_subset(
        arguments.compact_state,
        arguments.compact_receipt,
        arguments.output_state,
        arguments.output_receipt,
        ordered_source_particle_ids=arguments.source_particle_id,
    )
    print(f"COMPACT_PRE_PULSE_SUBSET=PASS PARTICLES={receipt['pulse_target_state']['particle_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
