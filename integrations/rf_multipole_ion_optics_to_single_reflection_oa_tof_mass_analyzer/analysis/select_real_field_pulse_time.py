"""Select a real-field pulse leading edge from a preregistered state-time grid."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
    _observed_id_set,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    select_detector_blind_real_field_pulse_time,
)


SELECTION_ORDER = [
    "maximize_pulse_eligible_count",
    "maximize_transverse_bore_count",
    "minimize_normalized_xyz_centroid_distance",
    "minimize_normalized_xyz_spread_norm",
    "minimize_absolute_distance_to_ballistic_seed",
    "select_earlier_time",
]
REQUIRED_STATE_COLUMNS = {
    "particle_id", "event", "sample_index", "instrument_time_us",
    "actual_instrument_time_us", "x_mm", "y_mm", "z_mm", "survival_status",
}
ALLOWED_STATE_COLUMNS = REQUIRED_STATE_COLUMNS | {
    "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "kinetic_energy_eV",
    "frame_id", "clock_epoch_id", "status", "checkpoint_provenance",
}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _load_state_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        if not REQUIRED_STATE_COLUMNS.issubset(columns):
            raise ContractError("real-field pulse state table is missing required columns")
        if columns - ALLOWED_STATE_COLUMNS:
            raise ContractError("real-field pulse state table contains forbidden columns")
        rows = list(reader)
    if not rows:
        raise ContractError("real-field pulse state table is empty")
    if any(
        "detector" in str(value).casefold()
        for row in rows
        for value in row.values()
        if value is not None
    ):
        raise ContractError("real-field pulse state table contains detector outcomes")
    return rows


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _binding(path: Path, *, repository_text: bool = False) -> dict[str, str]:
    return {
        "path": str(path.resolve()),
        "sha256": (
            repository_text_sha256(path) if repository_text else file_sha256(path)
        ),
    }


def _validate_screening_contract(contract: dict[str, Any]) -> bool:
    if (
        contract.get("role") != "rf_oatof_pre_pulse_time_series_screening_contract"
        or contract.get("mode") != "real_pa_rf_pre_pulse_time_series"
        or contract.get("pulse_disabled") is not True
        or contract.get("resolution_claim_allowed") is not False
        or contract.get("identities", {}).get("spatial_window_profile_id")
        != "ideal_source_box_1mm_xyz"
    ):
        raise ContractError("pre-pulse screening selection contract is invalid")
    selection_order = contract.get("selection_order")
    if selection_order is not None and selection_order != SELECTION_ORDER:
        raise ContractError("pre-pulse screening selection order differs")
    return selection_order is not None


def _load_population_ids(
    population: dict[str, Any], population_table_path: Path,
) -> list[int]:
    authority = population.get("source_authority", {})
    table = authority.get("table", {})
    if (
        population.get("role") != "rf_oatof_resolved_population_contract"
        or authority.get("table_binding") != "prepared_deterministic_prefix"
        or not population_table_path.is_file()
        or file_sha256(population_table_path) != table.get("sha256")
    ):
        raise ContractError("real-field pulse population table identity differs")
    with population_table_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "particle_id" not in (reader.fieldnames or ()):
            raise ContractError("real-field pulse population table has no particle IDs")
        try:
            particle_ids = [int(row["particle_id"]) for row in reader]
        except (TypeError, ValueError) as exc:
            raise ContractError("real-field pulse population ID is invalid") from exc
    identity = _observed_id_set(particle_ids)
    execution = population.get("execution_population", {})
    if (
        not particle_ids
        or len(set(particle_ids)) != len(particle_ids)
        or len(particle_ids) != execution.get("particle_count")
        or identity["ordered_particle_id_sha256"]
        != execution.get("ordered_particle_id_sha256")
    ):
        raise ContractError("real-field pulse population order differs")
    return particle_ids


def _validate_screening_receipt(
    receipt: dict[str, Any], *, contract: dict[str, Any],
    contract_path: Path, state_table_path: Path,
) -> None:
    states = receipt.get("outputs", {}).get("states", {})
    if (
        receipt.get("role") != "rf_oatof_pre_pulse_time_series_screening_receipt"
        or receipt.get("status") != "success"
        or receipt.get("execution_mode") != "real_pa_rf_pre_pulse_time_series"
        or receipt.get("pulse_disabled") is not True
        or receipt.get("resolution_claim_allowed") is not False
        or receipt.get("contract_sha256") != file_sha256(contract_path)
        or receipt.get("rf_time_grid") != contract.get("rf_time_grid")
        or states.get("sha256") != file_sha256(state_table_path)
        or states.get("row_count") != receipt.get("state_row_count")
    ):
        raise ContractError("pre-pulse screening receipt identity differs")
    receipt_ids = receipt.get("identities", {})
    contract_ids = contract.get("identities", {})
    for key in (
        "campaign_id", "experiment_id", "connection_profile_id",
        "ordered_particle_id_sha256", "layout_profile_id",
        "field_profile_id", "time_integration_profile_id",
    ):
        if receipt_ids.get(key) != contract_ids.get(key):
            raise ContractError("pre-pulse screening receipt identity differs")


def pulse_selection_content_identity(
    *, contract: dict[str, Any], population: dict[str, Any],
    source: dict[str, Any], connection: dict[str, Any], geometry: dict[str, Any],
    spatial_profile: dict[str, Any], selector_source_path: Path | None = None,
    selector_source_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Return the canonical detector-blind selection identity and digest."""
    if (selector_source_path is None) == (selector_source_sha256 is None):
        raise ContractError(
            "exactly one pulse selector source path or frozen SHA-256 is required"
        )
    selector_sha256 = (
        repository_text_sha256(selector_source_path)
        if selector_source_path is not None
        else selector_source_sha256
    )
    contract_basis = copy.deepcopy(contract)
    for key in (
        "campaign_id", "experiment_id", "experiment_row_sha256",
        "resolved_source_contract_sha256", "resolved_population_contract_sha256",
    ):
        contract_basis["identities"].pop(key, None)
    population_basis = copy.deepcopy(population)
    for key in (
        "campaign_id", "experiment_id", "experiment_row_sha256",
        "population_declaration_sha256",
    ):
        population_basis.pop(key, None)
    population_basis.get("source_authority", {}).get("table", {}).pop("path", None)
    connection_basis = {
        key: copy.deepcopy(connection[key])
        for key in (
            "selection", "spatial_registration", "connector", "port_geometry",
            "transition_aperture", "effective_clear_radius_mm",
            "potential_alignment", "clock_alignment", "field_ownership_segments",
        )
    }
    basis = {
        "schema_version": 1,
        "role": "rf_oatof_detector_blind_pulse_selection_content_key_basis",
        "screening_contract_semantic_sha256": _canonical_sha256(contract_basis),
        "resolved_population_semantic_sha256": _canonical_sha256(population_basis),
        "resolved_source_semantic_sha256": _canonical_sha256(source),
        "resolved_connection_semantic_sha256": _canonical_sha256(connection_basis),
        "resolved_geometry_sha256": _canonical_sha256(geometry),
        "spatial_window_profile_sha256": _canonical_sha256(spatial_profile),
        "selector_source_sha256": selector_sha256,
    }
    return basis, _canonical_sha256(basis)


