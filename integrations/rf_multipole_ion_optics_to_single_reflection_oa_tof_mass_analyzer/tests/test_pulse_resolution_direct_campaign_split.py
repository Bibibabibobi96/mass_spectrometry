from __future__ import annotations

import json
from pathlib import Path
import unittest

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.fixtures.campaign_fixture import (
    current_campaign_fixture,
)


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_CAMPAIGNS = INTEGRATION_ROOT / "docs" / "history" / "retired_campaigns" / "root_campaigns"
BASELINE = HISTORICAL_CAMPAIGNS / "pulse_resolution_direct_baseline_successor_r09_campaign.json"
ARCHIVED_BASELINE = HISTORICAL_CAMPAIGNS / "pulse_resolution_direct_baseline_successor_r07_campaign.json"
AUTHORIZED_CANDIDATES = HISTORICAL_CAMPAIGNS / (
    "pulse_resolution_direct_candidate_successor_r03_campaign.json"
)
SCHEMA = "rf_multipole_oatof_experiment_campaign.schema.json"


def load(path: Path) -> dict[str, object]:
    return current_campaign_fixture(json.loads(path.read_text(encoding="utf-8-sig")))


class PulseResolutionDirectCampaignSplitTests(unittest.TestCase):
    def test_r09_successor_changes_only_identity(self) -> None:
        archived = load(ARCHIVED_BASELINE)
        successor = load(BASELINE)
        self.assertEqual(successor["campaign_id"], "pulse_resolution_direct_baseline_v5_r09")
        self.assertTrue(successor["experiments"][0]["run_id"].endswith("__r09"))
        archived.pop("campaign_id")
        successor.pop("campaign_id")
        archived["experiments"][0].pop("run_id")
        successor["experiments"][0].pop("run_id")
        self.assertEqual(archived, successor)

    def test_candidate_successor_is_preregistered_against_r09(self) -> None:
        campaign = load(AUTHORIZED_CANDIDATES)
        validate_schema(campaign, SCHEMA)
        self.assertEqual(campaign["status"], "retired")
        self.assertEqual(
            campaign["pulse_resolution_baseline_evidence"]["sha256"],
            "EA4BB4084A754F5442B016B7D3744141A107C291B8DDABA8CCD9C193D759E37E",
        )
        self.assertEqual(
            [row["sequence"] for row in campaign["experiments"]], [2, 3, 4]
        )
        self.assertTrue(all(
            row["authority_status"] == "direct_executable_contract"
            for row in campaign["pulse_resolution_optimization"][
                "comparison_matrix"
            ]
        ))
        self.assertEqual(
            set(campaign["preregistration"]["frozen_experiment_row_sha256"]),
            {row["experiment_id"] for row in campaign["experiments"]},
        )


if __name__ == "__main__":
    unittest.main()
