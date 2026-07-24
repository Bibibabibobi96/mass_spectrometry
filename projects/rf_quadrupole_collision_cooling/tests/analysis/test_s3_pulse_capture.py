from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projects.rf_quadrupole_collision_cooling.analysis import validate_s3_pulse_capture as module


class S3PulseCaptureContractTests(unittest.TestCase):
    def test_repository_contract_passes(self) -> None:
        contract = module.validate_contract()
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["inputs"]["spatial_registration"],
            "config/resolved_rf_to_oatof_s2_spatial_registration.json",
        )
        self.assertEqual(
            contract["identity_contract"]["species_identity_key"],
            ["species_id", "mass_amu", "charge_state"],
        )
        self.assertTrue(contract["permissions"]["nominal_particle_runtime_allowed"])
        self.assertFalse(contract["permissions"]["s3_stage_pass_allowed"])
        self.assertEqual(contract["waveform"]["rise_fall_model"], "ideal_finite_step")

    def test_stage_plan_has_one_public_cumulative_entry(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        plan = module._load(module._relative(contract["inputs"]["stage_plan"]))
        self.assertEqual([item["id"] for item in plan["stages"]], ["S2", "S3"])
        self.assertEqual(
            [item["role"] for item in plan["stages"]],
            ["internal_passive_connector_step", "current_cumulative_entry"],
        )
        self.assertEqual(plan["governance"]["public_entry_count"], 1)
        self.assertFalse(plan["stages"][0]["public_entrypoint"])
        self.assertTrue(plan["stages"][1]["public_entrypoint"])
        self.assertEqual(
            plan["stages"][1]["entrypoint"],
            "tests/cross_solver/run_s3_cumulative_chain.ps1",
        )

    def test_stage_plan_drift_is_rejected_by_the_runtime_validator(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        plan_path = module._relative(contract["inputs"]["stage_plan"])
        original_load = module._load
        plan = original_load(plan_path)
        mutations = []
        changed = copy.deepcopy(plan)
        changed["governance"]["public_entry_count"] = 2
        mutations.append(changed)
        changed = copy.deepcopy(plan)
        changed["stages"][0]["public_entrypoint"] = True
        mutations.append(changed)
        changed = copy.deepcopy(plan)
        changed["stages"][1]["entrypoint"] = "tests/comsol/run_s3_pulse_capture.ps1"
        mutations.append(changed)
        for changed in mutations:
            def load(path: Path, replacement: dict = changed) -> dict:
                return replacement if Path(path).resolve() == plan_path else original_load(path)

            with self.subTest(plan=changed):
                with mock.patch.object(module, "_load", side_effect=load):
                    with self.assertRaisesRegex(ValueError, "entry|S2|S3"):
                        module.validate_contract()

    def test_clock_origin_and_pulse_timing_authority_drift_are_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["source"]["clock_epoch_id"] = "solver_local_time"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "clock epochs"):
                module.validate_contract(path)

        pulse_path = module._relative(contract["inputs"]["pulse_timing_policy"])
        pulse = module._load(pulse_path)
        changed_pulse = copy.deepcopy(pulse)
        changed_pulse["method"] = "fixed_solver_local_time"
        original_load = module._load

        def load(path: Path) -> dict:
            if Path(path).resolve() == pulse_path:
                return changed_pulse
            return original_load(path)

        with mock.patch.object(module, "_load", side_effect=load):
            with self.assertRaisesRegex(ValueError, "pulse timing method"):
                module.validate_contract()

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
        self.assertIn("RF_OATOF_S3_SHARED_JOINT_CONTRACT", task)
        self.assertIn("ions.instrument_time_us(index)", task)
        self.assertIn("if(t>=", task)
        self.assertIn("directMating = abs(s2.nominal_registration.connector_gap_mm)", task)
        self.assertIn("releaseIndices = find(insidePhysicalAperture)", task)
        self.assertIn("restartDtS = releaseOffset*1e-3/ions.velocity_x_m_s(index)", task)
        self.assertIn("canonical_rf_exit_at_s2_connector.csv", runner)
        self.assertIn("--s2-contract $s2", runner)
        self.assertIn("derive_shared_centroid_pulse_time.py", runner)
        self.assertIn("plot_shared_pulse_geometry_snapshot.py", runner)
        self.assertIn("verify_run_manifest.py", runner)
        self.assertIn("s3_stage_passed = $false", runner)


if __name__ == "__main__":
    unittest.main()
