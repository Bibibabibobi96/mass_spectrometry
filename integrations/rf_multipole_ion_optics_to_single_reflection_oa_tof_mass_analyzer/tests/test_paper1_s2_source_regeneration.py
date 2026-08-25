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


if __name__ == "__main__":
    unittest.main()
