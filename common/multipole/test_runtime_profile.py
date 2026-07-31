from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile
from common.multipole.simion_numerics import normalize_simion_solver_numerics


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_IDS = (
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
)
HIGH_ORDER_PROJECT_IDS = PROJECT_IDS[1:]


class RuntimeProfileTests(unittest.TestCase):
    def test_legacy_scalar_simion_cells_normalize_to_canonical_xyz(self) -> None:
        resolved = resolve_runtime_profile(
            REPO_ROOT,
            "rf_hexapole_ion_optics",
            "no_acceleration_full_length",
        )
        numerics = resolved["solver_numerics"]["simion"]["values"]
        self.assertNotIn("cell_mm", numerics)
        self.assertEqual(
            numerics["cell_mm_xyz"],
            {"x": 0.4, "y": 0.4, "z": 0.4},
        )

    def test_simion_cell_forms_are_mutually_exclusive_and_fail_closed(self) -> None:
        canonical = normalize_simion_solver_numerics(
            {
                "cell_mm_xyz": {"x": 0.2, "y": 0.3, "z": 0.4},
                "trajectory_quality": 10,
            }
        )
        self.assertEqual(
            canonical["cell_mm_xyz"],
            {"x": 0.2, "y": 0.3, "z": 0.4},
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            normalize_simion_solver_numerics(
                {
                    "cell_mm": 0.4,
                    "cell_mm_xyz": {"x": 0.4, "y": 0.4, "z": 0.4},
                }
            )
        for invalid in (
            {"cell_mm_xyz": {"x": 0.2, "y": 0.3}},
            {"cell_mm_xyz": {"x": 0.2, "y": 0.3, "z": 0.0}},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_simion_solver_numerics(invalid)

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

    def test_registration_identity_comes_from_all_design_profiles(self) -> None:
        for project_id in PROJECT_IDS:
            project_root = REPO_ROOT / "projects" / project_id
            descriptor = json.loads(
                (project_root / "config/project.json").read_text(encoding="utf-8-sig")
            )
            self.assertIsNone(descriptor["contracts"]["baseline"])
            profiles = json.loads(
                (project_root / descriptor["contracts"]["design_profiles"]).read_text(
                    encoding="utf-8-sig"
                )
            )
            identities = {
                json.dumps(profile["identity"], sort_keys=True)
                for profile in profiles["profiles"]
            }
            self.assertEqual(len(identities), 1)
            identity = json.loads(next(iter(identities)))
            self.assertEqual(identity["project_id"], descriptor["project_id"])
            self.assertEqual(identity["family_id"], descriptor["family_id"])
            self.assertEqual(
                identity["electrode_count"],
                2 * identity["radial_order_n"],
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

    def test_runtime_stop_stage_is_explicit_or_normalized_to_transport(self) -> None:
        normal = resolve_runtime_profile(
            REPO_ROOT,
            "rf_hexapole_ion_optics",
            "no_acceleration_full_length",
        )
        self.assertEqual(normal["stop_stage"], "transport")
        registry_path = (
            REPO_ROOT
            / "projects/rf_hexapole_ion_optics/config/runtime_profiles.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        special_profiles = [
            profile
            for profile in registry["profiles"].values()
            if profile.get("stop_stage", "transport") != "transport"
        ]
        for profile in special_profiles:
            self.assertIn(profile["stop_stage"], {"mesh_build", "field_solve"})

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

    def test_hybrid_profiles_bind_their_separate_campaign_budget(self) -> None:
        for project_id in (
            "rf_quadrupole_ion_optics",
            "rf_octupole_ion_optics",
        ):
            baseline = resolve_runtime_profile(
                REPO_ROOT,
                project_id,
                "no_acceleration_full_length",
            )
            hybrid = resolve_runtime_profile(
                REPO_ROOT,
                project_id,
                (
                    "no_acceleration_full_length_n100_"
                    "hybrid_exit025_temporal_refined"
                ),
            )
            self.assertTrue(
                baseline["engineering_budget"]["path"].endswith(
                    "engineering_budget.json"
                )
            )
            self.assertIn(
                "comsol_hybrid_no_acceleration_particle_convergence_budget",
                hybrid["engineering_budget"]["path"],
            )
            self.assertNotEqual(
                baseline["engineering_budget"]["path"],
                hybrid["engineering_budget"]["path"],
            )


if __name__ == "__main__":
    unittest.main()
