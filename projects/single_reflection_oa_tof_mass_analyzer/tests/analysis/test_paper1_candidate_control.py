"""Tests for the detector-blind C3 local-control compiler."""

from __future__ import annotations

import copy
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_candidate_control import (
    CandidateControlRequest,
    compile_local_control_candidates,
)


class Paper1CandidateControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = {
            "role": "oatof_three_zone_simion_candidate_resolved",
            "qualification": "CANDIDATE_ONLY",
            "accelerator_topology": {
                "topology_id": "three_zone_accelerator_ideal_v1",
                "planes_global_z_mm": {"repeller": -30.0, "intermediate1": -20.0, "intermediate2": -10.0, "exit": 0.0},
                "potentials_v": {"repeller": 300.0, "intermediate1": 200.0, "intermediate2": 100.0, "exit": 0.0},
            },
            "reflectron": {"u_r1_v": 1600.0, "f_r2_v_per_mm": 10.0},
        }
        self.request = CandidateControlRequest(
            request_id="j3_grid2_local_v1",
            adjustable_electrodes=("intermediate1", "intermediate2"),
            voltage_direction_v={"repeller": 0.0, "intermediate1": 1.0, "intermediate2": -1.0, "exit": 0.0},
            plane_direction_mm={"intermediate2": 0.0, "exit": 0.0},
            voltage_abs_bounds_v={"repeller": 0.0, "intermediate1": 3.0, "intermediate2": 3.0, "exit": 0.0},
            plane_abs_bounds_mm={"intermediate2": 0.0, "exit": 0.0},
            reflectron_direction={"u_r1_v": 0.5, "f_r2_v_per_mm": 0.01},
            reflectron_abs_bounds={"u_r1_v": 2.0, "f_r2_v_per_mm": 0.04},
        )

    def test_compiles_symmetric_bounded_family_with_identity(self) -> None:
        family = compile_local_control_candidates(self.candidate, self.request)
        self.assertEqual([item["scale"] for item in family["variants"]], [-2.0, -1.0, 0.0, 1.0, 2.0])
        self.assertEqual(family["variants"][2]["accelerator_topology"], self.candidate["accelerator_topology"])
        self.assertEqual(len(family["semantic_sha256"]), 64)
        self.assertTrue(all(item["requires_pa_rebuild"] for item in family["variants"]))
        self.assertEqual(family["variants"][2]["reflectron"], {"u_r1_v": 1600.0, "f_r2_v_per_mm": 10.0})

    def test_rejects_nonphysical_inversion_and_fixed_electrode_motion(self) -> None:
        inverted = copy.deepcopy(self.request)
        object.__setattr__(inverted, "voltage_direction_v", {"repeller": 0.0, "intermediate1": 60.0, "intermediate2": -60.0, "exit": 0.0})
        object.__setattr__(inverted, "voltage_abs_bounds_v", {"repeller": 0.0, "intermediate1": 200.0, "intermediate2": 200.0, "exit": 0.0})
        with self.assertRaisesRegex(ValueError, "inverts"):
            compile_local_control_candidates(self.candidate, inverted)
        fixed = copy.deepcopy(self.request)
        object.__setattr__(fixed, "voltage_direction_v", {"repeller": 1.0, "intermediate1": 1.0, "intermediate2": -1.0, "exit": 0.0})
        with self.assertRaisesRegex(ValueError, "fixed electrode"):
            compile_local_control_candidates(self.candidate, fixed)

    def test_rejects_geometry_topology_change(self) -> None:
        request = copy.deepcopy(self.request)
        object.__setattr__(request, "plane_direction_mm", {"intermediate2": -6.0, "exit": 0.0})
        object.__setattr__(request, "plane_abs_bounds_mm", {"intermediate2": 20.0, "exit": 0.0})
        with self.assertRaisesRegex(ValueError, "event topology"):
            compile_local_control_candidates(self.candidate, request)


if __name__ == "__main__":
    unittest.main()
