from __future__ import annotations

import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile import REGIONS


PROJECT = Path(__file__).resolve().parents[2]


class MirrorRealFieldProfileTest(unittest.TestCase):
    def test_regions_cover_axis_once_without_gaps(self) -> None:
        values = [z for _, _, lower, upper in REGIONS for z in range(lower, upper + 1)]
        self.assertEqual(values, list(range(-319, 320)))
        self.assertEqual(len(values), len(set(values)))

    def test_fixed_quarter_mm_runner_refines_only_two_operating_points(self) -> None:
        source = (PROJECT / "simion" / "run_mirror_turn_fixed_grid_validation.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_dirichlet_patch_operating_pa.lua", source)
        self.assertIn("mirror_turn_negative", source)
        self.assertIn("mirror_turn_positive", source)
        self.assertIn("response_family_not_built=$true", source)
        self.assertNotIn("--lua-output", source)
        self.assertNotIn("build_component_basis.lua", source)


if __name__ == "__main__":
    unittest.main()
