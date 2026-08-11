from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign import (
    NUMERICS_PATH,
    _assert_only_allowed_changes,
    _overrides,
)


class RadialCompactionCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(
            (PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8")
        )
        cls.config = json.loads(
            (PROJECT_ROOT / "config" / "radial_compaction_campaign.json").read_text(
                encoding="utf-8"
            )
        )

    def test_radius_rows_change_only_the_three_governed_radii(self) -> None:
        for row in self.config["radius_screen"]:
            candidate, _ = compile_design_overrides(self.baseline, _overrides(row))
            _assert_only_allowed_changes(
                self.baseline, candidate, allow_ring_counts=False
            )
            self.assertEqual(candidate["geometry_mm"]["flight_tube_wall"], 10.0)

    def test_smallest_shield_contains_offset_detector(self) -> None:
        smallest = min(
            self.config["radius_screen"],
            key=lambda row: row["shared_shield_inner_radius_mm"],
        )
        convention = self.baseline["coordinate_convention"]
        required = abs(convention["detector_x"]) + self.baseline["geometry_mm"][
            "detector_radius"
        ]
        self.assertGreaterEqual(smallest["shared_shield_inner_radius_mm"], required)

    def test_ring_compensation_changes_only_counts_in_addition_to_radii(self) -> None:
        target_id = self.config["ring_count_compensation"]["target_case_id"]
        target = next(row for row in self.config["radius_screen"] if row["case_id"] == target_id)
        for ring_case in self.config["ring_count_compensation"]["cases"]:
            row = {**target, **ring_case}
            candidate, _ = compile_design_overrides(self.baseline, _overrides(row))
            _assert_only_allowed_changes(
                self.baseline, candidate, allow_ring_counts=True,
                allowed_geometry_keys={
                    "ring_thickness", "shield_bore_z_max", "shield_outer_z_max"
                }
                if "ring_thickness_mm" in row else set(),
            )

    def test_stable_grid_override_is_explicit_and_only_changes_reflectron_axial_cell(self) -> None:
        self.assertEqual(
            self.config["fixed_contract"]["default_reflectron_mesh_mm"],
            {"axial": 0.1, "radial": 1.0},
        )
        grid_cases = [
            row
            for row in self.config["ring_count_compensation"]["cases"]
            if "reflectron_cell_axial_mm" in row
        ]
        self.assertGreaterEqual(len(grid_cases), 1)
        self.assertEqual(
            {row["reflectron_cell_axial_mm"] for row in grid_cases},
            {0.05, 0.1, 0.4},
        )
        source = json.loads(NUMERICS_PATH.read_text(encoding="utf-8"))
        changed = copy.deepcopy(source)
        changed["simion"]["geometry_build"]["reflectron"]["cell_axial_mm"] = 0.4
        source["simion"]["geometry_build"]["reflectron"].pop("cell_axial_mm")
        changed["simion"]["geometry_build"]["reflectron"].pop("cell_axial_mm")
        self.assertEqual(changed, source)

    def test_compensation_ideal_field_targets_are_declared_cases(self) -> None:
        compensation = self.config["ring_count_compensation"]
        case_ids = {row["case_id"] for row in compensation["cases"]}
        self.assertTrue(
            set(compensation["ideal_field_diagnostic_case_ids"]).issubset(case_ids)
        )

    def test_one_millimetre_manufacturing_gap_is_enforced(self) -> None:
        target = next(
            row for row in self.config["radius_screen"] if row["case_id"] == "shield100"
        )
        invalid = {**target, "stage1_count": 7, "stage2_count": 17}
        with self.assertRaisesRegex(ValueError, "stage-2 ring gap"):
            compile_design_overrides(self.baseline, _overrides(invalid))
        valid = {**target, "stage1_count": 7, "stage2_count": 15}
        candidate, _ = compile_design_overrides(self.baseline, _overrides(valid))
        gap = candidate["geometry_mm"]["L_stage2"] / 16 - candidate["geometry_mm"][
            "ring_thickness"
        ]
        self.assertGreaterEqual(gap, 1.0)

    def test_nonradius_change_is_rejected(self) -> None:
        candidate = copy.deepcopy(self.baseline)
        candidate["geometry_mm"]["L_flight"] -= 1.0
        with self.assertRaisesRegex(ValueError, "non-authorized"):
            _assert_only_allowed_changes(
                self.baseline, candidate, allow_ring_counts=False
            )

    def test_builder_supports_component_reuse_without_separate_shield_values(self) -> None:
        builder = (
            PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Copy-ReusablePaSet", builder)
        self.assertIn("ReusableParticleDir", builder)
        self.assertIn("ResumeRefinedReflectron", builder)
        self.assertIn("Assert-CompleteRefinedReflectronSet", builder)
        self.assertIn("'flight_tube_ground'", builder)
        self.assertIn("'reflectron'", builder)
        self.assertNotIn("reflectron_shield_inner_radius", builder)
        self.assertNotIn("reflectron_shield_wall", builder)


if __name__ == "__main__":
    unittest.main()
