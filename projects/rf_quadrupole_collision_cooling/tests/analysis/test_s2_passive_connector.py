from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import validate_s2_passive_connector as module


class S2PassiveConnectorTests(unittest.TestCase):
    def test_contract_inherits_s1_geometry_and_freezes_one_mm_gap(self) -> None:
        contract = module.validate_contract()
        registration = contract["nominal_registration"]
        geometry = contract["passive_connector_geometry"]
        self.assertEqual(registration["connector_gap_mm"], 1.0)
        self.assertEqual(registration["source_exit_center_instrument_mm"][0], -68.8)
        self.assertEqual(registration["target_entry_center_instrument_mm"][0], -67.8)
        self.assertEqual(geometry["upstream_clear_aperture"]["radius_mm"], 3.6)
        self.assertEqual(geometry["downstream_entry_aperture"]["full_width_y_mm"], 1.0)
        self.assertEqual(geometry["downstream_entry_aperture"]["full_height_z_mm"], 0.9)
        self.assertFalse(contract["field_ownership"]["oa_extraction_pulse_included"])
        self.assertTrue(contract["permissions"]["field_solve_allowed"])
        self.assertTrue(contract["permissions"]["particle_runtime_allowed"])
        self.assertFalse(
            contract["no_pulse_field_candidate"]["mesh"]["convergence_claim_allowed"]
        )
        rf = json.loads(
            (module.PROJECT_ROOT / contract["inputs"]["rf_resolved_geometry"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertLess(
            contract["no_pulse_field_candidate"]["rf_off_axis_probe_radius_mm"],
            rf["geometry_mm"]["field_radius_r0"],
        )
        evidence = contract["geometry_build_evidence"]
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["connector_domain_count"], 1)
        self.assertEqual(evidence["port_domain_count"], 1)
        self.assertFalse(evidence["field_solved"])
        dependencies = json.loads(
            (module.PROJECT_ROOT / contract["inputs"]["explicit_dependencies"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {item["provider_project"] for item in dependencies["dependencies"]},
            {"oa_tof"},
        )
        self.assertTrue(
            dependencies["runtime_policy"]["verify_source_and_frozen_sha256_equal"]
        )
        particle_evidence = contract["nominal_particle_evidence"]
        self.assertEqual(particle_evidence["source_particles"], 100)
        self.assertEqual(particle_evidence["oatof_entry_crossings"], 61)
        self.assertEqual(particle_evidence["downstream_entry_wall_losses"], 39)
        self.assertFalse(particle_evidence["s2_stage_passed"])

    def test_contract_rejects_a_gap_that_breaks_the_pose_derivation(self) -> None:
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        contract["nominal_registration"]["connector_gap_mm"] = 2.0
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "connector gap"):
                module.validate_contract(path)

    def test_contract_rejects_disabled_particle_runtime_after_authorization(self) -> None:
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        contract["permissions"]["particle_runtime_allowed"] = False
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "particle candidate"):
                module.validate_contract(path)


if __name__ == "__main__":
    unittest.main()
