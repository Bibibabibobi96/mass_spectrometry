from __future__ import annotations

import unittest
from pathlib import Path

from msplatform.workflows import rf_publication


PROJECT_ROOT = Path(rf_publication.__file__).resolve().parents[1] / "components" / "rf_multipole"
REPOSITORY_ROOT = Path(rf_publication.__file__).resolve().parents[3]
PROFILES = rf_publication.profile_paths(PROJECT_ROOT)
EXPECTED_IDENTITY = rf_publication.EXPECTED_IDENTITY


def resolve(profile: str) -> dict:
    return rf_publication.resolve(
        profile, project_root=PROJECT_ROOT, repository_root=REPOSITORY_ROOT, profiles=PROFILES
    )


class ResolvedDesignProfileTests(unittest.TestCase):
    def test_all_profiles_use_one_common_compiler_shape(self) -> None:
        publications = {
            profile: resolve(profile)
            for profile in PROFILES
        }
        official = publications["official"]
        self.assertEqual(
            official["role"], "multipole_resolved_design_do_not_edit"
        )
        self.assertEqual(official["identity"], EXPECTED_IDENTITY)
        for resolved in publications.values():
            self.assertEqual(
                resolved["geometry_mm"], official["geometry_mm"]
            )
            self.assertEqual(
                resolved["interfaces_mm"], official["interfaces_mm"]
            )
            self.assertEqual(resolved["segmentation"]["strategy"], "off")

    def test_mass_filter_is_only_an_explicit_request_overlay(self) -> None:
        official = resolve("official")
        mass_filter = resolve("mass_filter")
        self.assertEqual(
            official["drive"]["rf_amplitude_V_zero_to_peak_per_group"],
            mass_filter["drive"]["rf_amplitude_V_zero_to_peak_per_group"],
        )
        self.assertEqual(
            mass_filter["drive"]["dc_amplitude_V_per_group"],
            22.763014939677756,
        )
        self.assertEqual(
            mass_filter["drive"]["common_mode_offset_V"],
            -8.0,
        )

    def test_profiles_are_complete_requests_not_runtime_overlays(self) -> None:
        for profile in PROFILES.values():
            request = profile["request"]
            self.assertEqual(request.parent.name, "requests")
            self.assertNotIn("overlay", request.name)

    def test_interface_profile_reuses_official_publication(self) -> None:
        self.assertEqual(
            PROFILES["interface"]["output"],
            PROFILES["official"]["output"],
        )


if __name__ == "__main__":
    unittest.main()
