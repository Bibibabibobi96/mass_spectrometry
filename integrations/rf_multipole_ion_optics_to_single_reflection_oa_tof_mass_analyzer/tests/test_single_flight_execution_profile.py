from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_execution_profile import (
    ERROR,
    resolve_execution_profile,
)


REPO = Path(__file__).resolve().parents[3]
CONFIGURATION = REPO / (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "config/simion_single_flight.json"
)


class SingleFlightExecutionProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = json.loads(CONFIGURATION.read_text(encoding="utf-8"))

    def test_two_local_overlay_has_two_explicit_disjoint_roles(self) -> None:
        resolved = resolve_execution_profile(
            self.configuration,
            frontend_grid_profile_id="frontend_isotropic_020_accelerator_two_local_z005",
        )
        self.assertTrue(resolved["accelerator_overlay_enabled"])
        self.assertEqual(resolved["accelerator_overlay_layout"], "two_local_v1")

    def test_exact_terminal_aperture_profile_uses_tenth_mm_axial_cells(self) -> None:
        """All requested terminal heights are integral numbers of axial cells."""
        resolved = resolve_execution_profile(
            self.configuration,
            frontend_grid_profile_id=(
                "frontend_acceleration_xy025_z010_accelerator_two_local_xy025_z005"
            ),
        )
        self.assertEqual(resolved["frontend_cell_mm_xyz"]["z"], 0.1)
        self.assertEqual(resolved["frontend_cell_mm_xyz"]["x"], 0.25)
        self.assertEqual(resolved["frontend_cell_mm_xyz"]["y"], 0.25)
        self.assertEqual(
            resolved["coarse_bridge_cell_mm_xyz"],
            {"x": 0.5, "y": 0.5, "z": 0.5},
        )
        self.assertEqual(resolved["accelerator_overlay_layout"], "two_local_v1")
        self.assertEqual(
            [item["region_id"] for item in resolved["accelerator_overlay_specs"]],
            ["entrance", "intermediate2"],
        )
        self.assertEqual(
            resolved["accelerator_overlay_specs"][1]["intermediate_half_span_mm"],
            2.0,
        )

    def test_legacy_whole_overlay_preserves_single_overlay_identity(self) -> None:
        resolved = resolve_execution_profile(
            self.configuration,
            frontend_grid_profile_id="frontend_isotropic_020_accelerator_overlay_z005",
        )
        self.assertEqual(resolved["accelerator_overlay_layout"], "whole_accelerator_v1")
        self.assertEqual(
            resolved["accelerator_overlay_specs"],
            [{"region_id": "whole_accelerator", "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.05}}],
        )

    def test_two_local_overlay_rejects_legacy_single_overlay_numerical_override(self) -> None:
        with self.assertRaisesRegex(ValueError, ERROR):
            resolve_execution_profile(
                self.configuration,
                frontend_grid_profile_id="frontend_isotropic_020_accelerator_two_local_z005",
                numerical_overrides={
                    "accelerator_overlay_cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.025}
                },
            )

    def test_two_local_overlay_rejects_unknown_member(self) -> None:
        configuration = copy.deepcopy(self.configuration)
        profile = next(
            item
            for item in configuration["frontend_grid_profiles"]
            if item["profile_id"] == "frontend_isotropic_020_accelerator_two_local_z005"
        )
        profile["accelerator_overlay"]["illegal"] = 1
        with self.assertRaisesRegex(ValueError, ERROR):
            resolve_execution_profile(
                configuration,
                frontend_grid_profile_id=profile["profile_id"],
            )

    def test_directed_accelerator_corridor_is_a_registered_numerical_policy(self) -> None:
        configuration = copy.deepcopy(self.configuration)
        profile = next(
            item
            for item in configuration["frontend_grid_profiles"]
            if item["profile_id"] == (
                "frontend_acceleration_xy025_z010_accelerator_two_local_xy025_z005_"
                "directed_corridor"
            )
        )
        resolved = resolve_execution_profile(
            configuration, frontend_grid_profile_id=profile["profile_id"]
        )
        self.assertEqual(
            resolved["accelerator_main_domain"],
            profile["accelerator_main_domain"],
        )

    def test_main_only_axis_field_profile_uses_one_mm_coarse_boundary(self) -> None:
        resolved = resolve_execution_profile(
            self.configuration,
            frontend_grid_profile_id=(
                "frontend_acceleration_xy025_z010_coarse100_directed_corridor_"
                "main_only"
            ),
        )
        self.assertEqual(
            resolved["coarse_bridge_cell_mm_xyz"],
            {"x": 1.0, "y": 1.0, "z": 1.0},
        )
        self.assertEqual(
            resolved["frontend_cell_mm_xyz"],
            {"x": 0.25, "y": 0.25, "z": 0.1},
        )
        self.assertFalse(resolved["accelerator_overlay_enabled"])
        self.assertEqual(
            resolved["accelerator_main_domain"]["policy_id"],
            "directed_kinematic_corridor_v1",
        )

    def test_shared_main_local_aperture_profile_has_no_convergence_overlay(self) -> None:
        resolved = resolve_execution_profile(
            self.configuration,
            frontend_grid_profile_id=(
                "frontend_acceleration_xy025_z010_coarse100_shared_main_local_aperture"
            ),
        )
        self.assertEqual(
            resolved["coarse_bridge_cell_mm_xyz"],
            {"x": 1.0, "y": 1.0, "z": 1.0},
        )
        self.assertFalse(resolved["accelerator_overlay_enabled"])
        self.assertEqual(
            resolved["accelerator_main_reference_aperture_mm"],
            {"width": 1.0, "height": 1.0},
        )
        local = resolved["accelerator_entrance_local"]
        self.assertTrue(local["enabled"])
        self.assertEqual(local["iob_mode"], "highest_priority_entrance_local_v1")
        self.assertEqual(
            local["boundary_mode"],
            "accelerator_main_electrode_basis_dirichlet_v1",
        )

    def test_directed_accelerator_corridor_rejects_unknown_or_nonpositive_extent(self) -> None:
        configuration = copy.deepcopy(self.configuration)
        profile = next(
            item
            for item in configuration["frontend_grid_profiles"]
            if item["profile_id"] == "frontend_acceleration_xy025_z010_accelerator_two_local_xy025_z005"
        )
        profile["accelerator_main_domain"] = {
            "policy_id": "directed_kinematic_corridor_v1",
            "exit_axis_positive_extent_mm": 0.0,
            "transverse_half_span_mm": 10.0,
        }
        with self.assertRaisesRegex(ValueError, ERROR):
            resolve_execution_profile(
                configuration, frontend_grid_profile_id=profile["profile_id"]
            )


if __name__ == "__main__":
    unittest.main()
