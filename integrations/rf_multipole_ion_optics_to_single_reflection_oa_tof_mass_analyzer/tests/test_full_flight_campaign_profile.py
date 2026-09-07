from __future__ import annotations

import json
from pathlib import Path
import unittest

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    CAMPAIGN_SCHEMA_PATH,
    RESOLVED_CAMPAIGN_SCHEMA_PATH,
    expand_flat_experiment_authoring,
)


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_PATH = INTEGRATION_ROOT / "config" / "explorations" / (
    "ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_full_flight_continuous_n5000.json"
)
FULL_BORE_PROFILE_ID = (
    "frontend_xy025_z010_coarse100_full_bore_main_local_xy050_z010"
)


class FullFlightCampaignProfileTests(unittest.TestCase):
    def test_continuous_eight_arm_scan_uses_full_bore_main_and_local_apertures(self) -> None:
        """Keep complete-cohort full flight out of the narrow-core main PA."""

        campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        validate_schema(campaign, CAMPAIGN_SCHEMA_PATH)
        resolved = expand_flat_experiment_authoring(campaign)
        validate_schema(resolved, RESOLVED_CAMPAIGN_SCHEMA_PATH)

        self.assertEqual(
            campaign["experiments"]["shared"]["single_flight_frontend_grid_profile_id"],
            FULL_BORE_PROFILE_ID,
        )
        experiments = resolved["experiments"]
        self.assertEqual(len(experiments), 8)
        self.assertTrue(
            all(
                experiment["single_flight_frontend_grid_profile_id"] == FULL_BORE_PROFILE_ID
                for experiment in experiments
            )
        )
        self.assertEqual(
            {
                (experiment["single_flight_layout_profile_id"],
                 experiment["accelerator_entrance_local_aperture_mm"]["height"])
                for experiment in experiments
            },
            {
                ("three_zone_ideal_acceptance_300mm_square_kinematic_envelope_v1", height)
                for height in (1.0, 1.5, 2.0, 2.5)
            }
            | {
                ("three_zone_ideal_acceptance_300mm_cylindrical_kinematic_envelope_v1", height)
                for height in (1.0, 1.5, 2.0, 2.5)
            },
        )


if __name__ == "__main__":
    unittest.main()
