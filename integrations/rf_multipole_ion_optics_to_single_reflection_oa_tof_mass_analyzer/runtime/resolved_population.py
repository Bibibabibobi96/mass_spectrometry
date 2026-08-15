"""Compile the sole single-flight population authority from explicit inputs."""

from __future__ import annotations

from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema


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
    source_release_validation: dict[str, Any] | None = None,
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
    if source_release_validation is not None:
        contract["source_release_validation"] = source_release_validation
    validate_schema(contract, "rf_oatof_resolved_population_contract.schema.json")
    return contract
