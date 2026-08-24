from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.fixtures.campaign_fixture import (
    current_campaign_fixture,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _automatic_pulse_population_binding,
    compile_pre_pulse_time_series_contract,
    validate_pre_pulse_time_series_campaign,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = REPO_ROOT / (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "config" / "schemas"

ACTIVE_CAMPAIGN_SCHEMA = INTEGRATION_ROOT / "config" / "schemas" / (
    "rf_multipole_oatof_experiment_campaign.schema.json"
)
ARCHIVAL_CAMPAIGN_SCHEMA = ACTIVE_CAMPAIGN_SCHEMA.parent / (
    "rf_multipole_oatof_experiment_campaign_v1_to_v6.schema.json"
)
LEGACY_CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "docs/history/retired_campaigns/"
    "pre_pulse_time_series_gap3p2_three_zone_real_pa_first100_n100_campaign.json"
)
CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "docs/history/retired_campaigns/"
    "pre_pulse_time_series_gap3p2_three_zone_real_pa_first100_n100_campaign_v2.json"
)
V3_CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "docs/history/retired_campaigns/"
    "pre_pulse_time_series_gap3p2_three_zone_real_pa_first100_n100_campaign_v3.json"
)
V5_AUTO_CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "docs/history/retired_campaigns/"
    "connector_gap_three_zone_real_pa_first100_n100_campaign_v5.json"
)
CURRENT_AUTO_CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "docs/history/retired_campaigns/connector_gap_102p4_real_pa_full_n5000_v1.json"
)
ADAPTER_PATH = INTEGRATION_ROOT / "workflows/family_source_closure/adapter.ps1"


class PrePulseTimeSeriesCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))

    def _compile(
        self, *, time_integration_profile_id: str | None = None
    ) -> dict[str, object]:
        campaign = copy.deepcopy(self.campaign)
        campaign["pre_pulse_time_series_screening"][
            "spatial_window_profile_id"
        ] = "layout_resolved_axial_provisional_xy2_v1"
        row = campaign["experiments"][0]
        return compile_pre_pulse_time_series_contract(
            campaign=campaign,
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
            time_integration_profile_id=time_integration_profile_id,
        )

    def test_campaign_and_compiled_runner_contract_close_rf160_grid(self) -> None:
        validate_pre_pulse_time_series_campaign(self.campaign)
        contract = self._compile()
        validate_schema(
            contract, SCHEMA_DIR / "rf_oatof_pre_pulse_time_series_screening_contract.schema.json"
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

    def test_screening_solver_profile_is_independent_of_full_flight_profile(self) -> None:
        contract = self._compile(time_integration_profile_id="dt160")
        self.assertEqual(contract["identities"]["time_integration_profile_id"], "dt160")
        self.assertEqual(contract["active_scope"], "pre_pulse_frontend_accelerator")
        self.assertIsNone(contract["pa_cache_keys"]["flight_tube"])
        self.assertIsNone(contract["pa_cache_keys"]["reflectron"])
        self.assertEqual(contract["identities"]["mother_particle_source_sha256"], "D" * 64)

    def test_schema_accepts_unregistered_numerics_and_pre_pulse_grid_values(self) -> None:
        campaign = current_campaign_fixture(self.campaign)
        screening = campaign["pre_pulse_time_series_screening"]
        screening["rf_steps_per_period"] = 161
        screening["sample_count"] = 319
        screening["spatial_window_profile_id"] = "fixture_window_profile"
        screening["pa_cache_keys"]["frontend"] = "A" * 64
        screening["pa_cache_keys"]["accelerator_overlay"] = "B" * 64
        campaign["experiments"][0]["single_flight_trajectory_quality_profile_id"] = (
            "fixture_tqual"
        )
        campaign["experiments"][0]["single_flight_time_integration_profile_id"] = (
            "fixture_dt"
        )
        validate_schema(campaign, ARCHIVAL_CAMPAIGN_SCHEMA)

    def test_published_v1_campaign_is_no_longer_active_schema_input(self) -> None:
        legacy = json.loads(LEGACY_CAMPAIGN_PATH.read_text(encoding="utf-8"))
        with self.assertRaises(ContractError):
            validate_schema(
                legacy, ACTIVE_CAMPAIGN_SCHEMA
            )
        with self.assertRaisesRegex(ContractError, "source, population, or grid differs"):
            validate_pre_pulse_time_series_campaign(legacy)

    def test_v3_successor_changes_only_identity_and_mode_failure_claim(self) -> None:
        successor = json.loads(V3_CAMPAIGN_PATH.read_text(encoding="utf-8"))
        with self.assertRaises(ContractError):
            validate_schema(
                successor, ACTIVE_CAMPAIGN_SCHEMA
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

    def test_auto_policy_uses_ballistic_seed_minus56_plus264_without_pa_keys(self) -> None:
        row = self.campaign["experiments"][0]
        contract = compile_pre_pulse_time_series_contract(
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
            specification={
                "mode": "real_pa_rf_pre_pulse_time_series",
                "active_scope": "pre_pulse_frontend_accelerator",
                "time_grid_profile_id": "ballistic_seed_rf160_minus56_plus264_v1",
                "relative_start_index": -56,
                "relative_end_index": 264,
                "rf_steps_per_period": 160,
                "sample_count": 321,
                "spatial_window_profile_id": (
                    "layout_resolved_axial_provisional_xy2_v1"
                ),
                "pulse_disabled": True,
                "terminate_at_window_end": True,
                "resolution_claim_allowed": False,
                "prohibited_outputs": [
                    "detector_crossing", "resolution_metrics",
                    "single_flight_spatial_six_panel",
                ],
            },
            base_schedule={"pulse_effective_time_us": 45.4167939656417},
        )
        self.assertEqual(contract["schema_version"], 2)
        self.assertNotIn("pa_cache_keys", contract)
        self.assertEqual(
            contract["pa_cache_roles"]["required"],
            ["frontend", "accelerator_overlay"],
        )
        grid = contract["rf_time_grid"]
        self.assertEqual(grid["requested_relative_start_index"], -56)
        self.assertEqual(grid["requested_relative_end_index"], 264)
        self.assertAlmostEqual(
            contract["sample_times_us"][56], grid["ballistic_seed_time_us"], places=13
        )

    def test_screening_schema_closes_version_to_pa_authority_and_grid(self) -> None:
        legacy = self._compile()
        automatic = copy.deepcopy(legacy)
        automatic["schema_version"] = 2
        automatic["identities"]["spatial_window_profile_id"] = (
            "layout_resolved_axial_provisional_xy2_v1"
        )
        automatic["pa_cache_roles"] = {
            "identity_source": "runner_materialized_verified_pa_cache_receipt",
            "required": ["frontend", "accelerator_overlay"],
            "prohibited": ["flight_tube", "reflectron"],
        }
        automatic.pop("pa_cache_keys")
        automatic["rf_time_grid"] = {
            "time_grid_profile_id": "ballistic_seed_rf160_minus56_plus264_v1",
            "derivation": (
                "ballistic_seed_time_us + relative_index*period_us/"
                "rf_steps_per_period"
            ),
            "waveform": "sine",
            "frequency_hz": 1_100_000,
            "phase_rad": 0.25,
            "rf_steps_per_period": 160,
            "period_us": 10 / 11,
            "step_us": 1 / 176,
            "ballistic_seed_time_us": 45.4167939656417,
            "grid_origin_us": 45.09861214745988,
            "requested_relative_start_index": -56,
            "requested_relative_end_index": 264,
            "ballistic_seed_sample_index": 56,
            "start_index": 0,
            "end_index": 320,
            "sample_count": 321,
        }
        validate_schema(
            automatic,
            SCHEMA_DIR / "rf_oatof_pre_pulse_time_series_screening_contract.schema.json",
        )
        for crossed in (
            {**copy.deepcopy(legacy), "schema_version": 2},
            {**copy.deepcopy(automatic), "schema_version": 1},
            {**copy.deepcopy(legacy), "rf_time_grid": automatic["rf_time_grid"]},
            {**copy.deepcopy(automatic), "rf_time_grid": legacy["rf_time_grid"]},
        ):
            with self.assertRaises(ContractError):
                validate_schema(
                    crossed,
                    SCHEMA_DIR / "rf_oatof_pre_pulse_time_series_screening_contract.schema.json",
                )

    def test_active_cache_miss_schema_requires_layout_resolved_profile(self) -> None:
        campaign = json.loads(CURRENT_AUTO_CAMPAIGN_PATH.read_text(encoding="utf-8"))
        campaign["experiments"][0]["single_flight_pulse_schedule_policy"][
            "cache_miss_policy"
        ]["spatial_window_profile_id"] = "legacy_fixed_window"
        with self.assertRaises(ContractError):
            validate_schema(
                campaign, ARCHIVAL_CAMPAIGN_SCHEMA
            )
        for row in campaign["experiments"]:
            row["single_flight_pulse_schedule_policy"]["cache_miss_policy"][
                "spatial_window_profile_id"
            ] = "layout_resolved_axial_provisional_xy2_v1"
        validate_schema(campaign, ARCHIVAL_CAMPAIGN_SCHEMA)
        self.assertEqual(len(campaign["experiments"]), 1)
        for row in campaign["experiments"]:
            policy = row["single_flight_pulse_schedule_policy"]["cache_miss_policy"]
            self.assertEqual(
                policy["mode"],
                "auto_detector_blind_discovery_and_confirmation_v1",
            )
            self.assertNotIn("fixed_execution_authority", row["single_flight_pulse_schedule_policy"])

    def test_auto_policy_keeps_legacy_n100_prefix_compatibility(self) -> None:
        legacy = {
            "population_mode": "first_100_rows_in_frozen_file_order",
            "source_authority": {"table_binding": "prepared_deterministic_prefix"},
            "execution_population": {
                "particle_count": 100,
                "selection_algorithm": "first_100_rows_in_frozen_file_order",
            },
        }
        self.assertEqual(
            _automatic_pulse_population_binding(legacy),
            ("prepared_deterministic_prefix", 100),
        )
        legacy["execution_population"]["particle_count"] = 99
        with self.assertRaisesRegex(
            ContractError, "automatic pulse timing population differs"
        ):
            _automatic_pulse_population_binding(legacy)

    def test_schema_and_auto_policy_accept_generic_deterministic_prefix(self) -> None:
        campaign = json.loads(CURRENT_AUTO_CAMPAIGN_PATH.read_text(encoding="utf-8"))
        for row in campaign["experiments"]:
            population = row["single_flight_population"]
            population["population_mode"] = "first_n_rows_in_frozen_file_order"
            population["source_authority"]["table_binding"] = (
                "prepared_deterministic_prefix"
            )
            population["execution_population"]["particle_count"] = 37
            population["execution_population"]["selection_algorithm"] = (
                "first_n_rows_in_frozen_file_order"
            )
            population["denominators"]["population_count"] = 37
            population["denominators"]["eligible_population_count"] = 37
        validate_schema(campaign, ARCHIVAL_CAMPAIGN_SCHEMA)
        self.assertEqual(
            _automatic_pulse_population_binding(
                campaign["experiments"][0]["single_flight_population"]
            ),
            ("prepared_deterministic_prefix", 37),
        )

    def test_adapter_population_path_casts_execute_as_strings(self) -> None:
        script = r"""
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_ADAPTER_PATH, [ref]$null, [ref]$errors
)
if ($errors) { throw $errors[0] }
$cases = @(
  @('prePulseTimeSeriesPrefixBinding', 'pre_pulse_time_series_prefix_filename'),
  @('pulseCandidateConfirmationPrefixBinding',
    'pulse_candidate_confirmation_prefix_filename')
)
foreach ($case in $cases) {
  $variableName = '$' + $case[0]
  $assignment = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
      $node.Left.Extent.Text -eq $variableName
  }, $true)
  if ($null -eq $assignment) { throw "missing assignment: $variableName" }
  $frozenArguments = @{}
  $frozenArguments[$case[1]] = 'artifacts/projects/source.csv'
  . ([scriptblock]::Create($assignment.Extent.Text))
  $value = Get-Variable -Name $case[0] -ValueOnly
  if ($value.GetType().FullName -ne 'System.String' -or
      -not $value.StartsWith('artifacts/')) {
    throw "population path cast is not executable: $variableName"
  }
}
"CAST_SHAPE=PASS"
"""
        environment = os.environ.copy()
        environment["RF_ADAPTER_PATH"] = str(ADAPTER_PATH)
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False, timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CAST_SHAPE=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
