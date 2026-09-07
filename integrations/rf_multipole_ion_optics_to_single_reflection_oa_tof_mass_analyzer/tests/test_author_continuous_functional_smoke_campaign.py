"""Regression tests for the immutable continuous first-row smoke author."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import canonical_json_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_continuous_functional_smoke_campaign import author_campaign
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _population_source_table,
    _resolve_functional_smoke_pulse_schedule,
    _validate_continuous_functional_smoke_authority,
    compile_resolved_population_contract,
    expand_flat_experiment_authoring,
    write_pulse_resolution_screening_prefix,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_population import resolve_runtime_population


class ContinuousFunctionalSmokeAuthorTests(unittest.TestCase):
    @staticmethod
    def _comparator() -> dict[str, object]:
        file_record = {"path": "artifact/input.json", "sha256": "F" * 64}
        return {
            "authority_mode": "manifest_bound_continuous_full_flight_comparator_v1",
            "pre_pulse_producer_manifest": file_record,
            "pre_pulse_mother_particle_source": file_record,
            "compact_receipt": file_record,
            "producer_manifest": file_record,
            "producer_frozen_experiment": file_record,
            "producer_pulse_schedule": file_record,
            "producer_configuration": file_record,
            "producer_region_field_contract": file_record,
            "producer_frontend_grid_profile_id": "frontend",
        }

    def _source(self, workspace: Path) -> Path:
        document = {
            "schema_version": 7, "role": "rf_multipole_oatof_experiment_campaign",
            "integration_id": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
            "campaign_id": "source", "status": "exploration", "claim_limit": "test",
            "experiments": {"shared": {
                "execution_strategy": "simion_single_flight", "source_release_mode": "continuous_frontend",
                "connection_profile_id": "connection", "single_flight_layout_profile_id": "layout",
                "single_flight_pa_cache_policy": "build_and_publish_if_missing",
                "source": {
                    "run_id": "source", "launched_particle_count": 5000,
                    "particle_count_binding": {"mode": "derive_from_frozen_source_state_v1", "selector": {"event": "handoff", "status": "transmitted"}},
                    "particle_source_manifest_input_role": "particle_source",
                    "manifest": {"path": "artifact/manifest.json", "sha256": "A" * 64},
                    "state": {"path": "artifact/state.csv", "sha256": "B" * 64},
                    "particle_source": {"path": "artifact/source.csv", "sha256": "C" * 64},
                    "metadata": {"path": "artifact/metadata.json", "sha256": "D" * 64},
                    "handoff_publication_contract": {"path": "contract.json", "sha256": "E" * 64},
                },
                "single_flight_population": {
                    "population_id": "mother", "population_mode": "independent_spatial_velocity_ion_source_snapshot",
                    "source_authority": {"input_role": "single_flight_materialized_ion_source_volume", "table_binding": "prepared_materialized_ion_source_volume", "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1"},
                    "execution_population": {"particle_count": 5000, "ordered_particle_id_sha256": canonical_json_sha256(list(range(1, 5001))), "selection_algorithm": "all_rows_in_frozen_file_order", "selection_seed": 0},
                    "denominators": {"population_count": 5000, "eligible_population_count": 5000},
                    "analysis_randomness": {"bootstrap_resample_count": 1, "bootstrap_seed": 1}, "postselection_policy": "prohibited",
                },
            }, "variation_axes": [], "rows": [{
                "experiment_id": "square_h100_full_flight_n5000",
                "values": {"continuous_full_flight_comparator_authority": self._comparator()},
            }]},
        }
        path = workspace / "simulation_repo" / "integrations" / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer" / "config" / "explorations" / "source.json"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(document), encoding="utf-8"); return path

    def test_authors_fixed_first_row_and_retains_mother_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary); source = self._source(workspace); output = source.with_name("smoke.json")
            result = author_campaign(source_campaign_path=source, experiment_id="square_h100_full_flight_n5000", output_path=output, campaign_id="smoke", workspace=workspace)
            shared = result["experiments"]["shared"]; population = shared["single_flight_population"]
            self.assertEqual(population["execution_population"], {"particle_count": 1, "ordered_particle_id_sha256": canonical_json_sha256([1]), "selection_algorithm": "first_n_rows_in_frozen_file_order", "selection_seed": 0})
            self.assertEqual(population["denominators"]["population_count"], 5000)
            self.assertEqual(shared["continuous_functional_smoke_authority"]["execution_selection"]["source_particle_id"], 1)
            self.assertEqual(result["experiments"]["rows"][0]["experiment_id"], "square_h100_full_flight_functional_smoke_n1")
            values = result["experiments"]["rows"][0]["values"]
            self.assertNotIn("continuous_full_flight_comparator_authority", values)
            self.assertEqual(
                shared["continuous_functional_smoke_pulse_authority"]["continuous_full_flight_comparator_authority"],
                self._comparator(),
            )
            experiment = expand_flat_experiment_authoring(result)["experiments"][0]
            _validate_continuous_functional_smoke_authority(
                root=workspace / "simulation_repo", workspace=workspace, experiment=experiment,
            )

    def test_rejects_source_row_without_full_mother_comparator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary); source = self._source(workspace)
            document = json.loads(source.read_text(encoding="utf-8"))
            document["experiments"]["rows"][0]["values"] = {}
            source.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "lacks a full-mother comparator"):
                author_campaign(
                    source_campaign_path=source,
                    experiment_id="square_h100_full_flight_n5000",
                    output_path=source.with_name("smoke.json"),
                    campaign_id="smoke",
                    workspace=workspace,
                )

    def test_functional_smoke_pulse_reuses_exact_full_mother_schedule(self) -> None:
        comparator = {
            "schedule": {
                "rf_period_us": 0.125,
                "pulse_effective_time_us": 72.8863636363636,
                "pulse_width_us": 6.0,
            },
            "execution_authority": {"mode": "manifest_bound_continuous_full_flight_comparator_v1"},
        }
        schedule, state = _resolve_functional_smoke_pulse_schedule(
            base_schedule={"rf_period_us": 0.125, "policy": {}}, comparator=comparator,
        )
        self.assertEqual(state, "ready_verified")
        self.assertEqual(schedule["method"], "manifest_bound_full_mother_pulse_for_functional_smoke_v1")
        self.assertEqual(schedule["pulse_effective_time_us"], 72.8863636363636)
        self.assertEqual(schedule["pulse_width_us"], 6.0)
        self.assertNotEqual(state, "discovery_required")

    def test_rejects_nonmother_and_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary); source = self._source(workspace); value = json.loads(source.read_text(encoding="utf-8"))
            value["experiments"]["shared"]["single_flight_population"]["execution_population"]["particle_count"] = 2
            source.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "frozen ordered N=5000"):
                author_campaign(source_campaign_path=source, experiment_id="square_h100_full_flight_n5000", output_path=source.with_name("out.json"), campaign_id="smoke", workspace=workspace)
            source = self._source(workspace); output = source.with_name("out.json"); output.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "output already exists"):
                author_campaign(source_campaign_path=source, experiment_id="square_h100_full_flight_n5000", output_path=output, campaign_id="smoke", workspace=workspace)

    def test_rejects_output_escape_and_screening_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary); source = self._source(workspace)
            with self.assertRaisesRegex(ContractError, "config/explorations"):
                author_campaign(source_campaign_path=source, experiment_id="square_h100_full_flight_n5000", output_path=workspace / "artifacts" / "smoke.json", campaign_id="smoke", workspace=workspace)
            value = json.loads(source.read_text(encoding="utf-8")); value["pre_pulse_time_series_screening"] = {}
            source.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "must not carry pre-pulse screening"):
                author_campaign(source_campaign_path=source, experiment_id="square_h100_full_flight_n5000", output_path=source.with_name("smoke.json"), campaign_id="smoke", workspace=workspace)

    def test_prepare_prefix_and_resolved_runner_population_are_id1_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary); source = workspace / "mother.csv"; prefix = workspace / "prefix.csv"
            source.write_text(
                "particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state\n"
                "1,0,0,0,0,0,0,0,100,1\n2,0,0,0,0,0,0,0,100,1\n", encoding="utf-8",
            )
            write_pulse_resolution_screening_prefix(source, prefix, ordered_particle_ids=[1])
            self.assertEqual(prefix.read_text(encoding="utf-8").splitlines()[1].split(",")[0], "1")
            declaration = {
                "population_id": "smoke", "population_mode": "first_n_rows_in_frozen_file_order",
                "source_authority": {"input_role": "single_flight_materialized_ion_source_volume", "table_binding": "prepared_deterministic_prefix", "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1"},
                "execution_population": {"particle_count": 1, "ordered_particle_id_sha256": canonical_json_sha256([1]), "selection_algorithm": "first_n_rows_in_frozen_file_order", "selection_seed": 0},
                "denominators": {"population_count": 5000, "eligible_population_count": 5000}, "analysis_randomness": {"bootstrap_resample_count": 0, "bootstrap_seed": 0}, "postselection_policy": "prohibited",
            }
            contract = compile_resolved_population_contract(campaign_id="smoke", experiment_id="smoke_n1", experiment_row_sha256="A" * 64, population_declaration_sha256="B" * 64, execution_strategy="simion_single_flight", source_release_mode="continuous_frontend", declaration=declaration, source_table=_population_source_table(prefix, workspace=workspace, input_role="single_flight_materialized_ion_source_volume", table_binding="prepared_deterministic_prefix"), contract_schema_version=2)
            runtime = resolve_runtime_population(contract)
            self.assertEqual((runtime["launched_particle_count"], runtime["population_denominator_count"]), (1, 5000))
