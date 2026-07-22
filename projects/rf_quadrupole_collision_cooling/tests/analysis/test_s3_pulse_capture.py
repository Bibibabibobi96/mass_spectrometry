from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import validate_s3_pulse_capture as module


class S3PulseCaptureContractTests(unittest.TestCase):
    def test_repository_contract_passes(self) -> None:
        contract = module.validate_contract()
        self.assertTrue(contract["permissions"]["nominal_particle_runtime_allowed"])
        self.assertFalse(contract["permissions"]["s3_stage_pass_allowed"])
        self.assertEqual(contract["waveform"]["rise_fall_model"], "ideal_finite_step")

    def test_stage_promotion_is_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["claims"]["s3_stage_passed"] = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overclaims qualification"):
                module.validate_contract(path)

    def test_continuous_pre_pulse_field_is_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["waveform"]["pre_pulse_oatof_field_scale"] = 1.0
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite pulse scales"):
                module.validate_contract(path)

    def test_s3_extends_the_shared_s2_geometry_and_clock(self) -> None:
        task = (module.PROJECT_ROOT / "tests" / "comsol" / "solve_s3_pulse_capture.m").read_text(
            encoding="utf-8")
        runner = (module.PROJECT_ROOT / "tests" / "comsol" / "run_s3_pulse_capture.ps1").read_text(
            encoding="utf-8")
        self.assertIn("prepare_s2_joint_field_model", task)
        self.assertNotIn("build_s1_joint_field_candidate", task)
        self.assertIn("ions.instrument_time_us(index)", task)
        self.assertIn("if(t>=", task)
        self.assertIn("directMating = abs(s2.nominal_registration.connector_gap_mm)", task)
        self.assertIn("releaseIndices = find(insidePhysicalAperture)", task)
        self.assertIn("restartDtS = releaseOffset*1e-3/ions.velocity_x_m_s(index)", task)
        self.assertIn("canonical_rf_exit_at_s2_connector.csv", runner)
        self.assertIn("--s2-contract $s2", runner)
        self.assertIn("verify_run_manifest.py", runner)
        self.assertIn("s3_stage_passed = $false", runner)


if __name__ == "__main__":
    unittest.main()
