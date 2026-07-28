from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_IDS = (
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
)
HIGH_ORDER_PROJECT_IDS = PROJECT_IDS[1:]


class RuntimeProfileTests(unittest.TestCase):
    def test_multipole_family_profiles_freeze_one_shared_source(self) -> None:
        resolved = [
            resolve_runtime_profile(
                REPO_ROOT,
                project_id,
                "no_acceleration_full_length",
            )
            for project_id in PROJECT_IDS
        ]
        self.assertEqual(
            {item["particle_source"]["sha256"] for item in resolved},
            {"0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F"},
        )
        self.assertEqual(
            {item["particle_source"]["path"] for item in resolved},
            {
                str(
                    (
                        REPO_ROOT
                        / "common/multipole/sources/"
                        "rf_multipole_family_mother_sample_v1_100.csv"
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
        for project_id in HIGH_ORDER_PROJECT_IDS:
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
        for project_id in PROJECT_IDS:
            descriptor = json.loads(
                (
                    REPO_ROOT / "projects" / project_id / "config/project.json"
                ).read_text(encoding="utf-8-sig")
            )
            self.assertEqual(
                descriptor["contracts"]["baseline"], "config/baseline.json"
            )
        for project_id in HIGH_ORDER_PROJECT_IDS:
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
                REPO_ROOT, "rf_hexapole_ion_optics", "not-a-profile"
            )

    def test_quadrupole_uses_the_same_governed_runtime_chain(self) -> None:
        resolved = resolve_runtime_profile(
            REPO_ROOT,
            "rf_quadrupole_ion_optics",
            "no_acceleration_full_length",
        )
        self.assertEqual(
            resolved["design_profile_id"],
            "no_acceleration_full_length",
        )
        self.assertEqual(
            resolved["particle_source"]["sha256"],
            "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
        )
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            source = (
                REPO_ROOT
                / "projects/rf_quadrupole_ion_optics/workflows/no_collision_transport"
                / name
            ).read_text(encoding="utf-8-sig")
            self.assertIn("[string]$RuntimeProfileId", source)
            self.assertNotIn("[string]$ParticleSourcePath", source)


if __name__ == "__main__":
    unittest.main()
