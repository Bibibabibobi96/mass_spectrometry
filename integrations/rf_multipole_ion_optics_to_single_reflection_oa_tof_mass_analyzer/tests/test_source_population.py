from __future__ import annotations

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.source_population import (
    derive_source_population,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_SCHEMA = REPO_ROOT / "integrations" / (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
) / "config" / "schemas" / "rf_multipole_oatof_experiment_campaign.schema.json"
CAMPAIGN_PATH = REPO_ROOT / (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "docs/history/retired_campaigns/connector_gap_102p4_real_pa_full_n5000_v1.json"
)


class SourcePopulationTest(unittest.TestCase):
    def _state(self, root: Path) -> Path:
        path = root / "state.csv"
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output, fieldnames=["particle_id", "event", "status"]
            )
            writer.writeheader()
            for particle_id in range(1, 4504):
                writer.writerow(
                    {
                        "particle_id": particle_id,
                        "event": "handoff",
                        "status": "transmitted",
                    }
                )
            writer.writerow(
                {"particle_id": 4504, "event": "handoff", "status": "lost"}
            )
        return path

    def test_handoff_transmitted_count_is_derived_as_4503(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory))
            receipt = derive_source_population(
                state,
                expected_state_sha256=file_sha256(state),
                selector={"event": "handoff", "status": "transmitted"},
            )
        self.assertEqual(receipt["particle_count"], 4503)
        validate_schema(
            receipt, "rf_multipole_oatof_source_population_receipt.schema.json"
        )

    def test_tampered_state_or_selector_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                derive_source_population(
                    state,
                    expected_state_sha256="0" * 64,
                    selector={"event": "handoff", "status": "transmitted"},
                )
            with self.assertRaisesRegex(ValueError, "matched no particles"):
                derive_source_population(
                    state,
                    expected_state_sha256=file_sha256(state),
                    selector={"event": "terminal", "status": "transmitted"},
                )

    def test_current_campaign_uses_only_derived_count_binding(self) -> None:
        campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        source = campaign["experiments"][0]["source"]
        self.assertNotIn("particle_count", source)
        self.assertEqual(
            source["particle_count_binding"],
            {
                "mode": "derive_from_frozen_source_state_v1",
                "selector": {"event": "handoff", "status": "transmitted"},
            },
        )
        validate_schema(campaign, CAMPAIGN_SCHEMA)
        explicit = deepcopy(campaign)
        explicit["experiments"][0]["source"]["particle_count"] = 4503
        with self.assertRaises(ValueError):
            validate_schema(
                explicit, CAMPAIGN_SCHEMA
            )


if __name__ == "__main__":
    unittest.main()
