from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
            "exit_aperture_plate_acceleration",
        ):
            profile = resolve_design_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", profile_id
            )
            self.assertEqual(profile["profile"]["identity"]["electrode_count"], 6)
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
            "run_round_rod_field_screen.ps1",
        ):
            source = (PROJECT_ROOT / "analysis" / name).read_text(encoding="utf-8")
            for term in FORBIDDEN:
                self.assertNotIn(term, source)
            if name == "run_round_rod_field_screen.ps1":
                self.assertIn("DesignProfileId", source)
                self.assertIn("no_acceleration_full_length", source)
                self.assertIn("ProjectId", source)
                self.assertNotIn("ProjectRoot", source)
            else:
                self.assertIn("RuntimeProfileId", source)
                self.assertIn("project_transport_launcher_support.ps1", source)
                self.assertIn("Invoke-MultipoleProjectFinite3dTransport", source)
                self.assertIn("rf_hexapole_ion_optics", source)
                self.assertNotIn("ParticleSourcePath", source)
                self.assertNotIn("DesignProfileId", source)

    def test_no_acceleration_profile_is_full_length_and_zero_reference(self) -> None:
        resolution = resolve_design_profile(
            REPO_ROOT, "rf_hexapole_ion_optics", "no_acceleration_full_length"
        )
        compiled = resolution["resolved_design"]
        self.assertEqual(compiled["geometry_mm"]["rod_length"], 79.6)
        self.assertEqual(compiled["axial_drive"]["topology"], "none")
        self.assertEqual(compiled["axial_drive"]["predicted_energy_gain_eV"], 0.0)
        self.assertEqual(compiled["interfaces_mm"]["entrance"]["release_plane_z_mm"], -1.5)
        self.assertEqual(compiled["interfaces_mm"]["exit"]["handoff_plane_z_mm"], 80.6)
        self.assertEqual(compiled["interfaces_mm"]["exit"]["census_plane_z_mm"], 81.1)
        evidence = json.loads(
            (PROJECT_ROOT / "config/evidence/no_acceleration_full_length.json").read_text(
                encoding="utf-8"
            )
        )
        validate_schema(evidence, "multipole_evidence_contract.schema.json")
        self.assertEqual(evidence["design_profile_id"], "no_acceleration_full_length")


if __name__ == "__main__":
    unittest.main()
