"""Select a real-field pulse leading edge from a preregistered state-time grid."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import (
    canonical_json_sha256 as _canonical_sha256,
    file_sha256,
    repository_text_sha256,
)
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
    _observed_id_set,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pulse_reuse_identity_projection import (
    build_verified_pulse_reuse_projection,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    open_pre_pulse_state_table,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    _natural_archive_ids,
    select_detector_blind_real_field_pulse_time,
    select_detector_blind_natural_archive_pulse_time,
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
INTEGRATION_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "config" / "schemas"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _load_state_rows(path: Path) -> list[dict[str, str]]:
    rows = list(_iter_state_rows(path))
    if not rows:
        raise ContractError("real-field pulse state table is empty")
    return rows


def _iter_state_rows(path: Path):
    """Yield validated detector-blind rows without materializing the archive."""
    with open_pre_pulse_state_table(path) as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        if not REQUIRED_STATE_COLUMNS.issubset(columns):
            raise ContractError("real-field pulse state table is missing required columns")
        if columns - ALLOWED_STATE_COLUMNS:
            raise ContractError("real-field pulse state table contains forbidden columns")
        for row in reader:
            if any(
                "detector" in str(value).casefold()
                for value in row.values() if value is not None
            ):
                raise ContractError("real-field pulse state table contains detector outcomes")
            yield row


def _validate_detector_blind_state_table(path: Path) -> None:
    """Fail before authority processing if a state archive contains detector data."""
    if not any(True for _ in _iter_state_rows(path)):
        raise ContractError("real-field pulse state table is empty")


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
        != "layout_resolved_axial_provisional_xy2_v1"
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
    keys = receipt.get("pa_cache_keys", {})
    schema_version = contract.get("schema_version")
    if schema_version == 2:
        required = ("frontend", "accelerator_overlay")
    elif schema_version == 3:
        required = (
            "frontend",
            "accelerator_entrance_overlay",
            "accelerator_intermediate_overlay",
        )
    elif schema_version in {5, 6, 7}:
        required = ("fine_upstream", "accelerator_entrance_zone_collision")
    else:
        required = ()
    if required and (
        set(keys) != {*required, "flight_tube", "reflectron"}
        or any(not isinstance(keys.get(role), str) for role in required)
        or keys.get("flight_tube") is not None
        or keys.get("reflectron") is not None
    ):
        raise ContractError("pre-pulse screening PA cache roles differ")


def pulse_selection_content_identity(
    *, contract: dict[str, Any], source: dict[str, Any],
    connection: dict[str, Any], geometry: dict[str, Any],
    spatial_profile: dict[str, Any], selector_source_path: Path | None = None,
    selector_source_sha256: str | None = None,
    pa_cache_keys: dict[str, Any] | None = None,
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
        "mother_particle_source_sha256", "ordered_particle_id_sha256",
    ):
        contract_basis["identities"].pop(key, None)
    connection_basis = {
        key: copy.deepcopy(connection[key])
        for key in (
            "selection", "spatial_registration", "connector", "port_geometry",
            "transition_aperture", "effective_clear_radius_mm",
            "potential_alignment", "clock_alignment", "field_ownership_segments",
        )
    }
    basis = {
        "schema_version": 2,
        "role": "rf_oatof_detector_blind_pulse_selection_content_key_basis",
        "screening_contract_semantic_sha256": _canonical_sha256(contract_basis),
        "resolved_source_semantic_sha256": _canonical_sha256(source),
        "resolved_connection_semantic_sha256": _canonical_sha256(connection_basis),
        "resolved_geometry_sha256": _canonical_sha256(geometry),
        "spatial_window_profile_sha256": _canonical_sha256(spatial_profile),
        "selector_source_sha256": selector_sha256,
    }
    if contract.get("schema_version") in (2, 3) and pa_cache_keys is None:
        raise ContractError("actual PA cache keys are required for PA-backed pulse selection")
    if contract.get("schema_version") in (2, 3):
        basis["pa_cache_keys"] = copy.deepcopy(pa_cache_keys)
    return basis, _canonical_sha256(basis)


def verified_pulse_reuse_content_identity(
    candidate_basis: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return the physics-only identity for a full-flight-verified pulse."""
    basis = copy.deepcopy(candidate_basis)
    basis["schema_version"] = 1
    basis["role"] = "rf_oatof_verified_pulse_reuse_content_key_basis"
    basis.pop("selector_source_sha256", None)
    return basis, _canonical_sha256(basis)


