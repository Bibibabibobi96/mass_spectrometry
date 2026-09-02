from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    CAMPAIGN_SCHEMA_PATH,
    RESOLVED_CAMPAIGN_SCHEMA_PATH,
    expand_flat_experiment_authoring,
)


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_PATH = INTEGRATION_ROOT / "config" / "explorations" / (
    "ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000.json"
)


class PrePulseCampaignProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))

    def test_minimal_authored_contract_expands_to_complete_resolved_rows(self) -> None:
        validate_schema(self.campaign, CAMPAIGN_SCHEMA_PATH)
        resolved = expand_flat_experiment_authoring(self.campaign)
        validate_schema(resolved, RESOLVED_CAMPAIGN_SCHEMA_PATH)
        self.assertNotIn("pre_pulse_campaign_profile_id", resolved)
        self.assertEqual(len(resolved["experiments"]), 8)
        first = resolved["experiments"][0]
        self.assertEqual(first["execution_strategy"], "simion_single_flight")
        self.assertEqual(
            first["single_flight_population"]["execution_population"]["particle_count"], 5000
        )
        self.assertEqual(first["source"]["launched_particle_count"], 5000)

    def test_authoring_rows_scan_only_the_local_entrance_aperture_height(self) -> None:
        """Keep the eight-arm PA-reuse scan aligned to the 1 mm reference hole."""

        expected_heights_by_shape = {
            "square": [1.0, 1.5, 2.0, 2.5],
            "cylindrical": [1.0, 1.5, 2.0, 2.5],
        }
        rows_by_shape: dict[str, list[dict[str, object]]] = {
            "square": [], "cylindrical": [],
        }
        for row in self.campaign["experiments"]["rows"]:
            for shape in rows_by_shape:
                if f"_{shape}_" in row["experiment_id"]:
                    rows_by_shape[shape].append(row)
                    break

        for shape, expected_heights in expected_heights_by_shape.items():
            with self.subTest(shape=shape):
                rows = rows_by_shape[shape]
                apertures = [
                    row["values"]["accelerator_entrance_local_aperture_mm"]
                    for row in rows
                ]
                self.assertEqual(
                    [aperture["width"] for aperture in apertures],
                    [1.0] * len(expected_heights),
                )
                self.assertEqual(
                    [aperture["height"] for aperture in apertures],
                    expected_heights,
                )

    def test_profile_owned_shared_value_cannot_be_redeclared(self) -> None:
        campaign = copy.deepcopy(self.campaign)
        campaign["experiments"]["shared"]["execution_strategy"] = "simion_single_flight"
        with self.assertRaisesRegex(ContractError, "duplicates authored shared field"):
            expand_flat_experiment_authoring(campaign)


if __name__ == "__main__":
    unittest.main()
