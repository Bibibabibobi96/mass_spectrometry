from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_IDS = ("rf_hexapole_ion_guide", "rf_octupole_ion_guide")


class RuntimeProfileTests(unittest.TestCase):
    def test_hexapole_and_octupole_profiles_freeze_one_shared_source(self) -> None:
        resolved = [
            resolve_runtime_profile(REPO_ROOT, project_id, "baseline_finite_3d")
            for project_id in PROJECT_IDS
        ]
        self.assertEqual(
            {item["particle_source"]["sha256"] for item in resolved},
            {"494CB26FA128C475CB2DC1DB1A3437342DFBB5D1C1900E811E4BEBF47D7A6385"},
        )
        self.assertEqual(
            {item["particle_source"]["path"] for item in resolved},
            {
                str(
                    (
                        REPO_ROOT
                        / "common/multipole/sources/hex_oct_baseline_fixed_100.csv"
                    ).resolve()
                )
            },
        )

    def test_project_wrappers_expose_profile_identity_not_free_parameters(self) -> None:
        forbidden = (
            "[string]$ParticleSourcePath",
            "[int]$MeshAutoLevel",
            "[double]$CellMm",
            "[int]$RfStepsPerPeriod",
            "[int]$TrajectoryQuality",
            "[double]$MaximumTimeUs",
            "[string]$TemplateIob",
        )
        for project_id in PROJECT_IDS:
            for name in (
                "run_finite_3d_transport.ps1",
                "run_simion_finite_3d_transport.ps1",
            ):
                source = (
                    REPO_ROOT / "projects" / project_id / "analysis" / name
                ).read_text(encoding="utf-8-sig")
                self.assertIn("[string]$RuntimeProfileId", source)
                for token in forbidden:
                    self.assertNotIn(token, source)

    def test_legacy_baseline_registration_is_identity_only(self) -> None:
        for project_id in (
            "rf_quadrupole_collision_cooling",
            *PROJECT_IDS,
        ):
            descriptor = json.loads(
                (
                    REPO_ROOT / "projects" / project_id / "config/project.json"
                ).read_text(encoding="utf-8-sig")
            )
            self.assertEqual(
                descriptor["contracts"]["baseline"], "config/baseline.json"
            )
        for project_id in PROJECT_IDS:
            for wrapper in (
                "run_finite_3d_transport.ps1",
                "run_simion_finite_3d_transport.ps1",
            ):
                source = (
                    REPO_ROOT / "projects" / project_id / "analysis" / wrapper
                ).read_text(encoding="utf-8-sig")
                self.assertNotIn("config\\baseline.json", source)

    def test_unknown_runtime_profile_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            resolve_runtime_profile(
                REPO_ROOT, "rf_hexapole_ion_guide", "not-a-profile"
            )


if __name__ == "__main__":
    unittest.main()
