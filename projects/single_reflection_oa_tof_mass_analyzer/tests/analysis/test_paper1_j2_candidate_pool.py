"""Tests for the detector-blind common J2 real-field candidate pool."""

from __future__ import annotations

import copy
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_j2_candidate_pool import (
    J2CandidatePoolRequest,
    J2CandidateProposal,
    compile_j2_candidate_pool,
)


def _file() -> dict[str, object]:
    return {"path": "evidence.json", "bytes": 1, "sha256": "A" * 64}


def _candidate() -> dict[str, object]:
    return {
        "schema_version": 1,
        "role": "oatof_three_zone_simion_candidate_resolved",
        "project_id": "single_reflection_oa_tof_mass_analyzer",
        "qualification": "CANDIDATE_ONLY",
        "compiler_mode": "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
        "campaign": {"campaign_id": "three_zone_solver_free_funnel_v2", "file": _file()},
        "t5_evidence": {
            "stage_id": "T5", "status": "success", "conclusion": "PRIMARY_THEORY_ONLY_SUPPORTED", "plan_sha256": "B" * 64,
            "receipt": _file(), "report": _file(), "frozen_primary_row_id": "frozen_primary",
            "frozen_branch_root": {"policy": "scaled_parameter_distance_unique_nearest", "reference_fixture_id": "anchor", "accepted_index": 0, "cluster_index": 0, "coordinates": [0.0, 0.0, 0.0], "distance_to_branch_reference": 0.0, "inner": {"eta": 0.5, "u_r1_v": 1600.0, "f_r2_v_per_mm": 10.0}},
        },
        "source_identity": {"authority": "campaign.frozen_source", "campaign_id": "three_zone_solver_free_funnel_v2", "campaign_sha256": "C" * 64, "frozen_source": {"mass_to_charge_th": 524.0, "charge_sign": 1, "center_x_mm": 1.5, "center_velocity_m_per_s": 1000.0, "velocity_slope_m_per_s_per_mm": 1.0, "nominal_energy_per_charge_v": 2000.0}},
        "identities": {"topology_id": "three_zone_accelerator_ideal_v1", "geometry_id": "three_zone_focus_origin_planes_v1", "field_id": "three_zone_piecewise_uniform_ideal_field_v1"},
        "accelerator_topology": {"topology_id": "three_zone_accelerator_ideal_v1", "planes_global_z_mm": {"repeller": -30.0, "intermediate1": -20.0, "intermediate2": -10.0, "exit": 0.0}, "potentials_v": {"repeller": 3000.0, "intermediate1": 2000.0, "intermediate2": 1000.0, "exit": 0.0}},
        "accelerator_physics": {"lengths_mm": {"d1": 10.0, "d2": 10.0, "d3": 10.0}, "fields_v_per_mm": {"e1": 100.0, "e2": 100.0, "e3": 100.0}, "focus_drift_after_exit_mm": 0.0},
        "reflectron": {"u_r1_v": 1600.0, "f_r2_v_per_mm": 10.0},
        "claim_limit": "Candidate-only input.",
    }


def _request() -> J2CandidatePoolRequest:
    zero_v = {"repeller": 0.0, "intermediate1": 0.0, "intermediate2": 0.0, "exit": 0.0}
    zero_p = {"intermediate2": 0.0, "exit": 0.0}
    zero_r = {"u_r1_v": 0.0, "f_r2_v_per_mm": 0.0}
    return J2CandidatePoolRequest(
        request_id="j2_s1_three_zone_pilot", candidate_pool_id="j2_s1_three_zone_pool",
        adjustable_electrodes=("intermediate1", "intermediate2"),
        voltage_abs_bounds_v={"repeller": 0.0, "intermediate1": 50.0, "intermediate2": 50.0, "exit": 0.0},
        plane_abs_bounds_mm={"intermediate2": 1.0, "exit": 1.0},
        reflectron_abs_bounds={"u_r1_v": 20.0, "f_r2_v_per_mm": 1.0},
        proposals=(
            J2CandidateProposal("baseline", zero_v, zero_p, zero_r),
            J2CandidateProposal("shape_a", {"repeller": 0.0, "intermediate1": 20.0, "intermediate2": -10.0, "exit": 0.0}, {"intermediate2": 0.5, "exit": 0.0}, {"u_r1_v": 5.0, "f_r2_v_per_mm": 0.1}),
        ),
    )


class Paper1J2CandidatePoolTests(unittest.TestCase):
    def test_rederives_physics_and_binds_the_common_pool(self) -> None:
        pool = compile_j2_candidate_pool(_candidate(), _request())
        self.assertEqual(pool["candidate_ids"], ["baseline", "shape_a"])
        baseline, shaped = pool["candidates"]
        self.assertEqual(baseline["j2_evidence"]["pool_request_sha256"], pool["request_sha256"])
        self.assertEqual(shaped["compiler_mode"], "J2_REAL_FIELD_CANDIDATE_POOL_V1")
        planes = shaped["accelerator_topology"]["planes_global_z_mm"]
        physics = shaped["accelerator_physics"]
        self.assertAlmostEqual(planes["intermediate2"] - planes["intermediate1"], physics["lengths_mm"]["d2"])
        self.assertAlmostEqual((2020.0 - 990.0) / physics["lengths_mm"]["d2"], physics["fields_v_per_mm"]["e2"])

    def test_rejects_unregistered_or_nonphysical_controls(self) -> None:
        request = _request()
        invalid = copy.deepcopy(request.proposals[1])
        object.__setattr__(invalid, "voltage_offset_v", {"repeller": 1.0, "intermediate1": 20.0, "intermediate2": -10.0, "exit": 0.0})
        object.__setattr__(request, "proposals", (request.proposals[0], invalid))
        with self.assertRaisesRegex(ValueError, "fixed electrode"):
            compile_j2_candidate_pool(_candidate(), request)

        request = _request()
        inverted = copy.deepcopy(request.proposals[1])
        object.__setattr__(inverted, "voltage_offset_v", {"repeller": 0.0, "intermediate1": -2000.0, "intermediate2": 0.0, "exit": 0.0})
        object.__setattr__(request, "proposals", (request.proposals[0], inverted))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            compile_j2_candidate_pool(_candidate(), request)


if __name__ == "__main__":
    unittest.main()