def _select_source_region_profile(
    configuration: dict[str, Any], profile_id: str,
) -> dict[str, Any]:
    if configuration.get("role") != "rf_oatof_simion_single_flight_configuration":
        raise ContractError("single-flight configuration identity differs")
    matches = [
        profile
        for profile in configuration.get("source_region_diagnostic_profiles", [])
        if profile.get("profile_id") == profile_id
    ]
    if len(matches) != 1:
        raise ContractError("real-field pulse source-region profile is not unique")
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

    _validate_detector_blind_state_table(state_table_path)
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
    profile = _select_source_region_profile(
        configuration,
        str(contract["identities"]["spatial_window_profile_id"]),
    )
    grid = contract.get("rf_time_grid", {})
    natural_archive = contract.get("schema_version") == 7
    ballistic_seed_time_us = (
        float(grid["source_ballistic_seed_time_us"])
        if contract.get("schema_version") == 6
        else float(schedule["pulse_effective_time_us"])
    )
    if natural_archive:
        try:
            grid_origin_us = float(grid["grid_origin_us"])
            grid_step_us = float(grid["step_us"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("natural pre-pulse state grid is invalid") from exc
        result = select_detector_blind_natural_archive_pulse_time(
            _iter_state_rows(state_table_path), geometry, profile,
            frozen_particle_ids=frozen_particle_ids,
            ballistic_seed_time_us=ballistic_seed_time_us,
            grid_origin_us=grid_origin_us, grid_step_us=grid_step_us,
        )
    else:
        result = select_detector_blind_real_field_pulse_time(
            _load_state_rows(state_table_path), geometry, profile,
            candidate_times_us=list(contract["sample_times_us"]),
            frozen_particle_ids=frozen_particle_ids,
            ballistic_seed_time_us=ballistic_seed_time_us,
        )
    frozen_selection_order = contract.get("selection_order", SELECTION_ORDER)
    if result["selection_order"] != frozen_selection_order:
        raise ContractError("real-field pulse selection order differs from preregistration")

    content_key_basis, content_key = pulse_selection_content_identity(
        contract=contract, source=source,
        connection=connection, geometry=geometry, spatial_profile=profile,
        selector_source_path=selector_source_path,
        pa_cache_keys=screening_receipt.get("pa_cache_keys"),
    )
    verified_reuse_basis = None
    verified_reuse_key = None
    reuse_pa_keys = screening_receipt.get("pa_cache_keys")
    if contract.get("schema_version") in (2, 3, 4, 5) and isinstance(reuse_pa_keys, dict):
        verified_reuse_basis, verified_reuse_key = (
            build_verified_pulse_reuse_projection(
                screening_contract=contract,
                resolved_source=source,
                resolved_connection=connection,
                resolved_geometry=geometry,
                spatial_profile=profile,
                pa_cache_keys=reuse_pa_keys,
            )
        )

    candidate_rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(result["candidates_ranked"], start=1):
        candidate["rank"] = rank
        masks = candidate.pop("_natural_id_masks", None)
        for prefix, key in (
            ("population", "frozen_particle_ids"),
            ("alive", "alive_particle_ids"),
            ("missing", "missing_particle_ids"),
            ("pulse_eligible", "pulse_eligible_ids"),
            ("pulse_noneligible", "pulse_noneligible_ids"),
            ("transverse_bore", "transverse_bore_ids"),
            ("transverse_nonbore", "transverse_nonbore_ids"),
            ("source_region", "source_region_ids"),
        ):
            ids = (
                _natural_archive_ids(masks[key], frozen_particle_ids)
                if isinstance(masks, dict) else candidate[key]
            )
            candidate[f"{prefix}_identity"] = _observed_id_set(ids)
            # The compact natural receipt needs raw IDs only for its selected
            # handoff candidate.  Other candidate rows retain compact hashes.
            if masks is None or rank == 1:
                candidate[key] = ids
        candidate_rows.append(candidate)

    candidate_table_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_table_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "rank", "sample_index", "candidate_time_us",
            "offset_from_ballistic_seed_us", "population_count", "alive_count",
            "missing_count", "pulse_eligible_count", "transverse_bore_count",
            "pulse_noneligible_count", "transverse_nonbore_count",
            "source_region_count", "normalized_xyz_centroid_distance",
            "normalized_xyz_spread_norm", "population_id_sha256",
            "alive_id_sha256", "missing_id_sha256", "pulse_eligible_id_sha256",
            "pulse_noneligible_id_sha256", "transverse_bore_id_sha256",
            "transverse_nonbore_id_sha256", "source_region_id_sha256",
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
                "source_region_id_sha256": candidate["source_region_identity"][
                    "ordered_particle_id_sha256"
                ],
            })

    contract_schema_version = int(contract.get("schema_version") or 2)
    # A natural archive can contain tens of thousands of RF-grid samples for
    # every member of a 5,000-particle mother cohort.  The CSV below preserves
    # the complete detector-blind candidate census as counts and identities;
    # duplicating every per-particle candidate list inside the JSON receipt is
    # not evidence required to reproduce a later policy.  Keep the selected
    # candidate in the receipt (the handoff authority) and rederive any other
    # ranking from the immutable raw archive when a new pulse policy is used.
    compact_natural_receipt = contract_schema_version >= 7
    receipt_candidates = (
        [candidate_rows[0]] if compact_natural_receipt else candidate_rows
    )
    receipt_sample_census = (
        [
            {
                "sample_index": candidate_rows[0]["sample_index"],
                "candidate_time_us": candidate_rows[0]["candidate_time_us"],
                "population_count": candidate_rows[0]["population_count"],
                "alive": candidate_rows[0]["alive_identity"],
                "missing": candidate_rows[0]["missing_identity"],
            }
        ]
        if compact_natural_receipt
        else [
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
        ]
    )
    receipt: dict[str, Any] = {
        "schema_version": 5 if contract_schema_version >= 5 else (
            4 if contract_schema_version == 4 else (
            3 if contract_schema_version == 3 else 2
            )
        ),
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
        "source_region_bounds": result["source_region_bounds"],
        "candidates_ranked": receipt_candidates,
        "sample_census": receipt_sample_census,
        "candidate_table": {
            "path": str(candidate_table_path.resolve()),
            "sha256": file_sha256(candidate_table_path),
            "row_count": len(candidate_rows),
        },
    }
    if verified_reuse_key is not None:
        receipt["verified_reuse_content_key"] = verified_reuse_key
        receipt["verified_reuse_content_key_basis"] = verified_reuse_basis
    if contract.get("schema_version") in (2, 3, 4, 5, 6, 7):
        receipt["pa_cache_keys"] = copy.deepcopy(screening_receipt["pa_cache_keys"])
    receipt["authorities"]["selector_source"] = _binding(
        selector_source_path, repository_text=True
    )
    validate_schema(
        receipt,
        INTEGRATION_SCHEMA_DIR / "rf_oatof_detector_blind_pulse_timing_candidate_receipt.schema.json",
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
