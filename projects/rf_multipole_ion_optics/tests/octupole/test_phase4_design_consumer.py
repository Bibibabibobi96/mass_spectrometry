from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile
from common.contracts.particle_count_policy import validate_prefix_particle_sources


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
)
N100_TIER_SUFFIXES = (
    "",
    "_n100_spatial_refined",
    "_n100_temporal_refined",
)
HYBRID_RUNTIME_IDS = {
    "no_acceleration_full_length_n100_hybrid_exit025_temporal_coarse",
    "no_acceleration_full_length_n100_hybrid_exit025_temporal_refined",
    "no_acceleration_full_length_n100_hybrid_exit020_spatial_temporal_refined",
}


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


class CurrentRuntimeConsumerTests(unittest.TestCase):
    def test_family_runtime_profiles_resolve_without_free_numerics(self) -> None:
        registry = load("config/runtime_profiles.json")
        expected_ids = {
            f"{mode_id}{suffix}"
            for mode_id in MODE_IDS
            for suffix in N100_TIER_SUFFIXES
        }
        expected_ids |= {f"{mode_id}_n1000" for mode_id in MODE_IDS}
        expected_ids |= HYBRID_RUNTIME_IDS
        self.assertTrue({f"octupole_{name}" for name in expected_ids}.issubset(registry["profiles"]))
        source_identities = set()
        for runtime_id in sorted(expected_ids):
            resolved = resolve_runtime_profile(
                REPO_ROOT,
                "rf_multipole_ion_optics",
                ('octupole_' + runtime_id),
            )
            source_identities.add(
                (
                    resolved["particle_source"]["path"],
                    resolved["particle_source"]["sha256"],
                )
            )
        self.assertEqual(
            source_identities,
            {
                (
                    str(
                        REPO_ROOT
                        / "projects/rf_multipole_ion_optics/config/sources/"
                        "rf_multipole_family_mother_sample_v1_100.csv"
                    ),
                    "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
                ),
                (
                    str(
                        REPO_ROOT
                        / "projects/rf_multipole_ion_optics/config/sources/"
                        "rf_multipole_family_mother_sample_v1_1000.csv"
                    ),
                    "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
                ),
            },
        )

    def test_three_tiers_isolate_spatial_then_time_refinement(self) -> None:
        comsol = load("config/comsol_solver_numerics.json")["profiles"]
        simion = load("config/simion_solver_numerics.json")["profiles"]
        self.assertEqual(
            {
                profile["electric_potential_element_order"]
                for profile in comsol.values()
            },
            {"quadratic"},
        )
        self.assertEqual(
            (
                comsol['octupole_baseline_finite_3d']["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                comsol['octupole_n100_spatial_refined']["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                comsol['octupole_baseline_finite_3d']["trajectory"]["rf_steps_per_period"],
                comsol['octupole_n100_temporal_refined']["trajectory"][
                    "rf_steps_per_period"
                ],
            ),
            (0.5, 0.35, 80, 160),
        )
        self.assertEqual(
            (
                simion['octupole_baseline_finite_3d']["cell_mm"],
                simion['octupole_n100_spatial_refined']["cell_mm"],
                simion['octupole_baseline_finite_3d']["trajectory"]["rf_steps_per_period"],
                simion['octupole_n100_temporal_refined']["trajectory"][
                    "rf_steps_per_period"
                ],
            ),
            (0.4, 0.3, 40, 80),
        )
        self.assertEqual(
            comsol['octupole_n100_spatial_refined']["mesh"],
            comsol['octupole_n100_temporal_refined']["mesh"],
        )
        self.assertEqual(
            simion['octupole_n100_spatial_refined']["cell_mm"],
            simion['octupole_n100_temporal_refined']["cell_mm"],
        )

    def test_family_n100_is_the_exact_registered_n1000_prefix(self) -> None:
        profiles = load("config/particle_source_profiles.json")["profiles"]
        n100 = profiles['family_mother_sample_v1_n100']
        n1000 = profiles['family_mother_sample_v1_n1000']
        self.assertEqual(
            n100["sha256"],
            "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
        )
        self.assertEqual(
            n1000["sha256"],
            "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
        )
        validate_prefix_particle_sources(
            REPO_ROOT / n100["path"],
            REPO_ROOT / n1000["path"],
            expected_n100_sha256=n100["sha256"],
            expected_n1000_sha256=n1000["sha256"],
        )

    def test_volume_snapshot_runtime_binds_csv_and_generator_receipt(self) -> None:
        resolved = resolve_runtime_profile(
            REPO_ROOT,
            "rf_multipole_ion_optics",
            'octupole_no_acceleration_full_length_volume_snapshot_n100',
        )
        source = resolved["particle_source"]
        self.assertEqual(source["profile_id"], "octupole_continuous_axial_volume_snapshot_v1_n100")
        self.assertIn("volume_snapshot_receipt", source)
        receipt = source["volume_snapshot_receipt"]
        self.assertTrue(Path(receipt["path"]).is_file())
        self.assertRegex(receipt["sha256"], r"^[A-F0-9]{64}$")





    def test_design_profile_registry_contains_only_typed_modes(self) -> None:
        profiles = [profile for profile in load("config/design_profiles.json")["profiles"]
                    if profile["structural_variant_id"] == "octupole"]
        self.assertEqual(
            {profile["design_profile_id"] for profile in profiles},
            {f"octupole_{name}" for name in MODE_IDS} | {"octupole_grounded_shell_no_acceleration"},
        )
        self.assertEqual({profile["mode_id"] for profile in profiles}, set(MODE_IDS))


    def test_wrappers_delegate_registered_runtime_profile_resolution(self) -> None:
        runtime_ids = set(load("config/runtime_profiles.json")["profiles"])
        for name in (
            "workflows/no_collision_transport/run_comsol.ps1",
            "workflows/no_collision_transport/run_simion.ps1",
        ):
            source = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            self.assertIn("RuntimeProfileId", source)
            self.assertIn("project_transport_launcher_support.ps1", source)
            self.assertIn("Invoke-MultipoleProjectFinite3dTransport", source)
            self.assertIn("rf_multipole_ion_optics", source)
            self.assertNotIn("MeshAutoLevel", source)
            self.assertNotIn("CellMm", source)
            self.assertEqual(
                {
                    runtime_id
                    for runtime_id in runtime_ids
                    if f"'{runtime_id}'" in source
                },
                set(),
            )


if __name__ == "__main__":
    unittest.main()
