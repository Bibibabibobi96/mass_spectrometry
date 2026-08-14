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
    denominators = declaration["denominators"]
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
        "schema_version": 1,
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
        "denominators": declaration["denominators"],
        "analysis_randomness": declaration["analysis_randomness"],
        "postselection_policy": declaration["postselection_policy"],
    }
    if source_release_mode is not None:
        contract["source_release_mode"] = source_release_mode
    validate_schema(contract, "rf_oatof_resolved_population_contract.schema.json")
    return contract
