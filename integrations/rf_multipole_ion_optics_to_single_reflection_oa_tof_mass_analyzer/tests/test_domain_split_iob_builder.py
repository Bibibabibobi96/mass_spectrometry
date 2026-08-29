from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
BUILDER = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runtime"
    / "build_single_flight_domain_split_iob.lua"
)


class DomainSplitIobBuilderTests(unittest.TestCase):
    """Static contract for the non-runnable domain-split IOB structure."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = BUILDER.read_text(encoding="utf-8")

    def test_uses_the_existing_six_slot_container_and_exact_role_order(self) -> None:
        self.assertIn("six-instance container IOB is required", self.source)
        self.assertIn("SIMION container must contain exactly six instances", self.source)
        self.assertIn("for index=1,6 do", self.source)
        for argument, role in (
            (4, "coarse frontend PA0"),
            (5, "reflectron PA0"),
            (6, "accelerator-main PA0"),
            (7, "detector PA0"),
            (8, "upstream bridge PA0"),
            (9, "intermediate2 overlay PA0"),
        ):
            self.assertIn(f"assert(arg[{argument}], '{role} is required')", self.source)

    def test_preserves_only_reflectron_and_detector_formal_transforms_and_requires_explicit_local_origins(self) -> None:
        self.assertIn("for _,index in ipairs({2,4}) do", self.source)
        self.assertIn("coarse frontend origin x is invalid", self.source)
        self.assertIn("accelerator main origin z is invalid", self.source)
        self.assertIn("upstream bridge origin x is invalid", self.source)
        self.assertIn("intermediate2 overlay origin z is invalid", self.source)
        self.assertIn("item.pa:load(pa_paths[index])", self.source)
        self.assertIn("item.x,item.y,item.z=transform.x,transform.y,transform.z", self.source)

    def test_refuses_to_claim_a_runnable_or_superposed_field(self) -> None:
        self.assertIn("deliberately does not attach a Program/Fly2", self.source)
        self.assertIn("selects exactly one PA in every", self.source)
        self.assertIn("common bridge electrode bases before Refine", self.source)
        self.assertIn("STRUCTURAL_ONLY", self.source)
        self.assertNotIn("write_file(program", self.source)
        self.assertNotIn("wb:efield", self.source)


if __name__ == "__main__":
    unittest.main()
