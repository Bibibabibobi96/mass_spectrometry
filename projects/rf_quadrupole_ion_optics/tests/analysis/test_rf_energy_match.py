from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


from projects.rf_quadrupole_ion_optics.analysis import validate_rf_energy_match as module


class RfEnergyMatchTests(unittest.TestCase):
    def load_hybrid_mesh_descriptor(self) -> dict:
        return module.load(
            module.PROJECT_ROOT / "config" / "rf_hybrid_mesh_candidate.json"
        )

    def test_repository_contract_is_valid(self) -> None:
        contract = module.validate()
        self.assertEqual(contract["input_candidate"]["kinetic_energy_eV"], 5.0)
        self.assertEqual(
            contract["inputs"]["oatof_science_contract"],
            "../single_reflection_oa_tof_mass_analyzer/config/modes/formal.json",
        )
        self.assertFalse(contract["model_changes"]["velocity_rewrite_at_handoff_allowed"])
        evidence = contract["physical_port_pulse_evidence"]
        self.assertEqual(evidence["predicted_finite_wall_survivors"], 40)
        self.assertEqual(evidence["pre_pulse_accelerator_losses"], 1)
        self.assertEqual(evidence["active_at_pulse"], 39)

    def test_velocity_rewrite_is_rejected(self) -> None:
        contract = module.load(module.CONTRACT_PATH)
        contract["model_changes"]["velocity_rewrite_at_handoff_allowed"] = True
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rewrite"):
                module.validate(path)

    def test_arbitrary_pulse_time_is_rejected(self) -> None:
        contract = module.load(module.CONTRACT_PATH)
        contract["physical_port_pulse_evidence"]["derived_pulse_time_us"] += 0.1
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pulse time"):
                module.validate(path)

    def test_missing_hybrid_mesh_descriptor_is_rejected(self) -> None:
        contract = module.load(module.CONTRACT_PATH)
        with tempfile.TemporaryDirectory() as root:
            contract["inputs"]["hybrid_mesh"] = str(
                Path(root) / "missing_hybrid_mesh_descriptor.json"
            )
            path = Path(root) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                module.validate(path)

    def test_wrong_hybrid_mesh_original_sha_is_rejected(self) -> None:
        descriptor = self.load_hybrid_mesh_descriptor()
        descriptor["historical_identity"]["pre_compaction_repository_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "original contract identity"):
            module.validate_hybrid_mesh_descriptor(descriptor)

    def test_wrong_hybrid_mesh_artifact_basename_is_rejected(self) -> None:
        descriptor = self.load_hybrid_mesh_descriptor()
        descriptor["historical_evidence_pointer"]["contract_basename"] = "other.json"
        with self.assertRaisesRegex(ValueError, "basename"):
            module.validate_hybrid_mesh_descriptor(descriptor)

    def test_hybrid_mesh_authority_flags_must_remain_false(self) -> None:
        for flag in (
            "current_scientific_authority",
            "active_execution_allowed",
            "generation_allowed",
            "promotion_allowed",
        ):
            with self.subTest(flag=flag):
                descriptor = self.load_hybrid_mesh_descriptor()
                descriptor[flag] = True
                with self.assertRaisesRegex(ValueError, flag):
                    module.validate_hybrid_mesh_descriptor(descriptor)

    def test_hybrid_mesh_runtime_authority_path_is_required(self) -> None:
        for runtime_authority in ({}, {"repository_path": "config/other.json"}):
            with self.subTest(runtime_authority=runtime_authority):
                descriptor = self.load_hybrid_mesh_descriptor()
                descriptor["current_runtime_authority"] = runtime_authority
                with self.assertRaisesRegex(ValueError, "runtime authority path"):
                    module.validate_hybrid_mesh_descriptor(descriptor)


if __name__ == "__main__":
    unittest.main()
