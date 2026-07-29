from __future__ import annotations

import unittest
from pathlib import Path

from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "config"
    / "connection_profiles.json"
)


class RfToOatofConnectionProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_connection_profile_registry(REGISTRY)

    def test_both_profiles_close_through_the_common_resolver(self) -> None:
        expectations = {
            "rf_quadrupole_grounded_connector_gap_1mm": (1.0, 1.0, 1),
            "rf_quadrupole_direct_mating_gap_0mm": (0.0, 0.0, 0),
        }
        for profile_id, expected in expectations.items():
            with self.subTest(profile_id=profile_id):
                resolved = resolve_connection_profile(
                    self.registry, profile_id, repo_root=REPO_ROOT
                )
                self.assertEqual(resolved["compatibility"]["status"], "pass")
                self.assertEqual(
                    resolved["spatial_registration"]["actual_gap_mm"],
                    expected[0],
                )
                self.assertEqual(resolved["connector"]["length_mm"], expected[1])
                self.assertEqual(
                    len(resolved["field_ownership_segments"]), expected[2]
                )

    def test_transition_aperture_is_materialized_in_downstream_frame(self) -> None:
        resolved = resolve_connection_profile(
            self.registry,
            "rf_quadrupole_grounded_connector_gap_1mm",
            repo_root=REPO_ROOT,
        )
        aperture = resolved["transition_aperture"]
        downstream = resolved["port_geometry"]["downstream"]
        self.assertEqual(
            aperture["coordinate_frame_id"],
            downstream["coordinate_frame"]["frame_id"],
        )
        self.assertEqual(
            aperture["center_mm"], downstream["mating_surface"]["center_mm"]
        )


if __name__ == "__main__":
    unittest.main()
