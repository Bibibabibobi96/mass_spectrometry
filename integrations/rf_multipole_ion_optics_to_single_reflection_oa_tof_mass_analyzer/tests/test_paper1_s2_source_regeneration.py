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


if __name__ == "__main__":
    unittest.main()
