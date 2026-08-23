"""Compile the sole single-flight population authority from explicit inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema


RESOLVED_POPULATION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "schemas" /
    "rf_oatof_resolved_population_contract.schema.json"
)

_SINGLE_FLIGHT_EXECUTION_BY_POPULATION_MODE = {
    "continuous_injection_full_population": {
        "population_basis": "candidate_full_population",
        "requires_eligible_population": False,
        "is_pre_pulse_restart": False,
    },
    "resolved_layout_pulse_ideal_linear_z_vz": {
        "population_basis": "candidate_full_population",
        "requires_eligible_population": False,
        "is_pre_pulse_restart": False,
    },
    "pulse_eligible_conditional": {
        "population_basis": "pulse_eligible_conditional_population",
        "requires_eligible_population": True,
        "is_pre_pulse_restart": False,
    },
    "pre_pulse_restart": {
        "population_basis": "source_contract_population",
        "requires_eligible_population": False,
        "is_pre_pulse_restart": True,
    },
    "first_100_rows_in_frozen_file_order": {
        "population_basis": "candidate_full_population",
        "requires_eligible_population": False,
        "is_pre_pulse_restart": False,
    },
    "first_n_rows_in_frozen_file_order": {
        "population_basis": "candidate_full_population",
        "requires_eligible_population": False,
        "is_pre_pulse_restart": False,
    },
}


def resolve_single_flight_execution(
    population_mode: str, source_release_mode: str | None
) -> dict[str, Any]:
    """Compile runner-consumed sampling semantics from the declared population mode."""

    try:
        execution = _SINGLE_FLIGHT_EXECUTION_BY_POPULATION_MODE[population_mode].copy()
    except KeyError as exc:
        raise ContractError(
            f"population mode is not supported by the single-flight runner: {population_mode}"
        ) from exc
    if execution["is_pre_pulse_restart"] != (source_release_mode == "pre_pulse_restart"):
        raise ContractError(
            "population mode and source release mode differ for single-flight execution"
        )
    return execution


def compile_resolved_population_contract(
    *,
    campaign_id: str,
    experiment_id: str,
    experiment_row_sha256: str,
    population_declaration_sha256: str,
    execution_strategy: str,
    source_release_mode: str | None,
    declaration: dict[str, Any],
    source_table: dict[str, Any],
    contract_schema_version: int = 1,
    paired_cohort_authority: dict[str, Any] | None = None,
    cohort_authority_mode: str | None = None,
) -> dict[str, Any]:
    """Return one validated population contract; observed source data only cross-checks."""

    execution = declaration["execution_population"]
    authority = declaration["source_authority"]
    ordered_ids = source_table["ordered_particle_ids"]
    if source_table["input_role"] != authority["input_role"]:
        raise ContractError("population source input role differs from declaration")
    if source_table["table_binding"] != authority["table_binding"]:
        raise ContractError("population source table binding differs from declaration")
    if ordered_ids["encoding"] != authority["ordered_particle_id_encoding"]:
        raise ContractError("population ordered-particle encoding differs from declaration")
    if int(source_table["particle_count"]) != int(execution["particle_count"]):
        raise ContractError("population source count differs from declaration")
    if ordered_ids["sha256"] != execution["ordered_particle_id_sha256"]:
        raise ContractError("population ordered-particle identity differs from declaration")
    declared_denominators = declaration.get("denominators")
    if paired_cohort_authority is not None:
        population_count = len(
            paired_cohort_authority["source_release"]["ordered_particle_ids"]
        )
        eligible_count = len(
            paired_cohort_authority["pulse_eligible"]["ordered_particle_ids"]
        )
        denominators = {
            "population_count": population_count,
            "pre_pulse_state_count": len(
                paired_cohort_authority["pre_pulse_state"]["ordered_particle_ids"]
            ),
            "eligible_population_count": eligible_count,
            "outside_transverse_bore_count": len(
                paired_cohort_authority[
                    "outside_transverse_bore"
                ]["ordered_particle_ids"]
            ),
            "derivation": "frozen_ordered_particle_id_membership",
        }
    elif cohort_authority_mode == "establish_observed_authority":
        if declared_denominators is not None:
            raise ContractError(
                "baseline observed cohort cannot predeclare event denominators"
            )
        population_count = int(execution["particle_count"])
        eligible_count = population_count
        denominators = {
            "population_count": population_count,
            "derivation": "event_membership_observed_during_analysis",
        }
    else:
        if declared_denominators is None:
            raise ContractError("population denominators are missing")
        denominators = declared_denominators
        population_count = int(denominators["population_count"])
        eligible_count = int(denominators["eligible_population_count"])
    execution_count = int(execution["particle_count"])
    if (
        population_count < execution_count
        or population_count < eligible_count
        or (
            declaration["population_mode"] == "pulse_eligible_conditional"
            and eligible_count < execution_count
        )
    ):
        raise ContractError("population denominator ordering differs from declaration")

    contract = {
        "schema_version": contract_schema_version,
        "role": "rf_oatof_resolved_population_contract",
        "campaign_id": campaign_id,
        "experiment_id": experiment_id,
        "experiment_row_sha256": experiment_row_sha256,
        "population_declaration_sha256": population_declaration_sha256,
        "execution_strategy": execution_strategy,
        "population_id": declaration["population_id"],
        "population_mode": declaration["population_mode"],
        "source_authority": source_table,
        "execution_population": execution,
        "denominators": denominators,
        "analysis_randomness": declaration["analysis_randomness"],
        "postselection_policy": declaration["postselection_policy"],
    }
    if paired_cohort_authority is not None:
        source_ids = paired_cohort_authority["source_release"]["ordered_particle_ids"]
        pre_pulse_ids = paired_cohort_authority["pre_pulse_state"]["ordered_particle_ids"]
        eligible_ids = paired_cohort_authority["pulse_eligible"]["ordered_particle_ids"]
        outside_ids = paired_cohort_authority["outside_transverse_bore"]["ordered_particle_ids"]
        if (
            len(source_ids) != population_count
            or set(pre_pulse_ids) != set(eligible_ids) | set(outside_ids)
            or set(eligible_ids) & set(outside_ids)
            or not set(pre_pulse_ids).issubset(source_ids)
        ):
            raise ContractError("paired cohort membership differs from population authority")
        contract["paired_cohort_authority"] = paired_cohort_authority
    if cohort_authority_mode is not None:
        contract["cohort_authority_mode"] = cohort_authority_mode
    if source_release_mode is not None:
        contract["source_release_mode"] = source_release_mode
    if contract_schema_version >= 2 and execution_strategy == "simion_single_flight":
        contract["single_flight_execution"] = resolve_single_flight_execution(
            declaration["population_mode"], source_release_mode
        )
    validate_schema(contract, RESOLVED_POPULATION_SCHEMA_PATH)
    return contract