def _select_spatial_profile(configuration: dict[str, Any], profile_id: str) -> dict[str, Any]:
    if configuration.get("role") != "rf_oatof_simion_single_flight_configuration":
        raise ContractError("single-flight configuration identity differs")
    matches = [
        profile for profile in configuration.get("spatial_window_profiles", [])
        if profile.get("profile_id") == profile_id
    ]
    if len(matches) != 1:
        raise ContractError("real-field pulse spatial-window profile is not unique")
    return matches[0]


def select_and_write(
    *,
    state_table_path: Path,
    screening_contract_path: Path,
    screening_receipt_path: Path,
    resolved_population_path: Path,
    population_table_path: Path,
    resolved_source_path: Path,
    resolved_connection_path: Path,
    screening_manifest_path: Path,
    selector_source_path: Path,
    geometry_path: Path,
    single_flight_configuration_path: Path,
    ballistic_schedule_path: Path,
    candidate_table_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Validate frozen authorities, select one time, and write JSON/CSV evidence."""

    rows = _load_state_rows(state_table_path)
    contract = _load_object(screening_contract_path)
    selection_preregistered = _validate_screening_contract(contract)
    screening_receipt = _load_object(screening_receipt_path)
    _validate_screening_receipt(
        screening_receipt, contract=contract,
        contract_path=screening_contract_path,
        state_table_path=state_table_path,
    )
    population = _load_object(resolved_population_path)
    frozen_particle_ids = _load_population_ids(population, population_table_path)
    source = _load_object(resolved_source_path)
    if source.get("role") != "rf_multipole_oatof_source_contract":
        raise ContractError("real-field pulse source identity differs")
    connection = _load_object(resolved_connection_path)
    if (
        connection.get("role") != "resolved_connection_do_not_edit"
        or connection.get("selection", {}).get("connection_profile_id")
        != contract.get("identities", {}).get("connection_profile_id")
    ):
        raise ContractError("real-field pulse connection identity differs")
    geometry = _load_object(geometry_path)
    if geometry.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ContractError("real-field pulse timing geometry identity differs")
    configuration = _load_object(single_flight_configuration_path)
    schedule = _load_object(ballistic_schedule_path)
    if schedule.get("role") != "rf_oatof_resolved_single_flight_pulse_schedule":
        raise ContractError("real-field pulse ballistic schedule identity differs")
    profile = _select_spatial_profile(
        configuration,
        str(contract["identities"]["spatial_window_profile_id"]),
    )
    result = select_detector_blind_real_field_pulse_time(
        rows,
        geometry,
        profile,
        candidate_times_us=list(contract["sample_times_us"]),
        frozen_particle_ids=frozen_particle_ids,
        ballistic_seed_time_us=float(schedule["pulse_effective_time_us"]),
    )
    frozen_selection_order = contract.get("selection_order", SELECTION_ORDER)
    if result["selection_order"] != frozen_selection_order:
        raise ContractError("real-field pulse selection order differs from preregistration")

    content_key_basis, content_key = pulse_selection_content_identity(
        contract=contract, population=population, source=source,
        connection=connection, geometry=geometry, spatial_profile=profile,
        selector_source_path=selector_source_path,
    )

    candidate_rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(result["candidates_ranked"], start=1):
        candidate["rank"] = rank
        for prefix, key in (
            ("population", "frozen_particle_ids"),
            ("alive", "alive_particle_ids"),
            ("missing", "missing_particle_ids"),
            ("pulse_eligible", "pulse_eligible_ids"),
            ("pulse_noneligible", "pulse_noneligible_ids"),
            ("transverse_bore", "transverse_bore_ids"),
            ("transverse_nonbore", "transverse_nonbore_ids"),
            ("ideal_source_box", "ideal_source_box_ids"),
        ):
            candidate[f"{prefix}_identity"] = _observed_id_set(candidate[key])
        candidate_rows.append(candidate)

    candidate_table_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_table_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "rank", "sample_index", "candidate_time_us",
            "offset_from_ballistic_seed_us", "population_count", "alive_count",
            "missing_count", "pulse_eligible_count", "transverse_bore_count",
            "pulse_noneligible_count", "transverse_nonbore_count",
            "ideal_source_box_count", "normalized_xyz_centroid_distance",
            "normalized_xyz_spread_norm", "population_id_sha256",
            "alive_id_sha256", "missing_id_sha256", "pulse_eligible_id_sha256",
            "pulse_noneligible_id_sha256", "transverse_bore_id_sha256",
            "transverse_nonbore_id_sha256", "ideal_source_box_id_sha256",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for candidate in candidate_rows:
            writer.writerow({
                **{key: candidate[key] for key in fieldnames[:14]},
                "population_id_sha256": candidate["population_identity"][
                    "ordered_particle_id_sha256"
                ],
                "alive_id_sha256": candidate["alive_identity"][
                    "ordered_particle_id_sha256"
                ],
                "missing_id_sha256": candidate["missing_identity"][
                    "ordered_particle_id_sha256"
                ],
                "pulse_eligible_id_sha256": candidate["pulse_eligible_identity"][
                    "ordered_particle_id_sha256"
                ],
                "pulse_noneligible_id_sha256": candidate[
                    "pulse_noneligible_identity"
                ]["ordered_particle_id_sha256"],
                "transverse_bore_id_sha256": candidate["transverse_bore_identity"][
                    "ordered_particle_id_sha256"
                ],
                "transverse_nonbore_id_sha256": candidate[
                    "transverse_nonbore_identity"
                ]["ordered_particle_id_sha256"],
                "ideal_source_box_id_sha256": candidate["ideal_source_box_identity"][
                    "ordered_particle_id_sha256"
                ],
            })

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "role": "rf_oatof_detector_blind_real_field_pulse_timing_selection_receipt",
        "status": "success",
        "qualification": "candidate_selection",
        "selection_preregistered": selection_preregistered,
        "reusable_verified_pulse": False,
        "pulse_confirmation_status": "NOT_RUN",
        "claim_limit": "DETECTOR_BLIND_REAL_FIELD_PULSE_TIMING_ONLY",
        "selection_uses_detector_outcome": False,
        "detector_results_used": False,
        "detector_fields_present_in_state_table": False,
        "content_key": content_key,
        "content_key_basis": content_key_basis,
        "authorities": {
            name: _binding(path)
            for name, path in (
                ("real_field_state_table", state_table_path),
                ("pre_pulse_time_series_contract", screening_contract_path),
                ("pre_pulse_time_series_receipt", screening_receipt_path),
                ("resolved_population_contract", resolved_population_path),
                ("population_table", population_table_path),
                ("resolved_source_contract", resolved_source_path),
                ("resolved_connection", resolved_connection_path),
                ("screening_transport_manifest", screening_manifest_path),
                ("resolved_geometry", geometry_path),
                ("single_flight_configuration", single_flight_configuration_path),
                ("ballistic_pulse_schedule", ballistic_schedule_path),
            )
        },
        "selection_order": result["selection_order"],
        "ballistic_seed_time_us": result["ballistic_seed_time_us"],
        "selected_time_us": result["selected_time_us"],
        "population_denominator_count": result["population_denominator_count"],
        "ideal_source_box_bounds": result["ideal_source_box_bounds"],
        "candidates_ranked": candidate_rows,
        "sample_census": [
            {
                "sample_index": candidate["sample_index"],
                "candidate_time_us": candidate["candidate_time_us"],
                "population_count": candidate["population_count"],
                "alive": candidate["alive_identity"],
                "missing": candidate["missing_identity"],
            }
            for candidate in sorted(
                candidate_rows, key=lambda item: int(item["sample_index"])
            )
        ],
        "candidate_table": {
            "path": str(candidate_table_path.resolve()),
            "sha256": file_sha256(candidate_table_path),
            "row_count": len(candidate_rows),
        },
    }
    receipt["authorities"]["selector_source"] = _binding(
        selector_source_path, repository_text=True
    )
    validate_schema(
        receipt,
        "rf_oatof_detector_blind_pulse_timing_candidate_receipt.schema.json",
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
