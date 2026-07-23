from __future__ import annotations

import unittest

from projects.rf_quadrupole_collision_cooling.analysis import resolve_contract


class ResolvedDesignProfileTests(unittest.TestCase):
    def test_all_profiles_use_one_common_compiler_shape(self) -> None:
        publications = {
            profile: resolve_contract.resolve(profile)
            for profile in resolve_contract.PROFILES
        }
        official = publications["official"]
        self.assertEqual(
            official["role"], "multipole_resolved_design_do_not_edit"
        )
        self.assertEqual(official["identity"], resolve_contract.EXPECTED_IDENTITY)
        for resolved in publications.values():
            self.assertEqual(
                resolved["geometry_mm"], official["geometry_mm"]
            )
            self.assertEqual(
                resolved["interfaces_mm"], official["interfaces_mm"]
            )
            self.assertEqual(resolved["segmentation"]["strategy"], "off")

    def test_mass_filter_is_only_an_explicit_request_overlay(self) -> None:
        official = resolve_contract.resolve("official")
        mass_filter = resolve_contract.resolve("mass_filter")
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
        for profile in resolve_contract.PROFILES.values():
            request = profile["request"]
            self.assertEqual(request.parent.name, "requests")
            self.assertNotIn("overlay", request.name)

    def test_interface_profile_reuses_official_publication(self) -> None:
        self.assertEqual(
            resolve_contract.PROFILES["interface"]["output"],
            resolve_contract.PROFILES["official"]["output"],
        )


if __name__ == "__main__":
    unittest.main()
