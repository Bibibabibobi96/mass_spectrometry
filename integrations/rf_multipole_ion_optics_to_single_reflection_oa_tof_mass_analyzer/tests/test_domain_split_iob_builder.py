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
        for argument, role, omitted_in_pre_pulse in (
            (4, "coarse frontend PA0", "false"),
            (5, "reflectron PA0", "true"),
            (6, "accelerator-main PA0", "false"),
            (7, "detector PA0", "true"),
            (8, "upstream bridge PA0", "false"),
            (9, "intermediate2 overlay PA0", "false"),
        ):
            self.assertIn(
                f"pa_argument({argument}, '{role}', {omitted_in_pre_pulse})",
                self.source,
            )

    def test_full_flight_preserves_formal_transforms_and_pre_pulse_omits_downstream_pas(self) -> None:
        self.assertIn("pre_pulse_reachable_v1", self.source)
        self.assertIn("pre_pulse_reachable=(build_mode=='pre_pulse_reachable_v1')", self.source)
        self.assertIn("for _,index in ipairs({2,4}) do", self.source)
        self.assertIn("coarse frontend origin x is invalid", self.source)
        self.assertIn("accelerator main origin z is invalid", self.source)
        self.assertIn("upstream bridge origin x is invalid", self.source)
        self.assertIn("intermediate2 overlay origin z is invalid", self.source)
        self.assertIn("item.pa:load(pa_paths[index])", self.source)
        self.assertIn("pre_pulse_reachable and (index==2 or index==4)", self.source)
        self.assertIn("item.x,item.y,item.z=transform.x,transform.y,transform.z", self.source)
        self.assertIn("ACTIVE_ROLES=coarse_frontend,accelerator_main,upstream,intermediate2", self.source)
        self.assertIn("OMITTED_ROLES=reflectron,detector", self.source)

    def test_refuses_to_claim_a_runnable_or_superposed_field(self) -> None:
        self.assertIn("deliberately does not attach a Program/Fly2", self.source)
        self.assertIn("selects exactly one PA in every", self.source)
        self.assertIn("common bridge electrode bases before Refine", self.source)
        self.assertIn("STRUCTURAL_ONLY", self.source)
        self.assertNotIn("write_file(program", self.source)
        self.assertNotIn("wb:efield", self.source)


if __name__ == "__main__":
    unittest.main()
