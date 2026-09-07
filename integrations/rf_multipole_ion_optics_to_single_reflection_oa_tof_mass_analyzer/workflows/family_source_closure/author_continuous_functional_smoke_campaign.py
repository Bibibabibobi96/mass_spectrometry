"""Derive one immutable first-row continuous functional-smoke campaign.

This author is deliberately narrower than the pre-pulse-to-full-flight author:
it changes only the execution projection of one already-authoritative N=5000
continuous campaign.  The original mother authority remains embedded as
evidence; runtime selection is fixed to source particle ID 1.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    INTEGRATION_SCHEMA_DIR,
    RESOLVED_CAMPAIGN_SCHEMA_PATH,
    expand_flat_experiment_authoring,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MOTHER_COUNT = 5000
SMOKE_ID = 1
SMOKE_SELECTION = "first_n_rows_in_frozen_file_order"


def _load_campaign(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("continuous source campaign is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("continuous source campaign must be a JSON object")
    return value


def _require_full_mother(shared: dict[str, Any]) -> dict[str, Any]:
    population = shared.get("single_flight_population")
    if shared.get("source_release_mode") != "continuous_frontend" or not isinstance(population, dict):
        raise ContractError("source campaign is not a continuous full population")
    authority = population.get("source_authority")
    execution = population.get("execution_population")
    denominators = population.get("denominators")
    if not all(isinstance(value, dict) for value in (authority, execution, denominators)):
        raise ContractError("source campaign mother population is incomplete")
    if (
        population.get("population_mode")
        not in {"continuous_injection_full_population", "independent_spatial_velocity_ion_source_snapshot"}
        or authority.get("table_binding")
        not in {"source_contract_particle_source", "prepared_materialized_ion_source_volume"}
        or execution.get("particle_count") != MOTHER_COUNT
        or execution.get("selection_algorithm") != "all_rows_in_frozen_file_order"
        or execution.get("ordered_particle_id_sha256")
        != canonical_json_sha256(list(range(1, MOTHER_COUNT + 1)))
        or denominators.get("population_count") != MOTHER_COUNT
        or denominators.get("eligible_population_count") != MOTHER_COUNT
        or population.get("postselection_policy") != "prohibited"
    ):
        raise ContractError("source campaign is not the frozen ordered N=5000 mother")
    return population


def author_campaign(*, source_campaign_path: Path, experiment_id: str,
                    output_path: Path, campaign_id: str, workspace: Path) -> dict[str, Any]:
    """Write a one-row, non-overwriting ID-1 continuous functional smoke."""

    workspace = workspace.resolve()
    allowed_output_root = (
        workspace / "simulation_repo" / "integrations" / INTEGRATION_ID / "config" / "explorations"
    ).resolve()
    output = output_path.resolve()
    if not output.is_relative_to(allowed_output_root):
        raise ContractError("functional-smoke output must be under the repository config/explorations root")
    if output.exists():
        raise ContractError("functional-smoke campaign output already exists")
    if not campaign_id:
        raise ContractError("functional-smoke campaign_id is required")
    source = _load_campaign(source_campaign_path)
    if source.get("role") != "rf_multipole_oatof_experiment_campaign" or source.get("integration_id") != INTEGRATION_ID:
        raise ContractError("continuous source campaign identity differs")
    experiments = source.get("experiments")
    if not isinstance(experiments, dict) or set(experiments) != {"shared", "variation_axes", "rows"}:
        raise ContractError("continuous source campaign must use flat experiment authoring")
    shared = experiments.get("shared")
    rows = experiments.get("rows")
    if not isinstance(shared, dict) or not isinstance(rows, list):
        raise ContractError("continuous source campaign experiments are incomplete")
    mother = _require_full_mother(shared)
    if "pre_pulse_time_series_screening" in source:
        raise ContractError("functional-smoke source campaign must not carry pre-pulse screening")
    matches = [row for row in rows if isinstance(row, dict) and row.get("experiment_id") == experiment_id]
    if len(matches) != 1:
        raise ContractError("functional-smoke experiment must select exactly one source row")
    values = matches[0].get("values")
    if not isinstance(values, dict):
        raise ContractError("functional-smoke source row values are incomplete")
    comparator = values.get("continuous_full_flight_comparator_authority")
    if not isinstance(comparator, dict):
        raise ContractError("functional-smoke source row lacks a full-mother comparator authority")

    result = copy.deepcopy(source)
    result["campaign_id"] = campaign_id
    result["status"] = "exploration"
    result["claim_limit"] = (
        "FUNCTIONAL_SMOKE_ONLY. One fixed first row of the frozen ordered N=5000 "
        "continuous mother validates runtime plumbing only; it grants no transport, "
        "resolution, aperture-comparison, or population claim."
    )
    result_shared = copy.deepcopy(shared)
    smoke_population = copy.deepcopy(mother)
    smoke_population["population_id"] = mother["population_id"] + "_first_row_functional_smoke_n1"
    smoke_population["population_mode"] = "first_n_rows_in_frozen_file_order"
    smoke_population["source_authority"] = {
        "input_role": mother["source_authority"]["input_role"],
        "table_binding": "prepared_deterministic_prefix",
        "ordered_particle_id_encoding": mother["source_authority"]["ordered_particle_id_encoding"],
    }
    smoke_population["execution_population"] = {
        "particle_count": 1,
        "ordered_particle_id_sha256": canonical_json_sha256([SMOKE_ID]),
        "selection_algorithm": SMOKE_SELECTION,
        "selection_seed": 0,
    }
    # Keep the N=5000 denominator: the one trajectory is an execution smoke,
    # never an estimate of a one-ion physical population.
    smoke_population["denominators"] = copy.deepcopy(mother["denominators"])
    result_shared["single_flight_population"] = smoke_population
    result_shared["continuous_functional_smoke_authority"] = {
        "source_campaign": {
            "path": str(source_campaign_path.resolve().relative_to(workspace)).replace("\\", "/"),
            "sha256": file_sha256(source_campaign_path),
        },
        "mother_population": copy.deepcopy(mother),
        "execution_selection": {
            "source_experiment_id": experiment_id,
            "source_particle_id": SMOKE_ID,
            "selection_algorithm": SMOKE_SELECTION,
            "ordered_particle_id_sha256": canonical_json_sha256([SMOKE_ID]),
        },
    }
    result_shared["continuous_functional_smoke_pulse_authority"] = {
        "mother_population": copy.deepcopy(mother),
        "continuous_full_flight_comparator_authority": copy.deepcopy(comparator),
    }
    smoke_values = copy.deepcopy(values)
    smoke_values.pop("continuous_full_flight_comparator_authority")
    result["experiments"] = {
        "shared": result_shared,
        "variation_axes": list(experiments["variation_axes"]),
        "rows": [{
            "experiment_id": experiment_id.replace("_n5000", "_functional_smoke_n1"),
            "values": smoke_values,
        }],
    }
    validate_schema(result, INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_experiment_campaign.schema.json")
    validate_schema(expand_flat_experiment_authoring(result), RESOLVED_CAMPAIGN_SCHEMA_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaign", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    result = author_campaign(source_campaign_path=args.source_campaign, experiment_id=args.experiment_id,
                             output_path=args.output, campaign_id=args.campaign_id,
                             workspace=args.workspace)
    print("CONTINUOUS_FUNCTIONAL_SMOKE_CAMPAIGN_AUTHORED=PASS " + json.dumps({
        "campaign_id": result["campaign_id"], "row_count": 1,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
