from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
BUILDER = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runtime"
    / "build_single_flight_two_overlay_iob.lua"
)


class TwoOverlayIobBuilderContractTests(unittest.TestCase):
    """Static guardrails for the candidate-only six-instance IOB builder."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = BUILDER.read_text(encoding="utf-8")

    def test_requires_six_slot_container_and_all_physical_and_overlay_pas(self) -> None:
        self.assertIn("six-instance container IOB is required", self.source)
        self.assertIn("SIMION container must contain exactly six instances", self.source)
        self.assertIn("assert(#simion.wb.instances==6", self.source)
        for argument, role in (
            (4, "flight-tube PA0"),
            (5, "reflectron PA0"),
            (6, "accelerator PA0"),
            (7, "detector PA0"),
            (8, "entrance overlay PA0"),
            (9, "intermediate overlay PA0"),
        ):
            self.assertIn(f"assert(arg[{argument}], '{role} is required')", self.source)
        self.assertIn("for index=1,6 do", self.source)
        self.assertIn("item.pa.filename=pa_paths[index]", self.source)
        self.assertIn("item.pa:load()", self.source)

    def test_requires_two_explicit_local_origins(self) -> None:
        for argument, label in (
            (10, "entrance overlay origin x"),
            (11, "entrance overlay origin y"),
            (12, "entrance overlay origin z"),
            (13, "intermediate overlay origin x"),
            (14, "intermediate overlay origin y"),
            (15, "intermediate overlay origin z"),
        ):
            self.assertIn(
                f"assert(tonumber(arg[{argument}]), '{label} is invalid')",
                self.source,
            )
        self.assertIn("ENTRANCE_ORIGIN=", self.source)
        self.assertIn("INTERMEDIATE_ORIGIN=", self.source)

    def test_program_and_fly2_are_an_all_or_nothing_pair(self) -> None:
        self.assertIn("local program_path=arg[16]", self.source)
        self.assertIn("local fly2_path=arg[17]", self.source)
        self.assertIn(
            "same-basename Program and Fly2 must either both be supplied or both be omitted",
            self.source,
        )
        self.assertIn("write_file(program_path,program,'Program')", self.source)
        self.assertIn("write_file(fly2_path,fly2,'Fly2')", self.source)

    def test_preserves_formal_as_read_only_transform_source(self) -> None:
        self.assertIn("Formal IOB remains the sole source of the four physical placements.", self.source)
        self.assertIn("formal single-flight IOB must contain four or five instances", self.source)
        self.assertIn("for index=1,4 do", self.source)
        self.assertIn("simion.command('\"'..formal..'\"')", self.source)
        self.assertIn("simion.command('\"'..container..'\"')", self.source)
        self.assertIn("simion.wb:save(output)", self.source)
        self.assertNotIn("simion.wb:save(formal)", self.source)
        self.assertIn("for index=1,6 do", self.source)
        self.assertIn("item.pa.filename=pa_paths[index]", self.source)
        self.assertIn("item.pa:load()", self.source)
        self.assertIn("item.x,item.y,item.z=transform.x,transform.y,transform.z", self.source)


if __name__ == "__main__":
    unittest.main()
