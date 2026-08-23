from __future__ import annotations

import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.fixtures.campaign_fixture import (
    current_campaign_fixture,
)


SHA = "A" * 64


def campaign() -> dict[str, object]:
    source = {
        "run_id": "20260814_000000__sim__simion__fixture-gap0__n10",
        "launched_particle_count": 100,
        "particle_source_manifest_input_role": "simion_particle_source",
        "manifest": {"path": "fixture/manifest.json", "sha256": SHA},
        "state": {"path": "fixture/state.csv", "sha256": SHA},
        "particle_source": {"path": "fixture/source.csv", "sha256": SHA},
        "metadata": {"path": "fixture/metadata.json", "sha256": SHA},
    }
    return current_campaign_fixture({
        "schema_version": 3,
        "role": "rf_multipole_oatof_experiment_campaign",
        "integration_id": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
        "campaign_id": "fixture_v3_campaign",
        "status": "authorized",
        "execution_policy": {"path": "fixture/policy.json", "sha256": SHA},
        "claim_limit": "fixture",
        "experiments": [{
            "sequence": 1,
            "experiment_id": "fixture_experiment",
            "execution_strategy": "simion_single_flight",
            "single_flight_layout_profile_id": "fixture_layout",
            "architecture_generation_id": "fixture_architecture",
            "source_profile_id": "fixture_source",
            "field_overlay_id": "fixture_field",
            "source_release_mode": "continuous_frontend",
            "single_flight_pulse_schedule_policy": {
                "policy_id": "multipole_handoff_ballistic_centroid_v1",
                "offset_rf_periods": 0.0,
                "pulse_width_us": 1.0,
            },
            "single_flight_population": {
                "population_id": "fixture_population",
                "population_mode": "continuous_injection_full_population",
                "source_authority": {
                    "input_role": "particle_source",
                    "table_binding": "source_contract_particle_source",
                    "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1",
                },
                "execution_population": {
                    "particle_count": 10,
                    "ordered_particle_id_sha256": SHA,
                    "selection_algorithm": "all_rows_in_frozen_file_order",
                    "selection_seed": 0,
                },
                "denominators": {"population_count": 10, "eligible_population_count": 10},
                "analysis_randomness": {"bootstrap_resample_count": 0, "bootstrap_seed": 1},
                "postselection_policy": "prohibited",
            },
            "connection_profile_id": "fixture_connection",
            "run_id": "20260814_000000__sim__simion__fixture-gap0__n10",
            "source": source,
        }],
    })


class CampaignV3ContractTests(unittest.TestCase):
    def test_complete_v3_single_flight_is_valid(self):
        validate_schema(campaign(), "rf_multipole_oatof_experiment_campaign.schema.json")

    def test_campaign_execution_policy_is_legacy_optional(self):
        value = campaign()
        del value["execution_policy"]
        validate_schema(value, "rf_multipole_oatof_experiment_campaign.schema.json")

    def test_source_population_size_is_not_a_profile_enum(self):
        value = campaign()
        value["experiments"][0]["source"]["launched_particle_count"] = 101
        validate_schema(value, "rf_multipole_oatof_experiment_campaign.schema.json")
        value["experiments"][0]["source"]["launched_particle_count"] = 0
        with self.assertRaises(ContractError):
            validate_schema(value, "rf_multipole_oatof_experiment_campaign.schema.json")

    def test_v3_forbids_legacy_scalar_pulse_offset(self):
        value = campaign()
        value["experiments"][0]["single_flight_pulse_offset_rf_periods"] = 0.0
        with self.assertRaises(ContractError):
            validate_schema(value, "rf_multipole_oatof_experiment_campaign.schema.json")

    def test_v3_requires_each_single_flight_authority(self):
        for key in (
            "source_release_mode",
            "single_flight_pulse_schedule_policy",
            "single_flight_population",
        ):
            value = campaign()
            del value["experiments"][0][key]
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_schema(value, "rf_multipole_oatof_experiment_campaign.schema.json")

    def test_population_mode_rejects_cross_mode_tuple_substitution(self):
        mutations = (
            ("source_release_mode", "pre_pulse_restart"),
            ("execution_strategy", "staged_three_stage"),
            ("table_binding", "prepared_materialized_particle_source"),
            ("selection_algorithm", "first_100_rows_in_frozen_file_order"),
            ("postselection_policy", "pulse_eligibility_only"),
        )
        for field, replacement in mutations:
            value = campaign()
            row = value["experiments"][0]
            population = row["single_flight_population"]
            if field in {"source_release_mode", "execution_strategy"}:
                row[field] = replacement
            elif field == "table_binding":
                population["source_authority"][field] = replacement
            elif field == "selection_algorithm":
                population["execution_population"][field] = replacement
            else:
                population[field] = replacement
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_schema(
                    value, "rf_multipole_oatof_experiment_campaign.schema.json"
                )


if __name__ == "__main__":
    unittest.main()
