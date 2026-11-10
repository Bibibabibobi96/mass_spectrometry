"""Pure geometry regressions for the explicit P1-to-OA shield candidate."""
from __future__ import annotations
from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority

import copy
import unittest
from pathlib import Path

from msplatform.backends.simion.mr_geometry import resolve_mr_geometry as resolve_geometry
from msplatform.backends.simion.two_zone_candidate import resolve_closed_two_zone_electrodes
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import (
    CandidateContractError, load_contract,
)


PROJECT = Path(__file__).resolve().parents[2]


class PrismShieldExitExtensionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        # Small solver-neutral fixture in the existing OA resolved projection.
        authority = geometry_authority(self.contract)
        oa = resolve_closed_two_zone_electrodes(
            authority["accelerator_requirements"],
            geometry_profile_id=authority["geometry_profile_id"],
            geometry_profile=authority["geometry_profile"],
        ).to_dict()
        # Preserve the original independently varied native-placement oracle.
        oa["local_to_pa_translation_mm"] = [0.0, 17.25, 0.0]
        self.assembly = {
            "accelerator_iob_origin_mm": [0.0, -72.25, -6.0],
            "accelerator_resolved_electrodes": oa,
        }

    def candidate(self) -> dict:
        contract = copy.deepcopy(self.contract)
        contract["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"] = {"clearance_mm": 1.0}
        return contract

    def test_default_geometry_is_unchanged_even_with_assembly(self) -> None:
        self.assertEqual(resolve_geometry(self.contract, accelerator_geometry_authority=geometry_authority(self.contract)), resolve_geometry(self.contract, accelerator_assembly=self.assembly, accelerator_geometry_authority=geometry_authority(self.contract)))

    def test_body_and_slot_extend_together_without_changing_other_solids(self) -> None:
        contract = self.candidate()
        original = copy.deepcopy(contract)
        baseline = resolve_geometry(self.contract, accelerator_geometry_authority=geometry_authority(self.contract))
        result = resolve_geometry(contract, accelerator_assembly=self.assembly, accelerator_geometry_authority=geometry_authority(contract))
        shield = result["prism_ground_shields"][0]
        self.assertEqual(max(p[1] for p in shield["outer_polygon_yz_mm"]), -1.5)
        self.assertEqual(max(p[1] for p in shield["body_sections"][0]["polygon_yz_mm"]), -1.5)
        self.assertEqual(shield["rectangular_slots_mm"], [[-2, -75, -100, 2, -35, -1.5]])
        self.assertEqual(shield["x"], [-12, 12])
        self.assertEqual(shield["prism_clearance_polygon_yz_mm"], baseline["prism_ground_shields"][0]["prism_clearance_polygon_yz_mm"])
        self.assertEqual(shield["extension_to_accelerator_exit"]["added_length_mm"], 28.5)
        self.assertEqual(shield["extension_to_accelerator_exit"]["exit_support_component_electrode_id"], 24)
        self.assertEqual(contract, original)
        result["prism_ground_shields"][0] = baseline["prism_ground_shields"][0]
        self.assertEqual(result, baseline)

    def test_endpoint_is_derived_from_support_and_both_translations(self) -> None:
        assembly = copy.deepcopy(self.assembly)
        assembly["accelerator_resolved_electrodes"]["local_to_pa_translation_mm"][2] = 2.0
        assembly["accelerator_iob_origin_mm"][2] = -7.0
        assembly["accelerator_resolved_electrodes"]["grid_supports"].reverse()
        shield = resolve_geometry(self.candidate(), accelerator_assembly=assembly, accelerator_geometry_authority=geometry_authority(self.candidate()))["prism_ground_shields"][0]
        self.assertEqual(shield["rectangular_slots_mm"][0][5], -0.5)
        self.assertEqual(shield["extension_to_accelerator_exit"]["exit_support_downstream_z_mm"], 0.5)

    def test_missing_assembly_or_support_fails(self) -> None:
        for assembly in (None, {}, {"accelerator_resolved_electrodes": {}}):
            with self.subTest(assembly=assembly), self.assertRaises(CandidateContractError):
                resolve_geometry(self.candidate(), accelerator_assembly=assembly, accelerator_geometry_authority=geometry_authority(self.candidate()))

    def test_nonpositive_nonfinite_or_unknown_candidate_input_fails(self) -> None:
        for extension in ({"clearance_mm": 0}, {"clearance_mm": -1}, {"clearance_mm": float("nan")},
                          {"clearance_mm": float("inf")}, {"clearance_mm": 1, "end_z_mm": -1.5}, None):
            contract = self.candidate()
            contract["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"] = extension
            with self.subTest(extension=extension), self.assertRaises(CandidateContractError):
                resolve_geometry(contract, accelerator_assembly=self.assembly, accelerator_geometry_authority=geometry_authority(contract))

    def test_other_shield_and_nonextension_endpoint_fail(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["prisms"]["ground_shields"][1]["extension_to_accelerator_exit"] = {"clearance_mm": 1}
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract, accelerator_assembly=self.assembly, accelerator_geometry_authority=geometry_authority(contract))
        assembly = copy.deepcopy(self.assembly)
        assembly["accelerator_iob_origin_mm"][2] = -40
        with self.assertRaises(CandidateContractError):
            resolve_geometry(self.candidate(), accelerator_assembly=assembly, accelerator_geometry_authority=geometry_authority(self.candidate()))


if __name__ == "__main__":
    unittest.main()
