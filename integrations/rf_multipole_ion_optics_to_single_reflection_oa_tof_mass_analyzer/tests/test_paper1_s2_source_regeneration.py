"""Contract checks for the Paper 1 S2 provenance repair."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from common.multipole.runtime_profile import resolve_runtime_selection


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
CAMPAIGN = REPO / "common" / "multipole" / "campaigns" / "20260825__paper1_s2_segmented_standard_terminal_n100.json"
CAMPAIGN_N1000 = REPO / "common" / "multipole" / "campaigns" / "20260825__paper1_s2_segmented_standard_terminal_n1000.json"
INTEGRATION_ROOT = REPO / "integrations" / (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
PRE_PULSE_CAMPAIGN_N1000 = INTEGRATION_ROOT / "config" / "explorations" / (
    "paper1_s2_segmented_pre_pulse_n1000.json"
)
PRE_PULSE_SCHEMA = INTEGRATION_ROOT / "config" / "schemas" / (
    "rf_multipole_oatof_experiment_campaign.schema.json"
)


class Paper1S2SourceRegenerationTests(unittest.TestCase):
    def test_campaign_is_schema_valid_and_resolves_current_terminal(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        validate_schema(campaign, "multipole_transport_experiment_campaign.schema.json")
        self.assertEqual(
            campaign["downstream_terminal_profile"]["terminal_profile_id"],
            "oatof_shield_terminal",
        )
        resolved = resolve_runtime_selection(
            REPO,
            project_id="rf_hexapole_ion_optics",
            campaign_path=CAMPAIGN,
            experiment_id="paper1_s2_segmented_standard_terminal_n100",
        )
        self.assertEqual(
            resolved["design_profile_resolution"]["resolved_design"][
                "downstream_terminal"
            ]["terminal_profile_id"],
            "oatof_shield_terminal",
        )
        self.assertEqual(resolved["design_profile_id"], "segmented_rod_axial_acceleration")
        self.assertEqual(resolved["particle_source"]["profile_id"], "family_mother_sample_v1_n100")

    def test_n1000_campaign_is_schema_valid_and_uses_the_family_mother_sample(self) -> None:
        campaign = json.loads(CAMPAIGN_N1000.read_text(encoding="utf-8"))
        validate_schema(campaign, "multipole_transport_experiment_campaign.schema.json")
        resolved = resolve_runtime_selection(
            REPO,
            project_id="rf_hexapole_ion_optics",
            campaign_path=CAMPAIGN_N1000,
            experiment_id="paper1_s2_segmented_standard_terminal_n1000",
        )
        self.assertEqual(
            resolved["particle_source"]["profile_id"], "family_mother_sample_v1_n1000"
        )
        self.assertEqual(
            resolved["engineering_budget"]["inline_contract"]["pilot_authorization"]["scope"]
            ["authorized_run_id"],
            "20260825_103000__sim__simion__paper1-s2-segmented-standard-terminal__n1000",
        )
        self.assertEqual(resolved["simion_dispatch"]["kind"], "automatic")
        self.assertTrue(resolved["simion_dispatch"]["independent_particles"])

    def test_pre_pulse_contract_preserves_the_complete_s2_mother_cohort(self) -> None:
        campaign = json.loads(PRE_PULSE_CAMPAIGN_N1000.read_text(encoding="utf-8"))
        validate_schema(campaign, PRE_PULSE_SCHEMA)
        row = campaign["experiments"][0]
        population = row["single_flight_population"]
        self.assertEqual(campaign["status"], "exploration")
        self.assertEqual(row["source_profile_id"], "canonical_real_hexapole_n1000")
        self.assertEqual(
            row["single_flight_pa_cache_policy"],
            "build_and_publish_if_missing",
        )
        self.assertEqual(row["source"]["launched_particle_count"], 1000)
        self.assertEqual(population["execution_population"]["particle_count"], 1000)
        self.assertEqual(population["denominators"]["population_count"], 1000)
        self.assertEqual(population["postselection_policy"], "prohibited")
        self.assertTrue(campaign["pre_pulse_time_series_screening"]["pulse_disabled"])


if __name__ == "__main__":
    unittest.main()
