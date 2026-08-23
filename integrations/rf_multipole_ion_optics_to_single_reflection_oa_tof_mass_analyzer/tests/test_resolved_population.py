from __future__ import annotations

import unittest

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_population import (
    compile_resolved_population_contract,
)


SHA = "A" * 64
TABLE_SHA = "B" * 64
MODE_CONTRACTS = {
    "staged_three_stage": (
        "staged_three_stage",
        None,
        "particle_source",
        "staged_upstream_source",
        "all_rows_in_frozen_file_order",
        "prohibited",
    ),
    "continuous_injection_full_population": (
        "simion_single_flight",
        "continuous_frontend",
        "particle_source",
        "source_contract_particle_source",
        "all_rows_in_frozen_file_order",
        "prohibited",
    ),
    "resolved_layout_pulse_ideal_linear_z_vz": (
        "simion_single_flight",
        "continuous_frontend",
        "single_flight_materialized_particle_source",
        "prepared_materialized_particle_source",
        "all_rows_in_frozen_file_order",
        "prohibited",
    ),
    "pre_pulse_restart": (
        "simion_single_flight",
        "pre_pulse_restart",
        "pre_pulse_source_state",
        "experiment_pre_pulse_source_state",
        "all_rows_in_frozen_file_order",
        "prohibited",
    ),
    "pulse_eligible_conditional": (
        "simion_single_flight",
        "continuous_frontend",
        "single_flight_particle_source",
        "experiment_single_flight_particle_source",
        "all_rows_in_frozen_file_order",
        "pulse_eligibility_only",
    ),
    "first_100_rows_in_frozen_file_order": (
        "simion_single_flight",
        "continuous_frontend",
        "single_flight_particle_source",
        "prepared_deterministic_prefix",
        "first_100_rows_in_frozen_file_order",
        "prohibited",
    ),
    "first_n_rows_in_frozen_file_order": (
        "simion_single_flight",
        "continuous_frontend",
        "single_flight_particle_source",
        "prepared_deterministic_prefix",
        "first_n_rows_in_frozen_file_order",
        "prohibited",
    ),
}


def declaration(mode: str) -> dict[str, object]:
    _, _, input_role, table_binding, selection, postselection = MODE_CONTRACTS[mode]
    return {
        "population_id": "fixture_population",
        "population_mode": mode,
        "source_authority": {
            "input_role": input_role,
            "table_binding": table_binding,
            "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1",
        },
        "execution_population": {
            "particle_count": 10,
            "ordered_particle_id_sha256": SHA,
            "selection_algorithm": selection,
            "selection_seed": 0,
        },
        "denominators": {
            "population_count": 10,
            "eligible_population_count": 10,
        },
        "analysis_randomness": {
            "bootstrap_resample_count": 0,
            "bootstrap_seed": 20260812,
        },
        "postselection_policy": postselection,
    }


def source_table(mode: str) -> dict[str, object]:
    _, _, input_role, table_binding, _, _ = MODE_CONTRACTS[mode]
    return {
        "input_role": input_role,
        "table_binding": table_binding,
        "table": {"path": "fixtures/source.csv", "sha256": TABLE_SHA},
        "particle_count": 10,
        "ordered_particle_ids": {
            "encoding": "canonical_compact_json_integer_array_v1",
            "sha256": SHA,
        },
    }


class ResolvedPopulationTests(unittest.TestCase):
    def compile(self, mode: str, *, declared=None, observed=None):
        execution_strategy, release_mode, *_ = MODE_CONTRACTS[mode]
        return compile_resolved_population_contract(
            campaign_id="fixture_campaign",
            experiment_id="fixture_experiment",
            experiment_row_sha256="C" * 64,
            population_declaration_sha256="D" * 64,
            execution_strategy=execution_strategy,
            source_release_mode=release_mode,
            declaration=declared or declaration(mode),
            source_table=observed or source_table(mode),
        )

    def test_each_population_mode_accepts_only_its_canonical_tuple(self):
        for mode, expected in MODE_CONTRACTS.items():
            with self.subTest(mode=mode):
                result = self.compile(mode)
                self.assertEqual(result["population_mode"], mode)
                self.assertEqual(result["execution_strategy"], expected[0])
                self.assertEqual(result.get("source_release_mode"), expected[1])
                self.assertEqual(result["execution_population"]["particle_count"], 10)
                self.assertEqual(result["source_authority"]["ordered_particle_ids"]["sha256"], SHA)

    def test_cross_mode_tuple_substitutions_fail_closed(self):
        mode = "continuous_injection_full_population"
        for field, value in (
            ("table_binding", "prepared_materialized_particle_source"),
        ):
            declared = declaration(mode)
            observed = source_table(mode)
            declared["source_authority"][field] = value
            observed[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.compile(mode, declared=declared, observed=observed)
        for field, value in (
            ("selection_algorithm", "first_100_rows_in_frozen_file_order"),
            ("postselection_policy", "pulse_eligibility_only"),
        ):
            declared = declaration(mode)
            if field == "selection_algorithm":
                declared["execution_population"][field] = value
            else:
                declared[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.compile(mode, declared=declared)

    def test_release_and_execution_mode_substitutions_fail_closed(self):
        declared = declaration("continuous_injection_full_population")
        observed = source_table("continuous_injection_full_population")
        for execution_strategy, release_mode in (
            ("staged_three_stage", "continuous_frontend"),
            ("simion_single_flight", "pre_pulse_restart"),
        ):
            with self.subTest(
                execution_strategy=execution_strategy, release_mode=release_mode
            ), self.assertRaises(ContractError):
                compile_resolved_population_contract(
                    campaign_id="fixture_campaign",
                    experiment_id="fixture_experiment",
                    experiment_row_sha256="C" * 64,
                    population_declaration_sha256="D" * 64,
                    execution_strategy=execution_strategy,
                    source_release_mode=release_mode,
                    declaration=declared,
                    source_table=observed,
                )

    def test_source_count_is_cross_check_not_fallback(self):
        observed = source_table("continuous_injection_full_population")
        observed["particle_count"] = 9
        with self.assertRaisesRegex(ContractError, "count differs"):
            self.compile("continuous_injection_full_population", observed=observed)

    def test_ordered_identity_mismatch_fails_closed(self):
        observed = source_table("continuous_injection_full_population")
        observed["ordered_particle_ids"]["sha256"] = "D" * 64
        with self.assertRaisesRegex(ContractError, "identity differs"):
            self.compile("continuous_injection_full_population", observed=observed)

    def test_source_role_and_binding_mismatches_fail_closed(self):
        for key, value in (
            ("input_role", "wrong_role"),
            ("table_binding", "prepared_materialized_particle_source"),
        ):
            observed = source_table("continuous_injection_full_population")
            observed[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.compile("continuous_injection_full_population", observed=observed)

    def test_denominator_ordering_fails_closed(self):
        declared = declaration("pulse_eligible_conditional")
        declared["denominators"] = {
            "population_count": 9,
            "eligible_population_count": 8,
        }
        with self.assertRaisesRegex(ContractError, "denominator ordering"):
            self.compile("pulse_eligible_conditional", declared=declared)

    def test_missing_seed_is_rejected_by_schema(self):
        declared = declaration("continuous_injection_full_population")
        del declared["analysis_randomness"]["bootstrap_seed"]
        with self.assertRaises(ContractError):
            self.compile("continuous_injection_full_population", declared=declared)


if __name__ == "__main__":
    unittest.main()
