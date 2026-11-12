"""Selected MR accelerator geometry is independent of numerical mesh."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest

from msplatform.backends.simion.mr_geometry import resolve_mr_geometry
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import (
    CandidateContractError, derive_compact_accelerator_acceptance_design,
    derive_two_zone_focus, derive_two_zone_placement, load_contract, validate_contract,
)
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider import resolve_component
from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority

PROJECT = Path(__file__).resolve().parents[2]


class Gap2FixedDesignTests(unittest.TestCase):
    def test_mesh_change_keeps_selected_design_focus_and_real_provider_geometry(self):
        original = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        before = copy.deepcopy(original)
        changed = copy.deepcopy(original)
        changed["simion"]["component_mesh_mm_per_gu"]["accelerator"][2] = .2
        # The explicit strategy still selects a new mesh-aligned design when asked.
        selected_new = derive_compact_accelerator_acceptance_design(changed)
        self.assertNotEqual(selected_new["gap2_mm"], original["accelerator"]["gap_2_mm"])
        explicit = derive_compact_accelerator_acceptance_design(
            original, selected_gap2_mm=original["accelerator"]["gap_2_mm"])
        no_numerics = copy.deepcopy(original)
        del no_numerics["simion"]
        self.assertEqual(explicit, derive_compact_accelerator_acceptance_design(
            no_numerics, selected_gap2_mm=original["accelerator"]["gap_2_mm"]))
        self.assertEqual(explicit["gap2_selection_rule"], "explicit_selected_physical_gap")
        self.assertNotIn("gap2_solver_quantization_mm", explicit)
        self.assertNotIn("gap2_solver_quantum_mm", explicit)
        self.assertEqual(validate_contract(changed), changed)
        self.assertEqual(changed["accelerator"]["gap_2_mm"], original["accelerator"]["gap_2_mm"])
        self.assertEqual(derive_two_zone_focus(changed), derive_two_zone_focus(original))
        self.assertEqual(derive_two_zone_placement(changed), derive_two_zone_placement(original))
        a, b = geometry_authority(original), geometry_authority(changed)
        def resolve(contract, authority):
            request = dict(contract=contract, accelerator_requirements=authority["accelerator_requirements"],
                           geometry_profile=authority["geometry_profile"])
            return resolve_component(request, geometry_profile_id=authority["geometry_profile_id"])
        self.assertEqual(resolve(original, a), resolve(changed, b))
        self.assertEqual(resolve_mr_geometry(original, accelerator_geometry_authority=a),
                         resolve_mr_geometry(changed, accelerator_geometry_authority=b))
        self.assertEqual(original, before)

    def test_bad_design_still_rejected_and_off_grid_keeps_the_selected_geometry(self):
        original = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        bad = copy.deepcopy(original)
        ideal = derive_compact_accelerator_acceptance_design(original)["ideal_gap2_mm"]
        bad["accelerator"]["gap_2_mm"] = ideal + 1
        with self.assertRaisesRegex(CandidateContractError, "exceeds the compact acceptance"):
            validate_contract(bad)
        bad = copy.deepcopy(original)
        bad["accelerator"]["repeller_v"] += 1
        with self.assertRaisesRegex(CandidateContractError, "repeller_v differs"):
            validate_contract(bad)
        changed = copy.deepcopy(original)
        changed["simion"]["component_mesh_mm_per_gu"]["accelerator"][2] = .13
        self.assertEqual(validate_contract(changed), changed)
        authority = geometry_authority(changed)
        # This pure result is not proof that SIMION can faithfully represent
        # the zero-thickness planes on the selected grid.
        resolve_mr_geometry(changed, accelerator_geometry_authority=authority)
        self.assertEqual(changed["accelerator"]["gap_2_mm"], original["accelerator"]["gap_2_mm"])


if __name__ == "__main__":
    unittest.main()
