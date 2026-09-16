from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_z_compression_plan import (
    derive_local_z_compression_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AnalyzerLocalZCompressionPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = derive_local_z_compression_plan(CONTRACT, 0.5)

    def test_compares_tightened_and_both_merged_three_region_candidates(self) -> None:
        current = self.plan["current_five_region_reference"]
        schemes = {item["scheme_id"]: item for item in self.plan["schemes"]}
        tightened = schemes["A_tightened_five_region"]
        merged = schemes["B_merged_three_region"]
        wide = schemes["C_wide_merged_three_region"]
        self.assertEqual(current["total_grid_points_per_array"], 187_600_653)
        self.assertEqual(current["local_interface_count"], 4)
        self.assertEqual(tightened["region_count"], 5)
        self.assertEqual(tightened["local_interface_count"], 4)
        self.assertEqual(tightened["total_grid_points_per_array"], 142_921_611)
        self.assertAlmostEqual(tightened["grid_point_savings_fraction_vs_current"], 0.2381603757)
        self.assertEqual(merged["region_count"], 3)
        self.assertEqual(merged["local_interface_count"], 2)
        self.assertEqual(merged["total_grid_points_per_array"], 138_767_769)
        self.assertAlmostEqual(merged["grid_point_savings_fraction_vs_current"], 0.2603023136)
        self.assertLess(merged["estimated_pa0_bytes_total"], tightened["estimated_pa0_bytes_total"])
        self.assertEqual(wide["region_count"], 3)
        self.assertEqual(wide["local_interface_count"], 2)
        self.assertEqual(wide["total_grid_points_per_array"], 160_501_779)
        self.assertEqual(wide["estimated_pa0_bytes_total"], 1_284_014_232)
        self.assertEqual(wide["estimated_family_bytes_total"], 12_840_142_320)
        self.assertAlmostEqual(wide["grid_point_savings_fraction_vs_current"], 0.1444497850)

    def test_uses_contract_margin_around_half_open_responsibility_planes(self) -> None:
        self.assertEqual(self.plan["derivation_authorities"]["dirichlet_guard_z_mm"], 5.0)
        intervals = self.plan["instance_adjust_responsibility_intervals"]
        self.assertEqual(
            intervals["current_and_scheme_A_half_open_z_mm"]["central_transport"],
            [-72.0, 72.0],
        )
        tightened = self.plan["schemes"][0]
        boxes = {item["region"]: item["box_project_mm"] for item in tightened["regions"]}
        self.assertEqual(boxes["central_transport"][2:6:3], [-77.0, 77.0])
        self.assertEqual(boxes["stripe_mirror_bridge_positive"][2:6:3], [67.0, 136.0])

    def test_reports_material_cut_but_vacuum_nominal_portals(self) -> None:
        for handoff in self.plan["handoff_vacuum_audit"]:
            self.assertTrue(handoff["inside_current_adjacent_patch_overlap"])
            self.assertTrue(handoff["nominal_beam_axis_is_vacuum"])
            self.assertTrue(handoff["nominal_beam_axis_apertures"])
            self.assertFalse(handoff["full_xy_plane_is_vacuum"])
            self.assertIsNotNone(handoff["full_xy_plane_material_witness"])
            self.assertTrue(handoff["full_xy_plane_crosses_physical_envelopes"])
        for scheme in self.plan["schemes"]:
            for boundary in scheme["boundary_audit"]:
                self.assertTrue(boundary["cuts_physical_electrode"])
                self.assertIsNotNone(boundary["physical_electrode_witness"])
                self.assertTrue(boundary["nominal_beam_axis_is_vacuum"])
        self.assertFalse(self.plan["acceptance_boundary"]["build_authorized"])

    def test_wide_merge_is_union_only_and_adds_no_z_boundary(self) -> None:
        source = self.plan["current_five_region_reference"]["regions"]
        wide = self.plan["schemes"][2]
        boxes = {item["region"]: item["box_project_mm"] for item in wide["regions"]}
        self.assertEqual(boxes["negative_mirror_bridge_merged"][2:6:3], [-330.0, -42.0])
        self.assertEqual(
            boxes["central_transport"], source["central_transport"]["box_project_mm"]
        )
        self.assertEqual(boxes["positive_mirror_bridge_merged"][2:6:3], [42.0, 330.0])
        self.assertEqual(wide["new_z_boundary_locations_vs_current_mm"], [])
        self.assertFalse(wide["introduces_new_z_boundary_cut_risk"])
        self.assertTrue(all(item["cuts_physical_electrode"] for item in wide["boundary_audit"]))

    def test_three_region_candidate_declares_program_and_iob_change(self) -> None:
        merged = self.plan["schemes"][1]
        self.assertIn("three-local-instance IOB seed", merged["implementation_impact"])
        self.assertIn("Lua instance-count", merged["implementation_impact"])

    def test_rejects_scale_not_declared_by_contract(self) -> None:
        with self.assertRaises(CandidateContractError):
            derive_local_z_compression_plan(CONTRACT, 0.3)

    def test_guard_is_derived_from_changed_contract_margin(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        changed = copy.deepcopy(document)
        changed["simion"]["analyzer_spatial_convergence"]["patch_margin_mm"][2] = 6.0
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            plan = derive_local_z_compression_plan(path, 0.5)
        self.assertEqual(plan["derivation_authorities"]["dirichlet_guard_z_mm"], 6.0)
        boxes = {item["region"]: item["box_project_mm"] for item in plan["schemes"][0]["regions"]}
        handoff = plan["derivation_authorities"]["handoff_planes_project_mm"]
        self.assertEqual(boxes["central_transport"][2], handoff["negative_central_to_bridge"] - 6.0)
        self.assertEqual(boxes["central_transport"][5], handoff["positive_central_to_bridge"] + 6.0)


if __name__ == "__main__":
    unittest.main()
