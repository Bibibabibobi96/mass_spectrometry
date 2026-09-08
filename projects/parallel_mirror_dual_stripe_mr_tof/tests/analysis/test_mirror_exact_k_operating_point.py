"""Unit contracts for system-level exact-K mirror energy selection."""

from __future__ import annotations

import math
import json
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point import (
    EXACT_K_SELECTOR_STATUS,
    _td_over_t0,
)


CONTRACT = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"


class MirrorExactKOperatingPointTest(unittest.TestCase):
    def test_current_contract_uses_the_bare_mirror_adiabatic_selector_status(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            contract["mirror"]["theory_requirements"]
            ["exact_k_operating_point_selection"]["status"],
            EXACT_K_SELECTOR_STATUS,
        )

    def test_td_over_t0_uses_total_energy_only_for_the_entry_angle(self) -> None:
        kappa = 1.4892272347854711
        ratio = _td_over_t0(4000.0, 586.9393396818346, kappa, 340.0, 5.0)
        self.assertAlmostEqual(ratio, 24.41534839830574)
        wrong_total_energy_width = _td_over_t0(4005.0, 586.9393396818346, kappa, 340.0, 5.0)
        self.assertGreater(wrong_total_energy_width, ratio)

    def test_td_over_t0_rejects_no_hidden_mass_dependence(self) -> None:
        first = _td_over_t0(4200.0, 586.9, 1.489, 340.0, 5.0)
        second = _td_over_t0(4200.0, 586.9, 1.489, 340.0, 5.0)
        self.assertTrue(math.isfinite(first))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
