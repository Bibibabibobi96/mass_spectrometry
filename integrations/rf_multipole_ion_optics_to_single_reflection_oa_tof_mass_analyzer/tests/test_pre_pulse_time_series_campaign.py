from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    compile_pre_pulse_time_series_contract,
    validate_pre_pulse_time_series_campaign,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = REPO_ROOT / (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
LEGACY_CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "config/diagnostics/"
    "pre_pulse_time_series_gap3p2_three_zone_real_pa_first100_n100_campaign.json"
)
CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "config/diagnostics/"
    "pre_pulse_time_series_gap3p2_three_zone_real_pa_first100_n100_campaign_v2.json"
)
V3_CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "config/diagnostics/"
    "pre_pulse_time_series_gap3p2_three_zone_real_pa_first100_n100_campaign_v3.json"
)
ADAPTER_PATH = INTEGRATION_ROOT / "workflows/family_source_closure/adapter.ps1"
PUBLIC_ENTRY_PATH = INTEGRATION_ROOT / "workflows/family_source_closure/execute.ps1"


class PrePulseTimeSeriesCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))

    def _compile(self) -> dict[str, object]:
        row = self.campaign["experiments"][0]
        return compile_pre_pulse_time_series_contract(
            campaign=self.campaign,
            experiment=row,
            experiment_row_sha256="A" * 64,
            upstream_resolved_design={"drive": {
                "frequency_Hz": 1_100_000, "waveform": "sine", "phase_rad": 0.25,
            }},
            resolved_source_contract_sha256="B" * 64,
            resolved_population_contract_sha256="C" * 64,
            prepared_prefix_sha256="D" * 64,
            layout_profile={
                "topology_id": "three_zone_accelerator_ideal_v1",
                "geometry_id": "three_zone_focus_origin_planes_v1",
                "frontend_electrode_topology_id": "three_zone_frontend_v1",
            },
            selected_field_profile={"field_id": "three_zone_refined_pa_field_v1"},
            region_field_semantic_sha256="E" * 64,
            rf_steps_per_period=160,
        )

    def test_campaign_and_compiled_runner_contract_close_rf160_grid(self) -> None:
        validate_schema(
            self.campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        validate_pre_pulse_time_series_campaign(self.campaign)
        contract = self._compile()
        validate_schema(
            contract, "rf_oatof_pre_pulse_time_series_screening_contract.schema.json"
        )
        times = contract["sample_times_us"]
        grid = contract["rf_time_grid"]
        self.assertEqual(len(times), 321)
        self.assertAlmostEqual(times[160], 46.7467890041091, places=13)
        self.assertAlmostEqual(times[0], 45.8376980950182, places=13)
        self.assertAlmostEqual(times[-1], 47.6558799132, places=13)
        self.assertEqual(grid["start_index"], 0)
        self.assertEqual(grid["end_index"], 320)
        self.assertFalse(contract["resolution_claim_allowed"])
        self.assertEqual(contract["active_scope"], "pre_pulse_frontend_accelerator")
        self.assertIsNone(contract["pa_cache_keys"]["flight_tube"])
        self.assertIsNone(contract["pa_cache_keys"]["reflectron"])
        self.assertEqual(contract["identities"]["mother_particle_source_sha256"], "D" * 64)

    def test_published_v1_remains_schema_readable_but_non_executable(self) -> None:
        legacy = json.loads(LEGACY_CAMPAIGN_PATH.read_text(encoding="utf-8"))
        validate_schema(legacy, "rf_multipole_oatof_experiment_campaign.schema.json")
        with self.assertRaisesRegex(ContractError, "source, population, or grid differs"):
            validate_pre_pulse_time_series_campaign(legacy)

    def test_v3_successor_changes_only_identity_and_mode_failure_claim(self) -> None:
        successor = json.loads(V3_CAMPAIGN_PATH.read_text(encoding="utf-8"))
        validate_schema(
            successor, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        validate_pre_pulse_time_series_campaign(successor)
        self.assertEqual(
            successor["experiments"][0]["run_id"],
            "20260818_232200__sim__cross__three-zone-pre-pulse-time-series-gap3p2__n100",
        )
        self.assertIn("existing mode 2 held-off control", successor["claim_limit"])
        baseline = copy.deepcopy(self.campaign)
        comparison = copy.deepcopy(successor)
        for document in (baseline, comparison):
            document.pop("campaign_id")
            document.pop("claim_limit")
            document["experiments"][0].pop("experiment_id")
            document["experiments"][0].pop("run_id")
        self.assertEqual(comparison, baseline)

    def test_campaign_and_compiler_reject_population_or_rf_drift(self) -> None:
        drift = copy.deepcopy(self.campaign)
        drift["experiments"][0]["single_flight_population"]["denominators"][
            "population_count"
        ] = 99
        with self.assertRaises(ContractError):
            validate_pre_pulse_time_series_campaign(drift)
        row = self.campaign["experiments"][0]
        with self.assertRaisesRegex(ContractError, "upstream RF grid differs"):
            compile_pre_pulse_time_series_contract(
                campaign=self.campaign, experiment=row,
                experiment_row_sha256="A" * 64,
                upstream_resolved_design={"drive": {
                    "frequency_Hz": 1_100_001, "waveform": "sine", "phase_rad": 0,
                }},
                resolved_source_contract_sha256="B" * 64,
                resolved_population_contract_sha256="C" * 64,
                prepared_prefix_sha256="D" * 64,
                layout_profile={"topology_id": "three_zone_accelerator_ideal_v1",
                                "geometry_id": "three_zone_focus_origin_planes_v1",
                                "frontend_electrode_topology_id": "three_zone_frontend_v1"},
                selected_field_profile={"field_id": "three_zone_refined_pa_field_v1"},
                region_field_semantic_sha256="E" * 64,
                rf_steps_per_period=160,
            )

    def test_adapter_transports_internal_contract_without_new_public_cli(self) -> None:
        adapter = ADAPTER_PATH.read_text(encoding="utf-8")
        public_entry = PUBLIC_ENTRY_PATH.read_text(encoding="utf-8")
        for name in (
            "pre_pulse_time_series_prefix_filename",
            "pre_pulse_time_series_prefix_sha256",
            "pre_pulse_time_series_contract_filename",
            "pre_pulse_time_series_contract_sha256",
            "PrePulseTimeSeriesContract",
            "PrePulseTimeSeriesContractSha256",
        ):
            self.assertIn(name, adapter)
        self.assertIn("$runnerArguments.PrePulseTimeSeriesContract", adapter)
        self.assertNotIn("PrePulseTimeSeriesContract", public_entry)


if __name__ == "__main__":
    unittest.main()
