from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_refinement_plan import (
    derive_local_refinement_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AnalyzerLocalRefinementPlanTest(unittest.TestCase):
    def test_derives_grid_aligned_three_level_patches_from_resolved_geometry(self) -> None:
        plan = derive_local_refinement_plan(CONTRACT)
        self.assertEqual(plan["baseline"]["mesh_mm_per_gu"], [1.0, 1.0, 1.0])
        self.assertEqual(plan["baseline"]["grid_shape"], [181, 641, 721])
        self.assertEqual([item["scale_factor"] for item in plan["profiles"]], [1.0, 0.5, 0.25])
        self.assertEqual(plan["patches"]["mirror_turn_positive"], [-20.0, -147.0, 97.0, 20.0, 463.0, 330.0])
        self.assertEqual(plan["patches"]["central_transport"], [-29.0, -82.0, -105.0, 29.0, 395.0, 102.0])
        self.assertEqual(
            plan["patches"]["stripe_mirror_bridge_positive"],
            [-20.0, -147.0, 42.0, 20.0, 463.0, 165.0],
        )
        self.assertEqual(
            plan["patches"]["stripe_mirror_bridge_negative"],
            [-20.0, -147.0, -165.0, 20.0, 463.0, -42.0],
        )
        self.assertEqual(
            plan["derived_interface_gaps"]["inner_grounded_mirror_to_mirror_B_z_mm"],
            [162.0, 167.0],
        )
        self.assertEqual(plan["handoff_planes_project_mm"], {
            "negative_central_to_bridge": -72.0,
            "positive_central_to_bridge": 72.0,
            "negative_bridge_to_mirror": -131.0,
            "positive_bridge_to_mirror": 131.0,
        })
        self.assertEqual(len(plan["response_voltage_groups"]), 8)
        self.assertEqual(set(plan["fixed_zero_electrode_ids"]), {1, 6, 15, 18, 19, 20})
        self.assertEqual(plan["local_fast_adjust_group_ids"]["mirror_B"], 1)
        self.assertEqual(plan["local_fast_adjust_group_ids"]["prism_2"], 8)
        self.assertEqual(plan["physical_to_local_electrode_id"]["2"], 1)
        self.assertEqual(plan["physical_to_local_electrode_id"]["7"], 1)
        self.assertEqual(plan["physical_to_local_electrode_id"]["18"], 0)
        for profile in plan["profiles"]:
            for role in (
                "mirror_turn", "central_transport", "stripe_mirror_bridge",
                "stripe_mirror_bridge_negative",
            ):
                patch = profile[role]
                self.assertEqual(patch["pa_array_count"], 10)
                self.assertGreater(patch["grid_points_per_array"], 0)
                self.assertGreater(patch["estimated_family_bytes"], 0)
        local_half_bytes = sum(
            plan["profiles"][1][role]["estimated_family_bytes"]
            for role in ("mirror_turn", "central_transport")
        )
        self.assertLess(local_half_bytes, plan["rejected_naive_global_half_mesh"]["estimated_family_bytes"])
        self.assertEqual(plan["qualification"], "planning_only__no_local_pa_built_or_flown")

    def test_rejects_non_decreasing_mesh_levels(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        changed = copy.deepcopy(document)
        changed["simion"]["analyzer_spatial_convergence"]["local_mesh_scale_factors"] = [1, 0.5, 0.5]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                derive_local_refinement_plan(path)

    def test_rejects_missing_boundary_authority(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        changed = copy.deepcopy(document)
        del changed["simion"]["analyzer_spatial_convergence"]["boundary_rule"]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                derive_local_refinement_plan(path)

    def test_rejects_incomplete_electrode_partition(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        changed = copy.deepcopy(document)
        changed["simion"]["analyzer_spatial_convergence"]["response_voltage_groups"]["prism_2"] = [16]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                derive_local_refinement_plan(path)


if __name__ == "__main__":
    unittest.main()
