from __future__ import annotations

import unittest
from pathlib import Path

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
        for profile_id in ("baseline_finite_3d", "endplate_acceleration_reference"):
            profile = resolve_design_profile(
                REPO_ROOT, "rf_hexapole_ion_guide", profile_id
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
            self.assertIn("DesignProfileId", source)
            if name == "run_round_rod_field_screen.ps1":
                self.assertIn("baseline_finite_3d", source)
                self.assertIn("ProjectId", source)
                self.assertNotIn("ProjectRoot", source)
            else:
                self.assertIn("ParticleSourcePath", source)
                self.assertIn("endplate_acceleration_reference", source)


if __name__ == "__main__":
    unittest.main()
