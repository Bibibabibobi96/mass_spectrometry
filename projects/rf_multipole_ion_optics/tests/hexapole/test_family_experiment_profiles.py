from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import validate_schema
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
)
DESIGN_PROFILE_IDS = tuple(f"hexapole_{mode_id}" for mode_id in MODE_IDS)


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


class FamilyExperimentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolved = {
            mode_id: resolve_design_profile(
                REPO_ROOT, "rf_multipole_ion_optics", ('hexapole_' + mode_id)
            )["resolved_design"]
            for mode_id in MODE_IDS
        }

    def assert_contract_values(
        self, contract: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        for dotted_path, expected_value in expected.items():
            actual: Any = contract
            for key in dotted_path.split("."):
                actual = actual[key]
            self.assertEqual(actual, expected_value, dotted_path)

    def test_profiles_share_one_governed_base_catalog_and_envelope(self) -> None:
        registry = load("config/design_profiles.json")
        validate_schema(registry, "design_profiles.schema.json")
        current = [
            profile
            for profile in registry["profiles"]
            if profile["design_profile_id"] in DESIGN_PROFILE_IDS
        ]
        self.assertEqual({profile["mode_id"] for profile in current}, set(MODE_IDS))
        modes = load("config/operating_modes.json")
        self.assertEqual(modes["terminal_reference_V"], 0.0)
        self.assertEqual(
            [
                (
                    item["rod_entrance_relative_to_terminal_V"],
                    item["rod_exit_relative_to_terminal_V"],
                )
                for item in modes["modes"]
            ],
            [(0.0, 0.0), (3.0, 0.0)],
        )
        for key in ("design_request", "design_variables", "optimization_envelope"):
            self.assertEqual({profile[key] for profile in current}, {
                {
                    "design_request": "variants/hexapole/config/requests/mechanical_base.json",
                    "design_variables": "variants/hexapole/config/design_variables.json",
                    "optimization_envelope": "variants/hexapole/config/optimization_envelope.json",
                }[key]
            })
            self.assertEqual(len({profile["sha256"][key] for profile in current}), 1)
        aliases = {
            profile["design_profile_id"]: profile["mode_id"]
            for profile in registry["profiles"]
            if profile["structural_variant_id"] == "hexapole"
            and profile["design_profile_id"] not in DESIGN_PROFILE_IDS
        }
        self.assertEqual(aliases, {})

    def test_profile_source_hashes_use_canonical_repository_text(self) -> None:
        registry = load("config/design_profiles.json")
        current = [
            profile
            for profile in registry["profiles"]
            if profile["design_profile_id"] in DESIGN_PROFILE_IDS
        ]
        for field in ("design_request", "design_variables", "optimization_envelope"):
            for profile in current:
                path = PROJECT_ROOT / profile[field]
                self.assertEqual(
                    repository_text_sha256(path),
                    profile["sha256"][field],
                )

    def test_current_rod_modes_share_physical_geometry(self) -> None:
        baseline=self.resolved[MODE_IDS[0]]
        for resolved in self.resolved.values():
            self.assertEqual(resolved["geometry_mm"],baseline["geometry_mm"])
            self.assertEqual(resolved["geometry_mm"]["enclosure"],{"model":"bare"})
            self.assertNotIn("interfaces_mm",resolved)
            self.assertEqual(resolved["static_electrodes_V"],{"role":"bare_multipole_static_electrodes"})
            self.assertEqual(resolved["particle_source"],baseline["particle_source"])
            segments=resolved["segmentation"]["axial_acceleration"]["derived"]["segments"]
            self.assertEqual(len(segments),4)
            for row in segments:self.assertAlmostEqual(row["z_max_mm"]-row["z_min_mm"],19.6)
        self.assertEqual((baseline["geometry_mm"]["rod_z_min"],baseline["geometry_mm"]["rod_z_max"]),(0.,79.6))
        for mode,expected in ((MODE_IDS[0],[0.,0.,0.,0.]),(MODE_IDS[1],[3.,2.,1.,0.])):
            self.assertEqual([x["common_mode_V"] for x in self.resolved[mode]["segmentation"]["axial_acceleration"]["derived"]["segments"]],expected)

    def test_runtime_tiers_change_only_the_registered_numerical_axis(self) -> None:
        for mode_id in MODE_IDS:
            baseline = resolve_runtime_profile(
                REPO_ROOT, "rf_multipole_ion_optics", ('hexapole_' + mode_id)
            )
            spatial = resolve_runtime_profile(
                REPO_ROOT,
                "rf_multipole_ion_optics",
                ('hexapole_' + f"{mode_id}_n100_spatial_refined"),
            )
            temporal = resolve_runtime_profile(
                REPO_ROOT,
                "rf_multipole_ion_optics",
                ('hexapole_' + f"{mode_id}_n100_temporal_refined"),
            )
            statistical = resolve_runtime_profile(
                REPO_ROOT, "rf_multipole_ion_optics", ('hexapole_' + f"{mode_id}_n1000")
            )
            self.assertEqual(
                {
                    baseline["design_profile_id"],
                    spatial["design_profile_id"],
                    temporal["design_profile_id"],
                    statistical["design_profile_id"],
                },
                {f"hexapole_{mode_id}"},
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                spatial["particle_source"]["sha256"],
            )
            self.assertEqual(
                baseline["particle_source"]["profile_id"],
                "family_mother_sample_v1_n100",
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                temporal["particle_source"]["sha256"],
            )
            self.assertEqual(
                temporal["solver_numerics"]["comsol"]["values"]["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                0.35,
            )
            self.assertEqual(
                temporal["solver_numerics"]["comsol"]["values"]["trajectory"][
                    "rf_steps_per_period"
                ],
                160,
            )
            self.assertEqual(
                temporal["solver_numerics"]["simion"]["values"]["cell_mm_xyz"],
                {"x": 0.3, "y": 0.3, "z": 0.3},
            )
            self.assertEqual(
                temporal["solver_numerics"]["simion"]["values"]["trajectory"][
                    "rf_steps_per_period"
                ],
                80,
            )
            self.assertEqual(
                statistical["particle_source"]["sha256"],
                "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
            )
            self.assertEqual(
                statistical["particle_source"]["profile_id"],
                "family_mother_sample_v1_n1000",
            )
        runtime_profiles = load("config/runtime_profiles.json")
        self.assertNotIn("baseline_finite_3d", runtime_profiles["profiles"])
        self.assertNotIn(
            "exit_aperture_plate_acceleration_reference",
            runtime_profiles["profiles"],
        )


if __name__ == "__main__":
    unittest.main()
