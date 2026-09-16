from __future__ import annotations

import re
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
            self.assertIn("item.pa.filename=pa_paths[index]\n  item.pa:load()", source)
            self.assertNotIn("item.pa:load(pa_paths[index])", source)

    def test_continuous_full_flight_has_seven_consecutive_physical_slots(self) -> None:
        source = RUNTIME.joinpath("build_single_flight_full_iob.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("seven-instance container IOB is required", source)
        self.assertIn("full-flight container must contain exactly seven instances", source)
        self.assertIn("for index=1,7 do", source)
        self.assertIn(
            "local pa_paths={flight_path,coarse_path,main_path,upstream_path,reflectron_path,local_path,detector_path}",
            source,
        )
        self.assertEqual(
            re.findall(
                r"local (coarse|upstream|main|local)_origin=origin\((\d+), '([^']+)'\)",
                source,
            ),
            [
                ("coarse", "11", "coarse frontend"),
                ("upstream", "14", "upstream bridge"),
                ("main", "17", "accelerator main"),
                ("local", "20", "accelerator entrance local"),
            ],
        )
        self.assertIn("[2]=coarse_origin,[3]=main_origin,[4]=upstream_origin,[6]=local_origin", source)
        self.assertIn("for formal_index,slot in pairs({[1]=1,[2]=5,[4]=7})", source)
        self.assertIn(
            "ROLES=flight_tube,coarse_frontend,accelerator_main,upstream_bridge,reflectron,accelerator_entrance_aperture_local,detector",
            source,
        )
        self.assertNotIn("intermediate2 overlay", source)
        self.assertNotIn("for index=1,6 do", source)

    def test_pre_pulse_has_only_four_reachable_consecutive_roles(self) -> None:
        source = RUNTIME.joinpath("build_single_flight_pre_pulse_iob.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("pre-pulse container must contain exactly four instances", source)
        self.assertIn("for index=1,4 do", source)
        self.assertEqual(
            re.findall(
                r"assert\(arg\[(\d+)\], '([^']+ PA0 is required)'\)", source
            ),
            [
                ("3", "coarse frontend PA0 is required"),
                ("4", "accelerator-main PA0 is required"),
                ("5", "upstream bridge PA0 is required"),
                ("6", "field-bearing entrance-local PA0 is required"),
            ],
        )
        self.assertEqual(
            re.findall(
                r"assert\(tonumber\(arg\[(\d+)\]\), '([^']+ origin [xyz] is invalid)'\)",
                source,
            ),
            [
                (str(index), f"{role} origin {axis} is invalid")
                for role, first_index in (
                    ("coarse", 7),
                    ("accelerator-main", 10),
                    ("upstream", 13),
                    ("entrance-local", 16),
                )
                for index, axis in zip(range(first_index, first_index + 3), "xyz")
            ],
        )
        self.assertIn(
            "ROLES=coarse_frontend,accelerator_main,upstream_bridge,accelerator_entrance_aperture_local",
            source,
        )
        self.assertIn("coarse < main <\n-- upstream < local priority", source)
        self.assertLess(
            source.index("'accelerator-main PA0 is required'"),
            source.index("'upstream bridge PA0 is required'"),
        )
        self.assertIn("the already-refined accelerator-main PA", source)
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
