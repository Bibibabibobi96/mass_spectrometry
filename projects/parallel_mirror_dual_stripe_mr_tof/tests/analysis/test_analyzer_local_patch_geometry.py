from __future__ import annotations

from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry import (
    build_local_patch_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AnalyzerLocalPatchGeometryTest(unittest.TestCase):
    def test_emits_contract_derived_half_mesh_patch(self) -> None:
        text = build_local_patch_gem(CONTRACT, "central_transport", 0.5)
        self.assertIn("pa_define(117,955,415,planar,none,electrostatic,, 0.5,0.5,0.5,surface=none)", text)
        self.assertIn("locate(29,82,105)", text)
        self.assertIn("e(11)", text)
        self.assertIn("e(16)", text)
        self.assertIn("e(20)", text)

    def test_emits_positive_mirror_patch_from_same_geometry(self) -> None:
        text = build_local_patch_gem(CONTRACT, "mirror_turn_positive", 1.0)
        self.assertIn("pa_define(41,611,234,planar,none,electrostatic,, 1,1,1,surface=none)", text)
        self.assertIn("locate(20,147,-97)", text)
        self.assertIn("e(5)", text)

    def test_emits_negative_bridge_from_original_geometry(self) -> None:
        text = build_local_patch_gem(CONTRACT, "stripe_mirror_bridge_negative", 1.0)
        self.assertIn("pa_define(41,611,124,planar,none,electrostatic,, 1,1,1,surface=none)", text)
        self.assertIn("locate(20,147,165)", text)
        self.assertIn("e(16)", text)

    def test_rejects_undeclared_scale(self) -> None:
        with self.assertRaises(CandidateContractError):
            build_local_patch_gem(CONTRACT, "central_transport", 0.75)


if __name__ == "__main__":
    unittest.main()
