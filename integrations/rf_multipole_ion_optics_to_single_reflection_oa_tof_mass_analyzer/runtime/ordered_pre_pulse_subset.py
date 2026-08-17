"""Freeze and validate ordered pre-pulse subsets of one materialized mother."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
    materialize_pre_pulse_restart,
)


ORDERED_SUBSET_SELECTIONS = {
    "n1_center_source_id_500_v1": [500],
    "n100_file_order_source_ids_1_to_100_v1": list(range(1, 101)),
    "n100_uniform_full_width_source_ids_1_to_1000_v1": [
        1 + round(index * 999 / 99) for index in range(100)
    ],
}


def ordered_subset_source_particle_ids(selection_id: str) -> list[int]:
    """Resolve one preregistered subset selection to a fresh ordered ID list."""
    try:
        return list(ORDERED_SUBSET_SELECTIONS[selection_id])
    except KeyError as exc:
        raise ValueError("ordered subset selection identity is unsupported") from exc


def _id_list_sha256(particle_ids: list[int]) -> str:
    payload = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _ordered_id_sha256(count: int) -> str:
    return _id_list_sha256(list(range(1, count + 1)))


def materialize_ordered_pre_pulse_subset(
    mother_source_path: Path,
    mother_receipt_path: Path,
    subset_output_path: Path,
    subset_receipt_path: Path,
    *,
    pulse_time_us: float,
    ordered_source_particle_ids: list[int],
) -> dict[str, object]:
    """Freeze an ordered restart subset without changing particle state."""
    mother_receipt = json.loads(
        mother_receipt_path.read_text(encoding="utf-8-sig")
    )
    mother_target = mother_receipt.get("pulse_target_state", {})
    _, mother_rows = materialize_pre_pulse_restart(
        mother_source_path, pulse_time_us
    )
    mother_count = len(mother_rows)
    if (
        mother_receipt.get("role")
        != "rf_oatof_single_flight_source_materialization_receipt"
        or mother_receipt.get("method")
        != "resolved_layout_pulse_contract_ideal_linear_z_vz_v1"
        or mother_target.get("sha256") != file_sha256(mother_source_path)
        or mother_target.get("particle_count") != mother_count
    ):
        raise ValueError("ordered subset mother materialization identity differs")
    if (
        not ordered_source_particle_ids
        or len(ordered_source_particle_ids)
        != len(set(ordered_source_particle_ids))
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= mother_count
            for value in ordered_source_particle_ids
        )
    ):
        raise ValueError("ordered subset source-particle IDs are invalid")
    subset_rows = []
    row_map = []
    for simulation_id, source_id in enumerate(
        ordered_source_particle_ids, start=1
    ):
        row = dict(mother_rows[source_id - 1])
        row["particle_id"] = str(simulation_id)
        subset_rows.append(row)
        row_map.append(
            {
                "simulation_particle_id": simulation_id,
                "source_particle_id": source_id,
            }
        )
    subset_output_path.parent.mkdir(parents=True, exist_ok=True)
    with subset_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(subset_rows)
    subset_count = len(subset_rows)
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_pre_pulse_ordered_subset_receipt",
        "method": "frozen_ordered_subset_from_pre_pulse_mother_v1",
        "profile_id": mother_receipt["profile_id"],
        "source_profile_id": mother_receipt["source_profile_id"],
        "particle_count": subset_count,
        "source_full_width_mm": mother_receipt["source_full_width_mm"],
        "resolved_target_center_mm": mother_receipt[
            "resolved_target_center_mm"
        ],
        "resolved_pulse_time_us": pulse_time_us,
        "physics": mother_receipt["physics"],
        "mother_pulse_target_state": {
            "path": mother_source_path.name,
            "sha256": file_sha256(mother_source_path),
            "particle_count": mother_count,
            "materialization_receipt": {
                "path": mother_receipt_path.name,
                "sha256": file_sha256(mother_receipt_path),
            },
            "ordered_particle_id_sha256": _ordered_id_sha256(mother_count),
        },
        "selection": {
            "algorithm": "explicit_ordered_source_particle_ids_v1",
            "ordered_source_particle_ids": ordered_source_particle_ids,
            "ordered_source_particle_id_sha256": _id_list_sha256(
                ordered_source_particle_ids
            ),
            "simulation_to_source_particle_id": row_map,
            "postselection_prohibited": True,
        },
        "pulse_target_state": {
            "path": subset_output_path.name,
            "sha256": file_sha256(subset_output_path),
            "particle_count": subset_count,
            "source_state_epoch": "pulse_effective_time",
            "source_state_locus": mother_target["source_state_locus"],
            "coordinate_frame": "oatof_global_cartesian",
            "clock_basis": "canonical_instrument_time_us",
            "clock_authority": "resolved_single_flight_pulse_schedule",
            "ordered_particle_id_sha256": _ordered_id_sha256(subset_count),
        },
    }
    subset_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    subset_receipt_path.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def validate_ordered_pre_pulse_subset(
    subset_source_path: Path,
    subset_receipt: dict[str, object],
    mother_source_path: Path,
    mother_receipt_path: Path,
    *,
    pulse_time_us: float,
) -> list[dict[str, str]]:
    """Validate an ordered subset against its frozen mother bytes and receipt."""
    mother_receipt = json.loads(
        mother_receipt_path.read_text(encoding="utf-8-sig")
    )
    mother_target = mother_receipt.get("pulse_target_state", {})
    mother_record = subset_receipt.get("mother_pulse_target_state", {})
    selection = subset_receipt.get("selection", {})
    target = subset_receipt.get("pulse_target_state", {})
    if not all(
        isinstance(record, dict)
        for record in (mother_record, selection, target)
    ):
        raise ValueError("ordered subset receipt structure is invalid")
    source_ids = selection.get("ordered_source_particle_ids")
    materialization = mother_record.get("materialization_receipt", {})
    if (
        not isinstance(source_ids, list)
        or not isinstance(materialization, dict)
        or subset_receipt.get("role")
        != "rf_oatof_pre_pulse_ordered_subset_receipt"
        or subset_receipt.get("method")
        != "frozen_ordered_subset_from_pre_pulse_mother_v1"
        or subset_receipt.get("resolved_pulse_time_us") != pulse_time_us
        or mother_receipt.get("role")
        != "rf_oatof_single_flight_source_materialization_receipt"
        or mother_receipt.get("method")
        != "resolved_layout_pulse_contract_ideal_linear_z_vz_v1"
        or mother_record.get("sha256") != file_sha256(mother_source_path)
        or materialization.get("sha256")
        != file_sha256(mother_receipt_path)
        or mother_target.get("sha256") != file_sha256(mother_source_path)
        or target.get("sha256") != file_sha256(subset_source_path)
        or selection.get("algorithm")
        != "explicit_ordered_source_particle_ids_v1"
        or selection.get("postselection_prohibited") is not True
    ):
        raise ValueError("ordered subset receipt file identity differs")
    _, mother_rows = materialize_pre_pulse_restart(
        mother_source_path, pulse_time_us
    )
    _, subset_rows = materialize_pre_pulse_restart(
        subset_source_path, pulse_time_us
    )
    if (
        mother_record.get("particle_count") != len(mother_rows)
        or mother_target.get("particle_count") != len(mother_rows)
        or mother_record.get("ordered_particle_id_sha256")
        != _ordered_id_sha256(len(mother_rows))
        or target.get("particle_count") != len(subset_rows)
        or target.get("ordered_particle_id_sha256")
        != _ordered_id_sha256(len(subset_rows))
        or len(source_ids) != len(subset_rows)
    ):
        raise ValueError("ordered subset population identity differs")
    expected_map = []
    for simulation_id, source_id in enumerate(source_ids, start=1):
        if (
            not isinstance(source_id, int)
            or isinstance(source_id, bool)
            or not 1 <= source_id <= len(mother_rows)
        ):
            raise ValueError("ordered subset source-particle ID is invalid")
        expected = dict(mother_rows[source_id - 1])
        expected["particle_id"] = str(simulation_id)
        if subset_rows[simulation_id - 1] != expected:
            raise ValueError("ordered subset particle state differs from mother")
        expected_map.append(
            {
                "simulation_particle_id": simulation_id,
                "source_particle_id": source_id,
            }
        )
    if (
        len(source_ids) != len(set(source_ids))
        or selection.get("simulation_to_source_particle_id") != expected_map
        or selection.get("ordered_source_particle_id_sha256")
        != _id_list_sha256(source_ids)
    ):
        raise ValueError("ordered subset selection identity differs")
    if (
        mother_receipt.get("profile_id")
        != subset_receipt.get("profile_id")
        or mother_receipt.get("source_profile_id")
        != subset_receipt.get("source_profile_id")
        or mother_receipt.get("resolved_target_center_mm")
        != subset_receipt.get("resolved_target_center_mm")
        or mother_receipt.get("physics") != subset_receipt.get("physics")
    ):
        raise ValueError(
            "ordered subset scientific authority differs from mother"
        )
    return subset_rows
