from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RUNTIME = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runtime"
)


class DomainSplitIobBuilderTests(unittest.TestCase):
    """Static topology checks for current split-domain IOB builders."""

    def test_each_builder_binds_the_instance_filename_before_loading(self) -> None:
        """A multi-slot seed shares its placeholder PA until its instances bind files."""
        for name in (
            "build_single_flight_pre_pulse_iob.lua",
            "build_single_flight_post_pulse_iob.lua",
            "build_single_flight_domain_split_main_only_iob.lua",
            "build_single_flight_full_iob.lua",
            "build_single_flight_overlay_iob.lua",
            "build_single_flight_two_overlay_iob.lua",
        ):
            source = RUNTIME.joinpath(name).read_text(encoding="utf-8")
            self.assertIn("item.filename=pa_paths[index]\n  item.pa:load()", source)
            self.assertNotIn("item.pa:load(pa_paths[index])", source)

    def test_continuous_full_flight_has_seven_consecutive_physical_slots(self) -> None:
        source = RUNTIME.joinpath("build_single_flight_full_iob.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("seven-instance container IOB is required", source)
        self.assertIn("full-flight container must contain exactly seven instances", source)
        self.assertIn("for index=1,7 do", source)
        self.assertIn("[1]=coarse_origin,[2]=upstream_origin,[3]=main_origin,[6]=local_origin", source)
        self.assertIn("for formal_index,slot in pairs({[1]=4,[2]=5,[4]=7})", source)
        self.assertIn(
            "ROLES=coarse_frontend,upstream_bridge,accelerator_main,flight_tube,reflectron,accelerator_entrance_aperture_local,detector",
            source,
        )
        self.assertNotIn("intermediate2 overlay", source)
        self.assertNotIn("for index=1,6 do", source)

    def test_pre_pulse_has_only_three_reachable_consecutive_roles(self) -> None:
        source = RUNTIME.joinpath("build_single_flight_pre_pulse_iob.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("pre-pulse container must contain exactly three instances", source)
        self.assertIn("for index=1,3 do", source)
        self.assertIn(
            "ROLES=coarse_frontend,upstream_bridge,accelerator_entrance_zero_field",
            source,
        )
        self.assertNotIn("reflectron PA0", source)
        self.assertNotIn("detector PA0", source)

    def test_post_pulse_has_only_main_local_and_downstream_roles(self) -> None:
        source = RUNTIME.joinpath("build_single_flight_post_pulse_iob.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("five-instance handoff consumer IOB", source)
        self.assertIn("SIMION container must contain exactly five instances", source)
        self.assertIn("for index=1,5 do", source)
        self.assertIn(
            "ROLES=flight_tube,reflectron,accelerator_main,detector,accelerator_entrance_local",
            source,
        )
        self.assertNotIn("upstream bridge PA0", source)
        self.assertNotIn("coarse frontend PA0", source)


if __name__ == "__main__":
    unittest.main()
