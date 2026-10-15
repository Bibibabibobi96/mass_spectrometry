"""Pure geometry regressions for the explicit P1-to-OA shield candidate."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, load_contract,
)


PROJECT = Path(__file__).resolve().parents[2]


class PrismShieldExitExtensionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        # Small solver-neutral fixture in the existing OA resolved projection.
        self.assembly = {
            "accelerator_iob_origin_mm": [0.0, -72.25, -6.0],
            "accelerator_resolved_electrodes": {
                "acceleration_direction": "-z",
                "local_to_pa_translation_mm": [0.0, 17.25, 0.0],
                "grid_supports": [
                    {"component_electrode_id": 23, "frame_outer_box_mm": {"z_min_mm": 35.5}},
                    {"component_electrode_id": 24, "frame_outer_box_mm": {"z_min_mm": 5.5}},
                ],
            },
        }

    def candidate(self) -> dict:
        contract = copy.deepcopy(self.contract)
        contract["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"] = {"clearance_mm": 1.0}
        return contract

    def test_default_geometry_is_unchanged_even_with_assembly(self) -> None:
        self.assertEqual(resolve_geometry(self.contract), resolve_geometry(self.contract, accelerator_assembly=self.assembly))

    def test_body_and_slot_extend_together_without_changing_other_solids(self) -> None:
        contract = self.candidate()
        original = copy.deepcopy(contract)
        baseline = resolve_geometry(self.contract)
        result = resolve_geometry(contract, accelerator_assembly=self.assembly)
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
        shield = resolve_geometry(self.candidate(), accelerator_assembly=assembly)["prism_ground_shields"][0]
        self.assertEqual(shield["rectangular_slots_mm"][0][5], -0.5)
        self.assertEqual(shield["extension_to_accelerator_exit"]["exit_support_downstream_z_mm"], 0.5)

    def test_missing_assembly_or_support_fails(self) -> None:
        for assembly in (None, {}, {"accelerator_resolved_electrodes": {}}):
            with self.subTest(assembly=assembly), self.assertRaises(CandidateContractError):
                resolve_geometry(self.candidate(), accelerator_assembly=assembly)

    def test_nonpositive_nonfinite_or_unknown_candidate_input_fails(self) -> None:
        for extension in ({"clearance_mm": 0}, {"clearance_mm": -1}, {"clearance_mm": float("nan")},
                          {"clearance_mm": float("inf")}, {"clearance_mm": 1, "end_z_mm": -1.5}, None):
            contract = self.candidate()
            contract["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"] = extension
            with self.subTest(extension=extension), self.assertRaises(CandidateContractError):
                resolve_geometry(contract, accelerator_assembly=self.assembly)

    def test_other_shield_and_nonextension_endpoint_fail(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["prisms"]["ground_shields"][1]["extension_to_accelerator_exit"] = {"clearance_mm": 1}
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract, accelerator_assembly=self.assembly)
        assembly = copy.deepcopy(self.assembly)
        assembly["accelerator_iob_origin_mm"][2] = -40
        with self.assertRaises(CandidateContractError):
            resolve_geometry(self.candidate(), accelerator_assembly=assembly)


if __name__ == "__main__":
    unittest.main()
