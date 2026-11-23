from __future__ import annotations

import unittest
from pathlib import Path

from msplatform.workflows.rf_design_profiles import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[4] / "src" / "msplatform" / "components" / "rf_multipole"
REPO_ROOT = PROJECT_ROOT.parents[3]
FORBIDDEN = (
    "Adapter", "DesignRequestPath", "ResolvedDesignPath", "ParticleMassAmu",
    "FieldScreenRunId", "ConnectorLengthMm", "AxialAcceleration",
    "EndplateAcceleration",
)


class Phase4DesignConsumerTests(unittest.TestCase):
    def test_profile_and_thin_wrappers(self) -> None:
        for profile_id in (
            "no_acceleration_full_length",
            "segmented_rod_axial_acceleration",
        ):
            profile = resolve_design_profile(
                REPO_ROOT, "rf_multipole_ion_optics", ('hexapole_' + profile_id)
            )
            self.assertEqual(profile["profile"]["identity"]["electrode_count"], 6)

    def test_no_acceleration_profile_is_full_length_and_zero_reference(self) -> None:
        resolution = resolve_design_profile(
            REPO_ROOT, "rf_multipole_ion_optics", 'hexapole_no_acceleration_full_length'
        )
        compiled = resolution["resolved_design"]
        self.assertEqual(compiled["geometry_mm"]["rod_length"], 79.6)
        self.assertEqual(compiled["axial_drive"]["topology"], "none")
        self.assertEqual(compiled["axial_drive"]["predicted_energy_gain_eV"], 0.0)
        self.assertEqual(compiled["geometry_mm"]["observations"]["release_plane_z_mm"], -1.5)
        self.assertEqual(compiled["geometry_mm"]["observations"]["handoff_plane_z_mm"], 80.6)
        self.assertEqual(compiled["geometry_mm"]["observations"]["census_plane_z_mm"], 81.1)


if __name__ == "__main__":
    unittest.main()
