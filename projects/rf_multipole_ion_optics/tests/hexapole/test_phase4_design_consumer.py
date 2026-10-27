from __future__ import annotations

import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
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
        for name in (
            "workflows/no_collision_transport/run_comsol.ps1",
            "workflows/no_collision_transport/run_simion.ps1",
            "analysis/run_round_rod_field_screen.ps1",
        ):
            source = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            for term in FORBIDDEN:
                self.assertNotIn(term, source)
            if name == "analysis/run_round_rod_field_screen.ps1":
                self.assertIn("DesignProfileId", source)
                self.assertNotIn("$DesignProfileId =", source)
                self.assertIn("ProjectId", source)
                self.assertNotIn("ProjectRoot", source)
            else:
                self.assertIn("RuntimeProfileId", source)
                self.assertIn("project_transport_launcher_support.ps1", source)
                self.assertIn("Invoke-MultipoleProjectFinite3dTransport", source)
                self.assertIn("rf_multipole_ion_optics", source)
                self.assertNotIn("ParticleSourcePath", source)
                self.assertNotIn("DesignProfileId", source)

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
